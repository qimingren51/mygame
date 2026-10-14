//! 提灯夜行：可执行程序。只负责组装各模块的插件，不写游戏逻辑（docs/DESIGN.md 第 4 节）。

// 发布版在 Windows 上不弹出控制台窗口。
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use std::ffi::OsString;
use std::path::{Path, PathBuf};
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

mod smoke;
#[cfg(target_os = "windows")]
mod window_icon;

const USAGE: &str = "用法：lantern [--seed <数字>] [--windowed] [--replay <回放文件> [--from <秒>]] [--smoke-test（无窗口运行 120 帧）]";

#[derive(Debug)]
struct Args {
    seed: Option<u64>,
    windowed: bool,
    replay: Option<PathBuf>,
    from: Option<u32>,
    smoke_test: bool,
}

fn parse_args(values: impl IntoIterator<Item = OsString>) -> Result<Args, String> {
    let mut args = Args { seed: None, windowed: false, replay: None, from: None, smoke_test: false };
    let mut it = values.into_iter();
    while let Some(a) = it.next() {
        match a.to_str() {
            Some("--seed") => {
                let v = it.next().ok_or("--seed 后面要跟一个数字")?;
                args.seed = Some(
                    v.to_str().and_then(|v| v.parse().ok()).ok_or_else(|| format!("种子不是数字：{v:?}"))?,
                );
            }
            Some("--windowed") => args.windowed = true,
            Some("--smoke-test") => args.smoke_test = true,
            Some("--replay") => {
                args.replay = Some(it.next().ok_or("--replay 后面要跟回放文件的路径")?.into())
            }
            Some("--from") => {
                let v = it.next().ok_or("--from 后面要跟秒数")?;
                args.from = Some(
                    v.to_str()
                        .and_then(|v| v.parse().ok())
                        .ok_or_else(|| format!("--from 不是秒数：{v:?}"))?,
                );
            }
            Some("-h" | "--help") => return Err(USAGE.into()),
            _ => return Err(format!("不认识的参数：{a:?}\n{USAGE}")),
        }
    }
    if args.smoke_test && (args.replay.is_some() || args.from.is_some()) {
        return Err("--smoke-test 不能与 --replay 或 --from 一起使用".into());
    }
    Ok(args)
}

fn asset_file_path(assets: &Path) -> Result<String, String> {
    // Bevy 的资源插件只接受 UTF-8；不能替换路径里的无效字符后去读取另一个目录。
    assets.to_str().map(str::to_owned).ok_or_else(|| {
        format!("资源目录不是有效的 UTF-8 路径：{assets:?}。请将程序和 assets 移到有效的 Unicode 路径下。")
    })
}

