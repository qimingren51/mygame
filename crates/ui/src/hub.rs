//! 灯驿（docs/GAMEPLAY.md 第 11.6 节）：老灯匠（心灯）、货郎（属性）、灯童（成就）、说书人（图鉴）；
//! 以及出发前的准备：选更、择灯、挂灯坠、选悟、开关属性。
//!
//! 输入和面板的切换在 title 模块里，这里只画面板、处理各面板自己的选择。

use bevy::prelude::*;

use lantern_content::{Content, Reward};
use lantern_platform::{Actions, HubNews, Profile};
use lantern_view::atlas::AtlasDb;

use crate::choice::spawn_icon;
use crate::describe::{element_color, hex};
use crate::skin::Skin;
use crate::title::{TitleUi, clickable, dim_layer, focus, panel};
use crate::{Fonts, INK, INK_DIM, PAPER, on_paper, text};

const GOLD: &str = "#E8C27A";
const OIL: &str = "#FFD98A";

/// 灯驿里的四个人物：(人物, 管什么, 字)
pub(crate) const HUB: [(&str, &str, &str); 4] = [
    ("老灯匠", "心灯 · 收灯油", "匠"),
    ("货郎", "属性 · 收铜钱", "货"),
    ("灯童", "成就", "童"),
    ("说书人", "图鉴", "书"),
];

/// 属性铺的列数。
pub(crate) const SHOP_COLUMNS: usize = 2;

/// 出发前准备的一行。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PrepRow {
    /// 夜行 / 无尽夜（通关一更后出现）
    Mode,
    Tier,
    Lamp,
    Charm,
    Insight,
    /// `attributes.ron` 下标
    Attribute(usize),
    Go,
}

/// 准备面板里的行：悟只在点亮过时出现；属性只列买过的。
pub(crate) fn prep_rows(c: &Content, profile: &Profile) -> Vec<PrepRow> {
    let mut v = Vec::new();
    if profile.endless_unlocked() {
        v.push(PrepRow::Mode);
    }
    v.extend([PrepRow::Tier, PrepRow::Lamp, PrepRow::Charm]);
    if !profile.insights(c).is_empty() {
        v.push(PrepRow::Insight);
    }
    for (k, a) in c.attributes.list.iter().enumerate() {
        if profile.attribute_level(&a.id) > 0 {
            v.push(PrepRow::Attribute(k));
        }
    }
    v.push(PrepRow::Go);
    v
}

/// 上次的选择里不可用的项退回默认（灯：第一盏初始灯；灯坠、悟：不选）。
pub(crate) fn normalize_last(c: &Content, profile: &mut Profile) {
    let tier = profile.tier.max(1);
    let last = &profile.last;
    let lamp = last
        .lamp
        .clone()
        .filter(|id| profile.lamp_unlocked(c, id))
        .or_else(|| c.lamps.iter().find(|l| l.initial).map(|l| l.id.clone()));
    let charm = last.charm.clone().filter(|id| profile.charm_unlocked(c, id));
    let insight = last.insight.filter(|e| profile.insights(c).contains(e));
    let endless = last.endless && profile.endless_unlocked();
    let tier = last.tier.clamp(1, max_tier(profile, endless).min(tier));
    profile.last.endless = endless;
    profile.last.lamp = lamp;
    profile.last.charm = charm;
    profile.last.insight = insight;
    profile.last.tier = tier;
}

/// 能选到第几更：无尽夜只能选通关过的更。
fn max_tier(profile: &Profile, endless: bool) -> u8 {
    if endless { profile.cleared.max(1) } else { profile.tier.max(1) }
}

/// 在可选项里前后挪一格（循环）。
fn cycle<T: Clone + PartialEq>(options: &[T], current: &T, dir: i32) -> T {
    let i = options.iter().position(|o| o == current).unwrap_or(0) as i32;
    options[(i + dir).rem_euclid(options.len() as i32) as usize].clone()
}

/// 准备面板的结果。
pub(crate) enum PrepAction {
    None,
    Back,
    Go,
}

