//! 平台层：输入映射、数据目录、设置（docs/DESIGN.md 第 12 节）。
//!
//! 输入先汇总成与设备无关的 [`Actions`]，界面读它导航菜单；游戏进行中再转换成模拟的
//! [`InputFrame`] 和 [`SimCommand`]。

use bevy::input::InputSystems;
use bevy::prelude::*;
use bevy::window::{CursorMoved, MonitorSelection, PrimaryWindow, WindowMode};

use lantern_sim::{InputFrame, ReplayPlayback, RunState, SimCommand, SimCommands, SimPhase};

pub mod diagnostics;
pub mod paths;
pub mod profile;
pub mod replays;
mod rumble;
pub mod settings;

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
            .add_systems(PreUpdate, (gather_actions, feed_sim).chain().after(InputSystems))
            .add_systems(Update, toggle_fullscreen);
        replays::register(app);
        rumble::register(app);
    }
}

fn gather_actions(
    keys: Res<ButtonInput<KeyCode>>,
    gamepads: Query<&Gamepad>,
    mut cursor: MessageReader<CursorMoved>,
    mut actions: ResMut<Actions>,
) {
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
        ult: keys.any_just_pressed([KeyCode::KeyE, KeyCode::KeyF]),
        reroll: keys.just_pressed(KeyCode::KeyR),
        skip: keys.just_pressed(KeyCode::KeyX),
        banish: keys.just_pressed(KeyCode::KeyC),
        nav: IVec2::ZERO,
        pick: None,
        meta: keys.just_pressed(KeyCode::KeyM),
        pointer_moved: cursor.read().count() > 0,
    };
    let pressed = |a: KeyCode, b: KeyCode| keys.just_pressed(a) || keys.just_pressed(b);
    if pressed(KeyCode::ArrowLeft, KeyCode::KeyA) {
        a.nav.x -= 1;
    }
    if pressed(KeyCode::ArrowRight, KeyCode::KeyD) {
        a.nav.x += 1;
    }
    if pressed(KeyCode::ArrowUp, KeyCode::KeyW) {
        a.nav.y -= 1;
    }
    if pressed(KeyCode::ArrowDown, KeyCode::KeyS) {
        a.nav.y += 1;
    }
    const DIGITS: [(KeyCode, KeyCode); 9] = [
        (KeyCode::Digit1, KeyCode::Numpad1),
        (KeyCode::Digit2, KeyCode::Numpad2),
        (KeyCode::Digit3, KeyCode::Numpad3),
        (KeyCode::Digit4, KeyCode::Numpad4),
        (KeyCode::Digit5, KeyCode::Numpad5),
        (KeyCode::Digit6, KeyCode::Numpad6),
        (KeyCode::Digit7, KeyCode::Numpad7),
        (KeyCode::Digit8, KeyCode::Numpad8),
        (KeyCode::Digit9, KeyCode::Numpad9),
    ];
    a.pick = DIGITS.iter().position(|&(k, n)| pressed(k, n)).map(|i| i as u8);
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
        a.ult |= pad.just_pressed(GamepadButton::North) || pad.just_pressed(GamepadButton::RightTrigger2);
        a.reroll |= pad.just_pressed(GamepadButton::North);
        a.skip |= pad.just_pressed(GamepadButton::West);
        a.banish |= pad.just_pressed(GamepadButton::LeftTrigger);
        a.meta |= pad.just_pressed(GamepadButton::West);
        if pad.just_pressed(GamepadButton::DPadLeft) {
            a.nav.x -= 1;
        }
        if pad.just_pressed(GamepadButton::DPadRight) {
            a.nav.x += 1;
        }
        if pad.just_pressed(GamepadButton::DPadUp) {
            a.nav.y -= 1;
        }
        if pad.just_pressed(GamepadButton::DPadDown) {
            a.nav.y += 1;
        }
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
