//! 观看回放（`lantern --replay <文件>`）：自动开局，屏幕上方显示回放状态；
//! 与录制时的状态哈希不一致时提示从第几步开始分歧；播完后暂停，按 Enter 回到标题。

use bevy::prelude::*;

use lantern_core::step::TICK_HZ;
use lantern_platform::Actions;
use lantern_sim::{AppState, ReplayPlayback, SimOutbox, SimPhase, Tick};

use crate::{CINNABAR, Fonts, PAPER, text};

#[derive(Component)]
pub(crate) struct ReplayStatus;

/// 观看回放时从第几秒开始看（`lantern --replay <文件> --from <秒>`）。
#[derive(Resource, Clone, Copy, Debug)]
pub struct ReplaySeek(pub u32);

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Title), autostart)
        .add_systems(OnEnter(AppState::Run), spawn_status)
        .add_systems(OnExit(AppState::Run), stop)
        .add_systems(
            Update,
            (seek.run_if(resource_exists::<ReplaySeek>), update_status)
                .chain()
                .run_if(in_state(AppState::Run)),
        );
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
    phase: Option<Res<SimPhase>>,
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
        format!("回放中　种子 {}　共 {:02}:{:02}", p.replay.setup.seed, secs / 60, secs % 60)
    };
    if let Some(tick) = p.diverged_at {
        s.push_str(&format!("\n与录制时不一致：从第 {tick} 步起"));
        color.0 = CINNABAR;
    }
    if t.0 != s {
        t.0 = s;
    }
    if p.finished {
        // 一局已经结束（天明或倒下）时不暂停，让收尾的演出播完
        if !time.is_paused() && phase.is_none_or(|ph| *ph != SimPhase::Over) {
            time.pause();
        }
        if actions.confirm {
            next.set(AppState::Title);
        }
    }
}

/// 快进到 `--from`（事件直接丢掉）；时间没推进时让出本帧，下帧继续。
fn seek(world: &mut World) {
    let Some(ReplaySeek(secs)) = world.remove_resource::<ReplaySeek>() else { return };
    let target = u64::from(secs) * u64::from(TICK_HZ);
    while world.resource::<Tick>().0 < target
        && world.get_resource::<ReplayPlayback>().is_some_and(|p| !p.finished)
        && *world.resource::<SimPhase>() != SimPhase::Over
    {
        let before = world.resource::<Tick>().0;
        world.run_schedule(FixedUpdate);
        world.resource_mut::<SimOutbox>().0.clear();
        if world.resource::<Tick>().0 <= before {
            // 选择和演出停顿也会暂停 tick；结束前保留目标，但不能在本帧空转。
            if *world.resource::<SimPhase>() != SimPhase::Over
                && world.get_resource::<ReplayPlayback>().is_some_and(|p| !p.finished)
            {
                world.insert_resource(ReplaySeek(secs));
            }
            break;
        }
    }
}

/// 离开这一局时结束回放，恢复时间。
fn stop(mut commands: Commands, mut time: ResMut<Time<Virtual>>) {
    commands.remove_resource::<ReplayPlayback>();
    time.unpause();
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::{Replay, RunMode, RunSetup};

    #[derive(Resource, Default)]
    struct Steps(u32);

    fn world() -> World {
        let mut world = World::new();
        world.insert_resource(Tick(0));
        world.insert_resource(SimPhase::Play);
        world.insert_resource(SimOutbox::default());
        world.insert_resource(ReplayPlayback::new(Replay::new("test", 0, RunSetup::new(1, RunMode::Normal))));
        world.insert_resource(ReplaySeek(60));
        world.init_resource::<Steps>();
        world
    }

    #[test]
    fn seek_stops_at_the_end_even_before_playback_is_marked_finished() {
        let mut world = world();
        let mut schedule = Schedule::new(FixedUpdate);
        schedule.add_systems(
            |mut tick: ResMut<Tick>, mut phase: ResMut<SimPhase>, mut steps: ResMut<Steps>| {
                steps.0 += 1;
                assert_eq!(steps.0, 1, "终局后不能继续快进");
                tick.0 += 1;
                *phase = SimPhase::Over;
            },
        );
        world.add_schedule(schedule);
        seek(&mut world);
        assert_eq!(world.resource::<Tick>().0, 1);
        assert_eq!(*world.resource::<SimPhase>(), SimPhase::Over);
        assert!(!world.contains_resource::<ReplaySeek>());
        // 已在终局时也不能再执行调度。
        world.insert_resource(ReplaySeek(60));
        seek(&mut world);
        assert_eq!(world.resource::<Steps>().0, 1);
    }

    #[test]
    fn seek_yields_when_tick_stalls_and_resumes_next_frame() {
        let mut world = world();
        world.insert_resource(ReplaySeek(1));
        let mut schedule = Schedule::new(FixedUpdate);
        schedule.add_systems(|mut steps: ResMut<Steps>| {
            steps.0 += 1;
            assert!(steps.0 <= 1, "无进展时必须先退出本帧循环");
        });
        world.add_schedule(schedule);
        seek(&mut world);
        assert_eq!(world.resource::<Tick>().0, 0);
        assert!(world.contains_resource::<ReplaySeek>());

        let mut schedule = Schedule::new(FixedUpdate);
        schedule.add_systems(|mut tick: ResMut<Tick>| tick.0 += 1);
        world.add_schedule(schedule);
        seek(&mut world);
        assert_eq!(world.resource::<Tick>().0, u64::from(TICK_HZ));
        assert!(!world.contains_resource::<ReplaySeek>());
    }

    #[test]
    fn seek_stops_when_inputs_run_out_without_tick_progress() {
        let mut world = world();
        let mut schedule = Schedule::new(FixedUpdate);
        schedule.add_systems(|mut playback: ResMut<ReplayPlayback>| playback.finished = true);
        world.add_schedule(schedule);
        seek(&mut world);
        assert_eq!(world.resource::<Tick>().0, 0);
        assert!(!world.contains_resource::<ReplaySeek>());
    }
}
