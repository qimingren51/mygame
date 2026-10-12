//! 内容数据：结构定义、从 `assets/data/` 加载、校验。
//!
//! 游戏和命令行工具共用这一套结构。数据文件是 RON，错误信息会指出文件名和行列号。

use std::fmt;
use std::path::{Path, PathBuf};

use serde::Deserialize;

/// 主角基础数值（`player.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlayerDef {
    pub radius: f32,
    pub speed: f32,
    pub max_hp: f32,
    pub magnet: f32,
    /// 受伤后的无敌时间
    pub hurt_iframe: f32,
    pub dash: DashDef,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DashDef {
    pub duration: f32,
    pub speed: f32,
    pub cooldown: f32,
    pub iframe: f32,
}

/// 单局节奏（`run.ron`）。
#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RunDef {
    pub duration: f32,
    pub view_height: f32,
    pub max_aspect: f32,
}

/// 全部内容数据。
#[derive(Clone, Debug, PartialEq)]
pub struct Content {
    pub player: PlayerDef,
    pub run: RunDef,
}

#[derive(Debug)]
pub enum ContentError {
    Io { file: PathBuf, err: std::io::Error },
    Parse { file: PathBuf, err: Box<ron::error::SpannedError> },
    Invalid { file: PathBuf, msg: String },
}

impl fmt::Display for ContentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ContentError::Io { file, err } => write!(f, "{}：读取失败：{err}", file.display()),
            ContentError::Parse { file, err } => write!(f, "{}:{}", file.display(), err),
            ContentError::Invalid { file, msg } => write!(f, "{}：{msg}", file.display()),
        }
    }
}

impl std::error::Error for ContentError {}

fn read<T: serde::de::DeserializeOwned>(dir: &Path, name: &str) -> Result<T, ContentError> {
    let file = dir.join(name);
    let text = std::fs::read_to_string(&file).map_err(|err| ContentError::Io { file: file.clone(), err })?;
    ron::from_str(&text).map_err(|err| ContentError::Parse { file, err: Box::new(err) })
}

impl Content {
    /// 从数据目录（通常是 `assets/data`）加载并校验全部内容。
    pub fn load(data_dir: &Path) -> Result<Content, ContentError> {
        let content = Content { player: read(data_dir, "player.ron")?, run: read(data_dir, "run.ron")? };
        content.validate(data_dir)?;
        Ok(content)
    }

    fn validate(&self, dir: &Path) -> Result<(), ContentError> {
        let fail = |name: &str, msg: String| Err(ContentError::Invalid { file: dir.join(name), msg });
        let p = &self.player;
        for (field, v) in [
            ("radius", p.radius),
            ("speed", p.speed),
            ("max_hp", p.max_hp),
            ("dash.duration", p.dash.duration),
            ("dash.speed", p.dash.speed),
        ] {
            if !(v.is_finite() && v > 0.0) {
                return fail("player.ron", format!("{field} 必须是正数，现在是 {v}"));
            }
        }
        for (field, v) in [
            ("magnet", p.magnet),
            ("hurt_iframe", p.hurt_iframe),
            ("dash.cooldown", p.dash.cooldown),
            ("dash.iframe", p.dash.iframe),
        ] {
            if !(v.is_finite() && v >= 0.0) {
                return fail("player.ron", format!("{field} 不能为负数，现在是 {v}"));
            }
        }
        let r = &self.run;
        if !(r.duration > 0.0 && r.view_height > 0.0 && r.max_aspect >= 1.0) {
            return fail("run.ron", "duration、view_height 必须为正，max_aspect 不能小于 1".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo_data_dir() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")
    }

    /// 仓库里的全部数据文件都必须能加载并通过校验。
    #[test]
    fn repo_content_is_valid() {
        let c = Content::load(&repo_data_dir()).unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(c.run.duration, 600.0);
    }

    #[test]
    fn invalid_values_are_reported_with_file_name() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.player.speed = -1.0;
        let err = c.validate(Path::new("data")).unwrap_err().to_string();
        assert!(err.contains("player.ron") && err.contains("speed"), "{err}");
    }

    #[test]
    fn unknown_fields_are_rejected() {
        let r: Result<RunDef, _> =
            ron::from_str("(duration: 1.0, view_height: 1.0, max_aspect: 2.0, typo: 3)");
        assert!(r.is_err());
    }
}
