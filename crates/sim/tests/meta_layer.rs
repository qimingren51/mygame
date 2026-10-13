//! 局外层进入单局的部分：灯、余烬、属性、灯坠（docs/GAMEPLAY.md 第 5.7、11 节）。

mod common;

use bevy_math::Vec2;
use lantern_content::Stat;
use lantern_sim::charms::{Survival, Trail};
use lantern_sim::combat::Source;
use lantern_sim::flow::Shop;
use lantern_sim::{
    HitKind, InputFrame, Offer, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase,
};

use common::content;

fn setup(seed: u64) -> RunSetup {
    let mut s = RunSetup::new(seed, RunMode::Normal);
    s.charm_pool = content().charms.iter().map(|c| c.id.clone()).collect();
    s
}

fn quiet(s: RunSetup) -> SimHarness {
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim
}

fn idle(sim: &mut SimHarness, steps: u32) {
    for _ in 0..steps {
        sim.step(InputFrame::default(), &[]);
    }
}

fn charm_ids(sim: &SimHarness) -> Vec<String> {
    let c = content();
    sim.build().charms.iter().map(|&k| c.charms[k].id.clone()).collect()
}

#[test]
fn lamp_sets_start_weapon_and_trait() {
    let c = content();
    let mut s = setup(1);
    s.lamp = Some("mirror".into());
    let sim = SimHarness::with_setup(content(), s);
    assert_eq!(c.weapons[sim.arsenal().0[0].def].id, "sword");
    assert!((sim.stats().get(Stat::CritChance) - 0.15).abs() < 1e-5, "基础 5% + 铜镜 10%");
    assert!((sim.stats().max_hp() - 85.0).abs() < 1e-3);
    assert_eq!(sim.build().lamp_element, Some(lantern_content::Element::Metal));
    // 不写灯就用红纸灯
    let sim = SimHarness::with_setup(content(), setup(1));
    assert_eq!(c.weapons[sim.arsenal().0[0].def].id, "lamp");
}

#[test]
fn ember_offers_a_starting_passive_choice() {
    let c = content();
    let mut s = setup(3);
    s.meta.insert("ember".into(), 2);
    s.meta.insert("luck".into(), 1);
    let mut sim = quiet(s);
    idle(&mut sim, 1);
    assert_eq!(sim.phase(), SimPhase::LevelUp);
    let choice = sim.flow().choice.clone().unwrap();
    assert!(choice.ember && choice.offers.len() == 3);
    assert!(choice.offers.iter().all(|o| matches!(o, Offer::NewPassive(_))), "只出心法：{:?}", choice.offers);
    // 重抽也只出心法；不算升级、时间不走
    sim.step(InputFrame::default(), &[SimCommand::Reroll]);
    let choice = sim.flow().choice.clone().unwrap();
    assert!(choice.ember && choice.offers.iter().all(|o| matches!(o, Offer::NewPassive(_))));
    assert_eq!(sim.tick(), 1);
    let Offer::NewPassive(d) = choice.offers[0] else { unreachable!() };
    sim.step(InputFrame::default(), &[SimCommand::Choose(0)]);
    assert_eq!(sim.phase(), SimPhase::Play);
    assert_eq!(sim.build().passives.len(), 1);
    assert_eq!(sim.build().passives[0].def, d);
    assert_eq!(sim.build().passives[0].level, 2.min(c.passives[d].max_level));
    assert_eq!(sim.flow().ember, 0);

    // 跳过什么也不给
    let mut s = setup(3);
    s.meta.insert("ember".into(), 1);
    let mut sim = quiet(s);
    idle(&mut sim, 1);
    sim.step(InputFrame::default(), &[SimCommand::Skip]);
    assert_eq!(sim.phase(), SimPhase::Play);
    assert!(sim.build().passives.is_empty());
    assert_eq!(sim.flow().oil_bonus, 0);
}

