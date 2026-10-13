//! 单局层：点灯、铜钱、合围、夜主阶段与结界、更与精英词缀、货郎、燃灯充能、夜签规则
//! （docs/GAMEPLAY.md 第 8–12 节，docs/BALANCE.md 第 4、9、10、12 节）。

mod common;

use bevy_math::Vec2;
use lantern_content::{Element, Rule, Stat};
use lantern_sim::boss::BossState;
use lantern_sim::enemies::{TAG_CHILD, TAG_MINIBOSS};
use lantern_sim::flow::{ChestSource, LampReward};
use lantern_sim::gold::Coins;
use lantern_sim::lanterns::Lanterns;
use lantern_sim::run::Director;
use lantern_sim::{InputFrame, OmenPick, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase};

use common::content;

fn setup(seed: u64) -> RunSetup {
    let mut s = RunSetup::new(seed, RunMode::Normal);
    s.god = true;
    s
}

fn quiet(seed: u64) -> SimHarness {
    let mut sim = SimHarness::with_setup(content(), setup(seed));
    sim.quiet();
    sim
}

/// 只留下时间表里满足条件的第一项，并让它马上发生；其余刷怪照样关掉。
fn only_event(seed: u64, tier: u8, keep: impl Fn(&lantern_content::PlanEvent) -> bool) -> SimHarness {
    let c = content();
    let mut s = setup(seed);
    s.tier = tier;
    let mut sim = SimHarness::with_setup(content(), s);
    let mut plan = sim.world().resource::<lantern_sim::run::RunPlan>().clone();
    sim.quiet();
    plan.schedule.retain(|st| keep(&c.run.schedule[st.index].event));
    plan.schedule.truncate(1);
    for st in &mut plan.schedule {
        st.at = 0.0;
    }
    sim.world_mut().resource_mut::<lantern_sim::run::RunPlan>().schedule = plan.schedule;
    sim
}

fn player_pos(sim: &SimHarness) -> Vec2 {
    sim.world()
        .iter_entities()
        .find_map(|e| e.get::<lantern_sim::Player>().and(e.get::<lantern_sim::Pos>()).map(|p| p.0))
        .unwrap()
}

fn walk_to(sim: &mut SimHarness, target: Vec2, max_steps: u32) {
    for _ in 0..max_steps {
        let d = target - player_pos(sim);
        if d.length() < 8.0 {
            break;
        }
        sim.step(InputFrame::quantize(d.normalize_or_zero()), &[]);
    }
}

#[test]
fn five_lanterns_are_placed_one_per_sector() {
    let c = content();
    let sim = quiet(3);
    let l = sim.world().resource::<Lanterns>();
    assert_eq!(l.0.len(), 5);
    let mut sectors: Vec<usize> =
        l.0.iter()
            .map(|x| {
                let d = x.pos.length();
                assert!(d >= c.run.lanterns.distance.0 && d <= c.run.lanterns.distance.1);
                let a = bevy_math::ops::atan2(x.pos.y, x.pos.x).rem_euclid(std::f32::consts::TAU);
                (a / (std::f32::consts::TAU / 5.0)) as usize
            })
            .collect();
    sectors.sort();
    assert_eq!(sectors, [0, 1, 2, 3, 4]);
}

#[test]
fn standing_by_a_lantern_lights_it_and_offers_a_reward() {
    let mut sim = quiet(3);
    let target = sim.world().resource::<Lanterns>().0[0].pos;
    // 在灯旁停下：先走过去
    walk_to(&mut sim, target, 60 * 30);
    let mut lit = false;
    for _ in 0..60 * 5 {
        sim.step(InputFrame::default(), &[]);
        if sim.phase() == SimPhase::Lantern {
            lit = true;
            break;
        }
    }
    assert!(lit, "站 3 秒应该点亮");
    assert!(sim.world().resource::<Lanterns>().0[0].lit);
    let rewards = sim.flow().lamp.clone().unwrap();
    assert!(rewards.contains(&LampReward::Gold));
    let i = rewards.iter().position(|&r| r == LampReward::Gold).unwrap() as u8;
    let before = sim.progress().gold;
    sim.step(InputFrame::default(), &[SimCommand::Choose(i)]);
    assert_eq!(sim.phase(), SimPhase::Play);
    sim.step(InputFrame::default(), &[]);
    assert!(sim.progress().gold >= before + 20.0);
    // 光区：照见光区里的妖物
    let reveal = sim.world().resource::<lantern_sim::reveal::Reveal>();
    assert_eq!(reveal.zones.len(), 1);
}

