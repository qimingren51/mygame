//! 青丘的三只新妖物（docs/BALANCE.md 第 12.1 节）：狐火绕圈扑击、竹魅守距射竹刺、讨封狐伪装现形，
//! 以及竹魅从竹丛里钻出来的伏击。

mod common;

use bevy_math::{Vec2, ops};
use lantern_core::step::DT;
use lantern_sim::bamboo::Bamboo;
use lantern_sim::boss::Foes;
use lantern_sim::enemies::{CHARGE_DASH, CHARGE_WINDUP, Enemies, SPAWN_GRACE, TAG_REVEALED, UNMASK_GRACE};
use lantern_sim::run::Director;
use lantern_sim::{
    HurtBy, InputFrame, Player, Pos, PrevPos, Replay, RunMode, RunSetup, SimEvent, SimHarness,
};

use common::content;

fn quiet(seed: u64, god: bool) -> SimHarness {
    let mut s = RunSetup::new(seed, RunMode::Normal);
    s.god = god;
    let mut sim = SimHarness::with_setup(content(), s);
    sim.quiet();
    // 不带法器，免得妖物还没出手就被打死
    sim.set_build(&[], &[]);
    sim
}

fn player_pos(sim: &mut SimHarness) -> Vec2 {
    let world = sim.world_mut();
    world.query_filtered::<&Pos, bevy_ecs::query::With<Player>>().single(world).unwrap().0
}

fn teleport(sim: &mut SimHarness, at: Vec2) {
    let world = sim.world_mut();
    let mut q = world.query_filtered::<(&mut Pos, &mut PrevPos), bevy_ecs::query::With<Player>>();
    let (mut pos, mut prev) = q.single_mut(world).unwrap();
    pos.0 = at;
    prev.0 = at;
}

fn at(en: &Enemies, i: usize) -> Vec2 {
    Vec2::new(en.x[i], en.y[i])
}

/// 狐火从远处靠过来，在 160–220 的带里绕圈，冷却到了就蓄力、扑出。
#[test]
fn fox_wisp_circles_in_its_band_then_pounces() {
    let mut sim = quiet(21, true);
    let p = player_pos(&mut sim);
    let i = sim.spawn("fox_wisp", p + Vec2::new(380.0, 0.0)).unwrap();
    let start_angle = {
        let d = at(sim.enemies(), i) - p;
        ops::atan2(d.y, d.x)
    };
    // 先别让它扑，单看绕圈
    sim.world_mut().resource_mut::<Enemies>().charge_t[i] = 100.0;
    for _ in 0..(6 * 60) {
        sim.step(InputFrame::default(), &[]);
    }
    let d = at(sim.enemies(), i) - p;
    assert!((150.0..=230.0).contains(&d.length()), "绕圈的距离 {}", d.length());
    let turned = (ops::atan2(d.y, d.x) - start_angle).abs();
    assert!(turned > 0.5, "绕着主角转了 {turned} 弧度");
    // 冷却好了：蓄力，再以 220 扑出
    sim.world_mut().resource_mut::<Enemies>().charge_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    assert_eq!(sim.enemies().charge[i], CHARGE_WINDUP);
    let mut dashed = false;
    for _ in 0..60 {
        sim.step(InputFrame::default(), &[]);
        dashed |= sim.enemies().charge[i] == CHARGE_DASH;
    }
    assert!(dashed, "0.4 秒蓄力以后扑出");
}

/// 每只狐火的冷却按随机相位错开在 every ± jitter 里。
#[test]
fn fox_wisp_pounce_cooldowns_are_spread_out() {
    let c = content();
    let ch = c.enemies[c.enemy_index("fox_wisp").unwrap()].charge.clone().unwrap();
    let mut sim = quiet(22, true);
    let p = player_pos(&mut sim);
    let ts: Vec<f32> = (0..12)
        .map(|k| {
            let i = sim.spawn("fox_wisp", p + Vec2::new(500.0, 40.0 * k as f32)).unwrap();
            sim.enemies().charge_t[i]
        })
        .collect();
    assert!(ts.iter().all(|&t| t >= ch.every - ch.jitter - 1e-4 && t <= ch.every + ch.jitter + 1e-4));
    let (lo, hi) = ts.iter().fold((f32::MAX, f32::MIN), |(a, b), &t| (a.min(t), b.max(t)));
    assert!(hi - lo > 0.5, "冷却错开了：{lo}–{hi}");
}

