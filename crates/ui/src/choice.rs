//! 升级三选一、宝箱揭晓、进化演出（移植自网页版 ui/screens.ts）；点灯奖励、货郎。
//!
//! 模拟停在选择阶段时，这里画出对应的界面，把玩家的选择作为命令发给模拟。命令要等下一个模拟步才生效，
//! 发出后到界面刷新之前不再接受输入，避免连按把下一次升级也选掉。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::Actions;
use lantern_sim::flow::{ChestSource, Flow, LampReward};
use lantern_sim::{Arsenal, Build, GameContent, Offer, RunState, SimCommand, SimCommands, SimPhase};
use lantern_view::atlas::AtlasDb;

use crate::describe::{OfferInfo, Rarity, element_color, hex, offer_info, offer_note};
use crate::skin::Skin;
use crate::{DIM, Fonts, INK, INK_DIM, PAPER, on_paper, overlay_vignette, text};

/// 界面上现在画的是哪一个选择。变了就重画。
#[derive(Clone, Debug, PartialEq, Default)]
enum Shown {
    #[default]
    None,
    /// 选项、灵光一闪、余烬（开局心法要到的等级）
    LevelUp(Vec<Offer>, bool, u32),
    Chest(usize, ChestSource),
    Evolve(usize),
    Lamp(Vec<LampReward>),
    /// 货郎：宝箱价、灯坠价、有没有能给的灯坠
    Shop(u32, u32, bool),
    /// 灯坠三选一：选项、满格时选中的那一个、挂着的灯坠
    Charm(Vec<usize>, Option<usize>, Vec<usize>),
}

#[derive(Resource, Default)]
pub(crate) struct ChoiceUi {
    shown: Shown,
    selected: usize,
    /// 已经发出命令，等模拟处理
    waiting: bool,
    /// 打开了多久（防止上一个界面的按键直接把这个确认掉）
    age: f32,
    /// 鼠标点击、悬停
    clicked: Option<usize>,
    hovered: Option<usize>,
}

#[derive(Component)]
pub(crate) struct ChoiceRoot;

#[derive(Component)]
pub(crate) struct Card;

#[derive(Component)]
pub(crate) struct RerollLabel;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<ChoiceUi>().add_systems(OnExit(lantern_sim::AppState::Run), reset).add_systems(
        Update,
        (sync, input, highlight)
            .chain()
            .run_if(in_state(RunState::Playing))
            .run_if(resource_exists::<SimPhase>),
    );
}

fn reset(mut ui: ResMut<ChoiceUi>) {
    *ui = ChoiceUi::default();
}

fn current(phase: SimPhase, flow: &Flow, build: &Build) -> Shown {
    match phase {
        SimPhase::LevelUp => flow.choice.as_ref().map_or(Shown::None, |c| {
            Shown::LevelUp(c.offers.clone(), c.inspired, if c.ember { flow.ember } else { 0 })
        }),
        SimPhase::Chest => flow.chest.as_ref().map_or(Shown::None, |c| Shown::Chest(c.items.len(), c.source)),
        SimPhase::Evolve => flow.evolving.map_or(Shown::None, Shown::Evolve),
        SimPhase::Lantern => flow.lamp.clone().map_or(Shown::None, Shown::Lamp),
        SimPhase::Shop => {
            flow.shop.map_or(Shown::None, |s| Shown::Shop(s.chest_cost, s.charm_cost, s.charm_ok))
        }
        SimPhase::Charm => flow
            .charm
            .as_ref()
            .map_or(Shown::None, |ch| Shown::Charm(ch.offers.clone(), ch.picked, build.charms.clone())),
        _ => Shown::None,
    }
}

