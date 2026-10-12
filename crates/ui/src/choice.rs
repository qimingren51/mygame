//! 升级三选一、宝箱揭晓、进化演出（移植自网页版 ui/screens.ts）。
//!
//! 模拟停在选择阶段时，这里画出对应的界面，把玩家的选择作为命令发给模拟。命令要等下一个模拟步才生效，
//! 发出后到界面刷新之前不再接受输入，避免连按把下一次升级也选掉。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::Actions;
use lantern_sim::flow::{ChestSource, Flow};
use lantern_sim::{Arsenal, Build, GameContent, Offer, RunState, SimCommand, SimCommands, SimPhase};
use lantern_view::atlas::AtlasDb;

use crate::describe::{OfferInfo, element_color, hex, offer_info, offer_note};
use crate::{DIM, Fonts, PAPER, text};

/// 界面上现在画的是哪一个选择。变了就重画。
#[derive(Clone, Debug, PartialEq, Default)]
enum Shown {
    #[default]
    None,
    LevelUp(Vec<Offer>, bool),
    Chest(usize, ChestSource),
    Evolve(usize),
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
pub(crate) struct Card(usize);

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

fn current(phase: SimPhase, flow: &Flow) -> Shown {
    match phase {
        SimPhase::LevelUp => {
            flow.choice.as_ref().map_or(Shown::None, |c| Shown::LevelUp(c.offers.clone(), c.inspired))
        }
        SimPhase::Chest => flow.chest.as_ref().map_or(Shown::None, |c| Shown::Chest(c.items.len(), c.source)),
        SimPhase::Evolve => flow.evolving.map_or(Shown::None, Shown::Evolve),
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
    phase: Res<SimPhase>,
    flow: Res<Flow>,
    arsenal: Res<Arsenal>,
    build: Res<Build>,
    mut ui: ResMut<ChoiceUi>,
    roots: Query<Entity, With<ChoiceRoot>>,
) {
    ui.age += time.delta_secs();
    if flow.is_changed() {
        ui.waiting = false;
    }
    let now = current(*phase, &flow);
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
        Shown::LevelUp(offers, inspired) => {
            let level = flow.choice.as_ref().map_or(0, |ch| ch.level);
            spawn_level_up(
                &mut commands,
                c,
                &fonts,
                &db,
                &arsenal,
                &build,
                &offers,
                inspired,
                level,
                flow.rerolls,
            )
        }
        Shown::Chest(..) => {
            if let Some(chest) = &flow.chest {
                spawn_chest(&mut commands, c, &fonts, &db, &arsenal, &build, chest)
            }
        }
        Shown::Evolve(k) => spawn_evolve(&mut commands, c, &fonts, &db, &arsenal, k),
    }
}

fn input(
    actions: Res<Actions>,
    phase: Res<SimPhase>,
    flow: Res<Flow>,
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
            if let Some(h) = ui.hovered {
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
            } else if actions.skip {
                send(&mut ui, SimCommand::Skip);
            }
        }
        SimPhase::Chest if ui.age > 0.4 && (actions.confirm || clicked.is_some()) => {
            send(&mut ui, SimCommand::Ack);
        }
        SimPhase::Evolve if ui.age > 2.1 || (ui.age > 0.5 && (actions.confirm || clicked.is_some())) => {
            send(&mut ui, SimCommand::Ack);
        }
        _ => {}
    }
}

/// 选中的卡片描边更亮、底色更深。
fn highlight(
    ui: Res<ChoiceUi>,
    flow: Res<Flow>,
    mut cards: Query<(&Card, &mut BorderColor, &mut BackgroundColor)>,
    mut reroll: Query<&mut Text, With<RerollLabel>>,
) {
    for (card, mut border, mut bg) in &mut cards {
        let on = card.0 == ui.selected;
        let mut b = border.top;
        b.set_alpha(if on { 1.0 } else { 0.45 });
        *border = BorderColor::all(b);
        bg.0 = if on { Color::srgba(0.12, 0.13, 0.19, 0.97) } else { Color::srgba(0.07, 0.08, 0.12, 0.93) };
    }
    if flow.is_changed() {
        for mut t in &mut reroll {
            t.0 = format!("R / 手柄 Y　重抽（剩 {} 次）", flow.rerolls);
        }
    }
}

fn overlay() -> impl Bundle {
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
        BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.72)),
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

