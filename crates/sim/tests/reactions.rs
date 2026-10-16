//! 五行印记与反应、照见圈与灯焰带、闪避段数、封印与保底（docs/GAMEPLAY.md 第 4.2、5.8、6.2 节）。

mod common;

use bevy_math::{Vec2, ops};
use lantern_content::Element;
use lantern_sim::combat::Source;
use lantern_sim::{InputFrame, Offer, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase};

use common::content;

fn arena(weapons: &[(&str, u32, bool)], passives: &[(&str, u32)], enemy: &str, n: usize) -> SimHarness {
    let mut setup = RunSetup::new(7, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.quiet();
    sim.set_build(weapons, passives);
    for k in 0..n {
        let a = k as f32 / n as f32 * std::f32::consts::TAU;
        let r = 70.0 + (k % 3) as f32 * 25.0;
        sim.spawn(enemy, Vec2::new(ops::cos(a), ops::sin(a)) * r);
    }
    sim
}

fn run_for(sim: &mut SimHarness, seconds: f32) -> Vec<SimEvent> {
    let mut events = Vec::new();
    let end = sim.tick() + (seconds * 60.0) as u64;
    let mut guard = 0;
    while sim.tick() < end && guard < 100_000 {
        guard += 1;
        let cmds: &[SimCommand] = if sim.phase() == SimPhase::LevelUp { &[SimCommand::Skip] } else { &[] };
        sim.step(InputFrame::default(), cmds);
        events.extend(sim.take_events());
    }
    events
}

#[test]
fn water_marks_then_fire_steams() {
    let c = content();
    let steam = c.elements.reaction_between(Element::Water, Element::Fire).unwrap() as u8;
    // 法器等级低一些，妖物不会在蒸腾之前就被打死
    let mut sim = arena(&[("bell", 1, false), ("lamp", 1, false)], &[], "golem", 30);
    let events = run_for(&mut sim, 6.0);
    let n = events.iter().filter(|e| matches!(e, SimEvent::Reaction { kind, .. } if *kind == steam)).count();
    assert!(n > 0, "霜铃打上水印记，灯火命中时蒸腾");
    assert!(
        sim.damage_log().0.iter().any(|(s, d)| *s == Source::Reaction(steam) && *d > 0.0),
        "蒸腾造成伤害"
    );
    // 只有一系的法器不会反应
    let mut solo = arena(&[("lamp", 1, false)], &[], "golem", 30);
    let events = run_for(&mut solo, 6.0);
    assert!(!events.iter().any(|e| matches!(e, SimEvent::Reaction { .. })));
}

#[test]
fn first_reaction_holds_time_briefly() {
    let mut sim = arena(&[("bell", 8, false), ("lamp", 8, false)], &[], "golem", 30);
    let mut at = None;
    for _ in 0..60 * 10 {
        sim.step(InputFrame::default(), &[]);
        if sim.take_events().iter().any(|e| matches!(e, SimEvent::Reaction { first: true, .. })) {
            at = Some(sim.tick());
            break;
        }
    }
    let at = at.expect("10 秒内应该发生反应");
    for _ in 0..18 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.tick(), at, "第一次反应停顿 0.3 秒");
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.tick(), at + 1);
}

/// 存档里见过的反应不再算第一次（不停顿、不出说明），但这一局触发过的仍记进结算。
#[test]
fn reactions_known_from_the_save_are_not_first_again() {
    let mut setup = RunSetup::new(7, RunMode::Normal);
    setup.god = true;
    setup.known_reactions = u32::MAX;
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.quiet();
    sim.set_build(&[("bell", 8, false), ("lamp", 8, false)], &[]);
    for k in 0..30 {
        let a = k as f32 / 30.0 * std::f32::consts::TAU;
        sim.spawn("golem", Vec2::new(ops::cos(a), ops::sin(a)) * 80.0);
    }
    let events = run_for(&mut sim, 6.0);
    assert!(events.iter().any(|e| matches!(e, SimEvent::Reaction { .. })));
    assert!(!events.iter().any(|e| matches!(e, SimEvent::Reaction { first: true, .. })));
    let disc = sim.world().resource::<lantern_sim::reactions::Discoveries>();
    assert_ne!(disc.run, 0, "这一局触发过的照样记");
    assert_ne!(disc.run, u32::MAX, "结算只记这一局的，不把存档里的算进来");
}

#[test]
fn reactions_are_labelled_at_most_every_two_seconds() {
    let mut sim = arena(&[("bell", 8, true), ("lamp", 8, true)], &[], "golem", 60);
    let events = run_for(&mut sim, 6.0);
    let all: Vec<_> = events
        .iter()
        .filter_map(|e| match e {
            SimEvent::Reaction { kind, label, .. } => Some((*kind, *label)),
            _ => None,
        })
        .collect();
    let kinds: std::collections::BTreeSet<u8> = all.iter().map(|(k, _)| *k).collect();
    for k in kinds {
        let labels = all.iter().filter(|(kk, l)| *kk == k && *l).count();
        assert!(labels <= 4, "6 秒里同一种反应最多提示 3–4 次，实际 {labels}");
    }
}

