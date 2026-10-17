//! 卡片上的文字（移植自网页版 ui/optionText.ts）：选项的名称、说明、品阶，以及共鸣进度和进化线索。

use bevy::prelude::*;

use lantern_content::{Content, Effect, Element, PassiveDef, WeaponLevel};
use lantern_sim::{Arsenal, Build, Offer};

/// 品阶。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Rarity {
    Tian,
    Xuan,
    Ling,
    Fan,
    Yi,
    He,
}

impl Rarity {
    pub fn name(self) -> &'static str {
        match self {
            Rarity::Yi => "异化",
            Rarity::He => "合璧",
            Rarity::Tian => "天品",
            Rarity::Xuan => "玄品",
            Rarity::Ling => "灵品",
            Rarity::Fan => "凡品",
        }
    }

    pub fn color(self) -> Color {
        match self {
            Rarity::Yi => hex("#CF8CDB"),
            Rarity::He => hex("#F6BD62"),
            Rarity::Tian => hex("#FFD98A"),
            Rarity::Xuan => hex("#B07CF0"),
            Rarity::Ling => hex("#6FB8FF"),
            Rarity::Fan => hex("#A9AEC2"),
        }
    }
}

/// #RRGGBB → 颜色（内容校验保证格式正确）。
pub(crate) fn hex(s: &str) -> Color {
    let v = u32::from_str_radix(s.trim_start_matches('#'), 16).unwrap_or(0xffffff);
    Color::srgb_u8((v >> 16) as u8, (v >> 8) as u8, v as u8)
}

pub(crate) fn element_color(c: &Content, e: Element) -> Color {
    hex(&c.element(e).color)
}

/// 心法的颜色：无属性心法用素白。
pub(crate) fn passive_color(c: &Content, e: Option<Element>) -> Color {
    e.map_or(hex("#E6DFD0"), |e| element_color(c, e))
}

pub(crate) struct OfferInfo {
    pub rarity: Rarity,
    pub kind: String,
    /// 图集里的图标名；图集里没有就用 glyph
    pub icon: Option<String>,
    pub glyph: String,
    pub color: Color,
    pub name: String,
    /// 卡面那一行收益（LORE-TEXT 第 6 节，≤ 12 字）
    pub gain: String,
    /// 收益前面的数值图标（`ui/stat_*`）：心法按它第一条属性效果取，其余没有
    pub gain_icon: Option<String>,
    /// 完整说明：聚焦时卡片下方显示一行，图鉴里也是它
    pub desc: String,
    /// 卡面插画的帧名（`ui/card_<id>`）；图集里没有就放大图标
    pub art: String,
    /// 选完以后的等级和满级，画成等级点；进化、合璧、补给没有
    pub level: Option<(u32, u32)>,
    /// 配对：法器卡画它的进化心法，心法卡画它能让哪件法器进化
    pub pair: Option<Pair>,
    pub element: Option<Element>,
}

/// 进化配对的另一半。
pub(crate) struct Pair {
    pub icon: String,
    pub glyph: String,
    pub color: Color,
    pub name: String,
    /// 已经有了：亮着画
    pub owned: bool,
}

pub(crate) struct OfferNote {
    /// 高亮颜色；None 表示普通提示
    pub color: Option<Color>,
    pub title: String,
    pub body: String,
}

/// 法器升一级时数值的变化，例如“伤害 +4　冷却 -0.1 秒”（LORE-TEXT 6.1 节：不带句号，冷却一位小数）。
pub(crate) fn weapon_upgrade_text(a: &WeaponLevel, b: &WeaponLevel) -> String {
    let mut parts = Vec::new();
    if b.count != a.count {
        parts.push(format!("数量 +{}", b.count as i64 - a.count as i64));
    }
    if b.damage != a.damage {
        parts.push(format!("伤害 +{}", (b.damage - a.damage).round()));
    }
    if b.radius != a.radius {
        parts.push(format!("范围 +{}", (b.radius - a.radius).round()));
    }
    if b.pierce != a.pierce {
        parts.push(format!("穿透 +{}", b.pierce as i64 - a.pierce as i64));
    }
    if b.cooldown != a.cooldown {
        let d = a.cooldown - b.cooldown;
        // 一位小数会写成 0 时多留一位，免得看着像没变
        let d = if (d * 10.0).round() == 0.0 { format!("{d:.2}") } else { format!("{d:.1}") };
        parts.push(format!("冷却 -{d} 秒"));
    }
    if parts.is_empty() { "全面提升".into() } else { parts.join("　") }
}

/// 短句没写时退回说明的第一句。
fn short_or(short: &str, desc: &str) -> String {
    if short.is_empty() {
        desc.split(['，', '。', '；', '\n']).next().unwrap_or(desc).to_string()
    } else {
        short.to_string()
    }
}

