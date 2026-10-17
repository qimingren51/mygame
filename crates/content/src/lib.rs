//! 内容数据：结构定义、从 `assets/data/` 加载、校验。
//!
//! 游戏和命令行工具共用这一套结构。数据文件是 RON，错误信息会指出文件名和行列号。
//! 文件里用字符串 ID 互相引用，加载时检查引用是否存在；模拟开局时再换成数字下标。

use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};

mod defs;
mod effects;
mod identity;
mod validate;

pub use defs::*;
pub use effects::*;
pub use identity::WeaponIdentity;

/// 全部内容数据。
#[derive(Clone, Debug, PartialEq)]
pub struct Content {
    pub player: PlayerDef,
    /// 按 [`Stat::ALL`] 的顺序
    pub stats: Vec<StatDef>,
    pub run: RunDef,
    pub enemies: Vec<EnemyDef>,
    pub weapons: Vec<WeaponDef>,
    pub fusions: Vec<FusionDef>,
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
    /// 守灯人手记（纯文字，不计入内容哈希）。
    pub journals: Vec<JournalDef>,
    /// 局内属性面板的分组和标签（只有文字，不计入哈希）
    pub stat_labels: Vec<StatGroupDef>,
    /// 玩法数据文件原文的哈希（FNV-1a）。回放只能在玩法内容相同的版本上重放。
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
            fusions: read(data_dir, "fusions.ron", &mut hash)?,
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
            journals: read(data_dir, "journals.ron", &mut 0)?,
            stat_labels: read(data_dir, "stat_labels.ron", &mut 0)?,
            hash: 0,
        };
        content.hash = hash;
        content.validate(data_dir)?;
        Ok(content)
    }

    /// 属性的图标名（`stat_labels.ron` 的 icon，帧名是 `ui/stat_<icon>`）；没写的是 None。
    pub fn stat_icon(&self, stat: Stat) -> Option<&str> {
        self.stat_labels
            .iter()
            .flat_map(|g| &g.stats)
            .find(|l| l.stat == stat && !l.icon.is_empty())
            .map(|l| l.icon.as_str())
    }

    /// 解锁法器（`choices.locked` 里的 ID；`None` 是全部）。工具、测试用；内容哈希跟着变。
    pub fn unlock(&mut self, ids: Option<&[&str]>) {
        let before = self.run.choices.locked.len();
        self.run.choices.locked.retain(|id| ids.is_some_and(|ids| !ids.contains(&id.as_str())));
        if self.run.choices.locked.len() != before {
            self.hash = (self.hash ^ 0x756e_6c6f_636b_0000 ^ self.run.choices.locked.len() as u64)
                .wrapping_mul(0x0000_0100_0000_01b3);
        }
    }

    /// 命令行的 `--unlock all|<法器 ID>,…`：kite 跑局和游戏看回放共用，同样的参数得到同样的内容哈希，
    /// kite 带 `--unlock` 录的回放在游戏里带同样的参数就能看。
    pub fn unlock_arg(&mut self, arg: &str) -> Result<(), String> {
        if arg == "all" {
            self.unlock(None);
            return Ok(());
        }
        let ids: Vec<&str> = arg.split(',').map(str::trim).collect();
        if let Some(bad) = ids.iter().find(|id| !self.run.choices.locked.iter().any(|l| l == *id)) {
            return Err(format!("--unlock：\"{bad}\" 不在 run.ron 的 choices.locked 里"));
        }
        self.unlock(Some(&ids));
        Ok(())
    }

    /// 法器 d 是否还锁着（只看数据；存档解锁的由调用方另外排除）。
    pub fn weapon_locked(&self, d: usize) -> bool {
        self.run.choices.locked.iter().any(|id| *id == self.weapons[d].id)
    }

    /// 法器 d 的进化心法（异化共用同一门）。
    pub fn weapon_key(&self, d: usize) -> Option<usize> {
        self.weapons[d].evolution.as_ref().and_then(|e| self.passive_index(&e.passive))
    }

    /// 打开异化与合璧（EA 内容，`run.ron` 里默认关闭）。工具、测试用；内容哈希跟着变，
    /// 打开时录下的回放不会在关着开关的版本上重放。
    pub fn enable_transformations(&mut self) {
        if !self.run.transformations {
            self.run.transformations = true;
            self.hash = (self.hash ^ 0x7472_616e_7366_6f72).wrapping_mul(0x0000_0100_0000_01b3);
        }
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
        assert_eq!((c.meta.cost(luck, 0), c.meta.cost(luck, 2), c.meta.cost(luck, 4)), (200, 800, 3200));
        let dmg = &c.attributes.list[0];
        assert_eq!((c.attributes.price(dmg, 0, 0), c.attributes.price(dmg, 9, 0)), (60, 600));
        assert_eq!(c.attributes.price(dmg, 1, 10), 145);
        assert_eq!(c.passives.len(), 17);
    }

    /// 法器、进化、心法都要有卡片上的一句话（docs/LORE-TEXT.md 3.5、3.6 节）。
    #[test]
    fn weapons_and_passives_have_flavor() {
        let c = Content::load(&repo_data_dir()).unwrap();
        for w in &c.weapons {
            assert!(!w.flavor.is_empty(), "法器 {} 没写 flavor", w.id);
            if let Some(evo) = &w.evolution {
                assert!(!evo.flavor.is_empty(), "进化 {} 没写 flavor", evo.name);
            }
        }
        for p in &c.passives {
            assert!(!p.flavor.is_empty(), "心法 {} 没写 flavor", p.id);
        }
    }

    #[test]
    fn invalid_values_are_reported_with_file_name() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.player.dash.speed = -1.0;
        let err = c.validate(Path::new("data")).unwrap_err().to_string();
        assert!(err.contains("player.ron") && err.contains("speed"), "{err}");
    }

    #[test]
    fn boss_warning_durations_and_angles_must_be_valid() {
        for value in [0.0, -0.1, f32::NAN, f32::INFINITY] {
            for field in ["volley_warn", "sweep.warn", "rain.warn", "sweep.angle"] {
                let mut c = Content::load(&repo_data_dir()).unwrap();
                let b = c.enemies.iter_mut().find_map(|e| e.boss.as_mut()).unwrap();
                match field {
                    "volley_warn" => b.volley_warn = value,
                    "sweep.warn" => b.sweep.as_mut().unwrap().warn = value,
                    "rain.warn" => b.rain.as_mut().unwrap().warn = value,
                    _ => b.sweep.as_mut().unwrap().angle = value,
                }
                let error = c.validate(Path::new("data")).unwrap_err().to_string();
                assert!(error.contains(field), "{error}");
            }
        }
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.enemies.iter_mut().find_map(|e| e.boss.as_mut()).unwrap().sweep.as_mut().unwrap().angle = 7.0;
        assert!(c.validate(Path::new("data")).is_err());
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
    fn stat_labels_cover_every_stat_once_and_format_values() {
        let c = Content::load(&repo_data_dir()).unwrap();
        let listed: usize = c.stat_labels.iter().map(|g| g.stats.len()).sum();
        // 灯焰带倍率并进灯焰带
        assert_eq!(listed + 1, Stat::COUNT);
        assert!(c.stat_labels[0].always && c.stat_labels[0].stats.len() == 12);
        let mut bad = c.clone();
        bad.stat_labels[1].stats.pop();
        assert!(bad.validate(Path::new("data")).unwrap_err().to_string().contains("stat_labels.ron"));
        let mut bad = c.clone();
        bad.stat_labels[0].stats[0].hint = "一二三四五六七八九十一二三四五六七".into();
        assert!(bad.validate(Path::new("data")).unwrap_err().to_string().contains("stat_labels.ron"));
        let mut bad = c.clone();
        bad.stat_labels[0].stats[0].label = "命".into();
        assert!(bad.validate(Path::new("data")).unwrap_err().to_string().contains("stat_labels.ron"));
        // 基础 12 项和每组都有图标；图标名不能带路径
        assert!(c.stat_labels[0].stats.iter().all(|l| !l.icon.is_empty()));
        assert!(c.stat_labels.iter().all(|g| !g.icon.is_empty()));
        assert_eq!(c.stat_icon(Stat::Speed), Some("speed"));
        assert_eq!(c.stat_icon(Stat::LotusHeal), None);
        let mut bad = c.clone();
        bad.stat_labels[0].stats[0].icon = "../health".into();
        assert!(bad.validate(Path::new("data")).unwrap_err().to_string().contains("stat_labels.ron"));
        use StatFormat::*;
        for (f, v, shown) in [
            (Number, 120.0, "120"),
            (Number, 2.5, "2.5"),
            (PerSecond, 0.2, "0.2/秒"),
            (Multiplier, 1.2, "+20%"),
            (Multiplier, 0.94, "-6%"),
            (Multiplier, 1.0, "+0%"),
            (Multiplier, 1.005, "+0.5%"),
            (Number, 131.3, "131"),
            (PercentChange, -0.0001, "+0%"),
            (Percent, 0.05, "5%"),
            (PercentChange, 0.1, "+10%"),
            (PercentChange, -0.1, "-10%"),
            (PercentPerSecond, 0.01, "1%/秒"),
            (Times, 2.2, "×2.2"),
            (Count, 3.0, "3"),
            (CountChange, 1.0, "+1"),
            (Seconds, 2.4, "2.4 秒"),
            (Rank, 0.0, "无"),
            (Rank, 2.0, "2 级"),
            (Flag, 1.0, "有"),
        ] {
            assert_eq!(f.show(v), shown, "{f:?} {v}");
        }
        assert_eq!(Number.delta(20.0), "+20");
        assert_eq!(Multiplier.delta(0.1), "+10%");
        assert_eq!(Seconds.delta(-0.24), "-0.24 秒");
    }

    #[test]
    fn journals_and_story_conditions_are_validated() {
        let mut c = Content::load(&repo_data_dir()).unwrap();
        assert_eq!(c.journals.len(), 30);
        assert!(c.journals[12].text.contains("狐村"));
        assert!(c.journals[25].text.contains("一千年"));
        c.journals[0].page = 2;
        assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("journals.ron"));
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.hub[2].lines[0].when = HubWhen::All(vec![HubWhen::Story("typo".into())]);
        assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("hub.ron"));
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.hub[2].lines[0].when = HubWhen::JournalCount(31);
        assert!(c.validate(Path::new("data")).is_err());
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
    fn mutation_and_fusion_catalog_is_complete_and_validated() {
        let c = Content::load(&repo_data_dir()).unwrap();
        assert_eq!(c.fusions.len(), 3);
        for id in ["lamp", "sword", "bell", "crane", "seal"] {
            assert!(c.weapons[c.weapon_index(id).unwrap()].mutation.is_some());
        }
        let bad = |c: &Content, file: &str| {
            assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains(file))
        };
        let mut missing = c.clone();
        missing.fusions[0].weapons[0] = "不存在".into();
        bad(&missing, "fusions.ron");
        // 纸鹤（木）克山印（土），不相生
        let mut ke = c.clone();
        ke.fusions[0].weapons = ["crane".into(), "seal".into()];
        bad(&ke, "fusions.ron");
        // 合璧的行为要和第一件材料同一种
        let mut kind = c.clone();
        kind.fusions[0].weapons = ["lamp".into(), "crane".into()];
        bad(&kind, "fusions.ron");
        let mut duplicate = c.clone();
        duplicate.fusions.push(c.fusions[0].clone());
        bad(&duplicate, "fusions.ron");
        let mut mutation = c.clone();
        mutation.weapons[0].mutation = None;
        bad(&mutation, "weapons.ron");
        let mut invalid = c.clone();
        invalid.fusions[0].level.damage = f32::NAN;
        bad(&invalid, "fusions.ron");
        let unknown: Result<WeaponBehavior, _> =
            ron::from_str("Pulse(knockback: 0.0, slow: 0.2, slow_time: 1.0, typo: true)");
        assert!(unknown.is_err());
    }

    #[test]
    fn transformations_are_on_and_the_flag_still_switches() {
        let c = Content::load(&repo_data_dir()).unwrap();
        assert!(c.run.transformations, "试玩第 1 轮起默认打开（docs/PLAYTEST.md 第 6 项）");
        let text = std::fs::read_to_string(repo_data_dir().join("run.ron")).unwrap();
        let without: String = text
            .lines()
            .filter(|l| !l.trim_start().starts_with("transformations:"))
            .collect::<Vec<_>>()
            .join("\n");
        assert!(!ron::from_str::<RunDef>(&without).unwrap().transformations, "不写开关时关闭");
        let off = text.replace("transformations: true", "transformations: false");
        assert!(!ron::from_str::<RunDef>(&off).unwrap().transformations);
        let mut off = c.clone();
        off.run.transformations = false;
        let mut enabled = off.clone();
        enabled.enable_transformations();
        assert!(enabled.run.transformations);
        assert_ne!(enabled.hash, off.hash, "打开开关后的回放不能在关着的内容上重放");
        let mut cap = c.clone();
        cap.run.ground_cap = 0;
        assert!(cap.validate(Path::new("data")).unwrap_err().to_string().contains("run.ron"));
        let mut after = c.clone();
        after.run.choices.pity.key_guarantee_after = -1.0;
        assert!(after.validate(Path::new("data")).unwrap_err().to_string().contains("run.ron"));
    }

    #[test]
    fn mutation_fusion_fields_are_validated() {
        let c = Content::load(&repo_data_dir()).unwrap();
        for w in c.weapons.iter().filter_map(|w| w.mutation.as_ref()) {
            assert!(!w.flavor.is_empty(), "{} 缺一句话描述", w.name);
        }
        for f in &c.fusions {
            assert!(!f.flavor.is_empty(), "{} 缺一句话描述", f.name);
        }
        let mutation = |id: &str| c.weapon_index(id).unwrap();
        let bad = |edit: &dyn Fn(&mut Content), file: &str| {
            let mut c = c.clone();
            edit(&mut c);
            let err = c.validate(Path::new("data")).unwrap_err().to_string();
            assert!(err.contains(file), "{err}");
        };
        let behavior = |c: &Content, id: &str| -> WeaponBehavior {
            c.weapons[mutation(id)].mutation.as_ref().unwrap().behavior.clone()
        };
        let set = |c: &mut Content, id: &str, b: WeaponBehavior| {
            c.weapons[mutation(id)].mutation.as_mut().unwrap().behavior = b;
        };
        // 竹墙倍率在 (0, 1]
        for w in [0.0, 1.5, f32::NAN] {
            bad(
                &|c| {
                    let mut b = behavior(c, "seal");
                    if let WeaponBehavior::Drop { fissure: Some(f), .. } = &mut b {
                        f.wall = Some(w);
                    }
                    set(c, "seal", b);
                },
                "weapons.ron",
            );
        }
        // 铁羽：穿透至少 1，倍率在 (0, 1]
        for (pierce, ratio) in [(0, 0.5), (5, 0.0), (5, 1.5)] {
            bad(
                &|c| {
                    let mut b = behavior(c, "crane");
                    if let WeaponBehavior::Seeker { feather: Some(f), .. } = &mut b {
                        f.pierce = pierce;
                        f.ratio = ratio;
                    }
                    set(c, "crane", b);
                },
                "weapons.ron",
            );
        }
        // 分剑数量 1–8、倍率在 (0, 1]
        for (count, ratio) in [(0, 0.6), (9, 0.6), (2, 0.0)] {
            bad(
                &|c| {
                    let mut b = behavior(c, "sword");
                    if let WeaponBehavior::Volley { molten: Some(m), .. } = &mut b
                        && let Some(s) = &mut m.split
                    {
                        s.count = count;
                        s.ratio = ratio;
                    }
                    set(c, "sword", b);
                },
                "weapons.ron",
            );
        }
        // 冻土每步碎裂至少一次
        bad(
            &|c| {
                let mut b = behavior(c, "bell");
                if let WeaponBehavior::Pulse { permafrost: Some(p), .. } = &mut b {
                    p.shatter_budget = 0;
                }
                set(c, "bell", b);
            },
            "weapons.ron",
        );
        // 冰火：冻结、点燃不能为负
        bad(
            &|c| {
                let mut b = behavior(c, "lamp");
                if let WeaponBehavior::Orbit { ice_fire: Some(f), .. } = &mut b {
                    f.freeze = -1.0;
                }
                set(c, "lamp", b);
            },
            "weapons.ron",
        );
        // 异化的行为要和原法器同一种
        bad(
            &|c| {
                let b = behavior(c, "crane");
                set(c, "lamp", b);
            },
            "weapons.ron",
        );
        // 巨凤转速、判定半径为正
        bad(
            &|c| {
                let k = c.fusions.iter().position(|f| f.id == "phoenix").unwrap();
                if let WeaponBehavior::Seeker { escort: Some(e), .. } = &mut c.fusions[k].behavior {
                    e.size = 0.0;
                }
            },
            "fusions.ron",
        );
    }

    #[test]
    fn hub_milestones_validate_thresholds_references_and_ids() {
        let original = Content::load(&repo_data_dir()).unwrap();
        let invalid = [
            HubWhen::MetaLevels(0),
            HubWhen::MetaLevels(1000),
            HubWhen::MetaLevel("missing".into(), 1),
            HubWhen::MetaLevel("luck".into(), 0),
            HubWhen::MetaLevel("luck".into(), 6),
            HubWhen::Runs(0),
            HubWhen::Wins(0),
        ];
        for when in invalid {
            let mut c = original.clone();
            c.hub[0].lines.push(HubLineDef { once: "test_bad".into(), ask: false, when, text: "灯".into() });
            assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("hub.ron"));
        }
        for when in [
            HubWhen::MetaLevels(1),
            HubWhen::MetaLevel("luck".into(), 5),
            HubWhen::Runs(10),
            HubWhen::Wins(1),
        ] {
            let mut c = original.clone();
            c.hub[0].lines.push(HubLineDef { once: "test_ok".into(), ask: false, when, text: "灯".into() });
            c.validate(Path::new("data")).unwrap();
            c.hub[0].lines.last_mut().unwrap().once.clear();
            assert!(c.validate(Path::new("data")).is_err(), "里程碑必须有稳定 ID");
        }
        // 包在 All 里的里程碑也要带 once
        let mut c = original.clone();
        let when = HubWhen::All(vec![HubWhen::Runs(3), HubWhen::WithoutStory("qingqiu_entered".into())]);
        c.hub[0].lines.push(HubLineDef { once: String::new(), ask: false, when, text: "灯".into() });
        assert!(c.validate(Path::new("data")).is_err());
        // once 不能挂在初见上
        let mut c = original.clone();
        c.hub[0].lines.push(HubLineDef {
            once: "test_first".into(),
            ask: false,
            when: HubWhen::First,
            text: "灯".into(),
        });
        assert!(c.validate(Path::new("data")).is_err());
        // 同一个人几句共用一个 once 可以（同一问的几种说法），别的人物再用就算重复
        let mut c = original.clone();
        let shared = c.hub[2].lines.iter().find(|l| l.once == "qingqiu_asked_dark").unwrap().clone();
        c.hub[2].lines.push(shared.clone());
        c.validate(Path::new("data")).unwrap();
        c.hub[1].lines.push(shared);
        assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("重复"));
        let mut c = original;
        let duplicate = c.hub[0].lines.iter().find(|l| !l.once.is_empty()).unwrap().clone();
        c.hub[1].lines.push(duplicate);
        assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("重复"));
        let old: HubLineDef = ron::from_str("(when: Idle, text: \"灯\")").unwrap();
        assert!(old.once.is_empty() && !old.ask);
        // 追问必须带 once
        let mut c = Content::load(&repo_data_dir()).unwrap();
        c.hub[2].lines.iter_mut().find(|l| l.ask).unwrap().once.clear();
        assert!(c.validate(Path::new("data")).is_err());
    }

    /// 卡面和提示条的短句都填了（docs/LORE-TEXT.md 第 6 节），太长的校验不过。
    #[test]
    fn every_card_and_toast_has_a_short_line_within_the_limit() {
        let c = Content::load(&repo_data_dir()).unwrap();
        for w in &c.weapons {
            assert!(!w.short.is_empty(), "{}", w.name);
            assert!(w.evolution.as_ref().is_none_or(|e| !e.short.is_empty()), "{} 进化", w.name);
            assert!(w.mutation.as_ref().is_none_or(|m| !m.short.is_empty()), "{} 异化", w.name);
        }
        assert!(c.fusions.iter().all(|f| !f.short.is_empty()));
        assert!(c.passives.iter().all(|p| !p.short.is_empty()));
        assert!(c.elements.reactions.iter().all(|r| !r.short.is_empty()));
        assert!(c.elements.sheng.iter().all(|s| !s.short.is_empty()));
        assert!(c.elements.elements.iter().flat_map(|e| &e.tiers).all(|t| !t.short.is_empty()));
        let mut long = c.clone();
        long.passives[0].short = "一二三四五六七八九十一二三".into();
        assert!(long.validate(Path::new("data")).is_err(), "卡面超过 12 个字");
        let mut ok = c.clone();
        ok.passives[0].short = "暴击伤害 +200% 一二三四五六七八".into();
        ok.validate(Path::new("data")).unwrap();
        let mut long = c;
        long.elements.reactions[0].short = "一二三四五六七八九".into();
        assert!(long.validate(Path::new("data")).is_err(), "提示条超过 8 个字");
    }

    /// 接触半径按画出来的身体算，不超过碰撞半径；不写等于 radius（docs/PLAYTEST.md 的表）。
    #[test]
    fn contact_radius_defaults_to_radius_and_cannot_exceed_it() {
        let c = Content::load(&repo_data_dir()).unwrap();
        let lord = &c.enemies[c.enemy_index("stonelord").unwrap()];
        // 石将的身体比碰撞圈小得多（重画后量出 13.4，取 13）
        let contact = lord.contact_radius.expect("石将写了接触半径");
        assert!(contact < lord.radius);
        assert!((lord.contact_ratio() - contact / lord.radius).abs() < 1e-6);
        assert_eq!(c.enemies[c.enemy_index("shade").unwrap()].contact_ratio(), 1.0);
        for bad in [lord.radius + 1.0, 0.0] {
            let mut c = c.clone();
            let i = c.enemy_index("stonelord").unwrap();
            c.enemies[i].contact_radius = Some(bad);
            assert!(c.validate(Path::new("data")).is_err(), "{bad}");
        }
    }

    /// 只有灯童问青丘的四句是追问（排在初见前面）；老灯匠、说书人留灯以后的话不是。积累门槛算里程碑。
    #[test]
    fn hub_conditions_classify_story_questions_and_milestones() {
        let c = Content::load(&repo_data_dir()).unwrap();
        let child = &c.hub[2];
        let asked: Vec<_> = c.hub.iter().flat_map(|p| &p.lines).filter(|l| l.ask).collect();
        assert_eq!(asked.len(), 4);
        assert!(asked.iter().all(|l| l.once.starts_with("qingqiu_asked_") && l.when.is_story()));
        assert!(child.lines.iter().any(|l| l.when.is_milestone() && l.once == "child_three_returns"));
        assert!(!HubWhen::HasCleared(1).is_story() && !HubWhen::JournalCount(1).is_milestone());
        // 余烬那句跟着老灯匠
        assert!(c.hub[0].lines.iter().any(|l| l.once == "smith_ember"));
        assert!(!c.hub[1].lines.iter().any(|l| l.text.contains("火种")));
    }

    #[test]
    fn intro_route_rejects_invalid_levels_and_references() {
        let original = Content::load(&repo_data_dir()).unwrap();
        for entry in [("missing", 1), ("luck", 0), ("luck", 6), ("luck", 1)] {
            let mut c = original.clone();
            c.meta.intro.push((entry.0.into(), entry.1));
            assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("meta.ron"));
        }
        let mut c = original;
        c.meta.intro.clear();
        c.validate(Path::new("data")).unwrap();
    }

    #[test]
    fn quad_curve() {
        let q = Quad(1.6, 1.1, 0.1);
        assert!((q.at(2.0) - (1.6 + 2.2 + 0.4)).abs() < 1e-6);
    }

    #[test]
    fn invalid_experience_curves_and_stat_bounds_are_rejected() {
        let content = Content::load(&repo_data_dir()).unwrap();
        for q in [
            Quad(0.0, 0.0, 0.0),
            Quad(3.5, -4.0, 1.0), // 端点合法，低等级中间为负
            Quad(1.0, 0.0, -0.0001),
            Quad(f32::NAN, 0.0, 0.0),
            Quad(1.0, 0.0, f32::MAX),
        ] {
            let mut c = content.clone();
            c.run.xp_need = q;
            assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("xp_need"));
        }
        for (minimum, bound) in
            [(true, f32::NAN), (false, f32::NAN), (true, f32::INFINITY), (false, f32::NEG_INFINITY)]
        {
            let mut c = content.clone();
            if minimum {
                c.stats[0].min = bound;
            } else {
                c.stats[0].max = bound;
            }
            assert!(c.validate(Path::new("data")).unwrap_err().to_string().contains("stats.ron"));
        }
    }
}