#[test]
fn attributes_and_worn_charms_modify_stats() {
    let mut s = setup(1);
    s.attributes.insert("damage".into(), 4);
    s.charms = vec!["longevity".into()];
    let sim = SimHarness::with_setup(content(), s);
    // 伤害：属性 +20%，长命锁 −10%；生命 +60
    assert!((sim.stats().get(Stat::Damage) - 1.1).abs() < 1e-5);
    assert_eq!(sim.stats().max_hp(), 160.0);
}

#[test]
fn charm_choice_wears_then_replaces_when_full() {
    let mut sim = quiet(setup(5));
    sim.flow_mut().charm_queue = 1;
    idle(&mut sim, 1);
    assert_eq!(sim.phase(), SimPhase::Charm);
    let offers = sim.flow().charm.as_ref().unwrap().offers.clone();
    assert_eq!(offers.len(), 3);
    sim.step(InputFrame::default(), &[SimCommand::Choose(1)]);
    assert_eq!(sim.phase(), SimPhase::Play);
    assert_eq!(sim.build().charms, [offers[1]]);

    // 挂满 3 枚之后：先选新的，再选换下哪一枚；Skip 返回、再 Skip 放弃
    sim.world_mut().resource_mut::<lantern_sim::Build>().charms = vec![0, 1, 2];
    sim.flow_mut().charm_queue = 1;
    idle(&mut sim, 1);
    let offers = sim.flow().charm.as_ref().unwrap().offers.clone();
    assert!(offers.iter().all(|k| ![0, 1, 2].contains(k)), "不出已经挂着的");
    sim.step(InputFrame::default(), &[SimCommand::Choose(0)]);
    assert_eq!(sim.flow().charm.as_ref().unwrap().picked, Some(0));
    sim.step(InputFrame::default(), &[SimCommand::Skip]);
    assert_eq!(sim.flow().charm.as_ref().unwrap().picked, None);
    sim.step(InputFrame::default(), &[SimCommand::Choose(2)]);
    sim.step(InputFrame::default(), &[SimCommand::Choose(1)]);
    assert_eq!(sim.build().charms, [0, offers[2], 2]);
    assert_eq!(sim.phase(), SimPhase::Play);
}

#[test]
fn no_charm_choice_without_unlocked_charms() {
    let mut s = setup(5);
    s.charm_pool.clear();
    let mut sim = quiet(s);
    sim.flow_mut().charm_queue = 1;
    idle(&mut sim, 2);
    assert_eq!(sim.phase(), SimPhase::Play);
}

#[test]
fn miniboss_chest_and_merchant_give_charm_choices() {
    let mut sim = quiet(setup(9));
    sim.flow_mut().chest_queue.push_back(lantern_sim::flow::ChestSource::MiniBoss);
    idle(&mut sim, 1);
    assert_eq!(sim.phase(), SimPhase::Chest);
    sim.step(InputFrame::default(), &[SimCommand::Ack]);
    // 升级、进化演出可能排在前面；一路确认到灯坠
    for _ in 0..20 {
        if sim.phase() == SimPhase::Charm {
            break;
        }
        let cmds = common::respond(&sim);
        sim.step(InputFrame::default(), &cmds);
    }
    assert_eq!(sim.phase(), SimPhase::Charm);
    sim.step(InputFrame::default(), &[SimCommand::Skip]);
    assert_eq!(sim.phase(), SimPhase::Play);

    sim.progress_mut().gold = 100.0;
    sim.flow_mut().shop = Some(Shop { chest_cost: 40, charm_cost: 80, charm_ok: false });
    idle(&mut sim, 1);
    assert_eq!(sim.phase(), SimPhase::Shop);
    assert!(sim.flow().shop.unwrap().charm_ok);
    sim.step(InputFrame::default(), &[SimCommand::Choose(1)]);
    assert_eq!(sim.phase(), SimPhase::Charm);
    assert_eq!(sim.progress().gold, 20.0);
}

