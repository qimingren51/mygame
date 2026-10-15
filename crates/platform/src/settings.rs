//! 设置文件 `settings.ron`。带版本号；写入时先写临时文件再改名，并保留上一份备份。

use std::io;
use std::path::{Path, PathBuf};

use bevy::prelude::Resource;
use serde::{Deserialize, Serialize};

pub const SETTINGS_VERSION: u32 = 2;

#[derive(Resource, Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub version: u32,
    pub fullscreen: bool,
    pub vsync: bool,
    /// 0–1
    pub music_volume: f32,
    /// 0–1
    pub sfx_volume: f32,
    /// 震屏、镜头冲击和手柄震动的强度，0–1（0 为关）
    pub shake: f32,
    /// 顿帧与慢镜
    pub hitstop: bool,
    /// 辉光
    pub bloom: bool,
    /// 精简特效：粒子减半，不画环境萤火、夜雾和色散（配置低的机器用）
    pub lite_fx: bool,
    pub bindings: crate::bindings::Bindings,
    /// 允许用 F3 查看种子号和性能面板；面板仍由玩家主动打开。
    pub debug_tools: bool,
    #[serde(skip)]
    path: Option<PathBuf>,
    #[serde(skip)]
    save_error: Option<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            version: SETTINGS_VERSION,
            fullscreen: false,
            vsync: true,
            music_volume: 0.8,
            sfx_volume: 0.8,
            shake: 1.0,
            hitstop: true,
            bloom: true,
            lite_fx: false,
            bindings: Default::default(),
            debug_tools: false,
            path: None,
            save_error: None,
        }
    }
}

impl Settings {
    pub fn debug_tools_enabled(&self) -> bool {
        cfg!(feature = "dev") || self.debug_tools
    }

    /// 主文件不可用时尝试备份；无法安全恢复时禁止覆盖原文件。
    pub fn load(dir: &Path) -> Settings {
        let path = dir.join("settings.ron");
        let (mut s, error) = load_with_backup::<Settings>(&path);
        s.save_error = error;
        s.bindings.validate();
        s.version = SETTINGS_VERSION;
        s.path = Some(path);
        s
    }

    pub fn save(&self) -> io::Result<()> {
        if let Some(error) = &self.save_error {
            return Err(io::Error::other(error.clone()));
        }
        let Some(path) = &self.path else { return Ok(()) };
        let text =
            ron::ser::to_string_pretty(self, ron::ser::PrettyConfig::default()).map_err(io::Error::other)?;
        write_atomic(path, text.as_bytes())
    }
}

/// 区分首次运行和恢复失败。恢复备份后先保留坏主档，后续写入不会把坏数据复制进备份。
pub(crate) fn load_with_backup<T: serde::de::DeserializeOwned + Default>(path: &Path) -> (T, Option<String>) {
    let read = |path: &Path| -> io::Result<T> {
        let text = std::fs::read_to_string(path)?;
        ron::from_str(&text).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    };
    let main_error = match read(path) {
        Ok(value) => return (value, None),
        Err(e) => e,
    };
    let backup = path.with_extension("bak");
    match read(&backup) {
        Ok(value) => {
            eprintln!("{} 读取失败（{main_error}），已读取备份 {}", path.display(), backup.display());
            let preserved = match main_error.kind() {
                io::ErrorKind::NotFound => Ok(()),
                io::ErrorKind::InvalidData => {
                    let broken = path.with_extension("ron.broken");
                    if broken.exists() {
                        Err(io::Error::other("已有损坏文件留档，暂不覆盖"))
                    } else {
                        std::fs::rename(path, broken)
                    }
                }
                _ => Err(main_error),
            };
            let error =
                preserved.err().map(|e| format!("无法保留原文件 {}，已禁止保存：{e}", path.display()));
            if let Some(e) = &error {
                eprintln!("{e}");
            }
            (value, error)
        }
        Err(e) if main_error.kind() == io::ErrorKind::NotFound && e.kind() == io::ErrorKind::NotFound => {
            (T::default(), None)
        }
        Err(e) => {
            let error = format!("{} 及备份均无法读取，已禁止保存：{main_error}；{e}", path.display());
            eprintln!("{error}");
            (T::default(), Some(error))
        }
    }
}

