//! 标题界面：出发前抽夜签三选一、心灯（局外成长）、设置。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::{Actions, HubNews, MenuSoundscape, Profile, Settings, UiCue};
use lantern_sim::omens::{draw_omens, omen_good, omen_name};
use lantern_sim::{AppState, GameContent, OmenPick, RunSetup};

use bevy::ui::widget::NodeImageMode;
use lantern_view::atlas::AtlasDb;

use crate::choice::spawn_icon;
use crate::describe::{element_color, hex};
use crate::settings_ui::{self, ADVANCED_ITEMS, ITEMS, PrimaryWindowQuery};
use crate::skin::Skin;
use crate::{CINNABAR, DIM, Fonts, GodMode, INK, INK_DIM, PAPER, SeedOverride, bench, hub, on_paper, text};

/// 标题界面上打开的面板。
#[derive(Resource, Default, Clone, Debug, PartialEq)]
pub(crate) enum TitleMode {
    #[default]
    Main,
    /// 夜签三选一：这一局的种子和抽到的夜签
    Omen {
        seed: u64,
        picks: Vec<OmenPick>,
    },
    /// 出发前：选更、择灯、挂灯坠、选悟、开关属性
    Prep,
    /// 灯驿和里面的四处
    Hub,
    Meta,
    Shop,
    Achievements,
    Codex,
    /// 设置
    Settings,
    AdvancedSettings,
    /// 开场卷轴：看完用这份设置出发
    Scroll {
        setup: Box<RunSetup>,
        dawn: bool,
    },
}

#[derive(Resource, Default)]
pub(crate) struct TitleUi {
    pub(crate) selected: usize,
    pub(crate) clicked: Option<usize>,
    pub(crate) hovered: Option<usize>,
    /// 面板变了，需要重画
    pub(crate) dirty: bool,
}

#[derive(Component)]
pub(crate) struct TitlePanel;

/// 结算指定的落点，只在真正进入标题场景时消费。
#[derive(Resource)]
pub(crate) struct ReturnToHub;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<TitleMode>()
        .init_resource::<TitleUi>()
        .add_systems(OnEnter(AppState::Title), (enter, spawn_background))
        .add_systems(Update, sync_soundscape.after(input).run_if(in_state(AppState::Title)))
        .add_systems(
            Update,
            (
                input,
                redraw,
                highlight,
                crate::scroll::animate,
                crate::hub_scene::sync_scene,
                crate::hub_scene::refresh_scene,
                crate::cover::fit_covers,
            )
                .chain()
                .run_if(in_state(AppState::Title)),
        );
}

/// 灯驿长卷上的几处换成灯驿的环境声和混响；音频读这个资源，界面不直接碰音轨。
fn sync_soundscape(mode: Res<TitleMode>, mut soundscape: ResMut<MenuSoundscape>) {
    let scene = if on_scroll(&mode) { MenuSoundscape::Hub } else { MenuSoundscape::Title };
    soundscape.set_if_neq(scene);
}

/// 灯驿长卷上的面板：彼此切换不转场，环境声也算灯驿。
fn on_scroll(m: &TitleMode) -> bool {
    matches!(
        m,
        TitleMode::Hub | TitleMode::Meta | TitleMode::Shop | TitleMode::Achievements | TitleMode::Codex
    )
}

pub(super) fn enter(
    mut commands: Commands,
    hub: Option<Res<ReturnToHub>>,
    mut mode: ResMut<TitleMode>,
    mut ui: ResMut<TitleUi>,
    content: Res<GameContent>,
    mut profile: ResMut<Profile>,
) {
    *mode = if hub.is_some() && profile.basics { TitleMode::Hub } else { TitleMode::Main };
    commands.remove_resource::<ReturnToHub>();
    *ui = TitleUi { dirty: true, ..default() };
    // 老存档迁移（要等内容加载好）
    if profile.upgrade(&content.0) {
        info!("存档已迁移到第 {} 版", profile.version);
        if let Err(e) = profile.save() {
            warn!("保存存档失败：{e}");
        }
    }
}

/// 只用于挑选新一局的种子，不参与模拟。
pub(crate) fn random_seed() -> u64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    nanos % 1_000_000_000
}

