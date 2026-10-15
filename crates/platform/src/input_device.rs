//! 只为界面记录最近使用的设备，不改变操作合并或模拟输入。

use bevy::input::ButtonState;
use bevy::input::gamepad::{GamepadAxisChangedEvent, GamepadButtonChangedEvent};
use bevy::input::keyboard::KeyboardInput;
use bevy::input::mouse::MouseButtonInput;
use bevy::prelude::*;

#[derive(Resource, Default, Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputDevice {
    #[default]
    Keyboard,
    Gamepad,
}

pub(super) fn track(
    mut keys: MessageReader<KeyboardInput>,
    mut mouse: MessageReader<MouseButtonInput>,
    mut buttons: MessageReader<GamepadButtonChangedEvent>,
    mut axes: MessageReader<GamepadAxisChangedEvent>,
    mut device: ResMut<InputDevice>,
) {
    // 消费全部消息；按住、松开和摇杆回中都不抢走新设备的提示。
    let keyboard = keys.read().filter(|e| e.state == ButtonState::Pressed && !e.repeat).count() > 0;
    let mouse = mouse.read().filter(|e| e.state == ButtonState::Pressed).count() > 0;
    let button = buttons.read().filter(|e| e.state == ButtonState::Pressed).count() > 0;
    // 只认明显的摇杆动作，避免轻微漂移造成提示来回闪烁。
    let axis = axes.read().filter(|e| e.value.abs() > 0.25).count() > 0;
    // 同帧输入无法比较设备间的时间戳，统一优先键鼠。
    if keyboard || mouse {
        device.set_if_neq(InputDevice::Keyboard);
    } else if button || axis {
        device.set_if_neq(InputDevice::Gamepad);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bevy::input::keyboard::Key;

    #[test]
    fn switches_on_intentional_input_without_repeat_or_stick_drift() {
        let mut app = App::new();
        app.init_resource::<InputDevice>()
            .add_message::<KeyboardInput>()
            .add_message::<MouseButtonInput>()
            .add_message::<GamepadButtonChangedEvent>()
            .add_message::<GamepadAxisChangedEvent>()
            .add_systems(Update, track);
        let entity = app.world_mut().spawn_empty().id();
        let key = KeyboardInput {
            key_code: KeyCode::KeyW,
            logical_key: Key::Character("w".into()),
            state: ButtonState::Pressed,
            text: None,
            repeat: false,
            window: entity,
        };
        app.world_mut().write_message(GamepadButtonChangedEvent::new(
            entity,
            GamepadButton::North,
            ButtonState::Pressed,
            1.0,
        ));
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Gamepad);

        app.world_mut().write_message(KeyboardInput { repeat: true, ..key.clone() });
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Gamepad);

        app.world_mut().write_message(key);
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Keyboard);
        for value in [0.1, -0.2, 0.0] {
            app.world_mut().write_message(GamepadAxisChangedEvent::new(
                entity,
                GamepadAxis::LeftStickX,
                value,
            ));
        }
        app.world_mut().write_message(GamepadButtonChangedEvent::new(
            entity,
            GamepadButton::North,
            ButtonState::Released,
            0.0,
        ));
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Keyboard);

        app.world_mut().write_message(GamepadAxisChangedEvent::new(entity, GamepadAxis::LeftStickX, -0.8));
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Gamepad);
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Gamepad);

        app.world_mut().write_message(MouseButtonInput {
            button: MouseButton::Left,
            state: ButtonState::Pressed,
            window: entity,
        });
        app.update();
        assert_eq!(*app.world().resource::<InputDevice>(), InputDevice::Keyboard);
    }
}