#[test]
fn coins_are_picked_up_and_fly_in_at_dawn() {
    let mut sim = quiet(5);
    let p = player_pos(&sim);
    {
        let mut coins = sim.world_mut().resource_mut::<Coins>();
        coins.drop(p + Vec2::new(30.0, 0.0), 5.0, 400);
        coins.drop(p + Vec2::new(900.0, 0.0), 7.0, 400);
    }
    for _ in 0..60 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.progress().gold, 5.0, "近的被吸过来，远的不会自己飞回");
    assert_eq!(sim.world().resource::<Coins>().0.len(), 1);
}

#[test]
fn encirclement_spawns_a_ring_that_rushes_in() {
    let mut sim = only_event(1, 1, |e| matches!(e, lantern_content::PlanEvent::Encircle { .. }));
    let mut warned = false;
    let mut count = 0;
    for _ in 0..120 {
        sim.step(InputFrame::default(), &[]);
        for e in sim.take_events() {
            match e {
                SimEvent::EncircleWarn { .. } => warned = true,
                SimEvent::Encircle { count: n } => count = n,
                _ => {}
            }
        }
    }
    assert!(warned);
    assert!(count >= 20, "40 × 0.7 = 28 只左右，实际 {count}");
    let en = sim.enemies();
    let rushing = en.iter_alive().filter(|&i| en.rush[i] > 0.0).count();
    assert!(rushing > 0);
}

#[test]
fn miniboss_drops_a_three_chest_with_priority() {
    let mut sim = quiet(7);
    sim.set_build(&[("lamp", 6, false), ("sword", 2, false)], &[]);
    sim.flow_mut().chest_queue.push_back(ChestSource::MiniBoss);
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.phase(), SimPhase::Chest);
    let items = &sim.flow().chest.as_ref().unwrap().items;
    assert!(items.len() >= 3);
    // 第一项升级等级最高的灯火
    assert_eq!(items[0].offer, lantern_sim::Offer::WeaponUp(0));
}

#[test]
fn ghoul_spawns_as_miniboss_at_five_minutes() {
    let c = content();
    let mut sim = only_event(2, 1, |e| matches!(e, lantern_content::PlanEvent::MiniBoss { .. }));
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    let ghoul = c.enemy_index("ghoul").unwrap() as u16;
    let i = en.iter_alive().find(|&i| en.kind[i] == ghoul).expect("青面鬼出场");
    assert!(en.tags[i] & TAG_MINIBOSS != 0);
    assert_eq!(en.affix[i], 0, "小头目不带词缀");
}

#[test]
fn second_watch_makes_enemies_tougher_and_elites_get_affixes() {
    let c = content();
    let one = quiet(4);
    let mut s2 = setup(4);
    s2.tier = 2;
    let two = SimHarness::with_setup(content(), s2);
    assert!((two.stats().get(Stat::EnemyHp) - one.stats().get(Stat::EnemyHp) * 1.4).abs() < 1e-4);
    assert_eq!(two.stats().get(Stat::Affixes), 1.0);
    let mut s3 = setup(4);
    s3.tier = 3;
    let three = SimHarness::with_setup(content(), s3);
    assert!(three.stats().rule(Rule::BossExtra));
    assert!((three.stats().get(Stat::Healing) - 0.75).abs() < 1e-5);
    // 二更的精英带一个词缀
    drop(two);
    let mut sim = only_event(4, 2, |e| matches!(e, lantern_content::PlanEvent::Elite(_)));
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    let i = en.iter_alive().find(|&i| c.enemies[en.kind[i] as usize].rank == lantern_content::Rank::Elite);
    let i = i.expect("精英出场");
    assert_eq!(en.affix[i].count_ones(), 1);
}