pub(crate) fn input(
    actions: Res<Actions>,
    content: Res<GameContent>,
    (seed, god): (Res<SeedOverride>, Res<GodMode>),
    mut profile: ResMut<Profile>,
    mut news: ResMut<HubNews>,
    mut settings: ResMut<Settings>,
    mut controls: ResMut<crate::controls::Controls>,
    mut window: PrimaryWindowQuery,
    mut mode: ResMut<TitleMode>,
    mut ui: ResMut<TitleUi>,
    mut commands: Commands,
    mut next: ResMut<NextState<AppState>>,
    mut exit: MessageWriter<AppExit>,
    mut transition: ResMut<crate::transition::InkTransition>,
    mut cues: MessageWriter<UiCue>,
    (mut reader, dev): (ResMut<crate::journals::Reader>, Option<Res<crate::dev_panel::DevPanel>>),
) {
    // 手记、开发者面板开着时，按键归它们
    if controls.is_open() || transition.active() || reader.open || dev.is_some_and(|d| d.open) {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
    let previous = mode.clone();
    let selected = ui.selected;
    let c = &content.0;
    let clicked = ui.clicked.take();
    let open = |ui: &mut TitleUi| {
        ui.selected = 0;
        ui.dirty = true;
    };
    match mode.clone() {
        TitleMode::Main => {
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h;
            }
            if actions.nav.y != 0 {
                ui.selected = crate::navigation::cycle_enabled(
                    ui.selected,
                    actions.nav.y,
                    &[true, profile.basics, true, true],
                );
            }
            // 菜单：0 出发、1 灯驿、2 设置、3 退出；快捷键直接对应
            let act = clicked
                .or(actions.confirm.then_some(ui.selected))
                .or(actions.meta.then_some(1))
                .or(actions.back.then_some(3));
            match act {
                Some(0) => {
                    let seed = seed.0.unwrap_or_else(random_seed);
                    if profile.basics {
                        hub::normalize_last(c, &mut profile);
                        *mode = TitleMode::Prep;
                        // 光标默认停在“出发”上
                        ui.selected = hub::prep_rows(c, &profile).len() - 1;
                        ui.dirty = true;
                    } else {
                        // 第一局直接出发：一更、初始的灯，不抽夜签、不挂灯坠
                        let mut setup = profile.run_setup(c, seed);
                        setup.god = god.0;
                        info!("出发，种子 {seed}（第一夜）");
                        depart(c, &profile, setup, &mut mode, &mut ui, &mut commands, &mut next);
                    }
                }
                // 灯驿在第一夜之后开放
                Some(1) if profile.basics => {
                    *mode = TitleMode::Hub;
                    open(&mut ui);
                }
                Some(2) => {
                    *mode = TitleMode::Settings;
                    open(&mut ui);
                }
                Some(3) => {
                    exit.write(AppExit::Success);
                }
                _ => {}
            }
        }
        TitleMode::Omen { seed, picks } => {
            let n = picks.len();
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h;
            }
            if actions.nav.x != 0 && n > 0 {
                ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(n as i32) as usize;
            }
            let chosen = actions
                .pick
                .map(usize::from)
                .filter(|&i| i < n)
                .or(clicked)
                .or(actions.confirm.then_some(ui.selected));
            if let Some(i) = chosen {
                let mut setup = profile.run_setup(c, seed);
                setup.god = god.0;
                setup.omen = picks.get(i).cloned();
                info!("出发，种子 {seed}，夜签 {:?}", setup.omen);
                depart(c, &profile, setup, &mut mode, &mut ui, &mut commands, &mut next);
            } else if actions.back {
                *mode = TitleMode::Prep;
                ui.selected = hub::prep_rows(c, &profile).len() - 1;
                ui.dirty = true;
            }
        }
        TitleMode::Scroll { setup, dawn } => {
            if clicked.is_some() || actions.confirm || actions.back {
                profile.saw_scroll(crate::scroll::REGION, dawn);
                save(&profile);
                commands.insert_resource(*setup);
                next.set(AppState::Run);
            }
        }
        TitleMode::Prep => match hub::prep_input(&actions, c, &mut profile, &mut ui, clicked) {
            hub::PrepAction::Go => {
                save(&profile);
                let seed = seed.0.unwrap_or_else(random_seed);
                *mode = TitleMode::Omen { seed, picks: draw_omens(c, seed, 3) };
                open(&mut ui);
            }
            hub::PrepAction::Back => {
                save(&profile);
                *mode = TitleMode::Main;
                open(&mut ui);
            }
            hub::PrepAction::None => {}
        },
        TitleMode::Hub => {
            let n = hub::HUB.len();
            if let Some(i) = list_nav(&mut ui, &actions, clicked, n, n) {
                *mode =
                    [TitleMode::Meta, TitleMode::Shop, TitleMode::Achievements, TitleMode::Codex][i].clone();
                // 进去过就算见过，下次不再说“第一次”那句
                if let Some(p) = c.hub.get(i)
                    && profile.met.insert(p.id.clone())
                {
                    save(&profile);
                }
                open(&mut ui);
            } else if actions.back || actions.meta {
                *mode = TitleMode::Main;
                ui.selected = 1;
                ui.dirty = true;
            }
        }
        TitleMode::Shop => {
            let n = c.attributes.list.len() + 1;
            if let Some(i) = list_nav(&mut ui, &actions, clicked, n, hub::SHOP_COLUMNS) {
                let changed = match c.attributes.list.get(i) {
                    Some(a) => {
                        let id = a.id.clone();
                        profile.buy_attribute(c, &id)
                    }
                    None => {
                        let back = profile.refund_attributes() > 0;
                        news.refunded |= back;
                        back
                    }
                };
                if changed {
                    save(&profile);
                }
                ui.dirty = true;
            } else if actions.back {
                back_to_hub(&mut mode, &mut ui, 1);
            }
        }
        TitleMode::Achievements | TitleMode::Codex => {
            if *mode == TitleMode::Codex {
                if actions.meta {
                    reader.open = true;
                    return;
                }
                // 图鉴翻页：左右键，或者点页签
                let pages = hub::CODEX_PAGES.len();
                let tab = clicked.and_then(|k| k.checked_sub(hub::CODEX_TAB)).filter(|&k| k < pages);
                if let Some(k) = tab {
                    ui.selected = k;
                    ui.dirty = true;
                    return;
                }
                if actions.nav.x != 0 {
                    ui.selected = (ui.selected as i32 + actions.nav.x).rem_euclid(pages as i32) as usize;
                    ui.dirty = true;
                    return;
                }
            }
            if actions.back || actions.confirm || clicked.is_some() {
                let i = if *mode == TitleMode::Codex { 3 } else { 2 };
                back_to_hub(&mut mode, &mut ui, i);
            }
        }
        TitleMode::Settings | TitleMode::AdvancedSettings => {
            let advanced = *mode == TitleMode::AdvancedSettings;
            let items: &[settings_ui::Item] = if advanced { &ADVANCED_ITEMS } else { &ITEMS };
            let n = items.len() + 1;
            if let Some(h) = ui.hovered.take()
                && actions.pointer_moved
            {
                ui.selected = h;
            }
            if actions.nav.y != 0 {
                ui.selected = (ui.selected as i32 + actions.nav.y).rem_euclid(n as i32) as usize;
            }
            if let Some(i) = clicked {
                ui.selected = i;
            }
            if actions.back {
                *mode = if advanced { TitleMode::Settings } else { TitleMode::Main };
                open(&mut ui);
                ui.selected = if advanced { ITEMS.len() } else { 2 };
            } else if ui.selected < items.len() {
                let mut a = *actions;
                a.confirm |= clicked.is_some();
                settings_ui::adjust(items[ui.selected], &a, &mut settings, &mut window, &mut controls);
            } else if actions.confirm || clicked.is_some() {
                if advanced {
                    bench::start(&mut commands, &mut next);
                } else {
                    *mode = TitleMode::AdvancedSettings;
                    open(&mut ui);
                }
            }
        }
        TitleMode::Meta => {
            let n = c.meta.nodes.len();
            if let Some(i) = list_nav(&mut ui, &actions, clicked, n, META_COLUMNS) {
                let id = c.meta.nodes[i].id.clone();
                let first = profile.meta.get(&id).copied().unwrap_or(0) == 0;
                if profile.buy_meta(c, &id) {
                    news.meta_lit = true;
                    if first {
                        news.lit.push(id);
                    }
                    save(&profile);
                }
                ui.dirty = true;
            } else if actions.back || actions.meta {
                back_to_hub(&mut mode, &mut ui, 0);
            }
        }
    }
    // 界面音按这一帧的意图出：返回、确认（换面板、点击、回车）、移动（换选项、调设置）。
    let adjusting = matches!(*mode, TitleMode::Settings | TitleMode::AdvancedSettings) && actions.nav.x != 0;
    if actions.back {
        cues.write(UiCue::Back);
    } else if *mode != previous || clicked.is_some() || actions.confirm {
        cues.write(UiCue::Confirm);
    } else if ui.selected != selected || adjusting {
        cues.write(UiCue::Move);
    }
    // 保留旧面板，等墨色盖满后再重画；同一面板内的数值刷新、灯驿长卷上的几个面板之间切换不转场。
    if *mode != previous && !(on_scroll(&mode) && on_scroll(&previous)) {
        transition.page(mode.clone(), ui.selected);
        *mode = previous;
        ui.selected = selected;
        ui.dirty = false;
    }
}