fn main() -> AppExit {
    let values: Vec<_> = std::env::args_os().skip(1).collect();
    // 参数出错也不能让自动化测试等候 Windows 弹窗。
    let headless = values.iter().any(|value| value == "--smoke-test");
    let logging = if headless { diagnostics::init_headless() } else { diagnostics::init() };
    if let Err(e) = logging {
        return fatal(&e);
    }
    let args = match parse_args(values) {
        Ok(a) => a,
        Err(msg) => return fatal(&msg),
    };
    let assets = match paths::asset_dir() {
        Ok(path) => path,
        Err(msg) => return fatal(&msg),
    };
    let file_path = match asset_file_path(&assets) {
        Ok(path) => path,
        Err(msg) => return fatal(&msg),
    };
    info!("资源目录：{}", assets.display());
    let content = match Content::load(&assets.join("data")) {
        Ok(c) => c,
        Err(e) => return fatal(&format!("内容数据有误：{e}")),
    };
    if args.smoke_test {
        return match smoke::run(&assets, file_path, content, args.seed.unwrap_or(0)) {
            Ok(()) => AppExit::Success,
            Err(e) => fatal(&format!("冒烟测试失败：{e}")),
        };
    }
    let playback = match &args.replay {
        Some(path) => {
            let text = match std::fs::read_to_string(path) {
                Ok(t) => t,
                Err(e) => return fatal(&format!("读取回放 {path:?} 失败：{e}")),
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
            .set(AssetPlugin { file_path, ..default() }),
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

    #[cfg(target_os = "windows")]
    app.add_systems(Update, window_icon::set_window_icon);

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_defaults_and_options() {
        let args = parse_args([]).unwrap();
        assert_eq!(args.seed, None);
        assert!(!args.windowed);
        assert_eq!(args.replay, None);
        assert_eq!(args.from, None);
        assert!(!args.smoke_test);

        let args = parse_args(
            ["--seed", "42", "--windowed", "--replay", "回放 目录/夜行.ron", "--from", "12"]
                .map(OsString::from),
        )
        .unwrap();
        assert_eq!(args.seed, Some(42));
        assert!(args.windowed);
        assert_eq!(args.replay, Some(PathBuf::from("回放 目录/夜行.ron")));
        assert_eq!(args.from, Some(12));
    }

    #[test]
    fn parses_smoke_test_with_seed_in_either_order() {
        assert!(parse_args(["--smoke-test".into()]).unwrap().smoke_test);
        for values in [["--smoke-test", "--seed", "42"], ["--seed", "42", "--smoke-test"]] {
            let args = parse_args(values.map(OsString::from)).unwrap();
            assert!(args.smoke_test);
            assert_eq!(args.seed, Some(42));
        }
        // 路径值不能被当作开关。
        let args = parse_args(["--replay", "--smoke-test"].map(OsString::from)).unwrap();
        assert!(!args.smoke_test);
        assert_eq!(args.replay, Some(PathBuf::from("--smoke-test")));
    }

    #[test]
    fn rejects_smoke_test_values_and_replay_options() {
        for values in [
            vec!["--smoke-test", "120"],
            vec!["--smoke-test=120"],
            vec!["--smoke-test", "--seed", "abc"],
            vec!["--smoke-test", "--replay", "回放.ron"],
            vec!["--from", "12", "--smoke-test"],
        ] {
            assert!(parse_args(values.into_iter().map(OsString::from)).is_err());
        }
    }

    #[test]
    fn rejects_missing_and_invalid_arguments() {
        for args in [
            vec!["--seed"],
            vec!["--replay"],
            vec!["--from"],
            vec!["--seed", "abc"],
            vec!["--from", "-1"],
            vec!["--unknown"],
        ] {
            assert!(parse_args(args.into_iter().map(OsString::from)).is_err());
        }
        assert_eq!(parse_args(["--help".into()]).unwrap_err(), USAGE);
    }

    #[test]
    fn preserves_unicode_asset_path() {
        let path = "游戏 目录/assets";
        assert_eq!(asset_file_path(Path::new(path)).unwrap(), path);
    }

    #[test]
    #[cfg(unix)]
    fn preserves_non_utf8_replay_path_and_rejects_non_utf8_text() {
        use std::ffi::OsStr;
        use std::os::unix::ffi::OsStrExt;

        let path = OsStr::from_bytes(b"replays/\xff night.ron");
        let args = parse_args(["--replay".into(), path.to_owned(), "--windowed".into()]).unwrap();
        assert_eq!(args.replay.as_deref(), Some(Path::new(path)));
        assert!(args.windowed);
        for flag in ["--seed", "--from"] {
            assert!(parse_args([flag.into(), path.to_owned()]).is_err());
        }
        let error = parse_args([path.to_owned()]).unwrap_err();
        assert!(error.contains("不认识的参数"));
        assert!(!error.contains('\u{fffd}'));
    }

    #[test]
    #[cfg(unix)]
    fn rejects_non_utf8_asset_path_without_replacement() {
        use std::ffi::OsStr;
        use std::os::unix::ffi::OsStrExt;

        let error = asset_file_path(Path::new(OsStr::from_bytes(b"game/\xff/assets"))).unwrap_err();
        assert!(error.contains("资源目录不是有效的 UTF-8 路径"));
        assert!(error.contains("\\xFF"));
        assert!(!error.contains('\u{fffd}'));
    }

    #[test]
    #[cfg(windows)]
    fn preserves_unpaired_surrogate_in_replay_path_and_rejects_it_in_assets() {
        use std::os::windows::ffi::OsStringExt;

        let path = OsString::from_wide(&[b'n' as u16, 0xd800, b'.' as u16, b'r' as u16]);
        let args = parse_args(["--replay".into(), path.clone()]).unwrap();
        assert_eq!(args.replay.as_deref(), Some(Path::new(&path)));
        assert!(asset_file_path(Path::new(&path)).unwrap_err().contains("不是有效的 UTF-8 路径"));
        for flag in ["--seed", "--from"] {
            assert!(parse_args([flag.into(), path.clone()]).is_err());
        }
    }
}