/// 准备面板：↑↓ 选行，←→ 改这一行，Enter 改下一个（出发那一行就出发）。改的是 `profile.last`。
pub(crate) fn prep_input(
    actions: &Actions,
    c: &Content,
    profile: &mut Profile,
    ui: &mut TitleUi,
    clicked: Option<usize>,
) -> PrepAction {
    let rows = prep_rows(c, profile);
    let n = rows.len();
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h.min(n - 1);
    }
    if actions.nav.y != 0 {
        ui.selected = (ui.selected as i32 + actions.nav.y).rem_euclid(n as i32) as usize;
    }
    if ui.selected >= n {
        ui.selected = n - 1;
    }
    if actions.back {
        return PrepAction::Back;
    }
    let pressed = clicked.inspect(|&i| ui.selected = i).is_some() || actions.confirm;
    let dir = if actions.nav.x != 0 { actions.nav.x } else { i32::from(pressed) };
    if dir == 0 {
        return PrepAction::None;
    }
    match rows[ui.selected] {
        PrepRow::Go if pressed => return PrepAction::Go,
        PrepRow::Go => return PrepAction::None,
        PrepRow::Mode => {
            profile.last.endless = !profile.last.endless;
            profile.last.tier = profile.last.tier.min(max_tier(profile, profile.last.endless));
        }
        PrepRow::Tier => {
            let tiers: Vec<u8> = (1..=max_tier(profile, profile.last.endless)).collect();
            profile.last.tier = cycle(&tiers, &profile.last.tier, dir);
        }
        PrepRow::Lamp => {
            let lamps: Vec<Option<String>> = c
                .lamps
                .iter()
                .filter(|l| profile.lamp_unlocked(c, &l.id))
                .map(|l| Some(l.id.clone()))
                .collect();
            profile.last.lamp = cycle(&lamps, &profile.last.lamp, dir);
        }
        PrepRow::Charm => {
            let mut charms = vec![None];
            charms.extend(profile.charm_pool(c).into_iter().map(Some));
            profile.last.charm = cycle(&charms, &profile.last.charm, dir);
        }
        PrepRow::Insight => {
            let mut ins = vec![None];
            ins.extend(profile.insights(c).into_iter().map(Some));
            profile.last.insight = cycle(&ins, &profile.last.insight, dir);
        }
        PrepRow::Attribute(k) => {
            let id = c.attributes.list[k].id.clone();
            profile.toggle_attribute(c, &id);
        }
    }
    ui.dirty = true;
    PrepAction::None
}

/// 灯的光色往往很浅，写在纸上时和墨色对半调一下。
fn ink_tint(c: Color) -> Color {
    let (a, b) = (c.to_srgba(), INK.to_srgba());
    Color::srgb((a.red + b.red) * 0.5, (a.green + b.green) * 0.5, (a.blue + b.blue) * 0.5)
}

/// 一行文字，限宽自动换行。
fn para(fonts: &Fonts, size: f32, color: Color, s: &str, width: f32) -> impl Bundle {
    (text(&fonts.body, size, color, s), Node { max_width: px(width), ..default() })
}

/// 面板外框：标题、副标题、分隔线，内容由 body 画。
fn frame(
    commands: &mut Commands,
    fonts: &Fonts,
    skin: &Skin,
    width: f32,
    title: &str,
    sub: &str,
    hint: &str,
    body: impl FnOnce(&mut ChildSpawnerCommands),
) {
    commands.spawn(panel()).with_children(|p| {
        p.spawn(dim_layer());
        p.spawn((
            Node {
                width: px(width),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                padding: UiRect::axes(px(52), px(34)),
                row_gap: px(8),
                ..default()
            },
            skin.image("panel"),
        ))
        .with_children(|panel| {
            panel.spawn(text(&fonts.title, 56.0, INK, title));
            if !sub.is_empty() {
                panel.spawn(text(&fonts.body, 17.0, INK_DIM, sub));
            }
            panel.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
            body(panel);
        });
        p.spawn(text(&fonts.body, 18.0, PAPER, hint));
    });
}

/// 钱袋：灯油、铜钱。
pub(crate) fn purses(profile: &Profile) -> String {
    format!("灯油 {}　·　铜钱 {}", profile.oil, profile.gold)
}

