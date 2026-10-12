//! 测试共用：内容数据、自动选卡机器人（移植自网页版 tests/sim/bot.ts）。

#![allow(dead_code)]

use std::path::Path;

use bevy_math::{Vec2, ops};
use lantern_content::Content;
use lantern_sim::{InputFrame, Offer, SimCommand, SimHarness, SimPhase};

pub fn content() -> Content {
    Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).expect("内容数据")
}

/// 选卡策略：进化 > 已有法器升级 > 新法器（最多 4 件）> 对应进化的心法 > 心法升级 > 其他。
fn score(sim: &SimHarness, offer: Offer) -> i32 {
    let c = content_of(sim);
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

fn content_of(sim: &SimHarness) -> &Content {
    &sim.world().resource::<lantern_sim::GameContent>().0
}

/// 选择阶段替玩家下命令；Play 阶段什么也不做。
pub fn respond(sim: &SimHarness) -> Vec<SimCommand> {
    match sim.phase() {
        SimPhase::LevelUp => {
            let offers = &sim.flow().choice.as_ref().expect("升级阶段有选项").offers;
            let mut best = 0;
            let mut best_score = i32::MIN;
            for (i, &o) in offers.iter().enumerate() {
                let s = score(sim, o);
                if s > best_score {
                    best_score = s;
                    best = i;
                }
            }
            vec![SimCommand::Choose(best as u8)]
        }
        SimPhase::Chest | SimPhase::Evolve => vec![SimCommand::Ack],
        _ => Vec::new(),
    }
}

/// 走位：绕大圈，偶尔变向；每 2 秒闪避一次。
pub fn bot_input(tick: u64) -> (InputFrame, Vec<SimCommand>) {
    let a = tick as f32 * 0.01;
    let dir = Vec2::new(ops::cos(a), ops::sin(a * 0.7));
    let cmds = if tick.is_multiple_of(120) { vec![SimCommand::Dash] } else { vec![] };
    (InputFrame::quantize(dir), cmds)
}

/// 机器人走一步：选择阶段做选择，Play 阶段按 input 走。
pub fn bot_step(sim: &mut SimHarness, input: InputFrame, cmds: &[SimCommand]) {
    let mut all = respond(sim);
    if sim.phase() == SimPhase::Play {
        all.extend_from_slice(cmds);
    }
    sim.step(input, &all);
}
