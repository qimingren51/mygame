//! 高光时刻的演出（docs/FEEL.md 第 5 节，对应 docs/GAMEPLAY.md 第 14 节）：
//! 共鸣跨阶盖朱砂印、反应初见盖章、连斩题字、夜主登场（上下黑边 + 题字）、天明题字。
//!
//! 只读模拟事件和画面层的天明进度，不改模拟。动画用现实时间，顿帧和慢镜时照常播放。

use bevy::prelude::*;
use bevy::ui::Val2;

use lantern_sim::{AppState, GameContent, SimEvent, SimOutbox};
use lantern_view::Dawn;
use lantern_view::atlas::AtlasDb;

use crate::describe::{element_color, hex};
use crate::{CINNABAR, Fonts, PAPER, text};

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Run), reset)
        .add_systems(Update, (read_events, dawn_title, animate).chain().run_if(in_state(AppState::Run)));
}

/// 墨色（写在晨光里的大字）
const INK: Color = Color::srgb(0.09, 0.08, 0.07);
const GOLD: Color = Color::srgb(1.0, 0.85, 0.54);

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

fn reset(mut commands: Commands, q: Query<Entity, With<Moment>>) {
    for e in &q {
        commands.entity(e).despawn();
    }
}

/// 底色原本的不透明度（淡入淡出时按它的比例算）。
#[derive(Component)]
struct BaseAlpha(f32);

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
            // 夜主登场：上下黑边，正中题字
            SimEvent::BossArrived { kind } => {
                let e = &c.enemies[kind as usize];
                for top in [true, false] {
                    let mut node = Node { left: px(0), right: px(0), height: percent(0), ..absolute() };
                    if top {
                        node.top = px(0);
                    } else {
                        node.bottom = px(0);
                    }
                    commands.spawn((
                        Moment { t: 0.0, life: 3.8, anim: Anim::Bar },
                        DespawnOnExit(AppState::Run),
                        GlobalZIndex(5),
                        node,
                        BackgroundColor(Color::srgba(0.01, 0.01, 0.02, 0.94)),
                        BaseAlpha(0.94),
                    ));
                }
                // 名字写成“夜主 · 九尾”：前半是称号，后半写成大字
                let (title, name) = match e.name.split_once('·') {
                    Some((a, b)) => (a.trim().to_string(), b.trim().to_string()),
                    None => (e.title.clone().unwrap_or_else(|| "夜主".into()), e.name.clone()),
                };
                commands
                    .spawn((
                        Moment { t: 0.0, life: 3.8, anim: Anim::Fade },
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
                        let shadow =
                            TextShadow { offset: Vec2::new(3.0, 3.0), color: Color::BLACK.with_alpha(0.85) };
                        p.spawn((text(&fonts.title, 36.0, hex(&e.eye), &title), shadow));
                        p.spawn((text(&fonts.title, 112.0, PAPER, &name), shadow));
                        p.spawn((text(&fonts.body, 22.0, PAPER, "击败它，迎来天明"), shadow));
                    });
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

/// 推进所有演出，按各自的方式改大小、透明度。
fn animate(
    mut commands: Commands,
    time: Res<Time<Real>>,
    mut q: Query<(Entity, &mut Moment, &mut Node, Option<&mut UiTransform>)>,
    children: Query<&Children>,
    mut colors: Query<(
        Option<&mut TextColor>,
        Option<&mut ImageNode>,
        Option<&mut BackgroundColor>,
        Option<&mut BorderColor>,
        Option<&mut TextShadow>,
        Option<&BaseAlpha>,
    )>,
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
fn set_alpha(
    e: Entity,
    a: f32,
    children: &Query<&Children>,
    colors: &mut Query<(
        Option<&mut TextColor>,
        Option<&mut ImageNode>,
        Option<&mut BackgroundColor>,
        Option<&mut BorderColor>,
        Option<&mut TextShadow>,
        Option<&BaseAlpha>,
    )>,
) {
    if let Ok((tc, img, bg, border, shadow, base)) = colors.get_mut(e) {
        if let Some(mut tc) = tc {
            tc.0.set_alpha(a);
        }
        if let Some(mut img) = img {
            img.color.set_alpha(a);
        }
        if let Some(mut bg) = bg {
            // 底色本来就半透明：按原来的比例
            bg.0.set_alpha(base.map_or(1.0, |b| b.0) * a);
        }
        if let Some(mut border) = border {
            border.set_all(CINNABAR.with_alpha(a));
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
