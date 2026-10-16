//! 攻击判定（docs/PLAYTEST.md 第 1 项）：接触按画出来的身体算，冲锋按碰撞半径；冻住、击晕、刚刷出的
//! 不伤人；血祭坛要按交互键。
mod common;

use bevy_math::Vec2;
use lantern_sim::encounters::{Encounter, Encounters};
use lantern_sim::enemies::{CHARGE_DASH, SPAWN_GRACE};
use lantern_sim::{Enemies, InputFrame, SimCommand, SimEvent, SimHarness};

const HZ: f32 = 60.0;

fn arena() -> SimHarness {
    let mut sim = SimHarness::new(common::content(), 5);
    sim.quiet();
    sim.set_build(&[], &[]);
    sim
}

/// 摆一只过了刷出保护、钉在原地的妖物（定身照样还手）。
fn pinned(sim: &mut SimHarness, id: &str, at: Vec2) -> usize {
    let i = sim.spawn(id, at).unwrap();
    let mut en = sim.world_mut().resource_mut::<Enemies>();
    en.grace[i] = 0.0;
    en.root[i] = 100.0;
    i
}

/// 走 steps 步，主角掉没掉血。
fn hurt_within(sim: &mut SimHarness, steps: usize) -> bool {
    let hp = sim.player_hp();
    for _ in 0..steps {
        sim.step(InputFrame::default(), &[]);
    }
    sim.player_hp() < hp
}

#[test]
fn contact_uses_the_drawn_body_not_the_collision_radius() {
    let c = common::content();
    let pr = c.player.radius;
    let lord = &c.enemies[c.enemy_index("stonelord").unwrap()];
    let (body, collide) = (lord.contact_radius.unwrap(), lord.radius);
    assert!(body < collide);
    // 碰撞半径够得着、画出来的身体够不着：不掉血
    let mut sim = arena();
    pinned(&mut sim, "stonelord", Vec2::new(body + pr + 2.0, 0.0));
    assert!(!hurt_within(&mut sim, 30), "石将画出来的身子碰不到");
    // 身体贴上来才掉血
    let mut sim = arena();
    pinned(&mut sim, "stonelord", Vec2::new(body + pr - 2.0, 0.0));
    assert!(hurt_within(&mut sim, 5));
    // 没写 contact_radius 的照旧按 radius
    let shade = &c.enemies[c.enemy_index("shade").unwrap()];
    assert_eq!(shade.contact_ratio(), 1.0);
    let mut sim = arena();
    pinned(&mut sim, "shade", Vec2::new(shade.radius + pr - 1.0, 0.0));
    assert!(hurt_within(&mut sim, 5));
}

#[test]
fn a_dash_reaches_with_the_whole_collision_radius_at_its_real_speed() {
    let c = common::content();
    let pr = c.player.radius;
    let fox = &c.enemies[c.enemy_index("fox").unwrap()];
    let ch = fox.charge.as_ref().unwrap();
    let gap = fox.contact_radius.unwrap() + pr + 1.0;
    assert!(gap < fox.radius + pr);
    // 走着碰不到
    let mut sim = arena();
    pinned(&mut sim, "fox", Vec2::new(gap, 0.0));
    assert!(!hurt_within(&mut sim, 10));
    // 同样的距离扑过来就够得着（往侧面扑，第一步还在原处判定）
    let mut sim = arena();
    let i = sim.spawn("fox", Vec2::new(gap, 0.0)).unwrap();
    {
        let mut en = sim.world_mut().resource_mut::<Enemies>();
        en.grace[i] = 0.0;
        en.charge[i] = CHARGE_DASH;
        en.charge_t[i] = ch.duration;
        en.charge_dx[i] = 0.0;
        en.charge_dy[i] = 1.0;
    }
    assert!(hurt_within(&mut sim, 1));
    // 预警线按这一次的实际冲锋速度画
    assert!((sim.enemies().charge_speed[i] - ch.speed).abs() < 1e-3);
}

#[test]
fn frozen_and_stunned_enemies_do_not_hurt_but_rooted_ones_still_do() {
    for (state, hurts) in [("frozen", false), ("stun", false), ("root", true)] {
        let mut sim = arena();
        let i = sim.spawn("shade", Vec2::new(4.0, 0.0)).unwrap();
        {
            let mut en = sim.world_mut().resource_mut::<Enemies>();
            en.grace[i] = 0.0;
            match state {
                "frozen" => en.frozen[i] = 100.0,
                "stun" => en.stun[i] = 100.0,
                _ => en.root[i] = 100.0,
            }
        }
        assert_eq!(hurt_within(&mut sim, 30), hurts, "{state}");
    }
}

#[test]
fn freshly_spawned_enemies_cannot_hurt_until_their_grace_ends() {
    let mut sim = arena();
    // 刷在主角身上（九尾、召唤词缀会这样）
    let i = sim.spawn("shade", Vec2::new(2.0, 0.0)).unwrap();
    sim.world_mut().resource_mut::<Enemies>().root[i] = 100.0;
    assert_eq!(sim.enemies().grace[i], SPAWN_GRACE);
    let safe = (SPAWN_GRACE * HZ) as usize - 2;
    assert!(!hurt_within(&mut sim, safe), "保护时间里不伤人");
    assert!(hurt_within(&mut sim, 10), "保护时间过了照常");
}

#[test]
fn the_blood_altar_needs_the_interact_key() {
    let c = common::content();
    let kind = c.events.kinds.iter().position(|e| e.id == "altar").unwrap();
    let mut sim = arena();
    sim.world_mut().resource_mut::<Encounters>().list.push(Encounter {
        kind,
        pos: Vec2::ZERO,
        t: 0.0,
        enemy: None,
    });
    let hp = sim.player_hp();
    for _ in 0..30 {
        sim.step(InputFrame::default(), &[]);
    }
    assert_eq!(sim.player_hp(), hp, "路过碰到不献血");
    assert!(!sim.take_events().iter().any(|e| matches!(e, SimEvent::Sacrifice { .. })));
    assert!(sim.world().resource::<Encounters>().altar_near(&c, Vec2::ZERO));
    sim.step(InputFrame::default(), &[SimCommand::Interact]);
    assert!(sim.player_hp() < hp);
    assert!(sim.take_events().iter().any(|e| matches!(e, SimEvent::Sacrifice { .. })));
    assert!(!sim.world().resource::<Encounters>().interact, "按键这一步就用掉");
}
