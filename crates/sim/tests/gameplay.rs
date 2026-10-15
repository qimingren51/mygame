//! 玩法场景测试：搭一局最小的模拟，跑若干步，断言结果（docs/DESIGN.md 第 13 节）。

mod common;

use bevy_math::{Vec2, ops};
use lantern_content::Stat;
use lantern_sim::{InputFrame, Offer, RunMode, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase};

use common::{bot_step, content, respond};

/// 绕大圈走（像玩家放风筝），返回这一步的输入。
fn kite(tick: u64) -> InputFrame {
    let t = tick as f32 / 60.0;
    InputFrame::quantize(Vec2::new(ops::cos(t * 0.5), ops::sin(t * 0.5)))
}

#[test]
fn a_normal_run_spawns_kills_and_levels_up() {
    let mut sim = SimHarness::new(content(), 7);
    let mut kills = 0;
    let mut hits = 0;
    let mut levels = 0;
    let mut step = 0;
    while sim.tick() < 90 * 60 && !sim.is_over() {
        bot_step(&mut sim, kite(step), &[]);
        step += 1;
        for ev in sim.take_events() {
            match ev {
                SimEvent::Kill { .. } => kills += 1,
                SimEvent::Hit { .. } => hits += 1,
                SimEvent::LevelUp { .. } => levels += 1,
                _ => {}
            }
        }
    }
    assert!(sim.enemies().count > 10, "90 秒后场上应该有妖物，现在 {}", sim.enemies().count);
    assert!(hits >= kills && kills > 20, "法器应该命中并击杀妖物：命中 {hits}，击杀 {kills}");
    assert_eq!(sim.progress().kills, kills);
    assert!(sim.progress().level >= 3 && levels >= 2, "应该捡到魂火升级，现在 {} 级", sim.progress().level);
    let build = sim.arsenal().0.len() + sim.build().passives.len();
    assert!(build >= 3, "升级时应该选到了新法器或心法，现在只有 {build} 项");
}

#[test]
fn level_up_waits_for_a_choice_and_time_stops() {
    let mut sim = SimHarness::new(content(), 11);
    let mut step = 0;
    while sim.phase() == SimPhase::Play && step < 60 * 60 {
        sim.step(kite(step), &[]);
        step += 1;
    }
    assert_eq!(sim.phase(), SimPhase::LevelUp, "一分钟内应该升级");
    let tick = sim.tick();
    let choice = sim.flow().choice.clone().expect("有选项");
    assert!((3..=4).contains(&choice.offers.len()), "三选一（灵光一闪时四选一）：{:?}", choice.offers);
    // 选择阶段时间不走，闪避命令被丢弃
    for _ in 0..30 {
        sim.step(kite(0), &[SimCommand::Dash]);
    }
    assert_eq!(sim.tick(), tick);
    // 重抽两次后次数用完
    let rerolls = sim.flow().rerolls;
    assert_eq!(rerolls, content().stat(Stat::Rerolls).base as u32);
    for _ in 0..rerolls + 1 {
        sim.step(InputFrame::default(), &[SimCommand::Reroll]);
    }
    assert_eq!(sim.flow().rerolls, 0);
    let before = sim.arsenal().0.len() + sim.build().passives.len();
    let offer = sim.flow().choice.as_ref().unwrap().offers[0];
    sim.step(InputFrame::default(), &[SimCommand::Choose(0)]);
    // 选了新东西或升级，回到 Play（或接着下一次升级）
    let after = sim.arsenal().0.len() + sim.build().passives.len();
    match offer {
        Offer::NewWeapon(_) | Offer::NewPassive(_) => assert_eq!(after, before + 1),
        _ => assert_eq!(after, before),
    }
    assert_ne!(sim.phase(), SimPhase::Over);
}

#[test]
fn skipping_a_level_gives_oil() {
    let mut sim = SimHarness::new(content(), 11);
    let mut step = 0;
    while sim.phase() != SimPhase::LevelUp && step < 60 * 60 {
        sim.step(kite(step), &[]);
        step += 1;
    }
    sim.step(InputFrame::default(), &[SimCommand::Skip]);
    assert_eq!(sim.flow().oil_bonus, content().run.choices.skip_oil);
}

#[test]
fn standing_still_eventually_gets_the_player_killed() {
    let mut sim = SimHarness::new(content(), 3);
    for _ in 0..10 * 60 * 60 * 2 {
        if sim.is_over() {
            break;
        }
        let cmds = respond(&sim);
        sim.step(InputFrame::default(), &cmds);
    }
    assert!(sim.is_over(), "站着不动 10 分钟应该会倒下");
    assert_eq!(sim.player_hp(), 0.0);
    let result = sim.flow().result.clone().expect("有结算");
    assert!(!result.won);
    assert!(result.oil > 0, "倒下也有灯油：{result:?}");
}

