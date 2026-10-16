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
    assert!((two.stats().get(Stat::EnemyHp) - one.stats().get(Stat::EnemyHp) * 1.5).abs() < 1e-4);
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
fn uncharged_ult_reports_rejection_without_changing_simulation() {
    for charge in [0.0, 0.5, 0.999] {
        let mut sim = quiet(10);
        let mut control = quiet(10);
        sim.progress_mut().ult = charge;
        control.progress_mut().ult = charge;
        sim.take_events();
        control.take_events();
        for _ in 0..60 {
            sim.step(InputFrame::default(), &[SimCommand::Ult]);
            control.step(InputFrame::default(), &[]);
            let mut events = sim.take_events();
            assert_eq!(events.iter().filter(|e| **e == SimEvent::UltNotReady).count(), 1);
            assert!(!events.contains(&SimEvent::Ult));
            events.retain(|e| *e != SimEvent::UltNotReady);
            assert_eq!(events, control.take_events(), "除了未满提示，其余模拟事件相同");
            assert_eq!(sim.progress().ult, charge, "失败不消耗充能");
        }
        assert!(!sim.hashes().is_empty());
        assert_eq!(sim.hashes(), control.hashes(), "未满时反复尝试不改变状态哈希");
    }
}

#[test]
fn charged_ult_fires_once_and_rejects_a_second_attempt() {
    let mut sim = quiet(10);
    sim.progress_mut().ult = 1.0;
    sim.take_events();
    sim.step(InputFrame::default(), &[SimCommand::Ult, SimCommand::Ult]);
    let events = sim.take_events();
    let ult_events: Vec<_> =
        events.iter().filter(|e| matches!(e, SimEvent::Ult | SimEvent::UltNotReady)).copied().collect();
    assert_eq!(ult_events, [SimEvent::Ult, SimEvent::UltNotReady]);
    assert_eq!(sim.progress().ult, 0.0);
    assert!(
        events.iter().any(|e| matches!(e, SimEvent::Strike { fx: lantern_sim::combat::StrikeFx::Ult, .. }))
    );
}

#[test]
fn ult_outside_play_has_no_rejection_feedback() {
    let mut sim = quiet(10);
    sim.progress_mut().pending_levels = 1;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.phase(), SimPhase::LevelUp);
    sim.take_events();
    sim.step(InputFrame::default(), &[SimCommand::Ult]);
    assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::Ult | SimEvent::UltNotReady)));
    assert_eq!(sim.phase(), SimPhase::LevelUp);
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
    let per_kill = 10.0 / (lantern_sim::spawn::base_spawn_hp(&c, false, 0.0) * c.player.ult.clear_seconds);
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
    // 蓄力途中主角往下走，狐狸原地转向跟着（到锁定之前）
    let steps = ((ch.windup - ch.lock) * 60.0).round() as usize - 2;
    for _ in 0..steps {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
    }
    let en = sim.enemies();
    assert_eq!(en.charge[i], CHARGE_WINDUP);
    assert!(Vec2::new(en.x[i], en.y[i]).distance(start) < 1.0, "蓄力时不动");
    assert!(en.charge_dy[i] > 0.05, "转向跟着主角：{}", en.charge_dy[i]);
    // 出手前 lock 秒锁定：主角往回走，方向不再变
    for _ in 0..4 {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
    }
    let locked = (sim.enemies().charge_dx[i], sim.enemies().charge_dy[i]);
    while sim.enemies().charge[i] == CHARGE_WINDUP {
        sim.step(InputFrame::quantize(-Vec2::Y), &[]);
        assert_eq!((sim.enemies().charge_dx[i], sim.enemies().charge_dy[i]), locked, "锁定后不再转向");
    }
    assert_eq!(sim.enemies().charge[i], CHARGE_DASH);
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
            en.grace[i] = 0.0;
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

