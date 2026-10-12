//! 标题界面：出发前抽夜签三选一、心灯（局外成长）、跑分（移植自网页版 lantern/game.js）。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::{Actions, Profile};
use lantern_sim::omens::{draw_omens, omen_good};
use lantern_sim::{AppState, GameContent, OmenPick, RunMode, RunSetup};

use crate::describe::{element_color, hex};
use crate::{CINNABAR, DIM, Fonts, PAPER, SeedOverride, bench, text};

/// 标题界面上打开的面板。
#[derive(Resource, Default, Clone, Debug, PartialEq)]
pub(crate) enum TitleMode {
    #[default]
    Main,
    /// 夜签三选一：这一局的种子和抽到的夜签
    Omen { seed: u64, picks: Vec<OmenPick> },
    /// 心灯
    Meta,
}

#[derive(Resource, Default)]
pub(crate) struct TitleUi {
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
    /// 面板变了，需要重画
    dirty: bool,
}

#[derive(Component)]
pub(crate) struct TitlePanel;

#[derive(Component)]
pub(crate) struct Choice(usize);

pub(crate) fn register(app: &mut App) {
    app.init_resource::<TitleMode>()
        .init_resource::<TitleUi>()
        .add_systems(OnEnter(AppState::Title), enter)
        .add_systems(Update, (input, redraw, highlight).chain().run_if(in_state(AppState::Title)));
}

fn enter(mut mode: ResMut<TitleMode>, mut ui: ResMut<TitleUi>) {
    *mode = TitleMode::Main;
    *ui = TitleUi { dirty: true, ..default() };
}

/// 只用于挑选新一局的种子，不参与模拟。
fn random_seed() -> u64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    nanos % 1_000_000_000
}

fn input(
    actions: Res<Actions>,
    content: Res<GameContent>,
    seed: Res<SeedOverride>,
    mut profile: ResMut<Profile>,
    mut mode: ResMut<TitleMode>,
    mut ui: ResMut<TitleUi>,
    mut commands: Commands,
    mut next: ResMut<NextState<AppState>>,
    mut exit: MessageWriter<AppExit>,
) {
    let c = &content.0;
    let clicked = ui.clicked.take();
    let open = |ui: &mut TitleUi| {
        ui.selected = 0;
        ui.dirty = true;
    };
    match mode.clone() {
        TitleMode::Main => {
            if actions.confirm || clicked.is_some() {
                let seed = seed.0.unwrap_or_else(random_seed);
                *mode = TitleMode::Omen { seed, picks: draw_omens(c, seed, 3) };
                open(&mut ui);
            } else if actions.meta {
                *mode = TitleMode::Meta;
                open(&mut ui);
            } else if actions.bench {
                bench::start(&mut commands, &mut next);
            } else if actions.back {
                exit.write(AppExit::Success);
            }
        }
        TitleMode::Omen { seed, picks } => {
            let n = picks.len();
            if let Some(h) = ui.hovered.take() {
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
                let mut setup = RunSetup::new(seed, RunMode::Normal);
                setup.omen = picks.get(i).cloned();
                setup.meta = profile.meta.clone();
                info!("出发，种子 {seed}，夜签 {:?}", setup.omen);
                commands.insert_resource(setup);
                next.set(AppState::Run);
            } else if actions.back {
                *mode = TitleMode::Main;
                open(&mut ui);
            }
        }
        TitleMode::Meta => {
            let n = c.meta.lines.len();
            if let Some(h) = ui.hovered.take() {
                ui.selected = h;
            }
            if actions.nav.y != 0 && n > 0 {
                ui.selected = (ui.selected as i32 + actions.nav.y).rem_euclid(n as i32) as usize;
            }
            let chosen = actions
                .pick
                .map(usize::from)
                .filter(|&i| i < n)
                .or(clicked)
                .or(actions.confirm.then_some(ui.selected));
            if let Some(i) = chosen {
                ui.selected = i;
                let line = &c.meta.lines[i];
                let cost = c.meta.cost(profile.meta_level(&line.id));
                if profile.buy_meta(&line.id, cost, c.meta.max_level)
                    && let Err(e) = profile.save()
                {
                    warn!("保存存档失败：{e}");
                }
                ui.dirty = true;
            } else if actions.back || actions.meta {
                *mode = TitleMode::Main;
                open(&mut ui);
            }
        }
    }
}

