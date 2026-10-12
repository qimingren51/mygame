//! 内容数据：结构定义、从 `assets/data/` 加载、校验。
//!
//! 游戏和命令行工具共用这一套结构。数据文件是 RON，错误信息会指出文件名和行列号。
//! 文件里用字符串 ID 互相引用，加载时检查引用是否存在；模拟开局时再换成数字下标。

use std::fmt;
use std::path::{Path, PathBuf};

mod defs;
mod validate;

pub use defs::*;

/// 全部内容数据。
#[derive(Clone, Debug, PartialEq)]
pub struct Content {
    pub player: PlayerDef,
    pub run: RunDef,
    pub enemies: Vec<EnemyDef>,
    pub weapons: Vec<WeaponDef>,
    /// 全部数据文件原文的哈希（FNV-1a）。回放只能在内容相同的版本上重放。
    pub hash: u64,
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

/// 读一个数据文件，同时把原文计入内容哈希。
fn read<T: serde::de::DeserializeOwned>(dir: &Path, name: &str, hash: &mut u64) -> Result<T, ContentError> {
    let file = dir.join(name);
    let text = std::fs::read_to_string(&file).map_err(|err| ContentError::Io { file: file.clone(), err })?;
    for b in name.bytes().chain(text.bytes()) {
        *hash ^= u64::from(b);
        *hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    ron::from_str(&text).map_err(|err| ContentError::Parse { file, err: Box::new(err) })
}

impl Content {
    /// 从数据目录（通常是 `assets/data`）加载并校验全部内容。
    pub fn load(data_dir: &Path) -> Result<Content, ContentError> {
        let mut hash = 0xcbf2_9ce4_8422_2325;
        let mut content = Content {
            player: read(data_dir, "player.ron", &mut hash)?,
            run: read(data_dir, "run.ron", &mut hash)?,
            enemies: read(data_dir, "enemies.ron", &mut hash)?,
            weapons: read(data_dir, "weapons.ron", &mut hash)?,
            hash: 0,
        };
        content.hash = hash;
        content.validate(data_dir)?;
        Ok(content)
    }

    /// 妖物 ID 对应的下标。
    pub fn enemy_index(&self, id: &str) -> Option<usize> {
        self.enemies.iter().position(|e| e.id == id)
    }

    /// 法器 ID 对应的下标。
    pub fn weapon_index(&self, id: &str) -> Option<usize> {
        self.weapons.iter().position(|w| w.id == id)
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
        assert!(c.enemy_index(&c.run.spawn.base).is_some());
        assert!(c.weapon_index(&c.player.start_weapon).is_some());
    }

    #[test]
    fn invalid_values_are_reported_with_file_name() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.player.speed = -1.0;
        let err = c.validate(Path::new("data")).unwrap_err().to_string();
        assert!(err.contains("player.ron") && err.contains("speed"), "{err}");
    }

    #[test]
    fn dangling_references_are_reported() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.run.spawn.mix[0].enemy = "no_such_enemy".into();
        let err = c.validate(Path::new("data")).unwrap_err().to_string();
        assert!(err.contains("run.ron") && err.contains("no_such_enemy"), "{err}");

        let mut c = Content::load(&repo_data_dir()).unwrap();
        let dup = c.enemies[0].clone();
        c.enemies.push(dup);
        let err = c.validate(Path::new("data")).unwrap_err().to_string();
        assert!(err.contains("enemies.ron") && err.contains("重复"), "{err}");
    }

    #[test]
    fn unknown_fields_are_rejected() {
        let r: Result<PlayerDef, _> = ron::from_str("(radius: 1.0, typo: 3)");
        assert!(r.is_err());
    }

    #[test]
    fn quad_curve() {
        let q = Quad(1.6, 1.1, 0.1);
        assert!((q.at(2.0) - (1.6 + 2.2 + 0.4)).abs() < 1e-6);
    }
}