#[test]
fn no_charm_to_give_means_gold_instead() {
    // 解锁的只有一枚，而且已经挂上了
    let mut s = setup(9);
    s.charm_pool = vec!["longevity".into()];
    s.charms = vec!["longevity".into()];
    let mut sim = quiet(s);
    sim.flow_mut().chest_queue.push_back(lantern_sim::flow::ChestSource::MiniBoss);
    idle(&mut sim, 1);
    let gold = sim.progress().gold;
    assert!(gold >= 10.0 + 20.0, "宝箱附带 10–20，灯坠改给 20：{gold}");
    assert_eq!(sim.flow().charm_queue, 0);
    // 货郎不卖灯坠，买了也不扣钱
    for _ in 0..20 {
        if sim.phase() == SimPhase::Play {
            break;
        }
        let cmds = common::respond(&sim);
        sim.step(InputFrame::default(), &cmds);
    }
    sim.progress_mut().gold = 100.0;
    sim.flow_mut().shop = Some(Shop { chest_cost: 40, charm_cost: 80, charm_ok: true });
    idle(&mut sim, 1);
    assert!(!sim.flow().shop.unwrap().charm_ok);
    sim.step(InputFrame::default(), &[SimCommand::Choose(1)]);
    assert_eq!(sim.phase(), SimPhase::Shop);
    assert_eq!(sim.progress().gold, 100.0);
}

/// 让主角挨一下致命伤：在身上摆一只妖物，把它的接触伤害调到很高。
fn lethal_hit(sim: &mut SimHarness) {
    let i = sim.spawn("shade", Vec2::ZERO).unwrap();
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().damage[i] = 10_000.0;
    idle(sim, 1);
}

#[test]
fn elixir_revives_once_and_breaks() {
    let mut s = setup(2);
    s.charms = vec!["elixir".into()];
    let mut sim = quiet(s);
    lethal_hit(&mut sim);
    let events = sim.take_events();
    assert!(events.iter().any(|e| matches!(e, SimEvent::Revived { .. })));
    assert!(!sim.is_over());
    let hp = sim.player_hp();
    assert!((hp - sim.stats().max_hp() * 0.5).abs() < 1e-3, "回复 50%：{hp}");
    idle(&mut sim, 2);
    assert!(charm_ids(&sim).is_empty(), "金丹碎掉");
    // 震退全屏：身上那只被推开了
    assert!(sim.enemies().kx.iter().zip(&sim.enemies().alive).any(|(k, a)| *a && k.abs() > 100.0));
    // 无敌时间过后再挨一下就真的倒下
    idle(&mut sim, 130);
    lethal_hit(&mut sim);
    idle(&mut sim, 1);
    assert!(sim.is_over(), "金丹只救一次");
    assert!(sim.world().resource::<Survival>().revived);
}

#[test]
fn last_stand_comes_before_elixir() {
    let mut s = setup(2);
    s.charms = vec!["elixir".into()];
    s.meta.insert("afterglow".into(), 2);
    let mut sim = quiet(s);
    lethal_hit(&mut sim);
    let events = sim.take_events();
    assert!(events.iter().any(|e| matches!(e, SimEvent::LastStand { .. })));
    assert!(!events.iter().any(|e| matches!(e, SimEvent::Revived { .. })));
    let max = sim.stats().max_hp();
    assert!((sim.player_hp() - (1.0 + max * 0.3)).abs() < 1e-3);
    assert_eq!(charm_ids(&sim), ["elixir"]);
}