/// 竹魅停在 260–320，预警时方向锁定，然后射一根记着来源的竹刺；打中主角算竹刺伤害。
#[test]
fn bamboo_wraith_keeps_distance_and_fires_a_telegraphed_spike() {
    let c = content();
    let kind = c.enemy_index("bamboo_wraith").unwrap() as u16;
    let sh = c.enemies[kind as usize].shot.clone().unwrap();
    let mut sim = quiet(23, false);
    let p = player_pos(&mut sim);
    let i = sim.spawn("bamboo_wraith", p + Vec2::new(150.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 100.0;
    for _ in 0..(5 * 60) {
        sim.step(InputFrame::default(), &[]);
    }
    let d = (at(sim.enemies(), i) - p).length();
    assert!((250.0..=330.0).contains(&d), "退到守距的带里：{d}");
    sim.take_events();
    // 冷却好了：先预警（方向锁定），warn 秒后出手
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::EnemyAim { kind: k, .. } if *k == kind)));
    let locked = (sim.enemies().aim_dx[i], sim.enemies().aim_dy[i]);
    let origin = Vec2::new(sim.enemies().aim_x[i], sim.enemies().aim_y[i]);
    let handle = sim.enemies().handle(i);
    let steps = (sh.warn * 60.0).round() as usize;
    let mut fired = false;
    for _ in 0..steps + 1 {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
        if sim.enemies().aim_t[i] > 0.0 {
            assert_eq!((sim.enemies().aim_dx[i], sim.enemies().aim_dy[i]), locked, "预警时方向不跟着主角");
            assert_eq!(at(sim.enemies(), i), origin, "蓄力期间停步");
        }
        for e in sim.take_events() {
            if let SimEvent::EnemyShot { enemy, pos, kind: k } = e {
                assert_eq!((enemy, pos, k), (handle, origin, kind), "实际出手与预警、个体一致");
                fired = true;
            }
        }
    }
    assert!(fired, "预警 {} 秒后出手", sh.warn);
    let foes = sim.world().resource::<Foes>();
    assert!(foes.0.iter().any(|f| f.kind == Some(kind)), "竹刺进了敌方弹幕池");
    // 站着别动，等竹刺扎过来
    teleport(&mut sim, p);
    let mut hurt = false;
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 0.0;
    for _ in 0..(6 * 60) {
        sim.step(InputFrame::default(), &[]);
        hurt |= sim
            .take_events()
            .iter()
            .any(|e| matches!(e, SimEvent::PlayerHurt { by: HurtBy::Spike { kind: k }, .. } if *k == kind));
        if hurt {
            break;
        }
    }
    assert!(hurt, "竹刺打中主角，伤害来源是竹魅");
}

/// 预警即将完成时受到控制或位移，这一刺作废；解除后必须重新预警。
#[test]
fn control_or_displacement_cancels_a_bamboo_wraiths_pending_spike() {
    for state in ["frozen", "stun", "root", "confuse", "knockback", "displaced"] {
        let mut sim = quiet(24, true);
        let p = player_pos(&mut sim);
        let i = sim.spawn("bamboo_wraith", p + Vec2::new(290.0, 0.0)).unwrap();
        {
            let mut en = sim.world_mut().resource_mut::<Enemies>();
            en.grace[i] = 0.0;
            en.atk_t[i] = 0.0;
        }
        sim.step(InputFrame::default(), &[]);
        assert!(sim.enemies().aim_t[i] > 0.0);
        sim.take_events();
        {
            let mut en = sim.world_mut().resource_mut::<Enemies>();
            en.aim_t[i] = DT * 0.5;
            match state {
                "frozen" => en.frozen[i] = 0.1,
                "stun" => en.stun[i] = 0.1,
                "root" => en.root[i] = 0.1,
                "confuse" => en.confuse[i] = 0.1,
                "knockback" => en.kx[i] = 120.0,
                _ => en.x[i] += 60.0,
            }
        }
        sim.step(InputFrame::default(), &[]);
        assert_eq!(sim.enemies().aim_t[i], 0.0, "{state}");
        assert!(sim.world().resource::<Foes>().0.is_empty(), "{state} 打断将出手的一刺");
        assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::EnemyShot { .. })));
        let mut warned = false;
        let mut fired = false;
        for _ in 0..240 {
            sim.step(InputFrame::default(), &[]);
            for e in sim.take_events() {
                warned |= matches!(e, SimEvent::EnemyAim { .. });
                if matches!(e, SimEvent::EnemyShot { .. }) {
                    assert!(warned, "{state} 解除后先重新预警");
                    fired = true;
                }
            }
            if fired {
                break;
            }
        }
        assert!(fired, "{state} 解除后可恢复出手");
    }
}