pub(crate) fn hub_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    db: &AtlasDb,
    profile: &Profile,
    news: &HubNews,
) {
    frame(
        commands,
        fonts,
        skin,
        1080.0,
        "灯驿",
        &purses(profile),
        "← → 选择　Enter　进去　　Esc　返回",
        |panel| {
            panel
                .spawn(Node { column_gap: px(22), padding: UiRect::top(px(10)), ..default() })
                .with_children(|row| {
                    for (i, (who, what, glyph)) in HUB.iter().enumerate() {
                        let mut card = row.spawn((
                            Node {
                                width: px(210),
                                min_height: px(250),
                                flex_direction: FlexDirection::Column,
                                align_items: AlignItems::Center,
                                padding: UiRect::axes(px(20), px(24)),
                                row_gap: px(12),
                                ..default()
                            },
                            skin.image("card_omen"),
                        ));
                        card.with_children(|card| {
                            card.spawn(focus(skin, "card_focus", i, 6.0));
                            let icon = format!("ui/icon_hub_{i}");
                            spawn_icon(card, db, fonts, Some(&icon), glyph, INK, 84.0);
                            card.spawn(text(&fonts.title, 40.0, INK, who));
                            card.spawn(text(&fonts.body, 16.0, INK_DIM, what));
                            // 人物这次说的一句（docs/LORE-TEXT.md 第 1 节）
                            if let Some(line) = profile.hub_line(c, i, news) {
                                card.spawn(para(fonts, 14.0, INK, &format!("“{line}”"), 170.0));
                            }
                            card.spawn(Node { flex_grow: 1.0, ..default() });
                            card.spawn(text(&fonts.title, 22.0, INK_DIM, &format!("{}", i + 1)));
                        });
                        clickable(&mut card, i);
                    }
                });
        },
    );
}

/// 属性铺：Enter 买一级；最后一项全部退还。
pub(crate) fn shop_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    profile: &Profile,
) {
    let a = &c.attributes;
    let sub = format!(
        "铜钱 {}　·　每买一级，所有属性涨价 {}%　·　已买 {} 级",
        profile.gold,
        (a.inflation * 100.0).round(),
        profile.attributes_bought()
    );
    let hint = "方向键 选择　Enter　买一级　　出发前可以单独关掉　　Esc　返回";
    frame(commands, fonts, skin, 1120.0, "货郎 · 属性", &sub, hint, |panel| {
        panel
            .spawn(Node { width: percent(100), flex_wrap: FlexWrap::Wrap, row_gap: px(4), ..default() })
            .with_children(|g| {
                for (i, attr) in a.list.iter().enumerate() {
                    let lv = profile.attribute_level(&attr.id);
                    let price = profile.attribute_price(c, &attr.id);
                    let can = price.is_some_and(|x| profile.gold >= x);
                    let label = match price {
                        None => "已满".to_string(),
                        Some(x) if can => format!("{x} 铜钱"),
                        Some(x) => format!("{x} 铜钱　差 {}", x - profile.gold),
                    };
                    let mut row = g.spawn(Node {
                        width: percent(100.0 / SHOP_COLUMNS as f32),
                        flex_direction: FlexDirection::Column,
                        padding: UiRect::axes(px(14), px(6)),
                        row_gap: px(2),
                        ..default()
                    });
                    row.with_children(|r| {
                        r.spawn(focus(skin, "focus_ring", i, 2.0));
                        r.spawn(Node { column_gap: px(8), align_items: AlignItems::Center, ..default() })
                            .with_children(|h| {
                                h.spawn(text(&fonts.title, 26.0, INK, &attr.name));
                                for k in 0..attr.max_level {
                                    h.spawn((
                                        Node { width: px(12), height: px(12), ..default() },
                                        skin.image(if k < lv { "pip_on" } else { "pip" }),
                                    ));
                                }
                                h.spawn(text(
                                    &fonts.body,
                                    14.0,
                                    if can { on_paper(hex(GOLD)) } else { INK_DIM },
                                    &label,
                                ));
                            });
                        r.spawn(text(&fonts.body, 13.0, INK_DIM, &attr.desc));
                    });
                    clickable(&mut row, i);
                }
            });
        let i = a.list.len();
        let mut refund = panel.spawn(Node { padding: UiRect::axes(px(24), px(8)), ..default() });
        refund.with_children(|r| {
            r.spawn(focus(skin, "focus_ring", i, 2.0));
            let s = if profile.attributes_spent > 0 {
                format!("全部退还（返还 {} 铜钱）", profile.attributes_spent)
            } else {
                "全部退还".to_string()
            };
            r.spawn(text(&fonts.title, 24.0, INK, &s));
        });
        clickable(&mut refund, i);
    });
}

