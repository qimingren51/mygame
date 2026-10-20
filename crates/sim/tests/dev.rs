//! 开发者选项（docs/PLAYTEST.md 第 13 项）：都走 `SimCommand::Dev`，回放能复现；用过的局记成开发者局。

mod common;

use bevy_math::Vec2;
use lantern_sim::weapons::Form;
use lantern_sim::{
    Dev, DevCommand, Health, InputFrame, Player, Replay, RunSetup, SimCommand, SimEvent, SimHarness, SimPhase,
};

use common::{bot_step, content};

fn dev(cmd: DevCommand) -> [SimCommand; 1] {
    [SimCommand::Dev(cmd)]
}

fn quiet(seed: u64) -> SimHarness {
    let mut sim = SimHarness::new(content(), seed);
    sim.quiet();
    sim
}

fn weapon(id: &str) -> u16 {
    content().weapon_index(id).expect("法器") as u16
}

fn slot(sim: &SimHarness, id: &str) -> Option<(u32, Form)> {
    let d = content().weapon_index(id)?;
    sim.arsenal().0.iter().find(|w| w.def == d).map(|w| (w.level, w.form))
}

fn ack(sim: &mut SimHarness) {
    while sim.phase() != SimPhase::Play {
        sim.step(InputFrame::default(), &[SimCommand::Ack]);
    }
}

#[test]
fn growth_commands_level_up_fill_ult_and_add_gold() {
    let mut sim = quiet(1);
    sim.step(InputFrame::default(), &dev(DevCommand::FillUlt));
    assert_eq!(sim.progress().ult, 1.0);
    sim.step(InputFrame::default(), &dev(DevCommand::Gold(120)));
    assert!(sim.progress().gold >= 120.0);
    sim.step(InputFrame::default(), &dev(DevCommand::Levels(5)));
    assert_eq!(sim.progress().level, 6);
    assert_eq!(sim.phase(), SimPhase::LevelUp, "照常弹出选卡");
    assert!(sim.world().resource::<Dev>().used);
}

#[test]
fn commands_outside_play_are_dropped() {
    let mut sim = quiet(1);
    sim.step(InputFrame::default(), &dev(DevCommand::Levels(1)));
    assert_eq!(sim.phase(), SimPhase::LevelUp);
    let mut probe = quiet(1);
    probe.step(InputFrame::default(), &dev(DevCommand::Levels(1)));
    sim.step(InputFrame::default(), &dev(DevCommand::FillUlt));
    probe.step(InputFrame::default(), &[]);
    assert_eq!(sim.progress().ult, probe.progress().ult, "选卡时发来的丢掉");
}

#[test]
fn god_mode_keeps_the_player_alive_and_damage_scales_hits() {
    let mut sim = quiet(2);
    sim.step(InputFrame::default(), &dev(DevCommand::God(true)));
    let before = sim.player_hp();
    for _ in 0..5 {
        sim.spawn("golem", Vec2::new(8.0, 0.0));
    }
    for _ in 0..120 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.player_hp(), before, "无敌");

    // 同一种子、同样的打法，只差伤害倍率：每一下都正好 × 100
    let hits = |scale: Option<u16>| {
        let mut sim = quiet(3);
        if let Some(n) = scale {
            sim.step(InputFrame::default(), &dev(DevCommand::Damage(n)));
        } else {
            sim.step(InputFrame::default(), &[]);
        }
        let i = sim.spawn("golem", Vec2::new(40.0, 0.0)).unwrap();
        sim.world_mut().resource_mut::<lantern_sim::Enemies>().hp[i] = 1e12;
        let _ = sim.take_events();
        let mut out = Vec::new();
        for _ in 0..90 {
            sim.step(InputFrame::default(), &[]);
            for e in sim.take_events() {
                if let SimEvent::Hit { damage, .. } = e {
                    out.push(damage);
                }
            }
        }
        out
    };
    let (plain, scaled) = (hits(None), hits(Some(100)));
    assert!(!plain.is_empty());
    assert_eq!(plain.len(), scaled.len());
    for (a, b) in plain.iter().zip(&scaled) {
        assert!((b / a - 100.0).abs() < 1e-2, "{a} → {b}");
    }
}

