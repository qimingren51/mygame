//! 玩法模拟。
//!
//! 只依赖 `bevy_app`、`bevy_ecs`、`bevy_math`、`bevy_state`，链接不到渲染、窗口和音频。
//! 模拟在 `FixedUpdate` 里按 [`SimSet`] 的固定顺序运行，规则见 docs/DESIGN.md 第 6、7 节。

use std::sync::Arc;

use bevy_app::prelude::*;
use bevy_ecs::prelude::*;
use bevy_state::prelude::*;

pub mod components;
pub mod flow;
pub mod harness;
pub mod io;
mod player;
mod tick;

pub use components::*;
pub use flow::{AppState, RunState};
pub use harness::SimHarness;
pub use io::{InputFrame, SimCommand, SimCommands, SimEvent, SimOutbox};
pub use tick::{HashCheckpoint, HashLog, SimRng, Tick};

/// 全部内容数据（只读，整局共享）。
#[derive(Resource, Clone)]
pub struct GameContent(pub Arc<lantern_content::Content>);

/// 下一局的设置，在进入 [`AppState::Run`] 之前写好。
#[derive(Resource, Clone, Debug)]
pub struct RunSetup {
    pub seed: u64,
}

/// 每一步的执行顺序。往同一个队列写数据的系统必须在同一个 Set 里显式串行。
#[derive(SystemSet, Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum SimSet {
    /// 保存上一步位置、读取输入和命令
    Input,
    Player,
    Director,
    Ai,
    Move,
    Spatial,
    Weapons,
    Projectiles,
    Collide,
    Damage,
    Status,
    Death,
    Pickup,
    Progress,
    Cleanup,
    /// 步数加一，按间隔记录状态哈希
    Hash,
}

pub struct SimPlugin;

impl Plugin for SimPlugin {
    fn build(&self, app: &mut App) {
        app.init_state::<AppState>()
            .add_sub_state::<RunState>()
            .init_resource::<InputFrame>()
            .init_resource::<SimCommands>()
            .init_resource::<SimOutbox>()
            .configure_sets(
                FixedUpdate,
                (
                    SimSet::Input,
                    SimSet::Player,
                    SimSet::Director,
                    SimSet::Ai,
                    SimSet::Move,
                    SimSet::Spatial,
                    SimSet::Weapons,
                    SimSet::Projectiles,
                    SimSet::Collide,
                    SimSet::Damage,
                    SimSet::Status,
                    SimSet::Death,
                    SimSet::Pickup,
                    SimSet::Progress,
                    SimSet::Cleanup,
                    SimSet::Hash,
                )
                    .chain()
                    .run_if(in_state(RunState::Playing)),
            )
            .add_systems(OnEnter(AppState::Run), tick::start_run)
            .add_systems(OnExit(AppState::Run), tick::end_run)
            .add_systems(
                FixedUpdate,
                (
                    (tick::save_prev_pos, player::apply_commands).chain().in_set(SimSet::Input),
                    player::move_player.in_set(SimSet::Player),
                    (tick::advance_tick, tick::record_hash).chain().in_set(SimSet::Hash),
                ),
            )
            // 画面、音频、界面在 Update 里消费完事件后，这里统一清空。
            .add_systems(Last, io::clear_outbox);
    }
}