/// 先写 `<文件>.tmp`，再改名替换；原文件保留为 `<文件>.bak`。断电或崩溃不会留下写了一半的文件。
pub fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, bytes)?;
    if path.exists() {
        let _ = std::fs::copy(path, path.with_extension("bak"));
    }
    std::fs::rename(&tmp, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backup_recovery_preserves_progress_and_blocks_io_failures() {
        for problem in ["corrupt", "missing", "unreadable", "both_corrupt"] {
            let dir = std::env::temp_dir().join(format!("lantern-settings-{problem}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            let main = dir.join("settings.ron");
            let backup = dir.join("settings.bak");
            let good = "(fullscreen: true)";
            std::fs::write(&backup, if problem == "both_corrupt" { "broken" } else { good }).unwrap();
            match problem {
                "unreadable" => std::fs::create_dir(&main).unwrap(),
                "corrupt" | "both_corrupt" => std::fs::write(&main, "broken").unwrap(),
                _ => {}
            }
            let mut s = Settings::load(&dir);
            assert_eq!(s.fullscreen, problem != "both_corrupt");
            s.vsync = false;
            if problem == "unreadable" || problem == "both_corrupt" {
                assert!(s.save().is_err());
                if problem == "unreadable" {
                    assert!(main.is_dir());
                } else {
                    assert_eq!(std::fs::read_to_string(&main).unwrap(), "broken");
                }
            } else {
                s.save().unwrap();
                assert!(!Settings::load(&dir).vsync);
                if problem == "corrupt" {
                    assert_eq!(std::fs::read_to_string(dir.join("settings.ron.broken")).unwrap(), "broken");
                }
            }
            assert_eq!(
                std::fs::read_to_string(&backup).unwrap(),
                if problem == "both_corrupt" { "broken" } else { good }
            );
            std::fs::remove_dir_all(dir).unwrap();
        }
    }

    #[test]
    fn bindings_survive_save_reload_and_old_settings_gain_defaults() {
        use crate::bindings::Action;
        use bevy::prelude::{GamepadButton, KeyCode};
        let dir = std::env::temp_dir().join(format!("lantern-bindings-test-{}", std::process::id()));
        let mut settings = Settings::load(&dir);
        settings.bindings.bind_key(Action::Dash, KeyCode::KeyJ).unwrap();
        settings.bindings.bind_button(Action::Ult, GamepadButton::RightTrigger2).unwrap();
        settings.save().unwrap();
        assert_eq!(Settings::load(&dir).bindings, settings.bindings);
        std::fs::write(dir.join("settings.ron"), "(version: 1, music_volume: 0.4)").unwrap();
        let old = Settings::load(&dir);
        assert_eq!(old.version, SETTINGS_VERSION);
        assert_eq!(old.music_volume, 0.4);
        assert_eq!(old.bindings.key(Action::Dash), KeyCode::Space);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn roundtrip_and_recover_from_corruption() {
        let dir = std::env::temp_dir().join(format!("lantern-settings-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        let mut s = Settings::load(&dir);
        assert_eq!(s, Settings { path: Some(dir.join("settings.ron")), ..Settings::default() });
        s.fullscreen = true;
        s.debug_tools = true;
        s.save().unwrap();
        assert!(Settings::load(&dir).fullscreen);
        assert!(Settings::load(&dir).debug_tools);

        std::fs::write(dir.join("settings.ron"), "(fullscreen: maybe").unwrap();
        let broken = Settings::load(&dir);
        assert!(!broken.fullscreen);
        assert!(broken.save().is_err());
        assert_eq!(std::fs::read_to_string(dir.join("settings.ron")).unwrap(), "(fullscreen: maybe");

        // 缺字段时用默认值，旧版本的设置文件也能读。
        std::fs::write(dir.join("settings.ron"), "(fullscreen: true)").unwrap();
        let s = Settings::load(&dir);
        assert!(s.fullscreen && s.vsync);
        assert!(!s.debug_tools);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