#[test]
fn pillar_rewards_standing_still() {
    let mut s = setup(4);
    s.charms = vec!["pillar".into()];
    s.god = true;
    let mut sim = quiet(s);
    // 站定 1 秒以上：伤害 +25%
    idle(&mut sim, 70);
    let i = sim.spawn("golem", Vec2::new(30.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = 1e9;
    let before = sim.enemies().hp[i];
    let _ = sim.take_events();
    idle(&mut sim, 60);
    let still: f32 = sim
        .take_events()
        .iter()
        .filter_map(|e| match e {
            SimEvent::Hit { damage, crit: false, kind: HitKind::Normal, .. } => Some(*damage),
            _ => None,
        })
        .fold(0.0, f32::max);
    assert!(still > 0.0 && before > 0.0);
    // 移动时：伤害 −10%。同一件法器的单次命中之比 = 0.9 / 1.25
    let mut moving = 0.0f32;
    for k in 0..120 {
        let dir = if (k / 30) % 2 == 0 { Vec2::Y } else { -Vec2::Y };
        sim.step(InputFrame::quantize(dir), &[]);
        for e in sim.take_events() {
            if let SimEvent::Hit { damage, crit: false, kind: HitKind::Normal, .. } = e {
                moving = moving.max(damage);
            }
        }
    }
    assert!(moving > 0.0);
    assert!((moving / still - 0.9 / 1.25).abs() < 0.02, "{moving} / {still}");
}

#[test]
fn ice_soul_doubles_xp_from_frozen_kills() {
    let mut s = setup(6);
    s.charms = vec!["ice_soul".into()];
    let mut sim = quiet(s);
    let i = sim.spawn("shade", Vec2::new(500.0, 0.0)).unwrap();
    let k = sim.spawn("shade", Vec2::new(-500.0, 0.0)).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<lantern_sim::Enemies>();
        en.frozen[i] = 5.0;
        en.hp[i] = 0.0;
        en.hp[k] = 0.0;
    }
    // 生命归零的妖物在下一次结算命中时死去；直接打一下
    let h = [sim.enemies().handle(i), sim.enemies().handle(k)];
    for h in h {
        sim.world_mut()
            .resource_mut::<lantern_sim::combat::HitQueue>()
            .0
            .push(lantern_sim::combat::Hit::new(h, 1.0, Source::Ult));
    }
    idle(&mut sim, 1);
    let gems = sim.world().resource::<lantern_sim::Gems>();
    let mut values: Vec<f32> = gems.value[..gems.n].to_vec();
    values.sort_by(f32::total_cmp);
    assert_eq!(values.len(), 2);
    assert!((values[1] / values[0] - 2.0).abs() < 1e-4, "{values:?}");
}

#[test]
fn wind_wheel_dash_leaves_a_burning_trail() {
    let mut s = setup(8);
    s.charms = vec!["wind_wheel".into()];
    let mut sim = quiet(s);
    sim.step(InputFrame::quantize(Vec2::X), &[SimCommand::Dash]);
    idle(&mut sim, 12);
    let n = sim.world().resource::<Trail>().list.len();
    assert!(n >= 5, "闪避 115 左右，每 14 一段：{n}");
    let i = sim.spawn("golem", Vec2::new(60.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = 1e9;
    idle(&mut sim, 60);
    assert!(sim.damage_log().0.iter().any(|(s, d)| *s == Source::Trail && *d > 0.0));
    idle(&mut sim, 120);
    assert!(sim.world().resource::<Trail>().list.is_empty(), "2 秒后熄灭");
}

#[test]
fn flawless_elite_counts_only_without_damage() {
    let mut sim = quiet(setup(10));
    let i = sim.spawn("ghoul", Vec2::new(800.0, 0.0)).unwrap();
    let h = sim.enemies().handle(i);
    sim.world_mut().resource_mut::<Survival>().watch.push((h, 0));
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = 0.0;
    sim.world_mut().resource_mut::<lantern_sim::combat::HitQueue>().0.push(lantern_sim::combat::Hit::new(
        h,
        1.0,
        Source::Ult,
    ));
    idle(&mut sim, 1);
    assert_eq!(sim.world().resource::<Survival>().flawless, 1);
}