#[test]
fn flame_band_burns_the_edge_of_the_reveal_circle() {
    let mut sim = arena(&[("seal", 1, false)], &[("dengxin", 3)], "golem", 0);
    let r = sim.stats().get(lantern_content::Stat::Reveal);
    for k in 0..12 {
        let a = k as f32 / 12.0 * std::f32::consts::TAU;
        sim.spawn("golem", Vec2::new(ops::cos(a), ops::sin(a)) * (r - 6.0));
    }
    run_for(&mut sim, 2.0);
    assert!(sim.damage_log().0.iter().any(|(s, d)| *s == Source::Band && *d > 0.0));
}

#[test]
fn qinggong_gives_three_dashes() {
    let mut sim = arena(&[("lamp", 1, false)], &[("qinggong", 5)], "shade", 0);
    // 先把三段攒满
    run_for(&mut sim, 4.0);
    let mut dashes = 0;
    for _ in 0..60 {
        sim.step(InputFrame::quantize(Vec2::X), &[SimCommand::Dash]);
        dashes += sim.take_events().iter().filter(|e| matches!(e, SimEvent::Dash { .. })).count();
    }
    // 三段闪避，冷却 1.2 秒内补不回来
    assert_eq!(dashes, 3);
}

#[test]
fn banish_removes_an_offer_for_the_rest_of_the_run() {
    let c = content();
    let mut sim = arena(&[("lamp", 1, false)], &[], "shade", 0);
    sim.flow_mut().banishes = 1;
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.phase(), SimPhase::LevelUp);
    let first = sim.flow().choice.as_ref().unwrap().offers[0];
    let banned = first.banned(sim.arsenal(), sim.build()).expect("不是补给");
    sim.step(InputFrame::default(), &[SimCommand::Banish(0)]);
    assert_eq!(sim.flow().banishes, 0);
    assert!(sim.build().banished.contains(&banned));
    let offers = lantern_sim::build::offers(&c, sim.arsenal(), sim.build(), 0.0);
    assert!(offers.iter().all(|(o, _)| o.banned(sim.arsenal(), sim.build()) != Some(banned)));
    assert!(!sim.flow().choice.as_ref().unwrap().offers.contains(&first));
}

#[test]
fn early_level_ups_show_two_new_weapons() {
    for seed in 1..=40 {
        let mut setup = RunSetup::new(seed, RunMode::Normal);
        setup.god = true;
        let mut sim = SimHarness::with_setup(content(), setup);
        sim.quiet();
        let mut seen = std::collections::BTreeSet::new();
        for _ in 0..5 {
            sim.progress_mut().pending_levels = 1;
            sim.step(InputFrame::default(), &[]);
            assert_eq!(sim.phase(), SimPhase::LevelUp);
            for o in &sim.flow().choice.as_ref().unwrap().offers {
                if let Offer::NewWeapon(d) = o {
                    seen.insert(*d);
                }
            }
            sim.step(InputFrame::default(), &[SimCommand::Skip]);
        }
        assert!(seen.len() >= 2, "种子 {seed}：前 5 次升级只出现了 {} 件新法器", seen.len());
    }
}

/// 余印：带印记的妖物死时，印记传给附近 60 以内还没有印记的妖物，最多 3 只。
#[test]
fn marks_pass_on_when_a_marked_enemy_dies() {
    let c = content();
    let mut sim = arena(&[], &[], "golem", 0);
    let water = Element::Water.index() as u8 + 1;
    let victim = sim.spawn("golem", Vec2::new(300.0, 0.0)).unwrap();
    let near: Vec<usize> =
        (0..5).map(|k| sim.spawn("golem", Vec2::new(300.0 + 10.0 * k as f32, 30.0)).unwrap()).collect();
    let marked_already = sim.spawn("golem", Vec2::new(300.0, -30.0)).unwrap();
    let far = sim.spawn("golem", Vec2::new(420.0, 0.0)).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<lantern_sim::Enemies>();
        (en.mark[victim], en.mark_t[victim]) = (water, 2.0);
        (en.mark[marked_already], en.mark_t[marked_already]) = (Element::Fire.index() as u8 + 1, 2.0);
        // 灼烧把它烧死
        (en.hp[victim], en.burn_t[victim], en.burn_dps[victim], en.burn_stacks[victim]) =
            (0.01, 1.0, 100.0, 1.0);
    }
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    assert!(!en.alive[victim]);
    let got: Vec<usize> = near.iter().copied().filter(|&j| en.mark[j] == water).collect();
    assert_eq!(got.len(), 3, "最多传给 3 只");
    assert!(got.iter().all(|&j| (en.mark_t[j] - c.elements.marks.duration).abs() < 0.05), "重新计时");
    assert_eq!(en.mark[marked_already], Element::Fire.index() as u8 + 1, "已有印记的不覆盖");
    assert_eq!(en.mark[far], 0, "60 以外的不传");
}
