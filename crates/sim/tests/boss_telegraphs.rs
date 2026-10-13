//! 夜主预警的时序、锁定、取消与边界回归；专用黄金场景覆盖三阶段和狂暴。
mod common;

use bevy_math::{Vec2, ops};
use lantern_core::step::DT;
use lantern_sim::boss::{BossState, Foes, RainDrop, Sweep};
use lantern_sim::{
    Director, Enemies, InputFrame, Player, Pos, RunMode, RunSetup, SimEvent, SimHarness, SimPhase,
};

fn arena(god: bool, tier: u8) -> (SimHarness, usize) {
    let mut setup = RunSetup::new(7103, RunMode::Normal);
    setup.god = god;
    setup.tier = tier;
    let mut sim = SimHarness::with_setup(common::content(), setup);
    sim.quiet();
    sim.set_build(&[], &[]);
    let i = sim.spawn("jiuwei", Vec2::new(400.0, 0.0)).unwrap();
    let h = sim.enemies().handle(i);
    sim.world_mut().resource_mut::<Director>().boss = Some(h);
    sim.world_mut().resource_mut::<Enemies>().summon_t[i] = 1000.0;
    (sim, i)
}

fn start_volley(sim: &mut SimHarness, i: usize) {
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::VolleyWarn { illusion: false, .. })));
}

#[test]
fn volley_locks_before_firing_and_keeps_full_windup_even_when_enraged() {
    for enraged in [false, true] {
        let (mut sim, i) = arena(true, 1);
        if enraged {
            sim.world_mut().resource_mut::<Director>().boss_since = -200.0;
        }
        start_volley(&mut sim, i);
        let locked = sim.world().resource::<BossState>().volley.unwrap();
        assert_eq!(locked.t, 0.0);
        assert!(sim.world().resource::<Foes>().0.is_empty());
        let mut elapsed = 0.0;
        loop {
            sim.step(InputFrame::quantize(Vec2::Y), &[]);
            elapsed += DT;
            if sim.take_events().iter().any(|e| matches!(e, SimEvent::BossVolley { .. })) {
                break;
            }
            assert!(sim.world().resource::<Foes>().0.is_empty());
            let v = sim.world().resource::<BossState>().volley.unwrap();
            assert_eq!((v.origin, v.offset), (locked.origin, locked.offset));
            assert_eq!(Vec2::new(sim.enemies().x[i], sim.enemies().y[i]), locked.origin);
            assert!(elapsed < locked.warn + DT);
        }
        assert!(elapsed >= locked.warn && elapsed < locked.warn + DT);
        let foes = &sim.world().resource::<Foes>().0;
        assert_eq!(foes.len(), locked.count as usize);
        for (k, shot) in foes.iter().enumerate() {
            assert_eq!(shot.prev, locked.origin);
            assert_eq!(shot.vel, locked.direction(k as u32) * locked.speed);
            assert!(locked.lanes(0.0).nth(k).unwrap().contains(shot.pos));
        }
    }
}

#[test]
fn phase_pause_holds_warning_and_boss_removal_cancels_it() {
    let (mut sim, i) = arena(true, 1);
    start_volley(&mut sim, i);
    let locked = sim.world().resource::<BossState>().volley;
    *sim.world_mut().resource_mut::<SimPhase>() = SimPhase::LevelUp;
    for _ in 0..120 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.world().resource::<BossState>().volley, locked);
    assert!(sim.world().resource::<Foes>().0.is_empty());
    *sim.world_mut().resource_mut::<SimPhase>() = SimPhase::Play;
    sim.world_mut().resource_mut::<Director>().boss = None;
    sim.step(InputFrame::default(), &[]);
    assert!(sim.world().resource::<BossState>().volley.is_none());
    assert!(sim.world().resource::<Foes>().0.is_empty());
}

#[test]
fn dispelling_a_charging_illusion_cancels_its_locked_volley() {
    let (mut sim, i) = arena(true, 1);
    let hp = sim.enemies().max_hp[i];
    sim.world_mut().resource_mut::<Enemies>().hp[i] = hp * 0.5;
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 1000.0;
    sim.step(InputFrame::default(), &[]);
    {
        let mut st = sim.world_mut().resource_mut::<BossState>();
        st.illusions.truncate(1);
        st.illusions[0].volley_t = 0.0;
    }
    sim.step(InputFrame::default(), &[]);
    let illusion = sim.world().resource::<BossState>().illusions[0];
    assert!(illusion.volley.is_some());
    sim.take_events();
    let dispel =
        common::content().enemies.iter().find_map(|e| e.boss.as_ref()).unwrap().illusions.unwrap().dispel;
    sim.world_mut().resource_mut::<BossState>().illusions[0].seen = dispel;
    for _ in 0..60 {
        sim.step(InputFrame::default(), &[]);
    }
    assert!(sim.world().resource::<BossState>().illusions.is_empty());
    assert!(sim.world().resource::<Foes>().0.is_empty());
    assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::BossVolley { .. })));
}

