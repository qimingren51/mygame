//! 平台层：输入映射、数据目录、设置（docs/DESIGN.md 第 12 节）。
//!
//! 输入先汇总成与设备无关的 [`Actions`]，界面读它导航菜单；游戏进行中再转换成模拟的
//! [`InputFrame`] 和 [`SimCommand`]。

use bevy::input::InputSystems;
use bevy::prelude::*;
use bevy::window::{MonitorSelection, PrimaryWindow, WindowMode};

use lantern_sim::{InputFrame, ReplayPlayback, RunState, SimCommand, SimCommands};

pub mod paths;
pub mod replays;
pub mod settings;

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
            .add_systems(PreUpdate, (gather_actions, feed_sim).chain().after(InputSystems))
            .add_systems(Update, toggle_fullscreen);
        replays::register(app);
    }
}

fn gather_actions(keys: Res<ButtonInput<KeyCode>>, gamepads: Query<&Gamepad>, mut actions: ResMut<Actions>) {
    let held = |a: KeyCode, b: KeyCode| keys.pressed(a) || keys.pressed(b);
    let mut dir = Vec2::ZERO;
    if held(KeyCode::KeyA, KeyCode::ArrowLeft) {
        dir.x -= 1.0;
    }
    if held(KeyCode::KeyD, KeyCode::ArrowRight) {
        dir.x += 1.0;
    }
    if held(KeyCode::KeyW, KeyCode::ArrowUp) {
        dir.y -= 1.0;
    }
    if held(KeyCode::KeyS, KeyCode::ArrowDown) {
        dir.y += 1.0;
    }
    let mut a = Actions {
        move_dir: dir.normalize_or_zero(),
        dash: keys.any_just_pressed([KeyCode::Space, KeyCode::ShiftLeft, KeyCode::ShiftRight]),
        confirm: keys.any_just_pressed([KeyCode::Enter, KeyCode::NumpadEnter]),
        back: keys.just_pressed(KeyCode::Escape),
        pause: keys.just_pressed(KeyCode::Escape),
        quit_to_title: keys.just_pressed(KeyCode::KeyQ),
        toggle_fullscreen: keys.just_pressed(KeyCode::F11)
            || (keys.pressed(KeyCode::AltLeft) && keys.just_pressed(KeyCode::Enter)),
        bench: keys.just_pressed(KeyCode::KeyB),
        toggle_perf: keys.just_pressed(KeyCode::F3),
    };
    for pad in &gamepads {
        // 手柄摇杆 y 轴向上，这里翻转成向下。
        let stick = pad.left_stick() + pad.dpad();
        let stick = Vec2::new(stick.x, -stick.y);
        if stick.length_squared() > a.move_dir.length_squared() {
            a.move_dir = stick.clamp_length_max(1.0);
        }
        a.dash |= pad.just_pressed(GamepadButton::South) || pad.just_pressed(GamepadButton::RightTrigger);
        a.confirm |= pad.just_pressed(GamepadButton::South);
        a.back |= pad.just_pressed(GamepadButton::East);
        a.pause |= pad.just_pressed(GamepadButton::Start);
        a.quit_to_title |= pad.just_pressed(GamepadButton::Select);
    }
    if a.toggle_fullscreen {
        a.confirm = false;
    }
    *actions = a;
}

/// 游戏进行中，把操作交给模拟。帧率高于 60 时，某些帧不跑模拟步，命令会留到下一步处理。
fn feed_sim(
    time: Res<Time>,
    actions: Res<Actions>,
    state: Option<Res<State<RunState>>>,
    autopilot: Option<ResMut<AutoPilot>>,
    playback: Option<Res<ReplayPlayback>>,
    mut input: ResMut<InputFrame>,
    mut commands: ResMut<SimCommands>,
) {
    let playing = state.is_some_and(|s| *s.get() == RunState::Playing);
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
