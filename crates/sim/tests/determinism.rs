//! 确定性测试（docs/DESIGN.md 第 7 节）。
//!
//! 同一种子 + 同一串脚本输入跑两遍，状态哈希必须逐位相同；再与提交进仓库的黄金文件对照。
//! CI 在 Linux 和 Windows 上都跑，对照的是同一份文件，所以跨平台不一致会立刻发现。
//! 故意修改玩法后，用 `UPDATE_GOLDEN=1 cargo test -p lantern_sim` 重新生成。

mod common;

use std::path::{Path, PathBuf};

use bevy_math::{Vec2, ops};
use lantern_sim::{InputFrame, SimCommand, SimHarness};

use common::{bot_step, content};

/// 脚本化输入：绕不规则的圈走，每 2 秒闪避一次，偶尔停下。
fn scripted(tick: u64) -> (InputFrame, Vec<SimCommand>) {
    let t = tick as f32 / 60.0;
    let dir = if (tick / 300) % 4 == 3 {
        Vec2::ZERO
    } else {
        Vec2::new(ops::cos(t * 0.7), ops::sin(t * 1.3)) * (0.6 + 0.4 * ops::sin(t * 0.21))
    };
    let cmds = if tick % 120 == 60 { vec![SimCommand::Dash] } else { vec![] };
    (InputFrame::quantize(dir), cmds)
}

/// 跑到指定的游戏时间或主角倒下为止（升级时由机器人选卡），返回每秒的状态哈希。
fn run(seed: u64, ticks: u64) -> Vec<(u64, u64)> {
    let mut sim = SimHarness::new(content(), seed);
    let mut step = 0;
    while sim.tick() < ticks && !sim.is_over() {
        let (input, cmds) = scripted(step);
        bot_step(&mut sim, input, &cmds);
        step += 1;
    }
    assert!(sim.tick() == ticks || sim.is_over());
    sim.hashes().iter().map(|c| (c.tick, c.hash)).collect()
}

const SEEDS: [u64; 3] = [1, 20261012, 0xDEAD_BEEF];
const TICKS: u64 = 3 * 60 * 60;

#[test]
fn same_seed_same_result() {
    let a = run(SEEDS[1], TICKS);
    let b = run(SEEDS[1], TICKS);
    assert!(!a.is_empty());
    assert_eq!(a, b);
}

#[test]
fn different_seeds_differ() {
    assert_ne!(run(SEEDS[0], 120), run(SEEDS[2], 120));
}

fn golden_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden/scripted.ron")
}

#[test]
fn matches_golden_file() {
    let got: Vec<(u64, Vec<String>)> = SEEDS
        .iter()
        .map(|&seed| {
            let hashes = run(seed, TICKS).into_iter().map(|(t, h)| format!("{t}:{h:016x}")).collect();
            (seed, hashes)
        })
        .collect();
    let path = golden_path();
    if std::env::var_os("UPDATE_GOLDEN").is_some() {
        let text = ron::ser::to_string_pretty(&got, ron::ser::PrettyConfig::default()).unwrap();
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, text + "\n").unwrap();
        eprintln!("已更新黄金文件 {}", path.display());
        return;
    }
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|_| panic!("缺少黄金文件 {}，用 UPDATE_GOLDEN=1 生成", path.display()));
    let want: Vec<(u64, Vec<String>)> = ron::from_str(&text).unwrap();
    for ((seed, g), (_, w)) in got.iter().zip(&want) {
        if let Some(i) = g.iter().zip(w).position(|(a, b)| a != b) {
            panic!("种子 {seed} 在第 {} 个检查点开始不一致：得到 {}，期望 {}", i, g[i], w[i]);
        }
        assert_eq!(g.len(), w.len(), "种子 {seed} 的检查点数量不同");
    }
    assert_eq!(got.len(), want.len());
}
