//! 升级三选一、宝箱揭晓、进化演出（移植自网页版 ui/screens.ts）；点灯奖励、货郎。
//!
//! 模拟停在选择阶段时，这里画出对应的界面，把玩家的选择作为命令发给模拟。命令要等下一个模拟步才生效，
//! 发出后到界面刷新之前不再接受输入，避免连按把下一次升级也选掉。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::Actions;
use lantern_sim::flow::{ChestItem, ChestSource, Flow, LampReward};
use lantern_sim::{Arsenal, Build, GameContent, Offer, RunState, SimCommand, SimCommands, SimPhase};
use lantern_view::atlas::AtlasDb;

use crate::describe::{OfferInfo, Rarity, element_color, hex, offer_info, offer_note};
use crate::responsive::{
    CARD_GAP, CARD_HEIGHT, CARD_WIDTH, CHEST_CARD_GAP, CHEST_CARD_HEIGHT, CHEST_CARD_WIDTH, ChestCards,
    FitViewport, PANEL_WIDTH_PERCENT, UpgradeCards,
};
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

/// 卡面（docs/PLAYTEST.md 第 3 项）：上半张插画，下面卡名、一行收益、等级点。说明全文不上卡，
/// 聚焦时在卡片下方显示一行。
const CARD_NAME_SIZE: f32 = 30.0;
const CARD_GAIN_SIZE: f32 = 22.0;
const CARD_NOTE_SIZE: f32 = 15.0;
const CARD_LABEL_SIZE: f32 = 14.0;
const CARD_CAPTION_SIZE: f32 = 17.0;
/// 插画区贴着卡框内沿，正式插画保持完整的 4:3 构图。
const ART_PAD: f32 = 16.0;
const ART_HEIGHT: f32 = (CARD_WIDTH - 2.0 * ART_PAD) * 0.75;
/// 没有插画时放大的图标
const ART_ICON: f32 = 132.0;
const PAIR_ICON: f32 = 30.0;
/// 五行印的帧名后缀（`ui/icon_el_*`），按 `Element::index` 排
const ELEMENT_ICONS: [&str; 5] = ["metal", "wood", "water", "fire", "earth"];

