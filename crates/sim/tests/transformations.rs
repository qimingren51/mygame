//! 构筑质变：互斥分岔、终式占格、确定性与真实伤害管线。
mod common;

use bevy_math::{Vec2, ops};
use lantern_content::{Content, GroundKind, WeaponBehavior};
use lantern_core::{Pcg32, StateHasher};
use lantern_sim::build::{Banned, PassiveSlot, apply_offer, can_fuse, occupied_slots, roll_choices};
use lantern_sim::combat::{Hit, HitQueue, Source, StrikeFx};
use lantern_sim::weapons::Form;
use lantern_sim::weapons::drop::{Fissures, GROUND_CAP};
use lantern_sim::weapons::volley::Shots;
use lantern_sim::{
    Arsenal, Build, Enemies, InputFrame, Offer, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase,
};

fn arena() -> SimHarness {
    let mut setup = RunSetup::new(71, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(common::content(), setup);
    sim.quiet();
    sim
}

fn advance(sim: &mut SimHarness, ticks: u64) -> Vec<SimEvent> {
    let end = sim.tick() + ticks;
    let mut events = Vec::new();
    while sim.tick() < end {
        let commands = match sim.phase() {
            SimPhase::LevelUp => vec![SimCommand::Skip],
            SimPhase::Chest | SimPhase::Evolve => vec![SimCommand::Ack],
            _ => Vec::new(),
        };
        sim.step(InputFrame::default(), &commands);
        events.extend(sim.take_events());
    }
    events
}

fn pair(c: &Content, f: usize) -> (Arsenal, Build) {
    let mut a = Arsenal::default();
    let mut b = Build::default();
    for id in &c.fusions[f].weapons {
        let d = c.weapon_index(id).unwrap();
        let mut w = lantern_sim::weapons::WeaponSlot::new(d);
        w.level = 8;
        w.form = Form::Evolved;
        a.0.push(w);
        let key = c.passive_index(&c.weapons[d].evolution.as_ref().unwrap().passive).unwrap();
        b.passives.push(PassiveSlot { def: key, level: 5 });
    }
    b.compute_resonance(c, &a);
    (a, b)
}

#[test]
fn every_mutation_requires_key_max_and_counter_and_is_exclusive() {
    let c = common::content();
    for d in 0..c.weapons.len() {
        let counter = c.weapons.iter().position(|w| w.element.overcomes(c.weapons[d].element)).unwrap();
        let key = c.passive_index(&c.weapons[d].evolution.as_ref().unwrap().passive).unwrap();
        let mut a = Arsenal(vec![
            lantern_sim::weapons::WeaponSlot::new(d),
            lantern_sim::weapons::WeaponSlot::new(counter),
        ]);
        let mut b = Build::default();
        a.0[0].level = 8;
        a.0[1].level = 8;
        assert!(!a.0[0].can_mutate(&c, &b, &a), "缺心法");
        b.passives.push(PassiveSlot { def: key, level: 1 });
        a.0[0].level = 7;
        assert!(!a.0[0].can_mutate(&c, &b, &a), "本器未满级");
        a.0[0].level = 8;
        a.0[1].level = 7;
        assert!(!a.0[0].can_mutate(&c, &b, &a), "克制法器未满级");
        a.0[1].level = 8;
        assert!(a.0[0].can_mutate(&c, &b, &a));
        for form in [Form::Evolved, Form::Mutated] {
            a.0[0].form = Form::Base;
            let offer = if form == Form::Evolved { Offer::Evolve(0) } else { Offer::Mutate(0) };
            assert_eq!(apply_offer(&c, &mut a, &mut b, offer), Some(0));
            assert_eq!(a.0[0].form, form);
            assert!(!a.0[0].can_evolve(&c, &b));
            assert!(!a.0[0].can_mutate(&c, &b, &a));
            assert_eq!(apply_offer(&c, &mut a, &mut b, Offer::Mutate(0)), None);
            assert!(
                !lantern_sim::build::offers(&c, &a, &b, 360.0)
                    .iter()
                    .any(|(o, _)| matches!(o, Offer::Evolve(0) | Offer::Mutate(0)))
            );
            b.compute_resonance(&c, &a);
            assert_eq!(b.points[c.weapons[d].element.index()], 5, "质变四点，加钥匙一点");
        }
    }
}

#[test]
fn evolution_and_mutation_are_always_presented_together() {
    let c = common::content();
    let mut sim = arena();
    sim.set_build(&[("lamp", 8, false), ("bell", 8, false)], &[("changming", 1)]);
    for seed in 0..200 {
        let mut b = sim.build().clone();
        let (choices, _) =
            roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 360.0, &mut Pcg32::new(seed, 1), true);
        assert!(choices.contains(&Offer::Evolve(0)) && choices.contains(&Offer::Mutate(0)));
    }
}

