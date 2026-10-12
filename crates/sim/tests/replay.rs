//! 回放往返：录制一局 → 存成文本 → 解析 → 重放，每秒的状态哈希必须一致。

use std::path::Path;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_sim::{InputFrame, Replay, SimCommand, SimHarness};

fn content() -> Content {
    Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).expect("内容数据")
}

fn record(seed: u64, ticks: u64) -> (Replay, Vec<(u64, u64)>) {
    let mut sim = SimHarness::new(content(), seed);
    sim.record("test");
    for tick in 0..ticks {
        if sim.is_over() {
            break;
        }
        let t = tick as f32 / 60.0;
        let dir = Vec2::new(ops::cos(t * 0.4), ops::sin(t * 0.9));
        let cmds: &[SimCommand] = if tick % 150 == 75 { &[SimCommand::Dash] } else { &[] };
        sim.step(InputFrame::quantize(dir), cmds);
    }
    let hashes = sim.hashes().iter().map(|c| (c.tick, c.hash)).collect();
    (sim.replay().expect("在录制").clone(), hashes)
}

fn play(replay: Replay) -> (Vec<(u64, u64)>, Option<u64>) {
    let mut sim = SimHarness::from_replay(content(), replay);
    while !sim.playback().unwrap().finished && !sim.is_over() {
        sim.step(InputFrame::default(), &[]);
    }
    let hashes = sim.hashes().iter().map(|c| (c.tick, c.hash)).collect();
    (hashes, sim.playback().unwrap().diverged_at)
}

#[test]
fn replay_roundtrip_reproduces_the_run() {
    let (replay, original) = record(99, 90 * 60);
    assert!(!replay.commands.is_empty(), "应该录到闪避命令");
    assert!(replay.inputs.len() < replay.ticks as usize, "输入应该被游程编码压缩");
    assert_eq!(replay.content_hash, content().hash);

    let text = replay.to_ron();
    let parsed = Replay::parse(&text).expect("能解析回来");
    assert_eq!(parsed, replay);

    let (replayed, diverged) = play(parsed);
    assert_eq!(diverged, None);
    assert_eq!(replayed, original);
}

#[test]
fn tampered_replay_is_detected() {
    let (mut replay, _) = record(5, 20 * 60);
    // 把中间一段输入改掉
    let mid = replay.inputs.len() / 2;
    replay.inputs[mid].mx = replay.inputs[mid].mx.wrapping_add(60);
    let (_, diverged) = play(replay);
    assert!(diverged.is_some(), "改过的回放应该报告分歧");
}
