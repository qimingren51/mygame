//! 特效：伤害数字、击杀墨点、击杀闪光、场景道具的光（docs/DESIGN.md 第 9.3 节）。
//!
//! 只消费模拟事件，纯装饰的随机用画面层自己的随机数，不影响模拟。

use bevy::prelude::*;
use bevy::sprite::Anchor;
use bevy::text::FontSource;

use lantern_content::Rank;
use lantern_core::Pcg32;
use lantern_sim::{AppState, SimEvent, SimOutbox};

use crate::actors::{ActorFrames, GlowRequests};
use crate::atlas::{AtlasDb, FrameId};
use crate::feedback::{Feedback, Priority, eviction};
use crate::{layer, to_screen};

/// 同时显示的伤害数字上限（环形复用，最早的被顶掉）
const NUMBER_SLOTS: usize = 96;
const CRIT_SLOTS: usize = 24;
const FLASH_CAP: usize = 24;
const NUMBER_LIFE: f32 = 0.7;
/// 文字按这个字号栅格化，再缩小到世界单位，放大镜头时不糊
const NUMBER_RASTER: f32 = 28.0;
const INK_LIFE: f32 = 2.0;
const INK_CAP: usize = 160;
const FLASH_LIFE: f32 = 0.3;

const NUMBER_COLOR: Color = Color::srgb(0.96, 0.92, 0.87);
const CRIT_COLOR: Color = Color::srgb(1.0, 0.82, 0.48);
/// 五行反应的伤害数字
const REACT_COLOR: Color = Color::srgb(0.62, 0.92, 0.84);
const FLASH_LIGHT: Color = Color::srgb(1.0, 0.85, 0.6);

/// 五行给伤害数字上的颜色（和 `elements.ron` 一致）。
fn element_tint(e: lantern_content::Element) -> Color {
    use lantern_content::Element::*;
    match e {
        Metal => Color::srgb(0.91, 0.85, 0.65),
        Wood => Color::srgb(0.44, 0.84, 0.63),
        Water => Color::srgb(0.44, 0.72, 1.0),
        Fire => Color::srgb(1.0, 0.54, 0.24),
        Earth => Color::srgb(0.79, 0.57, 0.35),
    }
}

/// 场景道具上的光（石灯笼的灯火）。offset 是相对道具脚底的世界坐标（y 向上）。
#[derive(Component, Clone, Copy)]
pub(crate) struct PropLight {
    pub offset: Vec2,
    pub color: Color,
    pub radius: f32,
    /// 道具的自发光帧（灯窗）
    pub emit: Option<FrameId>,
}

#[derive(Component)]
pub(crate) struct DamageNumber {
    t: f32,
    start: Vec2,
    scale: f32,
    crit: bool,
}

#[derive(Component)]
pub(crate) struct Ink {
    t: f32,
}

struct Flash {
    priority: Priority,
    pos: Vec2,
    radius: f32,
    t: f32,
}

#[derive(Resource)]
pub(crate) struct Effects {
    rng: Pcg32,
    numbers: Vec<Entity>,
    next_number: usize,
    next_crit: usize,
    inks: Vec<Entity>,
    flashes: Vec<Flash>,
    ink_frames: Vec<FrameId>,
    font: Handle<Font>,
    /// 暴击用毛笔字（马善政）
    brush: Handle<Font>,
    /// 反应名：在反应发生的地方飘出来的毛笔字（环形复用）
    words: Vec<Entity>,
    next_word: usize,
}

/// 同时飘着的反应名上限
const WORD_SLOTS: usize = 12;
const WORD_LIFE: f32 = 1.0;

#[derive(Component)]
pub(crate) struct FloatWord {
    t: f32,
    start: Vec2,
}

