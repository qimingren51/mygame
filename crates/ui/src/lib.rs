//! 界面层（docs/DESIGN.md 第 11 节）。读模拟状态、发命令和切换状态，不直接改模拟数据。
//!
//! 界面里出现的汉字会被 `crates/ui/fonts.py` 扫描出来，用于裁剪字体子集。
//! 新增文字后要重新运行这个脚本，否则新字会显示成方框。M2 起文字统一放到 `assets/i18n/`。

use bevy::prelude::*;

use lantern_core::step::TICK_HZ;
use lantern_platform::Actions;
use lantern_sim::{AppState, Progress, RunMode, RunSetup, RunState, Tick};

mod bench;
mod hud;
mod perf;
mod replay_ui;

pub use perf::SimTiming;

/// 命令行指定的种子（`--seed`）。没有指定时每局随机。
#[derive(Resource, Default, Clone, Copy, Debug)]
pub struct SeedOverride(pub Option<u64>);

#[derive(Resource)]
pub(crate) struct Fonts {
    title: Handle<Font>,
    body: Handle<Font>,
}

pub(crate) const PAPER: Color = Color::srgb(0.914, 0.875, 0.78);
pub(crate) const DIM: Color = Color::srgba(0.914, 0.875, 0.78, 0.6);
pub(crate) const CINNABAR: Color = Color::srgb(0.80, 0.25, 0.18);

pub struct UiPlugin;

impl Plugin for UiPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<SeedOverride>()
            .add_systems(Startup, load_fonts)
            .add_systems(OnEnter(AppState::Title), spawn_title)
            .add_systems(OnEnter(AppState::Run), hud::spawn_hud)
            .add_systems(OnExit(AppState::Run), bench::cleanup)
            .add_systems(OnEnter(RunState::Paused), spawn_pause)
            .add_systems(OnEnter(RunState::Over), spawn_over)
            .add_systems(
                Update,
                (
                    title_input.run_if(in_state(AppState::Title)),
                    playing_input.run_if(in_state(RunState::Playing)),
                    paused_input.run_if(in_state(RunState::Paused)),
                    over_input.run_if(in_state(RunState::Over)),
                    hud::update_hud.run_if(in_state(AppState::Run)),
                    (bench::drive, bench::finish_input)
                        .chain()
                        .run_if(in_state(RunState::Playing))
                        .run_if(resource_exists::<bench::BenchRun>),
                ),
            );
        perf::register(app);
        replay_ui::register(app);
    }
}

fn load_fonts(mut commands: Commands, assets: Res<AssetServer>, mut next: ResMut<NextState<AppState>>) {
    commands.insert_resource(Fonts {
        title: assets.load("fonts/MaShanZheng-subset.ttf"),
        body: assets.load("fonts/NotoSerifSC-subset.ttf"),
    });
    // M0 没有需要等待的加载，直接进入标题。
    next.set(AppState::Title);
}

pub(crate) fn text(font: &Handle<Font>, size: f32, color: Color, s: &str) -> impl Bundle {
    (Text::new(s), TextFont::from(font.clone()).with_font_size(size), TextColor(color))
}

fn spawn_title(mut commands: Commands, fonts: Res<Fonts>) {
    commands.spawn((
        DespawnOnExit(AppState::Title),
        Node {
            width: percent(100),
            height: percent(100),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: px(18),
            ..default()
        },
        children![
            text(&fonts.title, 128.0, PAPER, "提灯夜行"),
            text(&fonts.body, 22.0, CINNABAR, concat!("桌面版 · 开发预览 v", env!("CARGO_PKG_VERSION"))),
            (Node { height: px(48), ..default() }),
            text(&fonts.body, 24.0, PAPER, "Enter / 手柄 A　出发"),
            text(&fonts.body, 18.0, DIM, "B　跑分　　F11　全屏　　Esc　退出"),
        ],
    ));
}

fn title_input(
    actions: Res<Actions>,
    seed: Res<SeedOverride>,
    mut commands: Commands,
    mut next: ResMut<NextState<AppState>>,
    mut exit: MessageWriter<AppExit>,
) {
    if actions.confirm {
        let seed = seed.0.unwrap_or_else(random_seed);
        info!("出发，种子 {seed}");
        commands.insert_resource(RunSetup { seed, mode: RunMode::Normal });
        next.set(AppState::Run);
    } else if actions.bench {
        bench::start(&mut commands, &mut next);
    } else if actions.back {
        exit.write(AppExit::Success);
    }
}

/// 只用于挑选新一局的种子，不参与模拟。
fn random_seed() -> u64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    nanos % 1_000_000_000
}

fn playing_input(actions: Res<Actions>, mut next: ResMut<NextState<RunState>>) {
    if actions.pause {
        next.set(RunState::Paused);
    }
}

fn spawn_pause(mut commands: Commands, fonts: Res<Fonts>) {
    commands.spawn((
        DespawnOnExit(RunState::Paused),
        Node {
            width: percent(100),
            height: percent(100),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: px(16),
            ..default()
        },
        BackgroundColor(Color::srgba(0.05, 0.06, 0.1, 0.7)),
        children![
            text(&fonts.title, 72.0, PAPER, "暂停"),
            text(&fonts.body, 22.0, PAPER, "Enter / Esc　继续　　Q / 手柄 Select　回到标题"),
        ],
    ));
}

fn paused_input(
    actions: Res<Actions>,
    mut next_run: ResMut<NextState<RunState>>,
    mut next_app: ResMut<NextState<AppState>>,
) {
    if actions.quit_to_title {
        next_app.set(AppState::Title);
    } else if actions.confirm || actions.pause || actions.back {
        next_run.set(RunState::Playing);
    }
}

/// 主角倒下。M1-5 换成完整的结算界面。
fn spawn_over(mut commands: Commands, fonts: Res<Fonts>, progress: Res<Progress>, tick: Res<Tick>) {
    let secs = tick.0 / u64::from(TICK_HZ);
    commands.spawn((
        DespawnOnExit(RunState::Over),
        Node {
            width: percent(100),
            height: percent(100),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: px(16),
            ..default()
        },
        BackgroundColor(Color::srgba(0.05, 0.06, 0.1, 0.75)),
        children![
            text(&fonts.title, 72.0, PAPER, "灯灭"),
            text(
                &fonts.body,
                22.0,
                PAPER,
                &format!(
                    "坚持 {:02}:{:02}　　击杀 {}　　等级 {}",
                    secs / 60,
                    secs % 60,
                    progress.kills,
                    progress.level
                )
            ),
            text(&fonts.body, 20.0, DIM, "Enter / 手柄 A　回到标题"),
        ],
    ));
}

fn over_input(actions: Res<Actions>, mut next_app: ResMut<NextState<AppState>>) {
    if actions.confirm || actions.back {
        next_app.set(AppState::Title);
    }
}
