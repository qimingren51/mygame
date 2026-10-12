//! 回放（docs/DESIGN.md 第 7 节）：录制每一步的输入和命令，重放时逐秒核对状态哈希。
//!
//! - 录制在模拟内部完成（[`SimSet::Input`] 的最前面），录到的就是模拟实际看到的输入。
//! - 文件是 RON：文件头（格式版本、游戏版本、内容哈希、开局设置），输入按游程编码，
//!   命令带步序号，每秒（游戏时间）一个状态哈希。
//! - 按“步”录制：升级选择等阶段游戏时间不走，但每一步都录一个输入，命令记在它生效的那一步。
//! - 重放时 [`ReplayPlayback`] 在同一位置把输入和命令喂给模拟，平台层的输入被忽略。
//!
//! [`SimSet::Input`]: crate::SimSet::Input

use bevy_ecs::prelude::*;
use serde::{Deserialize, Serialize};

use crate::{HashLog, InputFrame, RunSetup, SimCommand, SimCommands, Tick};

/// 回放文件格式的版本。改动格式时加一，并在 [`Replay::parse`] 里处理旧版本。
/// 第 2 版：按步录制，文件头带完整的开局设置（夜签、心灯）。第 1 版（M1）不再支持。
pub const REPLAY_FORMAT: u32 = 2;

/// 一段相同输入的连续步数。
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InputRun {
    pub steps: u32,
    pub mx: i8,
    pub my: i8,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Replay {
    pub format: u32,
    pub game_version: String,
    pub content_hash: u64,
    pub setup: RunSetup,
    /// 总步数（含升级选择等时间不走的步）
    pub steps: u64,
    /// 游戏时间走过的步数
    pub ticks: u64,
    pub inputs: Vec<InputRun>,
    /// (步序号, 命令)，按步序号排列
    pub commands: Vec<(u64, SimCommand)>,
    /// (游戏时间步数, 状态哈希)，每秒一个
    pub hashes: Vec<(u64, u64)>,
}

impl Replay {
    pub fn new(game_version: &str, content_hash: u64, setup: RunSetup) -> Self {
        Replay {
            format: REPLAY_FORMAT,
            game_version: game_version.to_string(),
            content_hash,
            setup,
            steps: 0,
            ticks: 0,
            inputs: Vec::new(),
            commands: Vec::new(),
            hashes: Vec::new(),
        }
    }

    fn push_input(&mut self, input: InputFrame) {
        match self.inputs.last_mut() {
            Some(run) if run.mx == input.mx && run.my == input.my && run.steps < u32::MAX => run.steps += 1,
            _ => self.inputs.push(InputRun { steps: 1, mx: input.mx, my: input.my }),
        }
        self.steps += 1;
    }

    pub fn to_ron(&self) -> String {
        ron::ser::to_string_pretty(self, ron::ser::PrettyConfig::default().depth_limit(1))
            .expect("回放序列化不会失败")
    }

    pub fn parse(text: &str) -> Result<Replay, String> {
        #[derive(Deserialize)]
        struct Head {
            format: u32,
        }
        // 先只读格式版本（其余字段忽略），旧版本给出明确的提示
        let head: Head = ron::from_str(text).map_err(|e| format!("回放文件格式错误：{e}"))?;
        if head.format != REPLAY_FORMAT {
            return Err(format!(
                "回放格式版本 {}，本程序只支持 {REPLAY_FORMAT}（旧版本录的回放无法重放）",
                head.format
            ));
        }
        ron::from_str(text).map_err(|e| format!("回放文件格式错误：{e}"))
    }
}

/// 按步取回放里输入和命令的位置（不借用回放本身，调用时传入）。
#[derive(Clone, Debug, Default)]
pub struct ReplayCursor {
    run: usize,
    used: u32,
    cmd: usize,
    step: u64,
}

impl ReplayCursor {
    /// 下一步的输入，这一步的命令追加到 commands；回放结束时返回 `None`。
    pub fn next_step(&mut self, replay: &Replay, commands: &mut Vec<SimCommand>) -> Option<InputFrame> {
        let run = replay.inputs.get(self.run)?;
        let input = InputFrame { mx: run.mx, my: run.my };
        while let Some(&(t, c)) = replay.commands.get(self.cmd) {
            if t != self.step {
                break;
            }
            commands.push(c);
            self.cmd += 1;
        }
        self.used += 1;
        if self.used >= run.steps {
            self.run += 1;
            self.used = 0;
        }
        self.step += 1;
        Some(input)
    }
}

/// 本局正在录制的回放。开局时由 game 插入（带上游戏版本和内容哈希）。
#[derive(Resource, Debug)]
pub struct ReplayLog(pub Replay);

/// 正在重放：存在这个资源时，模拟的输入和命令来自回放，平台层的输入被忽略。
#[derive(Resource)]
pub struct ReplayPlayback {
    pub replay: Replay,
    cursor: ReplayCursor,
    /// 第一次与录制时状态哈希不一致的步数
    pub diverged_at: Option<u64>,
    pub finished: bool,
}

impl ReplayPlayback {
    pub fn new(replay: Replay) -> Self {
        ReplayPlayback { replay, cursor: ReplayCursor::default(), diverged_at: None, finished: false }
    }

    /// 回放对应的开局设置。
    pub fn setup(&self) -> RunSetup {
        self.replay.setup.clone()
    }
}

/// 重放：把这一步的输入和命令喂给模拟。
pub(crate) fn feed_playback(
    playback: Option<ResMut<ReplayPlayback>>,
    mut input: ResMut<InputFrame>,
    mut commands: ResMut<SimCommands>,
) {
    let Some(mut p) = playback else { return };
    let p = &mut *p;
    commands.0.clear();
    match p.cursor.next_step(&p.replay, &mut commands.0) {
        Some(frame) => *input = frame,
        None => {
            p.finished = true;
            *input = InputFrame::default();
        }
    }
}

/// 录制：记下模拟这一步实际看到的输入和命令。
pub(crate) fn record(log: Option<ResMut<ReplayLog>>, input: Res<InputFrame>, commands: Res<SimCommands>) {
    let Some(mut log) = log else { return };
    let step = log.0.steps;
    for &c in &commands.0 {
        log.0.commands.push((step, c));
    }
    log.0.push_input(*input);
}

/// 把新记录的状态哈希抄进回放；重放时和录制的哈希对照。
pub(crate) fn sync_hashes(
    tick: Res<Tick>,
    hashes: Res<HashLog>,
    log: Option<ResMut<ReplayLog>>,
    playback: Option<ResMut<ReplayPlayback>>,
) {
    let mut log = log;
    if let Some(log) = &mut log {
        log.0.ticks = tick.0;
    }
    let Some(last) = hashes.0.last() else { return };
    if let Some(mut log) = log
        && log.0.hashes.last().is_none_or(|&(t, _)| t < last.tick)
    {
        log.0.hashes.push((last.tick, last.hash));
    }
    if let Some(mut p) = playback
        && p.diverged_at.is_none()
        && let Some(&(_, want)) = p.replay.hashes.iter().find(|&&(t, _)| t == last.tick)
        && want != last.hash
    {
        p.diverged_at = Some(last.tick);
    }
}