#[test]
fn weapons_can_be_taken_maxed_evolved_and_mutated() {
    let c = content();
    let mut sim = quiet(4);
    sim.step(InputFrame::default(), &dev(DevCommand::Weapon(weapon("sword"))));
    assert_eq!(slot(&sim, "sword"), Some((1, Form::Base)));
    sim.step(InputFrame::default(), &dev(DevCommand::Weapon(weapon("sword"))));
    assert_eq!(slot(&sim, "sword"), Some((2, Form::Base)), "已有的升一级");
    sim.step(InputFrame::default(), &dev(DevCommand::MaxWeapon(weapon("sword"))));
    let max = c.weapons[weapon("sword") as usize].levels.len() as u32;
    assert_eq!(slot(&sim, "sword"), Some((max, Form::Base)));

    // 进化：不看心法，照常演出
    let _ = sim.take_events();
    sim.step(InputFrame::default(), &dev(DevCommand::Evolve(weapon("sword"))));
    assert_eq!(slot(&sim, "sword").map(|s| s.1), Some(Form::Evolved));
    assert_eq!(sim.phase(), SimPhase::Evolve);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Evolve { form: Form::Evolved, .. })));
    ack(&mut sim);

    // 异化：没有的先拿、先满级，不看克制的条件
    let (k, mutant) =
        c.weapons.iter().enumerate().find(|(_, w)| w.mutation.is_some() && w.id != "sword").unwrap();
    sim.step(InputFrame::default(), &dev(DevCommand::Mutate(k as u16)));
    assert_eq!(slot(&sim, &mutant.id).map(|s| s.1), Some(Form::Mutated));
    assert_eq!(sim.phase(), SimPhase::Evolve);
    ack(&mut sim);

    // 已经变过形的不再变
    let before = sim.arsenal().0.clone();
    sim.step(InputFrame::default(), &dev(DevCommand::Evolve(weapon("sword"))));
    assert_eq!(sim.arsenal().0.len(), before.len());
    assert_eq!(sim.phase(), SimPhase::Play);
}

#[test]
fn fusion_takes_and_evolves_both_materials_then_fuses() {
    let c = content();
    let f = c.fusions.iter().position(|f| f.id == "frost_rain").unwrap();
    let mut sim = quiet(5);
    let _ = sim.take_events();
    sim.step(InputFrame::default(), &dev(DevCommand::Fuse(f as u16)));
    let fused: Vec<_> = sim.arsenal().0.iter().filter(|w| w.form == Form::Fused(f)).collect();
    assert_eq!(fused.len(), 1);
    assert!(
        fused[0].contains(&c, weapon("bell") as usize) && fused[0].contains(&c, weapon("sword") as usize)
    );
    assert_eq!(sim.phase(), SimPhase::Evolve, "合璧照常演出");
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Evolve { form: Form::Fused(_), .. })));
}

#[test]
fn passives_are_taken_then_leveled() {
    let mut sim = quiet(6);
    sim.step(InputFrame::default(), &dev(DevCommand::Passive(0)));
    assert_eq!(sim.build().passives.iter().find(|p| p.def == 0).map(|p| p.level), Some(1));
    sim.step(InputFrame::default(), &dev(DevCommand::Passive(0)));
    assert_eq!(sim.build().passives.iter().find(|p| p.def == 0).map(|p| p.level), Some(2));
    // 下标越界的丢掉
    sim.step(InputFrame::default(), &dev(DevCommand::Passive(u16::MAX)));
    sim.step(InputFrame::default(), &dev(DevCommand::Weapon(u16::MAX)));
    sim.step(InputFrame::default(), &dev(DevCommand::Fuse(u16::MAX)));
    assert_eq!(sim.phase(), SimPhase::Play);
}

#[test]
fn a_run_with_dev_commands_is_marked_in_the_result() {
    for used in [false, true] {
        let mut sim = quiet(7);
        let cmds: &[SimCommand] = if used { &dev(DevCommand::Gold(1)) } else { &[] };
        sim.step(InputFrame::default(), cmds);
        let world = sim.world_mut();
        let mut q = world.query_filtered::<&mut Health, bevy_ecs::query::With<Player>>();
        for mut h in q.iter_mut(world) {
            h.hp = 0.0;
        }
        for _ in 0..3 {
            sim.step(InputFrame::default(), &[]);
        }
        assert!(sim.is_over());
        assert_eq!(sim.flow().result.as_ref().unwrap().dev, used);
    }
}

/// 开发者操作进回放：存成文本再读回来，重放的每秒哈希一样
#[test]
fn dev_commands_replay_identically() {
    let mut sim = SimHarness::with_setup(content(), RunSetup::new(8, lantern_sim::RunMode::Normal));
    sim.record("test");
    let script: &[(u64, DevCommand)] = &[
        (10, DevCommand::Damage(10)),
        (20, DevCommand::Weapon(weapon("bell"))),
        (30, DevCommand::Evolve(weapon("bell"))),
        (200, DevCommand::Levels(3)),
        (400, DevCommand::God(true)),
        (500, DevCommand::FillUlt),
    ];
    for step in 0..60 * 20u64 {
        let cmds: Vec<SimCommand> =
            script.iter().filter(|(t, _)| *t == step).map(|(_, c)| SimCommand::Dev(*c)).collect();
        bot_step(&mut sim, InputFrame::quantize(Vec2::new(1.0, 0.3)), &cmds);
    }
    let replay = sim.replay().unwrap().clone();
    assert!(replay.commands.iter().any(|(_, c)| matches!(c, SimCommand::Dev(DevCommand::Evolve(_)))));
    let parsed = Replay::parse(&replay.to_ron()).expect("能解析回来");
    assert_eq!(parsed, replay);
    let mut played = SimHarness::from_replay(content(), parsed);
    while !played.playback().unwrap().finished && !played.is_over() {
        played.step(InputFrame::default(), &[]);
    }
    assert_eq!(played.playback().unwrap().diverged_at, None);
    assert_eq!(played.hashes(), sim.hashes());
    assert!(played.world().resource::<Dev>().used);
}
