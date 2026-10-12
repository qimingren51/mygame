//! 命令行工具（不开窗口）：跑分、内容检查。见 docs/DESIGN.md 第 13 节。
//!
//!   cargo run --release -p lantern-tools -- bench [--seconds 60] [--seed 1]
//!   cargo run -p lantern-tools -- check-content

use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_core::step::TICK_HZ;
use lantern_sim::{InputFrame, SimCommand, SimHarness};

const USAGE: &str = "用法：
  lantern-tools bench [--seconds <秒>] [--seed <种子>]   模拟跑分
  lantern-tools check-content                          校验 assets/data";

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
    let seconds = flag(args, "--seconds", 60)?;
    let seed = flag(args, "--seed", 1)?;
    let content = Content::load(&data_dir()).map_err(|e| e.to_string())?;
    let mut sim = SimHarness::new(content, seed);
    let ticks = seconds * u64::from(TICK_HZ);
    let start = Instant::now();
    for tick in 0..ticks {
        let t = tick as f32 / TICK_HZ as f32;
        let input = InputFrame::quantize(Vec2::new(ops::cos(t), ops::sin(t)));
        let cmds: &[SimCommand] = if tick % 120 == 0 { &[SimCommand::Dash] } else { &[] };
        sim.step(input, cmds);
    }
    let elapsed = start.elapsed();
    let last = sim.hashes().last().map(|c| c.hash).unwrap_or(0);
    println!(
        "模拟 {seconds} 秒（{ticks} 步），耗时 {:.1} ms，每步 {:.4} ms，最终哈希 {last:016x}",
        elapsed.as_secs_f64() * 1e3,
        elapsed.as_secs_f64() * 1e3 / ticks as f64,
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
