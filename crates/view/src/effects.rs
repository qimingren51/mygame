//! 特效：伤害数字、击杀墨点、击杀闪光、场景道具的光（docs/DESIGN.md 第 9.3 节）。
//!
//! 只消费模拟事件，纯装饰的随机用画面层自己的随机数，不影响模拟。

use bevy::prelude::*;
use bevy::sprite::Anchor;

use lantern_content::Rank;
use lantern_core::Pcg32;
use lantern_sim::{AppState, SimEvent, SimOutbox};

use crate::actors::{ActorFrames, GlowRequests};
use crate::atlas::{AtlasDb, FrameId};
use crate::{layer, to_screen};

/// 同时显示的伤害数字上限（环形复用，最早的被顶掉）
const NUMBER_SLOTS: usize = 96;
const NUMBER_LIFE: f32 = 0.7;
/// 文字按这个字号栅格化，再缩小到世界单位，放大镜头时不糊
const NUMBER_RASTER: f32 = 28.0;
const INK_LIFE: f32 = 2.0;
const INK_CAP: usize = 160;
const FLASH_LIFE: f32 = 0.3;

const NUMBER_COLOR: Color = Color::srgb(0.96, 0.92, 0.87);
const CRIT_COLOR: Color = Color::srgb(1.0, 0.82, 0.48);
const FLASH_LIGHT: Color = Color::srgb(1.0, 0.85, 0.6);

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
}

#[derive(Component)]
pub(crate) struct Ink {
    t: f32,
}

struct Flash {
    pos: Vec2,
    radius: f32,
    t: f32,
}

#[derive(Resource)]
pub(crate) struct Effects {
    rng: Pcg32,
    numbers: Vec<Entity>,
    next_number: usize,
    inks: Vec<Entity>,
    flashes: Vec<Flash>,
    ink_frames: Vec<FrameId>,
    font: Handle<Font>,
}

pub(crate) fn setup_effects(mut commands: Commands, db: Res<AtlasDb>, assets: Res<AssetServer>) {
    commands.insert_resource(Effects {
        rng: Pcg32::new(0x1a7e_2026, 7),
        numbers: Vec::new(),
        next_number: 0,
        inks: Vec::new(),
        flashes: Vec::new(),
        ink_frames: (0..3).filter_map(|i| db.find(&format!("vfx/ink_{i}"))).collect(),
        font: assets.load("fonts/NotoSerifSC-subset.ttf"),
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
                    DamageNumber { t: NUMBER_LIFE, start: Vec2::ZERO, scale: 0.0 },
                    Transform::default(),
                    Visibility::Hidden,
                    DespawnOnExit(AppState::Run),
                ))
                .id()
        })
        .collect();
    fx.next_number = 0;
    fx.inks.clear();
    fx.flashes.clear();
}

pub(crate) fn read_events(
    mut commands: Commands,
    outbox: Res<SimOutbox>,
    db: Res<AtlasDb>,
    mut fx: ResMut<Effects>,
    mut numbers: Query<(&mut Text2d, &mut TextColor, &mut DamageNumber, &mut Visibility)>,
) {
    let fx = &mut *fx;
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { pos, damage, crit, .. } => {
                let Some(&e) = fx.numbers.get(fx.next_number) else { continue };
                fx.next_number = (fx.next_number + 1) % fx.numbers.len().max(1);
                let Ok((mut text, mut color, mut num, mut vis)) = numbers.get_mut(e) else { continue };
                text.0 = format!("{}", damage.round().max(1.0) as u32);
                color.0 = if crit { CRIT_COLOR } else { NUMBER_COLOR };
                let jitter = Vec2::new(fx.rng.range_f32(-6.0, 6.0), fx.rng.range_f32(-3.0, 3.0));
                *num = DamageNumber {
                    t: 0.0,
                    start: to_screen(pos) + jitter,
                    scale: if crit { 13.0 } else { 9.0 } / NUMBER_RASTER,
                };
                *vis = Visibility::Inherited;
            }
            SimEvent::Kill { pos, rank, .. } => {
                let big = matches!(rank, Rank::Elite | Rank::Boss);
                fx.flashes.push(Flash {
                    pos: to_screen(pos),
                    radius: if big { 140.0 } else { 70.0 },
                    t: 0.0,
                });
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
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    mut fx: ResMut<Effects>,
    mut glow: ResMut<GlowRequests>,
    mut numbers: Query<(&mut DamageNumber, &mut Transform, &mut TextColor, &mut Visibility), Without<Ink>>,
    mut inks: Query<(Entity, &mut Ink, &mut Sprite)>,
    props: Query<(&PropLight, &Transform), (Without<DamageNumber>, Without<Ink>)>,
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
        // 先弹起再慢慢上浮，最后淡出
        let pop = 1.0 + 0.35 * (1.0 - (k * 6.0).min(1.0));
        tf.translation = (num.start + Vec2::new(0.0, 6.0 + 14.0 * k)).extend(layer::NUMBERS);
        tf.scale = Vec3::splat(num.scale * pop);
        color.0.set_alpha(if k < 0.6 { 1.0 } else { 1.0 - (k - 0.6) / 0.4 });
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
        let k = 1.0 - f.t / FLASH_LIFE;
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