/// 模拟的选择阶段变了：重画界面。
fn sync(
    mut commands: Commands,
    time: Res<Time>,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    db: Res<AtlasDb>,
    skin: Res<Skin>,
    phase: Res<SimPhase>,
    flow: Res<Flow>,
    arsenal: Res<Arsenal>,
    build: Res<Build>,
    progress: Res<lantern_sim::Progress>,
    mut ui: ResMut<ChoiceUi>,
    roots: Query<Entity, With<ChoiceRoot>>,
) {
    ui.age += time.delta_secs();
    if flow.is_changed() {
        ui.waiting = false;
    }
    let now = current(*phase, &flow, &build);
    if now == ui.shown {
        return;
    }
    for e in &roots {
        commands.entity(e).despawn();
    }
    ui.shown = now.clone();
    ui.selected = 0;
    ui.age = 0.0;
    ui.waiting = false;
    ui.clicked = None;
    ui.hovered = None;
    let c = &content.0;
    match now {
        Shown::None => {}
        Shown::LevelUp(offers, inspired, ember) => {
            let level = flow.choice.as_ref().map_or(0, |ch| ch.level);
            spawn_level_up(
                &mut commands,
                c,
                &fonts,
                &db,
                &skin,
                &arsenal,
                &build,
                &offers,
                inspired,
                level,
                ember,
                flow.rerolls,
                flow.banishes,
            )
        }
        Shown::Chest(..) => {
            if let Some(chest) = &flow.chest {
                spawn_chest(&mut commands, c, &fonts, &db, &skin, &arsenal, &build, chest)
            }
        }
        Shown::Evolve(k) => spawn_evolve(&mut commands, c, &fonts, &db, &skin, &arsenal, k),
        Shown::Lamp(rewards) => spawn_lamp(&mut commands, c, &fonts, &db, &skin, &rewards),
        Shown::Shop(chest, charm, charms) => {
            let gold = progress.gold.floor() as u32;
            spawn_shop(&mut commands, &fonts, &db, &skin, chest, charm, gold, charms)
        }
        Shown::Charm(offers, picked, worn) => {
            spawn_charm(&mut commands, c, &fonts, &db, &skin, &offers, picked, &worn)
        }
    }
}

fn input(
    actions: Res<Actions>,
    phase: Res<SimPhase>,
    flow: Res<Flow>,
    build: Res<Build>,
    mut ui: ResMut<ChoiceUi>,
    mut sim: ResMut<SimCommands>,
) {
    let clicked = ui.clicked.take();
    if ui.waiting || ui.shown == Shown::None {
        return;
    }
    let mut send = |ui: &mut ChoiceUi, cmd: SimCommand| {
        sim.0.push(cmd);
        ui.waiting = true;
    };
    match *phase {
        SimPhase::LevelUp => {
            let n = flow.choice.as_ref().map_or(0, |c| c.offers.len());
            if n == 0 {
                return;
            }
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h.min(n - 1);
            }
            if actions.nav.x != 0 {
                ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(n as i32) as usize;
            }
            if ui.age < 0.25 {
                return;
            }
            if let Some(i) = actions.pick.map(usize::from).filter(|&i| i < n).or(clicked) {
                send(&mut ui, SimCommand::Choose(i as u8));
            } else if actions.confirm {
                let i = ui.selected;
                send(&mut ui, SimCommand::Choose(i as u8));
            } else if actions.reroll && flow.rerolls > 0 {
                send(&mut ui, SimCommand::Reroll);
            } else if actions.banish && flow.banishes > 0 {
                let i = ui.selected;
                send(&mut ui, SimCommand::Banish(i as u8));
            } else if actions.skip {
                send(&mut ui, SimCommand::Skip);
            }
        }
        SimPhase::Chest if ui.age > 0.4 && (actions.confirm || clicked.is_some()) => {
            send(&mut ui, SimCommand::Ack);
        }
        SimPhase::Lantern => {
            let n = flow.lamp.as_ref().map_or(0, |v| v.len());
            if n == 0 {
                return;
            }
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h.min(n - 1);
            }
            if actions.nav.x != 0 {
                ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(n as i32) as usize;
            }
            if ui.age < 0.25 {
                return;
            }
            if let Some(i) = actions.pick.map(usize::from).filter(|&i| i < n).or(clicked) {
                send(&mut ui, SimCommand::Choose(i as u8));
            } else if actions.confirm {
                let i = ui.selected;
                send(&mut ui, SimCommand::Choose(i as u8));
            }
        }
        SimPhase::Charm => {
            let Some(ch) = &flow.charm else { return };
            // 满格时在挂着的灯坠里选替换哪一枚
            let n = if ch.picked.is_some() { build.charms.len() } else { ch.offers.len() };
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h.min(n.saturating_sub(1));
            }
            if actions.nav.x != 0 && n > 0 {
                ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(n as i32) as usize;
            }
            if ui.age < 0.25 {
                return;
            }
            let chosen = actions
                .pick
                .map(usize::from)
                .filter(|&i| i < n)
                .or(clicked)
                .or(actions.confirm.then_some(ui.selected));
            if let Some(i) = chosen {
                send(&mut ui, SimCommand::Choose(i as u8));
            } else if actions.back || actions.skip {
                send(&mut ui, SimCommand::Skip);
            }
        }
        SimPhase::Shop => {
            // 0 宝箱、1 灯坠、2 离开
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h.min(2);
            }
            if actions.nav.x != 0 {
                ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(3) as usize;
            }
            if ui.age < 0.25 {
                return;
            }
            let chosen = actions
                .pick
                .map(usize::from)
                .filter(|&i| i < 3)
                .or(clicked)
                .or(actions.confirm.then_some(ui.selected));
            if actions.back || actions.skip || chosen == Some(2) {
                send(&mut ui, SimCommand::Skip);
            } else if let Some(i @ (0 | 1)) = chosen {
                send(&mut ui, SimCommand::Choose(i as u8));
            }
        }
        SimPhase::Evolve if ui.age > 2.1 || (ui.age > 0.5 && (actions.confirm || clicked.is_some())) => {
            send(&mut ui, SimCommand::Ack);
        }
        _ => {}
    }
}

