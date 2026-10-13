//! 存档 `save.ron`（docs/DESIGN.md 第 12 节）：灯油与铜钱、心灯、局外属性、解锁、成就、最好成绩、累计统计。
//!
//! 和设置文件一样带版本号、原子写入、保留备份；文件损坏时改名保留，改用空存档。
//! 读到 M2 的存档（版本 1）时按 docs/BALANCE.md 第 10.6 节迁移一次：要等内容数据加载好，
//! 由 [`Profile::upgrade`] 完成。

use std::collections::{BTreeMap, BTreeSet};
use std::io;
use std::path::{Path, PathBuf};

use bevy::prelude::Resource;
use serde::{Deserialize, Serialize};

use lantern_content::{AchievementWhen, Content, Element, Reward};
use lantern_sim::{RunMode, RunResult, RunSetup};

use crate::settings::write_atomic;

pub const SAVE_VERSION: u32 = 2;

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

/// 跨局累计的统计。
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Totals {
    pub kills: u64,
    pub seconds: f64,
    pub gold: u64,
    pub oil: u64,
    pub lanterns: u32,
    pub evolutions: u32,
}

/// 上次出发时的选择，下次默认选它。
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct LastPick {
    pub lamp: Option<String>,
    pub charm: Option<String>,
    pub tier: u8,
    pub insight: Option<Element>,
    /// 走无尽夜
    pub endless: bool,
}

/// 无尽夜的最长一次。
#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct EndlessBest {
    pub seconds: f32,
    pub kills: u32,
    pub bosses: u32,
}

#[derive(Resource, Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Profile {
    pub version: u32,
    /// 灯油（心灯）：可以花的、累计得到的
    pub oil: u32,
    pub oil_total: u32,
    /// 铜钱（局外属性）：可以花的、累计得到的
    pub gold: u32,
    pub gold_total: u32,
    /// 心灯各节点的等级（按 `meta.ron` 的 ID）
    pub meta: BTreeMap<String, u32>,
    /// 局外属性的等级（按 `attributes.ron` 的 ID）、买属性一共花掉的铜钱（全部退还时返还）
    pub attributes: BTreeMap<String, u32>,
    pub attributes_spent: u32,
    /// 出发前手动开关过的属性；没写的按默认（招妖默认关闭）
    pub toggles: BTreeMap<String, bool>,
    /// 开放了心灯、属性、夜签，出发前可以挂灯坠（第 1 号成就）
    pub basics: bool,
    /// 靠成就解锁的灯、灯坠（初始的不写）
    pub lamps: BTreeSet<String>,
    pub charms: BTreeSet<String>,
    /// 开放到第几更
    pub tier: u8,
    /// 通关过的最高一更
    pub cleared: u8,
    /// 达成的成就
    pub achievements: BTreeSet<String>,
    /// 见过的反应（按 `elements.ron` 里 reactions 的下标置位，跨局累计）
    pub reactions: u32,
    pub last: LastPick,
    pub best: Best,
    /// 无尽夜的最长存活（按更；以后加了地区再按地区分开）
    pub endless: BTreeMap<u8, EndlessBest>,
    pub totals: Totals,
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
            gold: 0,
            gold_total: 0,
            meta: BTreeMap::new(),
            attributes: BTreeMap::new(),
            attributes_spent: 0,
            toggles: BTreeMap::new(),
            basics: false,
            lamps: BTreeSet::new(),
            charms: BTreeSet::new(),
            tier: 1,
            cleared: 0,
            achievements: BTreeSet::new(),
            reactions: 0,
            last: LastPick::default(),
            best: Best::default(),
            endless: BTreeMap::new(),
            totals: Totals::default(),
            runs: 0,
            wins: 0,
            path: None,
        }
    }
}

/// 一局结束时记进存档的东西。
#[derive(Clone, Copy, Debug)]
pub struct RunRecord<'a> {
    pub result: &'a RunResult,
    /// 第几更
    pub tier: u8,
    /// 有没有生效的局外属性（没买或关掉都算不生效）
    pub attributes: bool,
}

/// 这一局刷新了哪项记录。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NewRecord {
    FirstDawn,
    Kills,
    Survival,
    /// 无尽夜在这一更撑得最久的一次
    Endless,
}

