//! 卡片上的文字（移植自网页版 ui/optionText.ts）：选项的名称、说明、品阶，以及共鸣进度和进化线索。

use bevy::prelude::*;

use lantern_content::{Content, Element, WeaponLevel};
use lantern_sim::{Arsenal, Build, Offer};

/// 品阶。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Rarity {
    Tian,
    Xuan,
    Ling,
    Fan,
}

impl Rarity {
    pub fn name(self) -> &'static str {
        match self {
            Rarity::Tian => "天品",
            Rarity::Xuan => "玄品",
            Rarity::Ling => "灵品",
            Rarity::Fan => "凡品",
        }
    }

    pub fn color(self) -> Color {
        match self {
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
    /// 图集里的图标名；补给没有图标，用 glyph
    pub icon: Option<String>,
    pub glyph: String,
    pub color: Color,
    pub name: String,
    pub desc: String,
    /// 一句话描述（LORE-TEXT 3.5、3.6 节）；只在头一回见到时写，升级和补给留空
    pub flavor: String,
    pub element: Option<Element>,
}

pub(crate) struct OfferNote {
    /// 高亮颜色；None 表示普通提示
    pub color: Option<Color>,
    pub title: String,
    pub body: String,
}

/// 法器升一级时数值的变化，例如“数量 +1，伤害 +4。”
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
        parts.push(format!("冷却 -{:.2} 秒", a.cooldown - b.cooldown));
    }
    if parts.is_empty() { "全面提升。".into() } else { format!("{}。", parts.join("，")) }
}

pub(crate) fn offer_info(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> OfferInfo {
    let supply = |glyph: &str, name: &str, desc: String, color: Color| OfferInfo {
        rarity: Rarity::Fan,
        kind: "补给".into(),
        icon: None,
        glyph: glyph.into(),
        color,
        name: name.into(),
        desc,
        flavor: String::new(),
        element: None,
    };
    match offer {
        Offer::Heal => supply(
            "莲",
            "莲子",
            format!("回复 {}% 生命。", (c.run.choices.heal * 100.0).round()),
            hex("#6FD6A0"),
        ),
        Offer::Oil => supply("油", "灯油", format!("本局结算灯油 +{}。", c.run.choices.oil), hex("#FFD98A")),
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
                desc: evo.desc.clone(),
                flavor: evo.flavor.clone(),
                element: Some(def.element),
            }
        }
        Offer::NewWeapon(d) => {
            let def = &c.weapons[d];
            OfferInfo {
                rarity: Rarity::Xuan,
                kind: "法器 · 新".into(),
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.icon.clone(),
                color: element_color(c, def.element),
                name: def.name.clone(),
                desc: def.desc.clone(),
                flavor: def.flavor.clone(),
                element: Some(def.element),
            }
        }
        Offer::WeaponUp(k) => {
            let w = &arsenal.0[k];
            let def = &c.weapons[w.def];
            let lv = w.level as usize;
            OfferInfo {
                rarity: Rarity::Ling,
                kind: format!("法器 · Lv{} → {}", lv, lv + 1),
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.icon.clone(),
                color: element_color(c, def.element),
                name: def.name.clone(),
                desc: weapon_upgrade_text(&def.levels[lv - 1], &def.levels[lv.min(def.levels.len() - 1)]),
                flavor: String::new(),
                element: Some(def.element),
            }
        }
        Offer::NewPassive(d) | Offer::PassiveUp(d) => {
            let (def, kind, rarity, new) = match offer {
                Offer::NewPassive(_) => (&c.passives[d], "心法 · 新".to_string(), Rarity::Ling, true),
                _ => {
                    let p = build.passives[d];
                    (
                        &c.passives[p.def],
                        format!("心法 · Lv{} → {}", p.level, p.level + 1),
                        Rarity::Fan,
                        false,
                    )
                }
            };
            OfferInfo {
                rarity,
                kind,
                icon: Some(format!("ui/icon_{}", def.id)),
                glyph: def.name.chars().next().map(String::from).unwrap_or_default(),
                color: passive_color(c, def.element),
                name: def.name.clone(),
                desc: format!("{}。", def.desc),
                flavor: if new { def.flavor.clone() } else { String::new() },
                element: def.element,
            }
        }
    }
}

/// 卡片底部的提示：共鸣进度、相生、进化线索。
pub(crate) fn offer_note(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> Option<OfferNote> {
    let gold = hex("#FFD98A");
    let el = offer.element(c, arsenal, build)?;
    if let Offer::Evolve(k) = offer {
        let def = &c.weapons[arsenal.0[k].def];
        let evo = def.evolution.as_ref()?;
        let passive = c.passive_index(&evo.passive).map(|p| c.passives[p].name.as_str()).unwrap_or("");
        return Some(OfferNote {
            color: Some(gold),
            title: "选择后立即进化".into(),
            body: format!("{} Lv{} + {}", def.name, def.levels.len(), passive),
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
                !w.evolved && c.weapons[w.def].evolution.as_ref().is_some_and(|e| &e.passive == pid)
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
