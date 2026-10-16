//! 镇妖塔 / 玲珑塔（docs/BALANCE.md 第 6.3 节）：预警后落在妖物最密处、砸晕一片；立着时把周围的妖物往塔下吸
//! （精英一半）、定时跳伤害；到时间收走，玲珑塔炸开。

mod common;

use bevy_math::Vec2;
use lantern_sim::combat::Source;
use lantern_sim::enemies::Enemies;
use lantern_sim::weapons::tower::Towers;
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

fn tower(sim: &SimHarness) -> u16 {
    sim.world().resource::<lantern_sim::GameContent>().0.weapon_index("tower").unwrap() as u16
}

#[derive(Default)]
struct Log {
    land: Option<(u32, Vec2)>,
    burst: Option<u32>,
    hits: Vec<u32>,
}

/// 从下一步起落一座塔（之后不再落），走 steps 步。
fn drop_tower(sim: &mut SimHarness, steps: u32, mut each: impl FnMut(&mut SimHarness, u32)) -> Log {
    let weapon = tower(sim);
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 1.0 / 60.0;
    let mut log = Log::default();
    for step in 0..steps {
        sim.step(InputFrame::default(), &[]);
        sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 99.0;
        for e in sim.take_events() {
            match e {
                SimEvent::TowerLand { pos, .. } => log.land = Some((step, pos)),
                SimEvent::TowerBurst { .. } => log.burst = Some(step),
                SimEvent::Hit { source: Source::Weapon(w), target, .. } if w == weapon => {
                    log.hits.push(target.raw() & 0x1FFF)
                }
                _ => {}
            }
        }
        each(sim, step);
    }
    log
}

#[test]
fn tower_lands_on_the_crowd_after_a_warning_and_stuns() {
    let mut sim = quiet(71);
    sim.set_build(&[("tower", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let crowd: Vec<usize> = [Vec2::new(150.0, 0.0), Vec2::new(170.0, 20.0), Vec2::new(170.0, -20.0)]
        .iter()
        .map(|&o| dummy(&mut sim, "wisp", p + o))
        .collect();
    let lone = dummy(&mut sim, "wisp", p + Vec2::new(-80.0, 0.0));
    let mut stunned = 0;
    let log = drop_tower(&mut sim, 40, |sim, _| {
        let en = sim.world().resource::<Enemies>();
        stunned = stunned.max(crowd.iter().filter(|&&i| en.stun[i] > 0.0).count());
    });
    let (step, pos) = log.land.expect("落地");
    assert!((29..=31).contains(&step), "预警 0.5 秒：第 {step} 步");
    assert!(pos.distance(p + Vec2::new(150.0, 0.0)) < 1.0, "落在扎堆的地方：{:?}", pos - p);
    assert_eq!(stunned, 3, "落地砸晕一片");
    assert!(!log.hits.contains(&(lone as u32)));
}

#[test]
fn tower_pulls_nearby_enemies_in_and_ticks() {
    let mut sim = quiet(72);
    sim.set_build(&[("tower", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let base = dummy(&mut sim, "wisp", p + Vec2::new(150.0, 0.0));
    let near = dummy(&mut sim, "wisp", p + Vec2::new(150.0, 80.0));
    let elite = dummy(&mut sim, "stonelord", p + Vec2::new(150.0, -85.0));
    let far = dummy(&mut sim, "wisp", p + Vec2::new(150.0, 160.0));
    let (n0, e0, f0) = (at(&sim, near), at(&sim, elite), at(&sim, far));
    let mut after = None;
    let log = drop_tower(&mut sim, 300, |sim, step| {
        // 落地后吸 0.5 秒
        if step == 60 {
            after = Some((at(sim, near), at(sim, elite), at(sim, far)));
        }
    });
    let (n1, e1, f1) = after.unwrap();
    assert!((n0.distance(n1) - 45.0).abs() < 6.0, "每秒吸 90：0.5 秒 {}", n0.distance(n1));
    assert!((e0.distance(e1) - 22.5).abs() < 6.0, "精英一半：{}", e0.distance(e1));
    assert!(f0.distance(f1) < 1.0, "吸的范围外不动");
    // 落地一下，之后 4 秒每 0.5 秒一跳
    let n = log.hits.iter().filter(|&&h| h == base as u32).count();
    assert_eq!(n, 1 + 8, "落地 1 下 + 8 跳");
    assert!(sim.world().resource::<Towers>().0.is_empty(), "4 秒后收走");
    assert!(log.burst.is_none(), "没进化不炸");
}

#[test]
fn linglong_tower_pulls_from_afar_and_bursts() {
    let mut sim = quiet(73);
    sim.set_build(&[("tower", 8, true)], &[]);
    let p = player_pos(&mut sim);
    let c = p + Vec2::new(150.0, 0.0);
    dummy(&mut sim, "wisp", c);
    let ring: Vec<usize> = (0..6)
        .map(|k| {
            let a = k as f32 * std::f32::consts::TAU / 6.0;
            dummy(
                &mut sim,
                "wisp",
                c + Vec2::new(380.0 * bevy_math::ops::cos(a), 380.0 * bevy_math::ops::sin(a)),
            )
        })
        .collect();
    let mut stunned = 0;
    let log = drop_tower(&mut sim, 300, |sim, _| {
        let en = sim.world().resource::<Enemies>();
        stunned = stunned.max(ring.iter().filter(|&&i| en.stun[i] > 0.5).count());
    });
    let land = log.land.expect("落地").0;
    let burst = log.burst.expect("到时间炸开");
    assert!((burst - land).abs_diff(240) <= 1, "立 4 秒：{}", burst - land);
    for &i in &ring {
        assert!(at(&sim, i).distance(c) < 140.0, "380 外的也吸进来：{}", at(&sim, i).distance(c));
    }
    assert_eq!(stunned, ring.len(), "炸开击晕 1 秒");
}
