//! 回放往返：录制一局 → 存成文本 → 解析 → 重放，每秒的状态哈希必须一致。

mod common;

use bevy_math::{Vec2, ops};
use lantern_sim::{InputFrame, OmenPick, Replay, RunMode, RunSetup, SimCommand, SimHarness};

use common::{bot_step, content};

fn record(seed: u64, ticks: u64) -> (Replay, Vec<(u64, u64)>) {
    let mut setup = RunSetup::new(seed, RunMode::Normal);
    setup.omen = Some(OmenPick { id: "element".into(), element: Some(lantern_content::Element::Fire) });
    setup.meta.insert("dmg".into(), 2);
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.record("test");
    let mut step = 0u64;
    while sim.tick() < ticks && !sim.is_over() {
        let t = step as f32 / 60.0;
        let dir = Vec2::new(ops::cos(t * 0.4), ops::sin(t * 0.9));
        let cmds: &[SimCommand] = if step % 150 == 75 { &[SimCommand::Dash] } else { &[] };
        bot_step(&mut sim, InputFrame::quantize(dir), cmds);
        step += 1;
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
    assert!(replay.inputs.len() < replay.steps as usize, "输入应该被游程编码压缩");
    assert!(replay.commands.iter().any(|(_, c)| matches!(c, SimCommand::Choose(_))), "应该录到升级选择");
    assert!(replay.steps > replay.ticks, "选择阶段的步也要录下来");
    assert_eq!(replay.content_hash, content().hash);

    let text = replay.to_ron();
    let parsed = Replay::parse(&text).expect("能解析回来");
    assert_eq!(parsed, replay);

    let (replayed, diverged) = play(parsed);
    assert_eq!(diverged, None);
    assert_eq!(replayed, original);
}

#[test]
fn old_format_is_rejected_with_a_clear_message() {
    let err = Replay::parse("(format: 1, game_version: \"0.1.0\", seed: 1)").unwrap_err();
    assert!(err.contains("格式版本 1"), "{err}");
}

#[test]
fn tampered_replay_is_detected() {
    let (mut replay, _) = record(5, 20 * 60);
    // 把中间一段输入改掉
    let mid = replay.inputs.len() / 2;
    replay.inputs[mid].mx = replay.inputs[mid].mx.wrapping_add(60);
    replay.inputs[mid].my = replay.inputs[mid].my.wrapping_add(60);
    let (_, diverged) = play(replay);
    assert!(diverged.is_some(), "改过的回放应该报告分歧");
}

#[test]
fn replay_finishes_at_death_or_victory_with_inputs_remaining() {
    use bevy_ecs::prelude::*;
    use lantern_sim::replay::InputRun;
    use lantern_sim::{Health, Player};

    for won in [false, true] {
        let mut replay = Replay::new("test", content().hash, RunSetup::new(7, RunMode::Normal));
        replay.inputs.push(InputRun { steps: 600, mx: 0, my: 0 });
        replay.steps = 600;
        replay.ticks = 600;
        let mut sim = SimHarness::from_replay(content(), replay);
        sim.quiet();
        if won {
            sim.flow_mut().won_at = Some(0.0);
        } else {
            let world = sim.world_mut();
            world.query_filtered::<&mut Health, With<Player>>().single_mut(world).unwrap().hp = 0.0;
        }

        sim.step(InputFrame::default(), &[]);
        assert!(sim.is_over());
        assert_eq!(sim.flow().result.as_ref().unwrap().won, won);
        assert!(sim.playback().unwrap().finished, "终局无需再读一步输入才能结束回放");
        let tick = sim.tick();
        sim.step(InputFrame::default(), &[]);
        assert_eq!(sim.tick(), tick);
    }
}