#[test]
fn split_elites_break_into_four_small_ones() {
    let c = content();
    let mut sim = quiet(9);
    let fen = c.affixes.iter().position(|a| a.id == "fen").unwrap();
    let i = sim.spawn("fox", Vec2::new(200.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().affix[i] = 1 << fen;
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = 0.001;
    sim.set_build(&[("sword", 8, false)], &[]);
    let fox = c.enemy_index("fox").unwrap() as u16;
    let mut children = 0;
    for _ in 0..240 {
        sim.step(InputFrame::default(), &[]);
        let en = sim.enemies();
        children = children
            .max(en.iter_alive().filter(|&j| en.kind[j] == fox && en.tags[j] & TAG_CHILD != 0).count());
    }
    assert_eq!(children, 4);
}

#[test]
fn boss_phases_bring_illusions_and_sweeps() {
    let c = content();
    let mut sim = quiet(6);
    let boss = c.enemy_index("jiuwei").unwrap();
    let i = sim.spawn("jiuwei", Vec2::new(300.0, 0.0)).unwrap();
    let h = sim.enemies().handle(i);
    sim.world_mut().resource_mut::<Director>().boss = Some(h);
    let max = sim.enemies().max_hp[i];
    assert_eq!(sim.enemies().kind[i] as usize, boss);
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = max * 0.5;
    sim.step(InputFrame::default(), &[]);
    let st = sim.world().resource::<BossState>();
    assert_eq!(st.phase, 2);
    assert_eq!(st.illusions.len(), 2, "二阶段分出两个幻身");
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = max * 0.2;
    let mut swept = false;
    for _ in 0..60 * 5 {
        sim.step(InputFrame::default(), &[]);
        if sim.take_events().iter().any(|e| matches!(e, SimEvent::SweepWarn { .. })) {
            swept = true;
        }
    }
    assert_eq!(sim.world().resource::<BossState>().phase, 3);
    assert!(swept, "三阶段会九尾扫");
}

#[test]
fn boss_retries_after_the_enemy_cap_has_room() {
    let c = content();
    let mut sim = only_event(6, 1, |e| matches!(e, lantern_content::PlanEvent::Boss { .. }));
    sim.set_build(&[], &[]);
    let cap = c.run.spawn.hard_cap as usize;
    for k in 0..cap {
        sim.spawn("shade", Vec2::new(2000.0 + k as f32 * 30.0, 0.0)).unwrap();
    }
    assert!(sim.spawn("shade", Vec2::ZERO).is_none());

    for _ in 0..2 {
        sim.step(InputFrame::default(), &[]);
        assert!(sim.world().resource::<Director>().boss.is_none());
        assert!(!sim.world().resource::<lantern_sim::run::RunPlan>().schedule[0].done);
        assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::BossArrived { .. })));
    }

    sim.world_mut().resource_mut::<lantern_sim::Enemies>().kill(0);
    sim.step(InputFrame::default(), &[]);
    let boss = sim.world().resource::<Director>().boss.expect("腾出槽位后夜主出场");
    let i = sim.enemies().resolve(boss).unwrap();
    assert_eq!(c.enemies[sim.enemies().kind[i] as usize].rank, lantern_content::Rank::Boss);
    assert_eq!(sim.enemies().count, cap);
    assert!(sim.world().resource::<lantern_sim::run::RunPlan>().schedule[0].done);
    assert_eq!(sim.take_events().iter().filter(|e| matches!(e, SimEvent::BossArrived { .. })).count(), 1);

    sim.world_mut().resource_mut::<lantern_sim::Enemies>().kill(1);
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.world().resource::<Director>().boss, Some(boss));
    assert_eq!(sim.enemies().count, cap - 1);
    assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::BossArrived { .. })));
}

#[test]
fn illusions_inside_the_reveal_circle_dispel() {
    let mut sim = quiet(6);
    let i = sim.spawn("jiuwei", Vec2::new(300.0, 0.0)).unwrap();
    let h = sim.enemies().handle(i);
    sim.world_mut().resource_mut::<Director>().boss = Some(h);
    let max = sim.enemies().max_hp[i];
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = max * 0.5;
    // 照见圈罩到 200 以外（等级很高时照见圈到上限 220）：幻身在圈里，0.5 秒后散
    sim.set_build(&[], &[("dengxin", 5)]);
    sim.progress_mut().level = 200;
    sim.world_mut().resource_mut::<lantern_sim::stats::StatsDirty>().0 = true;
    let mut gone = false;
    for _ in 0..90 {
        sim.step(InputFrame::default(), &[]);
        if sim.take_events().iter().any(|e| matches!(e, SimEvent::IllusionDispelled { .. })) {
            gone = true;
        }
    }
    assert!(gone);
}

