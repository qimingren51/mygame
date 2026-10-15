//! 提示模板只在界面层展开，设备与绑定变化无需重建菜单或重播入场动画。

use bevy::prelude::*;
use lantern_platform::bindings::{button_label, key_label};
use lantern_platform::{Action, ActiveInput, InputDevice, Settings};

#[derive(Component)]
pub(crate) struct Prompt(pub String);

pub(crate) fn hint(font: &Handle<Font>, size: f32, color: Color, template: &str) -> impl Bundle {
    (Prompt(template.into()), crate::text(font, size, color, ""))
}

pub(crate) fn render(template: &str, active: &ActiveInput, settings: &Settings) -> String {
    let label = |action| match active.device {
        InputDevice::Keyboard => key_label(settings.bindings.key(action)),
        InputDevice::Gamepad => button_label(settings.bindings.button(action)),
    };
    let nav = match active.device {
        InputDevice::Keyboard => "方向键",
        InputDevice::Gamepad => "十字键 / 左摇杆",
    };
    let movement = match active.device {
        InputDevice::Keyboard => {
            [Action::Up, Action::Left, Action::Down, Action::Right].map(label).join(" / ")
        }
        InputDevice::Gamepad => "左摇杆".into(),
    };
    let mut result = template.replace("{nav}", nav).replace("{move}", &movement);
    for (token, action) in [
        ("{dash}", Action::Dash),
        ("{ult}", Action::Ult),
        ("{interact}", Action::Interact),
        ("{pause}", Action::Pause),
        ("{confirm}", Action::Confirm),
        ("{back}", Action::Back),
        ("{reroll}", Action::Reroll),
        ("{skip}", Action::Skip),
        ("{banish}", Action::Banish),
        ("{hub}", Action::Hub),
    ] {
        result = result.replace(token, &label(action));
    }
    for i in 1..=9 {
        result = result.replace(
            &format!("{{pick{i}}}"),
            &if active.device == InputDevice::Keyboard { i.to_string() } else { String::new() },
        );
    }
    result.replace("{fullscreen}", if active.device == InputDevice::Keyboard { "F11 全屏" } else { "" })
}

pub(crate) fn refresh(
    active: Res<ActiveInput>,
    settings: Res<Settings>,
    mut texts: Query<(&Prompt, &mut Text)>,
) {
    for (prompt, mut text) in &mut texts {
        let next = render(&prompt.0, &active, &settings);
        if text.0 != next {
            text.0 = next;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompts_follow_device_and_rebinding() {
        let mut settings = Settings::default();
        let mut active = ActiveInput::default();
        settings.bindings.bind_key(Action::Dash, KeyCode::KeyJ).unwrap();
        assert_eq!(render("{dash} 闪避", &active, &settings), "J 闪避");
        active.device = InputDevice::Gamepad;
        assert_eq!(render("{dash} 闪避", &active, &settings), "A 闪避");
        settings.bindings.bind_button(Action::Dash, GamepadButton::RightTrigger2).unwrap();
        assert_eq!(render("{dash} 闪避", &active, &settings), "RT 闪避");
        assert_eq!(render("{interact} 留灯", &active, &settings), "X 留灯");
        active.device = InputDevice::Keyboard;
        assert_eq!(render("{interact} 留灯", &active, &settings), "G 留灯");
    }
}
