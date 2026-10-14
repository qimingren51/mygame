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
use lantern_platform::{PlatformPlugin, Profile, Settings, diagnostics, diagnostics::fatal, paths};
use lantern_sim::{GameContent, Replay, ReplayPlayback, SimPlugin};
use lantern_ui::{ReplaySeek, SeedOverride, UiPlugin};
use lantern_view::ViewPlugin;

const USAGE: &str = "用法：lantern [--seed <数字>] [--windowed] [--replay <回放文件> [--from <秒>]]";

struct Args {
    seed: Option<u64>,
    windowed: bool,
    replay: Option<std::path::PathBuf>,
    from: Option<u32>,
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args { seed: None, windowed: false, replay: None, from: None };
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        match a.as_str() {
            "--seed" => {
                let v = it.next().ok_or("--seed 后面要跟一个数字")?;
                args.seed = Some(v.parse().map_err(|_| format!("种子不是数字：{v}"))?);
            }
            "--windowed" => args.windowed = true,
            "--replay" => args.replay = Some(it.next().ok_or("--replay 后面要跟回放文件的路径")?.into()),
            "--from" => {
                let v = it.next().ok_or("--from 后面要跟秒数")?;
                args.from = Some(v.parse().map_err(|_| format!("--from 不是秒数：{v}"))?);
            }
            "-h" | "--help" => return Err(USAGE.into()),
            other => return Err(format!("不认识的参数：{other}\n{USAGE}")),
        }
    }
    Ok(args)
}

fn main() -> AppExit {
    if let Err(e) = diagnostics::init() {
        return fatal(&e);
    }
    let args = match parse_args() {
        Ok(a) => a,
        Err(msg) => return fatal(&msg),
    };
    let assets = paths::asset_dir();
    info!("资源目录：{}", assets.display());
    let content = match Content::load(&assets.join("data")) {
        Ok(c) => c,
        Err(e) => return fatal(&format!("内容数据有误：{e}")),
    };
    let playback = match &args.replay {
        Some(path) => {
            let text = match std::fs::read_to_string(path) {
                Ok(t) => t,
                Err(e) => return fatal(&format!("读取回放 {} 失败：{e}", path.display())),
            };
            let replay = match Replay::parse(&text) {
                Ok(r) => r,
                Err(e) => return fatal(&e),
            };
            if replay.content_hash != content.hash {
                warn!(
                    "注意：回放录制时的内容数据与当前不同（游戏版本 {}），重放结果可能不一致",
                    replay.game_version
                );
            }
            Some(ReplayPlayback::new(replay))
        }
        None => None,
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
            .disable::<bevy::log::LogPlugin>()
            .set(AssetPlugin { file_path: assets.to_string_lossy().into_owned(), ..default() }),
    )
    .insert_resource(Time::<Fixed>::from_hz(f64::from(TICK_HZ)))
    .insert_resource(GameContent(Arc::new(content)))
    .insert_resource(SeedOverride(args.seed))
    .insert_resource(Profile::load(&paths::data_dir()))
    .add_plugins((
        SimPlugin,
        PlatformPlugin { settings },
        ViewPlugin { asset_root: assets.clone() },
        AudioPlugin,
        UiPlugin,
    ));

    if let Some(p) = playback {
        app.insert_resource(p);
        if let Some(secs) = args.from {
            app.insert_resource(ReplaySeek(secs));
        }
    }

    // 一帧最多补 4 步：卡顿时宁可变慢，也不让模拟连续追赶。
    app.world_mut()
        .resource_mut::<Time<Virtual>>()
        .set_max_delta(Duration::from_secs_f64(f64::from(MAX_CATCHUP_TICKS) / f64::from(TICK_HZ)));
    app.run()
}
