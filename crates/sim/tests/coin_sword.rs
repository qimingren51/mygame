//! 铜钱剑 / 天罡（docs/BALANCE.md 第 6.3 节）：朝最近的妖物挥扇形剑气、从近到远最多打 count 只、
//! 自带暴击率；天罡一整圈，暴击的那一下再斩一次。

mod common;

use bevy_math::Vec2;
use lantern_sim::combat::Source;
use lantern_sim::enemies::Enemies;
use lantern_sim::{InputFrame, Player, Pos, RunMode, RunSetup, SimEvent, SimHarness};

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

/// 摆一只打不死、不会动的小妖（疾影，半径 10，摆开了不会互相推）。
fn dummy(sim: &mut SimHarness, at: Vec2) -> usize {
    let i = sim.spawn("wisp", at).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.hp[i] = 1e9;
    en.max_hp[i] = 1e9;
    en.speed[i] = 0.0;
    i
}

/// 每挥一下之前把它们摆回原位，免得被击退推出范围。
fn reset(sim: &mut SimHarness, placed: &[(usize, Vec2)]) {
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    for &(i, at) in placed {
        en.x[i] = at.x;
        en.y[i] = at.y;
        en.px[i] = at.x;
        en.py[i] = at.y;
        en.kx[i] = 0.0;
        en.ky[i] = 0.0;
    }
}

fn coin(sim: &SimHarness) -> u16 {
    sim.world().resource::<lantern_sim::GameContent>().0.weapon_index("coin_sword").unwrap() as u16
}

/// 挥到下一次出手为止，返回这一下的 Sweep 事件和命中了哪些妖物（按槽位）。
fn next_swing(sim: &mut SimHarness, weapon: u16) -> (Vec2, Vec<u32>, usize) {
    for _ in 0..240 {
        sim.step(InputFrame::default(), &[]);
        let events = sim.take_events();
        let Some(dir) = events.iter().find_map(|e| match e {
            SimEvent::Sweep { dir, weapon: w, .. } if *w == weapon => Some(*dir),
            _ => None,
        }) else {
            continue;
        };
        // 命中在下一个阶段结算，同一步里就有
        let hits: Vec<u32> = events
            .iter()
            .filter_map(|e| match e {
                SimEvent::Hit { source: Source::Weapon(w), target, .. } if *w == weapon => {
                    Some(target.raw() & 0x1FFF)
                }
                _ => None,
            })
            .collect();
        let crits = events
            .iter()
            .filter(
                |e| matches!(e, SimEvent::Hit { source: Source::Weapon(w), crit: true, .. } if *w == weapon),
            )
            .count();
        return (dir, hits, crits);
    }
    panic!("铜钱剑没有出手");
}

#[test]
fn coin_sword_swings_at_the_nearest_enemy_and_hits_the_closest_few_in_its_fan() {
    let mut sim = quiet(31);
    sim.set_build(&[("coin_sword", 1, false)], &[]);
    let weapon = coin(&sim);
    let p = player_pos(&mut sim);
    // 右边四只（都在扇形里，从近到远），左边一只（扇形外）；1 级最多打 3 只
    let spots = [Vec2::new(30.0, 0.0), Vec2::new(45.0, 22.0), Vec2::new(45.0, -22.0), Vec2::new(62.0, 0.0)];
    let right: Vec<usize> = spots.iter().map(|&o| dummy(&mut sim, p + o)).collect();
    let left = dummy(&mut sim, p + Vec2::new(-45.0, 0.0));
    let mut placed: Vec<(usize, Vec2)> = right.iter().zip(spots).map(|(&i, o)| (i, p + o)).collect();
    placed.push((left, p + Vec2::new(-45.0, 0.0)));
    // 第一下出手之前一直摆着
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 1.0 / 60.0;
    reset(&mut sim, &placed);
    let (dir, hits, _) = next_swing(&mut sim, weapon);
    assert!(dir.x > 0.9, "朝最近的妖物（右边）挥：{dir:?}");
    assert_eq!(hits.len(), 3, "1 级最多打 3 只：{hits:?}");
    for i in &right[..3] {
        assert!(hits.contains(&(*i as u32)), "从近到远打最近的三只");
    }
    assert!(!hits.contains(&(left as u32)), "扇形外的不打");
}

#[test]
fn coin_sword_swings_toward_facing_when_nothing_is_near() {
    let mut sim = quiet(32);
    sim.set_build(&[("coin_sword", 1, false)], &[]);
    let weapon = coin(&sim);
    // 往下走一步，面向变成下
    sim.step(InputFrame::quantize(Vec2::new(0.0, -1.0)), &[]);
    let (dir, hits, _) = next_swing(&mut sim, weapon);
    assert!(hits.is_empty());
    assert!(dir.y < -0.9, "没有妖物就朝面向：{dir:?}");
}

#[test]
fn coin_sword_has_its_own_crit_bonus() {
    let mut sim = quiet(33);
    sim.set_build(&[("coin_sword", 8, false)], &[]);
    let weapon = coin(&sim);
    let p = player_pos(&mut sim);
    let i = dummy(&mut sim, p + Vec2::new(40.0, 0.0));
    let base = sim.stats().get(lantern_content::Stat::CritChance);
    let (mut n, mut crit) = (0, 0);
    for _ in 0..400 {
        reset(&mut sim, &[(i, p + Vec2::new(40.0, 0.0))]);
        let (_, hits, c) = next_swing(&mut sim, weapon);
        n += hits.len();
        crit += c;
    }
    let rate = crit as f32 / n as f32;
    assert!((rate - (base + 0.15)).abs() < 0.06, "暴击率 {rate}，应约 {}", base + 0.15);
}

#[test]
fn tiangang_hits_all_around_and_slashes_again_on_crit() {
    let mut sim = quiet(34);
    sim.set_build(&[("coin_sword", 8, true)], &[]);
    let weapon = coin(&sim);
    let p = player_pos(&mut sim);
    let placed: Vec<(usize, Vec2)> = (0..4)
        .map(|k| {
            let a = k as f32 * std::f32::consts::FRAC_PI_2;
            let at = p + Vec2::new(50.0 * bevy_math::ops::cos(a), 50.0 * bevy_math::ops::sin(a));
            (dummy(&mut sim, at), at)
        })
        .collect();
    let around: Vec<usize> = placed.iter().map(|&(i, _)| i).collect();
    let mut echoed = false;
    for _ in 0..60 {
        reset(&mut sim, &placed);
        let (_, hits, crits) = next_swing(&mut sim, weapon);
        for i in &around {
            assert!(hits.contains(&(*i as u32)), "一整圈，四面都打到");
        }
        // 每一下暴击多一下再斩
        if crits > 0 && hits.len() > around.len() {
            echoed = true;
        }
        assert!(hits.len() <= around.len() * 2);
    }
    assert!(echoed, "暴击时再斩一次");
}
