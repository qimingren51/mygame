//! 设备仲裁、摇杆死区与菜单连发都留在平台层，模拟只接收量化后的动作。

use std::collections::BTreeMap;

use bevy::input::{InputSystems, mouse::MouseWheel};
use bevy::prelude::*;
use bevy::window::CursorMoved;

use crate::bindings::{InputDevice, RebindFeedback};
use crate::{Action, Actions, ActiveInput, Rebind, Settings};
use lantern_sim::{RunState, SimPhase};

pub(crate) fn register(app: &mut App) {
    app.init_resource::<ActiveInput>()
        .init_resource::<Rebind>()
        .add_systems(PreUpdate, (gather, crate::feed_sim).chain().after(InputSystems));
}

#[derive(Default)]
struct Navigation {
    held: IVec2,
    remaining: f32,
    /// 游戏进行中按着方向走路；面板弹出后要先松开（回中）才开始在菜单里移动，
    /// 不然升级面板一打开光标就跟着跳。
    blocked: bool,
}

impl Navigation {
    fn step(&mut self, direction: IVec2, dt: f32) -> IVec2 {
        if direction == IVec2::ZERO {
            *self = Self::default();
            return IVec2::ZERO;
        }
        if self.blocked {
            return IVec2::ZERO;
        }
        if direction != self.held {
            self.held = direction;
            self.remaining = 0.34;
            return direction;
        }
        self.remaining -= dt.min(0.1);
        if self.remaining <= 0.0 {
            self.remaining = 0.11;
            direction
        } else {
            IVec2::ZERO
        }
    }
}

fn stick_direction(stick: Vec2, previous: IVec2) -> IVec2 {
    let threshold = if previous == IVec2::ZERO { 0.55 } else { 0.30 };
    if stick.abs().max_element() < threshold {
        IVec2::ZERO
    } else if stick.x.abs() > stick.y.abs() {
        IVec2::new(stick.x.signum() as i32, 0)
    } else {
        IVec2::new(0, -stick.y.signum() as i32)
    }
}

fn move_stick(stick: Vec2) -> Vec2 {
    let length = stick.length();
    if length <= 0.22 {
        Vec2::ZERO
    } else {
        Vec2::new(stick.x, -stick.y) / length * ((length - 0.22) / 0.78).min(1.0)
    }
}

#[derive(Default)]
struct InputMemory {
    sticks: BTreeMap<Entity, Vec2>,
    stick_nav: IVec2,
    nav: Navigation,
}

