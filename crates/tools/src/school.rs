//! 流派机器人和组合机器人（docs/BALANCE.md 第 11 节、docs/GAMEPLAY.md 第 7 节）。
//!
//! 只改选择：升级、余烬、灯坠偏向某个流派（或某个反应的两系）；走位还是风筝机器人。
//! 其他选择交给 `bot::respond`。P0 只有五件法器、三盏灯、八枚灯坠，流派里缺的关键件先空着。

use lantern_content::{Content, Element};
use lantern_sim::build::{occupied_slots, weapon_slots};
use lantern_sim::{Offer, RunSetup, SimCommand, SimHarness, SimPhase, bot};

/// 一种选卡偏好。
pub struct Plan {
    pub name: String,
    /// 带哪盏灯（没有这盏灯时用默认的）
    pub lamp: Option<&'static str>,
    /// 核心法器、心法、灯坠（按 ID）
    pub weapons: Vec<String>,
    pub passives: Vec<String>,
    pub charms: Vec<String>,
    /// 偏向的五行
    pub elements: Vec<Element>,
    /// 太极：哪一系还没到一阶，就优先补哪一系
    pub even: bool,
}

/// 八个流派：名字、灯、法器、心法、灯坠、五行。
const SCHOOLS: [(&str, &str, &[&str], &[&str], &[&str], &[Element]); 8] = [
    (
        "剑修",
        "mirror",
        &["sword", "coin_sword"],
        &["jianyi", "ruimu", "xunfeng"],
        &["broken_sword"],
        &[Element::Metal],
    ),
    ("百鸟", "", &["crane", "vine"], &["zhezhi", "huichun", "jixing"], &["longevity"], &[Element::Wood]),
    ("寒川", "frost", &["bell", "wave"], &["jingxin", "hanyi", "yinhun"], &["ice_soul"], &[Element::Water]),
    (
        "星火",
        "red",
        &["lamp", "sky_lantern"],
        &["changming", "luxin", "dengxin"],
        &["wind_wheel"],
        &[Element::Fire],
    ),
    (
        "不动",
        "",
        &["seal", "tower"],
        &["houde", "panshi", "zaiwu"],
        &["pillar", "longevity"],
        &[Element::Earth],
    ),
    ("身法", "", &[], &["qinggong", "jixing"], &["wind_wheel"], &[]),
    ("照夜", "", &["lamp"], &["dengxin", "changming"], &["night_pearl"], &[]),
    ("太极", "", &["lamp", "sword", "bell", "crane", "seal"], &[], &["five_coins"], &Element::ALL),
];

pub const SCHOOL_NAMES: &str = "剑修、百鸟、寒川、星火、不动、身法、照夜、太极";

impl Plan {
    /// 流派机器人。
    pub fn school(name: &str) -> Option<Plan> {
        let &(n, lamp, weapons, passives, charms, elements) = SCHOOLS.iter().find(|s| s.0 == name)?;
        let ids = |v: &[&str]| v.iter().map(|s| s.to_string()).collect();
        Some(Plan {
            name: n.to_string(),
            lamp: (!lamp.is_empty()).then_some(lamp),
            weapons: ids(weapons),
            passives: ids(passives),
            charms: ids(charms),
            elements: elements.to_vec(),
            even: n == "太极",
        })
    }

    /// 组合机器人：凑某个反应（`elements.ron` 里 reactions 的 ID 或名字），两系的法器、心法都要。
    pub fn combo(content: &Content, name: &str) -> Option<Plan> {
        let r = content.elements.reactions.iter().find(|r| r.id == name || r.name == name)?;
        let els = [r.a, r.b];
        Some(Plan {
            name: format!("反应·{}", r.name),
            lamp: None,
            weapons: content
                .weapons
                .iter()
                .filter(|w| els.contains(&w.element))
                .map(|w| w.id.clone())
                .collect(),
            passives: Vec::new(),
            charms: vec!["five_coins".into()],
            elements: els.to_vec(),
            even: true,
        })
    }

