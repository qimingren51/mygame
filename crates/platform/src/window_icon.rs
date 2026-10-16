//! 窗口与任务栏复用 EXE 内的图标，无须在安装包中另外查找 ICO。

use bevy::ecs::system::NonSendMarker;
use bevy::prelude::*;
use bevy::window::WindowCreated;
use bevy::winit::WINIT_WINDOWS;
use winit::platform::windows::{IconExtWindows, WindowExtWindows};
use winit::window::Icon;

pub(crate) fn set_window_icon(mut created: MessageReader<WindowCreated>, _main_thread: NonSendMarker) {
    for event in created.read() {
        // winresource::set_icon 默认使用资源编号 1；Windows 从多尺寸资源中选取图标。
        let icon = match Icon::from_resource(1, None) {
            Ok(icon) => icon,
            Err(error) => {
                warn!("读取窗口图标失败：{error}");
                continue;
            }
        };
        WINIT_WINDOWS.with_borrow(|windows| {
            if let Some(window) = windows.get_window(event.window) {
                window.set_window_icon(Some(icon.clone()));
                window.set_taskbar_icon(Some(icon));
            }
        });
    }
}