fn gather(
    time: Res<Time<Real>>,
    keys: Res<ButtonInput<KeyCode>>,
    mouse: Res<ButtonInput<MouseButton>>,
    gamepads: Query<(Entity, &Gamepad)>,
    mut cursor: MessageReader<CursorMoved>,
    mut wheel: MessageReader<MouseWheel>,
    mut settings: ResMut<Settings>,
    mut active: ResMut<ActiveInput>,
    mut rebind: ResMut<Rebind>,
    mut memory: Local<InputMemory>,
    mut actions: ResMut<Actions>,
    state: Option<Res<State<RunState>>>,
    phase: Option<Res<SimPhase>>,
) {
    let playing =
        state.is_some_and(|s| *s.get() == RunState::Playing) && phase.is_some_and(|p| *p == SimPhase::Play);
    let pointer_moved =
        cursor.read().fold(false, |moved, e| moved | e.delta.is_some_and(|d| d.length_squared() > 1.0));
    let wheel_moved = wheel.read().fold(false, |moved, e| moved | (e.x != 0.0 || e.y != 0.0));
    let keyboard_active = keys.get_just_pressed().next().is_some()
        || mouse.get_just_pressed().next().is_some()
        || pointer_moved
        || wheel_moved;
    let mut pad_activity = None;
    memory.sticks.retain(|entity, _| gamepads.get(*entity).is_ok());
    for (entity, pad) in &gamepads {
        let stick = pad.left_stick();
        let old = memory.sticks.get(&entity).copied().unwrap_or(Vec2::ZERO);
        if pad.get_just_pressed().next().is_some() || (stick.length() > 0.30 && (stick - old).length() > 0.12)
        {
            pad_activity = Some(entity);
            memory.sticks.insert(entity, stick);
        } else if stick.length() <= 0.22 {
            memory.sticks.insert(entity, Vec2::ZERO);
        }
    }
    if let Some(entity) = pad_activity {
        active.device = InputDevice::Gamepad;
        active.gamepad = Some(entity);
    } else if keyboard_active || active.gamepad.is_some_and(|e| gamepads.get(e).is_err()) {
        active.device = InputDevice::Keyboard;
        active.gamepad = None;
    }
    let pad = active.gamepad.and_then(|e| gamepads.get(e).ok().map(|(_, p)| p));
    let neutral = keys.get_pressed().next().is_none()
        && mouse.get_pressed().next().is_none()
        && gamepads.iter().all(|(_, p)| p.get_pressed().next().is_none() && p.left_stick().length() < 0.3);
    if rebind.target.is_some() || rebind.release_gate {
        *actions = Actions::default();
        memory.nav = Navigation::default();
        memory.stick_nav = IVec2::ZERO;
        capture(&keys, &gamepads, neutral, &mut settings, &mut rebind);
        return;
    }
    let bindings = &settings.bindings;
    let pressed = |action| {
        bindings.keys(action).any(|key| keys.just_pressed(key))
            || pad.is_some_and(|p| bindings.buttons(action).any(|button| p.just_pressed(button)))
    };
    let held = |action| keys.pressed(bindings.key(action));
    let direction = IVec2::new(
        i32::from(held(Action::Right) || keys.pressed(KeyCode::ArrowRight))
            - i32::from(held(Action::Left) || keys.pressed(KeyCode::ArrowLeft)),
        i32::from(held(Action::Down) || keys.pressed(KeyCode::ArrowDown))
            - i32::from(held(Action::Up) || keys.pressed(KeyCode::ArrowUp)),
    );
    let mut movement = direction.as_vec2().normalize_or_zero();
    let mut nav = direction;
    if let Some(pad) = pad {
        let dpad = IVec2::new(
            i32::from(pad.pressed(GamepadButton::DPadRight))
                - i32::from(pad.pressed(GamepadButton::DPadLeft)),
            i32::from(pad.pressed(GamepadButton::DPadDown)) - i32::from(pad.pressed(GamepadButton::DPadUp)),
        );
        let stick = move_stick(pad.left_stick()) + dpad.as_vec2();
        if stick.length_squared() > movement.length_squared() {
            movement = stick.clamp_length_max(1.0);
        }
        memory.stick_nav = stick_direction(pad.left_stick(), memory.stick_nav);
        if dpad != IVec2::ZERO {
            nav = dpad;
        } else if memory.stick_nav != IVec2::ZERO {
            nav = memory.stick_nav;
        }
    } else {
        memory.stick_nav = IVec2::ZERO;
    }
    // 每次只走一个轴，避免斜推时在网格里一次跳过两格。
    if nav.y != 0 {
        nav.x = 0;
    }
    if playing {
        memory.nav.blocked = true;
    }
    let toggle_fullscreen = keys.just_pressed(KeyCode::F11)
        || (keys.any_pressed([KeyCode::AltLeft, KeyCode::AltRight]) && keys.just_pressed(KeyCode::Enter));
    const DIGITS: [KeyCode; 9] = [
        KeyCode::Digit1,
        KeyCode::Digit2,
        KeyCode::Digit3,
        KeyCode::Digit4,
        KeyCode::Digit5,
        KeyCode::Digit6,
        KeyCode::Digit7,
        KeyCode::Digit8,
        KeyCode::Digit9,
    ];
    const NUMPAD: [KeyCode; 9] = [
        KeyCode::Numpad1,
        KeyCode::Numpad2,
        KeyCode::Numpad3,
        KeyCode::Numpad4,
        KeyCode::Numpad5,
        KeyCode::Numpad6,
        KeyCode::Numpad7,
        KeyCode::Numpad8,
        KeyCode::Numpad9,
    ];
    *actions = Actions {
        move_dir: movement,
        dash: pressed(Action::Dash),
        ult: pressed(Action::Ult),
        confirm: !toggle_fullscreen && pressed(Action::Confirm),
        back: pressed(Action::Back) || keys.just_pressed(KeyCode::Escape),
        pause: pressed(Action::Pause) || keys.just_pressed(KeyCode::Escape),
        reroll: pressed(Action::Reroll),
        skip: pressed(Action::Skip),
        banish: pressed(Action::Banish),
        meta: pressed(Action::Hub),
        nav: memory.nav.step(nav, time.delta_secs()),
        quit_to_title: keys.just_pressed(KeyCode::KeyQ)
            || pad.is_some_and(|p| p.just_pressed(GamepadButton::Select)),
        pick: DIGITS.iter().zip(NUMPAD).position(|(&k, n)| keys.any_just_pressed([k, n])).map(|i| i as u8),
        pointer_moved: pointer_moved && active.device == InputDevice::Keyboard,
        toggle_fullscreen,
        bench: keys.just_pressed(KeyCode::KeyB),
        toggle_perf: keys.just_pressed(KeyCode::F3),
    };
}

