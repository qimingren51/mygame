//! 高光时刻的演出（docs/FEEL.md 第 5 节，对应 docs/GAMEPLAY.md 第 14 节）：
//! 共鸣跨阶盖朱砂印、反应初见盖章、连斩题字、夜主登场（上下黑边 + 题字 + 台词）、
//! 夜主伏诛（黑边 + 台词）、天明题字。台词照 docs/LORE.md 第 7 节，写在 enemies.ron 里。
//!
//! 只读模拟事件和画面层的天明进度，不改模拟。动画用现实时间，顿帧和慢镜时照常播放。

use bevy::prelude::*;
use bevy::ui::Val2;

use lantern_content::{BossLines, Content, PlanEvent};
use lantern_sim::{AppState, Director, GameContent, SimEvent, SimOutbox};
use lantern_view::Dawn;
use lantern_view::atlas::AtlasDb;

use crate::describe::{element_color, hex};
use crate::toasts::ToastStack;
use crate::{CINNABAR, Fonts, PAPER, text};

pub(crate) fn register(app: &mut App) {
    app.init_resource::<LastBoss>().add_systems(OnEnter(AppState::Run), reset).add_systems(
        Update,
        (read_events, dawn_title, animate, hold_toasts).chain().run_if(in_state(AppState::Run)),
    );
}

/// 墨色（写在晨光里的大字）
const INK: Color = Color::srgb(0.09, 0.08, 0.07);
const GOLD: Color = Color::srgb(1.0, 0.85, 0.54);
/// 垫在题字后面的墨（#17140F）
const WASH_INK: Color = Color::srgb(0.09, 0.078, 0.059);

#[derive(Clone, Copy)]
enum Anim {
    /// 盖章：从大到小砸下来，回弹一下，停住，淡出
    Stamp { rot: f32 },
    /// 毛笔竖写：从上往下露出来（改高度），停住，淡出
    Brush { full: f32 },
    /// 淡入、停住、淡出
    Fade,
    /// 上下黑边：伸出、停住、收回
    Bar,
    /// 台词的一个字：t 从负数（等前面的字）开始，到 0 时淡入，最后一起淡出
    Ink,
    /// 只是个容器，到时一起消失，不改透明度
    Hold,
}

#[derive(Component)]
struct Moment {
    t: f32,
    life: f32,
    anim: Anim,
}

/// 天明题字（只有一个）。
#[derive(Component)]
struct DawnTitle;

/// 最近登场的夜主（伏诛时说哪一句）。
#[derive(Resource, Default)]
struct LastBoss(Option<u16>);

fn reset(
    mut commands: Commands,
    q: Query<Entity, (With<Moment>, Without<ChildOf>)>,
    mut last: ResMut<LastBoss>,
) {
    for e in &q {
        commands.entity(e).despawn();
    }
    last.0 = None;
}

/// 夜主的台词。kind 不知道时（回放从中途看起）用时间表里的那一个夜主。
fn boss_lines(c: &Content, kind: Option<u16>) -> Option<&BossLines> {
    let kind = kind.map(usize::from).or_else(|| {
        c.run.schedule.iter().find_map(|s| match &s.event {
            PlanEvent::Boss { enemy, .. } => c.enemy_index(enemy),
            _ => None,
        })
    })?;
    c.enemies.get(kind)?.boss.as_ref()?.lines.as_ref()
}

/// 上下黑边，电影那样。
fn spawn_bars(commands: &mut Commands, life: f32) {
    for top in [true, false] {
        let mut node = Node { left: px(0), right: px(0), height: percent(0), ..absolute() };
        if top {
            node.top = px(0);
        } else {
            node.bottom = px(0);
        }
        commands.spawn((
            Moment { t: 0.0, life, anim: Anim::Bar },
            DespawnOnExit(AppState::Run),
            GlobalZIndex(5),
            node,
            BackgroundColor(Color::srgba(0.01, 0.01, 0.02, 0.94)),
            BaseAlpha(0.94),
        ));
    }
}

