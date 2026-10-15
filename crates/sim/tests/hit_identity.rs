//! 表现元数据不能改变伤害、击退或随机流。
mod common;

use bevy_math::Vec2;
use lantern_content::Element;
use lantern_sim::combat::{HIT_NOCRIT, HIT_REACT, HIT_TRUE, Hit, HitQueue, Source, hit_contact};
use lantern_sim::{Enemies, InputFrame, RunMode, RunSetup, SimEvent, SimHarness};

fn arena() -> SimHarness {
    let mut setup = RunSetup::new(91, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(common::content(), setup);
    sim.quiet();
    sim.set_build(&[], &[]);
    sim
}

#[test]
fn contact_uses_velocity_then_origin_then_player_then_zero() {
    let center = Vec2::new(30.0, 40.0);
    let (pos, dir) = hit_contact(center, 10.0, Vec2::ZERO, Vec2::ZERO, Vec2::ZERO);
    assert!((dir - Vec2::new(0.6, 0.8)).length() < 1e-6);
    assert!((pos - Vec2::new(24.0, 32.0)).length() < 1e-6);
    assert_eq!(
        hit_contact(center, 10.0, center, center, Vec2::new(-20.0, 0.0)),
        (center + Vec2::X * 10.0, Vec2::NEG_X)
    );
    assert_eq!(
        hit_contact(center, 10.0, center, center - Vec2::Y, Vec2::ZERO),
        (center - Vec2::Y * 10.0, Vec2::Y)
    );
    assert_eq!(hit_contact(center, 10.0, center, center, Vec2::ZERO), (center, Vec2::ZERO));
}

#[test]
fn weapon_hit_and_kill_carry_the_same_identity_and_contact() {
    let mut sim = arena();
    let i = sim.spawn("shade", Vec2::new(30.0, 20.0)).unwrap();
    let en = sim.world().resource::<Enemies>();
    let target = en.handle(i);
    let radius = en.r[i];
    let sword = common::content().weapon_index("sword").unwrap() as u16;
    sim.world_mut().resource_mut::<HitQueue>().0.push(
        Hit::new(target, 10000.0, Source::Weapon(sword))
            .incoming(Vec2::new(0.0, -380.0))
            .flags(HIT_TRUE | HIT_NOCRIT)
            .element(Some(Element::Metal)),
    );
    sim.step(InputFrame::default(), &[]);
    let events = sim.take_events();
    let (impact, incoming) = events
        .iter()
        .find_map(|e| match e {
            SimEvent::Hit { target: t, pos, impact_pos, incoming_dir, weapon, .. } if *t == target => {
                assert_eq!(*weapon, Some(sword));
                assert_eq!(*incoming_dir, Vec2::NEG_Y);
                let center = *pos + Vec2::new(0.0, radius + 4.0);
                assert!((*impact_pos - center + *incoming_dir * radius).length() < 1e-5);
                Some((*impact_pos, *incoming_dir))
            }
            _ => None,
        })
        .expect("必须有确认后的命中");
    assert!(events.iter().any(|e| matches!(e, SimEvent::Kill { target: t, weapon: Some(w), incoming_dir, pos, .. }
        if *t == target && *w == sword && *incoming_dir == incoming && (*pos - incoming * radius - impact).length() < 1e-5)));
}

#[test]
fn non_weapon_and_bonus_sources_are_classified_without_changing_damage() {
    for source in [
        Source::Reaction(0),
        Source::Ult,
        Source::Blast,
        Source::Quake,
        Source::Screen,
        Source::Band,
        Source::Dash,
        Source::Trail,
        Source::BonusSword,
    ] {
        let mut sim = arena();
        let i = sim.spawn("shade", Vec2::new(40.0, 0.0)).unwrap();
        let target = sim.world().resource::<Enemies>().handle(i);
        let expected = if source == Source::BonusSword {
            common::content().weapon_index("sword").map(|i| i as u16)
        } else {
            None
        };
        sim.world_mut().resource_mut::<HitQueue>().0.push(
            Hit::new(target, 10000.0, source).knock(0.0, Vec2::ZERO).flags(HIT_TRUE | HIT_NOCRIT | HIT_REACT),
        );
        sim.step(InputFrame::default(), &[]);
        let events = sim.take_events();
        assert!(events.iter().any(|e| matches!(e, SimEvent::Hit { source: s, weapon, damage, .. } if *s == source && *weapon == expected && *damage == 10000.0)));
        assert!(events.iter().any(|e| matches!(e, SimEvent::Kill { weapon, .. } if *weapon == expected)));
    }
}

#[test]
fn burn_death_has_no_weapon_or_direction() {
    let mut sim = arena();
    let i = sim.spawn("shade", Vec2::X * 30.0).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.hp[i] = 1.0;
        en.burn_t[i] = 1.0;
        en.burn_dps[i] = 1000.0;
        en.burn_stacks[i] = 1.0;
        en.burn_show[i] = 0.0;
    }
    sim.step(InputFrame::default(), &[]);
    let events = sim.take_events();
    assert!(events.iter().any(|e| matches!(e, SimEvent::Hit { source: Source::Burn, weapon: None, incoming_dir, .. } if *incoming_dir == Vec2::ZERO)));
    assert!(events.iter().any(
        |e| matches!(e, SimEvent::Kill { weapon: None, incoming_dir, .. } if *incoming_dir == Vec2::ZERO)
    ));
}

#[test]
fn incoming_metadata_does_not_change_knockback_rng_or_hashes() {
    let run = |incoming| {
        let mut sim = arena();
        let i = sim.spawn("shade", Vec2::new(40.0, 20.0)).unwrap();
        let target = sim.world().resource::<Enemies>().handle(i);
        sim.world_mut()
            .resource_mut::<HitQueue>()
            .0
            .push(Hit::new(target, 1.0, Source::Weapon(0)).knock(50.0, Vec2::ZERO).incoming(incoming));
        for _ in 0..120 {
            sim.step(InputFrame::default(), &[]);
        }
        let en = sim.world().resource::<Enemies>();
        (sim.hashes().to_vec(), en.x[i], en.y[i], en.hp[i])
    };
    let a = run(Vec2::X * 380.0);
    let b = run(Vec2::NEG_Y * 250.0);
    assert!(!a.0.is_empty());
    assert_eq!(a, b);
}