/// 出发：这个地区的开场卷轴还没展开过的，先展开，看完再进入这一局。
fn depart(
    c: &Content,
    profile: &Profile,
    setup: RunSetup,
    mode: &mut TitleMode,
    ui: &mut TitleUi,
    commands: &mut Commands,
    next: &mut NextState<AppState>,
) {
    match profile.next_scroll(c, crate::scroll::REGION) {
        Some(dawn) => {
            *mode = TitleMode::Scroll { setup: Box::new(setup), dawn };
            ui.selected = 0;
            ui.dirty = true;
        }
        None => {
            commands.insert_resource(setup);
            next.set(AppState::Run);
        }
    }
}

fn save(profile: &Profile) {
    if let Err(e) = profile.save() {
        warn!("保存存档失败：{e}");
    }
}

fn back_to_hub(mode: &mut TitleMode, ui: &mut TitleUi, i: usize) {
    *mode = TitleMode::Hub;
    ui.selected = i;
    ui.dirty = true;
}

/// 网格导航（cols 列）：悬停、方向键移动；返回这一帧选中的项（数字键、点击、Enter）。
fn list_nav(
    ui: &mut TitleUi,
    actions: &Actions,
    clicked: Option<usize>,
    n: usize,
    cols: usize,
) -> Option<usize> {
    if n == 0 {
        return None;
    }
    if ui.selected >= n {
        ui.selected = 0;
    }
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h.min(n - 1);
    }
    ui.selected = crate::navigation::grid(ui.selected, actions.nav, n, cols);
    let chosen = actions
        .pick
        .map(usize::from)
        .filter(|&i| i < n)
        .or(clicked)
        .or(actions.confirm.then_some(ui.selected));
    if let Some(i) = chosen {
        ui.selected = i;
    }
    chosen
}

