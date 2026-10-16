//! 铜钱剑 / 天罡（docs/BALANCE.md 第 6.3 节）：朝最近的妖物挥扇形剑气、从近到远最多打 count 只、
//! 自带暴击率；天罡一整圈，暴击的那一下再斩一次。

mod common;

use bevy_math::{Vec2, ops};
use lantern_content::{Stat, WeaponBehavior};
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
    dummy(&mut sim, Vec2::new(500.0, 0.0));
    // 远处妖物不影响近身瞄准；往下走一步，面向变成下
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

#[test]
fn fan_angle_and_radius_match_the_swing_event() {
    for (angle, distance, expected) in [
        (59.0_f32, 60.0, true),
        (-59.0, 60.0, true),
        (61.0, 60.0, false),
        (-61.0, 60.0, false),
        (180.0, 60.0, false),
        (0.0, 80.0, true),
        (0.0, 81.0, false),
    ] {
        let mut sim = quiet(35);
        sim.set_build(&[("coin_sword", 1, false)], &[]);
        let p = player_pos(&mut sim);
        dummy(&mut sim, p + Vec2::new(30.0, 0.0));
        let a = angle.to_radians();
        let i = dummy(&mut sim, p + Vec2::new(ops::cos(a), ops::sin(a)) * distance);
        sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 0.0;
        sim.step(InputFrame::default(), &[]);
        let events = sim.take_events();
        assert!(events.iter().any(|e| matches!(e,
            SimEvent::Sweep { pos, dir, radius: 70.0, arc, evolved: false, .. }
                if *pos == p && *dir == Vec2::X && (*arc - 2.0944).abs() < 1e-5
        )));
        assert_eq!(
            events.iter().any(|e| matches!(e,
                SimEvent::Hit { target, .. } if target.raw() & 0x1FFF == i as u32
            )),
            expected,
            "角度 {angle}°，距离 {distance}，妖物半径 10"
        );
    }
}

#[test]
fn sweep_applies_area_amount_and_cooldown_bonuses() {
    let mut c = content();
    c.stats[Stat::Area as usize].base = 1.5;
    c.stats[Stat::Amount as usize].base = 2.0;
    c.stats[Stat::Cooldown as usize].base = 0.75;
    let mut sim = SimHarness::new(c, 36);
    sim.quiet();
    sim.set_build(&[("coin_sword", 1, false)], &[]);
    let p = player_pos(&mut sim);
    for k in 0..6 {
        let i = dummy(&mut sim, p + Vec2::new(30.0 + k as f32 * 14.0, 0.0));
        // 只测法器覆盖；去掉测试靶子的互相挤压。
        sim.world_mut().resource_mut::<Enemies>().r[i] = 0.0;
    }
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 0.0;
    let weapon = coin(&sim);
    let (_, hits, _) = next_swing(&mut sim, weapon);
    assert_eq!(hits.len(), 5);
    assert_eq!(sim.arsenal().0[0].count, 5);
    assert_eq!(sim.arsenal().0[0].radius, 105.0);
    assert!((sim.arsenal().0[0].timer - 0.9).abs() < 1e-6);
}

#[test]
fn tiangang_echoes_once_and_only_while_the_target_survives() {
    for lethal in [false, true] {
        let mut c = content();
        c.stats[Stat::CritChance as usize].base = 1.0;
        let mut sim = SimHarness::new(c, 37);
        sim.quiet();
        sim.set_build(&[("coin_sword", 8, true)], &[]);
        let p = player_pos(&mut sim);
        let at = p + Vec2::new(50.0, 0.0);
        let i = dummy(&mut sim, at);
        if lethal {
            sim.world_mut().resource_mut::<Enemies>().hp[i] = 1.0;
        }
        sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 0.0;
        sim.step(InputFrame::default(), &[]);
        let events = sim.take_events();
        let hits: Vec<_> = events
            .iter()
            .filter_map(|e| match e {
                SimEvent::Hit { source: Source::Weapon(_), damage, crit, .. } => Some((*damage, *crit)),
                _ => None,
            })
            .collect();
        let echoes: Vec<_> = events
            .iter()
            .filter_map(|e| match e {
                SimEvent::SweepEcho { pos, weapon } => Some((*pos, *weapon)),
                _ => None,
            })
            .collect();
        assert_eq!(hits.len(), if lethal { 1 } else { 2 });
        assert!(hits.iter().all(|(_, crit)| *crit));
        if lethal {
            assert!(echoes.is_empty(), "已被首击击杀，不应播放未发生的再斩");
        } else {
            assert_eq!(hits[0], hits[1], "再斩伤害倍率为 1，独立结算且不递归再斩");
            assert_eq!(echoes, [(at, coin(&sim))]);
        }
    }
}

#[test]
fn coin_sword_requires_max_level_and_ruimu_to_evolve() {
    let c = content();
    for (level, key, expected) in [(7, true, false), (8, false, false), (8, true, true)] {
        let mut sim = quiet(38);
        sim.set_build(&[("coin_sword", level, false)], if key { &[("ruimu", 1)] } else { &[] });
        assert_eq!(sim.arsenal().0[0].can_evolve(&c, sim.build()), expected);
        if expected {
            let mut arsenal = lantern_sim::Arsenal(sim.arsenal().0.clone());
            let mut build = sim.build().clone();
            assert_eq!(
                lantern_sim::build::apply_offer(&c, &mut arsenal, &mut build, lantern_sim::Offer::Evolve(0)),
                Some(0)
            );
            assert_eq!(arsenal.0[0].name(&c), "天罡");
            assert!(
                matches!(arsenal.0[0].behavior(&c), WeaponBehavior::Sweep { arc, echo: 1.0, .. } if *arc >= std::f32::consts::TAU)
            );
        }
    }
}

#[test]
fn coin_sword_recording_replays_hits_and_sweeps() {
    let mut c = content();
    // 仅给这个回放场景配置铜钱剑起手，之后升级、命中和输入都由正常模拟产生。
    c.lamps[0].start_weapon = "coin_sword".into();
    let mut setup = RunSetup::new(39, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(c.clone(), setup);
    sim.record("coin_sword_test");
    let mut events = Vec::new();
    for _ in 0..1800 {
        common::bot_step(&mut sim, InputFrame::default(), &[]);
        events.extend(sim.take_events());
    }
    assert!(events.iter().any(|e| matches!(e, SimEvent::Sweep { .. })));
    let weapon = coin(&sim);
    assert!(events.iter().any(|e| matches!(e, SimEvent::Hit { weapon: Some(w), .. } if *w == weapon)));
    let replay = lantern_sim::Replay::parse(&sim.replay().unwrap().to_ron()).unwrap();
    let mut played = SimHarness::from_replay(c, replay);
    let mut replayed_events = Vec::new();
    while !played.playback().unwrap().finished {
        played.step(InputFrame::default(), &[]);
        replayed_events.extend(played.take_events());
    }
    played.playback().unwrap().verification_result(played.tick()).unwrap();
    assert_eq!(played.hashes(), sim.hashes());
    assert_eq!(replayed_events, events);
}