/// 台词写在下边的黑边里，像字幕：start 秒起一个字一个字地出来，逗号句号处顿一下，end 秒淡完。
fn spawn_line(commands: &mut Commands, fonts: &Fonts, line: &str, start: f32, end: f32) {
    let mut delays = Vec::new();
    let mut d = start;
    for ch in line.chars() {
        delays.push((ch, d));
        d += match ch {
            '，' | '、' => 0.16,
            '。' | '！' | '？' | '…' => 0.34,
            _ => 0.07,
        };
    }
    commands
        .spawn((
            // 字先淡完，容器再走
            Moment { t: 0.0, life: end + 0.2, anim: Anim::Hold },
            DespawnOnExit(AppState::Run),
            GlobalZIndex(6),
            Node {
                left: px(0),
                right: px(0),
                bottom: px(0),
                height: percent(10),
                justify_content: JustifyContent::Center,
                align_items: AlignItems::Center,
                ..absolute()
            },
        ))
        .with_children(|p| {
            for (ch, d) in delays {
                p.spawn((
                    Moment { t: -d, life: end - d, anim: Anim::Ink },
                    text(&fonts.title, 30.0, PAPER.with_alpha(0.0), &ch.to_string()),
                    UiTransform::default(),
                ));
            }
        });
}

/// 底色原本的不透明度（淡入淡出时按它的比例算）。
#[derive(Component)]
struct BaseAlpha(f32);

/// 墨晕：题字后面一笔淡墨（美术的 ui/ink_wash，染墨色），背后是一片火光时字也看得清。数是浓度。
#[derive(Component)]
struct Wash(f32);

/// 夜主登场的题字。它在的时候，上方的提示条先藏起来，别和题字叠在一起。
#[derive(Component)]
struct BossCard;

/// 演出里会跟着淡入淡出的颜色。
type Paint<'w, 's> = Query<
    'w,
    's,
    (
        Option<&'static mut TextColor>,
        Option<&'static mut ImageNode>,
        Option<&'static mut BackgroundColor>,
        Option<&'static mut BorderColor>,
        Option<&'static mut TextShadow>,
        Option<&'static BaseAlpha>,
        Option<&'static Wash>,
    ),
>;

/// 盖章：印章盖在一张宣纸方笺上（印章周围是透明的，直接盖在夜色上看不清），
/// 从大到小砸下来。at 是屏幕百分比位置。
fn spawn_stamp(
    commands: &mut Commands,
    db: &AtlasDb,
    frame: lantern_view::atlas::FrameId,
    size: f32,
    at: (f32, f32),
    rot: f32,
    life: f32,
) {
    commands
        .spawn((
            Moment { t: 0.0, life, anim: Anim::Stamp { rot } },
            DespawnOnExit(AppState::Run),
            GlobalZIndex(6),
            Node {
                left: percent(at.0),
                top: percent(at.1),
                padding: UiRect::all(px(size * 0.08)),
                border_radius: BorderRadius::all(px(size * 0.08)),
                ..absolute()
            },
            BackgroundColor(PAPER.with_alpha(0.88)),
            BaseAlpha(0.88),
            UiTransform::from_scale(Vec2::splat(2.5)),
        ))
        .with_child((Node { width: px(size), height: px(size), ..default() }, db.ui_image(frame)));
}

fn absolute() -> Node {
    Node { position_type: PositionType::Absolute, ..default() }
}

/// 连斩的叫法。
fn combo_name(n: u32) -> String {
    match n {
        100 => "百斩".into(),
        300 => "三百斩".into(),
        500 => "五百斩".into(),
        1000 => "千斩".into(),
        3000 => "三千斩".into(),
        _ => format!("{n}斩"),
    }
}

/// 共鸣印的帧名（按 金木水火土）。
const RESONANCE_SEAL: [&str; 5] =
    ["ui/seal_rui", "ui/seal_sheng", "ui/seal_ning", "ui/seal_fen", "ui/seal_gu"];