    /// 合璧路线：优先拿两件材料和两门心法钥匙，其余新法器照常补满法器栏；升级仍来自正常卡池。
    pub fn fusion(content: &Content, id: &str) -> Option<Plan> {
        let f = content.fusions.iter().find(|f| f.id == id || f.name == id)?;
        let defs: Vec<_> = f
            .weapons
            .iter()
            .map(|id| &content.weapons[content.weapon_index(id).expect("合璧材料")])
            .collect();
        Some(Plan {
            name: format!("合璧·{}", f.name),
            lamp: if f.weapons.contains(&"bell".into()) {
                Some("frost")
            } else if f.weapons.contains(&"sword".into()) {
                Some("mirror")
            } else {
                Some("red")
            },
            weapons: f.weapons.to_vec(),
            passives: defs.iter().map(|d| d.evolution.as_ref().expect("正统进化").passive.clone()).collect(),
            charms: Vec::new(),
            elements: defs.iter().map(|d| d.element).collect(),
            even: false,
        })
    }

    /// 出发前：换成流派的灯，出发灯坠换成流派的（灯坠池里有的话）。
    pub fn apply(&self, content: &Content, setup: &mut RunSetup) {
        if let Some(l) = self.lamp
            && content.lamp_index(l).is_some()
        {
            setup.lamp = Some(l.to_string());
        }
        if setup.charms.is_empty() {
            return;
        }
        let pool = |id: &&String| setup.charm_pool.iter().any(|p| p == *id) || setup.charms.contains(id);
        if let Some(c) = self.charms.iter().find(pool) {
            setup.charms = vec![c.clone()];
        }
    }

    /// 升级选项的分数：进化 > 核心法器 > 本系心法 > 本系其他 > 别的。
    fn score(&self, sim: &SimHarness, content: &Content, offer: Offer) -> i32 {
        let arsenal = &sim.arsenal().0;
        let build = sim.build();
        // 太极、组合：还没到一阶的那一系加分
        let bonus = |e: Element| if self.even && build.tiers[e.index()] == 0 { 40 } else { 0 };
        match offer {
            Offer::Fuse { .. } => 1200,
            Offer::Evolve(_) => 1000,
            Offer::Mutate(_) => 950,
            Offer::WeaponUp(k) => {
                let def = &content.weapons[arsenal[k].def];
                if self.weapons.contains(&def.id) {
                    120
                } else if self.elements.contains(&def.element) {
                    100
                } else {
                    55
                }
            }
            Offer::NewWeapon(d) => {
                let def = &content.weapons[d];
                let room = occupied_slots(content, sim.arsenal(), build) < weapon_slots(content, build);
                if !room {
                    5
                } else if self.weapons.contains(&def.id) {
                    110 + bonus(def.element)
                } else if self.name.starts_with("合璧·") {
                    // 合璧路线也补满四件法器，材料优先
                    60
                } else if self.elements.contains(&def.element) {
                    95 + bonus(def.element)
                } else {
                    45
                }
            }
            Offer::NewPassive(d) => self.passive(sim, content, d, false),
            Offer::PassiveUp(k) => self.passive(sim, content, build.passives[k].def, true),
            Offer::Heal | Offer::Oil => 1,
        }
    }

    fn passive(&self, sim: &SimHarness, content: &Content, d: usize, up: bool) -> i32 {
        let def = &content.passives[d];
        let build = sim.build();
        // 手上某件法器进化要的心法，先拿到
        let evo = sim.arsenal().0.iter().any(|w| {
            !w.transformed() && content.weapons[w.def].evolution.as_ref().is_some_and(|e| e.passive == def.id)
        });
        if evo && !up {
            return 105;
        }
        if let Some(i) = self.passives.iter().position(|p| p == &def.id) {
            return 100 - i as i32 * 3;
        }
        let Some(e) = def.element.filter(|e| self.elements.contains(e)) else {
            return if def.element.is_none() { 30 } else { 25 };
        };
        if !self.even {
            return 85;
        }
        // 太极、组合：每系先有一门心法，别让同一系占满心法栏；没到一阶的那一系加分
        let held =
            |e: Element| build.passives.iter().filter(|p| content.passives[p.def].element == Some(e)).count();
        let lacking = if build.tiers[e.index()] == 0 { 40 } else { 0 };
        if up {
            85 + lacking
        } else if held(e) == 0 {
            125
        } else if self.elements.iter().any(|&x| held(x) == 0) {
            20
        } else {
            85 + lacking
        }
    }

