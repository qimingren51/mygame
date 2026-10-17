//! 青藤 / 万木春（docs/BALANCE.md 第 6.3 节）：连最近的几只、定时跳伤害、按伤害回血（有每秒上限）；
//! 目标走远就断、过一会儿接新的；万木春定时缠住。

mod common;

use bevy_math::Vec2;
use lantern_sim::combat::Source;
use lantern_sim::enemies::Enemies;
use lantern_sim::weapons::vine::Vines;
use lantern_sim::{Health, InputFrame, Player, Pos, RunMode, RunSetup, SimEvent, SimHarness};

use common::content;

fn quiet(seed: u64) -> SimHarness {
    let mut s = RunSetup::new(seed, RunMode::Normal);
    s.god = true;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim
}

fn player_pos(sim: &mut SimHarness) -> Vec2 {
    let world = sim.world_mut();
    world.query_filtered::<&Pos, bevy_ecs::query::With<Player>>().single(world).unwrap().0
}

fn hp(sim: &mut SimHarness) -> f32 {
    let world = sim.world_mut();
    world.query_filtered::<&Health, bevy_ecs::query::With<Player>>().single(world).unwrap().hp
}

fn set_hp(sim: &mut SimHarness, v: f32) {
    let world = sim.world_mut();
    world.query_filtered::<&mut Health, bevy_ecs::query::With<Player>>().single_mut(world).unwrap().hp = v;
}

/// 摆一只打不死、不会动的小妖。
fn dummy(sim: &mut SimHarness, at: Vec2) -> usize {
    let i = sim.spawn("wisp", at).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.hp[i] = 1e9;
    en.max_hp[i] = 1e9;
    en.speed[i] = 0.0;
    i
}

fn move_to(sim: &mut SimHarness, i: usize, at: Vec2) {
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.x[i] = at.x;
    en.y[i] = at.y;
    en.px[i] = at.x;
    en.py[i] = at.y;
}

fn vine(sim: &SimHarness) -> u16 {
    sim.world().resource::<lantern_sim::GameContent>().0.weapon_index("vine").unwrap() as u16
}

fn linked(sim: &SimHarness) -> Vec<u32> {
    let vines = sim.world().resource::<Vines>();
    vines.0.iter().flat_map(|v| v.links.iter().filter_map(|l| l.target.map(|t| t.raw() & 0x1FFF))).collect()
}

/// 走 steps 步，返回青藤打了谁（按槽位，一跳一条）和主角回了多少血。
fn run(sim: &mut SimHarness, steps: u32) -> (Vec<u32>, f32) {
    let weapon = vine(sim);
    let (mut hits, mut healed) = (Vec::new(), 0.0);
    for _ in 0..steps {
        sim.step(InputFrame::default(), &[]);
        for e in sim.take_events() {
            match e {
                SimEvent::Hit { source: Source::Weapon(w), target, .. } if w == weapon => {
                    hits.push(target.raw() & 0x1FFF)
                }
                SimEvent::PlayerHealed { amount } => healed += amount,
                _ => {}
            }
        }
    }
    (hits, healed)
}

#[test]
fn vine_links_the_nearest_few_and_ticks_them() {
    let mut sim = quiet(61);
    sim.set_build(&[("vine", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let near: Vec<usize> = [60.0, 95.0].iter().map(|&d| dummy(&mut sim, p + Vec2::new(d, 0.0))).collect();
    let third = dummy(&mut sim, p + Vec2::new(-125.0, 0.0));
    let far = dummy(&mut sim, p + Vec2::new(0.0, 200.0));
    // 第一跳在 0.6 秒，之后每 0.5 秒：2.5 秒里 4 跳
    let (hits, _) = run(&mut sim, 150);
    let mut l = linked(&sim);
    l.sort();
    assert_eq!(l, vec![near[0] as u32, near[1] as u32], "1 级两根藤，连最近的两只");
    for &i in &near {
        let n = hits.iter().filter(|&&h| h == i as u32).count();
        assert_eq!(n, 4, "每 0.5 秒一跳");
    }
    assert!(!hits.contains(&(third as u32)) && !hits.contains(&(far as u32)));
}

#[test]
fn vine_heals_a_share_of_damage_up_to_a_cap() {
    let mut sim = quiet(62);
    sim.set_build(&[("vine", 1, false)], &[]);
    let p = player_pos(&mut sim);
    for d in [60.0, 95.0] {
        dummy(&mut sim, p + Vec2::new(d, 0.0));
    }
    set_hp(&mut sim, 10.0);
    let (_, healed) = run(&mut sim, 240);
    // 每跳 2 × 6 × 4% = 0.48，超过 1 级的上限 (0.5 + 0.125) × 0.5 = 0.3125；4 秒里 7 跳（0.6、1.1……3.6 秒）
    let per_tick = (0.5 + 0.125) * 0.5;
    assert!((healed - per_tick * 7.0).abs() < 0.05, "回血 {healed}，应约 {}", per_tick * 7.0);
    assert!(hp(&mut sim) > 10.0);
}

#[test]
fn vine_breaks_when_the_target_walks_off_and_relinks() {
    let mut sim = quiet(63);
    sim.set_build(&[("vine", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let a = dummy(&mut sim, p + Vec2::new(60.0, 0.0));
    let b = dummy(&mut sim, p + Vec2::new(95.0, 0.0));
    let c = dummy(&mut sim, p + Vec2::new(-125.0, 0.0));
    run(&mut sim, 10);
    assert!(linked(&sim).contains(&(a as u32)));
    // 走出 140 + 40：断开；0.3 秒内不接，之后接上第三只
    move_to(&mut sim, a, p + Vec2::new(0.0, 190.0));
    run(&mut sim, 1);
    assert!(!linked(&sim).contains(&(a as u32)), "走远就断");
    assert!(!linked(&sim).contains(&(c as u32)), "0.3 秒后才接新的");
    run(&mut sim, 20);
    let mut l = linked(&sim);
    l.sort();
    assert_eq!(l, vec![b as u32, c as u32], "接上还没连的最近一只");
}

#[test]
fn wanmuchun_binds_its_targets_every_four_seconds() {
    let mut sim = quiet(64);
    sim.set_build(&[("vine", 8, true)], &[]);
    let p = player_pos(&mut sim);
    let around: Vec<usize> = (0..10)
        .map(|k| {
            let a = k as f32 * std::f32::consts::TAU / 10.0;
            dummy(&mut sim, p + Vec2::new(150.0 * bevy_math::ops::cos(a), 150.0 * bevy_math::ops::sin(a)))
        })
        .collect();
    let mut rooted = 0;
    let mut binds = 0;
    for _ in 0..300 {
        sim.step(InputFrame::default(), &[]);
        binds +=
            sim.take_events().iter().filter(|e| matches!(e, SimEvent::VineDrain { bind: true, .. })).count();
        let en = sim.world().resource::<Enemies>();
        rooted = rooted.max(around.iter().filter(|&&i| en.root[i] > 0.0).count());
    }
    assert_eq!(linked(&sim).len(), 8, "同时连八只");
    assert_eq!(rooted, 8, "连着的八只一起缠住");
    assert_eq!(binds, 8, "5 秒里缠一次（每 4 秒）");
}