#[test]
fn boss_barrier_keeps_the_player_inside() {
    let mut sim = quiet(6);
    sim.world_mut().resource_mut::<Director>().barrier = Some((Vec2::ZERO, 200.0));
    for _ in 0..60 * 5 {
        sim.step(InputFrame::quantize(Vec2::X), &[]);
    }
    assert!(player_pos(&sim).length() <= 200.0);
}

#[test]
fn merchant_sells_a_chest_for_gold() {
    let mut sim = quiet(8);
    sim.progress_mut().gold = 100.0;
    sim.flow_mut().shop = Some(lantern_sim::flow::Shop { chest_cost: 40, charm_cost: 80, charm_ok: false });
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.phase(), SimPhase::Shop);
    sim.step(InputFrame::default(), &[SimCommand::Choose(0)]);
    assert_eq!(sim.phase(), SimPhase::Chest, "买完就开宝箱");
    // 花掉 40，宝箱附带 10–20
    let g = sim.progress().gold;
    assert!((70.0..=80.0).contains(&g), "{g}");
}

#[test]
fn ult_charges_by_clear_amount() {
    let c = content();
    let mut sim = quiet(10);
    sim.set_build(&[("sword", 8, true)], &[]);
    for k in 0..40 {
        let a = k as f32 * 0.3;
        sim.spawn("shade", Vec2::new(bevy_math::ops::cos(a), bevy_math::ops::sin(a)) * 120.0);
    }
    for _ in 0..60 * 4 {
        sim.step(InputFrame::default(), &[]);
    }
    let kills = sim.progress().kills as f32;
    let per_kill = 10.0 / (lantern_sim::spawn::base_spawn_hp(&c, 0.0) * c.player.ult.clear_seconds);
    assert!(kills > 10.0);
    assert!((sim.progress().ult - (kills * per_kill).min(1.0)).abs() < 0.05, "{}", sim.progress().ult);

    // 三更：妖物更厚、刷得更快，分母一起乘上，充能节奏不随难度变快（docs/BALANCE.md 第 2.6 节）
    let mut s = setup(10);
    s.tier = 3;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim.set_build(&[("sword", 8, true)], &[]);
    for k in 0..40 {
        let a = k as f32 * 0.3;
        sim.spawn("shade", Vec2::new(bevy_math::ops::cos(a), bevy_math::ops::sin(a)) * 120.0);
    }
    for _ in 0..60 * 6 {
        sim.step(InputFrame::default(), &[]);
    }
    let kills = sim.progress().kills as f32;
    let spawn = sim.stats().get(Stat::SpawnRate);
    assert!(kills > 10.0);
    assert!(
        (sim.progress().ult - (kills * per_kill / spawn).min(1.0)).abs() < 0.05,
        "{} vs {}",
        sim.progress().ult,
        kills * per_kill / spawn
    );
}

#[test]
fn reverse_omen_disables_sheng_and_doubles_ke_reactions() {
    let mut s = setup(1);
    s.omen = Some(OmenPick { id: "nike".into(), element: None });
    let mut sim = SimHarness::with_setup(content(), s);
    sim.set_build(&[], &[("zhezhi", 5), ("luxin", 5)]);
    assert!(sim.build().sheng[0], "木生火点亮了");
    // 只剩红纸灯的 +20%
    assert!((sim.stats().get(Stat::BurnDamage) - 1.2).abs() < 1e-5, "但相生被动无效");
    assert_eq!(sim.stats().get(Stat::KeReaction), 2.0);
    let el = &content().elements;
    let ke = el.reaction_between(Element::Water, Element::Fire).unwrap();
    assert!(Element::Water.overcomes(Element::Fire) && ke < el.reactions.len());
}

