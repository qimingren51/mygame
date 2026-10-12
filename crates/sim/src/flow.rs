//! 游戏流程的状态机（docs/DESIGN.md 第 5 节）。

use bevy_state::prelude::*;

#[derive(States, Default, Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum AppState {
    /// 加载内容和资源
    #[default]
    Boot,
    Title,
    Run,
    Results,
}

/// 一局之内的状态。模拟只在 `Playing` 下运行。
#[derive(SubStates, Default, Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[source(AppState = AppState::Run)]
pub enum RunState {
    #[default]
    Playing,
    Paused,
}
