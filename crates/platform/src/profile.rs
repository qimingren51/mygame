//! 存档 `save.ron`（docs/DESIGN.md 第 12 节）：灯油与铜钱、心灯、局外属性、解锁、成就、最好成绩、累计统计。
//!
//! 和设置文件一样带版本号、原子写入、保留备份；优先恢复备份，恢复失败时禁止覆盖。
//! 读到 M2 的存档（版本 1）时按 docs/BALANCE.md 第 10.6 节迁移一次：要等内容数据加载好，
//! 由 [`Profile::upgrade`] 完成。

use std::collections::{BTreeMap, BTreeSet};
use std::io;
use std::path::{Path, PathBuf};

use bevy::prelude::Resource;
use serde::{Deserialize, Serialize};

use lantern_content::{AchievementWhen, Content, Element, HubWhen, Reward};
use lantern_sim::{RunMode, RunResult, RunSetup};

use crate::settings::{load_with_backup, write_atomic};

pub const SAVE_VERSION: u32 = 3;

/// 首夜教学的完成项；独立于模拟与回放，完成一项就保存。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct OnboardingProgress {
    pub movement: bool,
    pub dash: bool,
    pub ult: bool,
    pub upgrade: bool,
}

impl OnboardingProgress {
    pub fn complete(self) -> bool {
        self.movement && self.dash && self.ult && self.upgrade
    }
    pub fn completed() -> Self {
        Self { movement: true, dash: true, ult: true, upgrade: true }
    }
}

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
    /// 灯驿里已经见过的人物（`hub.ron` 的 ID）
    pub met: BTreeSet<String>,
    /// 灯驿里已经说出口的只说一次的台词（`hub.ron` 的 once ID：青丘追问、积累回应）
    pub hub_lines_seen: BTreeSet<String>,
    /// 展开过的开场卷轴：地区 ID；天明版写成“ID_dawn”
    pub scrolls: BTreeSet<String>,
    /// 已亲历的故事事件（模拟记下的，见 `lantern_content::STORY_EVENTS`）
    pub events: BTreeSet<String>,
    /// 已拾到的手记页码；未知卷的文字不进入界面。
    pub journals: BTreeSet<u8>,
    pub best: Best,
    /// 无尽夜的最长存活（按更；以后加了地区再按地区分开）
    pub endless: BTreeMap<u8, EndlessBest>,
    pub totals: Totals,
    pub runs: u32,
    pub wins: u32,
    pub onboarding: OnboardingProgress,
    #[serde(skip)]
    path: Option<PathBuf>,
    #[serde(skip)]
    save_error: Option<String>,
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
            met: BTreeSet::new(),
            hub_lines_seen: BTreeSet::new(),
            scrolls: BTreeSet::new(),
            events: BTreeSet::new(),
            journals: BTreeSet::new(),
            best: Best::default(),
            endless: BTreeMap::new(),
            totals: Totals::default(),
            runs: 0,
            wins: 0,
            onboarding: OnboardingProgress::default(),
            path: None,
            save_error: None,
        }
    }
}

/// 灯驿里人物要说的“刚发生的事”（不存档）：结算时记下这一局带来的变化，在灯驿里点亮心灯、退还属性时也记。
#[derive(Resource, Clone, Debug, Default, PartialEq)]
pub struct HubNews {
    pub meta_lit: bool,
    pub refunded: bool,
    pub achievement: bool,
    /// 五行谱多了一种反应
    pub reaction: bool,
    /// 新解锁的灯
    pub lamps: Vec<String>,
    /// 第一次通关的那一更
    pub cleared: Option<u8>,
    pub endless_back: bool,
    /// 这次在心灯里从 0 级点亮的节点（灯驿长卷上那盏灯的点亮动画用，播完由画面清掉）
    pub lit: Vec<String>,
    /// 上一局第一次在这个地区迎来天明（地区 ID；灯驿长卷上那座山的晨光铺开用，播完清掉）
    pub dawn: Option<String>,
    /// 这次归来新添的那盏路灯（从 0 起，第 n 次归来添第 n − 1 盏；灯驿长卷的点亮动画用，播完清掉）
    pub road_lit: Option<usize>,
    /// 这一趟回灯驿已经说出口的 once 台词：存档里记成听过了，但这一趟照样说，重画不换句
    pub heard: Vec<String>,
}