/// 选中的卡片叠一层泥金焦点框。
fn highlight(
    ui: Res<ChoiceUi>,
    flow: Res<Flow>,
    mut focus: Query<(&CardFocus, &mut Visibility)>,
    mut reroll: Query<&mut Text, With<RerollLabel>>,
) {
    for (f, mut v) in &mut focus {
        v.set_if_neq(if f.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
    if flow.is_changed() {
        for mut t in &mut reroll {
            t.0 = format!("R / 手柄 Y　重抽（剩 {} 次）", flow.rerolls);
        }
    }
}

#[derive(Component)]
pub(crate) struct CardFocus(usize);

fn overlay(skin: &Skin) -> impl Bundle {
    (
        ChoiceRoot,
        DespawnOnExit(lantern_sim::AppState::Run),
        GlobalZIndex(10),
        Node {
            position_type: PositionType::Absolute,
            width: percent(100),
            height: percent(100),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: px(18),
            ..default()
        },
        BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.65)),
        children![overlay_vignette(skin)],
    )
}

/// 图标：图集里有就用图片，没有就用一个字。
pub(crate) fn spawn_icon(
    p: &mut ChildSpawnerCommands,
    db: &AtlasDb,
    fonts: &Fonts,
    name: Option<&str>,
    glyph: &str,
    color: Color,
    size: f32,
) {
    let node = Node {
        width: px(size),
        height: px(size),
        justify_content: JustifyContent::Center,
        align_items: AlignItems::Center,
        ..default()
    };
    match name.and_then(|n| db.find(n)) {
        Some(f) => {
            p.spawn((node, db.ui_image(f)));
        }
        None => {
            p.spawn(node).with_child((
                Text::new(glyph),
                TextFont::from(fonts.title.clone()).with_font_size(size * 0.7),
                TextColor(color),
            ));
        }
    }
}

fn card_skin(r: Rarity) -> &'static str {
    match r {
        Rarity::Tian => "card_tian",
        Rarity::Xuan => "card_xuan",
        Rarity::Ling => "card_ling",
        Rarity::Fan => "card_fan",
    }
}

fn card(
    commands: &mut ChildSpawnerCommands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    build: &Build,
    i: usize,
    offer: Offer,
) {
    let info: OfferInfo = offer_info(c, arsenal, build, offer);
    let note = offer_note(c, arsenal, build, offer);
    let el = info.element.map(|e| format!("{} 属性", c.element(e).name)).unwrap_or_default();
    let mut card = commands.spawn((
        Card,
        Node {
            width: px(240),
            min_height: px(340),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            padding: UiRect::axes(px(22), px(20)),
            row_gap: px(8),
            ..default()
        },
        skin.image(card_skin(info.rarity)),
    ));
    card.with_children(|card| {
        // 焦点框：和卡片一样大，叠在上面
        card.spawn((
            CardFocus(i),
            Visibility::Hidden,
            Node {
                position_type: PositionType::Absolute,
                left: px(-6),
                right: px(-6),
                top: px(-6),
                bottom: px(-6),
                ..default()
            },
            skin.image("card_focus"),
        ));
        card.spawn(Node { width: percent(100), justify_content: JustifyContent::SpaceBetween, ..default() })
            .with_children(|row| {
                row.spawn(text(&fonts.body, 14.0, on_paper(info.rarity.color()), info.rarity.name()));
                row.spawn(text(&fonts.body, 14.0, INK_DIM, &info.kind));
            });
        spawn_icon(card, db, fonts, info.icon.as_deref(), &info.glyph, on_paper(info.color), 88.0);
        card.spawn(text(&fonts.title, 36.0, on_paper(info.color), &info.name));
        card.spawn((text(&fonts.body, 16.0, INK, &info.desc), Node { max_width: px(196), ..default() }));
        card.spawn(text(&fonts.body, 13.0, INK_DIM, &el));
        card.spawn(Node { flex_grow: 1.0, ..default() });
        if let Some(n) = note {
            let box_skin = if n.color.is_some() { "note_box_hi" } else { "note_box" };
            card.spawn((
                Node {
                    width: percent(100),
                    flex_direction: FlexDirection::Column,
                    padding: UiRect::axes(px(10), px(8)),
                    row_gap: px(2),
                    ..default()
                },
                skin.image(box_skin),
            ))
            .with_children(|b| {
                b.spawn(text(&fonts.body, 14.0, n.color.map_or(INK_DIM, on_paper), &n.title));
                if !n.body.is_empty() {
                    b.spawn((
                        text(&fonts.body, 13.0, INK_DIM, &n.body),
                        Node { max_width: px(176), ..default() },
                    ));
                }
            });
        }
        card.spawn(text(&fonts.title, 22.0, INK_DIM, &format!("{}", i + 1)));
    });
    card.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
    card.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
}

