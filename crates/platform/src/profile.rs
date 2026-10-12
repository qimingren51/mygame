//! 存档 `save.ron`：灯油、心灯等级、最好成绩（docs/DESIGN.md 第 12 节）。
//!
//! 和设置文件一样带版本号、原子写入、保留备份；文件损坏时改名保留，改用空存档。

use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};

use bevy::prelude::Resource;
use serde::{Deserialize, Serialize};

use crate::settings::write_atomic;

pub const SAVE_VERSION: u32 = 1;

/// 最好成绩。
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Best {
    /// 最长存活（秒）
    pub seconds: f32,
    pub kills: u32,
    /// 是否迎来过天明
    pub won: bool,
}

#[derive(Resource, Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Profile {
    pub version: u32,
    /// 可以花的灯油
    pub oil: u32,
    /// 累计得到的灯油
    pub oil_total: u32,
    /// 心灯各系的等级（按 `meta.ron` 的 ID）
    pub meta: BTreeMap<String, u32>,
    pub best: Best,
    pub runs: u32,
    pub wins: u32,
    #[serde(skip)]
    path: Option<PathBuf>,
}

impl Default for Profile {
    fn default() -> Self {
        Profile {
            version: SAVE_VERSION,
            oil: 0,
            oil_total: 0,
            meta: BTreeMap::new(),
            best: Best::default(),
            runs: 0,
            wins: 0,
            path: None,
        }
    }
}

/// 一局结束时记进存档的东西。
#[derive(Clone, Copy, Debug)]
pub struct RunRecord {
    pub won: bool,
    pub seconds: f32,
    pub kills: u32,
    pub oil: u32,
}

/// 这一局刷新了哪项记录。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NewRecord {
    FirstDawn,
    Kills,
    Survival,
}

impl Profile {
    pub fn load(dir: &Path) -> Profile {
        let path = dir.join("save.ron");
        let mut p = match std::fs::read_to_string(&path) {
            Ok(text) => match ron::from_str::<Profile>(&text) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("存档损坏，改用空存档（原文件改名为 save.ron.broken）：{e}");
                    let _ = std::fs::rename(&path, path.with_extension("ron.broken"));
                    Profile::default()
                }
            },
            Err(_) => Profile::default(),
        };
        p.version = SAVE_VERSION;
        p.path = Some(path);
        p
    }

    pub fn save(&self) -> io::Result<()> {
        let Some(path) = &self.path else { return Ok(()) };
        let text =
            ron::ser::to_string_pretty(self, ron::ser::PrettyConfig::default()).map_err(io::Error::other)?;
        write_atomic(path, text.as_bytes())
    }

    pub fn meta_level(&self, id: &str) -> u32 {
        self.meta.get(id).copied().unwrap_or(0)
    }

    /// 花灯油点亮一级心灯。灯油不够时返回 false。
    pub fn buy_meta(&mut self, id: &str, cost: u32, max_level: u32) -> bool {
        let lv = self.meta_level(id);
        if lv >= max_level || self.oil < cost {
            return false;
        }
        self.oil -= cost;
        self.meta.insert(id.to_string(), lv + 1);
        true
    }

    /// 记下一局的结果，返回刷新的记录（同时刷新几项时按 天明 > 击杀 > 存活 取一项）。
    pub fn record(&mut self, r: RunRecord) -> Option<NewRecord> {
        let b = &mut self.best;
        let new = if r.won && !b.won {
            Some(NewRecord::FirstDawn)
        } else if r.kills > b.kills {
            Some(NewRecord::Kills)
        } else if r.seconds > b.seconds && !r.won {
            Some(NewRecord::Survival)
        } else {
            None
        };
        b.seconds = b.seconds.max(r.seconds);
        b.kills = b.kills.max(r.kills);
        b.won |= r.won;
        self.oil += r.oil;
        self.oil_total += r.oil;
        self.runs += 1;
        self.wins += u32::from(r.won);
        new
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn records_buys_and_roundtrips() {
        let dir = std::env::temp_dir().join(format!("lantern-save-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut p = Profile::load(&dir);
        assert_eq!(p.oil, 0);
        let rec = |won, seconds, kills, oil| RunRecord { won, seconds, kills, oil };
        assert_eq!(p.record(rec(false, 200.0, 500, 250)), Some(NewRecord::Kills));
        assert_eq!(p.record(rec(false, 210.0, 100, 210)), Some(NewRecord::Survival));
        assert_eq!(p.record(rec(true, 600.0, 7000, 1300)), Some(NewRecord::FirstDawn));
        assert_eq!(p.oil, 1760);
        assert!(p.buy_meta("dmg", 120, 5));
        assert!(!p.buy_meta("dmg", 99_999, 5));
        assert_eq!(p.meta_level("dmg"), 1);
        p.save().unwrap();
        let q = Profile::load(&dir);
        assert_eq!((q.oil, q.meta_level("dmg"), q.runs, q.wins), (1640, 1, 3, 1));
        assert!(q.best.won && q.best.kills == 7000);

        std::fs::write(dir.join("save.ron"), "(oil: lots").unwrap();
        assert_eq!(Profile::load(&dir).oil, 0);
        assert!(dir.join("save.ron.broken").exists());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