impl HubNews {
    /// 一局记进存档之后：和记之前的存档比，这一局带来了什么。
    pub fn after_run(
        content: &Content,
        before: &Profile,
        now: &Profile,
        result: &RunResult,
        rec: &Recorded,
    ) -> Self {
        HubNews {
            achievement: !rec.achievements.is_empty(),
            reaction: now.reactions & !before.reactions != 0,
            lamps: content
                .lamps
                .iter()
                .filter(|l| now.lamp_unlocked(content, &l.id) && !before.lamp_unlocked(content, &l.id))
                .map(|l| l.id.clone())
                .collect(),
            cleared: (now.cleared > before.cleared).then_some(now.cleared),
            endless_back: result.endless,
            // P0 只有青丘：通关过一更就算这里天明过（以后按地区记通关）
            dawn: (before.cleared == 0 && now.cleared >= 1)
                .then(|| content.regions.first().map(|r| r.id.clone()))
                .flatten(),
            road_lit: (now.road_lamps() > before.road_lamps()).then(|| now.road_lamps() as usize - 1),
            ..Default::default()
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

/// 灯驿门外的路灯：回来一回添一盏，最多这么多盏（docs/DESIGN.md 第 15 节 `road_lamps`）。
pub const ROAD_LAMPS: u32 = 10;

/// M2 心灯每级的花费：round(120 × n^1.6 ÷ 10) × 10。
const M2_COSTS: [u32; 5] = [120, 360, 700, 1100, 1580];
/// M2 改由属性提供的三系（退还灯油）
const M2_REFUND: [&str; 3] = ["dmg", "hp", "agi"];

impl Profile {
    pub fn load(dir: &Path) -> Profile {
        let path = dir.join("save.ron");
        let (mut p, error) = load_with_backup::<Profile>(&path);
        p.save_error = error;
        p.path = Some(path);
        p
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
        if self.version < 3 && (self.runs > 0 || self.basics) {
            self.onboarding = OnboardingProgress::completed();
        }
        // 第三版新加的 events、journals、hub_lines_seen 都有默认值（空）；旧通关不冒认亲历过护火或留灯，
        // 旧存档也不补记听过哪句。
        self.version = SAVE_VERSION;
        true
    }

    // ---- 心灯 ----

    pub fn meta_level(&self, id: &str) -> u32 {
        self.meta.get(id).copied().unwrap_or(0)
    }

    /// 初程下一盏建议；自由选过的节点自动跳过。
    pub fn next_meta_intro<'a>(&self, content: &'a Content) -> Option<&'a lantern_content::MetaNodeDef> {
        content
            .meta
            .intro
            .iter()
            .find(|(id, lv)| self.meta_level(id) < *lv)
            .and_then(|(id, _)| content.meta.node(id))
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
        s.story = Some(lantern_sim::story::StorySeed {
            events: self.events.clone(),
            journals: self.journals.clone(),
            chapter: self.journal_chapter(),
        });
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
    /// 有效心灯总级数；不认识的旧节点和超出上限的等级不算。
    pub fn meta_levels(&self, content: &Content) -> u32 {
        content.meta.nodes.iter().map(|n| self.meta_level(&n.id).min(n.max_level)).sum()
    }

    /// 灯驿门外点着几盏路灯：回来几回点几盏，最多 [`ROAD_LAMPS`]。
    pub fn road_lamps(&self) -> u32 {
        self.runs.min(ROAD_LAMPS)
    }

    /// 心灯全部点亮。
    pub fn meta_full(&self, content: &Content) -> bool {
        content.meta.nodes.iter().all(|n| self.meta_cost(content, &n.id).is_none())
    }

    /// 属性全部买满。
    pub fn attributes_full(&self, content: &Content) -> bool {
        content.attributes.list.iter().all(|a| self.attribute_price(content, &a.id).is_none())
    }

    /// 章节只在出发时开放；本局留灯可提前打开卷三，绝不越到卷五。
    pub fn journal_chapter(&self) -> u8 {
        let left = self.events.contains("qingqiu_left_lantern");
        if self.cleared > 0
            && self.runs >= 6
            && self.journals.len() >= 18
            && self.meta.values().sum::<u32>() >= 6
            && self.endless.values().any(|e| e.seconds >= 900.0 && e.bosses > 0)
        {
            5
        } else if self.cleared > 0 && self.runs >= 4 && self.journals.len() >= 12 {
            4
        } else if self.cleared > 0 || left {
            3
        } else if self.events.contains("qingqiu_entered") || self.runs > 0 {
            2
        } else {
            1
        }
    }

    fn hub_when(&self, content: &Content, w: &HubWhen, news: &HubNews, first: bool) -> bool {
        match w {
            HubWhen::Story(id) => self.events.contains(id),
            HubWhen::WithoutStory(id) => !self.events.contains(id),
            HubWhen::JournalCount(n) => self.journals.len() >= usize::from(*n),
            HubWhen::HasCleared(t) => self.cleared >= *t,
            HubWhen::All(ws) => ws.iter().all(|w| self.hub_when(content, w, news, first)),
            HubWhen::MetaLevels(n) => self.meta_levels(content) >= *n,
            HubWhen::MetaLevel(id, lv) => self.meta_level(id) >= *lv,
            HubWhen::Runs(n) => self.runs >= *n,
            HubWhen::Wins(n) => self.wins >= *n,
            HubWhen::Idle => false,
            HubWhen::First => first,
            HubWhen::MetaLit => news.meta_lit,
            HubWhen::MetaFull => self.meta_full(content),
            HubWhen::Lamp(id) => news.lamps.contains(id),
            HubWhen::Cleared(t) => news.cleared == Some(*t),
            HubWhen::Refunded => news.refunded,
            HubWhen::AttributesFull => self.attributes_full(content),
            HubWhen::Achievement => news.achievement,
            HubWhen::Charm(id) => self.basics && self.last.charm.as_ref() == Some(id),
            HubWhen::Reaction => news.reaction,
            HubWhen::EndlessBack => news.endless_back,
        }
    }

    /// 灯驿第 who 个人物这次说哪句（docs/LORE-TEXT.md 第 1 节）。按档挑，同一档里取满足的最后一条：
    /// 1. 没听过的青丘追问（带 once、条件里有故事事件）——首通或倒下回来都不能被初见吞掉；
    /// 2. 第一次见面（First）；
    /// 3. 没听过的积累回应（带 once 的里程碑）；
    /// 4. 即时回应、持续状态（不带 once 的）；
    /// 5. 平时（Idle），按回来的次数轮着说。
    ///
    /// once 台词说出口就记成听过，以后不再说；但这一趟回灯驿里（`HubNews::heard`）照样算没听过，重画不换句。
    pub fn hub_dialogue<'a>(
        &self,
        content: &'a Content,
        who: usize,
        news: &HubNews,
    ) -> Option<&'a lantern_content::HubLineDef> {
        let person = content.hub.get(who)?;
        let first = !self.met.contains(&person.id);
        let lines = &person.lines;
        let hit = |l: &lantern_content::HubLineDef| self.hub_when(content, &l.when, news, first);
        let fresh = |l: &lantern_content::HubLineDef| {
            !l.once.is_empty() && (!self.hub_lines_seen.contains(&l.once) || news.heard.contains(&l.once))
        };
        let once =
            |story: bool| lines.iter().rev().find(|l| fresh(l) && l.when.is_story() == story && hit(l));
        once(true)
            .or_else(|| lines.iter().find(|l| first && l.when == HubWhen::First))
            .or_else(|| once(false))
            .or_else(|| lines.iter().rev().find(|l| l.once.is_empty() && hit(l)))
            .or_else(|| {
                let idle: Vec<_> = lines.iter().filter(|l| l.when == HubWhen::Idle).collect();
                idle.get(self.runs as usize % idle.len().max(1)).copied()
            })
    }

