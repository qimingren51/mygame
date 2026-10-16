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
                desc: m.desc.clone(),
                flavor: m.flavor.clone(),
                element: Some(def.element),
            }
        }
        Offer::Fuse { fusion_id, .. } => {
            let f = &c.fusions[fusion_id];
            let def = &c.weapons[c.weapon_index(&f.weapons[0]).expect("合璧材料")];
            OfferInfo {
                rarity: Rarity::He,
                kind: "合璧".into(),
                icon: Some(format!("ui/icon_{}_evo", def.id)),
                glyph: "合".into(),
                color: Rarity::He.color(),
                name: f.name.clone(),
                desc: f.desc.clone(),
                flavor: f.flavor.clone(),
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

/// 共鸣、进化优先；普通升级把首项收益提到卡面中心，完整描述仍由卡片保留。
pub(crate) fn offer_note(
    c: &Content,
    arsenal: &Arsenal,
    build: &Build,
    offer: Offer,
    desc: &str,
) -> OfferNote {
    emphasize_note(offer, desc, resonance_note(c, arsenal, build, offer))
}

fn emphasize_note(offer: Offer, desc: &str, note: Option<OfferNote>) -> OfferNote {
    let note = match note {
        Some(n) if n.color.is_some() || matches!(offer, Offer::NewWeapon(_)) => return n,
        note => note,
    };
    // 保留首项里的等级条件（如折纸），不把条件收益误写成每级必得。
    let title = desc.split(['，', '。', '；', '\n']).next().unwrap_or(desc).to_string();
    let body = note.map_or_else(String::new, |n| {
        if n.body.is_empty() { n.title } else { format!("{}\n{}", n.title, n.body) }
    });
    OfferNote { color: None, title, body }
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
        let slots = if build.charms.iter().any(|&k| c.charms[k].max_weapons.is_some()) {
            "断剑在身，仍占两格"
        } else {
            "两器合一，腾出一格"
        };
        return Some(OfferNote {
            color: Some(Rarity::He.color()),
            title: slots.into(),
            body: format!("{} + {}；两系各计四点", arsenal.0[a].name(c), arsenal.0[b].name(c)),
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

    #[test]
    fn resonance_and_evolution_take_priority_over_numeric_gain() {
        for title in ["金 2 → 3 · 共鸣激活", "满级 · 下次升级可进化"] {
            let note = emphasize_note(
                Offer::WeaponUp(0),
                "伤害 +4，冷却 -0.10 秒。",
                Some(OfferNote {
                    color: Some(Color::WHITE), title: title.into(), body: "进化线索".into()
                }),
            );
            assert_eq!(note.title, title);
            assert_eq!(note.body, "进化线索");
        }
    }

    #[test]
    fn ordinary_upgrade_emphasizes_gain_and_keeps_resonance_hint() {
        let note = emphasize_note(
            Offer::WeaponUp(0),
            "伤害 +4，冷却 -0.10 秒。",
            Some(OfferNote {
                color: None, title: "金 1".into(), body: "进化需心法「剑意」".into()
            }),
        );
        assert_eq!(note.title, "伤害 +4");
        assert_eq!(note.body, "金 1\n进化需心法「剑意」");
        assert!(note.color.is_none());
    }

    #[test]
    fn conditional_and_neutral_gains_keep_their_meaning() {
        for (offer, desc, expected) in [
            (Offer::PassiveUp(0), "1 / 3 / 5 级时数量 +1。", "1 / 3 / 5 级时数量 +1"),
            (Offer::NewPassive(0), "魂火价值 +6%，升级时 5% 概率多一个选项。", "魂火价值 +6%"),
            (Offer::Heal, "回复 30% 生命。", "回复 30% 生命"),
            (Offer::Oil, "本局结算灯油 +15。", "本局结算灯油 +15"),
        ] {
            let note = emphasize_note(offer, desc, None);
            assert_eq!(note.title, expected);
        }
    }
}