    /// 选择阶段替玩家下命令。
    pub fn respond(&self, sim: &SimHarness, content: &Content) -> Vec<SimCommand> {
        match sim.phase() {
            SimPhase::LevelUp => {
                let Some(choice) = &sim.flow().choice else { return Vec::new() };
                let best = choice
                    .offers
                    .iter()
                    .enumerate()
                    .max_by_key(|&(i, &o)| (self.score(sim, content, o), -(i as i32)))
                    .map_or(0, |(i, _)| i);
                vec![SimCommand::Choose(best as u8)]
            }
            SimPhase::Charm => self.charm(sim, content).unwrap_or_else(|| bot::respond(sim)),
            _ => bot::respond(sim),
        }
    }

    /// 灯坠：流派的灯坠优先；栏满了就换下一枚不是流派的。
    fn charm(&self, sim: &SimHarness, content: &Content) -> Option<Vec<SimCommand>> {
        let choice = sim.flow().charm.as_ref()?;
        let worn = &sim.build().charms;
        let ours = |k: usize| self.charms.iter().any(|c| c == &content.charms[k].id);
        let replace = worn.iter().position(|&k| !ours(k));
        if let Some(p) = choice.picked {
            return Some(vec![match replace {
                Some(slot) if ours(choice.offers[p]) => SimCommand::Choose(slot as u8),
                _ => SimCommand::Skip,
            }]);
        }
        let i = choice.offers.iter().position(|&k| ours(k) && !worn.contains(&k))?;
        let free = worn.len() < lantern_sim::charms::charm_slots(sim.stats());
        (free || replace.is_some()).then(|| vec![SimCommand::Choose(i as u8)])
    }
}

/// 机器人走一步：选择用 plan（没有就用 `bot::respond`），Play 阶段按 input 走、燃灯充满就放。
pub fn step(
    sim: &mut SimHarness,
    content: &Content,
    plan: Option<&Plan>,
    input: lantern_sim::InputFrame,
    cmds: &[SimCommand],
) {
    let Some(plan) = plan else {
        bot::step(sim, input, cmds);
        return;
    };
    let mut all = plan.respond(sim, content);
    if sim.phase() == SimPhase::Play {
        all.extend_from_slice(cmds);
        all.extend(bot::altar_interact(sim));
        if sim.progress().ult >= 1.0 {
            all.push(SimCommand::Ult);
        }
    }
    sim.step(input, &all);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 流派表里写的法器、心法、灯坠、灯都在数据里；每种反应都能组出组合机器人。
    #[test]
    fn plans_name_real_content() {
        let c = Content::load(&crate::data_dir()).unwrap();
        for name in SCHOOL_NAMES.split('、') {
            let p = Plan::school(name).unwrap_or_else(|| panic!("没有流派 {name}"));
            assert!(p.weapons.iter().all(|id| c.weapon_index(id).is_some()), "{name} 的法器");
            assert!(p.passives.iter().all(|id| c.passive_index(id).is_some()), "{name} 的心法");
            assert!(p.charms.iter().all(|id| c.charm_index(id).is_some()), "{name} 的灯坠");
            assert!(p.lamp.is_none_or(|l| c.lamp_index(l).is_some()), "{name} 的灯");
        }
        for r in &c.elements.reactions {
            let p = Plan::combo(&c, &r.id).unwrap();
            assert!(!p.weapons.is_empty(), "{} 两系都没有法器", r.name);
        }
    }
}