    pub fn hub_line<'a>(&self, content: &'a Content, who: usize, news: &HubNews) -> Option<&'a str> {
        self.hub_dialogue(content, who, news).map(|l| l.text.as_str())
    }

    /// 灯驿里选中的那位说出这句以后调用：只确认这一位这一句，被更高一档盖住的、别人的留到真正说出来。
    /// 查看纯数据或回放不推进。不重置 `HubNews` 的其他内容。返回存档有没有变（变了才需要写盘）。
    pub fn saw_hub(&mut self, content: &Content, who: usize, news: &mut HubNews) -> bool {
        let Some(person) = content.hub.get(who) else { return false };
        let Some(line) = self.hub_dialogue(content, who, news).filter(|l| !l.once.is_empty()) else {
            return false;
        };
        if !news.heard.contains(&line.once) {
            news.heard.push(line.once.clone());
        }
        let mut changed = self.hub_lines_seen.insert(line.once.clone());
        // 已经说过追问，就确实见过这个人：以后不再倒回初见那句。
        changed |= self.met.insert(person.id.clone());
        changed
    }

    /// 这次出发要不要先展开某个地区的开场卷轴：第一次来展开长夜版（false），拿回烛火以后再来展开一次
    /// 天明版（true，数据里写了天明的旁白才展开）；都看过了返回 None。
    pub fn next_scroll(&self, content: &Content, region: &str) -> Option<bool> {
        let r = content.regions.iter().find(|r| r.id == region)?;
        if !self.scrolls.contains(region) {
            return Some(false);
        }
        (self.cleared >= 1 && r.dawn.is_some() && !self.scrolls.contains(&format!("{region}_dawn")))
            .then_some(true)
    }

    /// 记下展开过的卷轴。
    pub fn saw_scroll(&mut self, region: &str, dawn: bool) {
        self.scrolls.insert(if dawn { format!("{region}_dawn") } else { region.to_string() });
    }

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
        self.events.extend(r.events.iter().cloned());
        self.journals.extend(r.journals.iter().copied().filter(|p| (1..=30).contains(p)));
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
            events: BTreeSet::new(),
            journals: BTreeSet::new(),
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

    /// 灯驿人物的台词：第一次见面说 First，之后取满足的最后一条，都不满足时轮着说“平时”。
    #[test]
    fn scrolls_unroll_once_at_night_and_once_at_dawn() {
        let mut c = content();
        let mut p = Profile::default();
        assert_eq!(p.next_scroll(&c, "qingqiu"), Some(false), "第一次来展开长夜版");
        assert_eq!(p.next_scroll(&c, "没有的地区"), None);
        p.saw_scroll("qingqiu", false);
        assert_eq!(p.next_scroll(&c, "qingqiu"), None);
        c.regions[0].dawn = Some("天明".into());
        assert_eq!(p.next_scroll(&c, "qingqiu"), None, "还没天明");
        p.cleared = 1;
        assert_eq!(p.next_scroll(&c, "qingqiu"), Some(true));
        p.saw_scroll("qingqiu", true);
        assert_eq!(p.next_scroll(&c, "qingqiu"), None);
        c.regions[0].dawn = None;
        let mut fresh = Profile { cleared: 1, ..Profile::default() };
        fresh.saw_scroll("qingqiu", false);
        assert_eq!(fresh.next_scroll(&c, "qingqiu"), None, "没写天明旁白时不展开");
    }

    #[test]
    fn hub_lines_follow_the_news() {
        let c = content();
        let mut p = Profile::default();
        let news = HubNews::default();
        let line = |p: &Profile, who, news: &HubNews| p.hub_line(&c, who, news).unwrap().to_string();
        assert!(line(&p, 0, &news).starts_with("回来了？"), "第一次见老灯匠");
        p.met.extend(["smith", "peddler", "child", "teller"].map(String::from));
        let idle0 = line(&p, 0, &news);
        p.runs = 1;
        assert_ne!(line(&p, 0, &news), idle0, "平时的几句轮着说");
        let lit = HubNews { meta_lit: true, ..Default::default() };
        assert!(line(&p, 0, &lit).contains("东街"));
        // 同时满足几条时取最后一条：成就、通关一更都满足，灯童说通关那句
        let won = HubNews { achievement: true, cleared: Some(1), ..Default::default() };
        assert!(line(&p, 2, &won).contains("狐狸也怕黑"));
        let back = HubNews { endless_back: true, ..Default::default() };
        assert!(line(&p, 3, &back).contains("走了多深"));
    }

    /// 第一次天明的那一局带上地区，灯驿长卷上那座山铺开晨光；以后再赢不带。
    #[test]
    fn first_dawn_brings_the_region() {
        let c = content();
        let mut p = Profile::default();
        let won = result(true, 600.0, 3000, 400, 50);
        let news = |p: &mut Profile| {
            let before = p.clone();
            let got = p.record(&c, RunRecord { result: &won, tier: 1, attributes: false });
            HubNews::after_run(&c, &before, p, &won, &got)
        };
        assert_eq!(news(&mut p).dawn.as_deref(), Some("qingqiu"));
        assert_eq!(news(&mut p).dawn, None);
    }

    #[test]
    fn corrupt_save_recovers_backup_without_overwriting_it() {
        let dir = temp("backup");
        let mut p = Profile::load(&dir);
        p.oil = 123;
        p.save().unwrap();
        p.oil = 456;
        p.save().unwrap();
        std::fs::write(dir.join("save.ron"), "broken").unwrap();
        let mut recovered = Profile::load(&dir);
        assert_eq!(recovered.oil, 123);
        recovered.oil += 1;
        recovered.save().unwrap();
        assert_eq!(Profile::load(&dir).oil, 124);
        assert!(std::fs::read_to_string(dir.join("save.bak")).unwrap().contains("oil: 123"));
        assert_eq!(std::fs::read_to_string(dir.join("save.ron.broken")).unwrap(), "broken");
        std::fs::remove_dir_all(dir).unwrap();
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

        // 心灯：祈福第 1 级 200
        assert!(p.buy_meta(&c, "luck"));
        assert_eq!((p.meta_level("luck"), p.oil), (1, 1560));
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
        assert!(Profile::load(&dir).save().is_err());
        assert_eq!(std::fs::read_to_string(dir.join("save.ron")).unwrap(), "(oil: lots");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn onboarding_progress_persists_and_v2_veterans_do_not_repeat_it() {
        let dir = temp("onboarding");
        let mut p = Profile::load(&dir);
        p.onboarding.dash = true;
        p.save().unwrap();
        let loaded = Profile::load(&dir);
        assert!(loaded.onboarding.dash);
        assert!(!loaded.onboarding.complete());
        std::fs::write(dir.join("save.ron"), "(version: 2, runs: 3, oil: 125)").unwrap();
        let mut old = Profile::load(&dir);
        assert!(old.upgrade(&content()));
        assert!(old.onboarding.complete());
        assert_eq!(old.oil, 125);
        // 第三版的叙事集合（events、journals）和听过的台词（hub_lines_seen）都有默认值，旧存档迁移时不补写。
        assert!(old.events.is_empty() && old.journals.is_empty() && old.hub_lines_seen.is_empty());
        let mut first = Profile { version: 2, ..Default::default() };
        first.upgrade(&content());
        assert!(!first.onboarding.complete());
        // 只有引导进度的第三版存档照常读出，叙事集合为空。
        std::fs::write(dir.join("save.ron"), "(version: 3, onboarding: (dash: true))").unwrap();
        let v3 = Profile::load(&dir);
        assert!(v3.onboarding.dash && v3.events.is_empty() && v3.journals.is_empty());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn additive_story_save_loads_old_versions_and_roundtrips_new_progress() {
        for version in [1, 2] {
            let mut p: Profile = ron::from_str(&format!("(version: {version}, runs: 3)")).unwrap();
            assert!(p.events.is_empty() && p.journals.is_empty());
            assert!(p.upgrade(&content()));
            assert_eq!(p.version, SAVE_VERSION);
            assert!(p.events.is_empty() && p.journals.is_empty());
            assert!(!p.upgrade(&content()), "不能重复迁移或补写未做过的故事");
        }
        let c = content();
        let dir = temp("story");
        let mut p = Profile::load(&dir);
        let mut r = result(false, 100.0, 1, 0, 0);
        r.events.extend(["qingqiu_entered", "qingqiu_guarded_fire"].map(String::from));
        r.journals.insert(1);
        p.record(&c, RunRecord { result: &r, tier: 1, attributes: false });
        p.save().unwrap();
        let q = Profile::load(&dir);
        assert_eq!(p, q);
        let seed = q.run_setup(&c, 1).story.unwrap();
        assert!(seed.events.contains("qingqiu_guarded_fire"));
        assert_eq!(seed.journals, BTreeSet::from([1]));
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn chapters_need_progress_even_if_the_first_night_is_cleared() {
        let mut p = Profile::default();
        assert_eq!(p.journal_chapter(), 1);
        p.events.insert("qingqiu_entered".into());
        assert_eq!(p.journal_chapter(), 2);
        p.events.insert("qingqiu_left_lantern".into());
        assert_eq!(p.journal_chapter(), 3);
        p.cleared = 1;
        p.runs = 1;
        p.meta.insert("luck".into(), 6);
        p.journals.extend(1..=24);
        assert_eq!(p.journal_chapter(), 3, "首通也不能揭露卷五");
        p.runs = 4;
        assert_eq!(p.journal_chapter(), 4);
        p.runs = 6;
        assert_eq!(p.journal_chapter(), 4, "没从深处回来不能开卷五");
        p.endless.insert(1, EndlessBest { seconds: 900.0, bosses: 1, kills: 1 });
        assert_eq!(p.journal_chapter(), 5);
        p.meta.clear();
        assert_eq!(p.journal_chapter(), 4);
    }

    /// 没听过的追问先说；说出口就记进存档，这一趟里照样说（重画不换句），下一趟不再说。
    #[test]
    fn childs_question_is_heard_once_and_stays_for_this_visit() {
        let c = content();
        let mut p = Profile { cleared: 1, ..Default::default() };
        let mut news = HubNews::default();
        assert!(p.hub_line(&c, 2, &news).unwrap().contains("回头看"), "追问优先于初见");
        assert!(p.hub_lines_seen.is_empty(), "查询不会记录听过");
        // 选中的是别人时，灯童的追问还没说出口，不能记成听过。
        for who in [0, 1, 3] {
            p.saw_hub(&c, who, &mut news);
        }
        assert!(!p.hub_lines_seen.contains("qingqiu_asked_dark") && !p.met.contains("child"));
        assert!(p.saw_hub(&c, 2, &mut news));
        assert!(p.hub_lines_seen.contains("qingqiu_asked_dark") && p.met.contains("child"));
        assert!(p.hub_line(&c, 2, &news).unwrap().contains("回头看"), "这一趟里重画不换句");
        assert!(!p.saw_hub(&c, 2, &mut news), "重画不重复写盘");
        // 下一趟：问过了不再问，也不倒回初见
        let line = p.hub_line(&c, 2, &HubNews::default()).unwrap();
        assert!(!line.contains("回头看") && !line.contains("你就是守灯人"), "{line}");
        // 护过火换一问，留了灯再换一问
        p.events.insert("qingqiu_guarded_fire".into());
        let mut news = HubNews::default();
        assert!(p.hub_line(&c, 2, &news).unwrap().contains("你走了以后"));
        assert!(p.saw_hub(&c, 2, &mut news));
        p.events.insert("qingqiu_left_lantern".into());
        let mut news = HubNews::default();
        assert!(p.hub_line(&c, 2, &news).unwrap().contains("替它们记"));
        assert!(p.saw_hub(&c, 2, &mut news));
        let q: Profile = ron::from_str(&ron::to_string(&p).unwrap()).unwrap();
        assert_eq!(q.hub_lines_seen.len(), 3);
        assert_eq!(p.hub_lines_seen, q.hub_lines_seen);
    }

    #[test]
    fn failed_nights_get_the_childs_response_before_any_clear_or_first_meeting() {
        let c = content();
        let news = HubNews::default();
        let mut fresh = Profile::default();
        assert!(fresh.hub_line(&c, 2, &news).unwrap().contains("你就是守灯人"));
        // 第一夜没走到狐村也先接住回来的人，不假称他已经见过小狐。
        let mut r = result(false, 1.0, 0, 0, 0);
        r.events.insert("qingqiu_entered".into());
        fresh.record(&c, RunRecord { result: &r, tier: 1, attributes: false });
        assert!(fresh.hub_line(&c, 2, &news).unwrap().contains("那边有没有灯"));
        for (beat, expected) in [
            (None, "qingqiu_asked_dark"),
            (Some("qingqiu_guarded_fire"), "qingqiu_asked_guarded"),
            (Some("qingqiu_left_lantern"), "qingqiu_asked_lit"),
        ] {
            if let Some(beat) = beat {
                r.events.insert(beat.into());
            }
            if beat == Some("qingqiu_left_lantern") {
                r.journals.insert(13);
            }
            // 每种经历都覆盖：结束后还没进灯驿就退出，重开仍要听到正确追问。
            let dir = temp(expected);
            let mut p = Profile::load(&dir);
            p.record(&c, RunRecord { result: &r, tier: 1, attributes: false });
            p.save().unwrap();
            let mut p = Profile::load(&dir);
            assert_eq!(p.cleared, 0);
            assert!(!p.met.contains("child"));
            assert!(!p.hub_lines_seen.contains(expected));
            // 追问应盖过初见、成就和挂着长命锁的台词。
            p.last.charm = Some("longevity".into());
            let mut news = HubNews { achievement: true, ..Default::default() };
            assert_eq!(p.hub_dialogue(&c, 2, &news).unwrap().once, expected);
            assert!(p.saw_hub(&c, 2, &mut news));
            p.save().unwrap();
            let mut p = Profile::load(&dir);
            assert!(p.hub_lines_seen.contains(expected));
            assert!(p.met.contains("child"));
            // 重开是新的一趟：问过的不再问，也不倒回较早的追问或初见
            let mut news = HubNews { achievement: true, ..Default::default() };
            let line = p.hub_dialogue(&c, 2, &news).unwrap();
            assert!(line.once.is_empty() && line.when != HubWhen::First, "{}", line.text);
            assert!(!p.saw_hub(&c, 2, &mut news));
            if beat == Some("qingqiu_left_lantern") {
                assert!(p.journals.contains(&13));
            }
            let _ = std::fs::remove_dir_all(dir);
        }
    }

    #[test]
    fn guarded_question_never_falls_back_to_unseen_dark_question_after_a_clear() {
        let c = content();
        let mut p = Profile { cleared: 1, ..Default::default() };
        p.events.insert("qingqiu_guarded_fire".into());
        assert!(p.saw_hub(&c, 2, &mut HubNews::default()));
        assert!(p.hub_lines_seen.contains("qingqiu_asked_guarded"));
        assert!(!p.hub_lines_seen.contains("qingqiu_asked_dark"));
        assert!(!p.saw_hub(&c, 2, &mut HubNews::default()), "下一趟也不补问没护火时那一问");
    }

    /// docs/BALANCE.md 10.4.1：前十局的点亮时间表（cost_exp 2.0）。
    #[test]
    fn first_ten_runs_have_meaningful_lights_without_victory_rewards() {
        let c = content();
        let route = [
            (1, "luck"),
            (2, "seal"),
            (3, "ember"),
            (4, "wu_fire"),
            (5, "afterglow"),
            (6, "wick"),
            (7, "wu_wood"),
            (8, "seal"),
            (10, "slot"),
        ];
        let minimum = [1, 2, 3, 4, 5, 6, 7, 8, 8, 9];
        // 第 8 局封印 2 级 600，第 10 局灯坠栏 1600
        let balances = [30, 230, 330, 430, 330, 630, 730, 630, 1130, 30];
        let mut p = Profile::default();
        for run in 1..=10 {
            // 灯油来自实际结算入口；不依赖通关、香火加成或成就赠油。
            let r = result(false, 180.0, 0, if run == 1 { 230 } else { 500 }, 0);
            p.record(&c, RunRecord { result: &r, tier: 1, attributes: false });
            for &(_, id) in route.iter().filter(|(at, _)| *at == run) {
                assert_eq!(p.next_meta_intro(&c).unwrap().id, id, "界面指引与节奏表一致");
                assert!(p.buy_meta(&c, id), "第 {run} 局应能点亮 {id}");
            }
            assert_eq!(p.meta_levels(&c), minimum[run - 1]);
            assert_eq!(p.oil, balances[run - 1]);
        }
        assert!(p.next_meta_intro(&c).is_none());
        assert_eq!(p.meta.len(), 8, "九级心灯覆盖八个不同节点");
        // 即便一直在约三分钟倒下，选廉价新功能也不必连续攒三局。
        let route = [(1, "luck"), (2, "wick"), (4, "seal"), (5, "ember"), (7, "wu_fire"), (9, "wu_wood")];
        let mut p = Profile::default();
        for run in 1..=10 {
            p.oil += 230;
            for &(_, id) in route.iter().filter(|(at, _)| *at == run) {
                assert!(p.buy_meta(&c, id));
            }
        }
        assert_eq!(p.meta_levels(&c), 6);
    }

    #[test]
    fn hub_seen_lines_survive_v2_migration_and_roundtrip() {
        let c = content();
        let old = r#"(version: 2, oil: 321, runs: 3, wins: 1, cleared: 1, meta: {"luck": 2})"#;
        let mut p: Profile = ron::from_str(old).unwrap();
        assert!(p.hub_lines_seen.is_empty());
        assert!(p.upgrade(&c));
        assert_eq!((p.oil, p.meta_level("luck"), p.runs, p.wins), (321, 2, 3, 1));
        assert!(p.hub_lines_seen.is_empty(), "旧存档不补记听过的台词");
        assert!(!p.upgrade(&c));
        let mut news = HubNews::default();
        p.met.insert("teller".into());
        assert!(p.saw_hub(&c, 3, &mut news));
        assert!(p.hub_lines_seen.contains("teller_first_dawn"));
        let restored: Profile = ron::from_str(&ron::to_string(&p).unwrap()).unwrap();
        assert_eq!(restored, p);
    }

    #[test]
    fn hub_milestones_queue_once_and_survive_text_and_order_changes() {
        let mut c = content();
        let mut p = Profile { runs: 10, wins: 1, ..Default::default() };
        p.meta.insert("luck".into(), 1);
        let mut news = HubNews { meta_lit: true, ..Default::default() };
        assert_eq!(p.hub_dialogue(&c, 0, &news).unwrap().when, HubWhen::First);
        assert!(!p.saw_hub(&c, 0, &mut news));
        assert!(p.hub_lines_seen.is_empty(), "初见遮住的里程碑不能被确认");
        p.met.extend(["smith", "peddler", "child", "teller"].map(String::from));
        assert_eq!(p.hub_dialogue(&c, 0, &news).unwrap().once, "smith_first_light");
        assert_eq!(p.hub_dialogue(&c, 2, &news).unwrap().once, "child_ten_returns");
        assert_eq!(p.hub_dialogue(&c, 3, &news).unwrap().once, "teller_first_dawn");
        for who in 0..c.hub.len() {
            p.saw_hub(&c, who, &mut news);
        }
        // 下一趟：听过的不再说，排着的下一句接上
        let mut news = HubNews { meta_lit: true, ..Default::default() };
        assert_eq!(p.hub_dialogue(&c, 2, &news).unwrap().once, "child_three_returns");
        let saved = ron::to_string(&p).unwrap();
        let mut p: Profile = ron::from_str(&saved).unwrap();
        // 改文字、调顺序都不影响听过的记录
        let line = c.hub[0].lines.iter_mut().find(|l| l.once == "smith_first_light").unwrap();
        line.text = "新稿".into();
        c.hub[0].lines.reverse();
        assert_eq!(p.hub_dialogue(&c, 0, &news).unwrap().when, HubWhen::MetaLit);
        p.saw_hub(&c, 2, &mut news);
        assert!(p.hub_dialogue(&c, 2, &HubNews::default()).unwrap().once.is_empty());
        assert!(!p.hub_lines_seen.contains("smith_ember"));
        p.meta.insert("ember".into(), 1);
        assert_eq!(p.hub_dialogue(&c, 0, &news).unwrap().once, "smith_ember");
    }

    /// 路灯：回来一回添一盏，最多十盏；这次归来新添的那盏记在 HubNews 里，给长卷演点亮。
    #[test]
    fn each_return_lights_one_more_road_lamp() {
        let c = content();
        let mut p = Profile::default();
        assert_eq!(p.road_lamps(), 0);
        let r = result(false, 60.0, 0, 0, 0);
        for run in 1..=12u32 {
            let before = p.clone();
            let got = p.record(&c, RunRecord { result: &r, tier: 1, attributes: false });
            let news = HubNews::after_run(&c, &before, &p, &r, &got);
            assert_eq!(p.road_lamps(), run.min(ROAD_LAMPS));
            assert_eq!(news.road_lit, (run <= ROAD_LAMPS).then(|| run as usize - 1));
        }
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
