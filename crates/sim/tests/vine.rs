//! 青藤：目标持有、断藤重连、实际伤害回复、缠绕与回放。
mod common;

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_content::{Content, Stat};
use lantern_sim::build::offers;
use lantern_sim::enemies::Enemies;
use lantern_sim::{Arsenal, Health, InputFrame, Offer, Player, Replay, RunMode, RunSetup, SimHarness};

fn content() -> Content {
    let mut c = common::content();
    c.stats[Stat::CritChance as usize].base = 0.0;
    c.stats[Stat::Regen as usize].base = 0.0;
    c.stats[Stat::Regen as usize].max = 0.0;
    c.stats[Stat::RegenFlat as usize].base = 0.0;
    c.enemies.iter_mut().for_each(|e| e.element = None);
    c
}

fn arena(level: u32, evolved: bool) -> SimHarness {
    let mut setup = RunSetup::new(37, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.quiet();
    sim.set_build(&[("vine", level, evolved)], &[]);
    sim
}

fn dummy(sim: &mut SimHarness, kind: &str, pos: Vec2) -> usize {
    let i = sim.spawn(kind, pos).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.hp[i] = 100_000.0;
    en.max_hp[i] = 100_000.0;
    en.speed[i] = 0.0;
    en.grace[i] = 0.0;
    i
}

fn step(sim: &mut SimHarness, n: usize) {
    for _ in 0..n {
        sim.step(InputFrame::default(), &[]);
    }
}

fn hp(sim: &mut SimHarness, value: f32) {
    let world = sim.world_mut();
    world.query_filtered::<&mut Health, With<Player>>().single_mut(world).unwrap().hp = value;
}

fn targets(sim: &SimHarness) -> Vec<usize> {
    sim.arsenal().0[0]
        .vine
        .as_ref()
        .unwrap()
        .links
        .iter()
        .filter_map(|l| l.target.and_then(|h| sim.enemies().resolve(h)))
        .collect()
}

#[test]
fn nearest_distinct_targets_stay_linked_until_the_break_distance() {
    let mut sim = arena(1, false);
    let near = dummy(&mut sim, "wisp", Vec2::new(60.0, 0.0));
    let middle = dummy(&mut sim, "wisp", Vec2::new(100.0, 0.0));
    let farther = dummy(&mut sim, "wisp", Vec2::new(-130.0, 0.0));
    let hidden = dummy(&mut sim, "wisp", Vec2::new(0.0, 45.0));
    sim.world_mut().resource_mut::<Enemies>().cloaked[hidden] = true;
    step(&mut sim, 1);
    assert_eq!(targets(&sim), [near, middle]);
    sim.world_mut().resource_mut::<Enemies>().x[middle] = 170.0;
    step(&mut sim, 1);
    assert_eq!(targets(&sim), [near, middle], "超过选敌半径但未超过断藤半径，不抖动换目标");
    sim.world_mut().resource_mut::<Enemies>().x[middle] = 190.0;
    step(&mut sim, 1);
    assert_eq!(targets(&sim), [near]);
    step(&mut sim, 17);
    assert_eq!(targets(&sim), [near], "断藤后需等待0.3秒，不能立即粘上另一只");
    step(&mut sim, 2);
    assert_eq!(targets(&sim), [near, farther]);
}

#[test]
fn a_reused_enemy_slot_cannot_inherit_the_old_link() {
    let mut sim = arena(1, false);
    let old = dummy(&mut sim, "wisp", Vec2::new(70.0, 0.0));
    dummy(&mut sim, "wisp", Vec2::new(-70.0, 0.0));
    step(&mut sim, 1);
    let handle = sim.enemies().handle(old);
    sim.world_mut().resource_mut::<Enemies>().kill(old);
    let new = dummy(&mut sim, "wisp", Vec2::new(70.0, 0.0));
    assert_eq!(new, old);
    assert_ne!(sim.enemies().handle(new), handle);
    step(&mut sim, 1);
    assert!(!targets(&sim).contains(&new));
    step(&mut sim, 19);
    assert!(targets(&sim).contains(&new));
}

#[test]
fn leech_uses_actual_damage_and_a_shared_one_second_budget() {
    let mut sim = arena(1, false);
    hp(&mut sim, 50.0);
    let victim = dummy(&mut sim, "wisp", Vec2::new(70.0, 0.0));
    sim.world_mut().resource_mut::<Enemies>().hp[victim] = 1.0;
    sim.world_mut().resource_mut::<Arsenal>().0[0].timer = 0.0;
    step(&mut sim, 1);
    assert!((sim.player_hp() - 50.04).abs() < 0.001, "过量伤害不能算入吸血");

    let mut sim = arena(8, true);
    hp(&mut sim, 50.0);
    for pos in [Vec2::new(70.0, 0.0), Vec2::new(-70.0, 0.0), Vec2::new(0.0, 90.0)] {
        dummy(&mut sim, "wisp", pos);
    }
    sim.world_mut().resource_mut::<Arsenal>().0[0].timer = 0.0;
    step(&mut sim, 1);
    assert!((sim.player_hp() - 52.5).abs() < 0.001);
    step(&mut sim, 35);
    assert!((sim.player_hp() - 52.5).abs() < 0.001, "下一跳仍共用同一秒预算");
    step(&mut sim, 30);
    assert!((sim.player_hp() - 55.0).abs() < 0.001, "进入下一秒才恢复回复预算");
}

#[test]
fn leech_does_not_revive_a_dead_player() {
    let mut sim = arena(8, true);
    dummy(&mut sim, "wisp", Vec2::new(80.0, 0.0));
    sim.world_mut().resource_mut::<Arsenal>().0[0].timer = 0.0;
    hp(&mut sim, 0.0);
    step(&mut sim, 1);
    assert_eq!(sim.player_hp(), 0.0);
}

#[test]
fn wanmuchun_binds_linked_enemies_but_respects_elites_and_bosses() {
    let mut sim = arena(8, true);
    let normal = dummy(&mut sim, "wisp", Vec2::new(100.0, 0.0));
    let elite = dummy(&mut sim, "fox", Vec2::new(-100.0, 0.0));
    let boss = dummy(&mut sim, "jiuwei", Vec2::new(0.0, 150.0));
    step(&mut sim, 1);
    assert_eq!(sim.enemies().root[normal], 0.0, "进化后仍从四秒节拍开始缠绕");
    sim.world_mut().resource_mut::<Arsenal>().0[0].vine.as_mut().unwrap().bind_t = Some(0.0);
    step(&mut sim, 1);
    assert!(sim.enemies().root[normal] > 0.98);
    assert!((sim.enemies().root[elite] - 0.5).abs() < 0.001);
    assert_eq!(sim.enemies().root[boss], 0.0);
    assert!(sim.arsenal().0[0].vine.as_ref().unwrap().bind_t.unwrap() > 3.9);
}

#[test]
fn binding_period_uses_cooldown_without_shortening_the_root() {
    let mut c = content();
    c.stats[Stat::Cooldown as usize].base = 0.6;
    let mut sim = SimHarness::new(c, 37);
    sim.quiet();
    sim.set_build(&[("vine", 8, true)], &[]);
    let victim = dummy(&mut sim, "wisp", Vec2::new(90.0, 0.0));
    step(&mut sim, 143);
    assert_eq!(sim.enemies().root[victim], 0.0);
    step(&mut sim, 2);
    assert!(sim.enemies().root[victim] > 0.97, "2.4秒出手，仍缠绕完整一秒");
    let next = sim.arsenal().0[0].vine.as_ref().unwrap().bind_t.unwrap();
    assert!((2.36..=2.41).contains(&next), "下一次缠绕也应采用冷却倍率：{next}");
}

#[test]
fn vine_evolution_requires_huichun_and_real_max_level() {
    let c = content();
    let mut sim = arena(8, false);
    assert!(!offers(&c, sim.arsenal(), sim.build(), 60.0).iter().any(|(o, _)| *o == Offer::Evolve(0)));
    sim.set_build(&[("vine", 7, false)], &[("huichun", 1)]);
    assert!(!sim.arsenal().0[0].can_evolve(&c, sim.build()));
    sim.set_build(&[("vine", 8, false)], &[("huichun", 1)]);
    assert!(offers(&c, sim.arsenal(), sim.build(), 60.0).iter().any(|(o, _)| *o == Offer::Evolve(0)));
}

#[test]
fn vine_links_and_healing_replay_deterministically() {
    let mut c = content();
    c.lamps[0].start_weapon = "vine".into();
    let mut setup = RunSetup::new(42, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(c.clone(), setup);
    sim.record("vine-test");
    for _ in 0..45 * 60 {
        lantern_sim::bot::step(&mut sim, InputFrame::default(), &[]);
    }
    assert!(sim.arsenal().0[0].vine.as_ref().is_some_and(|v| v.links.iter().any(|l| l.target.is_some())));
    let replay = Replay::parse(&sim.replay().unwrap().to_ron()).unwrap();
    let hashes = sim.hashes().to_vec();
    let mut played = SimHarness::from_replay(c, replay);
    while !played.playback().unwrap().finished {
        played.step(InputFrame::default(), &[]);
    }
    assert_eq!(played.playback().unwrap().diverged_at, None);
    played.playback().unwrap().verification_result(played.tick()).unwrap();
    assert_eq!(played.hashes(), hashes);
    assert_eq!(played.arsenal().0[0].vine, sim.arsenal().0[0].vine);
}