fn read_events(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    db: Res<AtlasDb>,
    outbox: Res<SimOutbox>,
    director: Option<Res<Director>>,
    mut last: ResMut<LastBoss>,
) {
    let c = &content.0;
    for ev in &outbox.0 {
        match *ev {
            // 共鸣跨阶：朱砂印盖在屏幕上
            SimEvent::Resonance { element, tier } => {
                let Some(frame) = db.find(RESONANCE_SEAL[element as usize]) else { continue };
                let size = 112.0 + 16.0 * tier as f32;
                spawn_stamp(&mut commands, &db, frame, size, (64.0, 24.0), -0.12, 2.0);
            }
            // 反应初见：盖那种反应的方印（美术图集里没有时写名字）
            SimEvent::Reaction { kind, first: true, .. } => {
                let r = &c.elements.reactions[kind as usize];
                if let Some(frame) = db.find(&format!("ui/seal_react_{}", r.id)) {
                    spawn_stamp(&mut commands, &db, frame, 140.0, (60.0, 22.0), 0.1, 2.4);
                    continue;
                }
                commands
                    .spawn((
                        Moment { t: 0.0, life: 2.4, anim: Anim::Stamp { rot: 0.1 } },
                        DespawnOnExit(AppState::Run),
                        GlobalZIndex(6),
                        Node {
                            left: percent(60),
                            top: percent(24),
                            padding: UiRect::axes(px(18), px(6)),
                            border: UiRect::all(px(5)),
                            border_radius: BorderRadius::all(px(8)),
                            ..absolute()
                        },
                        BorderColor::all(CINNABAR),
                        BackgroundColor(PAPER.with_alpha(0.9)),
                        BaseAlpha(0.9),
                        UiTransform::from_scale(Vec2::splat(2.5)),
                    ))
                    .with_children(|p| {
                        p.spawn(text(&fonts.title, 64.0, CINNABAR, &r.name));
                        p.spawn(text(&fonts.body, 14.0, element_color(c, r.b), "初见"));
                    });
            }
            // 连斩：屏幕左边竖着写出来
            SimEvent::Combo { count } if c.run.combo.milestones.contains(&count) => {
                let name = combo_name(count);
                let n = name.chars().count() as f32;
                let size = if count >= 1000 { 96.0 } else { 80.0 };
                commands
                    .spawn((
                        Moment { t: 0.0, life: 2.6, anim: Anim::Brush { full: n * size * 1.05 } },
                        DespawnOnExit(AppState::Run),
                        GlobalZIndex(6),
                        Node {
                            left: percent(5),
                            top: percent(18),
                            height: px(0),
                            flex_direction: FlexDirection::Column,
                            align_items: AlignItems::Center,
                            overflow: Overflow::clip(),
                            ..absolute()
                        },
                    ))
                    .with_children(|p| {
                        for ch in name.chars() {
                            p.spawn((
                                text(&fonts.title, size, GOLD, &ch.to_string()),
                                TextShadow { offset: Vec2::new(3.0, 3.0), color: INK.with_alpha(0.85) },
                                Node { height: px(size * 1.05), ..default() },
                            ));
                        }
                    });
            }
            // 夜主登场：上下黑边，正中题字，下边黑边里说一句话
            SimEvent::BossArrived { kind } => {
                let e = &c.enemies[kind as usize];
                last.0 = Some(kind);
                // 无尽夜不天明，夜主一次次回来；题字照 docs/LORE.md 第 7 节。
                // arrivals 在夜主生成那一刻已经加过 1
                let endless = director.as_ref().and_then(|d| d.endless);
                let again = endless.is_some_and(|n| n.arrivals > 1);
                let sub = match endless {
                    None => "击败它，迎来天明",
                    Some(_) if again => "它回来了，梦又深了一层",
                    Some(_) => "击败它，往深处走",
                };
                let line = boss_lines(c, Some(kind)).map(|l| if again { &l.again } else { &l.arrive });
                spawn_bars(&mut commands, if line.is_some() { 4.3 } else { 3.8 });
                if let Some(line) = line {
                    spawn_line(&mut commands, &fonts, line, 0.7, 3.9);
                }
                // 名字写成“夜主 · 九尾”：前半是称号，后半写成大字
                let (title, name) = match e.name.split_once('·') {
                    Some((a, b)) => (a.trim().to_string(), b.trim().to_string()),
                    None => (e.title.clone().unwrap_or_else(|| "夜主".into()), e.name.clone()),
                };
                commands
                    .spawn((
                        Moment { t: 0.0, life: 3.8, anim: Anim::Fade },
                        BossCard,
                        DespawnOnExit(AppState::Run),
                        GlobalZIndex(6),
                        Node {
                            left: px(0),
                            right: px(0),
                            top: percent(13),
                            flex_direction: FlexDirection::Column,
                            align_items: AlignItems::Center,
                            ..absolute()
                        },
                        UiTransform::default(),
                    ))
                    .with_children(|p| {
                        // 一笔横的淡墨：中间一段浓淡均匀，正好垫字；按原比例放进框里
                        if let Some(f) = db.find("ui/ink_wash") {
                            let mut img = db.ui_image(f);
                            img.color = WASH_INK.with_alpha(0.0);
                            p.spawn((
                                Node {
                                    left: percent(16),
                                    right: percent(16),
                                    top: px(-40),
                                    bottom: px(-30),
                                    ..absolute()
                                },
                                Wash(0.8),
                                img,
                            ));
                        }
                        let shadow =
                            TextShadow { offset: Vec2::new(3.0, 3.0), color: Color::BLACK.with_alpha(0.85) };
                        p.spawn((text(&fonts.title, 36.0, hex(&e.eye), &title), shadow));
                        p.spawn((text(&fonts.title, 112.0, PAPER, &name), shadow));
                        p.spawn((text(&fonts.body, 22.0, PAPER, sub), shadow));
                    });
            }
            // 夜主伏诛：慢镜里黑边再合上，它说最后一句；天明在黑边之间亮起来，结算浮现前收走
            SimEvent::BossDefeated { dawn: true, .. } => {
                let Some(lines) = boss_lines(c, last.0) else { continue };
                spawn_bars(&mut commands, 4.4);
                spawn_line(&mut commands, &fonts, &lines.defeat, 0.45, 4.0);
            }
            _ => {}
        }
    }
}

