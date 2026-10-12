//! 命令行工具（不开窗口）：跑分、内容检查。见 docs/DESIGN.md 第 13 节。
//!
//!   cargo run --release -p lantern-tools -- bench [--enemies 5000] [--seconds 20] [--seed 1]
//!   cargo run -p lantern-tools -- check-content

use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_core::step::TICK_HZ;
use lantern_sim::{InputFrame, RunMode, SimCommand, SimHarness};

const USAGE: &str = "用法：
  lantern-tools bench [--enemies <数量>] [--seconds <秒>] [--seed <种子>]
      跑分：场上保持指定数量的妖物（默认 5000），主角绕圈，统计每步耗时
  lantern-tools check-content
      校验 assets/data";

fn data_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")
}

fn flag(args: &[String], name: &str, default: u64) -> Result<u64, String> {
    match args.iter().position(|a| a == name) {
        Some(i) => {
            args.get(i + 1).and_then(|v| v.parse().ok()).ok_or_else(|| format!("{name} 后面要跟一个数字"))
        }
        None => Ok(default),
    }
}

fn bench(args: &[String]) -> Result<(), String> {
    let enemies = flag(args, "--enemies", 5000)? as u32;
    let seconds = flag(args, "--seconds", 20)?;
    let seed = flag(args, "--seed", 1)?;
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    let mut sim = SimHarness::with_mode(content, seed, RunMode::Bench { enemies });
    let input = |tick: u64| {
        let t = tick as f32 / TICK_HZ as f32;
        InputFrame::quantize(Vec2::new(ops::cos(t * 0.5), ops::sin(t * 0.5)))
    };
    // 热身 5 秒：妖物补满、围上来
    let warmup = 5 * u64::from(TICK_HZ);
    for tick in 0..warmup {
        sim.step(input(tick), &[]);
    }
    let ticks = seconds * u64::from(TICK_HZ);
    let mut times = Vec::with_capacity(ticks as usize);
    for tick in warmup..warmup + ticks {
        let cmds: &[SimCommand] = if tick % 120 == 0 { &[SimCommand::Dash] } else { &[] };
        let start = Instant::now();
        sim.step(input(tick), cmds);
        times.push(start.elapsed().as_secs_f64() * 1e3);
        sim.take_events();
    }
    let mean = times.iter().sum::<f64>() / times.len() as f64;
    times.sort_by(f64::total_cmp);
    let p95 = times[times.len() * 95 / 100];
    let max = times[times.len() - 1];
    let last = sim.hashes().last().map(|c| c.hash).unwrap_or(0);
    println!(
        "妖物 {} 只（目标 {enemies}），{seconds} 秒 {ticks} 步：每步平均 {mean:.3} ms，95% {p95:.3} ms，最大 {max:.3} ms，最终哈希 {last:016x}",
        sim.enemies().count
    );
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("bench") => bench(&args[1..]),
        Some("check-content") => {
            Content::load(&data_dir()).map(|_| println!("内容数据校验通过")).map_err(|e| e.to_string())
        }
        _ => Err(USAGE.into()),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("{msg}");
            ExitCode::FAILURE
        }
    }
}