fn spawn_level_up(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    build: &Build,
    offers: &[Offer],
    inspired: bool,
    level: u32,
    ember: u32,
    rerolls: u32,
    banishes: u32,
) {
    commands.spawn(overlay(skin)).with_children(|root| {
        root.spawn(Node {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            ..default()
        })
        .with_children(|head| {
            head.spawn(text(&fonts.title, 64.0, PAPER, if ember > 0 { "余烬" } else { "升级" }));
            let sub = if ember > 0 {
                format!("开局心法三选一　·　选中的那门直接到 Lv{ember}")
            } else if inspired {
                format!("Lv {} → {}　·　灵光一闪，多一个选项", level - 1, level)
            } else {
                format!("Lv {} → {}", level - 1, level)
            };
            head.spawn(text(&fonts.body, 18.0, if inspired { hex("#FFD98A") } else { DIM }, &sub));
        });
        root.spawn(Node { column_gap: px(22), ..default() }).with_children(|row| {
            for (i, &o) in offers.iter().enumerate() {
                card(row, c, fonts, db, skin, arsenal, build, i, o);
            }
        });
        root.spawn(Node { column_gap: px(36), ..default() }).with_children(|foot| {
            foot.spawn(text(&fonts.body, 16.0, PAPER, "1-4 / ← → + Enter　选择"));
            foot.spawn((
                RerollLabel,
                text(&fonts.body, 16.0, PAPER, &format!("R / 手柄 Y　重抽（剩 {rerolls} 次）")),
            ));
            if banishes > 0 {
                foot.spawn(text(
                    &fonts.body,
                    16.0,
                    PAPER,
                    &format!("C / 手柄 LB　封印选中项（剩 {banishes} 次）"),
                ));
            }
            let skip = if ember > 0 {
                "X / 手柄 X　跳过".to_string()
            } else {
                format!("X / 手柄 X　跳过（灯油 +{}）", c.run.choices.skip_oil)
            };
            foot.spawn(text(&fonts.body, 16.0, DIM, &skip));
        });
    });
}

/// 点灯奖励、货郎用的简单卡片。
#[allow(clippy::too_many_arguments)]
fn plain_card(
    row: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    i: usize,
    icon: Option<&str>,
    glyph: &str,
    color: Color,
    name: &str,
    desc: &str,
    enabled: bool,
) {
    let mut card = row.spawn((
        Card,
        Node {
            width: px(220),
            min_height: px(260),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            padding: UiRect::axes(px(22), px(22)),
            row_gap: px(10),
            ..default()
        },
        skin.image(if enabled { "card_ling" } else { "card_fan" }),
    ));
    card.with_children(|card| {
        card.spawn((
            CardFocus(i),
            Visibility::Hidden,
            Node {
                position_type: PositionType::Absolute,
                left: px(-6),
                right: px(-6),
                top: px(-6),
                bottom: px(-6),
                ..default()
            },
            skin.image("card_focus"),
        ));
        let c = if enabled { on_paper(color) } else { INK_DIM };
        spawn_icon(card, db, fonts, icon, glyph, c, 80.0);
        card.spawn(text(&fonts.title, 32.0, c, name));
        card.spawn((
            text(&fonts.body, 15.0, if enabled { INK } else { INK_DIM }, desc),
            Node { max_width: px(176), ..default() },
        ));
        card.spawn(Node { flex_grow: 1.0, ..default() });
        card.spawn(text(&fonts.title, 22.0, INK_DIM, &format!("{}", i + 1)));
    });
    card.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
    card.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
}

