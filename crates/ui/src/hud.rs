//! 游戏中的信息栏：用时、击杀、等级与经验条、生命条、操作提示。

use bevy::prelude::*;

use lantern_core::step::TICK_HZ;
use lantern_sim::{AppState, GameContent, Health, Player, Progress, RunSetup, Tick};

use crate::{CINNABAR, DIM, Fonts, PAPER, text};

#[derive(Component)]
pub(crate) struct Clock;

#[derive(Component)]
pub(crate) struct Kills;

#[derive(Component)]
pub(crate) struct LevelLabel;

#[derive(Component)]
pub(crate) struct XpFill;

#[derive(Component)]
pub(crate) struct HpFill;

#[derive(Component)]
pub(crate) struct HpLabel;

const BAR_BG: Color = Color::srgba(0.0, 0.0, 0.0, 0.45);
const XP_COLOR: Color = Color::srgb(0.62, 0.86, 0.95);

pub(crate) fn spawn_hud(mut commands: Commands, fonts: Res<Fonts>, setup: Res<RunSetup>) {
    // 顶端经验条
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            top: px(0),
            height: px(6),
            ..default()
        },
        BackgroundColor(BAR_BG),
        children![(
            XpFill,
            Node { width: percent(0), height: percent(100), ..default() },
            BackgroundColor(XP_COLOR)
        )],
    ));
    // 左上：用时、击杀、种子
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node {
            position_type: PositionType::Absolute,
            left: px(20),
            top: px(14),
            flex_direction: FlexDirection::Column,
            ..default()
        },
        children![
            (Clock, text(&fonts.body, 28.0, PAPER, "00:00")),
            (Kills, text(&fonts.body, 18.0, PAPER, "击杀 0")),
            text(&fonts.body, 14.0, DIM, &format!("种子 {}", setup.seed)),
        ],
    ));
    // 右上：等级
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node { position_type: PositionType::Absolute, right: px(20), top: px(14), ..default() },
        children![(LevelLabel, text(&fonts.body, 22.0, PAPER, "等级 1"))],
    ));
    // 底部中间：生命条
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            bottom: px(44),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            row_gap: px(4),
            ..default()
        },
        children![
            (HpLabel, text(&fonts.body, 14.0, DIM, "生命 100 / 100")),
            (
                Node { width: px(240), height: px(8), ..default() },
                BackgroundColor(BAR_BG),
                children![(
                    HpFill,
                    Node { width: percent(100), height: percent(100), ..default() },
                    BackgroundColor(CINNABAR)
                )],
            ),
        ],
    ));
    // 左下：操作提示
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node { position_type: PositionType::Absolute, left: px(20), bottom: px(14), ..default() },
        children![text(
            &fonts.body,
            16.0,
            DIM,
            "WASD / 方向键 / 左摇杆　移动　　空格 / 手柄 A　闪避　　Esc　暂停　　F3　性能"
        )],
    ));
}

pub(crate) fn update_hud(
    content: Res<GameContent>,
    tick: Option<Res<Tick>>,
    progress: Option<Res<Progress>>,
    player: Query<&Health, With<Player>>,
    mut texts: ParamSet<(
        Query<&mut Text, With<Clock>>,
        Query<&mut Text, With<Kills>>,
        Query<&mut Text, With<LevelLabel>>,
        Query<&mut Text, With<HpLabel>>,
    )>,
    mut xp: Query<&mut Node, (With<XpFill>, Without<HpFill>)>,
    mut hp: Query<&mut Node, (With<HpFill>, Without<XpFill>)>,
) {
    let (Some(tick), Some(progress)) = (tick, progress) else { return };
    let secs = tick.0 / u64::from(TICK_HZ);
    for mut t in &mut texts.p0() {
        t.0 = format!("{:02}:{:02}", secs / 60, secs % 60);
    }
    for mut t in &mut texts.p1() {
        t.0 = format!("击杀 {}", progress.kills);
    }
    for mut t in &mut texts.p2() {
        t.0 = format!("等级 {}", progress.level);
    }
    let need = content.0.run.xp_need.at(progress.level as f32).max(1.0);
    for mut n in &mut xp {
        n.width = percent((progress.xp / need * 100.0).clamp(0.0, 100.0));
    }
    if let Ok(h) = player.single() {
        for mut t in &mut texts.p3() {
            t.0 = format!("生命 {} / {}", h.hp.ceil() as i32, h.max.round() as i32);
        }
        for mut n in &mut hp {
            n.width = percent((h.hp / h.max * 100.0).clamp(0.0, 100.0));
        }
    }
}