/// 无尽夜（docs/BALANCE.md 第 4.7 节）：10 分钟以后每 5 分钟一次妖潮，妖潮结束时夜主再来，
/// 生命逐次 × 1.25；夜主倒下不天明，夜续下去。
#[test]
fn endless_night_brings_surges_and_tougher_bosses() {
    let c = content();
    let mut s = setup(3);
    s.mode = RunMode::Endless;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim.set_build(&[("sword", 8, false)], &[]);
    // 跳到 15:00 前一刻，当作第一个夜主已经来过、倒下
    let hz = u64::from(lantern_core::step::TICK_HZ);
    sim.world_mut().resource_mut::<lantern_sim::Tick>().0 = 15 * 60 * hz - 1;
    {
        let mut d = sim.world_mut().resource_mut::<Director>();
        let e = d.endless.as_mut().unwrap();
        (e.arrivals, e.downs) = (1, 1);
    }
    let mut surge_at = None;
    let mut boss_at = None;
    for _ in 0..40 * hz {
        sim.step(InputFrame::default(), &[]);
        for ev in sim.take_events() {
            match ev {
                SimEvent::Surge => surge_at = Some(sim.tick()),
                SimEvent::BossArrived { .. } => boss_at = Some(sim.tick()),
                _ => {}
            }
        }
        if boss_at.is_some() {
            break;
        }
    }
    let (surge_at, boss_at) = (surge_at.expect("15:00 妖潮"), boss_at.expect("妖潮过后夜主再来"));
    // 事件在 15:00 那一步发出，读到时步数已经加一
    assert_eq!(surge_at, 15 * 60 * hz + 1);
    assert_eq!(boss_at - surge_at, 30 * hz, "妖潮 30 秒后夜主来");
    let jiuwei = c.enemy_index("jiuwei").unwrap();
    let handle = sim.world().resource::<Director>().boss.unwrap();
    let i = sim.enemies().resolve(handle).unwrap();
    let want = c.enemies[jiuwei].hp * sim.stats().get(Stat::BossHp) * 1.25;
    assert!(
        (sim.enemies().max_hp[i] - want).abs() < 1.0,
        "第 2 次来的生命 × 1.25：{}",
        sim.enemies().max_hp[i]
    );
    assert!(sim.world().resource::<Director>().barrier.is_some());

    // 打倒它：不天明，结界撤掉，下一个妖潮（20:00）照常来
    let p = player_pos(&sim);
    {
        let mut en = sim.world_mut().resource_mut::<lantern_sim::Enemies>();
        (en.x[i], en.y[i], en.hp[i]) = (p.x + 60.0, p.y, 0.001);
    }
    let mut down = false;
    for _ in 0..5 * hz {
        sim.step(InputFrame::default(), &[]);
        down |= sim.take_events().iter().any(|e| matches!(e, SimEvent::BossDefeated { dawn: false, .. }));
    }
    assert!(down, "无尽夜里夜主倒下不天明");
    let d = sim.world().resource::<Director>();
    assert!(d.barrier.is_none() && d.endless.unwrap().downs == 2);
    assert!(sim.flow().won_at.is_none() && !sim.is_over());
}

/// 10 分钟以后刷怪、生命改成线性增长（docs/BALANCE.md 第 4.1 节）。
#[test]
fn curves_turn_linear_after_ten_minutes() {
    let c = content();
    let r = &c.run;
    let at10 = r.enemy_hp_scale.at(10.0);
    assert_eq!(r.late_at(r.enemy_hp_scale, r.late.hp, 9.0), r.enemy_hp_scale.at(9.0));
    assert!((r.late_at(r.enemy_hp_scale, r.late.hp, 14.0) - at10 * 2.0).abs() < 1e-4);
    assert!((r.late_at(r.spawn.rate, r.late.spawn, 20.0) - r.spawn.rate.at(10.0) * 1.8).abs() < 1e-3);
}

/// 无尽夜的灯油：前 10 分钟照常，之后每秒 0.5、击杀 × 0.01；第一个夜主算天明 300，再来的每个 150。
#[test]
fn endless_oil_counts_late_time_and_bosses_separately() {
    let mut s = setup(4);
    s.mode = RunMode::Endless;
    s.god = false;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    let hz = u64::from(lantern_core::step::TICK_HZ);
    sim.world_mut().resource_mut::<lantern_sim::Tick>().0 = 1200 * hz;
    sim.progress_mut().kills = 30_000;
    {
        let mut d = sim.world_mut().resource_mut::<Director>();
        let e = d.endless.as_mut().unwrap();
        (e.late_kills, e.downs) = (20_000, 3);
    }
    let w = sim.world_mut();
    let mut q = w.query_filtered::<&mut lantern_sim::Health, bevy_ecs::query::With<lantern_sim::Player>>();
    q.single_mut(w).unwrap().hp = 0.0;
    sim.step(InputFrame::default(), &[]);
    let r = sim.flow().result.clone().expect("倒下就结算");
    assert!(r.endless && !r.won && r.bosses == 3);
    // 存活 600 + 600 × 0.5；击杀 10000 × 0.05 + 20000 × 0.01；夜主 300 + 2 × 150
    assert_eq!(&r.oil_parts[..3], &[900, 700, 600]);
}

