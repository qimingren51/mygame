//! 跑分模式（标题界面按 B）：场上依次保持 250、1000、2500、5000 只妖物，各跑 10 秒，
//! 主角自动绕圈、无敌。每段统计帧率、帧时间和模拟耗时，最后显示结果并存成文本文件，
//! 方便把结果发回来（docs/DESIGN.md 第 16、17 节，M1 的门槛就是这份结果）。

use std::fmt::Write as _;

use bevy::prelude::*;
use bevy::render::renderer::RenderAdapterInfo;
use bevy::window::PrimaryWindow;

use lantern_platform::{Actions, AutoPilot, paths};
use lantern_sim::{AppState, Enemies, RunMode, RunSetup, SimCommand, SimCommands};

use crate::perf::SimTiming;
use crate::{DIM, Fonts, PAPER, text};

pub const STAGES: [u32; 4] = [250, 1000, 2500, 5000];
const STAGE_SECS: f32 = 10.0;
/// 每段开头不计入：等妖物补满、围上来
const WARMUP_SECS: f32 = 3.0;

struct StageResult {
    target: u32,
    enemies: f32,
    fps: f32,
    p95_ms: f32,
    max_ms: f32,
    sim_ms: f64,
}

#[derive(Resource)]
pub(crate) struct BenchRun {
    stage: usize,
    t: f32,
    frame_ms: Vec<f32>,
    enemy_sum: f64,
    sim_start: (f64, u64),
    results: Vec<StageResult>,
    done: bool,
}

/// 从标题界面开始跑分。
pub(crate) fn start(commands: &mut Commands, next: &mut NextState<AppState>) {
    info!("开始跑分");
    commands.insert_resource(RunSetup::new(1, RunMode::Bench { enemies: STAGES[0] }));
    commands.insert_resource(AutoPilot::default());
    commands.insert_resource(BenchRun {
        stage: 0,
        t: 0.0,
        frame_ms: Vec::new(),
        enemy_sum: 0.0,
        sim_start: (0.0, 0),
        results: Vec::new(),
        done: false,
    });
    next.set(AppState::Run);
}

pub(crate) fn drive(
    mut commands: Commands,
    time: Res<Time>,
    timing: Res<SimTiming>,
    en: Option<Res<Enemies>>,
    fonts: Res<Fonts>,
    adapter: Option<Res<RenderAdapterInfo>>,
    window: Single<&Window, With<PrimaryWindow>>,
    mut bench: ResMut<BenchRun>,
    mut sim_commands: ResMut<SimCommands>,
) {
    if bench.done {
        return;
    }
    let dt = time.delta_secs();
    bench.t += dt;
    if bench.t < WARMUP_SECS {
        bench.sim_start = (timing.total_ms, timing.steps);
        return;
    }
    bench.frame_ms.push(dt * 1e3);
    bench.enemy_sum += en.map_or(0, |e| e.count) as f64;
    if bench.t < STAGE_SECS {
        return;
    }
    // 这一段结束
    let n = bench.frame_ms.len().max(1);
    let mut sorted = bench.frame_ms.clone();
    sorted.sort_by(f32::total_cmp);
    let avg = sorted.iter().sum::<f32>() / n as f32;
    let steps = timing.steps.saturating_sub(bench.sim_start.1).max(1);
    let result = StageResult {
        target: STAGES[bench.stage],
        enemies: (bench.enemy_sum / n as f64) as f32,
        fps: 1000.0 / avg.max(0.001),
        p95_ms: sorted[(n * 95 / 100).min(n - 1)],
        max_ms: sorted[n - 1],
        sim_ms: (timing.total_ms - bench.sim_start.0) / steps as f64,
    };
    bench.results.push(result);
    bench.stage += 1;
    bench.t = 0.0;
    bench.frame_ms.clear();
    bench.enemy_sum = 0.0;
    if let Some(&next) = STAGES.get(bench.stage) {
        sim_commands.0.push(SimCommand::BenchTarget(next));
        return;
    }
    // 全部跑完：停止自动绕圈，显示并保存结果
    bench.done = true;
    commands.remove_resource::<AutoPilot>();
    let gpu = adapter.map_or_else(|| "未知".to_string(), |a| format!("{}（{:?}）", a.name, a.backend));
    let report = format_report(&bench.results, &gpu, window.physical_width(), window.physical_height());
    info!("跑分结果\n{report}");
    let saved = save_report(&report);
    let mut card = vec![report.clone()];
    card.push(match saved {
        Ok(path) => format!("已保存到 {path}"),
        Err(e) => format!("保存失败：{e}"),
    });
    commands.spawn((
        DespawnOnExit(AppState::Run),
        Node {
            width: percent(100),
            height: percent(100),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: px(14),
            ..default()
        },
        BackgroundColor(Color::srgba(0.05, 0.06, 0.1, 0.8)),
        children![
            text(&fonts.title, 56.0, PAPER, "跑分结果"),
            text(&fonts.body, 18.0, PAPER, &card[0]),
            text(&fonts.body, 14.0, DIM, &card[1]),
            text(&fonts.body, 18.0, DIM, "Enter / 手柄 A　回到标题"),
        ],
    ));
}

fn format_report(results: &[StageResult], gpu: &str, w: u32, h: u32) -> String {
    let mut s = String::new();
    let _ = writeln!(s, "提灯夜行 v{}　显卡 {gpu}　窗口 {w}×{h}", env!("CARGO_PKG_VERSION"));
    let _ = writeln!(s, "妖物　　帧率　　帧时间 95%　　最长　　模拟每步");
    for r in results {
        let _ = writeln!(
            s,
            "{:>5}（实际 {:>4.0}）　{:>5.0}　　{:>6.1} ms　　{:>6.1} ms　　{:>5.2} ms",
            r.target, r.enemies, r.fps, r.p95_ms, r.max_ms, r.sim_ms
        );
    }
    s
}

fn save_report(report: &str) -> Result<String, String> {
    let dir = paths::data_dir().join("bench");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let stamp =
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let path = dir.join(format!("bench-{stamp}.txt"));
    std::fs::write(&path, report).map_err(|e| e.to_string())?;
    Ok(path.display().to_string())
}

/// 跑完后按 Enter 回到标题。
pub(crate) fn finish_input(
    mut commands: Commands,
    actions: Res<Actions>,
    bench: Res<BenchRun>,
    mut next: ResMut<NextState<AppState>>,
) {
    if bench.done && actions.confirm {
        commands.remove_resource::<BenchRun>();
        next.set(AppState::Title);
    }
}

/// 中途离开（暂停后回到标题）时清掉跑分状态。
pub(crate) fn cleanup(mut commands: Commands) {
    commands.remove_resource::<BenchRun>();
    commands.remove_resource::<AutoPilot>();
}
