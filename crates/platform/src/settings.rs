//! 设置文件 `settings.ron`。带版本号；写入时先写临时文件再改名，并保留上一份备份。

use std::io;
use std::path::{Path, PathBuf};

use bevy::prelude::Resource;
use serde::{Deserialize, Serialize};

pub const SETTINGS_VERSION: u32 = 1;

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
    #[serde(skip)]
    path: Option<PathBuf>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            version: SETTINGS_VERSION,
            fullscreen: false,
            vsync: true,
            music_volume: 0.8,
            sfx_volume: 0.8,
            path: None,
        }
    }
}

impl Settings {
    /// 从数据目录读取。文件不存在或已损坏时用默认值（损坏的文件会先改名保留）。
    pub fn load(dir: &Path) -> Settings {
        let path = dir.join("settings.ron");
        let mut s = match std::fs::read_to_string(&path) {
            Ok(text) => match ron::from_str::<Settings>(&text) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("设置文件损坏，改用默认值：{e}");
                    let _ = std::fs::rename(&path, path.with_extension("ron.broken"));
                    Settings::default()
                }
            },
            Err(_) => Settings::default(),
        };
        s.version = SETTINGS_VERSION;
        s.path = Some(path);
        s
    }

    pub fn save(&self) -> io::Result<()> {
        let Some(path) = &self.path else { return Ok(()) };
        let text =
            ron::ser::to_string_pretty(self, ron::ser::PrettyConfig::default()).map_err(io::Error::other)?;
        write_atomic(path, text.as_bytes())
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
    fn roundtrip_and_recover_from_corruption() {
        let dir = std::env::temp_dir().join(format!("lantern-settings-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);

        let mut s = Settings::load(&dir);
        assert_eq!(s, Settings { path: Some(dir.join("settings.ron")), ..Settings::default() });
        s.fullscreen = true;
        s.save().unwrap();
        assert!(Settings::load(&dir).fullscreen);

        std::fs::write(dir.join("settings.ron"), "(fullscreen: maybe").unwrap();
        assert!(!Settings::load(&dir).fullscreen);
        assert!(dir.join("settings.ron.broken").exists());

        // 缺字段时用默认值，旧版本的设置文件也能读。
        std::fs::write(dir.join("settings.ron"), "(fullscreen: true)").unwrap();
        let s = Settings::load(&dir);
        assert!(s.fullscreen && s.vsync);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
