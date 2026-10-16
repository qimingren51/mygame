//! 奇遇不能在伤害结算后把已倒下的主角复活。

mod common;

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_sim::encounters::{Encounter, Encounters};
use lantern_sim::{Health, InputFrame, Player, SimCommand, SimEvent, SimHarness};

fn encounter(id: &str, hp: f32) -> SimHarness {
    let c = common::content();
    let kind = c.events.kinds.iter().position(|e| e.id == id).unwrap();
    let mut sim = SimHarness::new(c, 7);
    sim.quiet();
    sim.set_build(&[], &[]);
    let world = sim.world_mut();
    world.query_filtered::<&mut Health, With<Player>>().single_mut(world).unwrap().hp = hp;
    world.resource_mut::<Encounters>().list.push(Encounter { kind, pos: Vec2::ZERO, t: 0.0, enemy: None });
    sim
}

#[test]
fn lethal_damage_prevents_healing_and_encounter_interactions_in_the_same_step() {
    for id in ["spring", "altar", "shrine", "merchant"] {
        let mut sim = encounter(id, 1.0);
        let i = sim.spawn("golem", Vec2::new(5.0, 0.0)).unwrap();
        // 跳过刷出保护；血祭坛也按了交互键，照样不能献
        sim.world_mut().resource_mut::<lantern_sim::Enemies>().grace[i] = 0.0;
        sim.step(InputFrame::default(), &[SimCommand::Interact]);

        let events = sim.take_events();
        assert!(events.iter().any(|e| matches!(e, SimEvent::PlayerDied)), "{id}：确实受了致命伤");
        assert_eq!(sim.player_hp(), 0.0, "{id} 不能复活主角");
        assert!(sim.is_over(), "{id} 不得阻止结算");
        assert!(!sim.flow().result.as_ref().unwrap().won);
        assert!(sim.flow().chest_queue.is_empty());
        assert!(sim.flow().shop.is_none());
        assert!(sim.world().resource::<Encounters>().buff.is_none());
        assert_eq!(sim.world().resource::<Encounters>().list.len(), 1, "不能消费奇遇");
        assert!(!events.iter().any(|e| matches!(e, SimEvent::Sacrifice { .. } | SimEvent::Buff { .. })));
    }
}

#[test]
fn nonpositive_health_cannot_use_springs_or_altars() {
    for id in ["spring", "altar"] {
        for hp in [0.0, -5.0] {
            let mut sim = encounter(id, hp);
            sim.step(InputFrame::default(), &[]);
            assert_eq!(sim.player_hp(), hp, "{id} 不能给已倒下的主角加血");
            assert!(sim.is_over());
            assert!(sim.flow().chest_queue.is_empty());
        }
    }
}

#[test]
fn living_players_can_still_heal_and_sacrifice_their_last_health() {
    let mut spring = encounter("spring", 1.0);
    spring.step(InputFrame::default(), &[]);
    assert!(spring.player_hp() > 1.0);
    assert!(!spring.is_over());

    let mut altar = encounter("altar", 1.0);
    altar.step(InputFrame::default(), &[SimCommand::Interact]);
    assert_eq!(altar.player_hp(), 1.0);
    assert!(!altar.is_over());
    assert!(altar.flow().chest.is_some());
    assert!(altar.take_events().iter().any(|e| matches!(e, SimEvent::Sacrifice { .. })));
}
