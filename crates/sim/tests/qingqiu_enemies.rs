//! 青丘的三只新妖物（docs/BALANCE.md 第 12.1 节）：狐火绕圈扑击、竹魅守距射竹刺、讨封狐伪装现形，
//! 以及竹魅从竹丛里钻出来的伏击。

mod common;

use bevy_math::{Vec2, ops};
use lantern_sim::bamboo::Bamboo;
use lantern_sim::boss::Foes;
use lantern_sim::enemies::{CHARGE_DASH, CHARGE_WINDUP, Enemies, TAG_REVEALED};
use lantern_sim::run::Director;
use lantern_sim::{HurtBy, InputFrame, Player, Pos, PrevPos, RunMode, RunSetup, SimEvent, SimHarness};

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
    let steps = (sh.warn * 60.0).round() as usize;
    let mut fired = false;
    for _ in 0..steps + 1 {
        sim.step(InputFrame::quantize(Vec2::Y), &[]);
        if sim.enemies().aim_t[i] > 0.0 {
            assert_eq!((sim.enemies().aim_dx[i], sim.enemies().aim_dy[i]), locked, "预警时方向不跟着主角");
        }
        fired |= sim.take_events().iter().any(|e| matches!(e, SimEvent::EnemyShot { .. }));
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

/// 预警时被冻住，这一刺作废。
#[test]
fn freezing_a_bamboo_wraith_cancels_its_spike() {
    let mut sim = quiet(24, true);
    let p = player_pos(&mut sim);
    let i = sim.spawn("bamboo_wraith", p + Vec2::new(290.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<Enemies>().atk_t[i] = 0.0;
    sim.step(InputFrame::default(), &[]);
    assert!(sim.enemies().aim_t[i] > 0.0);
    sim.world_mut().resource_mut::<Enemies>().frozen[i] = 2.0;
    for _ in 0..60 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.enemies().aim_t[i], 0.0);
    assert!(sim.world().resource::<Foes>().0.iter().all(|f| f.kind.is_none()), "没有射出竹刺");
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
