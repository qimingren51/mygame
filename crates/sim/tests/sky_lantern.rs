//! 孔明灯 / 万灯升（docs/BALANCE.md 第 6.3 节）：灯飘向妖物最密的地方，几盏的落点互相隔开，
//! 到时间落地爆燃、点灼烧、留火海；没有妖物就落在前方。

mod common;

use bevy_math::Vec2;
use lantern_content::GroundKind;
use lantern_sim::combat::Source;
use lantern_sim::enemies::Enemies;
use lantern_sim::weapons::drop::Fissures;
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

/// 摆一只打不死、不会动的小妖（疾影，半径 10）。
fn dummy(sim: &mut SimHarness, at: Vec2) -> usize {
    let i = sim.spawn("wisp", at).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.hp[i] = 1e9;
    en.max_hp[i] = 1e9;
    en.speed[i] = 0.0;
    i
}

/// 每步把它们摆回去，免得被挤开或击退。
fn hold(sim: &mut SimHarness, placed: &[(usize, Vec2)]) {
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

fn place(sim: &mut SimHarness, p: Vec2, spots: &[Vec2]) -> Vec<(usize, Vec2)> {
    spots.iter().map(|&o| (dummy(sim, p + o), p + o)).collect()
}

fn lantern(sim: &SimHarness) -> u16 {
    sim.world().resource::<lantern_sim::GameContent>().0.weapon_index("sky_lantern").unwrap() as u16
}

struct Burst {
    step: u32,
    pos: Vec2,
    evolved: bool,
    hits: Vec<u32>,
}

/// 从现在起立刻放灯，一直走到 steps 步，记下每次爆燃和那一步孔明灯打到了谁。
/// moved：走到第几步时把妖物整体挪到新位置。
fn fly(
    sim: &mut SimHarness,
    placed: &mut [(usize, Vec2)],
    steps: u32,
    moved: Option<(u32, Vec2)>,
) -> Vec<Burst> {
    let weapon = lantern(sim);
    sim.world_mut().resource_mut::<lantern_sim::Arsenal>().0[0].timer = 1.0 / 60.0;
    let mut out = Vec::new();
    for step in 0..steps {
        if let Some((at, by)) = moved
            && step == at
        {
            for (_, p) in placed.iter_mut() {
                *p += by;
            }
        }
        hold(sim, placed);
        sim.step(InputFrame::default(), &[]);
        let events = sim.take_events();
        let hits: Vec<u32> = events
            .iter()
            .filter_map(|e| match e {
                SimEvent::Hit { source: Source::Weapon(w), target, .. } if *w == weapon => {
                    Some(target.raw() & 0x1FFF)
                }
                _ => None,
            })
            .collect();
        for e in &events {
            if let SimEvent::LanternBurst { pos, evolved, .. } = e {
                out.push(Burst { step, pos: *pos, evolved: *evolved, hits: hits.clone() });
            }
        }
    }
    out
}

#[test]
fn sky_lantern_drifts_to_the_densest_spot_burns_and_leaves_fire() {
    let mut sim = quiet(41);
    sim.set_build(&[("sky_lantern", 1, false)], &[]);
    let p = player_pos(&mut sim);
    // 右边近处一只落单的，左边远一点四只扎堆；灯要去扎堆的那边
    let mut placed = place(
        &mut sim,
        p,
        &[
            Vec2::new(60.0, 0.0),
            Vec2::new(-130.0, 0.0),
            Vec2::new(-160.0, 25.0),
            Vec2::new(-160.0, -25.0),
            Vec2::new(-190.0, 0.0),
        ],
    );
    let lone = placed[0].0 as u32;
    let bursts = fly(&mut sim, &mut placed, 200, None);
    let b = bursts.first().expect("3 秒内落地");
    assert!((178..=182).contains(&b.step), "3 秒落地：第 {} 步", b.step);
    assert!(
        b.pos.distance(p + Vec2::new(-130.0, 0.0)) < 8.0,
        "落在扎堆那边离主角最近的一只上：{:?}",
        b.pos - p
    );
    assert!(b.hits.len() >= 3, "爆燃打到扎堆的几只：{:?}", b.hits);
    assert!(!b.hits.contains(&lone), "落单的不打");
    let en = sim.world().resource::<Enemies>();
    for &i in &b.hits {
        assert!(en.burn_stacks[i as usize] >= 1.0, "点 1 层灼烧");
    }
    let fire =
        sim.world().resource::<Fissures>().0.iter().find(|f| f.kind == GroundKind::Fire).expect("留下火海");
    assert!(fire.pos.distance(b.pos) < 1.0);
    assert!((fire.radius - 44.0 * 0.8).abs() < 0.5, "火海半径 0.8 倍：{}", fire.radius);
}

#[test]
fn sky_lanterns_spread_their_landing_spots() {
    let mut sim = quiet(42);
    sim.set_build(&[("sky_lantern", 3, false)], &[]);
    let p = player_pos(&mut sim);
    // 两堆一样多：两盏各去一堆，不挤在一处
    let mut placed = place(
        &mut sim,
        p,
        &[
            Vec2::new(110.0, 0.0),
            Vec2::new(130.0, 25.0),
            Vec2::new(130.0, -25.0),
            Vec2::new(-110.0, 0.0),
            Vec2::new(-130.0, 25.0),
            Vec2::new(-130.0, -25.0),
        ],
    );
    let bursts = fly(&mut sim, &mut placed, 200, None);
    assert_eq!(bursts.len(), 2, "3 级两盏");
    assert!(bursts[0].pos.distance(bursts[1].pos) >= 120.0, "落点至少隔开 120");
    assert!(bursts.iter().any(|b| b.pos.x > p.x) && bursts.iter().any(|b| b.pos.x < p.x));
}

#[test]
fn sky_lantern_follows_the_crowd_in_flight() {
    let mut sim = quiet(43);
    sim.set_build(&[("sky_lantern", 1, false)], &[]);
    let p = player_pos(&mut sim);
    let mut placed =
        place(&mut sim, p, &[Vec2::new(-100.0, 0.0), Vec2::new(-125.0, 20.0), Vec2::new(-125.0, -20.0)]);
    // 飞到 1 秒时整堆往上挪 80，灯每 0.5 秒重新找一次，要跟过去
    let bursts = fly(&mut sim, &mut placed, 200, Some((60, Vec2::new(0.0, 80.0))));
    let b = bursts.first().expect("落地");
    assert!(b.pos.y - p.y > 50.0, "跟着妖群挪过去：{:?}", b.pos - p);
    assert!(!b.hits.is_empty());
}

#[test]
fn sky_lantern_lands_ahead_when_nothing_is_near() {
    let mut sim = quiet(44);
    sim.set_build(&[("sky_lantern", 1, false)], &[]);
    // 往下走一步，面向变成下
    sim.step(InputFrame::quantize(Vec2::new(0.0, -1.0)), &[]);
    let p = player_pos(&mut sim);
    let bursts = fly(&mut sim, &mut [], 200, None);
    let b = bursts.first().expect("没有妖物也照样放");
    assert!(b.pos.y < p.y - 100.0 && (b.pos.x - p.x).abs() < 10.0, "落在前方：{:?}", b.pos - p);
}

#[test]
fn wandeng_sheng_drops_eight_lanterns_in_two_seconds() {
    let mut sim = quiet(45);
    sim.set_build(&[("sky_lantern", 8, true)], &[]);
    let bursts = fly(&mut sim, &mut [], 160, None);
    assert_eq!(bursts.len(), 8, "一次放飞 8 盏");
    for b in &bursts {
        assert!(b.evolved);
        assert!((118..=122).contains(&b.step), "2 秒落地：第 {} 步", b.step);
    }
    for (k, a) in bursts.iter().enumerate() {
        for b in &bursts[k + 1..] {
            assert!(a.pos.distance(b.pos) > 1.0, "没有妖物时几盏也错开落");
        }
    }
}