fn capture(
    keys: &ButtonInput<KeyCode>,
    gamepads: &Query<(Entity, &Gamepad)>,
    neutral: bool,
    settings: &mut Settings,
    rebind: &mut Rebind,
) {
    if rebind.release_gate {
        if neutral {
            rebind.release_gate = false;
        }
        return;
    }
    let Some((device, action)) = rebind.target else { return };
    if !rebind.armed {
        rebind.armed = neutral;
        return;
    }
    let cancel_action = if action == Action::Back { Action::Confirm } else { Action::Back };
    let cancel = keys.just_pressed(KeyCode::Escape)
        || gamepads.iter().any(|(_, p)| p.just_pressed(settings.bindings.button(cancel_action)));
    if cancel {
        rebind.target = None;
        rebind.release_gate = true;
        rebind.feedback = RebindFeedback::Cancelled;
        return;
    }
    let result = match device {
        InputDevice::Keyboard => {
            keys.get_just_pressed().min().map(|key| settings.bindings.bind_key(action, *key))
        }
        InputDevice::Gamepad => gamepads
            .iter()
            .flat_map(|(_, p)| p.get_just_pressed())
            .min()
            .map(|button| settings.bindings.bind_button(action, *button)),
    };
    if let Some(result) = result {
        match result {
            Ok(()) => {
                rebind.target = None;
                rebind.release_gate = true;
                rebind.feedback = match settings.save() {
                    Ok(()) => RebindFeedback::Saved,
                    Err(e) => {
                        warn!("保存按键失败：{e}");
                        RebindFeedback::SaveFailed
                    }
                };
            }
            Err(error) => rebind.feedback = RebindFeedback::Error(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stick_deadzone_hysteresis_and_single_axis() {
        assert_eq!(move_stick(Vec2::splat(0.1)), Vec2::ZERO);
        assert_eq!(stick_direction(Vec2::new(0.5, 0.0), IVec2::ZERO), IVec2::ZERO);
        assert_eq!(stick_direction(Vec2::new(0.7, 0.6), IVec2::ZERO), IVec2::X);
        assert_eq!(stick_direction(Vec2::new(0.4, 0.0), IVec2::X), IVec2::X);
        assert_eq!(stick_direction(Vec2::new(0.2, 0.0), IVec2::X), IVec2::ZERO);
        assert_eq!(stick_direction(Vec2::Y, IVec2::ZERO), IVec2::NEG_Y);
    }

    #[test]
    fn repeat_delays_then_repeats_and_resets_on_release() {
        let mut nav = Navigation::default();
        assert_eq!(nav.step(IVec2::X, 0.016), IVec2::X);
        for _ in 0..3 {
            assert_eq!(nav.step(IVec2::X, 0.1), IVec2::ZERO);
        }
        assert_eq!(nav.step(IVec2::X, 0.05), IVec2::X);
        assert_eq!(nav.step(IVec2::X, 0.05), IVec2::ZERO);
        assert_eq!(nav.step(IVec2::X, 0.07), IVec2::X);
        assert_eq!(nav.step(IVec2::NEG_X, 0.01), IVec2::NEG_X);
        assert_eq!(nav.step(IVec2::ZERO, 0.01), IVec2::ZERO);
        assert_eq!(nav.step(IVec2::X, 0.01), IVec2::X);
    }

    /// 游戏里按着方向走路时弹出面板：先松开才开始在菜单里移动。
    #[test]
    fn held_direction_from_play_is_ignored_until_released() {
        let mut nav = Navigation { blocked: true, ..default() };
        for _ in 0..10 {
            assert_eq!(nav.step(IVec2::NEG_Y, 0.1), IVec2::ZERO);
        }
        assert_eq!(nav.step(IVec2::ZERO, 0.01), IVec2::ZERO);
        assert_eq!(nav.step(IVec2::NEG_Y, 0.01), IVec2::NEG_Y);
    }

    fn input_app() -> (App, Entity) {
        let mut app = App::new();
        app.init_resource::<Time<Real>>()
            .init_resource::<ButtonInput<KeyCode>>()
            .init_resource::<ButtonInput<MouseButton>>()
            .init_resource::<Settings>()
            .init_resource::<Actions>()
            .init_resource::<ActiveInput>()
            .init_resource::<Rebind>()
            .add_message::<CursorMoved>()
            .add_message::<MouseWheel>()
            .add_systems(Update, gather);
        let pad = app.world_mut().spawn(Gamepad::default()).id();
        (app, pad)
    }

    fn set_stick(app: &mut App, entity: Entity, x: f32, y: f32) {
        use bevy::input::gamepad::GamepadAxis;
        let mut pad = app.world_mut().get_mut::<Gamepad>(entity).unwrap();
        pad.analog_mut().set(GamepadAxis::LeftStickX, x);
        pad.analog_mut().set(GamepadAxis::LeftStickY, y);
    }

    #[test]
    fn real_gather_switches_devices_ignores_drift_and_handles_disconnect() {
        let (mut app, pad) = input_app();
        set_stick(&mut app, pad, 0.1, 0.0);
        app.update();
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Keyboard);
        assert_eq!(app.world().resource::<Actions>().move_dir, Vec2::ZERO);
        // 缓慢推杆也会接管；保持杆位不会抢走新按下的键盘。
        for i in 2..=7 {
            set_stick(&mut app, pad, i as f32 * 0.1, 0.0);
            app.update();
        }
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Gamepad);
        assert!(app.world().resource::<Actions>().move_dir.x > 0.5);
        app.world_mut().resource_mut::<ButtonInput<KeyCode>>().press(KeyCode::KeyJ);
        app.update();
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Keyboard);
        app.world_mut().resource_mut::<ButtonInput<KeyCode>>().clear();
        app.update();
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Keyboard);
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().press(GamepadButton::South);
        app.update();
        assert!(app.world().resource::<Actions>().confirm);
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Gamepad);
        app.world_mut().despawn(pad);
        app.update();
        assert_eq!(app.world().resource::<ActiveInput>().device, InputDevice::Keyboard);
        assert_eq!(app.world().resource::<Actions>().move_dir, Vec2::ZERO);
    }

    #[test]
    fn capture_waits_for_release_consumes_press_and_uses_new_binding() {
        let (mut app, pad) = input_app();
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().press(GamepadButton::South);
        app.world_mut().resource_mut::<Rebind>().begin(InputDevice::Gamepad, Action::Dash);
        app.update();
        assert!(!app.world().resource::<Rebind>().armed);
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().reset_all();
        app.update();
        assert!(app.world().resource::<Rebind>().armed);
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().press(GamepadButton::RightTrigger2);
        app.update();
        assert_eq!(
            app.world().resource::<Settings>().bindings.button(Action::Dash),
            GamepadButton::RightTrigger2
        );
        assert!(!app.world().resource::<Actions>().dash);
        assert!(app.world().resource::<Rebind>().release_gate);
        app.update();
        assert!(!app.world().resource::<Actions>().dash);
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().reset_all();
        app.update();
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().press(GamepadButton::RightTrigger2);
        app.update();
        assert!(app.world().resource::<Actions>().dash);
        assert!(!app.world().resource::<Actions>().confirm);
    }

    #[test]
    fn dpad_and_stick_produce_the_same_menu_direction() {
        let (mut app, pad) = input_app();
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().press(GamepadButton::DPadDown);
        app.update();
        assert_eq!(app.world().resource::<Actions>().nav, IVec2::Y);
        app.world_mut().get_mut::<Gamepad>(pad).unwrap().digital_mut().reset_all();
        app.update();
        set_stick(&mut app, pad, 0.0, -0.8);
        app.update();
        assert_eq!(app.world().resource::<Actions>().nav, IVec2::Y);
    }
}