#[test]
fn bamboo_wraith_waits_for_spawn_grace_then_a_full_warning() {
    let mut sim = quiet(27, false);
    let p = player_pos(&mut sim);
    let i = sim.spawn("bamboo_wraith", p + Vec2::new(290.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 0.0;
    let mut elapsed = 0.0;
    while sim.enemies().grace[i] > 0.0 {
        sim.step(InputFrame::default(), &[]);
        elapsed += DT;
        assert_eq!(sim.enemies().aim_t[i], 0.0, "出生保护期间不开始蓄力");
        assert!(sim.world().resource::<Foes>().0.is_empty());
    }
    assert!(elapsed >= SPAWN_GRACE);
    sim.step(InputFrame::default(), &[]);
    let warn = sim.enemies().aim_t[i];
    assert!(warn > 0.0);
    let mut elapsed = 0.0;
    loop {
        sim.step(InputFrame::default(), &[]);
        elapsed += DT;
        if sim.take_events().iter().any(|e| matches!(e, SimEvent::EnemyShot { .. })) {
            assert!(elapsed >= warn - 1e-5 && elapsed < warn + DT + 1e-5);
            break;
        }
        assert!(elapsed < warn + DT);
    }
}

#[test]
fn a_winding_up_bamboo_wraith_keeps_external_displacement() {
    let mut sim = quiet(30, true);
    let p = player_pos(&mut sim);
    let i = sim.spawn("bamboo_wraith", p + Vec2::new(290.0, 0.0)).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.grace[i] = 0.0;
        en.atk_t[i] = 0.0;
    }
    sim.step(InputFrame::default(), &[]);
    let origin = at(sim.enemies(), i);
    {
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.x[i] += 3.0;
        en.kx[i] = 0.5;
    }
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    assert!(en.aim_t[i] > 0.0, "身子以内的微小位移不取消预警");
    assert!(en.x[i] > origin.x + 3.0, "互推和轻微击退不能被拉回蓄力原点");
    assert_eq!(Vec2::new(en.aim_x[i], en.aim_y[i]), origin, "弹道仍以原预警为准");
}

#[test]
fn taofeng_fox_cannot_hurt_during_its_reveal_animation() {
    let mut sim = quiet(28, false);
    let p = player_pos(&mut sim);
    let i = sim.spawn("taofeng_fox", p + Vec2::new(4.0, 0.0)).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.grace[i] = 0.0;
        en.root[i] = 100.0;
    }
    let hp = sim.player_hp();
    sim.step(InputFrame::default(), &[]);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Unmasked { .. })));
    assert_eq!(sim.player_hp(), hp, "现形同一步不接触伤人");
    assert_eq!(sim.enemies().grace[i], UNMASK_GRACE);
    while sim.enemies().grace[i] > 0.0 {
        sim.step(InputFrame::default(), &[]);
        assert_eq!(sim.player_hp(), hp, "现形动画期间不接触伤人");
    }
    sim.step(InputFrame::default(), &[]);
    assert!(sim.player_hp() < hp, "现形完成恢复接触伤害");
}

/// 讨封狐在照见圈外锁定不到；进了照见圈现形，速度换成现形的速度，之后一直现形。
#[test]
fn taofeng_fox_is_disguised_until_it_enters_the_reveal_circle() {
    let c = content();
    let def = &c.enemies[c.enemy_index("taofeng_fox").unwrap()];
    let ratio = def.disguise.as_ref().unwrap().speed / def.speed;
    let mut sim = quiet(25, true);
    let p = player_pos(&mut sim);
    let i = sim.spawn("taofeng_fox", p + Vec2::new(420.0, 0.0)).unwrap();
    let base = sim.enemies().speed[i];
    sim.step(InputFrame::default(), &[]);
    assert!(sim.enemies().cloaked[i], "照见圈外锁定不到");
    assert_eq!(sim.enemies().tags[i] & TAG_REVEALED, 0);
    let mut unmasked = false;
    for _ in 0..(12 * 60) {
        sim.step(InputFrame::default(), &[]);
        unmasked |= sim.take_events().iter().any(|e| matches!(e, SimEvent::Unmasked { .. }));
        if sim.enemies().tags[i] & TAG_REVEALED != 0 {
            break;
        }
    }
    assert!(unmasked, "走进照见圈就现形");
    let en = sim.enemies();
    assert!(!en.cloaked[i]);
    assert!((en.speed[i] - base * ratio).abs() < 1e-3, "现形后 {} ≈ {} × {ratio}", en.speed[i], base);
    // 再走出照见圈也不会变回去
    teleport(&mut sim, p + Vec2::new(-900.0, 0.0));
    sim.step(InputFrame::default(), &[]);
    assert!(!sim.enemies().cloaked[i] && sim.enemies().tags[i] & TAG_REVEALED != 0);
}