/// 点亮石灯笼后的三选一。
fn spawn_lamp(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    rewards: &[LampReward],
) {
    let l = &c.run.lanterns;
    commands.spawn(overlay(skin)).with_children(|root| {
        root.spawn(text(&fonts.title, 64.0, hex("#FFD98A"), "灯亮了"));
        root.spawn(text(&fonts.body, 18.0, DIM, "石灯笼照亮一方：区里的妖物减速、易伤"));
        root.spawn(Node { column_gap: px(22), ..default() }).with_children(|row| {
            for (i, r) in rewards.iter().enumerate() {
                let (icon, glyph, color, name, desc) = match r {
                    LampReward::Heal => (
                        Some("ui/icon_lotus"),
                        "愈",
                        hex("#FFB0C0"),
                        "回复",
                        format!("回复 {}% 生命", (l.heal * 100.0).round()),
                    ),
                    LampReward::Level => {
                        (Some("ui/icon_level"), "升", hex("#9FE3FF"), "升级", "立即获得一次升级".to_string())
                    }
                    LampReward::Gold => (None, "金", hex("#E8C27A"), "金币", format!("获得 {} 金币", l.gold)),
                };
                plain_card(row, fonts, db, skin, i, icon, glyph, color, name, &desc, true);
            }
        });
        root.spawn(text(&fonts.body, 16.0, PAPER, "1-3 / ← → + Enter　选择"));
    });
}

/// 货郎的摊子。charms：有没有解锁的灯坠可卖。
#[allow(clippy::too_many_arguments)]
fn spawn_shop(
    commands: &mut Commands,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    chest: u32,
    charm: u32,
    gold: u32,
    charms: bool,
) {
    commands.spawn(overlay(skin)).with_children(|root| {
        root.spawn(text(&fonts.title, 64.0, hex("#E8C27A"), "货郎"));
        root.spawn(text(&fonts.body, 18.0, DIM, &format!("身上的金币 {gold}　·　花掉的就带不出这一夜了")));
        root.spawn(Node { column_gap: px(22), ..default() }).with_children(|row| {
            plain_card(
                row,
                fonts,
                db,
                skin,
                0,
                None,
                "箱",
                hex("#FFD98A"),
                "宝箱",
                &format!("{chest} 金币"),
                gold >= chest,
            );
            plain_card(
                row,
                fonts,
                db,
                skin,
                1,
                None,
                "坠",
                hex("#B07CF0"),
                "灯坠",
                &if charms {
                    format!("{charm} 金币　三选一")
                } else {
                    "解锁的灯坠都挂上了".to_string()
                },
                charms && gold >= charm,
            );
            plain_card(row, fonts, db, skin, 2, None, "走", PAPER, "离开", "不买了", true);
        });
        root.spawn(text(&fonts.body, 16.0, PAPER, "1-3 / ← → + Enter　选择　　Esc / X　离开"));
    });
}

/// 灯坠三选一；满格时选中一枚后，改为在挂着的灯坠里选替换哪一枚。
#[allow(clippy::too_many_arguments)]
fn spawn_charm(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    offers: &[usize],
    picked: Option<usize>,
    worn: &[usize],
) {
    let color = hex("#B07CF0");
    let card = |row: &mut ChildSpawnerCommands, i: usize, k: usize| {
        let d = &c.charms[k];
        let glyph: String = d.name.chars().next().map(String::from).unwrap_or_default();
        let icon = format!("ui/icon_charm_{}", d.id);
        let desc = format!("{}\n代价：{}", d.good, d.bad);
        plain_card(row, fonts, db, skin, i, Some(&icon), &glyph, color, &d.name, &desc, true);
    };
    commands.spawn(overlay(skin)).with_children(|root| match picked {
        None => {
            root.spawn(text(&fonts.title, 64.0, color, "灯坠"));
            root.spawn(text(&fonts.body, 18.0, DIM, "挂在灯上，改写规则；每一枚都有代价"));
            root.spawn(Node { column_gap: px(22), ..default() }).with_children(|row| {
                for (i, &k) in offers.iter().enumerate() {
                    card(row, i, k);
                }
            });
            root.spawn(text(&fonts.body, 16.0, PAPER, "1-3 / ← → + Enter　选择　　Esc / X　放弃"));
        }
        Some(p) => {
            let name = offers.get(p).map_or("", |&k| c.charms[k].name.as_str());
            root.spawn(text(&fonts.title, 56.0, color, "灯坠栏满了"));
            root.spawn(text(&fonts.body, 18.0, DIM, &format!("换下哪一枚，挂上「{name}」？换下的直接消失")));
            root.spawn(Node { column_gap: px(22), ..default() }).with_children(|row| {
                for (i, &k) in worn.iter().enumerate() {
                    card(row, i, k);
                }
            });
            root.spawn(text(&fonts.body, 16.0, PAPER, "数字键 / ← → + Enter　替换　　Esc / X　返回"));
        }
    });
}