/// 天明：夜色褪到三成时，正中慢慢写出“天明”。
fn dawn_title(
    mut commands: Commands,
    fonts: Res<Fonts>,
    dawn: Res<Dawn>,
    q: Query<Entity, With<DawnTitle>>,
    mut shown: Local<bool>,
) {
    if dawn.t.is_none() {
        *shown = false;
        return;
    }
    if dawn.progress() < 0.25 || !q.is_empty() || *shown {
        return;
    }
    *shown = true;
    commands
        .spawn((
            DawnTitle,
            // 结算浮现前后淡出
            Moment { t: 0.0, life: 3.6, anim: Anim::Fade },
            DespawnOnExit(AppState::Run),
            GlobalZIndex(6),
            UiTransform::default(),
            Node {
                left: px(0),
                right: px(0),
                top: percent(10),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                row_gap: px(2),
                ..absolute()
            },
        ))
        .with_children(|p| {
            p.spawn(text(&fonts.title, 36.0, CINNABAR, "夜主伏诛"));
            p.spawn(text(&fonts.title, 150.0, INK, "天明"));
        });
}

fn ease_out_back(x: f32) -> f32 {
    let c1 = 1.70158;
    let c3 = c1 + 1.0;
    1.0 + c3 * (x - 1.0).powi(3) + c1 * (x - 1.0).powi(2)
}

