//! 构筑：属性叠加、五行共鸣、相生太极、升级选项、升级流程、宝箱（对应网页版 tests/sim/build.test.ts）。

mod common;

use bevy_math::Vec2;
use lantern_content::{Element, Stat};
use lantern_sim::build::Awaken;
use lantern_sim::flow::ChestSource;
use lantern_sim::{InputFrame, Offer, OmenPick, RunMode, RunSetup, SimCommand, SimHarness, SimPhase};

use common::content;

fn fresh(seed: u64) -> SimHarness {
    let mut setup = RunSetup::new(seed, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(content(), setup);
    sim.quiet();
    sim
}

fn idle(sim: &mut SimHarness) {
    sim.step(InputFrame::default(), &[]);
}

#[test]
fn passives_stack_stats_by_level() {
    let mut sim = fresh(1);
    sim.set_build(&[("lamp", 1, false)], &[("changming", 3), ("ruimu", 2), ("houde", 1)]);
    let s = sim.stats();
    assert!((s.get(Stat::Area) - 1.3).abs() < 1e-5);
    assert_eq!(s.max_hp(), 120.0);
    assert_eq!(s.get(Stat::Armor), 1.0);
    // 锐目 2 级 +10%，没有金系共鸣
    assert!((s.get(Stat::CritChance) - 0.15).abs() < 1e-5);
    assert_eq!(sim.player_hp(), 120.0);
}

#[test]
fn zhezhi_adds_amount_at_levels_1_3_5() {
    let mut sim = fresh(1);
    let amounts: Vec<u32> = (0..=5)
        .map(|lv| {
            let passives: Vec<(&str, u32)> = if lv == 0 { vec![] } else { vec![("zhezhi", lv)] };
            sim.set_build(&[], &passives);
            sim.stats().amount()
        })
        .collect();
    // 5 级折纸计 3 点，木系一阶，还不到二阶（数量 +1 要 7 点）
    assert_eq!(amounts, [0, 1, 1, 2, 2, 3]);
}

#[test]
fn a_max_level_weapon_counts_three_points_and_wakes_a_tier() {
    let mut sim = fresh(1);
    let woke = sim.set_build(&[("lamp", 8, false)], &[]);
    assert_eq!(sim.build().points[Element::Fire.index()], 3);
    assert_eq!(sim.build().tiers[Element::Fire.index()], 1);
    assert!(woke.contains(&Awaken::Tier { element: Element::Fire, tier: 1 }));
    assert_eq!(sim.world().resource::<lantern_sim::Effects>().hit.len(), 1, "火一阶：命中附加灼烧");
}

#[test]
fn points_follow_investment() {
    let mut sim = fresh(1);
    let pts = |sim: &mut SimHarness, w: &[(&str, u32, bool)], p: &[(&str, u32)]| {
        sim.set_build(w, p);
        sim.build().points
    };
    let f = Element::Fire.index();
    assert_eq!(pts(&mut sim, &[("lamp", 3, false)], &[])[f], 1);
    assert_eq!(pts(&mut sim, &[("lamp", 4, false)], &[])[f], 2);
    assert_eq!(pts(&mut sim, &[("lamp", 8, true)], &[])[f], 4);
    assert_eq!(pts(&mut sim, &[], &[("luxin", 2)])[f], 1);
    assert_eq!(pts(&mut sim, &[], &[("luxin", 3)])[f], 2);
    // 无属性心法不计点
    assert_eq!(pts(&mut sim, &[], &[("qinggong", 5), ("juhun", 5)]), [0; 5]);
    // 一阶 3、二阶 7、三阶 12
    sim.set_build(&[("lamp", 8, true)], &[("luxin", 5), ("changming", 5), ("dengxin", 2)]);
    assert_eq!(sim.build().points[f], 11);
    assert_eq!(sim.build().tiers[f], 2);
    sim.set_build(&[("lamp", 8, true)], &[("luxin", 5), ("changming", 5), ("dengxin", 3)]);
    assert_eq!(sim.build().tiers[f], 3);
}

#[test]
fn extreme_tier_replaces_tier_three() {
    let mut sim = fresh(1);
    let full: [(&str, u32); 3] = [("jianyi", 5), ("ruimu", 5), ("xunfeng", 5)];
    sim.set_build(&[("sword", 8, true)], &full);
    assert_eq!(sim.build().tiers[Element::Metal.index()], 3);
    let crit = &sim.world().resource::<lantern_sim::Effects>().crit;
    assert_eq!(crit.len(), 1);
    assert!(crit[0].chance < 1.0, "三阶：50% 追加飞剑");
    // P0 的内容一系最多 13 点，到不了极境；这里借夜签的加点凑到 20
    sim.world_mut().resource_mut::<lantern_sim::Build>().bonus = Some((Element::Metal, 10));
    let woke = sim.set_build(&[("sword", 8, true)], &full);
    assert!(woke.contains(&Awaken::Tier { element: Element::Metal, tier: 4 }));
    let crit = &sim.world().resource::<lantern_sim::Effects>().crit;
    assert_eq!(crit.len(), 1, "极境取代三阶，不会每次暴击追加两把");
    assert_eq!(crit[0].chance, 1.0);
}

#[test]
fn new_passives_change_stats() {
    let mut sim = fresh(1);
    sim.set_build(&[], &[("qinggong", 5), ("hanyi", 2), ("dengxin", 1), ("zaiwu", 2), ("houde", 3)]);
    let s = sim.stats();
    assert_eq!(s.get(Stat::DashCharges), 3.0);
    assert!((s.get(Stat::DashCooldown) - 2.4 * 0.5).abs() < 1e-4);
    assert!((s.get(Stat::SlowPower) - 0.12).abs() < 1e-5);
    assert_eq!(s.get(Stat::FlameBand), 1.0);
    // 载物 2 级：每点护甲伤害 +2%，厚德 3 级护甲 3 点
    assert!((s.get(Stat::Damage) - 1.06).abs() < 1e-5);
    assert!((s.get(Stat::Reveal) - 130.0 * 1.06).abs() < 1e-3);
}

#[test]
fn reveal_grows_with_level() {
    let mut sim = fresh(1);
    sim.progress_mut().level = 11;
    sim.world_mut().resource_mut::<lantern_sim::stats::StatsDirty>().0 = true;
    idle(&mut sim);
    assert!((sim.stats().get(Stat::Reveal) - 143.0).abs() < 1e-3);
    sim.progress_mut().level = 200;
    sim.world_mut().resource_mut::<lantern_sim::stats::StatsDirty>().0 = true;
    idle(&mut sim);
    assert_eq!(sim.stats().get(Stat::Reveal), 220.0, "照见圈最大 220");
}

#[test]
fn metal_tier_one_adds_crit() {
    let mut sim = fresh(1);
    sim.set_build(&[], &[("jianyi", 5)]);
    assert_eq!(sim.build().tiers[Element::Metal.index()], 1);
    assert!((sim.stats().get(Stat::CritChance) - 0.15).abs() < 1e-5);
}

#[test]
fn sheng_and_taiji_light_up() {
    let mut sim = fresh(1);
    sim.set_build(&[], &[("zhezhi", 5), ("luxin", 5)]);
    assert!(sim.build().sheng[0], "木生火");
    // 红纸灯 +20%（相加），木生火 ×1.3
    assert!((sim.stats().get(Stat::BurnDamage) - 1.56).abs() < 1e-5);
    let woke =
        sim.set_build(&[], &[("zhezhi", 5), ("luxin", 5), ("jianyi", 5), ("jingxin", 5), ("houde", 5)]);
    assert!(sim.build().taiji);
    assert!(woke.contains(&Awaken::Taiji));
    assert_eq!(sim.world().resource::<lantern_sim::Effects>().periodic.len(), 1, "太极每 30 秒全屏");
}

#[test]
fn element_omen_gives_points_and_favor() {
    let mut setup = RunSetup::new(1, RunMode::Normal);
    setup.omen = Some(OmenPick { id: "element".into(), element: Some(Element::Water) });
    let sim = SimHarness::with_setup(content(), setup);
    assert_eq!(sim.build().points[Element::Water.index()], 3);
    assert_eq!(sim.build().tiers[Element::Water.index()], 1);
    assert_eq!(sim.build().favor, Some(Element::Water));
}

#[test]
fn meta_and_omen_modify_stats() {
    let mut setup = RunSetup::new(1, RunMode::Normal);
    setup.attributes.insert("health".into(), 5);
    setup.omen = Some(OmenPick { id: "glass".into(), element: None });
    let sim = SimHarness::with_setup(content(), setup);
    // (100 + 10 × 5) × (1 − 0.35) = 97.5，取整为 98
    assert_eq!(sim.stats().max_hp(), 98.0);
    // 加成区相加：琉璃夜 +40%
    assert!((sim.stats().get(Stat::Damage) - 1.4).abs() < 1e-5);
}

#[test]
fn evolution_offer_needs_max_level_and_passive() {
    let c = content();
    let mut sim = fresh(1);
    sim.set_build(&[("lamp", 8, false)], &[]);
    let offers = lantern_sim::build::offers(&c, sim.arsenal(), sim.build(), 0.0);
    assert!(!offers.iter().any(|(o, _)| matches!(o, Offer::Evolve(_))), "没有长明不能进化");
    assert!(!offers.iter().any(|(o, _)| *o == Offer::WeaponUp(0)), "满级不再出升级");
    sim.set_build(&[("lamp", 8, false)], &[("changming", 1)]);
    let offers = lantern_sim::build::offers(&c, sim.arsenal(), sim.build(), 0.0);
    assert!(offers.contains(&(Offer::Evolve(0), c.run.choices.weight_evolve)));
}

#[test]
fn when_everything_is_maxed_only_supplies_remain() {
    let c = content();
    let mut sim = fresh(1);
    let weapons: Vec<(&str, u32, bool)> = c.weapons.iter().map(|w| (w.id.as_str(), 8, true)).collect();
    let passives: Vec<(&str, u32)> = c.passives.iter().take(6).map(|p| (p.id.as_str(), 5)).collect();
    sim.set_build(&weapons, &passives);
    sim.progress_mut().pending_levels = 1;
    idle(&mut sim);
    assert_eq!(sim.phase(), SimPhase::LevelUp);
    assert_eq!(sim.flow().choice.as_ref().unwrap().offers, [Offer::Heal, Offer::Oil]);
}

#[test]
fn choosing_an_evolution_plays_the_show_then_continues() {
    let mut sim = fresh(5);
    sim.set_build(&[("lamp", 8, false)], &[("changming", 1)]);
    sim.progress_mut().pending_levels = 1;
    idle(&mut sim);
    let i = sim.flow().choice.as_ref().unwrap().offers.iter().position(|o| matches!(o, Offer::Evolve(_)));
    let i = i.expect("进化必出") as u8;
    sim.step(InputFrame::default(), &[SimCommand::Choose(i)]);
    assert_eq!(sim.phase(), SimPhase::Evolve);
    assert_eq!(sim.flow().evolving, Some(0));
    assert!(sim.arsenal().0[0].evolved);
    sim.step(InputFrame::default(), &[SimCommand::Ack]);
    assert_eq!(sim.phase(), SimPhase::Play);
}

#[test]
fn chests_open_one_three_or_five_and_apply_immediately() {
    let mut counts = std::collections::BTreeSet::new();
    for seed in 1..=40 {
        let mut sim = fresh(seed);
        let levels = |sim: &SimHarness| {
            sim.arsenal().0.iter().map(|w| w.level).sum::<u32>()
                + sim.build().passives.iter().map(|p| p.level).sum::<u32>()
        };
        sim.set_build(&[("lamp", 1, false), ("sword", 1, false)], &[("luxin", 1)]);
        let before = levels(&sim);
        sim.flow_mut().chest_queue.push_back(ChestSource::Elite);
        idle(&mut sim);
        assert_eq!(sim.phase(), SimPhase::Chest);
        let n = sim.flow().chest.as_ref().unwrap().items.len() as u32;
        counts.insert(n);
        assert_eq!(levels(&sim), before + n, "宝箱只开升级");
        sim.step(InputFrame::default(), &[SimCommand::Ack]);
        assert_eq!(sim.phase(), SimPhase::Play);
    }
    assert!(counts.iter().all(|n| [1, 3, 5].contains(n)), "{counts:?}");
    assert!(counts.contains(&1));
}

#[test]
fn elites_drop_a_chest_that_opens_when_picked_up() {
    let mut sim = fresh(3);
    // 灯火的火圈中间是空的，贴身的妖物打不到；这里用符剑
    sim.set_build(&[("sword", 8, false)], &[]);
    // 精英在附近，飞剑慢慢打死它；之后走过去捡宝箱
    sim.spawn("fox", Vec2::new(120.0, 0.0));
    let mut opened = false;
    for _ in 0..60 * 60 {
        if sim.phase() == SimPhase::Chest {
            opened = true;
            break;
        }
        let cmds = common::respond(&sim);
        let me = sim.world().iter_entities().find_map(|e| e.get::<lantern_sim::Pos>().map(|p| p.0));
        let chest = sim
            .world()
            .resource::<lantern_sim::pickups::Pickups>()
            .0
            .iter()
            .find(|p| p.kind == lantern_sim::pickups::PickupKind::Chest)
            .map(|p| p.pos);
        let input = match (me, chest) {
            (Some(me), Some(chest)) => InputFrame::quantize((chest - me).normalize_or_zero()),
            _ => InputFrame::default(),
        };
        sim.step(input, &cmds);
    }
    assert!(opened, "精英死后应该掉宝箱并打开");
}