/// 记下一局之后的结果：刷新的记录、新达成的成就（`achievements.ron` 下标）。
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Recorded {
    pub record: Option<NewRecord>,
    pub achievements: Vec<usize>,
}

/// M2 心灯每级的花费：round(120 × n^1.6 ÷ 10) × 10。
const M2_COSTS: [u32; 5] = [120, 360, 700, 1100, 1580];
/// M2 改由属性提供的三系（退还灯油）
const M2_REFUND: [&str; 3] = ["dmg", "hp", "agi"];

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
        p.path = Some(path);
        p
    }

    pub fn save(&self) -> io::Result<()> {
        let Some(path) = &self.path else { return Ok(()) };
        let text =
            ron::ser::to_string_pretty(self, ron::ser::PrettyConfig::default()).map_err(io::Error::other)?;
        write_atomic(path, text.as_bytes())
    }

    /// 内容加载好之后调用：老存档迁移到当前版本。迁移过返回 true（需要保存）。
    pub fn upgrade(&mut self, content: &Content) -> bool {
        if self.version >= SAVE_VERSION {
            return false;
        }
        if self.version < 2 {
            // 锋芒、体魄、灵巧清零，退回花掉的灯油；祈福保留等级；铜钱从 0 开始
            for id in M2_REFUND {
                if let Some(lv) = self.meta.remove(id) {
                    self.oil += M2_COSTS.iter().take(lv as usize).sum::<u32>();
                }
            }
            self.meta.retain(|id, _| content.meta.node(id).is_some());
            // 按局数和胜场补发成就（M2 的胜利算青丘一更）
            if self.wins > 0 {
                self.cleared = self.cleared.max(1);
            }
            for (k, a) in content.achievements.iter().enumerate() {
                let due = match a.when {
                    AchievementWhen::Runs(n) => self.runs >= n,
                    AchievementWhen::Clear(1) => self.wins > 0,
                    _ => false,
                };
                if due {
                    self.grant(content, k);
                }
            }
        }
        self.version = SAVE_VERSION;
        true
    }

    // ---- 心灯 ----

    pub fn meta_level(&self, id: &str) -> u32 {
        self.meta.get(id).copied().unwrap_or(0)
    }

    /// 点亮下一级要多少灯油；已经满级时返回 None。
    pub fn meta_cost(&self, content: &Content, id: &str) -> Option<u32> {
        let node = content.meta.node(id)?;
        let lv = self.meta_level(id);
        (lv < node.max_level).then(|| content.meta.cost(node, lv))
    }

    /// 花灯油点亮一级心灯。灯油不够或已满级时返回 false。
    pub fn buy_meta(&mut self, content: &Content, id: &str) -> bool {
        let Some(cost) = self.meta_cost(content, id) else { return false };
        if self.oil < cost {
            return false;
        }
        self.oil -= cost;
        *self.meta.entry(id.to_string()).or_default() += 1;
        true
    }

    // ---- 局外属性 ----

    pub fn attribute_level(&self, id: &str) -> u32 {
        self.attributes.get(id).copied().unwrap_or(0)
    }

    /// 一共买过几级（涨价按它算）。
    pub fn attributes_bought(&self) -> u32 {
        self.attributes.values().sum()
    }

    /// 下一级的价格；已经满级时返回 None。
    pub fn attribute_price(&self, content: &Content, id: &str) -> Option<u32> {
        let a = content.attributes.list.iter().find(|a| a.id == id)?;
        let lv = self.attribute_level(id);
        (lv < a.max_level).then(|| content.attributes.price(a, lv, self.attributes_bought()))
    }

    pub fn buy_attribute(&mut self, content: &Content, id: &str) -> bool {
        let Some(price) = self.attribute_price(content, id) else { return false };
        if self.gold < price {
            return false;
        }
        self.gold -= price;
        self.attributes_spent += price;
        *self.attributes.entry(id.to_string()).or_default() += 1;
        true
    }

    /// 全部退还：返还实际花掉的铜钱（包括涨价的部分）。返回退回了多少。
    pub fn refund_attributes(&mut self) -> u32 {
        let back = self.attributes_spent;
        self.gold += back;
        self.attributes_spent = 0;
        self.attributes.clear();
        back
    }

    /// 这项属性出发时是否生效（没开关过的按默认）。
    pub fn attribute_on(&self, content: &Content, id: &str) -> bool {
        self.toggles.get(id).copied().unwrap_or_else(|| {
            !content.attributes.list.iter().find(|a| a.id == id).is_some_and(|a| a.off_by_default)
        })
    }

    pub fn toggle_attribute(&mut self, content: &Content, id: &str) {
        let on = self.attribute_on(content, id);
        self.toggles.insert(id.to_string(), !on);
    }

    /// 出发时生效的属性等级（关掉的、没买的不写）。
    pub fn active_attributes(&self, content: &Content) -> BTreeMap<String, u32> {
        self.attributes
            .iter()
            .filter(|&(id, &lv)| lv > 0 && self.attribute_on(content, id))
            .map(|(id, &lv)| (id.clone(), lv))
            .collect()
    }

    // ---- 解锁 ----

    pub fn lamp_unlocked(&self, content: &Content, id: &str) -> bool {
        content.lamps.iter().any(|l| l.id == id && l.initial) || self.lamps.contains(id)
    }

    pub fn charm_unlocked(&self, content: &Content, id: &str) -> bool {
        content.charms.iter().any(|c| c.id == id && c.initial) || self.charms.contains(id)
    }

    /// 已经解锁的灯坠（局内可能出现的），按 `charms.ron` 的顺序。
    pub fn charm_pool(&self, content: &Content) -> Vec<String> {
        content.charms.iter().filter(|c| self.charm_unlocked(content, &c.id)).map(|c| c.id.clone()).collect()
    }

    /// 已经点亮的悟·五行。
    pub fn insights(&self, content: &Content) -> Vec<Element> {
        content.meta.nodes.iter().filter(|n| self.meta_level(&n.id) > 0).filter_map(|n| n.insight).collect()
    }

    /// 按存档和上次的选择拼出下一局的设置。灯、灯坠、更、悟不可用时退回默认。
    pub fn run_setup(&self, content: &Content, seed: u64) -> RunSetup {
        let mut s = RunSetup::new(seed, RunMode::Normal);
        s.meta = self.meta.clone();
        s.attributes = self.active_attributes(content);
        s.tier = self.last.tier.clamp(1, self.tier.max(1));
        // 无尽夜只能选通关过的更
        if self.last.endless && self.endless_unlocked() {
            s.mode = RunMode::Endless;
            s.tier = s.tier.min(self.cleared);
        }
        s.lamp = self.last.lamp.clone().filter(|id| self.lamp_unlocked(content, id));
        if self.basics {
            s.charms =
                self.last.charm.iter().filter(|id| self.charm_unlocked(content, id)).cloned().collect();
        }
        s.charm_pool = self.charm_pool(content);
        s.insight = self.last.insight.filter(|e| self.insights(content).contains(e));
        s
    }

    // ---- 成就 ----

    /// 发放一个成就的奖励（成就发的灯油和铜钱不乘倍率）。已经达成过的不再发。
    pub fn grant(&mut self, content: &Content, k: usize) -> bool {
        let a = &content.achievements[k];
        if !self.achievements.insert(a.id.clone()) {
            return false;
        }
        for r in &a.rewards {
            match r {
                Reward::Basics => self.basics = true,
                Reward::Lamp(id) => {
                    self.lamps.insert(id.clone());
                }
                Reward::Charm(id) => {
                    self.charms.insert(id.clone());
                }
                Reward::Tier(t) => self.tier = self.tier.max(*t),
                Reward::Gold(n) => {
                    self.gold += n;
                    self.gold_total += n;
                }
                Reward::Oil(n) => {
                    self.oil += n;
                    self.oil_total += n;
                }
            }
        }
        true
    }

    /// 这一局做到了哪些成就（不管之前有没有达成过）。
    fn achieved(&self, content: &Content, k: usize, rec: &RunRecord) -> bool {
        let r = rec.result;
        let f = &r.feats;
        let all = (1u32 << content.elements.reactions.len()) - 1;
        match content.achievements[k].when {
            AchievementWhen::Runs(n) => self.runs >= n,
            AchievementWhen::Clear(t) => r.won && rec.tier >= t,
            AchievementWhen::AllLanterns => r.lamps_complete,
            AchievementWhen::Died => !r.won,
            AchievementWhen::Taiji => f.taiji,
            AchievementWhen::ClearWithWeapons(n) => r.won && f.max_weapons <= n,
            AchievementWhen::Reaction => f.reactions != 0,
            AchievementWhen::AllReactions => self.reactions & all == all,
            AchievementWhen::ResonanceTier(t) => f.max_tier >= t,
            AchievementWhen::Evolution => r.evolutions > 0,
            AchievementWhen::FlawlessElite => f.flawless_elites > 0,
            AchievementWhen::ClearNoAttributes => r.won && !rec.attributes,
        }
    }

    // ---- 一局结束 ----

    /// 记下一局的结果：货币、统计、最好成绩、成就。刷新的记录同时有几项时按 天明 > 击杀 > 存活 取一项。
    /// 无尽夜：通关青丘一更后开放（docs/GAMEPLAY.md 第 3.4 节）。
    pub fn endless_unlocked(&self) -> bool {
        self.cleared >= 1
    }

    pub fn record(&mut self, content: &Content, rec: RunRecord) -> Recorded {
        let r = rec.result;
        let b = &mut self.best;
        let record = if r.endless {
            // 无尽夜只记在自己的榜上
            let e = self.endless.entry(rec.tier).or_default();
            let new = r.seconds > e.seconds;
            if new {
                *e = EndlessBest { seconds: r.seconds, kills: r.kills, bosses: r.bosses };
            }
            new.then_some(NewRecord::Endless)
        } else if r.won && !b.won {
            Some(NewRecord::FirstDawn)
        } else if r.kills > b.kills {
            Some(NewRecord::Kills)
        } else if r.seconds > b.seconds && !r.won {
            Some(NewRecord::Survival)
        } else {
            None
        };
        if !r.endless {
            b.seconds = b.seconds.max(r.seconds);
            b.kills = b.kills.max(r.kills);
            b.won |= r.won;
        }
        self.oil += r.oil;
        self.oil_total += r.oil;
        self.gold += r.gold;
        self.gold_total += r.gold;
        self.runs += 1;
        self.wins += u32::from(r.won);
        if r.won {
            self.cleared = self.cleared.max(rec.tier);
        }
        self.reactions |= r.feats.reactions;
        let t = &mut self.totals;
        t.kills += u64::from(r.kills);
        t.seconds += f64::from(r.seconds);
        t.gold += u64::from(r.gold);
        t.oil += u64::from(r.oil);
        t.lanterns += r.lanterns;
        t.evolutions += r.evolutions;
        let mut achievements = Vec::new();
        for k in 0..content.achievements.len() {
            if self.achieved(content, k, &rec) && self.grant(content, k) {
                achievements.push(k);
            }
        }
        Recorded { record, achievements }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::flow::Feats;

    fn content() -> Content {
        Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).expect("内容数据")
    }

    fn result(won: bool, seconds: f32, kills: u32, oil: u32, gold: u32) -> RunResult {
        RunResult {
            won,
            seconds,
            kills,
            level: 10,
            best_combo: 0,
            evolutions: 0,
            oil,
            oil_parts: [0; 5],
            gold,
            lanterns: 0,
            lamps_complete: false,
            feats: Feats::default(),
            endless: false,
            bosses: u32::from(won),
        }
    }

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("lantern-save-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn records_buys_and_roundtrips() {
        let c = content();
        let dir = temp("roundtrip");
        let mut p = Profile::load(&dir);
        assert_eq!((p.oil, p.tier, p.basics), (0, 1, false));
        fn rec(r: &RunResult) -> RunRecord<'_> {
            RunRecord { result: r, tier: 1, attributes: false }
        }
        let r1 = result(false, 200.0, 500, 250, 50);
        let got = p.record(&c, rec(&r1));
        assert_eq!(got.record, Some(NewRecord::Kills));
        // 第一局：开放基础，第一次倒下得到九转金丹
        assert!(p.basics && p.charm_unlocked(&c, "elixir"));
        let names: Vec<_> = got.achievements.iter().map(|&k| c.achievements[k].id.as_str()).collect();
        assert_eq!(names, ["first_night", "first_fall"]);
        let r2 = result(false, 210.0, 100, 210, 0);
        assert_eq!(p.record(&c, rec(&r2)).record, Some(NewRecord::Survival));
        assert!(p.lamp_unlocked(&c, "mirror") && !p.lamp_unlocked(&c, "frost"));
        let r3 = result(true, 600.0, 7000, 1300, 650);
        let got = p.record(&c, rec(&r3));
        assert_eq!(got.record, Some(NewRecord::FirstDawn));
        // 通关一更：霜瓷灯、二更；不带属性通关再 500 铜钱
        assert!(p.lamp_unlocked(&c, "frost") && p.tier == 2);
        assert!(p.achievements.contains("no_attributes"));
        assert_eq!(p.oil, 1760);
        assert_eq!(p.gold, 50 + 650 + 500);

        // 心灯：祈福第 1 级 300
        assert!(p.buy_meta(&c, "luck"));
        assert_eq!((p.meta_level("luck"), p.oil), (1, 1460));
        // 属性：伤害 60，第二次买涨价 2%：生命 40 → 80 × 1.02 ≈ 80
        assert!(p.buy_attribute(&c, "damage"));
        assert_eq!(p.attribute_price(&c, "health"), Some(40));
        assert!(p.buy_attribute(&c, "health"));
        let spent = p.attributes_spent;
        assert_eq!(spent, 100);
        assert_eq!(p.active_attributes(&c).len(), 2);
        p.toggle_attribute(&c, "damage");
        assert_eq!(p.active_attributes(&c).keys().collect::<Vec<_>>(), ["health"]);

        p.last = LastPick {
            lamp: Some("frost".into()),
            charm: Some("elixir".into()),
            tier: 2,
            ..Default::default()
        };
        let s = p.run_setup(&c, 7);
        assert_eq!((s.lamp.as_deref(), s.tier, s.charms.len()), (Some("frost"), 2, 1));
        assert!(
            s.charm_pool.iter().any(|id| id == "elixir") && !s.charm_pool.iter().any(|id| id == "five_coins")
        );

        // 无尽夜：通关一更后开放，只能选通关过的更；记在自己的榜上
        assert!(p.endless_unlocked());
        p.last.endless = true;
        let s = p.run_setup(&c, 8);
        assert_eq!((s.mode, s.tier), (RunMode::Endless, 1));
        let best = p.best.clone();
        let e = RunResult { endless: true, bosses: 2, ..result(false, 1300.0, 40000, 2900, 900) };
        assert_eq!(p.record(&c, rec(&e)).record, Some(NewRecord::Endless));
        assert_eq!(p.endless[&1], EndlessBest { seconds: 1300.0, kills: 40000, bosses: 2 });
        assert_eq!(p.best, best);
        let shorter = RunResult { endless: true, ..result(false, 900.0, 20000, 1500, 400) };
        assert_eq!(p.record(&c, rec(&shorter)).record, None);
        p.last.endless = false;

        p.save().unwrap();
        let mut q = Profile::load(&dir);
        assert!(!q.upgrade(&c));
        assert_eq!(q, Profile { path: q.path.clone(), ..p.clone() });
        assert_eq!(q.refund_attributes(), spent);
        assert_eq!(q.gold, p.gold + spent);

        std::fs::write(dir.join("save.ron"), "(oil: lots").unwrap();
        assert_eq!(Profile::load(&dir).oil, 0);
        assert!(dir.join("save.ron.broken").exists());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// docs/BALANCE.md 第 10.6 节：M2 存档迁移。
    #[test]
    fn migrates_m2_saves() {
        let c = content();
        let dir = temp("migrate");
        std::fs::create_dir_all(&dir).unwrap();
        let old = "(version: 1, oil: 500, oil_total: 9000, meta: {\"dmg\": 3, \"hp\": 1, \"luck\": 2}, \
                   best: (seconds: 600.0, kills: 7000, won: true), runs: 5, wins: 1)";
        std::fs::write(dir.join("save.ron"), old).unwrap();
        let mut p = Profile::load(&dir);
        assert!(p.upgrade(&c));
        // 锋芒 3 级退 1180，体魄 1 级退 120；补发前三个成就
        assert_eq!(p.oil, 500 + 1180 + 120);
        assert_eq!(p.oil_total, 9000);
        assert_eq!(p.meta, BTreeMap::from([("luck".to_string(), 2)]));
        assert_eq!(p.gold, 0);
        assert!(p.basics && p.lamp_unlocked(&c, "mirror") && p.lamp_unlocked(&c, "frost"));
        assert_eq!((p.tier, p.cleared, p.version), (2, 1, SAVE_VERSION));
        assert!(!p.upgrade(&c));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