/// 无尽夜里夜主再来时池子满了，也等腾出槽位再来，不丢、不重复。
#[test]
fn endless_boss_waits_for_room_too() {
    let c = content();
    let mut s = setup(5);
    s.mode = RunMode::Endless;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    sim.set_build(&[], &[]);
    let hz = u64::from(lantern_core::step::TICK_HZ);
    sim.world_mut().resource_mut::<lantern_sim::Tick>().0 = 20 * 60 * hz;
    {
        // 20:00 的妖潮已经来过，夜主该来了
        let mut d = sim.world_mut().resource_mut::<Director>();
        let e = d.endless.as_mut().unwrap();
        (e.wave, e.boss_due) = (2, Some(0.0));
    }
    let cap = c.run.spawn.hard_cap as usize;
    for k in 0..cap {
        sim.spawn("shade", Vec2::new(2000.0 + k as f32 * 30.0, 0.0)).unwrap();
    }
    for _ in 0..2 {
        sim.step(InputFrame::default(), &[]);
        assert!(sim.world().resource::<Director>().boss.is_none());
        assert!(sim.world().resource::<Director>().endless.unwrap().boss_due.is_some(), "还记着要来");
    }
    sim.world_mut().resource_mut::<lantern_sim::Enemies>().kill(0);
    sim.step(InputFrame::default(), &[]);
    assert!(sim.world().resource::<Director>().boss.is_some(), "腾出槽位后夜主再来");
    let e = sim.world().resource::<Director>().endless.unwrap();
    assert!(e.boss_due.is_none() && e.arrivals == 1);
    assert_eq!(sim.take_events().iter().filter(|e| matches!(e, SimEvent::BossArrived { .. })).count(), 1);
}

/// 夜深（docs/BALANCE.md 第 4.7 节）：无尽夜 10 分钟以后，生命按每分钟 × 1.2 复利涨，
/// 冻住的计时减得更快；普通一夜还是线性的 late.hp，冻住照常。
#[test]
fn deep_night_toughens_enemies_only_in_endless() {
    let c = content();
    let r = &c.run;
    let d = r.endless.depth;
    let hz = u64::from(lantern_core::step::TICK_HZ);
    let at15 = |mode: RunMode| {
        let mut s = setup(8);
        s.mode = mode;
        let mut sim = SimHarness::with_setup(content(), s);
        sim.quiet();
        sim.set_build(&[], &[]);
        sim.world_mut().resource_mut::<lantern_sim::Tick>().0 = 15 * 60 * hz;
        let i = sim.spawn("shade", Vec2::new(400.0, 0.0)).unwrap();
        sim.world_mut().resource_mut::<lantern_sim::Enemies>().frozen[i] = 1.0;
        (sim, i)
    };
    let shade = &c.enemies[c.enemy_index("shade").unwrap()];
    let (mut night, i) = at15(RunMode::Normal);
    let (mut deep, j) = at15(RunMode::Endless);
    let base = shade.hp * night.stats().get(Stat::EnemyHp);
    let linear = base * r.late_at(r.enemy_hp_scale, r.late.hp, 15.0);
    let compound = base * r.enemy_hp_scale.at(r.late.after) * bevy_math::ops::powf(d.hp_growth, 5.0);
    assert!((night.enemies().max_hp[i] - linear).abs() < linear * 1e-4, "普通一夜照线性");
    assert!((deep.enemies().max_hp[j] - compound).abs() < compound * 1e-4, "无尽夜按夜深复利");
    // 抗控制：15 分钟时 r = min(0.9, 0.25 × 5) = 0.9，冻住的计时每步减 DT × (1 + 4r)
    night.step(InputFrame::default(), &[]);
    deep.step(InputFrame::default(), &[]);
    let dt = 1.0 / hz as f32;
    let resist = (d.control * 5.0).min(d.control_max);
    assert!((1.0 - night.enemies().frozen[i] - dt).abs() < 1e-4);
    assert!((1.0 - deep.enemies().frozen[j] - dt * (1.0 + 4.0 * resist)).abs() < 1e-4);
}