pub(crate) fn setup_effects(mut commands: Commands, db: Res<AtlasDb>, assets: Res<AssetServer>) {
    commands.insert_resource(Effects {
        rng: Pcg32::new(0x1a7e_2026, 7),
        numbers: Vec::new(),
        next_number: 0,
        next_crit: 0,
        inks: Vec::new(),
        flashes: Vec::new(),
        ink_frames: (0..3).filter_map(|i| db.find(&format!("vfx/ink_{i}"))).collect(),
        font: assets.load("fonts/NotoSerifSC-subset.ttf"),
        brush: assets.load("fonts/MaShanZheng-subset.ttf"),
        words: Vec::new(),
        next_word: 0,
    });
}

/// 开局时建好伤害数字的环形池。
pub(crate) fn spawn_number_pool(mut commands: Commands, mut fx: ResMut<Effects>) {
    let font = fx.font.clone();
    fx.numbers = (0..NUMBER_SLOTS)
        .map(|_| {
            commands
                .spawn((
                    Text2d::new(""),
                    TextFont::from(font.clone()).with_font_size(NUMBER_RASTER),
                    TextColor(NUMBER_COLOR),
                    Anchor::CENTER,
                    DamageNumber { t: NUMBER_LIFE, start: Vec2::ZERO, scale: 0.0, crit: false },
                    Transform::default(),
                    Visibility::Hidden,
                    DespawnOnExit(AppState::Run),
                ))
                .id()
        })
        .collect();
    fx.next_number = 0;
    fx.next_crit = 0;
    let brush = fx.brush.clone();
    fx.words = (0..WORD_SLOTS)
        .map(|_| {
            commands
                .spawn((
                    Text2d::new(""),
                    TextFont::from(brush.clone()).with_font_size(NUMBER_RASTER * 1.4),
                    TextColor(NUMBER_COLOR),
                    bevy::sprite::Text2dShadow {
                        offset: Vec2::new(2.0, -2.0),
                        color: Color::BLACK.with_alpha(0.7),
                    },
                    Anchor::CENTER,
                    FloatWord { t: WORD_LIFE, start: Vec2::ZERO },
                    Transform::default(),
                    Visibility::Hidden,
                    DespawnOnExit(AppState::Run),
                ))
                .id()
        })
        .collect();
    fx.next_word = 0;
    fx.inks.clear();
    fx.flashes.clear();
}

