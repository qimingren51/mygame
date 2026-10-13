//! 平台层：输入映射、数据目录、设置（docs/DESIGN.md 第 12 节）。
//!
//! 输入先汇总成与设备无关的 [`Actions`]，界面读它导航菜单；游戏进行中再转换成模拟的
//! [`InputFrame`] 和 [`SimCommand`]。

use bevy::prelude::*;
use bevy::window::{MonitorSelection, PrimaryWindow, WindowMode};

use lantern_sim::{InputFrame, ReplayPlayback, RunState, SimCommand, SimCommands, SimPhase};

pub mod bindings;
mod input;
pub mod paths;
pub mod profile;
pub mod replays;
mod rumble;
pub mod settings;

pub use bindings::{Action, ActiveInput, InputDevice, Rebind};
pub use profile::{HubNews, Profile};
pub use settings::Settings;

/// 本帧的抽象操作。由键盘和手柄合并而来，y 轴向下（与模拟一致）。
#[derive(Resource, Default, Debug, Clone, Copy)]
pub struct Actions {
    pub move_dir: Vec2,
    pub dash: bool,
    pub confirm: bool,
    pub back: bool,
    pub pause: bool,
    pub quit_to_title: bool,
    pub toggle_fullscreen: bool,
    /// 标题界面：开始跑分
    pub bench: bool,
    /// 显示 / 隐藏性能面板
    pub toggle_perf: bool,
    /// 燃灯
    pub ult: bool,
    /// 升级时重抽、跳过、封印选中的一项
    pub reroll: bool,
    pub skip: bool,
    pub banish: bool,
    /// 菜单里移动选择（这一帧按下的方向，y 向下）
    pub nav: IVec2,
    /// 数字键 1–9 直接选择（从 0 起）
    pub pick: Option<u8>,
    /// 标题界面：心灯
    pub meta: bool,
    /// 这一帧鼠标动过。菜单弹出时光标恰好停在某一项上，不算悬停，免得抢走键盘的选择
    pub pointer_moved: bool,
}

/// 跑分时自动绕圈走，代替玩家输入。存在这个资源时，键盘和手柄的移动不交给模拟。
#[derive(Resource, Default, Debug)]
pub struct AutoPilot {
    pub t: f32,
}

pub struct PlatformPlugin {
    pub settings: Settings,
}

impl Plugin for PlatformPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(self.settings.clone())
            .init_resource::<Actions>()
            .add_systems(Update, toggle_fullscreen);
        input::register(app);
        replays::register(app);
        rumble::register(app);
    }
}

/// 游戏进行中，把操作交给模拟。帧率高于 60 时，某些帧不跑模拟步，命令会留到下一步处理。
fn feed_sim(
    time: Res<Time>,
    actions: Res<Actions>,
    state: Option<Res<State<RunState>>>,
    phase: Option<Res<SimPhase>>,
    autopilot: Option<ResMut<AutoPilot>>,
    playback: Option<Res<ReplayPlayback>>,
    mut input: ResMut<InputFrame>,
    mut commands: ResMut<SimCommands>,
) {
    // 升级选择等阶段的命令由界面发；这里只管游戏进行中的移动、闪避、燃灯
    let playing =
        state.is_some_and(|s| *s.get() == RunState::Playing) && phase.is_some_and(|p| *p == SimPhase::Play);
    // 重放时输入和命令由回放提供
    if playback.is_some() {
        return;
    }
    if !playing {
        *input = InputFrame::default();
        return;
    }
    if let Some(mut auto) = autopilot {
        // 半径约 236 的大圈，速度和玩家走路一样
        auto.t += time.delta_secs();
        *input = InputFrame::quantize(Vec2::new((auto.t * 0.5).cos(), (auto.t * 0.5).sin()));
        return;
    }
    *input = InputFrame::quantize(actions.move_dir);
    if actions.dash {
        commands.0.push(SimCommand::Dash);
    }
    if actions.ult {
        commands.0.push(SimCommand::Ult);
    }
}

fn toggle_fullscreen(
    actions: Res<Actions>,
    mut settings: ResMut<Settings>,
    mut window: Single<&mut Window, With<PrimaryWindow>>,
) {
    if !actions.toggle_fullscreen {
        return;
    }
    settings.fullscreen = !settings.fullscreen;
    window.mode = if settings.fullscreen {
        WindowMode::BorderlessFullscreen(MonitorSelection::Current)
    } else {
        WindowMode::Windowed
    };
    if let Err(e) = settings.save() {
        warn!("保存设置失败：{e}");
    }
}