fn spawn_chest(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    build: &Build,
    chest: &lantern_sim::flow::ChestReveal,
) {
    let title = match (chest.source, chest.items.len()) {
        (ChestSource::Altar, _) => "血祭 · 以血换力".to_string(),
        (ChestSource::MiniBoss, n) => format!("小头目的宝箱 · {n} 连"),
        (ChestSource::Merchant, _) => "货郎的宝箱".to_string(),
        (_, 1) => "宝箱".to_string(),
        (_, 3) => "宝箱 · 三连".to_string(),
        (_, 5) => "宝箱 · 五连".to_string(),
        (_, n) => format!("宝箱 · {n} 连"),
    };
    commands
        .spawn(overlay(skin))
        .with_children(|root| {
            root.spawn(text(&fonts.title, 64.0, hex("#FFD98A"), &title));
            // 卷轴：展开的纸上一行一件
            root.spawn((
                Node {
                    width: px(480),
                    flex_direction: FlexDirection::Column,
                    row_gap: px(6),
                    padding: UiRect::axes(px(40), px(36)),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|list| {
                for (k, item) in chest.items.iter().enumerate() {
                    // 物品已经生效，按生效前的样子描述（升级显示“Lv a → a+1”）
                    let info = offer_info(c, arsenal, build, item.offer);
                    let kind = match item.offer {
                        Offer::WeaponUp(_) | Offer::PassiveUp(_) => {
                            format!("Lv{} → {}", item.level - 1, item.level)
                        }
                        Offer::Evolve(_) => "进化".into(),
                        Offer::NewWeapon(_) | Offer::NewPassive(_) => "新".into(),
                        _ => "补给".into(),
                    };
                    if k > 0 {
                        list.spawn((
                            Node { height: px(10), width: percent(100), ..default() },
                            skin.image("divider"),
                        ));
                    }
                    list.spawn(Node { align_items: AlignItems::Center, column_gap: px(14), ..default() })
                        .with_children(|row| {
                            spawn_icon(
                                row,
                                db,
                                fonts,
                                info.icon.as_deref(),
                                &info.glyph,
                                on_paper(info.color),
                                56.0,
                            );
                            row.spawn(Node { flex_direction: FlexDirection::Column, ..default() })
                                .with_children(|t| {
                                    t.spawn(text(&fonts.title, 28.0, on_paper(info.color), &info.name));
                                    t.spawn(text(
                                        &fonts.body,
                                        14.0,
                                        INK_DIM,
                                        &format!("{}　{kind}", info.rarity.name()),
                                    ));
                                });
                        });
                }
            });
            root.spawn(text(&fonts.body, 18.0, PAPER, "Enter / 手柄 A　继续"));
        })
        .observe(|_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(0));
}

fn spawn_evolve(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    k: usize,
) {
    let def = &c.weapons[arsenal.0[k].def];
    let Some(evo) = &def.evolution else { return };
    let color = element_color(c, def.element);
    let icon_name = format!("ui/icon_{}_evo", def.id);
    commands
        .spawn(overlay(skin))
        .with_children(|root| {
            if let Some(seal) = db.find("ui/seal_evo") {
                root.spawn((Node { width: px(72), height: px(72), ..default() }, db.ui_image(seal)));
            }
            spawn_icon(root, db, fonts, Some(&icon_name), &def.icon, color, 168.0);
            root.spawn(text(&fonts.title, 88.0, color, &evo.name));
            root.spawn(text(&fonts.body, 20.0, PAPER, &format!("{} → {}", def.name, evo.name)));
            root.spawn(text(&fonts.body, 18.0, DIM, &evo.desc));
        })
        .observe(|_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(0));
}