/// 心灯面板的列数。
const META_COLUMNS: usize = 2;

/// 标题菜单：(文字, 快捷键)
const MENU: [(&str, &str); 4] = [("出发", "{confirm}"), ("灯驿", "{hub}"), ("设置", ""), ("退出", "{back}")];

pub(crate) fn panel() -> impl Bundle {
    (
        TitlePanel,
        crate::responsive::FitViewport::default(),
        DespawnOnExit(AppState::Title),
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
    )
}

/// 标题画：一直铺在标题界面的最底下，夜签和心灯面板盖在上面。按“铺满再居中裁边”缩放，不拉伸。
fn spawn_background(mut commands: Commands, skin: Res<Skin>) {
    commands.spawn((
        DespawnOnExit(AppState::Title),
        GlobalZIndex(-1),
        Node { position_type: PositionType::Absolute, ..default() },
        crate::cover::Cover(Vec2::new(1920.0, 1080.0)),
        ImageNode::new(skin.title.clone()).with_mode(NodeImageMode::Stretch),
        crate::title_fx::TitleBg,
        UiTransform::default(),
    ));
}

fn redraw(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    db: Res<AtlasDb>,
    mut profile: ResMut<Profile>,
    mut news: ResMut<HubNews>,
    settings: Res<Settings>,
    mode: Res<TitleMode>,
    art: Res<crate::scroll::ScrollArt>,
    window: Single<&Window, With<bevy::window::PrimaryWindow>>,
    scene: Option<Res<crate::hub_scene::HubScene>>,
    mut ui: ResMut<TitleUi>,
    panels: Query<Entity, With<TitlePanel>>,
) {
    if !ui.dirty {
        return;
    }
    ui.dirty = false;
    for e in &panels {
        commands.entity(e).despawn();
    }
    let c = &content.0;
    match &*mode {
        TitleMode::Main => main_panel(&mut commands, &fonts, &skin, &profile),
        TitleMode::Omen { picks, .. } => omen_panel(&mut commands, c, &fonts, &skin, &db, picks),
        TitleMode::Meta => meta_panel(&mut commands, c, &fonts, &skin, &db, &profile),
        TitleMode::Prep => hub::prep_panel(&mut commands, c, &fonts, &skin, &db, &profile),
        // 台词只确认选中的那位真正说出口的一句；存档有变才写盘，重画不重复写。
        TitleMode::Hub => match &scene {
            Some(scene) => {
                if crate::hub_scene::labels(
                    &mut commands,
                    scene,
                    c,
                    &fonts,
                    &mut profile,
                    &mut news,
                    ui.selected,
                    Vec2::new(window.width(), window.height()),
                ) {
                    save(&profile);
                }
            }
            None => {
                hub::hub_panel(&mut commands, c, &fonts, &skin, &db, &profile, &news);
                if profile.saw_hub(c, ui.selected, &mut news) {
                    save(&profile);
                }
            }
        },
        TitleMode::Shop => hub::shop_panel(&mut commands, c, &fonts, &skin, &profile),
        TitleMode::Achievements => hub::achievements_panel(&mut commands, c, &fonts, &skin, &profile),
        TitleMode::Codex => hub::codex_panel(&mut commands, c, &fonts, &skin, &db, &profile, ui.selected),
        TitleMode::Settings | TitleMode::AdvancedSettings => {
            settings_panel(&mut commands, &fonts, &skin, &settings, *mode == TitleMode::AdvancedSettings)
        }
        TitleMode::Scroll { dawn, .. } => {
            if let Some(region) = c.regions.iter().find(|r| r.id == crate::scroll::REGION) {
                let mut root = commands.spawn(panel());
                // 卷轴已经使用视口百分比和自适应字号，不再套固定画布。
                root.remove::<crate::responsive::FitViewport>();
                clickable(&mut root, 0);
                let root = root.id();
                crate::scroll::spawn(&mut commands, root, &art, &fonts, region, *dawn, window.width());
            }
        }
    }
}