pub(crate) fn read_events(
    mut commands: Commands,
    content: Res<lantern_sim::GameContent>,
    outbox: Res<SimOutbox>,
    feedback: Res<Feedback>,
    db: Res<AtlasDb>,
    mut fx: ResMut<Effects>,
    mut numbers: Query<(&mut Text2d, &mut TextFont, &mut TextColor, &mut DamageNumber, &mut Visibility)>,
    mut words: Query<(&mut Text2d, &mut TextColor, &mut FloatWord, &mut Visibility), Without<DamageNumber>>,
) {
    let fx = &mut *fx;
    for &index in &feedback.selected {
        let ev = &outbox.0[index];
        match *ev {
            SimEvent::Hit { pos, damage, crit, kind, element, .. } => {
                // 暴击保留独立槽位，后续普通命中不能覆盖刚盖下的金色大字。
                let slot = if crit {
                    let slot = NUMBER_SLOTS - CRIT_SLOTS + fx.next_crit;
                    fx.next_crit = (fx.next_crit + 1) % CRIT_SLOTS;
                    slot
                } else {
                    let slot = fx.next_number;
                    fx.next_number = (fx.next_number + 1) % (NUMBER_SLOTS - CRIT_SLOTS);
                    slot
                };
                let Some(&e) = fx.numbers.get(slot) else { continue };
                let Ok((mut text, mut font, mut color, mut num, mut vis)) = numbers.get_mut(e) else {
                    continue;
                };
                text.0 = format!("{}", damage.round().max(1.0) as u32);
                // 暴击：金色毛笔大字；其余按五行淡淡上色
                let want = if crit { &fx.brush } else { &fx.font };
                if !matches!(&font.font, FontSource::Handle(h) if h == want) {
                    font.font = FontSource::Handle(want.clone());
                }
                color.0 = if crit {
                    CRIT_COLOR
                } else if kind == lantern_sim::HitKind::Reaction {
                    REACT_COLOR
                } else if let Some(el) = element {
                    NUMBER_COLOR.mix(&element_tint(el), 0.5)
                } else {
                    NUMBER_COLOR
                };
                let jitter = Vec2::new(fx.rng.range_f32(-6.0, 6.0), fx.rng.range_f32(-3.0, 3.0));
                // 越大的数字字越大一点，暴击再大一圈
                let big = (damage.max(1.0).log10() * 1.2).min(4.0);
                *num = DamageNumber {
                    t: 0.0,
                    start: to_screen(pos) + jitter,
                    scale: if crit { 15.0 + big * 1.5 } else { 8.0 + big } / NUMBER_RASTER,
                    crit,
                };
                *vis = Visibility::Inherited;
            }
            // 反应名：在发生的地方飘出毛笔小字（第一次发生由界面盖章）
            SimEvent::Reaction { kind, pos, first: false, label: true } => {
                let Some(&e) = fx.words.get(fx.next_word) else { continue };
                fx.next_word = (fx.next_word + 1) % fx.words.len().max(1);
                let Ok((mut text, mut color, mut w, mut vis)) = words.get_mut(e) else { continue };
                let r = &content.0.elements.reactions[kind as usize];
                text.0.clone_from(&r.name);
                color.0 = element_tint(r.b).mix(&NUMBER_COLOR, 0.25);
                *w = FloatWord { t: 0.0, start: to_screen(pos) + Vec2::new(0.0, 18.0) };
                *vis = Visibility::Inherited;
            }
            SimEvent::Kill { pos, rank, .. } => {
                let big = matches!(rank, Rank::Elite | Rank::Boss);
                let priority = Priority::of(ev);
                let limit = if big { FLASH_CAP } else { FLASH_CAP - 4 };
                if fx.flashes.len() >= limit
                    && let Some(index) = eviction(&fx.flashes, priority, |f| f.priority)
                {
                    fx.flashes.remove(index);
                }
                if fx.flashes.len() < limit {
                    fx.flashes.push(Flash {
                        priority,
                        pos: to_screen(pos),
                        radius: if big { 140.0 } else { 48.0 },
                        t: 0.0,
                    });
                }
                if fx.ink_frames.is_empty() {
                    continue;
                }
                let frame = fx.ink_frames[fx.rng.below(fx.ink_frames.len() as u32) as usize];
                let (mut sprite, anchor) = db.sprite(frame);
                let scale = fx.rng.range_f32(0.8, 1.2) * if big { 2.0 } else { 1.0 };
                sprite.custom_size = Some(db.frame(frame).size * scale);
                sprite.flip_x = fx.rng.chance(0.5);
                let s = to_screen(pos);
                let ink = commands
                    .spawn((
                        Ink { t: 0.0 },
                        sprite,
                        anchor,
                        Transform::from_xyz(s.x, s.y, layer::GROUND + 0.95).with_rotation(
                            Quat::from_rotation_z(fx.rng.range_f32(0.0, std::f32::consts::TAU)),
                        ),
                        DespawnOnExit(AppState::Run),
                    ))
                    .id();
                fx.inks.push(ink);
                if fx.inks.len() > INK_CAP {
                    let old = fx.inks.remove(0);
                    commands.entity(old).despawn();
                }
            }
            _ => {}
        }
    }
}