/// 夜主题字在的时候、天明以后，藏起上方的提示条（提示照常计时，藏着的那几秒就错过了）。
/// 天明时提示条自己也会清空，但击杀夜主那一下常常同时充满燃灯，“燃灯已满”排在伏诛前面，清不掉。
fn hold_toasts(
    cards: Query<(), With<BossCard>>,
    dawn: Res<Dawn>,
    mut stack: Query<&mut Visibility, With<ToastStack>>,
) {
    let hide = !cards.is_empty() || dawn.t.is_some();
    let want = if hide { Visibility::Hidden } else { Visibility::Inherited };
    for mut v in &mut stack {
        v.set_if_neq(want);
    }
}

/// 推进所有演出，按各自的方式改大小、透明度。
fn animate(
    mut commands: Commands,
    time: Res<Time<Real>>,
    mut q: Query<(Entity, &mut Moment, &mut Node, Option<&mut UiTransform>)>,
    children: Query<&Children>,
    mut colors: Paint,
) {
    let dt = time.delta_secs().min(0.1);
    for (e, mut m, mut node, tf) in &mut q {
        m.t += dt;
        if m.t >= m.life {
            commands.entity(e).despawn();
            continue;
        }
        let left = m.life - m.t;
        let alpha = match m.anim {
            Anim::Hold => continue,
            Anim::Ink => {
                let k = (m.t / 0.22).clamp(0.0, 1.0);
                if let Some(mut tf) = tf {
                    tf.translation = Val2::px(0.0, 6.0 * (1.0 - k) * (1.0 - k));
                }
                k * (left / 0.6).min(1.0)
            }
            Anim::Stamp { rot } => {
                // 0.12 秒砸下，回弹，停住，最后 0.4 秒淡出
                let k = (m.t / 0.12).min(1.0);
                let s = if m.t < 0.12 {
                    2.5 - 1.5 * k * k
                } else {
                    1.0 + 0.08 * (-(m.t - 0.12) * 14.0).exp() * ((m.t - 0.12) * 40.0).cos()
                };
                if let Some(mut tf) = tf {
                    tf.scale = Vec2::splat(s);
                    tf.rotation = Rot2::radians(rot * (0.4 + 0.6 * k));
                }
                (m.t / 0.08).min(1.0) * (left / 0.4).min(1.0)
            }
            Anim::Brush { full } => {
                let k = (m.t / 0.45).min(1.0);
                node.height = px(full * (1.0 - (1.0 - k).powi(2)));
                (left / 0.5).min(1.0)
            }
            Anim::Fade => {
                if let Some(mut tf) = tf {
                    tf.translation = Val2::px(0.0, 12.0 * (1.0 - ease_out_back((m.t / 0.6).min(1.0))));
                }
                (m.t / 0.6).min(1.0) * (left / 0.8).min(1.0)
            }
            Anim::Bar => {
                let k = (m.t / 0.4).min(1.0) * (left / 0.5).min(1.0);
                node.height = percent(10.0 * (1.0 - (1.0 - k).powi(3)));
                1.0
            }
        };
        set_alpha(e, alpha, &children, &mut colors);
    }
}

/// 把整棵子树的颜色都乘上同一个透明度（按各自的原色比例保存在 alpha 里不现实，直接覆盖）。
fn set_alpha(e: Entity, a: f32, children: &Query<&Children>, colors: &mut Paint) {
    if let Ok((tc, img, bg, border, shadow, base, wash)) = colors.get_mut(e) {
        if let Some(mut tc) = tc {
            tc.0.set_alpha(a);
        }
        if let Some(mut img) = img {
            img.color.set_alpha(wash.map_or(1.0, |w| w.0) * a);
        }
        // 每个节点都自带透明的底色和边框，只改有底子（标了 BaseAlpha）的，否则会变成黑块
        if let Some(base) = base {
            if let Some(mut bg) = bg {
                // 底色本来就半透明：按原来的比例
                bg.0.set_alpha(base.0 * a);
            }
            if let Some(mut border) = border {
                border.set_all(CINNABAR.with_alpha(a));
            }
        }
        if let Some(mut shadow) = shadow {
            shadow.color.set_alpha(0.85 * a);
        }
    }
    if let Ok(kids) = children.get(e) {
        for &k in kids {
            set_alpha(k, a, children, colors);
        }
    }
}