/// 选中项的焦点标记。
#[derive(Component)]
pub(crate) struct FocusMark(usize);

fn highlight(ui: Res<TitleUi>, mut q: Query<(&FocusMark, &mut Visibility)>) {
    for (m, mut v) in &mut q {
        v.set_if_neq(if m.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
}

pub(crate) fn clickable(e: &mut EntityCommands, i: usize) {
    e.observe(move |_: On<PointerClick>, mut ui: ResMut<TitleUi>| ui.clicked = Some(i));
    e.observe(move |_: On<PointerOver>, mut ui: ResMut<TitleUi>| ui.hovered = Some(i));
}

/// 盖住父节点的焦点框（默认隐藏）。
pub(crate) fn focus(skin: &Skin, name: &str, i: usize, pad: f32) -> impl Bundle {
    (
        FocusMark(i),
        Visibility::Hidden,
        Node {
            position_type: PositionType::Absolute,
            left: px(-pad),
            right: px(-pad),
            top: px(-pad),
            bottom: px(-pad),
            ..default()
        },
        skin.image(name),
    )
}

fn main_panel(commands: &mut Commands, fonts: &Fonts, skin: &Skin, profile: &Profile) {
    let best = &profile.best;
    let record = if profile.runs == 0 {
        "第一次夜行".to_string()
    } else {
        let s = best.seconds as u32;
        format!(
            "最长 {:02}:{:02}　·　最多击杀 {}{}",
            s / 60,
            s % 60,
            best.kills,
            if best.won { "　·　已迎来天明" } else { "" }
        )
    };
    commands.spawn(panel()).with_children(|root| {
        root.spawn(Node {
            position_type: PositionType::Absolute,
            left: percent(7),
            top: percent(12),
            bottom: percent(8),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Start,
            row_gap: px(10),
            ..default()
        })
        .with_children(|p| {
            p.spawn((
                Node { width: px(520), height: px(172), ..default() },
                ImageNode::new(skin.logo.clone()),
                crate::title_fx::TitleLogo,
                UiTransform::default(),
            ));
            p.spawn(Node { height: px(36), ..default() });
            for (i, (label, key)) in MENU.iter().enumerate() {
                let mut item = p.spawn(Node {
                    width: px(300),
                    height: px(64),
                    align_items: AlignItems::Center,
                    padding: UiRect::left(px(36)),
                    column_gap: px(18),
                    ..default()
                });
                item.with_children(|it| {
                    it.spawn(focus(skin, "menu_hl", i, 0.0));
                    let locked = i == 1 && !profile.basics;
                    it.spawn(text(&fonts.title, 40.0, if locked { DIM } else { PAPER }, label));
                    it.spawn(crate::prompts::hint(
                        &fonts.body,
                        15.0,
                        DIM,
                        if locked { "第一夜之后开放" } else { key },
                    ));
                });
                clickable(&mut item, i);
            }
            p.spawn(Node { flex_grow: 1.0, ..default() });
            p.spawn(text(&fonts.body, 18.0, hex("#FFD98A"), &hub::purses(profile)));
            p.spawn(text(&fonts.body, 15.0, DIM, &record));
            p.spawn(crate::prompts::hint(
                &fonts.body,
                14.0,
                CINNABAR,
                concat!("桌面版 · 开发预览 v", env!("CARGO_PKG_VERSION"), "　　{fullscreen}"),
            ));
        });
    });
}

pub(crate) fn dim_layer() -> impl Bundle {
    (
        Node {
            position_type: PositionType::Absolute,
            width: percent(100),
            height: percent(100),
            ..default()
        },
        BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.6)),
    )
}