#[test]
fn all_fusions_require_orthodox_forms_and_both_tiers_then_free_a_slot() {
    let c = common::content();
    for f in 0..c.fusions.len() {
        let (mut a, mut b) = pair(&c, f);
        assert!(can_fuse(&c, &a, &b, 0, 1, f));
        for form in [Form::Base, Form::Mutated, Form::Fused(f)] {
            a.0[0].form = form;
            assert!(!can_fuse(&c, &a, &b, 0, 1, f));
        }
        a.0[0].form = Form::Evolved;
        for k in 0..2 {
            b.passives[k].level = 4;
            assert!(!can_fuse(&c, &a, &b, 0, 1, f));
            b.passives[k].level = 5;
        }
        assert!(!can_fuse(&c, &a, &b, 0, 0, f));
        assert_eq!(apply_offer(&c, &mut a, &mut b, Offer::Fuse { a: 1, b: 0, fusion_id: f }), Some(0));
        assert_eq!(a.0.len(), 1);
        assert_eq!(occupied_slots(&c, &a, &b), 1);
        assert_eq!(a.0[0].form, Form::Fused(f));
        b.compute_resonance(&c, &a);
        for id in &c.fusions[f].weapons {
            let d = c.weapon_index(id).unwrap();
            assert_eq!(b.points[c.weapons[d].element.index()], 7);
            assert!(
                !lantern_sim::build::offers(&c, &a, &b, 540.0).iter().any(|(o, _)| *o == Offer::NewWeapon(d))
            );
        }
        b.charms.push(c.charm_index("broken_sword").unwrap());
        assert_eq!(occupied_slots(&c, &a, &b), 2);
        for id in ["lamp", "sword", "bell", "crane", "seal"] {
            let d = c.weapon_index(id).unwrap();
            apply_offer(&c, &mut a, &mut b, Offer::NewWeapon(d));
        }
        assert_eq!(occupied_slots(&c, &a, &b), 4);
        assert_eq!(a.0.len(), 3, "断剑：终式两格，另带两器");
    }
}

#[test]
fn fusion_is_guaranteed_until_banished_without_banning_materials() {
    let c = common::content();
    let sim = arena();
    let (a, mut b) = pair(&c, 0);
    let offer = Offer::Fuse { a: 0, b: 1, fusion_id: 0 };
    for seed in 0..100 {
        assert!(
            roll_choices(&c, &a, &mut b, sim.stats(), 540.0, &mut Pcg32::new(seed, 2), false)
                .0
                .contains(&offer)
        );
    }
    b.banished.push(offer.banned(&a, &b).unwrap());
    assert_eq!(b.banished, [Banned::Fusion(0)]);
    assert!(!lantern_sim::build::offers(&c, &a, &b, 540.0).iter().any(|(o, _)| *o == offer));
}

#[test]
fn five_minute_chest_preserves_mutation_choice_and_keys_are_guaranteed() {
    let c = common::content();
    let mut sim = arena();
    sim.set_build(&[("lamp", 8, false), ("bell", 8, false)], &[("changming", 1)]);
    sim.flow_mut().chest_queue.push_back(lantern_sim::flow::ChestSource::MiniBoss);
    advance(&mut sim, 1);
    assert_eq!(sim.arsenal().0[0].form, Form::Base, "宝箱不替玩家选择分岔");
    sim.set_build(&[("lamp", 8, false)], &[]);
    let key = Offer::NewPassive(c.passive_index("changming").unwrap());
    for seed in 0..100 {
        let mut b = sim.build().clone();
        assert!(
            roll_choices(&c, sim.arsenal(), &mut b, sim.stats(), 300.0, &mut Pcg32::new(seed, 3), true)
                .0
                .contains(&key)
        );
    }
}

fn transformed_arena(form: Form, weapon: &str) -> SimHarness {
    let c = common::content();
    let mut sim = arena();
    sim.set_build(&[(weapon, 8, false)], &[]);
    sim.world_mut().resource_mut::<Arsenal>().0[0].form = form;
    for k in 0..48 {
        let a = k as f32 / 48.0 * std::f32::consts::TAU;
        let r = 65.0 + (k % 4) as f32 * 27.0;
        let h = sim.spawn("shade", Vec2::new(ops::cos(a), ops::sin(a)) * r);
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        if let Some(i) = h {
            en.hp[i] = 1000.0;
            en.max_hp[i] = 1000.0;
        }
    }
    sim.world_mut().resource_mut::<lantern_sim::stats::StatsDirty>().0 = true;
    assert!(c.weapon_index(weapon).is_some());
    sim
}