#[test]
fn bench_mode_keeps_enemy_count_and_player_alive() {
    let mut sim = SimHarness::with_mode(content(), 1, RunMode::Bench { enemies: 1000 });
    for tick in 0..20 * 60 {
        sim.step(kite(tick), &[]);
    }
    let count = sim.enemies().count;
    assert!((950..=1000).contains(&count), "跑分模式应保持约 1000 只，现在 {count}");
    assert!(!sim.is_over());
    assert_eq!(sim.player_hp(), content().stat(Stat::MaxHp).base);
    assert_eq!(sim.progress().level, 1, "跑分模式不升级");
    assert_eq!(sim.phase(), SimPhase::Play);
}

/// 机器人（无敌）整局：10 分钟内升到 20 级以上、出现进化，并在击败夜主后天明。
/// 对应网页版 tests/sim/run.test.ts。
#[test]
fn bot_full_run_defeats_the_boss() {
    let mut setup = RunSetup::new(424242, RunMode::Normal);
    setup.god = true;
    // 出发前挂风火轮；局内可能出现全部灯坠（5:00 小头目必给一次三选一）
    setup.charms = vec!["wind_wheel".into()];
    setup.charm_pool = content().charms.iter().map(|c| c.id.clone()).collect();
    let mut sim = SimHarness::with_setup(content(), setup);
    let mut levels = Vec::new();
    let mut step = 0u64;
    let mut elites = 0;
    let mut boss = false;
    while !sim.is_over() && step < 60 * 60 * 14 {
        let (input, cmds) = common::bot_input(sim.tick());
        let tick = sim.tick();
        bot_step(&mut sim, input, &cmds);
        step += 1;
        if sim.tick() != tick && sim.tick().is_multiple_of(1800) {
            levels.push(sim.progress().level);
        }
        for ev in sim.take_events() {
            match ev {
                SimEvent::Elite { .. } => elites += 1,
                SimEvent::BossArrived { .. } => boss = true,
                _ => {}
            }
        }
    }
    let c = content();
    let weapons: Vec<String> = sim
        .arsenal()
        .0
        .iter()
        .map(|w| {
            format!("{}{}", c.weapons[w.def].id, if w.evolved { "★".into() } else { w.level.to_string() })
        })
        .collect();
    let passives: Vec<String> =
        sim.build().passives.iter().map(|p| format!("{}{}", c.passives[p.def].id, p.level)).collect();
    let mut dmg = sim.damage_log().0.clone();
    dmg.sort_by(|a, b| b.1.total_cmp(&a.1));
    eprintln!(
        "整局：每 30 秒等级 {levels:?}；击杀 {}；进化 {}；用时 {:.0} 秒；法器 {weapons:?}；心法 {passives:?}；伤害 {dmg:?}",
        sim.progress().kills,
        sim.build().evolutions,
        sim.tick() as f32 / 60.0,
    );
    assert!(levels.len() >= 12, "至少跑到 6 分钟：{levels:?}");
    assert!(levels[5] >= 8, "3 分钟时的等级：{levels:?}");
    assert!(levels[11] >= 14, "6 分钟时的等级：{levels:?}");
    assert!(sim.progress().level >= 20);
    assert!(sim.build().evolutions >= 1);
    assert!(sim.progress().kills > 1000);
    assert!(elites >= 4 && boss, "精英 {elites} 次，夜主 {boss}");
    assert!(sim.build().charms.len() >= 2, "小头目给了灯坠：{:?}", sim.build().charms);
    let result = sim.flow().result.clone().expect("有结算");
    assert!(result.won, "无敌时击败夜主就会天明：{result:?}");
}

#[test]
fn bench_can_fill_5000_slots_without_raising_the_normal_cap() {
    let c = content();
    let cap = c.run.spawn.hard_cap as usize;
    let mut sim = SimHarness::with_mode(c.clone(), 7, RunMode::Bench { enemies: 5000 });
    sim.set_build(&[], &[]);
    for _ in 0..120 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.enemies().count, 5000);
    let mut en = lantern_sim::Enemies::default();
    let mut rng = lantern_core::Pcg32::new(7, 1);
    let stats = lantern_sim::Stats::base(&c);
    for _ in 0..cap {
        assert!(lantern_sim::spawn::spawn_enemy(&c, &stats, &mut en, &mut rng, 0, 0.0, 0.0, 0.0).is_some());
    }
    assert!(lantern_sim::spawn::spawn_enemy(&c, &stats, &mut en, &mut rng, 0, 0.0, 0.0, 0.0).is_none());
    assert_eq!(en.count, cap);
}

#[test]
fn invalid_xp_cannot_loop_or_overflow_levels() {
    for need in [0.0, -1.0, f32::NAN, f32::INFINITY] {
        let mut c = content();
        c.run.xp_need = lantern_content::Quad(need, 0.0, 0.0);
        let mut sim = SimHarness::new(c, 7);
        sim.quiet();
        sim.progress_mut().xp = 100.0;
        sim.step(InputFrame::default(), &[]);
        assert_eq!(sim.progress().level, 1);
        assert_eq!(sim.progress().pending_levels, 0);
    }
    let mut sim = SimHarness::new(content(), 7);
    sim.quiet();
    sim.progress_mut().xp = f32::INFINITY;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.progress().level, 1);
}
