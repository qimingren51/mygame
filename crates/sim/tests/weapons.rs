//! 法器：每件法器（进化前后）都能击杀妖物，以及一些细节（对应网页版 tests/sim/weapons.test.ts）。

mod common;

use bevy_math::{Vec2, ops};
use lantern_sim::combat::StrikeFx;
use lantern_sim::weapons::drop::Fissures;
use lantern_sim::weapons::volley::Shots;
use lantern_sim::{InputFrame, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase};

use common::content;

/// 只带一件法器，周围摆一圈影妖，关掉正常刷怪。
fn arena(id: &str, level: u32, evolved: bool) -> SimHarness {
    let mut setup = RunSetup::new(11, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.quiet();
    sim.set_build(&[(id, level, evolved)], &[]);
    for k in 0..40 {
        let a = k as f32 / 40.0 * std::f32::consts::TAU;
        let r = 60.0 + (k % 4) as f32 * 30.0;
        sim.spawn("shade", Vec2::new(ops::cos(a), ops::sin(a)) * r);
    }
    sim
}

/// 跑若干秒游戏时间，升级一律跳过（构筑不变）。返回本段时间里的事件。
fn run_for(sim: &mut SimHarness, seconds: f32) -> Vec<SimEvent> {
    let mut events = Vec::new();
    let end = sim.tick() + (seconds * 60.0) as u64;
    while sim.tick() < end {
        let cmds: &[SimCommand] = if sim.phase() == SimPhase::LevelUp { &[SimCommand::Skip] } else { &[] };
        sim.step(InputFrame::default(), cmds);
        events.extend(sim.take_events());
    }
    events
}

#[test]
fn every_weapon_kills_before_and_after_evolving() {
    for w in &content().weapons {
        for evolved in [false, true] {
            let mut sim = arena(&w.id, 8, evolved);
            let events = run_for(&mut sim, 8.0);
            let kills = events.iter().filter(|e| matches!(e, SimEvent::Kill { .. })).count();
            assert!(kills > 5, "{}（进化 {evolved}）8 秒只杀了 {kills} 只", w.id);
        }
    }
}

#[test]
fn sword_fires_shots() {
    let mut sim = arena("sword", 1, false);
    let mut max_shots = 0;
    for _ in 0..120 {
        sim.step(InputFrame::default(), &[]);
        max_shots = max_shots.max(sim.world().resource::<Shots>().0.len());
    }
    assert!(max_shots > 0);
}

#[test]
fn bell_pulses_a_ring() {
    let mut sim = arena("bell", 4, false);
    let events = run_for(&mut sim, 4.0);
    assert!(events.iter().any(|e| matches!(e, SimEvent::Strike { fx: StrikeFx::Pulse, .. })));
}

#[test]
fn evolved_bell_tolls_across_the_screen() {
    let mut sim = arena("bell", 8, true);
    let events = run_for(&mut sim, 7.0);
    assert!(events.iter().any(|e| matches!(e, SimEvent::Strike { fx: StrikeFx::Toll, .. })));
}

#[test]
fn evolved_seal_leaves_fissures() {
    let mut sim = arena("seal", 8, true);
    let mut most = 0;
    for _ in 0..300 {
        let cmds: &[SimCommand] = if sim.phase() == SimPhase::LevelUp { &[SimCommand::Skip] } else { &[] };
        sim.step(InputFrame::default(), cmds);
        most = most.max(sim.world().resource::<Fissures>().0.len());
    }
    assert!(most > 0);
}

#[test]
fn crane_count_grows_with_level_and_evolution() {
    let mut a = arena("crane", 1, false);
    a.step(InputFrame::default(), &[]);
    let mut b = arena("crane", 8, true);
    b.step(InputFrame::default(), &[]);
    assert_eq!(a.arsenal().0[0].cranes.len(), 1);
    assert_eq!(b.arsenal().0[0].cranes.len(), 10);
}

#[test]
fn each_real_weapon_emits_direction_and_content_index() {
    let content = content();
    for id in ["lamp", "sword", "bell", "crane", "seal"] {
        let mut sim = arena(id, 8, false);
        let index = content.weapon_index(id).unwrap() as u16;
        let events = run_for(&mut sim, 3.0);
        assert!(
            events.iter().any(|e| matches!(e, SimEvent::Hit { weapon: Some(w), incoming_dir, .. }
            if *w == index && (incoming_dir.length() - 1.0).abs() < 1e-5)),
            "{id}"
        );
    }
}