fn panel() -> impl Bundle {
    (
        TitlePanel,
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

fn redraw(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    profile: Res<Profile>,
    mode: Res<TitleMode>,
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
        TitleMode::Main => main_panel(&mut commands, &fonts, &profile),
        TitleMode::Omen { seed, picks } => omen_panel(&mut commands, c, &fonts, *seed, picks),
        TitleMode::Meta => meta_panel(&mut commands, c, &fonts, &profile),
    }
}

fn highlight(ui: Res<TitleUi>, mut q: Query<(&Choice, &mut BorderColor, &mut BackgroundColor)>) {
    for (choice, mut border, mut bg) in &mut q {
        let on = choice.0 == ui.selected;
        let mut b = border.top;
        b.set_alpha(if on { 1.0 } else { 0.35 });
        *border = BorderColor::all(b);
        bg.0 = if on { Color::srgba(0.12, 0.13, 0.19, 0.95) } else { Color::srgba(0.07, 0.08, 0.12, 0.85) };
    }
}

fn clickable(e: &mut EntityCommands, i: usize) {
    e.observe(move |_: On<PointerClick>, mut ui: ResMut<TitleUi>| ui.clicked = Some(i));
    e.observe(move |_: On<PointerOver>, mut ui: ResMut<TitleUi>| ui.hovered = Some(i));
}

fn main_panel(commands: &mut Commands, fonts: &Fonts, profile: &Profile) {
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
    let mut root = commands.spawn(panel());
    root.with_children(|p| {
        p.spawn(text(&fonts.title, 128.0, PAPER, "提灯夜行"));
        p.spawn(text(&fonts.body, 22.0, CINNABAR, concat!("桌面版 · 开发预览 v", env!("CARGO_PKG_VERSION"))));
        p.spawn(text(&fonts.body, 18.0, DIM, &format!("灯油 {}　·　{record}", profile.oil)));
        p.spawn(Node { height: px(36), ..default() });
        p.spawn(text(&fonts.body, 24.0, PAPER, "Enter / 手柄 A　出发"));
        p.spawn(text(&fonts.body, 18.0, DIM, "M / 手柄 X　心灯　　B　跑分　　F11　全屏　　Esc　退出"));
    });
}

fn omen_panel(commands: &mut Commands, c: &Content, fonts: &Fonts, seed: u64, picks: &[OmenPick]) {
    commands.spawn(panel()).with_children(|p| {
        p.spawn(text(&fonts.title, 72.0, PAPER, "抽取夜签"));
        p.spawn(text(&fonts.body, 18.0, DIM, &format!("本局规则三选一　·　种子 {seed}")));
        p.spawn(Node { column_gap: px(20), ..default() }).with_children(|row| {
            for (i, pick) in picks.iter().enumerate() {
                let Some(def) = c.omen_index(&pick.id).map(|k| &c.omens[k]) else { continue };
                let color = pick.element.map_or(hex("#FFD98A"), |e| element_color(c, e));
                let mut card = row.spawn((
                    Choice(i),
                    Node {
                        width: px(240),
                        min_height: px(250),
                        flex_direction: FlexDirection::Column,
                        align_items: AlignItems::Center,
                        padding: UiRect::all(px(18)),
                        row_gap: px(12),
                        border: UiRect::all(px(2)),
                        border_radius: BorderRadius::all(px(10)),
                        ..default()
                    },
                    BorderColor::all(color),
                    BackgroundColor(Color::srgba(0.07, 0.08, 0.12, 0.85)),
                ));
                card.with_children(|card| {
                    card.spawn(text(&fonts.body, 14.0, DIM, "夜签"));
                    card.spawn(text(&fonts.title, 52.0, color, &def.name));
                    card.spawn(Node { flex_grow: 1.0, ..default() });
                    card.spawn(text(
                        &fonts.body,
                        17.0,
                        hex("#8FE3B0"),
                        &format!("＋ {}", omen_good(c, pick)),
                    ));
                    card.spawn(text(&fonts.body, 17.0, hex("#FF8A7A"), &format!("－ {}", def.bad)));
                    card.spawn(text(&fonts.body, 14.0, DIM, &format!("{}", i + 1)));
                });
                clickable(&mut card, i);
            }
        });
        p.spawn(text(&fonts.body, 18.0, PAPER, "1-3 / ← → + Enter　选择　　Esc　返回"));
    });
}

fn meta_panel(commands: &mut Commands, c: &Content, fonts: &Fonts, profile: &Profile) {
    let m = &c.meta;
    commands.spawn(panel()).with_children(|p| {
        p.spawn(text(&fonts.title, 72.0, PAPER, "心灯"));
        p.spawn(text(&fonts.body, 20.0, hex("#FFD98A"), &format!("灯油 {}", profile.oil)));
        p.spawn(Node { flex_direction: FlexDirection::Column, row_gap: px(10), ..default() }).with_children(
            |list| {
                for (i, line) in m.lines.iter().enumerate() {
                    let lv = profile.meta_level(&line.id);
                    let maxed = lv >= m.max_level;
                    let cost = m.cost(lv);
                    let can = !maxed && profile.oil >= cost;
                    let pips: String = (0..m.max_level).map(|k| if k < lv { '●' } else { '○' }).collect();
                    let price = if maxed {
                        "已满".to_string()
                    } else if can {
                        format!("{cost} 灯油　可点亮")
                    } else {
                        format!("{cost} 灯油　还差 {}", cost - profile.oil)
                    };
                    let mut row = list.spawn((
                        Choice(i),
                        Node {
                            width: px(560),
                            align_items: AlignItems::Center,
                            column_gap: px(16),
                            padding: UiRect::axes(px(16), px(10)),
                            border: UiRect::all(px(2)),
                            border_radius: BorderRadius::all(px(8)),
                            ..default()
                        },
                        BorderColor::all(if can { hex("#FFD98A") } else { DIM }),
                        BackgroundColor(Color::srgba(0.07, 0.08, 0.12, 0.85)),
                    ));
                    row.with_children(|r| {
                        r.spawn(text(
                            &fonts.title,
                            44.0,
                            if lv > 0 { hex("#FFD98A") } else { DIM },
                            &line.icon,
                        ));
                        r.spawn(Node { flex_direction: FlexDirection::Column, flex_grow: 1.0, ..default() })
                            .with_children(|t| {
                                t.spawn(Node {
                                    column_gap: px(12),
                                    align_items: AlignItems::Center,
                                    ..default()
                                })
                                .with_children(|h| {
                                    h.spawn(text(&fonts.title, 28.0, PAPER, &line.name));
                                    h.spawn(text(&fonts.body, 18.0, hex("#FFD98A"), &pips));
                                });
                                t.spawn(text(&fonts.body, 15.0, DIM, &line.desc));
                            });
                        r.spawn(text(&fonts.body, 15.0, if can { hex("#FFD98A") } else { DIM }, &price));
                    });
                    clickable(&mut row, i);
                }
            },
        );
        p.spawn(text(&fonts.body, 18.0, PAPER, "↑ ↓ 选择　Enter　点亮　　Esc　返回"));
    });
}