/// 说明跟随目标卡片；焦点移到封印按钮时仍能查看将被封印的卡。
#[derive(Component)]
struct CardDetail(usize);

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
        Shown::Evolve(k) => spawn_evolve(&mut commands, c, &fonts, &db, &skin, &arsenal, &build, k),
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
                && h < n + enabled.len()
                && (h < n || enabled[h - n])
            {
                ui.selected = h;
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

/// 焦点用泥金标出；移到页脚时，目标卡留下较淡的金边，说明与封印对象仍然明确。
fn highlight(
    ui: Res<ChoiceUi>,
    flow: Res<Flow>,
    mut focus: Query<(&CardFocus, &mut Visibility, Option<&mut ImageNode>)>,
    mut reroll: Query<&mut crate::prompts::Prompt, (With<RerollLabel>, Without<BanishLabel>)>,
    mut banish: Query<&mut crate::prompts::Prompt, (With<BanishLabel>, Without<RerollLabel>)>,
) {
    for (f, mut v, image) in &mut focus {
        let (index, retained) = match *f {
            CardFocus::Selected(index) => (index, false),
            CardFocus::Target(index) => (index, index == ui.card_target),
        };
        let selected = index == ui.selected;
        v.set_if_neq(if selected || retained { Visibility::Inherited } else { Visibility::Hidden });
        if let Some(mut image) = image {
            let color = Color::WHITE.with_alpha(if selected { 1.0 } else { 0.42 });
            if image.color != color {
                image.color = color;
            }
        }
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
pub(crate) enum CardFocus {
    Selected(usize),
    Target(usize),
}

fn show_details(ui: Res<ChoiceUi>, mut details: Query<(&CardDetail, &mut Visibility)>) {
    for (detail, mut visibility) in &mut details {
        visibility.set_if_neq(if detail.0 == ui.card_target {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        });
    }
}

fn overlay(skin: &Skin) -> impl Bundle {
    overlay_with_gap(skin, 18.0)
}

fn overlay_with_gap(skin: &Skin, gap: f32) -> impl Bundle {
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
            row_gap: px(gap),
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
    let icon = name.and_then(|n| {
        db.find(n).or_else(|| {
            // 铜钱剑专属图标尚未入库，先借用已有的五帝钱；正式帧始终优先。
            matches!(n, "ui/icon_coin_sword" | "ui/icon_coin_sword_evo")
                .then(|| db.find("ui/icon_charm_five_coins"))
                .flatten()
        })
    });
    match icon {
        Some(f) => {
            // 颜色的透明度也用在图片上（配对心法没拿到时画淡）
            p.spawn((node, db.ui_image(f).with_color(Color::WHITE.with_alpha(color.alpha()))));
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

/// 插画区的底色：五行色压暗，和纸面拉开。
fn art_ground(color: Color) -> Color {
    color.mix(&Color::srgb(0.06, 0.06, 0.09), 0.78)
}

/// 一张升级卡。
#[allow(clippy::too_many_arguments)]
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
    ember: u32,
) {
    let info: OfferInfo = offer_info(c, arsenal, build, offer);
    let note = offer_note(c, arsenal, build, offer);
    // 余烬：开局心法直接到这一级
    let level = info.level.map(|(lv, max)| (if ember > 0 { ember.min(max) } else { lv }, max));
    let mut card = commands.spawn((
        Card,
        Rise::after(0.04 + i as f32 * 0.07),
        Node {
            width: px(CARD_WIDTH),
            height: px(CARD_HEIGHT),
            flex_shrink: 0.0,
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            padding: UiRect { bottom: px(ART_PAD + 4.0), ..UiRect::all(px(ART_PAD)) },
            ..default()
        },
        skin.image(card_skin(info.rarity)),
        BoxShadow::new(Color::BLACK.with_alpha(0.32), px(0), px(8), px(0), px(18)),
    ));
    card.with_children(|card| {
        // 金边贴住原卡框，避免套出另一张厚框抢过插画。
        card.spawn((
            CardFocus::Target(i),
            Visibility::Hidden,
            Pickable::IGNORE,
            Node {
                position_type: PositionType::Absolute,
                left: px(-2),
                right: px(-2),
                top: px(-2),
                bottom: px(-2),
                ..default()
            },
            skin.image("card_focus"),
        ));
        // 插画：图集里有 `ui/card_<id>` 就用，没有就放大图标
        card.spawn((
            Node {
                width: percent(100),
                height: px(ART_HEIGHT),
                flex_shrink: 0.0,
                justify_content: JustifyContent::Center,
                align_items: AlignItems::Center,
                overflow: Overflow::clip(),
                border_radius: BorderRadius::all(px(6)),
                ..default()
            },
            BackgroundColor(art_ground(info.color)),
        ))
        .with_children(|art| {
            match db.find(&info.art) {
                Some(f) => {
                    art.spawn((
                        Node { width: percent(100), height: percent(100), ..default() },
                        db.ui_image(f),
                    ));
                }
                None => spawn_icon(art, db, fonts, info.icon.as_deref(), &info.glyph, info.color, ART_ICON),
            }
            // 独立叠框不挤占画面，正式插画不会因边线改变 4:3 的比例。
            art.spawn((
                Pickable::IGNORE,
                Node {
                    position_type: PositionType::Absolute,
                    width: percent(100),
                    height: percent(100),
                    border: UiRect::all(px(1)),
                    border_radius: BorderRadius::all(px(6)),
                    ..default()
                },
                BorderColor::all(INK.with_alpha(0.35)),
            ));
            // 五行印压在左上角
            if let Some(e) = info.element {
                art.spawn(Node {
                    position_type: PositionType::Absolute,
                    left: px(8),
                    top: px(8),
                    ..default()
                })
                .with_children(|seal| {
                    let icon = format!("ui/icon_el_{}", ELEMENT_ICONS[e.index()]);
                    let color = element_color(c, e);
                    spawn_icon(seal, db, fonts, Some(&icon), &c.element(e).name, color, 34.0);
                });
            }
            // 品阶写在右上角
            art.spawn((
                Node {
                    position_type: PositionType::Absolute,
                    right: px(8),
                    top: px(8),
                    padding: UiRect::axes(px(10), px(3)),
                    ..default()
                },
                skin.image("chip_dark"),
            ))
            .with_child(text(
                &fonts.body,
                CARD_LABEL_SIZE,
                info.rarity.color(),
                info.rarity.name(),
            ));
        });
        card.spawn((
            Pickable::IGNORE,
            Node {
                width: percent(100),
                height: px(12),
                flex_shrink: 0.0,
                margin: UiRect::top(px(4)),
                ..default()
            },
            skin.image("divider"),
        ));
        // 卡名、收益、等级点、提示在插画和页脚之间居中
        let mut body = card.spawn(Node {
            width: percent(100),
            flex_grow: 1.0,
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            ..default()
        });
        body.with_children(|card| {
            card.spawn(text(&fonts.title, CARD_NAME_SIZE, INK, &info.name));
            card.spawn((
                Text::new(&info.gain),
                // 名字保留笔意；收益里的数字、百分号统一用正文字体。
                TextFont::from(fonts.body.clone()).with_font_size(CARD_GAIN_SIZE),
                TextColor(on_paper(info.color).mix(&INK, 0.25)),
                TextLayout::new(Justify::Center, bevy::text::LineBreak::AnyCharacter),
                Node { width: percent(100), margin: UiRect::top(px(4)), ..default() },
            ));
            if let Some((lv, max)) = level {
                card.spawn(Node { column_gap: px(6), margin: UiRect::top(px(10)), ..default() })
                    .with_children(|dots| {
                        for k in 1..=max {
                            dots.spawn((
                                Node { width: px(10), height: px(10), ..default() },
                                skin.image(if k <= lv { "pip_on" } else { "pip" }),
                            ));
                        }
                    });
            }
            // 共鸣、进化、合璧亮色写；普通的只写五行点数
            if let Some(n) = &note {
                card.spawn((
                    text(&fonts.body, CARD_NOTE_SIZE, n.color.map_or(INK_DIM, on_paper), &n.title),
                    TextLayout::justify(Justify::Center),
                    Node { width: percent(100), margin: UiRect::top(px(8)), ..default() },
                ));
            }
        });
        // 页脚：类别；进化配对（没拿到的画淡）；按键
        // 卡框的花边画在图片里面一圈，页脚再往里收一点
        card.spawn(Node {
            width: percent(100),
            align_items: AlignItems::Center,
            justify_content: JustifyContent::SpaceBetween,
            padding: UiRect::horizontal(px(10)),
            // 有没有配对图标都一样高，卡名对齐
            min_height: px(PAIR_ICON),
            ..default()
        })
        .with_children(|foot| {
            foot.spawn(text(&fonts.body, CARD_LABEL_SIZE, INK_DIM, &info.kind));
            foot.spawn(Node { align_items: AlignItems::Center, column_gap: px(8), ..default() })
                .with_children(|right| {
                    if let Some(p) = &info.pair {
                        let color = on_paper(p.color).with_alpha(if p.owned { 1.0 } else { 0.5 });
                        spawn_icon(right, db, fonts, Some(&p.icon), &p.glyph, color, PAIR_ICON);
                    }
                    right.spawn(crate::prompts::hint(
                        &fonts.title,
                        18.0,
                        INK_DIM,
                        &format!("{{pick{}}}", i + 1),
                    ));
                });
        });
    });
    card.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| ui.clicked = Some(i));
    card.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| ui.hovered = Some(i));
}

/// 聚焦卡的完整说明：一行正文，再加一行进化或共鸣的细节，没有细节时写配对。
fn caption(c: &Content, arsenal: &Arsenal, build: &Build, offer: Offer) -> String {
    let info = offer_info(c, arsenal, build, offer);
    let detail =
        offer_note(c, arsenal, build, offer).map(|n| n.body).filter(|b| !b.is_empty()).or_else(|| {
            info.pair.as_ref().map(|p| match offer {
                Offer::NewWeapon(_) | Offer::WeaponUp(_) => format!("进化需心法「{}」", p.name),
                _ => format!("可让「{}」进化", p.name),
            })
        });
    match detail {
        Some(d) => format!("{} · {}\n{d}", info.name, info.desc),
        None => format!("{} · {}", info.name, info.desc),
    }
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
    commands.spawn(overlay_with_gap(skin, 12.0)).insert(FitViewport::Upgrades(offers.len())).with_children(
        |root| {
            root.spawn(Node {
                max_width: percent(PANEL_WIDTH_PERCENT),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                ..default()
            })
            .with_children(|head| {
                head.spawn(text(&fonts.title, 48.0, PAPER, if ember > 0 { "余烬" } else { "升级" }));
                let sub = if ember > 0 {
                    format!("开局心法三选一　·　选中的那门直接到 Lv{ember}")
                } else if inspired {
                    format!("Lv {} → {}　·　灵光一闪，多一个选项", level - 1, level)
                } else {
                    format!("Lv {} → {}", level - 1, level)
                };
                head.spawn((
                    text(&fonts.body, 18.0, if inspired { hex("#FFD98A") } else { DIM }, &sub),
                    TextLayout::justify(Justify::Center),
                    Node { max_width: percent(100), ..default() },
                ));
            });
            let cards = offers.len() as f32;
            let width = CARD_WIDTH * cards + CARD_GAP * (cards - 1.0).max(0.0);
            root.spawn((
                UpgradeCards(offers.len()),
                Node {
                    display: Display::Grid,
                    width: percent(PANEL_WIDTH_PERCENT),
                    max_width: px(width),
                    flex_shrink: 0.0,
                    justify_content: JustifyContent::Center,
                    column_gap: px(CARD_GAP),
                    row_gap: px(CARD_GAP),
                    ..default()
                },
            ))
            .with_children(|row| {
                for (i, &o) in offers.iter().enumerate() {
                    card(row, c, fonts, db, skin, arsenal, build, i, o, ember);
                }
            });
            // 同一网格单元保留最长说明的实际高度；窄窗口换行也不压住操作区。
            // 一两张卡时也按三张的宽度排，说明不会挤成好几行
            root.spawn(Node {
                display: Display::Grid,
                grid_template_columns: vec![GridTrack::flex(1.0)],
                width: percent(PANEL_WIDTH_PERCENT),
                max_width: px(width.max(CARD_WIDTH * 3.0 + CARD_GAP * 2.0)),
                min_height: px(CARD_CAPTION_SIZE * 2.8),
                flex_shrink: 0.0,
                ..default()
            })
            .with_children(|slot| {
                for (i, &o) in offers.iter().enumerate() {
                    slot.spawn((
                        CardDetail(i),
                        Visibility::Hidden,
                        text(&fonts.body, CARD_CAPTION_SIZE, PAPER, &caption(c, arsenal, build, o)),
                        TextShadow { offset: Vec2::new(0.0, 2.0), color: Color::BLACK.with_alpha(0.8) },
                        TextLayout::justify(Justify::Center),
                        Node {
                            grid_row: GridPlacement::start(1),
                            grid_column: GridPlacement::start(1),
                            width: percent(100),
                            ..default()
                        },
                    ));
                }
            });
            root.spawn((
                Node { max_width: percent(PANEL_WIDTH_PERCENT), ..default() },
                TextLayout::justify(Justify::Center),
                crate::prompts::hint(
                    &fonts.body,
                    17.0,
                    DIM,
                    "{nav} 选择　上下切换卡片与操作　{confirm} 确定",
                ),
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
                            min_height: px(52),
                            padding: UiRect::axes(px(20), px(12)),
                            align_items: AlignItems::Center,
                            justify_content: JustifyContent::Center,
                            ..default()
                        },
                        skin.image(if enabled { "btn" } else { "btn_disabled" }),
                    ));
                    if enabled {
                        button.observe(move |_: On<PointerClick>, mut ui: ResMut<ChoiceUi>| {
                            ui.clicked = Some(i);
                        });
                        button.observe(move |_: On<PointerOver>, mut ui: ResMut<ChoiceUi>| {
                            ui.hovered = Some(i);
                        });
                    }
                    button.with_children(|b| {
                        b.spawn((
                            CardFocus::Selected(i),
                            Visibility::Hidden,
                            Pickable::IGNORE,
                            Node {
                                position_type: PositionType::Absolute,
                                left: px(0),
                                right: px(0),
                                top: px(0),
                                bottom: px(0),
                                ..default()
                            },
                            skin.image("btn_focus"),
                        ));
                        let mut label = b.spawn((
                            Pickable::IGNORE,
                            crate::prompts::hint(
                                &fonts.body,
                                17.0,
                                if enabled { PAPER } else { hex("#B5AB98") },
                                label,
                            ),
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
        },
    );
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
            CardFocus::Selected(i),
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

/// 一箱可能连续升级同一件法器；最终构筑不能替代每件奖励自己的等级快照。
/// 只为描述恢复领取前一级，让现有 OfferInfo 计算本次收益，不修改模拟状态。
fn chest_info(c: &Content, arsenal: &Arsenal, build: &Build, item: &ChestItem) -> OfferInfo {
    match item.offer {
        Offer::WeaponUp(k) => {
            let mut before = Arsenal(arsenal.0.clone());
            before.0[k].level = item.level.saturating_sub(1).max(1);
            offer_info(c, &before, build, item.offer)
        }
        Offer::PassiveUp(k) => {
            let mut before = build.clone();
            before.passives[k].level = item.level.saturating_sub(1);
            offer_info(c, arsenal, &before, item.offer)
        }
        _ => offer_info(c, arsenal, build, item.offer),
    }
}

fn chest_card(
    parent: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    info: &OfferInfo,
    item: &ChestItem,
    index: usize,
    gold: bool,
) {
    let at = CHIME_AT + index as f32 * CHIME_GAP;
    let outcome = match item.offer {
        Offer::WeaponUp(_) | Offer::PassiveUp(_) => {
            format!("Lv{} → {}", item.level.saturating_sub(1), item.level)
        }
        Offer::NewWeapon(_) | Offer::NewPassive(_) => format!("{} · Lv{}", info.kind, item.level),
        _ => info.kind.clone(),
    };
    parent
        .spawn((
            Card,
            Rise::after(at - 0.05),
            Node {
                width: px(CHEST_CARD_WIDTH),
                height: px(CHEST_CARD_HEIGHT),
                flex_shrink: 0.0,
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                padding: UiRect::all(px(12)),
                ..default()
            },
            skin.image(card_skin(info.rarity)),
            BoxShadow::new(Color::BLACK.with_alpha(0.3), px(0), px(6), px(0), px(14)),
        ))
        .with_children(|card| {
            card.spawn((
                Node {
                    width: percent(100),
                    height: px((CHEST_CARD_WIDTH - 24.0) * 0.75),
                    flex_shrink: 0.0,
                    align_items: AlignItems::Center,
                    justify_content: JustifyContent::Center,
                    ..default()
                },
                BackgroundColor(art_ground(info.color)),
            ))
            .with_children(|art| {
                if let Some(frame) = db.find(&info.art) {
                    art.spawn((
                        Node { width: percent(100), height: percent(100), ..default() },
                        db.ui_image(frame),
                    ));
                } else {
                    spawn_icon(art, db, fonts, info.icon.as_deref(), &info.glyph, info.color, 104.0);
                }
                art.spawn((
                    Node {
                        position_type: PositionType::Absolute,
                        top: px(6),
                        right: px(6),
                        padding: UiRect::axes(px(8), px(3)),
                        ..default()
                    },
                    skin.image("chip_dark"),
                ))
                .with_child(text(
                    &fonts.body,
                    13.0,
                    info.rarity.color(),
                    info.rarity.name(),
                ));
            });
            card.spawn(Node {
                width: percent(100),
                flex_grow: 1.0,
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                row_gap: px(6),
                ..default()
            })
            .with_children(|body| {
                body.spawn((
                    text(&fonts.title, 28.0, on_paper(info.color), &info.name),
                    TextLayout::justify(Justify::Center),
                    Node { width: percent(100), ..default() },
                ));
                body.spawn(text(&fonts.body, 16.0, INK_DIM, &outcome));
                body.spawn((
                    text(&fonts.body, 18.0, INK, &info.gain),
                    TextLayout::new(Justify::Center, bevy::text::LineBreak::AnyCharacter),
                    Node { width: percent(100), ..default() },
                ));
                if let Some((level, max)) = info.level {
                    body.spawn(Node { column_gap: px(4), ..default() }).with_children(|dots| {
                        for step in 1..=max {
                            dots.spawn((
                                Node { width: px(8), height: px(8), ..default() },
                                skin.image(if step <= level { "pip_on" } else { "pip" }),
                            ));
                        }
                    });
                }
            });
            // 金光只掠过卡边，不盖白整张插画；时刻仍和原开箱钟声一致。
            card.spawn((
                Pickable::IGNORE,
                ChestGlow { part: ChestPart::Item { at, peak: if gold { 0.9 } else { 0.65 } }, t: 0.0 },
                Node {
                    position_type: PositionType::Absolute,
                    left: px(-2),
                    right: px(-2),
                    top: px(-2),
                    bottom: px(-2),
                    ..default()
                },
                skin.image("card_focus").with_color(Color::WHITE.with_alpha(0.0)),
            ));
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
    let n = chest.items.len();
    let source = match chest.source {
        ChestSource::Altar => "血祭\n以血换力",
        ChestSource::MiniBoss => "小头目的宝箱",
        ChestSource::Merchant => "货郎的宝箱",
        _ => "宝箱",
    };
    let title = match n {
        1 => source.to_string(),
        3 => format!("{source}\n三连"),
        5 => format!("{source}\n五连"),
        _ => format!("{source}\n{n}连"),
    };
    // 三连以上标题盖下来；五连每张卡的金边更亮，最后一声钟后整组泛起金光。
    let big = n >= 3;
    let gold = n >= 5;
    commands
        .spawn(overlay(skin))
        .insert(FitViewport::ChestRewards(n))
        .with_children(|root| {
            let mut title = root.spawn((
                text(&fonts.title, if big { 34.0 } else { 48.0 }, CHEST_GOLD, &title),
                TextLayout::new(Justify::Center, bevy::text::LineBreak::NoWrap),
                Node {
                    // 来源与连数各占完整行；字号为原有放大动画留宽，不靠挤窄文字换行。
                    max_width: percent(PANEL_WIDTH_PERCENT),
                    flex_shrink: 0.0,
                    ..default()
                },
            ));
            if big {
                // 先藏着、放大，第一帧就从大到小砸下来
                title.insert((
                    ChestGlow { part: ChestPart::Title, t: 0.0 },
                    TextColor(CHEST_GOLD.with_alpha(0.0)),
                    TextShadow { offset: Vec2::new(3.0, 3.0), color: Color::BLACK.with_alpha(0.0) },
                    UiTransform::from_scale(Vec2::splat(CHEST_TITLE_SCALE)),
                ));
            }
            let width = CHEST_CARD_WIDTH * n as f32 + CHEST_CARD_GAP * n.saturating_sub(1) as f32;
            let mut cards = root.spawn((
                ChestCards(n),
                Node {
                    display: Display::Grid,
                    width: percent(PANEL_WIDTH_PERCENT),
                    max_width: px(width),
                    flex_shrink: 0.0,
                    justify_content: JustifyContent::Center,
                    column_gap: px(CHEST_CARD_GAP),
                    row_gap: px(CHEST_CARD_GAP),
                    border_radius: BorderRadius::all(px(14)),
                    ..default()
                },
            ));
            if gold {
                cards.insert((
                    ChestGlow { part: ChestPart::Halo { at: CHIME_AT + n as f32 * CHIME_GAP }, t: 0.0 },
                    BoxShadow::new(CHEST_GOLD.with_alpha(0.0), px(0), px(0), px(6), px(44)),
                ));
            }
            cards.with_children(|grid| {
                for (k, item) in chest.items.iter().enumerate() {
                    let info = chest_info(c, arsenal, build, item);
                    chest_card(grid, fonts, db, skin, &info, item, k, gold);
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
const CHEST_TITLE_SCALE: f32 = 1.7;

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
    /// 单卡：钟响时金边亮一下再暗下去；peak 是最亮时的不透明度。
    Item { at: f32, peak: f32 },
    /// 五连：最后一声钟后整组外圈泛起金光，留一圈淡的。
    Halo { at: f32 },
}

pub(crate) fn animate_chest(
    time: Res<Time<Real>>,
    mut q: Query<(
        &mut ChestGlow,
        Option<&mut ImageNode>,
        Option<&mut BoxShadow>,
        &mut UiTransform,
        Option<&mut TextColor>,
        Option<&mut TextShadow>,
    )>,
) {
    let dt = time.delta_secs().min(0.1);
    for (mut g, image, shadow, mut tf, color, text_shadow) in &mut q {
        g.t += dt;
        let t = g.t;
        match g.part {
            ChestPart::Title => {
                if t > 0.6 {
                    continue;
                }
                let k = (t / 0.16).min(1.0);
                let s = if t < 0.16 {
                    CHEST_TITLE_SCALE - (CHEST_TITLE_SCALE - 1.0) * k * k
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
            ChestPart::Item { at, peak } => {
                let k = t - at;
                if !(0.0..=1.6).contains(&k) {
                    continue;
                }
                let a = peak * (k / 0.05).min(1.0) * (-(k - 0.05).max(0.0) * 3.5).exp();
                if let Some(mut image) = image {
                    image.color.set_alpha(a);
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

/// 进化演出的各部分（docs/FEEL.md 第 5 节）：旧法器化墨淡去，新形态完整显现，
/// 最后盖章，名字和收益淡入。沿用 2.1 秒后自动确认，也允许玩家提前确认。
#[derive(Component, Clone, Copy)]
pub(crate) enum EvoPart {
    Old,
    New,
    Seal,
    Text(f32),
}

/// 进化演出的计时（现实秒）。
#[derive(Component, Default)]
pub(crate) struct EvoClock(f32);

const EVOLVE_ART_SIZE: Vec2 = Vec2::new(400.0, 300.0);

/// 演出发生在质变生效之后；合璧材料从内容中还原，仅供既有卡片描述读取。
/// 图片、名字、收益都和选择时那张卡一致，不再把异化或合璧画成正统进化图标。
fn evolution_info(c: &Content, arsenal: &Arsenal, build: &Build, k: usize) -> (OfferInfo, Vec<OfferInfo>) {
    use lantern_sim::weapons::{Form, WeaponSlot};
    let w = &arsenal.0[k];
    if let Form::Fused(fusion_id) = w.form {
        let materials = Arsenal(
            c.fusions[fusion_id]
                .weapons
                .iter()
                .map(|id| WeaponSlot::new(c.weapon_index(id).expect("合璧材料")))
                .collect(),
        );
        let result = offer_info(c, &materials, build, Offer::Fuse { a: 0, b: 1, fusion_id });
        let origins =
            (0..materials.0.len()).map(|i| offer_info(c, &materials, build, Offer::Evolve(i))).collect();
        (result, origins)
    } else {
        let offer = match w.form {
            Form::Evolved => Offer::Evolve(k),
            Form::Mutated => Offer::Mutate(k),
            _ => Offer::NewWeapon(w.def),
        };
        (offer_info(c, arsenal, build, offer), vec![offer_info(c, arsenal, build, Offer::NewWeapon(w.def))])
    }
}

/// 插画保留 4:3 全幅；缺图时的图标或字形也挂同一演出部件，不能提前常亮。
fn evolution_visual(
    parent: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    db: &AtlasDb,
    info: &OfferInfo,
    part: EvoPart,
    size: Vec2,
) {
    let alpha = if matches!(part, EvoPart::Old) { 1.0 } else { 0.0 };
    parent
        .spawn(Node {
            width: px(size.x),
            height: px(size.y),
            flex_shrink: 0.0,
            justify_content: JustifyContent::Center,
            align_items: AlignItems::Center,
            ..default()
        })
        .with_children(|layer| {
            let image = db.find(&info.art).map(|frame| (frame, size)).or_else(|| {
                info.icon
                    .as_deref()
                    .and_then(|name| db.find(name))
                    .map(|frame| (frame, Vec2::splat((size.y * 0.7).min(144.0))))
            });
            match image {
                Some((frame, size)) => {
                    layer.spawn((
                        part,
                        UiTransform::default(),
                        Node { width: px(size.x), height: px(size.y), ..default() },
                        db.ui_image(frame).with_color(Color::WHITE.with_alpha(alpha)),
                    ));
                }
                None => {
                    layer.spawn((
                        part,
                        UiTransform::default(),
                        text(&fonts.title, (size.y * 0.55).min(96.0), PAPER.with_alpha(alpha), &info.glyph),
                    ));
                }
            }
        });
}

fn spawn_evolve(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    arsenal: &Arsenal,
    build: &Build,
    k: usize,
) {
    let w = &arsenal.0[k];
    let (info, origins) = evolution_info(c, arsenal, build, k);
    let stamp = match w.form {
        lantern_sim::weapons::Form::Mutated => "异化",
        lantern_sim::weapons::Form::Fused(_) => "合璧",
        _ => "进化",
    };
    let origin = origins.iter().map(|info| info.name.as_str()).collect::<Vec<_>>().join(" + ");
    let words = || Node { width: percent(90), max_width: px(700), flex_shrink: 0.0, ..default() };
    commands
        .spawn((overlay_with_gap(skin, 10.0), EvoClock::default()))
        // 单幅成果页无需沿用三张升级卡的最小宽度，竖窗里也能保留可读字号。
        .insert(FitViewport::Fixed(Vec2::new(800.0, 640.0)))
        .with_children(|root| {
            root.spawn((
                EvoPart::Text(0.7),
                words(),
                TextLayout::justify(Justify::Center),
                text(&fonts.body, 17.0, PAPER.with_alpha(0.0), &format!("{origin} → {}", info.name)),
            ));
            root.spawn((
                Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    flex_shrink: 0.0,
                    padding: UiRect::all(px(12)),
                    row_gap: px(8),
                    ..default()
                },
                skin.image(card_skin(info.rarity)),
                BoxShadow::new(Color::BLACK.with_alpha(0.35), px(0), px(8), px(0), px(20)),
            ))
            .with_children(|frame| {
                frame.spawn((
                    EvoPart::Seal,
                    UiTransform::default(),
                    text(&fonts.title, 28.0, on_paper(info.color).with_alpha(0.0), stamp),
                ));
                frame
                    .spawn((
                        Node {
                            width: px(EVOLVE_ART_SIZE.x),
                            height: px(EVOLVE_ART_SIZE.y),
                            flex_shrink: 0.0,
                            overflow: Overflow::clip(),
                            ..default()
                        },
                        BackgroundColor(art_ground(info.color)),
                    ))
                    .with_children(|art| {
                        let layer = || Node {
                            position_type: PositionType::Absolute,
                            width: percent(100),
                            height: percent(100),
                            align_items: AlignItems::Center,
                            justify_content: JustifyContent::Center,
                            column_gap: px(12),
                            ..default()
                        };
                        art.spawn(layer()).with_children(|new| {
                            evolution_visual(new, fonts, db, &info, EvoPart::New, EVOLVE_ART_SIZE);
                        });
                        art.spawn(layer()).with_children(|old| {
                            let width = (EVOLVE_ART_SIZE.x - 12.0 * (origins.len() - 1) as f32)
                                / origins.len() as f32;
                            for origin in &origins {
                                evolution_visual(
                                    old,
                                    fonts,
                                    db,
                                    origin,
                                    EvoPart::Old,
                                    Vec2::new(width, width * 0.75),
                                );
                            }
                        });
                    });
            });
            root.spawn((
                EvoPart::Text(1.0),
                words(),
                TextLayout::justify(Justify::Center),
                text(&fonts.title, 60.0, info.color.with_alpha(0.0), &info.name),
            ));
            root.spawn((
                EvoPart::Text(1.0),
                words(),
                TextLayout::justify(Justify::Center),
                text(&fonts.body, 24.0, PAPER.with_alpha(0.0), &info.gain),
            ));
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
    settings: Res<lantern_platform::Settings>,
    mut clocks: Query<&mut EvoClock>,
    mut parts: Query<(&EvoPart, Option<&mut UiTransform>, Option<&mut ImageNode>, Option<&mut TextColor>)>,
) {
    let Some(mut clock) = clocks.iter_mut().next() else { return };
    clock.0 += time.delta_secs().min(0.1);
    let t = clock.0;
    let motion = if settings.lite_fx { 0.0 } else { 1.0 };
    // 旧器先化墨淡去；新画从略小的尺寸落定，任何时刻都不裁掉构图。
    let ink = smooth(t / 0.45);
    let gone = smooth((t - 0.35) / 0.4);
    // 新形态仍从 0.55 秒开始显现。
    let born = (t - 0.55) / 0.4;
    // 印：0.95 秒砸下
    let stamp = (t - 0.95) / 0.12;
    let words = smooth((t - 0.8) / 0.5);
    for (part, tf, img, txt) in &mut parts {
        match part {
            EvoPart::Old => {
                let c = Color::WHITE.mix(&Color::srgb(0.06, 0.06, 0.08), ink).with_alpha(1.0 - gone);
                if let Some(mut img) = img {
                    img.color = c;
                }
                if let Some(mut color) = txt {
                    color.0 = c;
                }
                if let Some(mut tf) = tf {
                    // 化墨前轻轻一颤
                    let shake = if t < 0.35 {
                        (t * 70.0).sin() * 3.0 * (1.0 - t / 0.35) * settings.shake.clamp(0.0, 1.0) * motion
                    } else {
                        0.0
                    };
                    tf.translation = bevy::ui::Val2::px(shake, 0.0);
                    tf.scale = Vec2::splat(1.0 - 0.04 * gone * motion);
                }
            }
            EvoPart::New => {
                if let Some(mut img) = img {
                    img.color = Color::WHITE.with_alpha(smooth(born * 1.5));
                }
                if let Some(mut color) = txt {
                    color.0.set_alpha(smooth(born * 1.5));
                }
                if let Some(mut tf) = tf {
                    tf.scale = Vec2::splat(1.0 - 0.06 * (1.0 - smooth(born)) * motion);
                }
            }
            EvoPart::Seal => {
                if let Some(mut color) = txt {
                    color.0.set_alpha(smooth(stamp * 2.0));
                }
                if let Some(mut img) = img {
                    img.color = Color::WHITE.with_alpha(smooth(stamp * 2.0));
                }
                if let Some(mut tf) = tf {
                    let k = stamp.clamp(0.0, 1.0);
                    tf.scale = Vec2::splat(1.0 + 0.4 * (1.0 - k * k) * motion);
                    tf.rotation = Rot2::radians(-0.06 * k * motion);
                }
            }
            EvoPart::Text(alpha) => {
                if let Some(mut c) = txt {
                    c.0.set_alpha(words * alpha);
                }
            }
        }
    }
}

#[cfg(test)]
mod chest_tests {
    use super::*;
    use lantern_sim::build::PassiveSlot;
    use lantern_sim::weapons::{Form, WeaponSlot};

    #[test]
    fn repeated_chest_upgrades_use_each_items_received_level() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets");
        let c = Content::load(&root.join("data")).unwrap();
        let lamp = c.weapon_index("lamp").unwrap();
        let paper = c.passive_index("zhezhi").unwrap();
        let mut arsenal = Arsenal(vec![WeaponSlot { level: 4, ..WeaponSlot::new(lamp) }]);
        let build = Build { passives: vec![PassiveSlot { def: paper, level: 5 }], ..default() };
        for received in [2, 3] {
            let info =
                chest_info(&c, &arsenal, &build, &ChestItem { offer: Offer::WeaponUp(0), level: received });
            let levels = &c.weapons[lamp].levels;
            let expected = crate::describe::weapon_upgrade_text(
                &levels[received as usize - 2],
                &levels[received as usize - 1],
            );
            assert_eq!(info.desc, format!("{expected}。"));
            assert_eq!(info.level, Some((received, levels.len() as u32)));
        }
        let passive = chest_info(&c, &arsenal, &build, &ChestItem { offer: Offer::PassiveUp(0), level: 2 });
        assert_eq!(passive.level, Some((2, 5)));
        assert_eq!(passive.art, "ui/card_zhezhi");
        assert_eq!(arsenal.0[0].level, 4);
        assert_eq!(build.passives[0].level, 5);

        // 后一项已让同一法器进化，先前的满级卡仍展示领取当时的原形与等级。
        let max = c.weapons[lamp].levels.len() as u32;
        arsenal.0[0].level = max;
        arsenal.0[0].form = Form::Evolved;
        let before_evolution =
            chest_info(&c, &arsenal, &build, &ChestItem { offer: Offer::WeaponUp(0), level: max });
        let evolved = chest_info(&c, &arsenal, &build, &ChestItem { offer: Offer::Evolve(0), level: max });
        assert_eq!(before_evolution.level, Some((max, max)));
        assert_eq!(before_evolution.art, "ui/card_lamp");
        assert_eq!(evolved.art, "ui/card_lamp_evo");
        assert!(evolved.level.is_none());
    }
}

#[cfg(test)]
mod evolution_tests {
    use super::*;
    use bevy::ecs::system::RunSystemOnce;
    use lantern_sim::weapons::{Form, WeaponSlot};

    #[test]
    fn result_art_tracks_evolved_mutated_and_fused_forms() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets");
        let c = Content::load(&root.join("data")).unwrap();
        let fusion = c.fusions.iter().position(|f| f.id == "phoenix").unwrap();
        for (id, form, art, name) in [
            ("lamp", Form::Evolved, "ui/card_lamp_evo", "不夜城"),
            ("lamp", Form::Mutated, "ui/card_lamp_mut", "冰火两重天"),
            ("crane", Form::Fused(fusion), "ui/card_phoenix", "百鸟朝凤"),
            ("coin_sword", Form::Evolved, "ui/card_coin_sword_evo", "天罡"),
        ] {
            let arsenal = Arsenal(vec![WeaponSlot { form, ..WeaponSlot::new(c.weapon_index(id).unwrap()) }]);
            let (result, origins) = evolution_info(&c, &arsenal, &Build::default(), 0);
            assert_eq!(result.art, art);
            assert_eq!(result.name, name);
            assert!(!result.gain.is_empty());
            if matches!(form, Form::Fused(_)) {
                assert_eq!(
                    origins.iter().map(|info| info.art.as_str()).collect::<Vec<_>>(),
                    ["ui/card_crane_evo", "ui/card_lamp_evo"]
                );
            } else {
                assert_eq!(origins.len(), 1);
                assert_eq!(origins[0].art, format!("ui/card_{id}"));
            }
        }
    }

    #[test]
    fn missing_art_and_icon_keep_the_glyph_in_the_reveal_timing() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets");
        let c = Content::load(&root.join("data")).unwrap();
        let arsenal = Arsenal(vec![WeaponSlot {
            form: Form::Mutated,
            ..WeaponSlot::new(c.weapon_index("lamp").unwrap())
        }]);
        let (mut info, _) = evolution_info(&c, &arsenal, &Build::default(), 0);
        info.art = "ui/missing_result_art".into();
        info.icon = Some("ui/missing_result_icon".into());
        let mut app = App::new();
        let mut settings = lantern_platform::Settings::default();
        settings.lite_fx = true;
        app.add_plugins((
            MinimalPlugins,
            AssetPlugin { file_path: root.to_str().unwrap().to_owned(), ..default() },
        ))
        .init_asset::<Image>()
        .init_asset::<TextureAtlasLayout>()
        .insert_resource(settings);
        app.world_mut()
            .run_system_once(
                move |mut commands: Commands,
                      assets: Res<AssetServer>,
                      mut layouts: ResMut<Assets<TextureAtlasLayout>>| {
                    let db = AtlasDb::load(&root, &assets, &mut layouts).unwrap();
                    let fonts = Fonts { title: default(), body: default() };
                    commands.spawn((Node::default(), EvoClock::default())).with_children(|parent| {
                        evolution_visual(parent, &fonts, &db, &info, EvoPart::New, EVOLVE_ART_SIZE);
                    });
                },
            )
            .unwrap();
        app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(100));
        for step in 1..=10 {
            app.world_mut().run_system_once(animate_evolve).unwrap();
            let world = app.world_mut();
            let (part, color, transform) = world
                .query_filtered::<(&EvoPart, &TextColor, &UiTransform), With<Text>>()
                .single(world)
                .unwrap();
            assert!(matches!(part, EvoPart::New));
            if step <= 5 {
                assert_eq!(color.0.alpha(), 0.0);
            } else if step == 10 {
                assert_eq!(color.0.alpha(), 1.0);
            }
            // 精简模式只淡入淡出，字形回退也没有缩放或颤动。
            assert_eq!(*transform, UiTransform::IDENTITY);
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
            app.world_mut().spawn((CardFocus::Target(i), Visibility::Hidden, ImageNode::default()));
            app.world_mut().spawn((CardDetail(i), Visibility::Hidden));
        }
        app
    }

    fn assert_expanded(app: &mut App, selected: usize) {
        assert_eq!(app.world().resource::<ChoiceUi>().card_target, selected);
        let world = app.world_mut();
        for (detail, visibility) in world.query::<(&CardDetail, &Visibility)>().iter(world) {
            assert_eq!(*visibility != Visibility::Hidden, detail.0 == selected);
        }
        let footer_focused = world.resource::<ChoiceUi>().selected >= 4;
        for (focus, visibility, image) in world.query::<(&CardFocus, &Visibility, &ImageNode)>().iter(world) {
            let CardFocus::Target(index) = *focus else { continue };
            assert_eq!(*visibility != Visibility::Hidden, index == selected);
            if index == selected {
                assert_eq!(image.color.alpha(), if footer_focused { 0.42 } else { 1.0 });
            }
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

        // 没有次数的页脚按钮不接走鼠标焦点，否则下一次回车会落在无效操作上。
        app.world_mut().resource_mut::<ChoiceUi>().hovered = Some(4);
        app.insert_resource(Actions { pointer_moved: true, ..default() });
        app.update();
        assert_eq!(app.world().resource::<ChoiceUi>().selected, 2);
        assert_expanded(&mut app, 2);

        // 移到页脚仍显示将被操作的目标卡；返回后确认也不会换卡。
        app.insert_resource(Actions { nav: IVec2::Y, ..default() });
        app.update();
        assert!(app.world().resource::<ChoiceUi>().selected >= 4);
        assert_expanded(&mut app, 2);
        app.update();
        assert_eq!(app.world().resource::<ChoiceUi>().selected, 2);

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
}
