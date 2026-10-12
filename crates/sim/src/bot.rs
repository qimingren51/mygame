//! 自动选卡机器人（移植自网页版 tests/sim/bot.ts）：整局测试和平衡工具用它替玩家做选择、走位。
//!
//! 选卡策略：进化 > 已有法器升级 > 新法器（最多 4 件）> 对应进化的心法 > 心法升级 > 其他。
//! 走位：绕大圈，偶尔变向；每 2 秒闪避一次；燃灯充满就放。

use bevy_math::{Vec2, ops};

use crate::{GameContent, InputFrame, Offer, SimCommand, SimHarness, SimPhase};

fn score(sim: &SimHarness, offer: Offer) -> i32 {
    let c = &sim.world().resource::<GameContent>().0;
    match offer {
        Offer::Evolve(_) => 1000,
        Offer::WeaponUp(_) => 100,
        Offer::NewWeapon(_) => {
            if sim.arsenal().0.len() < 4 {
                90
            } else {
                10
            }
        }
        Offer::NewPassive(d) => {
            let id = &c.passives[d].id;
            let wanted = sim
                .arsenal()
                .0
                .iter()
                .any(|w| c.weapons[w.def].evolution.as_ref().is_some_and(|e| &e.passive == id));
            if wanted { 80 } else { 30 }
        }
        Offer::PassiveUp(_) => 40,
        Offer::Heal | Offer::Oil => 1,
    }
}

/// 选择阶段替玩家下命令；Play 阶段什么也不做。
pub fn respond(sim: &SimHarness) -> Vec<SimCommand> {
    match sim.phase() {
        SimPhase::LevelUp => {
            let Some(choice) = &sim.flow().choice else { return Vec::new() };
            let best = choice
                .offers
                .iter()
                .enumerate()
                .max_by_key(|&(i, &o)| (score(sim, o), -(i as i32)))
                .map_or(0, |(i, _)| i);
            vec![SimCommand::Choose(best as u8)]
        }
        SimPhase::Chest | SimPhase::Evolve => vec![SimCommand::Ack],
        // 点灯奖励：血少回血，否则要一次升级
        SimPhase::Lantern => {
            let Some(rewards) = &sim.flow().lamp else { return Vec::new() };
            let low = sim
                .world()
                .iter_entities()
                .find_map(|e| e.get::<crate::Health>().map(|h| h.hp < h.max * 0.5))
                .unwrap_or(false);
            let want = if low { crate::flow::LampReward::Heal } else { crate::flow::LampReward::Level };
            let i = rewards.iter().position(|&r| r == want).unwrap_or(0);
            vec![SimCommand::Choose(i as u8)]
        }
        // 灯坠：有空格就拿第一个，满了不换
        SimPhase::Charm => {
            let free = sim.build().charms.len() < crate::charms::charm_slots(sim.stats());
            let picking = sim.flow().charm.as_ref().is_some_and(|c| c.picked.is_none());
            vec![if free && picking { SimCommand::Choose(0) } else { SimCommand::Skip }]
        }
        // 货郎：钱够就买宝箱，否则走开
        SimPhase::Shop => {
            let afford = sim.flow().shop.is_some_and(|s| sim.progress().gold >= s.chest_cost as f32);
            vec![if afford { SimCommand::Choose(0) } else { SimCommand::Skip }]
        }
        _ => Vec::new(),
    }
}

/// 走位：绕大圈，偶尔变向；每 2 秒闪避一次。
pub fn input(tick: u64) -> (InputFrame, Vec<SimCommand>) {
    let a = tick as f32 * 0.01;
    let dir = Vec2::new(ops::cos(a), ops::sin(a * 0.7));
    let cmds = if tick.is_multiple_of(120) { vec![SimCommand::Dash] } else { vec![] };
    (InputFrame::quantize(dir), cmds)
}

/// 机器人走一步：选择阶段做选择，Play 阶段按 input 走（燃灯充满就放）。
pub fn step(sim: &mut SimHarness, input: InputFrame, cmds: &[SimCommand]) {
    let mut all = respond(sim);
    if sim.phase() == SimPhase::Play {
        all.extend_from_slice(cmds);
        if sim.progress().ult >= 1.0 {
            all.push(SimCommand::Ult);
        }
    }
    sim.step(input, &all);
}
