//! 测试共用：内容数据、自动选卡机器人（在 lantern_sim::bot 里）。

#![allow(dead_code)]

use std::path::Path;

use lantern_content::Content;
use lantern_sim::{InputFrame, SimCommand, SimHarness};

pub fn content() -> Content {
    Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).expect("内容数据")
}

#[allow(unused_imports)]
pub use lantern_sim::bot::{input as bot_input, respond};

/// 机器人走一步（不放燃灯，和黄金文件录制时一致）。
pub fn bot_step(sim: &mut SimHarness, input: InputFrame, cmds: &[SimCommand]) {
    let mut all = respond(sim);
    if sim.phase() == lantern_sim::SimPhase::Play {
        all.extend_from_slice(cmds);
    }
    sim.step(input, &all);
}