fn omen_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    db: &AtlasDb,
    picks: &[OmenPick],
) {
    commands.spawn(panel()).with_children(|p| {
        p.spawn(dim_layer());
        p.spawn(text(&fonts.title, 72.0, PAPER, "抽取夜签"));
        p.spawn(text(&fonts.body, 18.0, DIM, "本局规则三选一"));
        p.spawn(Node { column_gap: px(24), ..default() }).with_children(|row| {
            for (i, pick) in picks.iter().enumerate() {
                let Some(def) = c.omen_index(&pick.id).map(|k| &c.omens[k]) else { continue };
                let accent = pick.element.map_or(CINNABAR, |e| on_paper(element_color(c, e)));
                let mut card = row.spawn((
                    Node {
                        width: px(250),
                        min_height: px(320),
                        flex_direction: FlexDirection::Column,
                        align_items: AlignItems::Center,
                        padding: UiRect::axes(px(24), px(22)),
                        row_gap: px(12),
                        ..default()
                    },
                    skin.image("card_omen"),
                ));
                card.with_children(|card| {
                    card.spawn(focus(skin, "card_focus", i, 6.0));
                    card.spawn(text(&fonts.body, 14.0, INK_DIM, "夜签"));
                    let icon = format!("ui/icon_omen_{}", def.id);
                    let name = omen_name(c, pick);
                    spawn_icon(card, db, fonts, Some(&icon), &name, accent, 84.0);
                    card.spawn(text(&fonts.title, 48.0, accent, &name));
                    card.spawn(Node { flex_grow: 1.0, ..default() });
                    card.spawn((
                        text(&fonts.body, 16.0, hex("#2F6B45"), &format!("＋ {}", omen_good(c, pick))),
                        Node { max_width: px(200), ..default() },
                    ));
                    card.spawn((
                        text(&fonts.body, 16.0, hex("#9A3324"), &format!("－ {}", def.bad)),
                        Node { max_width: px(200), ..default() },
                    ));
                    card.spawn(crate::prompts::hint(
                        &fonts.title,
                        22.0,
                        INK_DIM,
                        &format!("{{pick{}}}", i + 1),
                    ));
                });
                clickable(&mut card, i);
            }
        });
        p.spawn(crate::prompts::hint(&fonts.body, 18.0, PAPER, "{nav} 选择　{confirm} 确定　{back} 返回"));
    });
}

pub(super) fn meta_panel(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    db: &AtlasDb,
    profile: &Profile,
) {
    let m = &c.meta;
    let mut root = commands.spawn(panel());
    root.insert(crate::responsive::FitViewport::for_meta(m.nodes.len()));
    root.with_children(|p| {
        p.spawn(dim_layer());
        p.spawn((
            Node {
                width: percent(crate::responsive::PANEL_WIDTH_PERCENT),
                max_width: px(1120),
                flex_shrink: 0.0,
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                padding: UiRect::axes(px(56), px(36)),
                row_gap: px(8),
                ..default()
            },
            skin.image("panel"),
        ))
        .with_children(|panel| {
            panel.spawn(text(&fonts.title, 56.0, INK, "心灯"));
            // 初程建议（meta.ron 的 intro）：只提示下一盏，不锁别的选择
            panel.spawn(text(
                &fonts.body,
                18.0,
                on_paper(hex("#FFD98A")),
                &match profile.next_meta_intro(c) {
                    Some(n) => format!("灯油 {}　·　初程下一盏：{}　·　也可自由点灯", profile.oil, n.name),
                    None => format!("灯油 {}", profile.oil),
                },
            ));
            panel.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
            let mut grid = panel.spawn(Node {
                width: percent(100),
                flex_wrap: FlexWrap::Wrap,
                row_gap: px(4),
                ..default()
            });
            grid.with_children(|g| {
                for (i, node) in m.nodes.iter().enumerate() {
                    let lv = profile.meta_level(&node.id);
                    let cost = profile.meta_cost(c, &node.id);
                    let can = cost.is_some_and(|x| profile.oil >= x);
                    let price = match cost {
                        None => "已满".to_string(),
                        Some(x) if can => format!("{x} 灯油"),
                        Some(x) => format!("{x} 灯油　差 {}", x - profile.oil),
                    };
                    let mut row = g.spawn(Node {
                        width: percent(100.0 / META_COLUMNS as f32),
                        min_width: px(0),
                        align_items: AlignItems::Center,
                        column_gap: px(12),
                        padding: UiRect::axes(px(12), px(6)),
                        ..default()
                    });
                    row.with_children(|r| {
                        r.spawn(focus(skin, "focus_ring", i, 2.0));
                        let icon = if lv > 0 {
                            format!("ui/icon_meta_{}", node.id)
                        } else {
                            format!("ui/icon_meta_{}_off", node.id)
                        };
                        spawn_icon(r, db, fonts, Some(&icon), &node.icon, INK, 44.0);
                        r.spawn(Node {
                            flex_direction: FlexDirection::Column,
                            flex_grow: 1.0,
                            flex_shrink: 1.0,
                            min_width: px(0),
                            row_gap: px(2),
                            ..default()
                        })
                        .with_children(|t| {
                            t.spawn(Node {
                                flex_wrap: FlexWrap::Wrap,
                                column_gap: px(8),
                                align_items: AlignItems::Center,
                                ..default()
                            })
                            .with_children(|h| {
                                h.spawn(text(&fonts.title, 26.0, INK, &node.name));
                                for k in 0..node.max_level {
                                    h.spawn((
                                        Node { width: px(14), height: px(14), ..default() },
                                        skin.image(if k < lv { "pip_on" } else { "pip" }),
                                    ));
                                }
                                h.spawn(text(
                                    &fonts.body,
                                    14.0,
                                    if can { on_paper(hex("#FFD98A")) } else { INK_DIM },
                                    &price,
                                ));
                            });
                            t.spawn(text(&fonts.body, 13.0, INK_DIM, &node.desc));
                        });
                    });
                    clickable(&mut row, i);
                }
            });
        });
        p.spawn(crate::prompts::hint(&fonts.body, 18.0, PAPER, "{nav} 选择　{confirm} 点亮　{back} 返回"));
    });
}

