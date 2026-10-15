//! 可存档的动作映射。冲突按使用场景判断，菜单保留方向键与 Esc 作为恢复入口。

use std::collections::BTreeMap;

use bevy::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Action {
    Up,
    Down,
    Left,
    Right,
    Dash,
    Ult,
    Pause,
    Confirm,
    Back,
    Reroll,
    Skip,
    Banish,
    Hub,
}

impl Action {
    pub const ALL: [Self; 13] = [
        Self::Up,
        Self::Down,
        Self::Left,
        Self::Right,
        Self::Dash,
        Self::Ult,
        Self::Pause,
        Self::Confirm,
        Self::Back,
        Self::Reroll,
        Self::Skip,
        Self::Banish,
        Self::Hub,
    ];
    pub const BUTTONS: [Self; 9] = [
        Self::Dash,
        Self::Ult,
        Self::Pause,
        Self::Confirm,
        Self::Back,
        Self::Reroll,
        Self::Skip,
        Self::Banish,
        Self::Hub,
    ];

    fn contexts(self) -> u8 {
        match self {
            Self::Up | Self::Down | Self::Left | Self::Right => 15,
            Self::Dash | Self::Ult => 1,
            Self::Pause => 9,
            Self::Confirm | Self::Back => 14,
            Self::Reroll | Self::Skip | Self::Banish => 2,
            Self::Hub => 4,
        }
    }

    fn conflicts(self, other: Self) -> bool {
        self != other
            && !matches!((self, other), (Self::Pause, Self::Back) | (Self::Back, Self::Pause))
            && self.contexts() & other.contexts() != 0
    }

    pub fn default_key(self) -> KeyCode {
        match self {
            Self::Up => KeyCode::KeyW,
            Self::Down => KeyCode::KeyS,
            Self::Left => KeyCode::KeyA,
            Self::Right => KeyCode::KeyD,
            Self::Dash => KeyCode::Space,
            Self::Ult => KeyCode::KeyE,
            Self::Pause | Self::Back => KeyCode::Escape,
            Self::Confirm => KeyCode::Enter,
            Self::Reroll => KeyCode::KeyR,
            Self::Skip => KeyCode::KeyX,
            Self::Banish => KeyCode::KeyC,
            Self::Hub => KeyCode::KeyM,
        }
    }

