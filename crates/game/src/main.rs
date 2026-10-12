//! 提灯夜行：可执行程序。只负责组装各模块的插件，不写游戏逻辑（docs/DESIGN.md 第 4 节）。

// 发布版在 Windows 上不弹出控制台窗口。
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use std::sync::Arc;
use std::time::Duration;

use bevy::prelude::*;
use bevy::window::{MonitorSelection, PresentMode, WindowMode, WindowResolution};

use lantern_audio::AudioPlugin;
use lantern_content::Content;
use lantern_core::step::{MAX_CATCHUP_TICKS, TICK_HZ};
use lantern_platform::{PlatformPlugin, Settings, paths};
use lantern_sim::{GameContent, SimPlugin};
use lantern_ui::{SeedOverride, UiPlugin};
use lantern_view::ViewPlugin;

const USAGE: &str = "用法：lantern [--seed <数字>] [--windowed]";

struct Args {
    seed: Option<u64>,
    windowed: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args { seed: None, windowed: false };
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        match a.as_str() {
            "--seed" => {
                let v = it.next().ok_or("--seed 后面要跟一个数字")?;
                args.seed = Some(v.parse().map_err(|_| format!("种子不是数字：{v}"))?);
            }
            "--windowed" => args.windowed = true,
            "-h" | "--help" => return Err(USAGE.into()),
            other => return Err(format!("不认识的参数：{other}\n{USAGE}")),
        }
    }
    Ok(args)
}

/// 启动前出错时：打印到终端，同时写进数据目录，Windows 发布版没有控制台也能找到原因。
fn fatal(msg: &str) -> AppExit {
    eprintln!("{msg}");
    let dir = paths::data_dir().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::write(dir.join("startup-error.txt"), msg);
    AppExit::error()
}

fn main() -> AppExit {
    let args = match parse_args() {
        Ok(a) => a,
        Err(msg) => return fatal(&msg),
    };
    let assets = paths::asset_dir();
    let content = match Content::load(&assets.join("data")) {
        Ok(c) => c,
        Err(e) => return fatal(&format!("内容数据有误：{e}")),
    };
    let mut settings = Settings::load(&paths::data_dir());
    if args.windowed {
        settings.fullscreen = false;
    }

    let window = Window {
        title: "提灯夜行".into(),
        resolution: WindowResolution::new(1280, 720),
        mode: if settings.fullscreen {
            WindowMode::BorderlessFullscreen(MonitorSelection::Current)
        } else {
            WindowMode::Windowed
        },
        present_mode: if settings.vsync { PresentMode::AutoVsync } else { PresentMode::AutoNoVsync },
        ..default()
    };

    let mut app = App::new();
    app.add_plugins(
        DefaultPlugins
            .set(WindowPlugin { primary_window: Some(window), ..default() })
            .set(AssetPlugin { file_path: assets.to_string_lossy().into_owned(), ..default() }),
    )
    .insert_resource(Time::<Fixed>::from_hz(f64::from(TICK_HZ)))
    .insert_resource(GameContent(Arc::new(content)))
    .insert_resource(SeedOverride(args.seed))
    .add_plugins((SimPlugin, PlatformPlugin { settings }, ViewPlugin, AudioPlugin, UiPlugin));

    // 一帧最多补 4 步：卡顿时宁可变慢，也不让模拟连续追赶。
    app.world_mut()
        .resource_mut::<Time<Virtual>>()
        .set_max_delta(Duration::from_secs_f64(f64::from(MAX_CATCHUP_TICKS) / f64::from(TICK_HZ)));
    app.run()
}