/// 法器的进化心法。
fn weapon_pair(c: &Content, build: &Build, w: usize) -> Option<Pair> {
    let p = c.passive_index(&c.weapons[w].evolution.as_ref()?.passive)?;
    let def = &c.passives[p];
    Some(Pair {
        icon: format!("ui/icon_{}", def.id),
        glyph: def.name.chars().next().map(String::from).unwrap_or_default(),
        color: passive_color(c, def.element),
        name: def.name.clone(),
        owned: build.passive_level(p) > 0,
    })
}

/// 心法能让哪件法器进化：先找身上还没变过的，没有就取内容里第一件。
fn passive_pair(c: &Content, arsenal: &Arsenal, p: usize) -> Option<Pair> {
    let id = &c.passives[p].id;
    let keyed = |w: usize| c.weapons[w].evolution.as_ref().is_some_and(|e| &e.passive == id);
    let owned = arsenal.0.iter().find(|w| !w.transformed() && keyed(w.def)).map(|w| w.def);
    let w = owned.or_else(|| (0..c.weapons.len()).find(|&w| keyed(w)))?;
    let def = &c.weapons[w];
    Some(Pair {
        icon: format!("ui/icon_{}", def.id),
        glyph: def.icon.clone(),
        color: element_color(c, def.element),
        name: def.name.clone(),
        owned: owned.is_some(),
    })
}

