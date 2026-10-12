//! 性能面板（F3）：帧率、帧时间、模拟每步耗时、妖物和魂火数量。
//!
//! 模拟耗时用 FixedUpdate 首尾两个计时系统测量。这只是诊断，不进入模拟逻辑，不影响可复现。

use std::time::Instant;

use bevy::prelude::*;
use lantern_platform::Actions;
use lantern_sim::{Enemies, Gems, RunState, SimSet};

use crate::{Fonts, PAPER, text};

/// 模拟每步的实际耗时（毫秒）。
#[derive(Resource, Default)]
pub struct SimTiming {
    start: Option<Instant>,
    pub total_ms: f64,
    pub steps: u64,
}

fn sim_begin(mut t: ResMut<SimTiming>) {
    t.start = Some(Instant::now());
}

fn sim_end(mut t: ResMut<SimTiming>) {
    if let Some(s) = t.start.take() {
        t.total_ms += s.elapsed().as_secs_f64() * 1e3;
        t.steps += 1;
    }
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<SimTiming>()
        .init_resource::<PerfWindow>()
        .add_systems(
            FixedUpdate,
            (
                sim_begin.before(SimSet::Input).run_if(in_state(RunState::Playing)),
                sim_end.after(SimSet::Hash).run_if(in_state(RunState::Playing)),
            ),
        )
        // 字体在 Startup 里用命令插入，面板等到 PostStartup 再生成
        .add_systems(PostStartup, spawn_panel)
        .add_systems(Update, update_panel);
}

#[derive(Component)]
struct PerfText;

/// 最近半秒的帧时间统计。
#[derive(Resource, Default)]
struct PerfWindow {
    t: f32,
    frames: u32,
    sum_ms: f32,
    max_ms: f32,
    sim_ms: f64,
    sim_steps: u64,
    visible: bool,
}

fn spawn_panel(mut commands: Commands, fonts: Res<Fonts>) {
    commands.spawn((
        PerfText,
        Node { position_type: PositionType::Absolute, right: px(20), top: px(44), ..default() },
        text(&fonts.body, 14.0, PAPER, ""),
        BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.5)),
        Visibility::Hidden,
    ));
}

fn update_panel(
    time: Res<Time>,
    actions: Res<Actions>,
    timing: Res<SimTiming>,
    en: Option<Res<Enemies>>,
    gems: Option<Res<Gems>>,
    mut w: ResMut<PerfWindow>,
    mut q: Query<(&mut Text, &mut Visibility), With<PerfText>>,
) {
    let Ok((mut text, mut vis)) = q.single_mut() else { return };
    if actions.toggle_perf {
        w.visible = !w.visible;
        *vis = if w.visible { Visibility::Inherited } else { Visibility::Hidden };
    }
    let ms = time.delta_secs() * 1e3;
    w.t += time.delta_secs();
    w.frames += 1;
    w.sum_ms += ms;
    w.max_ms = w.max_ms.max(ms);
    if w.t < 0.5 {
        return;
    }
    let sim = if timing.steps > w.sim_steps {
        (timing.total_ms - w.sim_ms) / (timing.steps - w.sim_steps) as f64
    } else {
        0.0
    };
    let avg = w.sum_ms / w.frames as f32;
    text.0 = format!(
        "帧率 {:.0}　帧 {:.1} ms（最长 {:.1}）\n模拟每步 {:.2} ms\n妖物 {}　魂火 {}",
        1000.0 / avg.max(0.001),
        avg,
        w.max_ms,
        sim,
        en.map_or(0, |e| e.count),
        gems.map_or(0, |g| g.n),
    );
    w.sim_ms = timing.total_ms;
    w.sim_steps = timing.steps;
    w.t = 0.0;
    w.frames = 0;
    w.sum_ms = 0.0;
    w.max_ms = 0.0;
}
