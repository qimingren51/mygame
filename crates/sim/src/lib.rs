//! 玩法模拟。
//!
//! 只依赖 `bevy_app`、`bevy_ecs`、`bevy_math`、`bevy_state`，链接不到渲染、窗口和音频。
//! 模拟在 `FixedUpdate` 里按 [`SimSet`] 的固定顺序运行，规则见 docs/DESIGN.md 第 6、7 节。

use std::collections::BTreeMap;
use std::sync::Arc;

use bevy_app::prelude::*;
use bevy_ecs::prelude::*;
use bevy_state::prelude::*;
use serde::{Deserialize, Serialize};

use lantern_content::Element;

pub mod boss;
pub mod bot;
pub mod build;
pub mod charms;
pub mod combat;
pub mod components;
mod crowd;
pub mod encounters;
pub mod enemies;
pub mod flow;
pub mod gems;
pub mod gold;
pub mod harness;
pub mod io;
pub mod lanterns;
mod movement;
pub mod omens;
pub mod pickups;
pub mod player;
pub mod reactions;
pub mod replay;
pub mod reveal;
pub mod run;
pub mod spatial;
pub mod spawn;
pub mod stats;
mod tick;
pub mod weapons;

pub use build::{Build, Offer};
pub use components::*;
pub use enemies::Enemies;
pub use flow::{AppState, Flow, RunResult, RunState, SimPhase};
pub use gems::Gems;
pub use harness::SimHarness;
pub use io::{HitKind, InputFrame, SimCommand, SimCommands, SimEvent, SimOutbox};
pub use replay::{Replay, ReplayLog, ReplayPlayback};
pub use run::{Director, Progress, RunMode, SimView};
pub use stats::{Effects, Stats};
pub use tick::{HashCheckpoint, HashLog, SimRng, Tick};
pub use weapons::Arsenal;

/// 全部内容数据（只读，整局共享）。
#[derive(Resource, Clone)]
pub struct GameContent(pub Arc<lantern_content::Content>);

/// 开局抽到并选定的夜签。
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OmenPick {
    /// `omens.ron` 里的 ID
    pub id: String,
    /// pick_element 的夜签选定的五行
    #[serde(default)]
    pub element: Option<Element>,
}

/// 下一局的设置，在进入 [`AppState::Run`] 之前写好。回放文件头里存的就是它。
#[derive(Resource, Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RunSetup {
    pub seed: u64,
    pub mode: RunMode,
    #[serde(default)]
    pub omen: Option<OmenPick>,
    /// 心灯各系的等级（按 `meta.ron` 的 ID）
    #[serde(default)]
    pub meta: BTreeMap<String, u32>,
    /// 主角无敌（测试、机器人用）
    #[serde(default)]
    pub god: bool,
    /// 难度：第几更（从 1 起，`difficulty.ron` 的下标 + 1）
    #[serde(default = "first_tier")]
    pub tier: u8,
    /// 灯（`lamps.ron` 的 ID）；不写时用第一盏初始灯
    #[serde(default)]
    pub lamp: Option<String>,
    /// 出发前挂上的灯坠
    #[serde(default)]
    pub charms: Vec<String>,
    /// 已经解锁、局内可能出现的灯坠
    #[serde(default)]
    pub charm_pool: Vec<String>,
    /// 生效的局外属性等级（按 `attributes.ron` 的 ID；关掉的不写）
    #[serde(default)]
    pub attributes: BTreeMap<String, u32>,
    /// 悟·五行：选中的那一系
    #[serde(default)]
    pub insight: Option<Element>,
}

fn first_tier() -> u8 {
    1
}

impl RunSetup {
    pub fn new(seed: u64, mode: RunMode) -> Self {
        RunSetup {
            seed,
            mode,
            omen: None,
            meta: BTreeMap::new(),
            god: false,
            tier: 1,
            lamp: None,
            charms: Vec::new(),
            charm_pool: Vec::new(),
            attributes: BTreeMap::new(),
            insight: None,
        }
    }

    /// 这一局用的灯（`lamps.ron` 下标）。
    pub fn lamp_index(&self, content: &lantern_content::Content) -> usize {
        self.lamp
            .as_deref()
            .and_then(|id| content.lamp_index(id))
            .or_else(|| content.lamps.iter().position(|l| l.initial))
            .unwrap_or(0)
    }
}