/// 伏击：到点了从离主角 260–400 的一丛竹子里钻出一只竹魅；场上满了就不出。
#[test]
fn bamboo_wraiths_ambush_from_a_nearby_clump_up_to_the_cap() {
    let c = content();
    let a = c.run.spawn.ambush[0].clone();
    let kind = c.enemy_index(&a.enemy).unwrap() as u16;
    let mut sim = quiet(26, true);
    sim.step(InputFrame::default(), &[]);
    // 找一丛立着的竹子，把主角挪到离它 330 的地方
    let clump = sim.world().resource::<Bamboo>().clumps.iter().find(|c| c.standing()).map(|c| c.pos).unwrap();
    teleport(&mut sim, clump + Vec2::new(330.0, 0.0));
    sim.step(InputFrame::default(), &[]);
    sim.world_mut().resource_mut::<Director>().ambush_t = vec![0.0];
    sim.step(InputFrame::default(), &[]);
    let p = player_pos(&mut sim);
    let en = sim.enemies();
    let wraiths: Vec<usize> = en.iter_alive().filter(|&i| en.kind[i] == kind).collect();
    assert_eq!(wraiths.len(), 1, "钻出一只");
    let d = (at(en, wraiths[0]) - p).length();
    assert!(d >= a.dist.0 - 5.0 && d <= a.dist.1 + 5.0, "从 {:?} 以内的竹丛钻出：{d}", a.dist);
    let next = sim.world().resource::<Director>().ambush_t[0];
    assert!((next - (sim.tick() as f32 / 60.0 + a.every)).abs() < 0.1, "下一次在 every 秒后");
    // 场上已经有 max 只：到点也不出
    for k in 1..a.max {
        sim.spawn(&a.enemy, p + Vec2::new(0.0, 300.0 + k as f32)).unwrap();
    }
    sim.world_mut().resource_mut::<Director>().ambush_t = vec![0.0];
    sim.step(InputFrame::default(), &[]);
    let en = sim.enemies();
    assert_eq!(en.iter_alive().filter(|&i| en.kind[i] == kind).count(), a.max as usize);
}

/// 三只都进了常规刷怪或伏击：狐火 1:30、讨封狐 4:00 起混进配比，竹魅 3:00 起伏击。
#[test]
fn new_enemies_are_wired_into_the_qingqiu_spawns() {
    let c = content();
    let mix = |id: &str| c.run.spawn.mix.iter().find(|m| m.enemy == id).cloned();
    assert_eq!(mix("fox_wisp").unwrap().from_minute, 1.5);
    assert_eq!(mix("taofeng_fox").unwrap().from_minute, 4.0);
    let a = &c.run.spawn.ambush[0];
    assert_eq!((a.enemy.as_str(), a.from, a.max), ("bamboo_wraith", 180.0, 4));
}

/// 把出场时间前移，实际录制三妖的移动、预警、出手和现形，再用同一内容重放。
#[test]
fn qingqiu_enemy_actions_roundtrip_through_replay() {
    let mut c = content();
    for mix in &mut c.run.spawn.mix {
        mix.from_minute = 0.0;
        mix.share =
            if matches!(mix.enemy.as_str(), "fox_wisp" | "taofeng_fox") { (0.5, 0.5) } else { (0.0, 0.0) };
    }
    c.run.spawn.ambush[0].from = 1.0;
    c.run.spawn.ambush[0].every = 3.0;
    c.run.spawn.ambush[0].dist = (260.0, 500.0);
    for def in &mut c.enemies {
        if matches!(def.id.as_str(), "fox_wisp" | "bamboo_wraith" | "taofeng_fox") {
            def.hp = 10000.0;
        }
    }
    let mut setup = RunSetup::new(29, RunMode::Normal);
    setup.god = true;
    let mut sim = SimHarness::with_setup(c.clone(), setup);
    sim.record("qingqiu-test");
    let mut actions = [false; 3];
    let mut pounced = false;
    for _ in 0..35 * 60 {
        common::bot_step(&mut sim, InputFrame::default(), &[]);
        pounced |= sim.enemies().iter_alive().any(|i| sim.enemies().charge[i] == CHARGE_DASH);
        for event in sim.take_events() {
            match event {
                SimEvent::EnemyAim { .. } => actions[0] = true,
                SimEvent::EnemyShot { .. } => actions[1] = true,
                SimEvent::Unmasked { .. } => actions[2] = true,
                _ => {}
            }
        }
    }
    assert!(
        pounced && actions.iter().all(|&seen| seen),
        "实际发生扑击/预警/出手/现形：{pounced} {actions:?}"
    );
    let replay = Replay::parse(&sim.replay().unwrap().to_ron()).unwrap();
    let hashes = replay.hashes.clone();
    let mut playback = SimHarness::from_replay(c, replay);
    while !playback.playback().unwrap().finished && !playback.is_over() {
        playback.step(InputFrame::default(), &[]);
    }
    assert_eq!(playback.playback().unwrap().verification_result(playback.tick()), Ok(hashes.len()));
    assert_eq!(playback.hashes().iter().map(|h| (h.tick, h.hash)).collect::<Vec<_>>(), hashes);
}
