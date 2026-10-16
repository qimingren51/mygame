//! 沧浪 / 北冥潮（docs/BALANCE.md 第 6.3 节）：朝面向推浪（站着不动朝最近的妖物），碰到的妖物打一次、
//! 减速、推着走（精英一半）；数量加成左右偏开；北冥潮一圈往外推、冻结。

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

/// 摆一只打不死、自己不会动的妖物。
fn dummy(sim: &mut SimHarness, id: &str, at: Vec2) -> usize {
    let i = sim.spawn(id, at).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.hp[i] = 1e9;
    en.max_hp[i] = 1e9;
    en.speed[i] = 0.0;
    i
}

fn at(sim: &SimHarness, i: usize) -> Vec2 {
    let en = sim.world().resource::<Enemies>();
    Vec2::new(en.x[i], en.y[i])
}

fn wave(sim: &SimHarness) -> u16 {
    sim.world().resource::<lantern_sim::GameContent>().0.weapon_index("wave").unwrap() as u16
}

/// 下一步就出浪（input 决定这一步走不走），然后站着走完 steps 步。
/// 返回推出的浪的方向和每只妖物被这件法器打了几下。
fn push_out(sim: &mut SimHarness, input: InputFrame, steps: u32) -> (Vec<Vec2>, Vec<u32>) {
    let weapon = wave(sim);
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 1.0 / 60.0;
    let (mut dirs, mut hits) = (Vec::new(), Vec::new());
    for k in 0..steps {
        sim.step(if k == 0 { input } else { InputFrame::default() }, &[]);
        for e in sim.take_events() {
            match e {
                SimEvent::Wave { dir, .. } => dirs.push(dir),
                SimEvent::Hit { source: Source::Weapon(w), target, .. } if w == weapon => {
                    hits.push(target.raw() & 0x1FFF)
                }
                _ => {}
            }
        }
        // 只看这一道浪
        sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 99.0;
    }
    (dirs, hits)
}

#[test]
fn wave_pushes_along_facing_slows_and_carries() {
    let mut sim = quiet(51);
    sim.set_build(&[("wave", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let a = dummy(&mut sim, "wisp", p + Vec2::new(80.0, 0.0));
    let off = dummy(&mut sim, "wisp", p + Vec2::new(80.0, 120.0));
    let elite = dummy(&mut sim, "stonelord", p + Vec2::new(90.0, -40.0));
    let (a0, e0, off0) = (at(&sim, a), at(&sim, elite), at(&sim, off));
    // 往右走一步：浪朝右；0.5 秒时看减速，再等它推完
    let (dirs, hits) = push_out(&mut sim, InputFrame::quantize(Vec2::new(1.0, 0.0)), 30);
    let slowed = sim.world().resource::<Enemies>().slow_amount[a];
    assert!(slowed >= 0.4 - 1e-4, "减速 40%：{slowed}");
    for _ in 0..90 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(dirs.len(), 1);
    assert!(dirs[0].x > 0.99, "朝面向：{:?}", dirs[0]);
    assert_eq!(hits.iter().filter(|&&h| h == a as u32).count(), 1, "每道浪只打一次");
    assert_eq!(hits.iter().filter(|&&h| h == elite as u32).count(), 1);
    assert!(!hits.contains(&(off as u32)), "宽度外的不打");
    let pushed = at(&sim, a).x - a0.x;
    assert!((pushed - 140.0).abs() < 15.0, "推 140 左右：{pushed}");
    let pushed_elite = at(&sim, elite).x - e0.x;
    assert!((pushed_elite - 70.0).abs() < 15.0, "精英推一半：{pushed_elite}");
    assert!(at(&sim, off).distance(off0) < 1.0);
}

#[test]
fn wave_aims_at_the_nearest_enemy_when_standing_still() {
    let mut sim = quiet(52);
    sim.set_build(&[("wave", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let up = dummy(&mut sim, "wisp", p + Vec2::new(0.0, 100.0));
    let (dirs, hits) = push_out(&mut sim, InputFrame::default(), 60);
    assert!(dirs[0].y > 0.99, "站着不动朝最近的妖物：{:?}", dirs[0]);
    assert!(hits.contains(&(up as u32)));
}

#[test]
fn extra_waves_fan_out_left_and_right() {
    let mut sim = quiet(53);
    // 折纸 1 级：数量 +1 → 两道浪
    sim.set_build(&[("wave", 1, false)], &[("zhezhi", 1)]);
    let (dirs, _) = push_out(&mut sim, InputFrame::quantize(Vec2::new(1.0, 0.0)), 2);
    assert_eq!(dirs.len(), 2);
    let a = bevy_math::ops::atan2(dirs[1].y, dirs[1].x) - bevy_math::ops::atan2(dirs[0].y, dirs[0].x);
    assert!((a.abs() - 25f32.to_radians()).abs() < 0.01, "偏 25°：{}", a.to_degrees());
}

#[test]
fn beiming_tide_rings_out_pushes_away_and_freezes() {
    let mut sim = quiet(54);
    sim.set_build(&[("wave", 8, true)], &[]);
    let p = player_pos(&mut sim);
    let around: Vec<usize> = (0..4)
        .map(|k| {
            let a = k as f32 * std::f32::consts::FRAC_PI_2;
            dummy(
                &mut sim,
                "wisp",
                p + Vec2::new(100.0 * bevy_math::ops::cos(a), 100.0 * bevy_math::ops::sin(a)),
            )
        })
        .collect();
    let mut frozen = vec![false; around.len()];
    let weapon = wave(&sim);
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 1.0 / 60.0;
    let mut hits = Vec::new();
    for _ in 0..90 {
        sim.step(InputFrame::default(), &[]);
        for e in sim.take_events() {
            if let SimEvent::Hit { source: Source::Weapon(w), target, .. } = e
                && w == weapon
            {
                hits.push(target.raw() & 0x1FFF);
            }
        }
        let en = sim.world().resource::<Enemies>();
        for (k, &i) in around.iter().enumerate() {
            frozen[k] |= en.frozen[i] > 0.0;
        }
        sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 99.0;
    }
    for (k, &i) in around.iter().enumerate() {
        assert_eq!(hits.iter().filter(|&&h| h == i as u32).count(), 1, "一圈只打一次");
        assert!(frozen[k], "冻结");
        let d = at(&sim, i).distance(p);
        assert!((d - 260.0).abs() < 20.0, "往外推 160 左右：离主角 {d}");
    }
}