fn reward_text(c: &Content, r: &Reward) -> String {
    match r {
        Reward::Basics => "开放心灯、属性、夜签，出发前可以挂灯坠".into(),
        Reward::Lamp(id) => {
            format!("灯「{}」", c.lamp_index(id).map_or(id.as_str(), |k| c.lamps[k].name.as_str()))
        }
        Reward::Charm(id) => {
            format!("灯坠「{}」", c.charm_index(id).map_or(id.as_str(), |k| c.charms[k].name.as_str()))
        }
        Reward::Tier(t) => {
            c.difficulty.get(*t as usize - 1).map_or("下一更", |d| d.name.as_str()).to_string()
        }
        Reward::Gold(n) => format!("{n} 铜钱"),
        Reward::Oil(n) => format!("{n} 灯油"),
    }
}

pub(crate) fn achievements_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    profile: &Profile,
) {
    let done = c.achievements.iter().filter(|a| profile.achievements.contains(&a.id)).count();
    let sub = format!("已达成 {done} / {}", c.achievements.len());
    frame(commands, fonts, skin, 1160.0, "灯童 · 成就", &sub, "Esc　返回", |panel| {
        panel
            .spawn(Node { width: percent(100), flex_wrap: FlexWrap::Wrap, row_gap: px(6), ..default() })
            .with_children(|g| {
                for a in &c.achievements {
                    let got = profile.achievements.contains(&a.id);
                    let rewards: Vec<String> = a.rewards.iter().map(|r| reward_text(c, r)).collect();
                    g.spawn(Node {
                        width: percent(50),
                        flex_direction: FlexDirection::Column,
                        padding: UiRect::axes(px(12), px(3)),
                        ..default()
                    })
                    .with_children(|r| {
                        r.spawn(Node { column_gap: px(10), align_items: AlignItems::Center, ..default() })
                            .with_children(|h| {
                                h.spawn(text(&fonts.title, 22.0, if got { INK } else { INK_DIM }, &a.name));
                                h.spawn(text(
                                    &fonts.body,
                                    14.0,
                                    if got { on_paper(hex(OIL)) } else { INK_DIM },
                                    if got { "已达成" } else { "" },
                                ));
                            });
                        r.spawn(para(
                            fonts,
                            13.0,
                            INK_DIM,
                            &format!("{}　→　{}", a.desc, rewards.join("、")),
                            500.0,
                        ));
                    });
                }
            });
    });
}

/// 一句话描述另起一行；没有就是空的。
fn flavor_line(flavor: &str) -> String {
    if flavor.is_empty() { String::new() } else { format!("\n{flavor}") }
}

/// 无尽夜各更的最长存活；没打过时是空的。
fn endless_line(c: &Content, profile: &Profile) -> String {
    let v: Vec<String> = profile
        .endless
        .iter()
        .filter(|(_, b)| b.seconds > 0.0)
        .map(|(&t, b)| format!("{} {}", tier_name(c, t), mmss(f64::from(b.seconds))))
        .collect();
    if v.is_empty() { String::new() } else { format!("无尽夜最长　{}", v.join("　·　")) }
}

fn mmss(secs: f64) -> String {
    let s = secs.max(0.0) as u64;
    if s >= 3600 {
        format!("{} 小时 {} 分", s / 3600, s % 3600 / 60)
    } else {
        format!("{} 分 {} 秒", s / 60, s % 60)
    }
}