#[test]
fn every_mutation_and_fusion_deals_damage_and_replays_deterministically() {
    let c = common::content();
    let cases = c
        .weapons
        .iter()
        .map(|w| (Form::Mutated, w.id.as_str()))
        .chain(c.fusions.iter().enumerate().map(|(f, d)| (Form::Fused(f), d.weapons[0].as_str())));
    for (form, id) in cases {
        let mut a = transformed_arena(form, id);
        let mut b = transformed_arena(form, id);
        let events = advance(&mut a, 480);
        advance(&mut b, 480);
        assert!(
            events.iter().any(|e| matches!(e, SimEvent::Hit { damage, .. } if *damage > 0.0)),
            "{id} {form:?}"
        );
        assert_eq!(a.hashes(), b.hashes(), "{id} {form:?} 同种子逐秒哈希");
        assert_eq!(a.damage_log().0, b.damage_log().0);
    }
}

#[test]
fn iron_cranes_cap_at_five_even_with_amount_bonuses() {
    let mut sim = arena();
    sim.set_build(&[("crane", 8, false)], &[("zhezhi", 5)]);
    sim.world_mut().resource_mut::<Arsenal>().0[0].form = Form::Mutated;
    advance(&mut sim, 1);
    assert_eq!(sim.arsenal().0[0].cranes.len(), 5);
}

#[test]
fn ground_caps_and_bamboo_blocks_while_fusion_leaves_sword_groves() {
    let c = common::content();
    let WeaponBehavior::Drop { fissure: Some(f), .. } =
        c.weapons[c.weapon_index("seal").unwrap()].mutation.as_ref().unwrap().behavior
    else {
        panic!()
    };
    let mut ground = Fissures::default();
    for _ in 0..100 {
        ground.add(Vec2::ZERO, 80.0, 50.0, Source::Weapon(4), f);
    }
    assert_eq!(ground.0.len(), GROUND_CAP);
    assert!(ground.speed_at(Vec2::ZERO) < 0.2);
    assert_eq!(ground.speed_at(Vec2::splat(500.0)), 1.0);
    let f = c.fusions.iter().position(|f| f.id == "sword_grove").unwrap();
    let mut sim = transformed_arena(Form::Fused(f), "seal");
    advance(&mut sim, 120);
    assert!(sim.world().resource::<Fissures>().0.iter().any(|f| f.kind == GroundKind::Sword));
}

#[test]
fn molten_kill_splits_once_and_children_keep_only_vulnerability() {
    let c = common::content();
    let mut sim = arena();
    sim.set_build(&[], &[]);
    let victim = sim.spawn("shade", Vec2::new(60.0, 0.0)).unwrap();
    let victim = sim.world().resource::<Enemies>().handle(victim);
    sim.spawn("shade", Vec2::new(110.0, 0.0));
    sim.spawn("shade", Vec2::new(110.0, 20.0));
    let d = c.weapon_index("sword").unwrap();
    let WeaponBehavior::Volley { molten, .. } = c.weapons[d].mutation.as_ref().unwrap().behavior else {
        panic!()
    };
    let mut hit = Hit::new(victim, 100.0, Source::Weapon(d as u16));
    hit.molten = molten;
    sim.world_mut().resource_mut::<HitQueue>().0.push(hit);
    advance(&mut sim, 1);
    let shots = &sim.world().resource::<Shots>().0;
    assert_eq!(shots.len(), 2);
    assert!(shots.iter().all(|s| s.effects.molten.unwrap().split_ratio == 0.0));
    advance(&mut sim, 90);
    assert!(sim.world().resource::<Shots>().0.is_empty(), "分剑不再分裂");
}

#[test]
fn permafrost_shatter_cannot_chain() {
    let mut sim = arena();
    sim.set_build(&[("bell", 8, false)], &[]);
    {
        let mut a = sim.world_mut().resource_mut::<Arsenal>();
        a.0[0].form = Form::Mutated;
        a.0[0].timer = 100.0;
    }
    let victim = sim.spawn("shade", Vec2::new(60.0, 0.0)).unwrap();
    let victim = sim.world().resource::<Enemies>().handle(victim);
    sim.spawn("shade", Vec2::new(70.0, 0.0));
    sim.spawn("shade", Vec2::new(80.0, 0.0));
    sim.world_mut().resource_mut::<HitQueue>().0.push(Hit::new(victim, 100.0, Source::Ult));
    let events = advance(&mut sim, 10);
    assert_eq!(
        events.iter().filter(|e| matches!(e, SimEvent::Strike { fx: StrikeFx::Blast(_), .. })).count(),
        1
    );
}