/// 伤害数字上浮淡出、墨点淡出、闪光衰减；场景道具的光也在这里加入发光请求。
pub(crate) fn update_effects(
    mut commands: Commands,
    time: Res<Time>,
    feedback: Res<Feedback>,
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    mut fx: ResMut<Effects>,
    mut glow: ResMut<GlowRequests>,
    mut numbers: Query<(&mut DamageNumber, &mut Transform, &mut TextColor, &mut Visibility), Without<Ink>>,
    mut inks: Query<(Entity, &mut Ink, &mut Sprite)>,
    mut words: Query<
        (&mut FloatWord, &mut Transform, &mut TextColor, &mut Visibility),
        (Without<DamageNumber>, Without<Ink>),
    >,
    props: Query<(&PropLight, &Transform), (Without<DamageNumber>, Without<Ink>, Without<FloatWord>)>,
) {
    let dt = time.delta_secs();
    for (mut num, mut tf, mut color, mut vis) in &mut numbers {
        if *vis == Visibility::Hidden {
            continue;
        }
        num.t += dt;
        if num.t >= NUMBER_LIFE {
            *vis = Visibility::Hidden;
            continue;
        }
        let k = num.t / NUMBER_LIFE;
        // 先弹起再慢慢上浮，最后淡出；暴击像盖章一样从大砸到小，略微歪一点
        let (pop, rise) = if num.crit {
            let s = (num.t / 0.09).min(1.0);
            (1.0 + 1.1 * (1.0 - s) * (1.0 - s), 4.0 + 8.0 * k)
        } else {
            (1.0 + 0.35 * (1.0 - (k * 6.0).min(1.0)), 6.0 + 14.0 * k)
        };
        tf.translation =
            (num.start + Vec2::new(0.0, rise)).extend(layer::NUMBERS + if num.crit { 1.0 } else { 0.0 });
        tf.scale = Vec3::splat(num.scale * pop);
        tf.rotation = if num.crit { Quat::from_rotation_z(-0.08) } else { Quat::IDENTITY };
        let priority = if num.crit { Priority::Critical } else { Priority::Normal };
        color
            .0
            .set_alpha((if k < 0.6 { 1.0 } else { 1.0 - (k - 0.6) / 0.4 }) * feedback.visibility(priority));
    }
    for (mut w, mut tf, mut color, mut vis) in &mut words {
        if *vis == Visibility::Hidden {
            continue;
        }
        w.t += dt;
        if w.t >= WORD_LIFE {
            *vis = Visibility::Hidden;
            continue;
        }
        let k = w.t / WORD_LIFE;
        let pop = 1.0 + 0.6 * (1.0 - (w.t / 0.12).min(1.0)).powi(2);
        tf.translation = (w.start + Vec2::new(0.0, 16.0 * k)).extend(layer::NUMBERS + 2.0);
        tf.scale = Vec3::splat(11.0 / NUMBER_RASTER * pop);
        color.0.set_alpha(
            (if k < 0.65 { 1.0 } else { 1.0 - (k - 0.65) / 0.35 }) * feedback.visibility(Priority::Normal),
        );
    }
    for (e, mut ink, mut sprite) in &mut inks {
        ink.t += dt;
        if ink.t >= INK_LIFE {
            commands.entity(e).despawn();
            fx.inks.retain(|&x| x != e);
            continue;
        }
        sprite.color.set_alpha(0.75 * (1.0 - ink.t / INK_LIFE));
    }
    fx.flashes.retain_mut(|f| {
        f.t += dt;
        f.t < FLASH_LIFE
    });
    for f in &fx.flashes {
        let k = (1.0 - f.t / FLASH_LIFE)
            * feedback.visibility(f.priority)
            * if f.priority == Priority::Normal { 0.35 } else { 0.8 };
        glow.light(&frames, &db, f.pos, (FLASH_LIGHT.with_alpha(k), f.radius));
    }
    for (prop, tf) in &props {
        let base = tf.translation.truncate();
        glow.light(&frames, &db, base + prop.offset, (prop.color, prop.radius));
        if let Some(emit) = prop.emit {
            glow.emit(emit, base, false, Color::WHITE);
        }
    }
}