/// 说书人：见过的反应和累计统计（P0 的图鉴先做五行谱里的反应）。
pub(crate) fn codex_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    profile: &Profile,
) {
    let seen = (0..c.elements.reactions.len()).filter(|&k| profile.reactions & (1 << k) != 0).count();
    let sub = format!("五行谱 · 见过的反应 {seen} / {}", c.elements.reactions.len());
    frame(
        commands,
        fonts,
        skin,
        1120.0,
        "说书人 · 图鉴",
        &sub,
        "M / 手柄 X　手记　　Esc　返回",
        |panel| {
            panel
                .spawn(Node { width: percent(100), flex_wrap: FlexWrap::Wrap, row_gap: px(6), ..default() })
                .with_children(|g| {
                    for (k, r) in c.elements.reactions.iter().enumerate() {
                        let known = profile.reactions & (1 << k) != 0;
                        g.spawn(Node {
                            width: percent(50),
                            flex_direction: FlexDirection::Column,
                            padding: UiRect::axes(px(12), px(3)),
                            ..default()
                        })
                        .with_children(|row| {
                            let color = if known { on_paper(element_color(c, r.b)) } else { INK_DIM };
                            let pair = format!(
                                "{}{} · {}",
                                c.element(r.a).name,
                                c.element(r.b).name,
                                if known { r.name.as_str() } else { "？？？" }
                            );
                            row.spawn(text(&fonts.title, 22.0, color, &pair));
                            let desc = if known { r.desc.as_str() } else { "还没见过" };
                            row.spawn(para(fonts, 13.0, INK_DIM, desc, 500.0));
                        });
                    }
                });
            panel.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
            let t = &profile.totals;
            let lines = [
                format!(
                    "夜行 {} 次　·　天明 {} 次　·　通关到 {}",
                    profile.runs,
                    profile.wins,
                    tier_name(c, profile.cleared)
                ),
                format!("累计击杀 {}　·　累计时长 {}", t.kills, mmss(t.seconds)),
                endless_line(c, profile),
                format!(
                    "累计铜钱 {}　·　累计灯油 {}　·　点亮石灯笼 {}　·　进化 {}",
                    t.gold, t.oil, t.lanterns, t.evolutions
                ),
            ];
            for l in lines.iter().filter(|l| !l.is_empty()) {
                panel.spawn(text(&fonts.body, 16.0, INK, l));
            }
            panel
                .spawn((
                    Node { padding: UiRect::all(px(10)), ..default() },
                    text(&fonts.body, 20.0, INK, "翻看手记"),
                ))
                .observe(
                    |_: On<bevy::picking::events::PointerClick>,
                     mut reader: ResMut<crate::journals::Reader>| {
                        reader.open = true;
                    },
                );
        },
    );
}

fn tier_name(c: &Content, tier: u8) -> &str {
    if tier == 0 {
        "——"
    } else {
        c.difficulty.get(tier as usize - 1).map_or("——", |d| d.name.as_str())
    }
}