    pub fn default_button(self) -> GamepadButton {
        match self {
            Self::Up => GamepadButton::DPadUp,
            Self::Down => GamepadButton::DPadDown,
            Self::Left => GamepadButton::DPadLeft,
            Self::Right => GamepadButton::DPadRight,
            Self::Dash | Self::Confirm => GamepadButton::South,
            Self::Ult | Self::Reroll => GamepadButton::North,
            Self::Pause => GamepadButton::Start,
            Self::Back => GamepadButton::East,
            Self::Skip | Self::Hub => GamepadButton::West,
            Self::Banish => GamepadButton::LeftTrigger,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Bindings {
    keyboard: BTreeMap<Action, KeyCode>,
    gamepad: BTreeMap<Action, GamepadButton>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BindError {
    Reserved,
    Conflict(Action),
}

impl Bindings {
    pub fn key(&self, action: Action) -> KeyCode {
        self.keyboard.get(&action).copied().unwrap_or_else(|| action.default_key())
    }

    pub fn button(&self, action: Action) -> GamepadButton {
        self.gamepad.get(&action).copied().unwrap_or_else(|| action.default_button())
    }

    /// 旧版的便捷副键只在该动作未改键、且副键未被别的自定义绑定占用时保留。
    pub fn keys(&self, action: Action) -> impl Iterator<Item = KeyCode> + '_ {
        let aliases: &[KeyCode] = match action {
            Action::Dash => &[KeyCode::ShiftLeft, KeyCode::ShiftRight],
            Action::Ult => &[KeyCode::KeyF],
            Action::Confirm => &[KeyCode::NumpadEnter],
            _ => &[],
        };
        std::iter::once(self.key(action)).chain(aliases.iter().copied().filter(move |key| {
            !self.keyboard.contains_key(&action) && !self.keyboard.values().any(|bound| bound == key)
        }))
    }

    pub fn buttons(&self, action: Action) -> impl Iterator<Item = GamepadButton> + '_ {
        let aliases: &[GamepadButton] = match action {
            Action::Dash => &[GamepadButton::RightTrigger],
            Action::Ult => &[GamepadButton::RightTrigger2],
            _ => &[],
        };
        std::iter::once(self.button(action)).chain(aliases.iter().copied().filter(move |button| {
            !self.gamepad.contains_key(&action) && !self.gamepad.values().any(|bound| bound == button)
        }))
    }

    pub fn bind_key(&mut self, action: Action, key: KeyCode) -> Result<(), BindError> {
        // 固定菜单导航、数字直选与系统快捷键不参与改键。
        if matches!(
            key,
            KeyCode::ArrowUp
                | KeyCode::ArrowDown
                | KeyCode::ArrowLeft
                | KeyCode::ArrowRight
                | KeyCode::F3
                | KeyCode::F11
                | KeyCode::KeyB
                | KeyCode::AltLeft
                | KeyCode::AltRight
                | KeyCode::SuperLeft
                | KeyCode::SuperRight
                | KeyCode::Unidentified(_)
                | KeyCode::Digit1
                | KeyCode::Digit2
                | KeyCode::Digit3
                | KeyCode::Digit4
                | KeyCode::Digit5
                | KeyCode::Digit6
                | KeyCode::Digit7
                | KeyCode::Digit8
                | KeyCode::Digit9
                | KeyCode::Numpad1
                | KeyCode::Numpad2
                | KeyCode::Numpad3
                | KeyCode::Numpad4
                | KeyCode::Numpad5
                | KeyCode::Numpad6
                | KeyCode::Numpad7
                | KeyCode::Numpad8
                | KeyCode::Numpad9
        ) || (key == KeyCode::Escape && !matches!(action, Action::Back | Action::Pause))
        {
            return Err(BindError::Reserved);
        }
        if let Some(other) =
            Action::ALL.into_iter().find(|&other| action.conflicts(other) && self.key(other) == key)
        {
            return Err(BindError::Conflict(other));
        }
        self.keyboard.insert(action, key);
        Ok(())
    }

    pub fn bind_button(&mut self, action: Action, button: GamepadButton) -> Result<(), BindError> {
        if !Action::BUTTONS.contains(&action)
            || matches!(
                button,
                GamepadButton::DPadUp
                    | GamepadButton::DPadDown
                    | GamepadButton::DPadLeft
                    | GamepadButton::DPadRight
                    | GamepadButton::Mode
            )
        {
            return Err(BindError::Reserved);
        }
        if let Some(other) =
            Action::BUTTONS.into_iter().find(|&other| action.conflicts(other) && self.button(other) == button)
        {
            return Err(BindError::Conflict(other));
        }
        self.gamepad.insert(action, button);
        Ok(())
    }

    pub fn reset(&mut self, device: InputDevice) {
        match device {
            InputDevice::Keyboard => self.keyboard.clear(),
            InputDevice::Gamepad => self.gamepad.clear(),
        }
    }

    /// 手改文件出现冲突时按设备恢复默认，防止确认或返回失效。
    pub fn validate(&mut self) {
        let old = self.clone();
        for (action, key) in &old.keyboard {
            if self.bind_key(*action, *key).is_err() {
                self.keyboard.clear();
                break;
            }
        }
        for (action, button) in &old.gamepad {
            if self.bind_button(*action, *button).is_err() {
                self.gamepad.clear();
                break;
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum InputDevice {
    #[default]
    Keyboard,
    Gamepad,
}

#[derive(Resource, Default, Debug)]
pub struct ActiveInput {
    pub device: InputDevice,
    pub gamepad: Option<Entity>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RebindFeedback {
    Idle,
    Listening,
    Saved,
    Cancelled,
    Error(BindError),
    SaveFailed,
}

#[derive(Resource, Debug)]
pub struct Rebind {
    pub target: Option<(InputDevice, Action)>,
    pub feedback: RebindFeedback,
    pub(crate) armed: bool,
    pub(crate) release_gate: bool,
}

impl Default for Rebind {
    fn default() -> Self {
        Self { target: None, feedback: RebindFeedback::Idle, armed: false, release_gate: false }
    }
}

impl Rebind {
    pub fn begin(&mut self, device: InputDevice, action: Action) {
        self.target = Some((device, action));
        self.feedback = RebindFeedback::Listening;
        self.armed = false;
    }
}

pub fn key_label(key: KeyCode) -> String {
    match key {
        KeyCode::Escape => "Esc".into(),
        KeyCode::Space => "空格".into(),
        KeyCode::Enter => "回车".into(),
        KeyCode::Backspace => "退格".into(),
        KeyCode::ArrowUp => "↑".into(),
        KeyCode::ArrowDown => "↓".into(),
        KeyCode::ArrowLeft => "←".into(),
        KeyCode::ArrowRight => "→".into(),
        KeyCode::ShiftLeft => "L Shift".into(),
        KeyCode::ShiftRight => "R Shift".into(),
        KeyCode::ControlLeft => "L Ctrl".into(),
        KeyCode::ControlRight => "R Ctrl".into(),
        _ => {
            let s = format!("{key:?}");
            s.strip_prefix("Key").or_else(|| s.strip_prefix("Digit")).unwrap_or(&s).into()
        }
    }
}

/// 用位置标识兼容不同厂商的面键图案。
pub fn button_label(button: GamepadButton) -> String {
    match button {
        GamepadButton::South => "A".into(),
        GamepadButton::East => "B".into(),
        GamepadButton::West => "X".into(),
        GamepadButton::North => "Y".into(),
        GamepadButton::LeftTrigger => "LB".into(),
        GamepadButton::RightTrigger => "RB".into(),
        GamepadButton::LeftTrigger2 => "LT".into(),
        GamepadButton::RightTrigger2 => "RT".into(),
        GamepadButton::LeftThumb => "L3".into(),
        GamepadButton::RightThumb => "R3".into(),
        _ => format!("{button:?}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conflicts_are_checked_in_context_and_never_destroy_old_binding() {
        let mut b = Bindings::default();
        assert_eq!(b.bind_key(Action::Dash, KeyCode::KeyW), Err(BindError::Conflict(Action::Up)));
        assert_eq!(b.key(Action::Dash), KeyCode::Space);
        assert!(b.bind_button(Action::Dash, GamepadButton::South).is_ok());
        assert!(b.bind_button(Action::Hub, GamepadButton::West).is_ok());
        assert_eq!(
            b.bind_button(Action::Confirm, GamepadButton::East),
            Err(BindError::Conflict(Action::Back))
        );
        assert_eq!(b.bind_button(Action::Ult, GamepadButton::DPadUp), Err(BindError::Reserved));
        assert_eq!(b.bind_key(Action::Dash, KeyCode::F11), Err(BindError::Reserved));
        assert!(b.bind_key(Action::Confirm, KeyCode::KeyJ).is_ok());
        b.reset(InputDevice::Keyboard);
        assert_eq!(b.key(Action::Confirm), KeyCode::Enter);
    }

    #[test]
    fn hand_edited_conflicting_mapping_recovers_only_affected_device() {
        let mut b = Bindings::default();
        b.keyboard.insert(Action::Confirm, KeyCode::KeyW);
        b.bind_button(Action::Dash, GamepadButton::RightTrigger2).unwrap();
        b.validate();
        assert_eq!(b.key(Action::Confirm), KeyCode::Enter);
        assert_eq!(b.button(Action::Dash), GamepadButton::RightTrigger2);
    }
}