#[test]
fn form_is_in_state_hash() {
    let c = common::content();
    let (mut a, _) = pair(&c, 0);
    let hash = |a: &Arsenal| {
        let mut h = StateHasher::new();
        a.hash_into(&mut h);
        h.finish()
    };
    let before = hash(&a);
    a.0[0].form = Form::Mutated;
    assert_ne!(before, hash(&a));
    assert_eq!(c.elements.weapon_points(8, true), 4);
}

#[test]
fn ice_and_fire_orbit_triggers_existing_steam_reaction() {
    let c = common::content();
    let steam =
        c.elements.reaction_between(lantern_content::Element::Water, lantern_content::Element::Fire).unwrap();
    let mut sim = transformed_arena(Form::Mutated, "lamp");
    let events = advance(&mut sim, 300);
    assert!(events.iter().any(|e| matches!(e, SimEvent::Reaction { kind, .. } if *kind as usize == steam)));
}

#[test]
fn overlapping_ground_uses_strongest_instead_of_stacking() {
    let c = common::content();
    let WeaponBehavior::Drop { fissure: Some(f), .. } = c.fusions[1].behavior else { panic!() };
    let run = |copies: usize| {
        let mut sim = arena();
        sim.set_build(&[], &[]);
        let i = sim.spawn("shade", Vec2::new(100.0, 0.0)).unwrap();
        {
            let mut en = sim.world_mut().resource_mut::<Enemies>();
            en.hp[i] = 10000.0;
            en.max_hp[i] = 10000.0;
            en.speed[i] = 0.0;
        }
        for _ in 0..copies {
            sim.world_mut().resource_mut::<Fissures>().add(
                Vec2::new(100.0, 0.0),
                60.0,
                100.0,
                Source::Weapon(4),
                f,
            );
        }
        advance(&mut sim, 90);
        sim.damage_log().0.clone()
    };
    assert_eq!(run(1), run(10), "十片同类剑林也只计最强一片");
}

#[test]
fn banishing_evolution_removes_its_mutation_card_too() {
    let mut sim = arena();
    sim.set_build(&[("lamp", 8, false), ("bell", 8, false)], &[("changming", 1)]);
    sim.flow_mut().banishes = 1;
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    let i = sim.flow().choice.as_ref().unwrap().offers.iter().position(|o| *o == Offer::Evolve(0)).unwrap();
    sim.step(InputFrame::default(), &[SimCommand::Banish(i as u8)]);
    assert!(
        !sim.flow()
            .choice
            .as_ref()
            .unwrap()
            .offers
            .iter()
            .any(|o| matches!(o, Offer::Evolve(0) | Offer::Mutate(0)))
    );
}

#[test]
fn transformation_events_preserve_chosen_identity() {
    let c = common::content();
    let mut sim = arena();
    sim.set_build(&[("lamp", 8, false), ("bell", 8, false)], &[("changming", 1)]);
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    let i = sim.flow().choice.as_ref().unwrap().offers.iter().position(|o| *o == Offer::Mutate(0)).unwrap();
    sim.step(InputFrame::default(), &[SimCommand::Choose(i as u8)]);
    assert_eq!(sim.phase(), SimPhase::Evolve);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Evolve { form: Form::Mutated, .. })));
    let (a, b) = pair(&c, 0);
    sim.world_mut().insert_resource(a);
    sim.world_mut().insert_resource(b);
    sim.step(InputFrame::default(), &[SimCommand::Ack]);
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    let i = sim
        .flow()
        .choice
        .as_ref()
        .unwrap()
        .offers
        .iter()
        .position(|o| matches!(o, Offer::Fuse { .. }))
        .unwrap();
    sim.step(InputFrame::default(), &[SimCommand::Choose(i as u8)]);
    assert_eq!(sim.phase(), SimPhase::Evolve);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Evolve { form: Form::Fused(0), .. })));
}

#[test]
fn iron_execution_only_finishes_low_health_normal_enemies() {
    let mut sim = arena();
    sim.set_build(&[], &[]);
    let mut handles = Vec::new();
    for (id, pos) in [("shade", Vec2::new(70.0, 0.0)), ("fox", Vec2::new(120.0, 0.0))] {
        let i = sim.spawn(id, pos).unwrap();
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.max_hp[i] = 1000.0;
        en.hp[i] = 100.0;
        handles.push(en.handle(i));
    }
    for h in &handles {
        let mut hit = Hit::new(*h, 1.0, Source::Weapon(3));
        hit.execute = 0.2;
        sim.world_mut().resource_mut::<HitQueue>().0.push(hit);
    }
    advance(&mut sim, 1);
    let en = sim.world().resource::<Enemies>();
    assert!(en.resolve(handles[0]).is_none());
    assert!(en.resolve(handles[1]).is_some(), "精英不被斩杀");
}