/// 出发前：选更、择灯、挂灯坠、选悟、开关属性。
pub(crate) fn prep_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    db: &AtlasDb,
    profile: &Profile,
) {
    let rows = prep_rows(c, profile);
    let last = &profile.last;
    let hint = "↑ ↓ 选择　← → 更换　Enter　出发　　Esc　返回";
    frame(
        commands,
        fonts,
        skin,
        960.0,
        "出发",
        "地区 · 青丘（其余地区抢先体验开放）",
        hint,
        |panel| {
            for (i, row) in rows.iter().enumerate() {
                // (标签, 值, 值的颜色, 说明, 图标)
                let (label, value, color, desc, icon): (
                    &str,
                    String,
                    Color,
                    String,
                    Option<(String, String)>,
                ) = match *row {
                    PrepRow::Mode if last.endless => {
                        let best = profile
                            .endless
                            .get(&last.tier)
                            .filter(|b| b.seconds > 0.0)
                            .map_or(String::new(), |b| {
                                format!("　这一更最长 {}", mmss(f64::from(b.seconds)))
                            });
                        (
                            "玩法",
                            "无尽夜".into(),
                            on_paper(hex("#B07CF0")),
                            format!(
                                "不等天明，往梦的深处走：夜主倒下也不天明，每 5 分钟妖潮过后它再来，一次比一次凶{best}"
                            ),
                            None,
                        )
                    }
                    PrepRow::Mode => {
                        ("玩法", "夜行".into(), INK, "一夜 10 分钟，击败夜主迎来天明".into(), None)
                    }
                    PrepRow::Tier => {
                        let d = c.difficulty.get(last.tier as usize - 1);
                        let locked = if last.endless {
                            "　（无尽夜只能选通关过的更）"
                        } else if profile.tier < c.difficulty.len() as u8 {
                            "　（通关上一更开放下一更）"
                        } else {
                            ""
                        };
                        (
                            "更",
                            d.map_or(String::new(), |d| d.name.clone()),
                            INK,
                            format!("{}{locked}", d.map_or("", |d| d.desc.as_str())),
                            None,
                        )
                    }
                    PrepRow::Lamp => {
                        let k = last.lamp.as_deref().and_then(|id| c.lamp_index(id)).unwrap_or(0);
                        let l = &c.lamps[k];
                        let weapon =
                            c.weapon_index(&l.start_weapon).map_or("", |w| c.weapons[w].name.as_str());
                        let locked = c.lamps.iter().filter(|x| !profile.lamp_unlocked(c, &x.id)).count();
                        let more = if locked > 0 {
                            format!("　（还有 {locked} 盏未解锁）")
                        } else {
                            String::new()
                        };
                        (
                            "灯",
                            l.name.clone(),
                            ink_tint(hex(&l.color)),
                            format!(
                                "{} · 起手「{weapon}」　＋ {}　－ {}{more}{}",
                                l.school,
                                l.good,
                                l.bad,
                                flavor_line(&l.flavor)
                            ),
                            Some((format!("ui/icon_lamp_{}", l.id), l.name.chars().take(1).collect())),
                        )
                    }
                    PrepRow::Charm => match last.charm.as_deref().and_then(|id| c.charm_index(id)) {
                        Some(k) => {
                            let d = &c.charms[k];
                            (
                                "灯坠",
                                d.name.clone(),
                                on_paper(hex("#B07CF0")),
                                format!("＋ {}　－ {}{}", d.good, d.bad, flavor_line(&d.flavor)),
                                Some((format!("ui/icon_charm_{}", d.id), d.name.chars().take(1).collect())),
                            )
                        }
                        None => ("灯坠", "不挂".into(), INK_DIM, "出发前可以挂一枚已解锁的灯坠".into(), None),
                    },
                    PrepRow::Insight => match last.insight {
                        Some(e) => (
                            "悟",
                            format!("悟·{}", c.element(e).name),
                            on_paper(element_color(c, e)),
                            format!("{}系的升级选项更容易出现", c.element(e).name),
                            None,
                        ),
                        None => ("悟", "不选".into(), INK_DIM, "从点亮的悟·五行里选一个生效".into(), None),
                    },
                    PrepRow::Attribute(k) => {
                        let a = &c.attributes.list[k];
                        let on = profile.attribute_on(c, &a.id);
                        let lv = profile.attribute_level(&a.id);
                        (
                            "属性",
                            format!("{} Lv{lv}　{}", a.name, if on { "生效" } else { "关闭" }),
                            if on { INK } else { INK_DIM },
                            a.desc.clone(),
                            None,
                        )
                    }
                    PrepRow::Go => ("", "出发".into(), INK, String::new(), None),
                };
                let mut r = panel.spawn(Node {
                    width: percent(100),
                    align_items: AlignItems::Center,
                    column_gap: px(16),
                    padding: UiRect::axes(px(16), px(if *row == PrepRow::Go { 12.0 } else { 5.0 })),
                    justify_content: if *row == PrepRow::Go {
                        JustifyContent::Center
                    } else {
                        JustifyContent::Start
                    },
                    ..default()
                });
                r.with_children(|r| {
                    r.spawn(focus(skin, "focus_ring", i, 2.0));
                    if *row == PrepRow::Go {
                        r.spawn(text(&fonts.title, 40.0, INK, &value));
                        return;
                    }
                    r.spawn((text(&fonts.body, 16.0, INK_DIM, label), Node { width: px(48), ..default() }));
                    if let Some((name, glyph)) = &icon {
                        spawn_icon(r, db, fonts, Some(name), glyph, color, 40.0);
                    }
                    r.spawn(Node { flex_direction: FlexDirection::Column, flex_shrink: 1.0, ..default() })
                        .with_children(|t| {
                            // 马善政体没有箭头，箭头用正文字体
                            t.spawn(Node {
                                column_gap: px(10),
                                align_items: AlignItems::Center,
                                ..default()
                            })
                            .with_children(|v| {
                                v.spawn(text(&fonts.body, 14.0, INK_DIM, "◀"));
                                v.spawn(text(&fonts.title, 28.0, color, &value));
                                v.spawn(text(&fonts.body, 14.0, INK_DIM, "▶"));
                            });
                            if !desc.is_empty() {
                                t.spawn(para(fonts, 13.0, INK_DIM, &desc, 700.0));
                            }
                        });
                });
                clickable(&mut r, i);
            }
        },
    );
}
