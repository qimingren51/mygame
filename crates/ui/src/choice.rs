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
use crate::responsive::{CARD_GAP, CARD_WIDTH, FitViewport, PANEL_WIDTH_PERCENT};
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
    /// 焦点移到封印按钮时，保留要封印的卡片。
    card_target: usize,
    /// 已经发出命令，等模拟处理
    waiting: bool,
    /// 打开了多久（防止上一个界面的按键直接把这个确认掉）
    age: f32,
    /// 鼠标点击、悬停
    clicked: Option<usize>,
    hovered: Option<usize>,
}

impl ChoiceUi {
    /// 资源的变更版本也参与缓存：同样的选项可能属于下一次选择，描述还依赖构筑。
    fn update(&mut self, now: Shown, changed: bool) -> bool {
        if now == self.shown && (!changed || now == Shown::None) {
            return false;
        }
        *self = Self { shown: now, ..default() };
        true
    }
}

#[derive(Component)]
pub(crate) struct ChoiceRoot;

#[derive(Component)]
pub(crate) struct Card;

#[derive(Component)]
pub(crate) struct RerollLabel;

#[derive(Component)]
struct BanishLabel;

/// 卡面字号：收益与卡名拉开层级，说明退到纸面墨色里。
const CARD_NAME_SIZE: f32 = 30.0;
const CARD_GAIN_SIZE: f32 = 26.0;
const CARD_DESC_SIZE: f32 = 14.0;
const CARD_LABEL_SIZE: f32 = 12.0;
const CARD_META_SIZE: f32 = 11.0;