fn settings_panel(commands: &mut Commands, fonts: &Fonts, skin: &Skin, settings: &Settings, advanced: bool) {
    let items: &[settings_ui::Item] = if advanced { &ADVANCED_ITEMS } else { &ITEMS };
    commands.spawn(panel()).with_children(|p| {
        p.spawn(dim_layer());
        p.spawn((
            Node {
                width: px(580),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                padding: UiRect::axes(px(42), px(24)),
                row_gap: px(2),
                ..default()
            },
            skin.image("panel"),
        ))
        .with_children(|panel| {
            panel.spawn(text(&fonts.title, 64.0, INK, if advanced { "高级" } else { "设置" }));
            if advanced {
                panel.spawn(text(&fonts.body, 18.0, INK_DIM, "开发者工具"));
            }
            panel.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
            for (i, &item) in items.iter().enumerate() {
                let mut row = panel.spawn(Node {
                    width: percent(100),
                    padding: UiRect::axes(px(18), px(4)),
                    ..default()
                });
                row.with_children(|r| {
                    r.spawn(focus(skin, "focus_ring", i, 0.0));
                    settings_ui::spawn_row(r, fonts, settings, item);
                });
                clickable(&mut row, i);
            }
            let mut row =
                panel.spawn(Node { width: percent(100), padding: UiRect::axes(px(18), px(8)), ..default() });
            row.with_children(|r| {
                r.spawn(focus(skin, "focus_ring", items.len(), 0.0));
                r.spawn(text(&fonts.title, 30.0, INK, if advanced { "性能跑分" } else { "高级" }));
            });
            clickable(&mut row, items.len());
            if advanced {
                panel.spawn(text(&fonts.body, 16.0, INK_DIM, "开启性能调试后，按 F3 查看种子与性能数据。"));
                panel.spawn(text(&fonts.body, 16.0, INK_DIM, "开发模式始终支持 F3。"));
                panel.spawn(text(
                    &fonts.body,
                    16.0,
                    INK_DIM,
                    "开启开发者选项后，对局里按 F1 或在暂停菜单里点“开发者”。用过的局不计奖励。",
                ));
            }
        });
        p.spawn(crate::prompts::hint(
            &fonts.body,
            18.0,
            PAPER,
            "{nav} 选择 / 调整　{confirm} 设置　{back} 返回",
        ));
    });
}

#[cfg(test)]
mod input_tests {
    use super::*;