/// 每一步的执行顺序。往同一个队列写数据的系统必须在同一个 Set 里显式串行。
#[derive(SystemSet, Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum SimSet {
    /// 读取输入和命令（选择阶段也运行），保存上一步位置
    Input,
    /// 主角移动、回复、护盾、周期触发器
    Player,
    /// 刷怪、时间表、奇遇
    Director,
    /// 重建空间网格（本步之后的查询都用它）
    Spatial,
    /// 夜主出招
    Ai,
    /// 妖物移动、互推、接触伤害
    Move,
    /// 排队的动作、法器、石印与地裂，最后把范围打击变成命中
    Weapons,
    /// 飞剑、弹幕
    Projectiles,
    /// 回光、九转金丹的震退
    Collide,
    /// 结算命中
    Damage,
    /// 灼烧
    Status,
    /// 掉落、击杀触发器、击败夜主
    Death,
    /// 魂火、拾取物、奇遇的触碰
    Pickup,
    /// 升级、宝箱、结束
    Progress,
    Cleanup,
    /// 步数加一，按间隔记录状态哈希
    Hash,
}

pub struct SimPlugin;

impl Plugin for SimPlugin {
    fn build(&self, app: &mut App) {
        // 模拟的系统本来就按固定顺序串行，用单线程执行器省掉每个系统唤醒工作线程的开销
        // （实测约占 15%）。系统内部仍然可以用任务池并行。
        app.edit_schedule(FixedUpdate, |s| {
            s.set_executor(bevy_ecs::schedule::SingleThreadedExecutor::new());
        });
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
                    SimSet::Spatial,
                    SimSet::Ai,
                    SimSet::Move,
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
                    .run_if(in_state(RunState::Playing))
                    .run_if(flow::not_over),
            )
            // 选择阶段每步只跑 Input；其余各阶段只在本步开头处于 Play 时运行
            .configure_sets(
                FixedUpdate,
                (
                    SimSet::Player,
                    SimSet::Director,
                    SimSet::Spatial,
                    SimSet::Ai,
                    SimSet::Move,
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
                    .run_if(flow::playing),
            )
            .add_systems(OnEnter(AppState::Run), tick::start_run)
            .add_systems(OnExit(AppState::Run), tick::end_run)
            .add_systems(
                FixedUpdate,
                (
                    (
                        flow::begin_step,
                        replay::feed_playback,
                        replay::record,
                        flow::handle_commands,
                        tick::save_prev_pos.run_if(flow::playing),
                        stats::refresh_stats,
                    )
                        .chain()
                        .in_set(SimSet::Input),
                    (player::move_player, charms::lay_trail, player::upkeep, reveal::update_reveal)
                        .chain()
                        .in_set(SimSet::Player),
                    (spawn::update_spawns, encounters::spawn_encounters).chain().in_set(SimSet::Director),
                    movement::build_grid.in_set(SimSet::Spatial),
                    (boss::boss_attacks, boss::elite_summons).chain().in_set(SimSet::Ai),
                    (movement::update_enemies, crowd::separate).chain().in_set(SimSet::Move),
                    (
                        combat::run_actions,
                        weapons::update_weapons,
                        weapons::drop::update_seals,
                        player::dash_strike,
                        reveal::flame_band,
                        reactions::update_zones,
                        charms::burn_trail,
                        combat::process_strikes,
                    )
                        .chain()
                        .in_set(SimSet::Weapons),
                    (weapons::volley::update_shots, boss::update_foes).chain().in_set(SimSet::Projectiles),
                    charms::apply_rescue.in_set(SimSet::Collide),
                    combat::resolve_hits.in_set(SimSet::Damage),
                    combat::burn.in_set(SimSet::Status),
                    combat::process_deaths.in_set(SimSet::Death),
                    (
                        gems::update_gems,
                        gold::update_coins,
                        pickups::update_pickups,
                        lanterns::update_lanterns,
                        reactions::update_herbs,
                        encounters::update_encounters,
                        stats::refresh_stats,
                    )
                        .chain()
                        .in_set(SimSet::Pickup),
                    (gems::level_up, flow::check_flow).chain().in_set(SimSet::Progress),
                    (tick::advance_tick, tick::record_hash, replay::sync_hashes).chain().in_set(SimSet::Hash),
                ),
            )
            // 模拟进入结束阶段后切换界面状态；画面、音频、界面在 Update 里消费完事件后，这里统一清空。
            .add_systems(
                Update,
                tick::sync_run_state.run_if(in_state(RunState::Playing)).run_if(resource_exists::<SimPhase>),
            )
            .add_systems(Last, io::clear_outbox);
    }
}