/// docs/BALANCE.md 第 12.6 节：赤面狐蓄力时原地转向，出手后方向锁定，冲出约 speed × duration。
#[test]
fn fox_winds_up_then_pounces_in_a_locked_direction() {
    use lantern_sim::enemies::{CHARGE_DASH, CHARGE_IDLE, CHARGE_RECOVER, CHARGE_WINDUP};
    let c = content();
    let fox = &c.enemies[c.enemy_index("fox").unwrap()];
    let ch = fox.charge.clone().expect("赤面狐会扑击");
    let mut sim = quiet(11);
    let i = sim.spawn("fox", Vec2::new(200.0, 0.0)).unwrap();
    // 冷却好了，主角在范围里：下一步开始蓄力
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().charge_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    assert_eq!(en.charge[i], CHARGE_WINDUP);
    let start = Vec2::new(en.x[i], en.y[i]);
    // 蓄力途中主角往下走，狐狸原地转向跟着
    let steps = (ch.windup * 60.0).round() as usize - 2;
    for _ in 0..steps {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
    }
    let en = sim.enemies();
    assert_eq!(en.charge[i], CHARGE_WINDUP);
    assert!(Vec2::new(en.x[i], en.y[i]).distance(start) < 1.0, "蓄力时不动");
    assert!(en.charge_dy[i] > 0.05, "转向跟着主角：{}", en.charge_dy[i]);
    // 出手：方向锁定，主角再怎么走也不变
    while sim.enemies().charge[i] == CHARGE_WINDUP {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
    }
    assert_eq!(sim.enemies().charge[i], CHARGE_DASH);
    let locked = (sim.enemies().charge_dx[i], sim.enemies().charge_dy[i]);
    let from = Vec2::new(sim.enemies().x[i], sim.enemies().y[i]);
    while sim.enemies().charge[i] == CHARGE_DASH {
        sim.step(InputFrame::quantize(-Vec2::Y), &[]);
        assert_eq!((sim.enemies().charge_dx[i], sim.enemies().charge_dy[i]), locked);
    }
    let en = sim.enemies();
    assert_eq!(en.charge[i], CHARGE_RECOVER);
    let dist = Vec2::new(en.x[i], en.y[i]).distance(from);
    let want = ch.speed * ch.duration;
    assert!((dist - want).abs() < want * 0.15, "扑出 {dist}，应约 {want}");
    // 收势后回到冷却，等 every 秒再出手
    let steps = (ch.recover * 60.0).round() as usize + 1;
    for _ in 0..steps {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.enemies().charge[i], CHARGE_IDLE);
    assert!(sim.enemies().charge_t[i] > ch.every - 0.1);
}

#[test]
fn freezing_a_fox_interrupts_its_pounce() {
    use lantern_sim::enemies::{CHARGE_IDLE, CHARGE_WINDUP};
    let mut sim = quiet(12);
    let i = sim.spawn("fox", Vec2::new(200.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().charge_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.enemies().charge[i], CHARGE_WINDUP);
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().frozen[i] = 1.0;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.enemies().charge[i], CHARGE_IDLE);
}

#[test]
fn a_pounce_hits_harder_than_a_bump() {
    use lantern_sim::enemies::CHARGE_DASH;
    let c = content();
    let fox = &c.enemies[c.enemy_index("fox").unwrap()];
    let mult = fox.charge.as_ref().unwrap().damage_mult;
    let hit = |dash: bool| {
        let mut s = RunSetup::new(13, RunMode::Normal);
        s.god = false;
        let mut sim = SimHarness::with_setup(content(), s);
        sim.quiet();
        let i = sim.spawn("fox", Vec2::new(5.0, 0.0)).unwrap();
        {
            let mut en = sim.world_mut().resource_mut::<lantern_sim::Enemies>();
            en.charge_t[i] = 5.0;
            if dash {
                en.charge[i] = CHARGE_DASH;
                en.charge_t[i] = 1.0;
                en.charge_dx[i] = -1.0;
            }
        }
        let before = sim.player_hp();
        sim.step(InputFrame::default(), &[]);
        before - sim.player_hp()
    };
    let (bump, pounce) = (hit(false), hit(true));
    assert!(bump > 0.0);
    // 减去护甲之前是 1.5 倍；默认没有护甲
    assert!((pounce / bump - mult).abs() < 0.01, "扑击 {pounce}，碰撞 {bump}");
}
