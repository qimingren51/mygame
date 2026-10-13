//! 青丘的竹丛（docs/BALANCE.md 第 12.7 节）：按块生成、减速、打碎、长回来、夜主结界里烧平。

mod common;

use bevy_math::Vec2;
use lantern_sim::bamboo::{Bamboo, ClumpState};
use lantern_sim::combat::{Area, Source, Strike, StrikeFx, Strikes};
use lantern_sim::{InputFrame, Player, Pos, PrevPos, RunMode, RunSetup, SimEvent, SimHarness};

use common::content;

fn quiet(seed: u64) -> SimHarness {
    let mut s = RunSetup::new(seed, RunMode::Normal);
    s.god = true;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    // 不带法器，免得灯火顺手把竹丛打碎
    sim.set_build(&[], &[]);
    sim
}

fn player_pos(sim: &mut SimHarness) -> Vec2 {
    let world = sim.world_mut();
    world.query_filtered::<&Pos, bevy_ecs::query::With<Player>>().single(world).unwrap().0
}

fn teleport(sim: &mut SimHarness, at: Vec2) {
    let world = sim.world_mut();
    let mut q = world.query_filtered::<(&mut Pos, &mut PrevPos), bevy_ecs::query::With<Player>>();
    let (mut pos, mut prev) = q.single_mut(world).unwrap();
    pos.0 = at;
    prev.0 = at;
}

/// 主角附近立着的一丛（离出生点最近的）。
fn nearest_clump(sim: &SimHarness) -> (usize, Vec2) {
    let b = sim.world().resource::<Bamboo>();
    b.clumps
        .iter()
        .enumerate()
        .filter(|(_, c)| c.state == ClumpState::Standing)
        .min_by(|a, b| a.1.pos.length().total_cmp(&b.1.pos.length()))
        .map(|(i, c)| (i, c.pos))
        .expect("附近应该长了竹丛")
}

fn state(sim: &SimHarness, i: usize) -> ClumpState {
    sim.world().resource::<Bamboo>().clumps[i].state
}

#[test]
fn clumps_grow_around_the_player_and_slow_walking() {
    let c = content();
    let def = c.run.bamboo.unwrap();
    let mut sim = quiet(4);
    sim.step(InputFrame::default(), &[]);
    let b = sim.world().resource::<Bamboo>();
    // 5 × 5 块，每块至少 2 丛（出生点附近的让开了）
    assert!(b.clumps.len() >= 25, "只长了 {} 丛", b.clumps.len());
    assert!(b.clumps.iter().all(|c| c.pos.length() >= def.clear_spawn), "出生点附近不长");
    // 同一个种子，竹丛一样
    let mut again = quiet(4);
    again.step(InputFrame::default(), &[]);
    let pos =
        |s: &SimHarness| s.world().resource::<Bamboo>().clumps.iter().map(|c| c.pos).collect::<Vec<_>>();
    assert_eq!(pos(&sim), pos(&again));

    // 在丛里往右走一步，比在空地上慢 30%
    let (_, at) = nearest_clump(&sim);
    let walk = |sim: &mut SimHarness, from: Vec2| {
        teleport(sim, from);
        sim.step(InputFrame::quantize(Vec2::X), &[]);
        player_pos(sim).x - from.x
    };
    let inside = walk(&mut sim, at);
    let outside = walk(&mut sim, Vec2::ZERO);
    assert!((inside / outside - (1.0 - def.slow)).abs() < 1e-3, "丛里 {inside}，空地 {outside}");
}

#[test]
fn clumps_break_and_grow_back_when_you_are_away() {
    let c = content();
    let def = c.run.bamboo.unwrap();
    let mut sim = quiet(6);
    sim.step(InputFrame::default(), &[]);
    let (i, at) = nearest_clump(&sim);
    // 一记范围打击（印、反应、燃灯都走这里）
    let hit = |sim: &mut SimHarness, damage: f32| {
        sim.world_mut().resource_mut::<Strikes>().0.push(Strike::new(
            at,
            Area::Circle(20.0),
            damage,
            Source::Ult,
            StrikeFx::None,
        ));
        sim.step(InputFrame::default(), &[]);
        sim.take_events()
    };
    hit(&mut sim, def.hp * 0.6);
    assert_eq!(state(&sim, i), ClumpState::Standing);
    // 受伤间隔内再打不掉血
    let events = hit(&mut sim, def.hp * 0.6);
    assert_eq!(state(&sim, i), ClumpState::Standing);
    assert!(!events.iter().any(|e| matches!(e, SimEvent::BambooBroken { .. })));
    for _ in 0..(def.hit_every * 60.0) as u32 {
        sim.step(InputFrame::default(), &[]);
    }
    let events = hit(&mut sim, def.hp * 0.6);
    assert!(matches!(state(&sim, i), ClumpState::Broken(_)));
    assert!(events.iter().any(|e| matches!(*e, SimEvent::BambooBroken { pos } if pos == at)));

    // 站在旁边不长回来；走远了到时间才长
    teleport(&mut sim, at + Vec2::new(def.regrow_clear * 0.5, 0.0));
    for _ in 0..(def.regrow * 60.0) as u32 + 10 {
        sim.step(InputFrame::default(), &[]);
    }
    assert!(matches!(state(&sim, i), ClumpState::Broken(_)), "主角在旁边时不长");
    teleport(&mut sim, at + Vec2::new(def.regrow_clear * 2.0, 0.0));
    sim.step(InputFrame::default(), &[]);
    assert_eq!(state(&sim, i), ClumpState::Standing);
    assert_eq!(sim.world().resource::<Bamboo>().clumps[i].hp, def.hp);
}

#[test]
fn the_boss_barrier_burns_the_clumps_inside() {
    let c = content();
    let mut s = RunSetup::new(2, RunMode::Normal);
    s.god = true;
    let mut sim = SimHarness::with_setup(content(), s);
    // 时间表只留夜主，马上登场
    let mut plan = sim.world().resource::<lantern_sim::run::RunPlan>().clone();
    sim.quiet();
    sim.set_build(&[], &[]);
    plan.schedule
        .retain(|st| matches!(c.run.schedule[st.index].event, lantern_content::PlanEvent::Boss { .. }));
    for st in &mut plan.schedule {
        st.at = 1.0 / 60.0;
    }
    sim.world_mut().resource_mut::<lantern_sim::run::RunPlan>().schedule = plan.schedule;
    let mut burned = false;
    for _ in 0..10 {
        sim.step(InputFrame::default(), &[]);
        burned |= sim.take_events().iter().any(|e| matches!(e, SimEvent::BambooBurned { .. }));
    }
    assert!(burned);
    let (center, r) = sim.world().resource::<lantern_sim::run::Director>().barrier.unwrap();
    let b = sim.world().resource::<Bamboo>();
    let inside: Vec<_> = b.clumps.iter().filter(|c| c.pos.distance(center) < r).collect();
    assert!(!inside.is_empty());
    assert!(inside.iter().all(|c| c.state == ClumpState::Burned));
    assert!(b.clumps.iter().any(|c| c.pos.distance(center) > r && c.state == ClumpState::Standing));
}