pub(crate) fn offer_info(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> OfferInfo {
    let supply = |id: &str, glyph: &str, name: &str, gain: String, desc: String, color: Color| OfferInfo {
        rarity: Rarity::Fan,
        kind: "补给".into(),
        icon: Some(format!("ui/icon_{id}")),
        glyph: glyph.into(),
        color,
        name: name.into(),
        gain,
        desc,
        art: format!("ui/card_{id}"),
        level: None,
        pair: None,
        gain_icon: None,
        element: None,
    };
    match offer {
        Offer::Heal => {
            let pct = (c.run.choices.heal * 100.0).round();
            supply(
                "lotus",
                "莲",
                "莲子",
                format!("回复 {pct}% 生命"),
                format!("回复 {pct}% 生命。"),
                hex("#6FD6A0"),
            )
        }
        Offer::Oil => {
            let oil = c.run.choices.oil;
            supply(
                "oil",
                "油",
                "灯油",
                format!("灯油 +{oil}"),
                format!("本局结算灯油 +{oil}。"),
                hex("#FFD98A"),
            )
        }
        Offer::Evolve(k) => {
            let def = &c.weapons[arsenal.0[k].def];
            let evo = def.evolution.as_ref().expect("能进化的法器有进化数据");
            OfferInfo {
                rarity: Rarity::Tian,
                kind: "进化".into(),
                icon: Some(format!("ui/icon_{}_evo", def.id)),
                glyph: def.icon.clone(),
                color: element_color(c, def.element),
                name: evo.name.clone(),
                gain: short_or(&evo.short, &evo.desc),
                desc: evo.desc.clone(),
                art: format!("ui/card_{}_evo", def.id),
                level: None,
                pair: None,
                gain_icon: None,
                element: Some(def.element),
            }
        }
        Offer::Mutate(k) => {
            let def = &c.weapons[arsenal.0[k].def];
            let m = def.mutation.as_ref().expect("异化数据");
            OfferInfo {
                rarity: Rarity::Yi,
                kind: "异化 · 不可合璧".into(),
                icon: Some(format!("ui/icon_{}_evo", def.id)),
                glyph: "异".into(),
                color: Rarity::Yi.color(),
                name: m.name.clone(),
                gain: short_or(&m.short, &m.desc),
                desc: m.desc.clone(),
                art: format!("ui/card_{}_mut", def.id),
                level: None,
                pair: None,
                gain_icon: None,
                element: Some(def.element),
            }
        }
        Offer::Fuse { fusion_id, .. } => {
            let f = &c.fusions[fusion_id];
            let def = &c.weapons[c.weapon_index(&f.weapons[0]).expect("合璧材料")];
            // 灯坠“断剑”在身时合璧不腾格子
            let kind = if build.charms.iter().any(|&k| c.charms[k].max_weapons.is_some()) {
                "合璧 · 仍占两格"
            } else {
                "合璧 · 腾出一格"
            };
            OfferInfo {
                rarity: Rarity::He,
                kind: kind.into(),
                icon: Some(format!("ui/icon_{}_evo", def.id)),
                glyph: "合".into(),
                color: Rarity::He.color(),
                name: f.name.clone(),
                gain: short_or(&f.short, &f.desc),
                desc: f.desc.clone(),
                art: format!("ui/card_{}", f.id),
                level: None,
                pair: None,
                gain_icon: None,
                element: Some(def.element),
            }
        }
        Offer::NewWeapon(d) => {
            let def = &c.weapons[d];
            OfferInfo {
                rarity: Rarity::Xuan,
                kind: "新法器".into(),
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.icon.clone(),
                color: element_color(c, def.element),
                name: def.name.clone(),
                gain: short_or(&def.short, &def.desc),
                desc: def.desc.clone(),
                art: format!("ui/card_{}", def.id),
                level: Some((1, def.levels.len() as u32)),
                pair: weapon_pair(c, build, d),
                gain_icon: None,
                element: Some(def.element),
            }
        }
        Offer::WeaponUp(k) => {
            let w = &arsenal.0[k];
            let def = &c.weapons[w.def];
            let lv = w.level as usize;
            let gain = weapon_upgrade_text(&def.levels[lv - 1], &def.levels[lv.min(def.levels.len() - 1)]);
            OfferInfo {
                rarity: Rarity::Ling,
                kind: "法器".into(),
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.icon.clone(),
                color: element_color(c, def.element),
                name: def.name.clone(),
                desc: format!("{gain}。"),
                gain,
                art: format!("ui/card_{}", def.id),
                level: Some((w.level + 1, def.levels.len() as u32)),
                pair: weapon_pair(c, build, w.def),
                gain_icon: None,
                element: Some(def.element),
            }
        }
        Offer::NewPassive(d) | Offer::PassiveUp(d) => {
            let (p, kind, rarity, level) = match offer {
                Offer::NewPassive(_) => (d, "新心法", Rarity::Ling, 1),
                _ => {
                    let p = build.passives[d];
                    (p.def, "心法", Rarity::Fan, p.level + 1)
                }
            };
            let def = &c.passives[p];
            OfferInfo {
                rarity,
                kind: kind.into(),
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.name.chars().next().map(String::from).unwrap_or_default(),
                color: passive_color(c, def.element),
                name: def.name.clone(),
                gain: short_or(&def.short, &def.desc),
                desc: format!("{}。", def.desc),
                art: format!("ui/card_{}", def.id),
                level: Some((level, def.max_level)),
                pair: passive_pair(c, arsenal, p),
                gain_icon: passive_stat_icon(c, def),
                element: def.element,
            }
        }
    }
}

/// 心法的主属性图标：每级效果（或第一级效果）里第一条加减属性的那一项，`stat_labels.ron` 给了图标才有。
fn passive_stat_icon(c: &Content, def: &PassiveDef) -> Option<String> {
    let first = def.per_level.iter().chain(def.levels.iter().flatten()).find_map(|e| match e {
        Effect::Add(s, _) | Effect::Mul(s, _) => Some(*s),
        _ => None,
    })?;
    c.stat_icon(first).map(|i| format!("ui/stat_{i}"))
}

/// 卡面收益下面那一行：共鸣、进化、异化、合璧亮色写；普通的只写五行点数变化，细节放进聚焦说明。
pub(crate) fn offer_note(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> Option<OfferNote> {
    resonance_note(c, arsenal, build, offer)
}

/// 共鸣进度、相生与进化线索，只读取当前构筑。
fn resonance_note(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> Option<OfferNote> {
    let gold = hex("#FFD98A");
    let el = offer.element(c, arsenal, build)?;
    if let Offer::Mutate(_) = offer {
        return Some(OfferNote {
            color: Some(Rarity::Yi.color()),
            title: "另辟一途，不能回头".into(),
            body: "与正统进化互斥；异化之后，失去合璧资格。".into(),
        });
    }
    if let Offer::Fuse { a, b, .. } = offer {
        return Some(OfferNote {
            color: Some(Rarity::He.color()),
            title: format!("{} + {}", arsenal.0[a].name(c), arsenal.0[b].name(c)),
            body: "两器合一；两系各计四点".into(),
        });
    }
    if let Offer::Evolve(k) = offer {
        let def = &c.weapons[arsenal.0[k].def];
        let evo = def.evolution.as_ref()?;
        let passive = c.passive_index(&evo.passive).map(|p| c.passives[p].name.as_str()).unwrap_or("");
        // 异化与合璧打开时，才提示正统进化保留合璧之路
        let path = if c.run.transformations { "；走正统，保留合璧之路" } else { "" };
        return Some(OfferNote {
            color: Some(gold),
            title: "选择后立即进化".into(),
            body: format!("{} Lv{} + {}{path}", def.name, def.levels.len(), passive),
        });
    }
    let from = build.points[el.index()];
    // 按投入计点：升级后的点数减去升级前的
    let ep = &c.elements;
    let gain = match offer {
        Offer::NewWeapon(_) => ep.weapon_points(1, false),
        Offer::NewPassive(_) => ep.passive_points(1),
        Offer::WeaponUp(k) => {
            let w = &arsenal.0[k];
            ep.weapon_points(w.level + 1, false) - ep.weapon_points(w.level, false)
        }
        Offer::PassiveUp(k) => {
            let p = build.passives[k];
            ep.passive_points(p.level + 1) - ep.passive_points(p.level)
        }
        _ => 0,
    };
    let to = from + gain;
    let th = &c.elements.thresholds;
    let tier = |n: u32| th.iter().filter(|&&t| n >= t).count();
    let e = c.element(el);
    if tier(to) > tier(from) {
        let t = tier(to);
        let mut body = e.tiers[t - 1].desc.clone();
        if t == 1
            && let Some(s) = c.elements.sheng.iter().find(|s| {
                (s.from == el && build.tiers[s.to.index()] >= 1)
                    || (s.to == el && build.tiers[s.from.index()] >= 1)
            })
        {
            body.push_str(&format!("，并点亮「{}」", s.name));
        }
        let what = if t == th.len() { "达成" } else { "激活" };
        return Some(OfferNote {
            color: Some(element_color(c, el)),
            title: format!("{} {from} → {to} · 共鸣{what}", e.name),
            body,
        });
    }
    let progress =
        if gain > 0 { format!("{} {from} → {to}", e.name) } else { format!("{} {from}", e.name) };
    match offer {
        Offer::NewWeapon(_) | Offer::WeaponUp(_) => {
            let (def, lv_after) = match offer {
                Offer::NewWeapon(d) => (&c.weapons[d], 1),
                Offer::WeaponUp(k) => (&c.weapons[arsenal.0[k].def], arsenal.0[k].level as usize + 1),
                _ => unreachable!(),
            };
            let evo = def.evolution.as_ref()?;
            let passive = c.passive_index(&evo.passive)?;
            if lv_after >= def.levels.len() && build.passive_level(passive) > 0 {
                return Some(OfferNote {
                    color: Some(gold),
                    title: "满级 · 下次升级可进化".into(),
                    body: format!("→ {}", evo.name),
                });
            }
            Some(OfferNote {
                color: None,
                title: progress,
                body: format!("进化需心法「{}」", c.passives[passive].name),
            })
        }
        _ => {
            let pid = match offer {
                Offer::NewPassive(d) => &c.passives[d].id,
                Offer::PassiveUp(k) => &c.passives[build.passives[k].def].id,
                _ => unreachable!(),
            };
            let owned = arsenal.0.iter().find(|w| {
                !w.transformed() && c.weapons[w.def].evolution.as_ref().is_some_and(|e| &e.passive == pid)
            });
            if let Some(w) = owned {
                let def = &c.weapons[w.def];
                let evo = def.evolution.as_ref()?;
                return Some(if w.level as usize >= def.levels.len() {
                    OfferNote {
                        color: Some(gold),
                        title: "可进化".into(),
                        body: format!("{} → {}", def.name, evo.name),
                    }
                } else {
                    OfferNote {
                        color: None, title: progress, body: format!("{} 满级后可进化", def.name)
                    }
                });
            }
            Some(OfferNote { color: None, title: progress, body: String::new() })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn level(cooldown: f32, damage: f32, count: u32) -> WeaponLevel {
        WeaponLevel { cooldown, damage, count, ..WeaponLevel::default() }
    }

    #[test]
    fn upgrade_line_has_no_period_and_one_decimal_cooldown() {
        assert_eq!(weapon_upgrade_text(&level(1.0, 10.0, 1), &level(0.9, 14.0, 1)), "伤害 +4　冷却 -0.1 秒");
        assert_eq!(weapon_upgrade_text(&level(1.0, 10.0, 1), &level(1.0, 10.0, 2)), "数量 +1");
        // 太小的冷却变化多留一位，不写成 -0.0
        assert_eq!(weapon_upgrade_text(&level(1.0, 10.0, 1), &level(0.96, 10.0, 1)), "冷却 -0.04 秒");
        assert_eq!(weapon_upgrade_text(&level(1.0, 10.0, 1), &level(1.0, 10.0, 1)), "全面提升");
    }

    #[test]
    fn missing_short_falls_back_to_the_first_clause() {
        assert_eq!(short_or("暴击率 +5%", "暴击率 +5%，别的"), "暴击率 +5%");
        assert_eq!(short_or("", "魂火价值 +6%，升级时 5% 概率多一个选项。"), "魂火价值 +6%");
    }

    /// 心法卡的收益图标取第一条属性效果：每级都加的、逐级写的都算；没画图标的属性不画。
    #[test]
    fn passive_gain_icon_follows_its_first_stat() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
        let c = Content::load(&root).unwrap();
        let icon = |id: &str| passive_stat_icon(&c, &c.passives[c.passive_index(id).unwrap()]);
        assert_eq!(icon("jixing").as_deref(), Some("ui/stat_speed"));
        assert_eq!(icon("zhezhi").as_deref(), Some("ui/stat_count"));
        assert_eq!(icon("xunfeng"), None);
    }
}
