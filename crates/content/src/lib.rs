//! 内容数据：结构定义、从 `assets/data/` 加载、校验。
//!
//! 游戏和命令行工具共用这一套结构。数据文件是 RON，错误信息会指出文件名和行列号。
//! 文件里用字符串 ID 互相引用，加载时检查引用是否存在；模拟开局时再换成数字下标。

use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};

mod defs;
mod effects;
mod validate;

pub use defs::*;
pub use effects::*;

/// 全部内容数据。
#[derive(Clone, Debug, PartialEq)]
pub struct Content {
    pub player: PlayerDef,
    /// 按 [`Stat::ALL`] 的顺序
    pub stats: Vec<StatDef>,
    pub run: RunDef,
    pub enemies: Vec<EnemyDef>,
    pub weapons: Vec<WeaponDef>,
    pub passives: Vec<PassiveDef>,
    pub elements: ElementsDef,
    pub omens: Vec<OmenDef>,
    pub events: EventsDef,
    pub meta: MetaDef,
    /// 精英词缀
    pub affixes: Vec<AffixDef>,
    /// 难度：一更、二更……
    pub difficulty: Vec<DifficultyDef>,
    pub attributes: AttributesDef,
    pub lamps: Vec<LampDef>,
    pub charms: Vec<CharmDef>,
    pub achievements: Vec<AchievementDef>,
    /// 灯驿人物的台词（纯文字，不计入内容哈希）
    pub hub: Vec<HubPersonDef>,
    /// 地区：名字、开场卷轴的旁白（纯文字，不计入内容哈希）
    pub regions: Vec<RegionDef>,
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
        let player = read(data_dir, "player.ron", &mut hash)?;
        let stats: BTreeMap<Stat, StatDef> = read(data_dir, "stats.ron", &mut hash)?;
        let missing: Vec<String> =
            Stat::ALL.iter().filter(|s| !stats.contains_key(s)).map(|s| format!("{s:?}")).collect();
        if !missing.is_empty() {
            return Err(ContentError::Invalid {
                file: data_dir.join("stats.ron"),
                msg: format!("缺少这些属性的定义：{}", missing.join("、")),
            });
        }
        let mut content = Content {
            player,
            stats: Stat::ALL.iter().map(|s| stats[s]).collect(),
            run: read(data_dir, "run.ron", &mut hash)?,
            enemies: read(data_dir, "enemies.ron", &mut hash)?,
            weapons: read(data_dir, "weapons.ron", &mut hash)?,
            passives: read(data_dir, "passives.ron", &mut hash)?,
            elements: read(data_dir, "elements.ron", &mut hash)?,
            omens: read(data_dir, "omens.ron", &mut hash)?,
            events: read(data_dir, "events.ron", &mut hash)?,
            meta: read(data_dir, "meta.ron", &mut hash)?,
            affixes: read(data_dir, "affixes.ron", &mut hash)?,
            difficulty: read(data_dir, "difficulty.ron", &mut hash)?,
            attributes: read(data_dir, "attributes.ron", &mut hash)?,
            lamps: read(data_dir, "lamps.ron", &mut hash)?,
            charms: read(data_dir, "charms.ron", &mut hash)?,
            achievements: read(data_dir, "achievements.ron", &mut hash)?,
            hub: read(data_dir, "hub.ron", &mut 0)?,
            regions: read(data_dir, "regions.ron", &mut 0)?,
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

    /// 心法 ID 对应的下标。
    pub fn passive_index(&self, id: &str) -> Option<usize> {
        self.passives.iter().position(|p| p.id == id)
    }

    pub fn omen_index(&self, id: &str) -> Option<usize> {
        self.omens.iter().position(|o| o.id == id)
    }

    pub fn lamp_index(&self, id: &str) -> Option<usize> {
        self.lamps.iter().position(|l| l.id == id)
    }

    pub fn charm_index(&self, id: &str) -> Option<usize> {
        self.charms.iter().position(|c| c.id == id)
    }

    pub fn stat(&self, s: Stat) -> StatDef {
        self.stats[s as usize]
    }

    pub fn element(&self, e: Element) -> &ElementDef {
        &self.elements.elements[e.index()]
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
        assert_eq!(c.stats.len(), Stat::COUNT);
        assert_eq!(c.stat(Stat::CritMult).base, 2.0);
        let luck = c.meta.node("luck").unwrap();
        assert_eq!((c.meta.cost(luck, 0), c.meta.cost(luck, 2), c.meta.cost(luck, 4)), (300, 770, 1970));
        let dmg = &c.attributes.list[0];
        assert_eq!((c.attributes.price(dmg, 0, 0), c.attributes.price(dmg, 9, 0)), (60, 600));
        assert_eq!(c.attributes.price(dmg, 1, 10), 145);
        assert_eq!(c.passives.len(), 17);
    }

    #[test]
    fn invalid_values_are_reported_with_file_name() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.player.dash.speed = -1.0;
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
    fn reactions_cover_every_pair() {
        let c = Content::load(&repo_data_dir()).unwrap();
        let el = &c.elements;
        for (i, &a) in Element::ALL.iter().enumerate() {
            for &b in &Element::ALL[i + 1..] {
                let r = el.reaction_between(a, b).unwrap_or_else(|| panic!("{a:?} + {b:?} 没有反应"));
                assert_eq!(el.reaction_between(b, a), Some(r));
                // 每一对五行要么相生、要么相克
                let sheng = el.sheng.iter().any(|s| (s.from, s.to) == (a, b) || (s.from, s.to) == (b, a));
                assert_ne!(sheng, a.overcomes(b) || b.overcomes(a), "{a:?} {b:?}");
            }
        }
        assert_eq!(el.weapon_points(1, false), 1);
        assert_eq!(el.weapon_points(4, false), 2);
        assert_eq!(el.weapon_points(8, false), 3);
        assert_eq!(el.weapon_points(8, true), 4);
        assert_eq!(el.passive_points(5), 3);
    }

    #[test]
    fn quad_curve() {
        let q = Quad(1.6, 1.1, 0.1);
        assert!((q.at(2.0) - (1.6 + 2.2 + 0.4)).abs() < 1e-6);
    }
}