fn card(
    commands: &mut ChildSpawnerCommands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    arsenal: &Arsenal,
    build: &Build,
    i: usize,
    offer: Offer,
) {
    let info: OfferInfo = offer_info(c, arsenal, build, offer);
    let note = offer_note(c, arsenal, build, offer);
    let el = info.element.map(|e| format!("{} 属性", c.element(e).name)).unwrap_or_default();
    let mut card = commands.spawn((
        Card(i),
        Node {
            width: px(236),
            min_height: px(330),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            padding: UiRect::all(px(16)),
            row_gap: px(8),
            border: UiRect::all(px(2)),
            border_radius: BorderRadius::all(px(10)),
            ..default()
        },
        BorderColor::all(info.color),
        BackgroundColor(Color::srgba(0.07, 0.08, 0.12, 0.93)),
    ));
    card.with_children(|card| {
        card.spawn(Node { width: percent(100), justify_content: JustifyContent::SpaceBetween, ..default() })
            .with_children(|row| {
                row.spawn(text(&fonts.body, 14.0, info.rarity.color(), info.rarity.name()));
                row.spawn(text(&fonts.body, 14.0, DIM, &info.kind));
            });
        spawn_icon(card, db, fonts, info.icon.as_deref(), &info.glyph, info.color, 84.0);
        card.spawn(text(&fonts.title, 34.0, info.color, &info.name));
        card.spawn((text(&fonts.body, 16.0, PAPER, &info.desc), Node { max_width: px(200), ..default() }));
        card.spawn(text(&fonts.body, 13.0, DIM, &el));
        card.spawn(Node { flex_grow: 1.0, ..default() });
        if let Some(n) = note {
            card.spawn((
                Node {
                    width: percent(100),
                    flex_direction: FlexDirection::Column,
                    padding: UiRect::all(px(8)),
                    row_gap: px(2),
                    border_radius: BorderRadius::all(px(6)),
                    ..default()
                },
                BackgroundColor(Color::srgba(1.0, 1.0, 1.0, 0.05)),
            ))
            .with_children(|b| {
                b.spawn(text(&fonts.body, 14.0, n.color.unwrap_or(DIM), &n.title));
                if !n.body.is_empty() {
                    b.spawn((
                        text(&fonts.body, 13.0, DIM, &n.body),
                        Node { max_width: px(196), ..default() },
                    ));
                }
            });
        }
        card.spawn(text(&fonts.body, 14.0, DIM, &format!("{}", i + 1)));
    });
    card.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
    card.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
}

fn spawn_level_up(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    arsenal: &Arsenal,
    build: &Build,
    offers: &[Offer],
    inspired: bool,
    level: u32,
    rerolls: u32,
) {
    commands.spawn(overlay()).with_children(|root| {
        root.spawn(Node {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            ..default()
        })
        .with_children(|head| {
            head.spawn(text(&fonts.title, 64.0, PAPER, "升级"));
            let sub = if inspired {
                format!("Lv {} → {}　·　灵光一闪，多一个选项", level - 1, level)
            } else {
                format!("Lv {} → {}", level - 1, level)
            };
            head.spawn(text(&fonts.body, 18.0, if inspired { hex("#FFD98A") } else { DIM }, &sub));
        });
        root.spawn(Node { column_gap: px(18), ..default() }).with_children(|row| {
            for (i, &o) in offers.iter().enumerate() {
                card(row, c, fonts, db, arsenal, build, i, o);
            }
        });
        root.spawn(Node { column_gap: px(36), ..default() }).with_children(|foot| {
            foot.spawn(text(&fonts.body, 16.0, PAPER, "1-4 / ← → + Enter　选择"));
            foot.spawn((
                RerollLabel,
                text(&fonts.body, 16.0, PAPER, &format!("R / 手柄 Y　重抽（剩 {rerolls} 次）")),
            ));
            foot.spawn(text(
                &fonts.body,
                16.0,
                DIM,
                &format!("X / 手柄 X　跳过（灯油 +{}）", c.run.choices.skip_oil),
            ));
        });
    });
}

fn spawn_chest(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    arsenal: &Arsenal,
    build: &Build,
    chest: &lantern_sim::flow::ChestReveal,
) {
    let title = match (chest.source, chest.items.len()) {
        (ChestSource::Altar, _) => "血祭 · 以血换力".to_string(),
        (_, 1) => "宝箱".to_string(),
        (_, 3) => "宝箱 · 三连".to_string(),
        (_, 5) => "宝箱 · 五连".to_string(),
        (_, n) => format!("宝箱 · {n} 连"),
    };
    commands
        .spawn(overlay())
        .with_children(|root| {
            root.spawn(text(&fonts.title, 64.0, hex("#FFD98A"), &title));
            root.spawn(Node { flex_direction: FlexDirection::Column, row_gap: px(10), ..default() })
                .with_children(|list| {
                    for item in &chest.items {
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
                        list.spawn((
                            Card(usize::MAX),
                            Node {
                                width: px(420),
                                align_items: AlignItems::Center,
                                column_gap: px(14),
                                padding: UiRect::axes(px(14), px(8)),
                                border: UiRect::all(px(2)),
                                border_radius: BorderRadius::all(px(8)),
                                ..default()
                            },
                            BorderColor::all(info.color.with_alpha(0.5)),
                            BackgroundColor(Color::srgba(0.07, 0.08, 0.12, 0.93)),
                        ))
                        .with_children(|row| {
                            spawn_icon(row, db, fonts, info.icon.as_deref(), &info.glyph, info.color, 52.0);
                            row.spawn(Node { flex_direction: FlexDirection::Column, ..default() })
                                .with_children(|t| {
                                    t.spawn(text(&fonts.title, 28.0, info.color, &info.name));
                                    t.spawn(text(&fonts.body, 14.0, DIM, &kind));
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
    arsenal: &Arsenal,
    k: usize,
) {
    let def = &c.weapons[arsenal.0[k].def];
    let Some(evo) = &def.evolution else { return };
    let color = element_color(c, def.element);
    let icon_name = format!("ui/icon_{}_evo", def.id);
    commands
        .spawn(overlay())
        .with_children(|root| {
            root.spawn(text(&fonts.body, 22.0, hex("#FFD98A"), "进化"));
            spawn_icon(root, db, fonts, Some(&icon_name), &def.icon, color, 160.0);
            root.spawn(text(&fonts.title, 88.0, color, &evo.name));
            root.spawn(text(&fonts.body, 20.0, PAPER, &format!("{} → {}", def.name, evo.name)));
            root.spawn(text(&fonts.body, 18.0, DIM, &evo.desc));
        })
        .observe(|_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(0));
}
