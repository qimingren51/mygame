//! 观看回放（`lantern --replay <文件>`）：自动开局，屏幕上方显示回放状态；
//! 与录制时的状态哈希不一致时提示从第几步开始分歧；播完后暂停，按 Enter 回到标题。

use bevy::prelude::*;

use lantern_core::step::TICK_HZ;
use lantern_platform::Actions;
use lantern_sim::{AppState, ReplayPlayback};

use crate::{CINNABAR, Fonts, PAPER, text};

#[derive(Component)]
pub(crate) struct ReplayStatus;

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Title), autostart)
        .add_systems(OnEnter(AppState::Run), spawn_status)
        .add_systems(OnExit(AppState::Run), stop)
        .add_systems(Update, update_status.run_if(in_state(AppState::Run)));
}

/// 带着回放启动时，跳过标题直接开局。
fn autostart(
    mut commands: Commands,
    playback: Option<Res<ReplayPlayback>>,
    mut next: ResMut<NextState<AppState>>,
) {
    if let Some(p) = playback {
        commands.insert_resource(p.setup());
        next.set(AppState::Run);
    }
}

fn spawn_status(mut commands: Commands, fonts: Res<Fonts>, playback: Option<Res<ReplayPlayback>>) {
    if playback.is_none() {
        return;
    }
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            top: px(14),
            justify_content: JustifyContent::Center,
            ..default()
        },
        children![(ReplayStatus, text(&fonts.body, 18.0, PAPER, "回放中"))],
    ));
}

fn update_status(
    actions: Res<Actions>,
    playback: Option<Res<ReplayPlayback>>,
    mut time: ResMut<Time<Virtual>>,
    mut next: ResMut<NextState<AppState>>,
    mut q: Query<(&mut Text, &mut TextColor), With<ReplayStatus>>,
) {
    let Some(p) = playback else { return };
    let Ok((mut t, mut color)) = q.single_mut() else { return };
    let secs = p.replay.ticks / u64::from(TICK_HZ);
    let mut s = if p.finished {
        format!("回放结束（{:02}:{:02}）　Enter　回到标题", secs / 60, secs % 60)
    } else {
        format!("回放中　种子 {}　共 {:02}:{:02}", p.replay.seed, secs / 60, secs % 60)
    };
    if let Some(tick) = p.diverged_at {
        s.push_str(&format!("\n与录制时不一致：从第 {tick} 步起"));
        color.0 = CINNABAR;
    }
    if t.0 != s {
        t.0 = s;
    }
    if p.finished {
        if !time.is_paused() {
            time.pause();
        }
        if actions.confirm {
            next.set(AppState::Title);
        }
    }
}

/// 离开这一局时结束回放，恢复时间。
fn stop(mut commands: Commands, mut time: ResMut<Time<Virtual>>) {
    commands.remove_resource::<ReplayPlayback>();
    time.unpause();
}