    fn app() -> App {
        let content =
            Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let mut app = App::new();
        app.insert_resource(GameContent(std::sync::Arc::new(content)))
            .init_resource::<Actions>()
            .init_resource::<SeedOverride>()
            .init_resource::<GodMode>()
            .init_resource::<Profile>()
            .init_resource::<HubNews>()
            .init_resource::<Settings>()
            .init_resource::<TitleMode>()
            .init_resource::<TitleUi>()
            .init_resource::<crate::controls::Controls>()
            .init_resource::<crate::transition::InkTransition>()
            .init_resource::<crate::journals::Reader>()
            .init_resource::<NextState<AppState>>()
            .add_message::<AppExit>()
            .add_message::<UiCue>()
            .add_systems(Update, input);
        app.world_mut().spawn((Window::default(), bevy::window::PrimaryWindow));
        app
    }

    fn cues(app: &App) -> Vec<UiCue> {
        app.world().resource::<Messages<UiCue>>().iter_current_update_messages().copied().collect()
    }

    #[test]
    fn god_mode_applies_to_first_night_and_omen_departures() {
        for god in [false, true] {
            for returning in [false, true] {
                let mut app = app();
                app.insert_resource(GodMode(god));
                app.insert_resource(SeedOverride(Some(42)));
                if returning {
                    let picks = draw_omens(&app.world().resource::<GameContent>().0, 42, 3);
                    app.insert_resource(TitleMode::Omen { seed: 42, picks });
                    let mut profile = app.world_mut().resource_mut::<Profile>();
                    profile.basics = true;
                    profile.saw_scroll(crate::scroll::REGION, false);
                }
                app.insert_resource(Actions { confirm: true, ..default() });
                app.update();
                if !returning {
                    // 首次出发经开场卷轴；跳过墨幕后确认，验证设置没有丢失。
                    app.world_mut().resource_scope(|world, mut t: Mut<crate::transition::InkTransition>| {
                        let mut mode = world.resource_mut::<TitleMode>();
                        let mut selected = 0;
                        t.skip(&mut mode, &mut selected);
                    });
                    assert!(matches!(*app.world().resource::<TitleMode>(), TitleMode::Scroll { .. }));
                    app.update();
                }
                let setup = app.world().resource::<RunSetup>();
                assert_eq!(setup.god, god);
                assert_eq!(setup.seed, 42);
                assert_eq!(setup.omen.is_some(), returning);
                assert!(matches!(
                    *app.world().resource::<NextState<AppState>>(),
                    NextState::Pending(AppState::Run)
                ));
            }
        }
    }

    #[test]
    fn title_skips_locked_hub_and_settings_opens_rebinding_with_focus_preserved() {
        let mut app = app();
        app.world_mut().resource_mut::<Actions>().nav = IVec2::Y;
        app.update();
        assert_eq!(app.world().resource::<TitleUi>().selected, 2);
        assert_eq!(cues(&app), [UiCue::Move]);
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        // 换面板要先拉墨幕；这里直接跳过。确认声在按下时就响。
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Main);
        assert_eq!(cues(&app), [UiCue::Confirm]);
        app.world_mut().resource_scope(|world, mut t: Mut<crate::transition::InkTransition>| {
            let mut mode = world.resource_mut::<TitleMode>();
            let mut m = mode.clone();
            let mut selected = 0;
            t.skip(&mut m, &mut selected);
            *mode = m;
            world.resource_mut::<TitleUi>().selected = selected;
        });
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Settings);
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::Y, ..default() };
        // 往下走到“键盘按键”（加了“伤害数字”以后是第 11 行）
        let keyboard = 1 + crate::settings_ui::ITEMS
            .iter()
            .position(|&i| i == crate::settings_ui::Item::Keyboard)
            .unwrap();
        for _ in 0..keyboard - 1 {
            app.update();
        }
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        assert!(app.world().resource::<crate::controls::Controls>().is_open());
        *app.world_mut().resource_mut::<Actions>() = Actions { back: true, nav: IVec2::Y, ..default() };
        app.update();
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Settings);
        assert_eq!(app.world().resource::<TitleUi>().selected, keyboard - 1);
    }

    #[test]
    fn hub_grid_moves_into_shop_and_back() {
        let mut app = app();
        *app.world_mut().resource_mut::<TitleMode>() = TitleMode::Hub;
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::X, confirm: true, ..default() };
        app.update();
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Shop);
        assert_eq!(app.world().resource::<TitleUi>().selected, 0);
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::Y, ..default() };
        app.update();
        assert_eq!(app.world().resource::<TitleUi>().selected, hub::SHOP_COLUMNS);
        *app.world_mut().resource_mut::<Actions>() = Actions { back: true, ..default() };
        app.update();
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Hub);
        assert_eq!(app.world().resource::<TitleUi>().selected, 1);
    }
}