#[test]
fn simultaneous_body_and_two_illusion_volleys_identify_their_casters() {
    let (mut sim, i) = arena(true, 1);
    let hp = sim.enemies().max_hp[i];
    sim.world_mut().resource_mut::<Enemies>().hp[i] = hp * 0.5;
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 1000.0;
    sim.step(InputFrame::default(), &[]);
    {
        let mut boss = sim.world_mut().resource_mut::<BossState>();
        assert_eq!(boss.illusions.len(), 2);
        for illusion in &mut boss.illusions {
            illusion.volley_t = 0.0;
        }
    }
    start_volley(&mut sim, i);
    let boss = sim.world().resource::<BossState>();
    let body = boss.volley.unwrap();
    let illusions: Vec<_> = boss.illusions.iter().map(|m| m.volley.unwrap()).collect();
    for _ in 0..60 {
        sim.step(InputFrame::default(), &[]);
        let fired: Vec<_> =
            sim.take_events().into_iter().filter(|e| matches!(e, SimEvent::BossVolley { .. })).collect();
        if fired.is_empty() {
            continue;
        }
        assert_eq!(fired.len(), 3);
        assert_eq!(fired[0], SimEvent::BossVolley { pos: body.origin, illusion: false });
        for (event, volley) in fired[1..].iter().zip(&illusions) {
            assert_eq!(*event, SimEvent::BossVolley { pos: volley.origin, illusion: true });
        }
        assert_eq!(
            sim.world().resource::<Foes>().0.len(),
            (body.count + illusions.iter().map(|v| v.count).sum::<u32>()) as usize
        );
        return;
    }
    panic!("本体和幻身应在完整预警后同时出手");
}

#[test]
fn sweep_and_rain_use_the_visible_player_center_boundary() {
    let reach = common::content().player.radius;
    for rain in [false, true] {
        for dir in [0.0, std::f32::consts::FRAC_PI_2, 2.4, -2.4] {
            for outside in [false, true] {
                let (mut sim, i) = arena(false, 1);
                sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 1000.0;
                let (s, c) = ops::sin_cos(dir);
                let radius = if rain { 40.0 } else { 220.0 };
                let target = Vec2::new(c, s) * (radius + reach + if outside { 0.25 } else { -0.25 });
                let world = sim.world_mut();
                let mut q = world.query_filtered::<&mut Pos, bevy_ecs::prelude::With<Player>>();
                q.single_mut(world).unwrap().0 = target;
                let mut st = world.resource_mut::<BossState>();
                st.phase = 1;
                if rain {
                    st.drops.push(RainDrop { pos: Vec2::ZERO, radius, damage: 16.0, t: 0.0, warn: 0.8 });
                } else {
                    st.sweeps.push(Sweep {
                        origin: Vec2::ZERO,
                        dir,
                        angle: 2.0944,
                        radius,
                        damage: 25.0,
                        t: 0.0,
                        warn: 0.8,
                    });
                }
                let mut elapsed = 0.0;
                loop {
                    sim.step(InputFrame::default(), &[]);
                    elapsed += DT;
                    let events = sim.take_events();
                    let struck = events
                        .iter()
                        .any(|e| matches!(e, SimEvent::SweepStrike { .. } | SimEvent::RainStrike { .. }));
                    let hurt = events.iter().any(|e| matches!(e, SimEvent::PlayerHurt { .. }));
                    if struck {
                        assert!((0.8..0.8 + DT).contains(&elapsed));
                        assert_eq!(hurt, !outside, "rain={rain}, dir={dir}, outside={outside}");
                        break;
                    }
                    assert!(!hurt);
                    assert!(elapsed < 0.8 + DT);
                }
            }
        }
    }
}

fn boss_trace() -> Vec<String> {
    let (mut sim, i) = arena(true, 3);
    let hp = sim.enemies().max_hp[i];
    let mut trace = Vec::new();
    for tick in 0..900 {
        if tick == 120 {
            sim.world_mut().resource_mut::<Enemies>().hp[i] = hp * 0.5;
        }
        if tick == 360 {
            sim.world_mut().resource_mut::<Enemies>().hp[i] = hp * 0.2;
        }
        if tick == 600 {
            sim.world_mut().resource_mut::<Director>().boss_since = -200.0;
        }
        let t = tick as f32 * DT;
        sim.step(InputFrame::quantize(Vec2::new(ops::cos(t), ops::sin(t))), &[]);
        for event in sim.take_events() {
            if matches!(
                event,
                SimEvent::VolleyWarn { .. }
                    | SimEvent::BossVolley { .. }
                    | SimEvent::SweepWarn { .. }
                    | SimEvent::SweepStrike { .. }
                    | SimEvent::RainWarn { .. }
                    | SimEvent::RainStrike { .. }
                    | SimEvent::BossPhase { .. }
                    | SimEvent::BossEnraged
            ) {
                trace.push(format!("{}:{event:?}", sim.tick()));
            }
        }
    }
    for h in sim.hashes() {
        trace.push(format!("{}:{:016x}", h.tick, h.hash));
    }
    trace
}

#[test]
fn boss_telegraphs_match_golden_and_repeat_exactly() {
    let got = boss_trace();
    assert_eq!(got, boss_trace());
    for name in [
        "VolleyWarn",
        "illusion: true",
        "BossVolley",
        "SweepWarn",
        "SweepStrike",
        "RainWarn",
        "RainStrike",
        "BossEnraged",
    ] {
        assert!(got.iter().any(|line| line.contains(name)), "黄金场景没有覆盖 {name}");
    }
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden/boss_telegraphs.ron");
    if std::env::var_os("UPDATE_GOLDEN").is_some() {
        std::fs::write(
            path,
            ron::ser::to_string_pretty(&got, ron::ser::PrettyConfig::default()).unwrap() + "\n",
        )
        .unwrap();
    } else {
        let want: Vec<String> = ron::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        assert_eq!(got, want, "夜主时序或结果改变后需更新黄金文件");
    }
}