/// 直接跟随焦点框，鼠标和键盘共用同一份展开状态。
#[derive(Component)]
struct CardDetail {
    focus: Entity,
    expanded: bool,
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<ChoiceUi>().add_systems(OnExit(lantern_sim::AppState::Run), reset).add_systems(
        Update,
        (sync, input, highlight, show_details, animate_evolve, animate_rise, animate_chest)
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
    let now = current(*phase, &flow, &build);
    if !ui.update(now.clone(), flow.is_changed() || arsenal.is_changed() || build.is_changed()) {
        return;
    }
    for e in &roots {
        commands.entity(e).despawn();
    }
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
    progress: Res<lantern_sim::Progress>,
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
            let enabled = [flow.rerolls > 0, flow.banishes > 0, true];
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h.min(n + 2);
            }
            if actions.nav.y != 0 {
                ui.selected = if ui.selected < n {
                    n + enabled.iter().position(|x| *x).unwrap_or(2)
                } else {
                    ui.card_target.min(n - 1)
                };
            } else if actions.nav.x != 0 {
                ui.selected = if ui.selected < n {
                    (ui.selected as i32 + actions.nav.x).rem_euclid(n as i32) as usize
                } else {
                    n + crate::navigation::cycle_enabled(ui.selected - n, actions.nav.x, &enabled)
                };
            }
            if ui.selected < n {
                ui.card_target = ui.selected;
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
            if let Some(i) = chosen.filter(|&i| i < n) {
                send(&mut ui, SimCommand::Choose(i as u8));
            } else if (actions.reroll || chosen == Some(n)) && flow.rerolls > 0 {
                send(&mut ui, SimCommand::Reroll);
            } else if (actions.banish || chosen == Some(n + 1)) && flow.banishes > 0 {
                let i = ui.card_target;
                send(&mut ui, SimCommand::Banish(i as u8));
            } else if actions.skip || chosen == Some(n + 2) {
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
            let Some(shop) = flow.shop else { return };
            let enabled = [
                progress.gold >= shop.chest_cost as f32,
                shop.charm_ok && progress.gold >= shop.charm_cost as f32,
                true,
            ];
            if !enabled[ui.selected.min(2)] {
                ui.selected = enabled.iter().position(|x| *x).unwrap_or(2);
            }
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
                && h < 3
                && enabled[h]
            {
                ui.selected = h;
            }
            if actions.nav.x != 0 {
                ui.selected = crate::navigation::cycle_enabled(ui.selected, actions.nav.x, &enabled);
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
            } else if let Some(i @ (0 | 1)) = chosen
                && enabled[i]
            {
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
    mut reroll: Query<&mut crate::prompts::Prompt, (With<RerollLabel>, Without<BanishLabel>)>,
    mut banish: Query<&mut crate::prompts::Prompt, (With<BanishLabel>, Without<RerollLabel>)>,
) {
    for (f, mut v) in &mut focus {
        v.set_if_neq(if f.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
    if flow.is_changed() {
        for mut t in &mut reroll {
            t.0 = format!("{{reroll}} 重抽（剩 {} 次）", flow.rerolls);
        }
    }
    for mut t in &mut banish {
        t.0 = format!("{{banish}} 封印第 {} 项（剩 {} 次）", ui.card_target + 1, flow.banishes);
    }
}

#[derive(Component)]
pub(crate) struct CardFocus(usize);

fn show_details(
    focus: Query<&Visibility, With<CardFocus>>,
    mut details: Query<(&CardDetail, &mut Visibility), Without<CardFocus>>,
) {
    for (detail, mut visibility) in &mut details {
        let expanded = focus.get(detail.focus).is_ok_and(|v| *v != Visibility::Hidden);
        visibility.set_if_neq(if expanded == detail.expanded {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        });
    }
}

/// 按字截取，保留中文边界；完整内容留在焦点卡里。
fn card_summary(s: &str) -> String {
    let line = s.lines().next().unwrap_or_default();
    let mut chars = line.chars();
    let mut short: String = chars.by_ref().take(16).collect();
    if chars.next().is_some() || s.contains('\n') {
        short.push('…');
    }
    short
}

fn overlay(skin: &Skin) -> impl Bundle {
    (
        ChoiceRoot,
        FitViewport::default(),
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
        Rarity::Tian | Rarity::He => "card_tian",
        Rarity::Xuan | Rarity::Yi => "card_xuan",
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
    let note = offer_note(c, arsenal, build, offer, &info.desc);
    let el = info.element.map(|e| format!("{} 属性", c.element(e).name)).unwrap_or_default();
    let mut card = commands.spawn((
        Card,
        Rise::after(0.04 + i as f32 * 0.07),
        Node {
            width: px(CARD_WIDTH),
            min_height: px(380),
            flex_shrink: 0.0,
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            padding: UiRect::axes(px(20), px(22)),
            ..default()
        },
        skin.image(card_skin(info.rarity)),
    ));
    card.with_children(|card| {
        // 焦点框：和卡片一样大，叠在上面
        let focus = card
            .spawn((
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
            ))
            .id();
        card.spawn(Node { width: percent(100), justify_content: JustifyContent::SpaceBetween, ..default() })
            .with_children(|row| {
                row.spawn(text(
                    &fonts.body,
                    CARD_LABEL_SIZE,
                    on_paper(info.rarity.color()),
                    info.rarity.name(),
                ));
                row.spawn(text(&fonts.body, CARD_LABEL_SIZE, INK_DIM, &info.kind));
            });
        card.spawn(Node {
            width: percent(100),
            align_items: AlignItems::Center,
            column_gap: px(10),
            margin: UiRect::vertical(px(14)),
            ..default()
        })
        .with_children(|head| {
            spawn_icon(head, db, fonts, info.icon.as_deref(), &info.glyph, on_paper(info.color), 56.0);
            head.spawn((
                text(&fonts.title, CARD_NAME_SIZE, INK, &info.name),
                Node { max_width: px(150), ..default() },
            ));
        });
        // 共鸣与数值占据中腰；明确分行，避免大字挤成一段说明。
        card.spawn((
            Node {
                width: percent(100),
                min_height: px(92),
                padding: UiRect::all(px(12)),
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            skin.image(if note.color.is_some() { "note_box_hi" } else { "note_box" }),
        ))
        .with_child((
            Text::new(note.title.replace(" · ", "\n")),
            // 毛笔字体缺少箭头等字形，用正文补齐，保留数值变化的方向。
            TextFont {
                font: bevy::text::FontSource::list([fonts.title.clone(), fonts.body.clone()]),
                ..TextFont::from_font_size(CARD_GAIN_SIZE)
            },
            TextColor(on_paper(note.color.unwrap_or(info.color)).mix(&INK, 0.25)),
            TextLayout::new(Justify::Center, bevy::text::LineBreak::AnyCharacter),
            Node { width: percent(100), ..default() },
        ));
        // 隐藏的全文仍占位，摘要叠在同一位置：切换焦点不推挤整排卡片。
        card.spawn(Node {
            width: percent(100),
            min_height: px(104),
            flex_grow: 1.0,
            margin: UiRect::top(px(16)),
            ..default()
        })
        .with_children(|slot| {
            slot.spawn((
                CardDetail { focus, expanded: true },
                Visibility::Hidden,
                Node {
                    width: percent(100),
                    flex_direction: FlexDirection::Column,
                    row_gap: px(10),
                    ..default()
                },
            ))
            .with_children(|detail| {
                detail.spawn((
                    text(&fonts.body, CARD_DESC_SIZE, INK_DIM, &info.desc),
                    Node { width: percent(100), ..default() },
                ));
                if !info.flavor.is_empty() {
                    detail.spawn((
                        text(&fonts.body, CARD_LABEL_SIZE, INK_DIM, &info.flavor),
                        Node { width: percent(100), ..default() },
                    ));
                }
                if !note.body.is_empty() {
                    detail.spawn((
                        text(&fonts.body, CARD_LABEL_SIZE, INK_DIM, &note.body),
                        Node { width: percent(100), ..default() },
                    ));
                }
            });
            let summary =
                if note.body.is_empty() { "聚焦查看详情".into() } else { card_summary(&note.body) };
            slot.spawn((
                CardDetail { focus, expanded: false },
                text(&fonts.body, CARD_LABEL_SIZE, INK_DIM, &summary),
                TextLayout::no_wrap(),
                Node { position_type: PositionType::Absolute, top: px(0), left: px(0), ..default() },
            ));
        });
        card.spawn(Node {
            width: percent(100),
            align_items: AlignItems::Center,
            justify_content: JustifyContent::SpaceBetween,
            margin: UiRect::top(px(12)),
            ..default()
        })
        .with_children(|foot| {
            foot.spawn(text(&fonts.body, CARD_META_SIZE, INK_DIM, &el));
            foot.spawn(crate::prompts::hint(&fonts.title, 18.0, INK_DIM, &format!("{{pick{}}}", i + 1)));
        });
    });
    card.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
    card.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
}

pub(super) fn spawn_level_up(
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
    // 小窗口、高缩放时整页等比缩小；窄窗口里卡片换行（docs/DESIGN.md 第 11 节）。
    commands.spawn(overlay(skin)).insert(FitViewport::Upgrades(offers.len())).with_children(|root| {
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
        let cards = offers.len() as f32;
        root.spawn(Node {
            width: percent(PANEL_WIDTH_PERCENT),
            max_width: px(CARD_WIDTH * cards + CARD_GAP * (cards - 1.0).max(0.0)),
            flex_wrap: FlexWrap::Wrap,
            flex_shrink: 0.0,
            justify_content: JustifyContent::Center,
            column_gap: px(CARD_GAP),
            row_gap: px(CARD_GAP),
            ..default()
        })
        .with_children(|row| {
            for (i, &o) in offers.iter().enumerate() {
                card(row, c, fonts, db, skin, arsenal, build, i, o);
            }
        });
        root.spawn(crate::prompts::hint(
            &fonts.body,
            17.0,
            PAPER,
            "{nav} 选择　上下切换卡片与操作　{confirm} 确定",
        ));
        root.spawn(Node {
            max_width: percent(94),
            flex_wrap: FlexWrap::Wrap,
            justify_content: JustifyContent::Center,
            column_gap: px(16),
            row_gap: px(8),
            ..default()
        })
        .with_children(|foot| {
            let labels = [
                format!("{{reroll}} 重抽（剩 {rerolls} 次）"),
                format!("{{banish}} 封印第 1 项（剩 {banishes} 次）"),
                if ember > 0 {
                    "{skip} 跳过".into()
                } else {
                    format!("{{skip}} 跳过（灯油 +{}）", c.run.choices.skip_oil)
                },
            ];
            for (k, label) in labels.iter().enumerate() {
                let i = offers.len() + k;
                let enabled = match k {
                    0 => rerolls > 0,
                    1 => banishes > 0,
                    _ => true,
                };
                let mut button = foot.spawn((
                    Node {
                        min_width: px(240),
                        padding: UiRect::axes(px(20), px(12)),
                        justify_content: JustifyContent::Center,
                        ..default()
                    },
                    skin.image(if enabled { "btn" } else { "btn_disabled" }),
                ));
                button.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
                button.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
                button.with_children(|b| {
                    b.spawn((
                        CardFocus(i),
                        Node {
                            position_type: PositionType::Absolute,
                            left: px(0),
                            right: px(0),
                            top: px(0),
                            bottom: px(0),
                            ..default()
                        },
                        skin.image("focus_ring"),
                    ));
                    let mut label = b.spawn(crate::prompts::hint(
                        &fonts.body,
                        16.0,
                        if enabled { INK } else { INK_DIM },
                        label,
                    ));
                    if k == 0 {
                        label.insert(RerollLabel);
                    }
                    if k == 1 {
                        label.insert(BanishLabel);
                    }
                });
            }
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
        Rise::after(0.04 + i as f32 * 0.07),
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
        card.spawn(crate::prompts::hint(&fonts.title, 22.0, INK_DIM, &format!("{{pick{}}}", i + 1)));
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
                    LampReward::Gold => (None, "钱", hex("#E8C27A"), "铜钱", format!("获得 {} 铜钱", l.gold)),
                };
                plain_card(row, fonts, db, skin, i, icon, glyph, color, name, &desc, true);
            }
        });
        root.spawn(crate::prompts::hint(&fonts.body, 16.0, PAPER, "{nav} 选择　{confirm} 确定"));
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
        root.spawn(text(&fonts.body, 18.0, DIM, &format!("身上的铜钱 {gold}　·　花掉的就带不出这一夜了")));
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
                &format!("{chest} 铜钱"),
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
                    format!("{charm} 铜钱　三选一")
                } else {
                    "解锁的灯坠都挂上了".to_string()
                },
                charms && gold >= charm,
            );
            plain_card(row, fonts, db, skin, 2, None, "走", PAPER, "离开", "不买了", true);
        });
        root.spawn(crate::prompts::hint(&fonts.body, 16.0, PAPER, "{nav} 选择　{confirm} 确定　{back} 离开"));
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
        let mut desc = format!("{}\n代价：{}", d.good, d.bad);
        if !d.flavor.is_empty() {
            desc.push_str(&format!("\n\n{}", d.flavor));
        }
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
            root.spawn(crate::prompts::hint(
                &fonts.body,
                16.0,
                PAPER,
                "{nav} 选择　{confirm} 确定　{back} 放弃",
            ));
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
            root.spawn(crate::prompts::hint(
                &fonts.body,
                16.0,
                PAPER,
                "{nav} 选择　{confirm} 替换　{back} 返回",
            ));
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
    let n = chest.items.len();
    // 三连以上标题盖下来；五连每件亮得更足，最后一声钟后整卷泛起金光
    let big = n >= 3;
    let gold = n >= 5;
    commands
        .spawn(overlay(skin))
        .with_children(|root| {
            let mut title = root.spawn(text(&fonts.title, 64.0, CHEST_GOLD, &title));
            if big {
                // 先藏着、放大，第一帧就从大到小砸下来
                title.insert((
                    ChestGlow { part: ChestPart::Title, t: 0.0 },
                    TextColor(CHEST_GOLD.with_alpha(0.0)),
                    TextShadow { offset: Vec2::new(3.0, 3.0), color: Color::BLACK.with_alpha(0.0) },
                    UiTransform::from_scale(Vec2::splat(1.7)),
                ));
            }
            // 卷轴：展开的纸上一行一件
            let mut scroll = root.spawn((
                Node {
                    width: px(480),
                    flex_direction: FlexDirection::Column,
                    row_gap: px(6),
                    padding: UiRect::axes(px(40), px(36)),
                    // 金光是按节点的方框画的，圆角让它贴着纸边、不显得方
                    border_radius: BorderRadius::all(px(18)),
                    ..default()
                },
                skin.image("panel"),
            ));
            if gold {
                scroll.insert((
                    ChestGlow { part: ChestPart::Halo { at: CHIME_AT + n as f32 * CHIME_GAP }, t: 0.0 },
                    BoxShadow::new(CHEST_GOLD.with_alpha(0.0), px(0), px(0), px(6), px(44)),
                ));
            }
            scroll.with_children(|list| {
                for (k, item) in chest.items.iter().enumerate() {
                    // 物品已经生效，按生效前的样子描述（升级显示“Lv a → a+1”）
                    let info = offer_info(c, arsenal, build, item.offer);
                    let kind = match item.offer {
                        Offer::WeaponUp(_) | Offer::PassiveUp(_) => {
                            format!("Lv{} → {}", item.level - 1, item.level)
                        }
                        Offer::Evolve(_) => "进化".into(),
                        Offer::Mutate(_) => "异化".into(),
                        Offer::Fuse { .. } => "合璧".into(),
                        Offer::NewWeapon(_) | Offer::NewPassive(_) => "新".into(),
                        _ => "补给".into(),
                    };
                    if k > 0 {
                        list.spawn((
                            Node { height: px(10), width: percent(100), ..default() },
                            skin.image("divider"),
                        ));
                    }
                    // 和开箱的钟声对上：第 k 声在 0.35 + 0.28k 秒，那一行跟着亮一下
                    let at = CHIME_AT + k as f32 * CHIME_GAP;
                    list.spawn((
                        Node {
                            align_items: AlignItems::Center,
                            column_gap: px(14),
                            padding: UiRect::axes(px(8), px(2)),
                            border_radius: BorderRadius::all(px(6)),
                            ..default()
                        },
                        Rise::after(at - 0.05),
                        BackgroundColor(CHEST_GOLD.with_alpha(0.0)),
                        ChestGlow { part: ChestPart::Row { at, peak: if gold { 0.5 } else { 0.3 } }, t: 0.0 },
                    ))
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
                        row.spawn(Node { flex_direction: FlexDirection::Column, ..default() }).with_children(
                            |t| {
                                t.spawn(text(&fonts.title, 28.0, on_paper(info.color), &info.name));
                                t.spawn(text(
                                    &fonts.body,
                                    14.0,
                                    INK_DIM,
                                    &format!("{}　{kind}", info.rarity.name()),
                                ));
                            },
                        );
                    });
                }
            });
            root.spawn(crate::prompts::hint(&fonts.body, 18.0, PAPER, "{confirm} 继续"));
        })
        .observe(|_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(0));
}

/// 开箱钟声的时刻（和 `lantern_audio` 的 chest 音效对上）：第 k 声在 CHIME_AT + k × CHIME_GAP 秒。
const CHIME_AT: f32 = 0.35;
const CHIME_GAP: f32 = 0.28;
const CHEST_GOLD: Color = Color::srgb(1.0, 0.85, 0.54);

/// 宝箱的金光（docs/FEEL.md 第 5 节）。
#[derive(Component)]
pub(crate) struct ChestGlow {
    part: ChestPart,
    t: f32,
}

#[derive(Clone, Copy)]
enum ChestPart {
    /// 三连以上的标题：从大到小砸下来
    Title,
    /// 一行：钟响时亮一下再暗下去；peak 是最亮时底色的不透明度
    Row { at: f32, peak: f32 },
    /// 五连：最后一声钟后卷轴外圈泛起金光，留一圈淡的
    Halo { at: f32 },
}

pub(crate) fn animate_chest(
    time: Res<Time<Real>>,
    mut q: Query<(
        &mut ChestGlow,
        Option<&mut BackgroundColor>,
        Option<&mut BoxShadow>,
        &mut UiTransform,
        Option<&mut TextColor>,
        Option<&mut TextShadow>,
    )>,
) {
    let dt = time.delta_secs().min(0.1);
    for (mut g, bg, shadow, mut tf, color, text_shadow) in &mut q {
        g.t += dt;
        let t = g.t;
        match g.part {
            ChestPart::Title => {
                if t > 0.6 {
                    continue;
                }
                let k = (t / 0.16).min(1.0);
                let s = if t < 0.16 {
                    1.7 - 0.7 * k * k
                } else {
                    1.0 + 0.06 * (-(t - 0.16) * 14.0).exp() * ((t - 0.16) * 40.0).cos()
                };
                tf.scale = Vec2::splat(s);
                let a = (t / 0.08).min(1.0);
                if let Some(mut c) = color {
                    c.0.set_alpha(a);
                }
                if let Some(mut sh) = text_shadow {
                    sh.color.set_alpha(0.8 * a);
                }
            }
            ChestPart::Row { at, peak } => {
                let k = t - at;
                if !(0.0..=1.6).contains(&k) {
                    continue;
                }
                let a = peak * (k / 0.05).min(1.0) * (-(k - 0.05).max(0.0) * 3.5).exp();
                if let Some(mut bg) = bg {
                    bg.0.set_alpha(a);
                }
            }
            ChestPart::Halo { at } => {
                let k = t - at;
                if !(0.0..=3.0).contains(&k) {
                    continue;
                }
                // 猛地亮起，慢慢退到一圈淡金
                let a = 0.95 * (k / 0.06).min(1.0) * (-k * 2.2).exp() + 0.3 * (k / 0.4).min(1.0);
                if let Some(mut sh) = shadow {
                    for st in &mut sh.0 {
                        st.color.set_alpha(a);
                        st.spread_radius = px(6.0 + 10.0 * (-k * 3.0).exp());
                    }
                }
            }
        }
    }
}

/// 出场动画：等 delay 秒后从下面弹上来（卡片依次出现，宝箱逐项揭晓）。
#[derive(Component)]
pub(crate) struct Rise {
    delay: f32,
    t: f32,
}

impl Rise {
    pub(crate) fn after(delay: f32) -> (Rise, UiTransform, Visibility) {
        (
            Rise { delay, t: 0.0 },
            UiTransform {
                translation: bevy::ui::Val2::px(0.0, 46.0),
                scale: Vec2::splat(0.9),
                ..UiTransform::IDENTITY
            },
            Visibility::Hidden,
        )
    }
}

pub(crate) fn animate_rise(
    time: Res<Time<Real>>,
    mut q: Query<(&mut Rise, &mut UiTransform, &mut Visibility)>,
) {
    let dt = time.delta_secs().min(0.1);
    for (mut r, mut tf, mut vis) in &mut q {
        if r.t >= r.delay + 0.3 {
            continue;
        }
        r.t += dt;
        let k = ((r.t - r.delay) / 0.3).clamp(0.0, 1.0);
        if k > 0.0 {
            vis.set_if_neq(Visibility::Inherited);
        }
        let e = ease_out_back(k);
        tf.translation = bevy::ui::Val2::px(0.0, 46.0 * (1.0 - e));
        tf.scale = Vec2::splat(0.9 + 0.1 * e);
    }
}

/// 进化演出的各部分（docs/FEEL.md 第 5 节）：旧法器化墨淡去，新形态从大到小画出来，
/// 最后盖上“化”字印，名字和说明淡入。整段在 2 秒内（模拟的进化阶段 2.1 秒后自动关闭）。
#[derive(Component, Clone, Copy)]
pub(crate) enum EvoPart {
    Old,
    New(Color),
    Seal,
    Text,
}

/// 进化演出的计时（现实秒）。
#[derive(Component, Default)]
pub(crate) struct EvoClock(f32);

fn spawn_evolve(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    k: usize,
) {
    let w = &arsenal.0[k];
    let def = &c.weapons[w.def];
    let (stamp, color) = match w.form {
        lantern_sim::weapons::Form::Mutated => ("异", hex("#CF8CDB")),
        lantern_sim::weapons::Form::Fused(_) => ("合", hex("#FFD98A")),
        _ => ("进化", element_color(c, def.element)),
    };
    let origin = if let lantern_sim::weapons::Form::Fused(f) = w.form {
        c.fusions[f]
            .weapons
            .iter()
            .map(|id| {
                c.weapons[c.weapon_index(id).expect("合璧材料")]
                    .evolution
                    .as_ref()
                    .expect("正统进化")
                    .name
                    .as_str()
            })
            .collect::<Vec<_>>()
            .join(" + ")
    } else {
        def.name.clone()
    };
    let icon_name = format!("ui/icon_{}_evo", def.id);
    let old_icon = db.find(&format!(
        "ui/icon_{}{}",
        def.id,
        if matches!(w.form, lantern_sim::weapons::Form::Fused(_)) { "_evo" } else { "" }
    ));
    let new_icon = db.find(&icon_name);
    let size = 168.0;
    commands
        .spawn((overlay(skin), EvoClock::default()))
        .with_children(|root| {
            // “进化”竖印（96×160），垫一张宣纸方笺才看得清
            if stamp != "进化" {
                root.spawn((
                    EvoPart::Seal,
                    Node {
                        padding: UiRect::all(px(12)),
                        border_radius: BorderRadius::all(px(6)),
                        ..default()
                    },
                    BackgroundColor(PAPER.with_alpha(0.0)),
                    UiTransform::from_scale(Vec2::splat(2.4)),
                    text(&fonts.title, 70.0, color.with_alpha(0.0), stamp),
                ));
            } else if let Some(seal) = db.find("ui/seal_evo") {
                root.spawn((
                    EvoPart::Seal,
                    Node {
                        width: px(54.0 + 16.0),
                        height: px(90.0 + 16.0),
                        padding: UiRect::all(px(8)),
                        border_radius: BorderRadius::all(px(6)),
                        ..default()
                    },
                    BackgroundColor(PAPER.with_alpha(0.0)),
                    UiTransform::from_scale(Vec2::splat(2.4)),
                    db.ui_image(seal).with_color(Color::WHITE.with_alpha(0.0)),
                ));
            }
            match (old_icon, new_icon) {
                (Some(old), Some(new)) => {
                    root.spawn(Node { width: px(size), height: px(size), ..default() }).with_children(|b| {
                        let full = Node {
                            position_type: PositionType::Absolute,
                            width: percent(100),
                            height: percent(100),
                            ..default()
                        };
                        b.spawn((
                            EvoPart::New(if stamp == "异" { color } else { Color::WHITE }),
                            full.clone(),
                            UiTransform::from_scale(Vec2::splat(1.35)),
                            db.ui_image(new).with_color(Color::WHITE.with_alpha(0.0)),
                        ));
                        b.spawn((EvoPart::Old, full, UiTransform::default(), db.ui_image(old)));
                        if let lantern_sim::weapons::Form::Fused(f) = w.form {
                            let other = &c.fusions[f].weapons[1];
                            if let Some(icon) = db.find(&format!("ui/icon_{other}_evo")) {
                                b.spawn((
                                    EvoPart::Old,
                                    Node {
                                        position_type: PositionType::Absolute,
                                        left: px(size * 0.7),
                                        top: px(size * 0.25),
                                        width: px(size * 0.7),
                                        height: px(size * 0.7),
                                        ..default()
                                    },
                                    UiTransform::default(),
                                    db.ui_image(icon),
                                ));
                            }
                        }
                    });
                }
                _ => spawn_icon(root, db, fonts, Some(&icon_name), &def.icon, color, size),
            }
            root.spawn((EvoPart::Text, text(&fonts.title, 88.0, color.with_alpha(0.0), w.name(c))));
            root.spawn((
                EvoPart::Text,
                text(&fonts.body, 20.0, PAPER.with_alpha(0.0), &format!("{} → {}", origin, w.name(c))),
            ));
            root.spawn((EvoPart::Text, text(&fonts.body, 18.0, DIM.with_alpha(0.0), w.desc(c))));
            if !w.flavor(c).is_empty() {
                root.spawn((EvoPart::Text, text(&fonts.body, 16.0, DIM.with_alpha(0.0), w.flavor(c))));
            }
        })
        .observe(|_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(0));
}

fn smooth(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}

fn ease_out_back(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    1.0 + 2.70158 * (x - 1.0).powi(3) + 1.70158 * (x - 1.0).powi(2)
}

/// 推进进化演出。
pub(crate) fn animate_evolve(
    time: Res<Time<Real>>,
    mut clocks: Query<&mut EvoClock>,
    mut parts: Query<(
        &EvoPart,
        Option<&mut UiTransform>,
        Option<&mut ImageNode>,
        Option<&mut TextColor>,
        Option<&mut BackgroundColor>,
    )>,
) {
    let Some(mut clock) = clocks.iter_mut().next() else { return };
    clock.0 += time.delta_secs().min(0.1);
    let t = clock.0;
    // 旧图标：先变成墨色，再胀开淡去
    let ink = smooth(t / 0.45);
    let gone = smooth((t - 0.35) / 0.4);
    // 新图标：0.55 秒起从大到小落定
    let born = (t - 0.55) / 0.4;
    // 印：0.95 秒砸下
    let stamp = (t - 0.95) / 0.12;
    let words = smooth((t - 0.8) / 0.5);
    for (part, tf, img, txt, bg) in &mut parts {
        match part {
            EvoPart::Old => {
                if let Some(mut img) = img {
                    let c = Color::WHITE.mix(&Color::srgb(0.06, 0.06, 0.08), ink);
                    img.color = c.with_alpha(1.0 - gone);
                }
                if let Some(mut tf) = tf {
                    // 化墨前轻轻一颤
                    let shake = if t < 0.35 { (t * 70.0).sin() * 3.0 * (1.0 - t / 0.35) } else { 0.0 };
                    tf.translation = bevy::ui::Val2::px(shake, 0.0);
                    tf.scale = Vec2::splat(1.0 + 0.2 * gone);
                }
            }
            EvoPart::New(tint) => {
                if let Some(mut img) = img {
                    img.color = tint.with_alpha(smooth(born * 1.5));
                }
                if let Some(mut tf) = tf {
                    tf.scale = Vec2::splat(1.35 - 0.35 * ease_out_back(born));
                }
            }
            EvoPart::Seal => {
                if let Some(mut color) = txt {
                    color.0.set_alpha(smooth(stamp * 2.0));
                }
                if let Some(mut img) = img {
                    img.color = Color::WHITE.with_alpha(smooth(stamp * 2.0));
                }
                if let Some(mut bg) = bg {
                    bg.0.set_alpha(0.88 * smooth(stamp * 2.0));
                }
                if let Some(mut tf) = tf {
                    let k = stamp.clamp(0.0, 1.0);
                    tf.scale = Vec2::splat(2.4 - 1.4 * k * k);
                    tf.rotation = Rot2::radians(-0.12 * k);
                }
            }
            EvoPart::Text => {
                if let Some(mut c) = txt {
                    c.0.set_alpha(words);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::flow::{ChestItem, ChestReveal, Choice};

    fn track(
        flow: Res<Flow>,
        build: Res<Build>,
        arsenal: Res<Arsenal>,
        phase: Res<SimPhase>,
        mut ui: ResMut<ChoiceUi>,
    ) {
        ui.update(
            current(*phase, &flow, &build),
            flow.is_changed() || build.is_changed() || arsenal.is_changed(),
        );
    }

    #[test]
    fn consecutive_choices_reset_the_cache_and_input_guard() {
        let mut app = App::new();
        app.init_resource::<Flow>()
            .init_resource::<Build>()
            .init_resource::<Arsenal>()
            .init_resource::<ChoiceUi>()
            .insert_resource(SimPhase::Chest)
            .add_systems(Update, track);
        for offer in [Offer::Oil, Offer::Heal, Offer::Heal] {
            app.world_mut().resource_mut::<Flow>().chest =
                Some(ChestReveal { items: vec![ChestItem { offer, level: 0 }], source: ChestSource::Elite });
            app.update();
            {
                let mut ui = app.world_mut().resource_mut::<ChoiceUi>();
                assert_eq!(ui.age, 0.0);
                assert!(!ui.waiting);
                ui.age = 1.0;
                ui.waiting = true;
            }
            app.update();
            assert_eq!(app.world().resource::<ChoiceUi>().age, 1.0);
        }
        *app.world_mut().resource_mut::<SimPhase>() = SimPhase::LevelUp;
        for level in [2, 3] {
            app.world_mut().resource_mut::<Flow>().choice =
                Some(Choice { offers: vec![Offer::Oil], inspired: false, level, ember: false });
            app.update();
            let mut ui = app.world_mut().resource_mut::<ChoiceUi>();
            assert_eq!(ui.age, 0.0);
            ui.age = 1.0;
            ui.waiting = true;
        }
        app.world_mut().resource_mut::<Build>().charms.push(0);
        app.update();
        // 构筑改变也要刷新描述和输入保护。
        assert_eq!(app.world().resource::<ChoiceUi>().age, 0.0);
        assert!(!app.world().resource::<ChoiceUi>().waiting);
    }
}

#[cfg(test)]
mod input_tests {
    use super::*;
    use lantern_sim::Progress;

    fn app(phase: SimPhase, shown: Shown, flow: Flow) -> App {
        let mut app = App::new();
        app.init_resource::<Actions>()
            .init_resource::<Build>()
            .init_resource::<Progress>()
            .init_resource::<SimCommands>()
            .insert_resource(phase)
            .insert_resource(flow)
            .insert_resource(ChoiceUi { shown, age: 1.0, ..default() })
            .add_systems(Update, input);
        app
    }

    #[test]
    fn card_footer_navigation_banishes_remembered_card_and_gates_duplicate_commands() {
        let offers = vec![Offer::NewWeapon(0), Offer::NewWeapon(1), Offer::NewPassive(0)];
        let flow = Flow {
            choice: Some(lantern_sim::flow::Choice {
                offers: offers.clone(),
                inspired: false,
                level: 2,
                ember: false,
            }),
            rerolls: 1,
            banishes: 1,
            ..default()
        };
        let mut app = app(SimPhase::LevelUp, Shown::LevelUp(offers, false, 0), flow);
        app.world_mut().resource_mut::<Actions>().nav = IVec2::X;
        app.update();
        assert_eq!(app.world().resource::<ChoiceUi>().selected, 1);
        app.world_mut().resource_mut::<Actions>().nav = IVec2::Y;
        app.update();
        assert_eq!(app.world().resource::<ChoiceUi>().selected, 3);
        app.world_mut().resource_mut::<Actions>().nav = IVec2::X;
        app.update();
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        app.update();
        assert_eq!(app.world().resource::<SimCommands>().0, vec![SimCommand::Banish(1)]);
    }

    #[test]
    fn unaffordable_shop_items_cannot_trap_confirmation() {
        let flow = Flow {
            shop: Some(lantern_sim::flow::Shop { chest_cost: 100, charm_cost: 200, charm_ok: true }),
            ..default()
        };
        let mut app = app(SimPhase::Shop, Shown::Shop(100, 200, true), flow);
        *app.world_mut().resource_mut::<Actions>() = Actions { pick: Some(0), ..default() };
        app.update();
        assert_eq!(app.world().resource::<ChoiceUi>().selected, 2);
        assert!(!app.world().resource::<ChoiceUi>().waiting);
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        assert_eq!(app.world().resource::<SimCommands>().0, vec![SimCommand::Skip]);
    }
}

#[cfg(test)]
mod card_tests {
    use super::*;

    fn choice_app() -> App {
        let offers = vec![Offer::Heal, Offer::Oil, Offer::Heal, Offer::Oil];
        let mut app = App::new();
        app.insert_resource(ChoiceUi {
            shown: Shown::LevelUp(offers.clone(), true, 0),
            age: 1.0,
            ..default()
        })
        .insert_resource(Flow {
            choice: Some(lantern_sim::flow::Choice { offers, inspired: true, level: 2, ember: false }),
            ..default()
        })
        .insert_resource(SimPhase::LevelUp)
        .init_resource::<Build>()
        .init_resource::<lantern_sim::Progress>()
        .init_resource::<Actions>()
        .init_resource::<SimCommands>()
        .add_systems(Update, (input, highlight, show_details).chain());
        for i in 0..4 {
            let focus = app.world_mut().spawn((CardFocus(i), Visibility::Hidden)).id();
            for expanded in [true, false] {
                app.world_mut().spawn((CardDetail { focus, expanded }, Visibility::Hidden));
            }
        }
        app
    }

    fn assert_expanded(app: &mut App, selected: usize) {
        assert_eq!(app.world().resource::<ChoiceUi>().selected, selected);
        let world = app.world_mut();
        for (detail, visibility) in world.query::<(&CardDetail, &Visibility)>().iter(world) {
            let index = world.get::<CardFocus>(detail.focus).unwrap().0;
            assert_eq!(*visibility != Visibility::Hidden, (index == selected) == detail.expanded);
        }
    }

    #[test]
    fn details_follow_keyboard_and_pointer_focus_without_choosing() {
        let mut app = choice_app();
        app.update();
        assert_expanded(&mut app, 0);

        // 左移循环到第四张；静止光标不能抢回焦点。
        app.world_mut().resource_mut::<ChoiceUi>().hovered = Some(1);
        app.insert_resource(Actions { nav: IVec2::NEG_X, ..default() });
        app.update();
        assert_expanded(&mut app, 3);

        app.world_mut().resource_mut::<ChoiceUi>().hovered = Some(1);
        app.insert_resource(Actions { pointer_moved: true, ..default() });
        app.update();
        assert_expanded(&mut app, 1);

        app.insert_resource(Actions { nav: IVec2::X, ..default() });
        app.update();
        assert_expanded(&mut app, 2);
        assert!(app.world().resource::<SimCommands>().0.is_empty());

        app.insert_resource(Actions { confirm: true, ..default() });
        app.update();
        assert!(matches!(app.world().resource::<SimCommands>().0.as_slice(), [SimCommand::Choose(2)]));
    }

    #[test]
    fn number_keys_still_choose_each_of_four_cards_once() {
        for pick in 0..4 {
            let mut app = choice_app();
            app.insert_resource(Actions { pick: Some(pick), ..default() });
            app.update();
            app.update();
            assert!(
                matches!(app.world().resource::<SimCommands>().0.as_slice(), [SimCommand::Choose(i)] if *i == pick)
            );
        }
    }

    #[test]
    fn summary_preserves_short_lines_and_marks_hidden_text() {
        assert_eq!(card_summary("金 2 → 3"), "金 2 → 3");
        assert_eq!(card_summary("金 2 → 3\n进化需心法「剑意」"), "金 2 → 3…");
        let long = "每次暴击都追加飞剑，追加的也能暴击、继续追加";
        let short = card_summary(long);
        assert_eq!(short.chars().count(), 17);
        assert!(short.ends_with('…'));
        assert!(long.starts_with(short.trim_end_matches('…')));
    }
}
