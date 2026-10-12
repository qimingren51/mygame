//! 界面层（docs/DESIGN.md 第 11 节）。读模拟状态、发命令和切换状态，不直接改模拟数据。
//!
//! 界面里出现的汉字会被 `crates/ui/fonts.py` 扫描出来，用于裁剪字体子集。
//! 新增文字后要重新运行这个脚本，否则新字会显示成方框。M2 起文字统一放到 `assets/i18n/`。

use bevy::prelude::*;

use lantern_platform::Actions;
use lantern_sim::{AppState, RunState};

mod bench;
mod choice;
mod describe;
mod hud;
mod perf;
mod replay_ui;
mod results;
mod title;
mod toasts;

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
            .add_systems(OnEnter(AppState::Run), hud::spawn_hud)
            .add_systems(OnExit(AppState::Run), bench::cleanup)
            .add_systems(OnEnter(RunState::Paused), spawn_pause)
            .add_systems(
                Update,
                (
                    playing_input.run_if(in_state(RunState::Playing)),
                    paused_input.run_if(in_state(RunState::Paused)),
                    (hud::update_hud, hud::update_slots, hud::update_chips).run_if(in_state(AppState::Run)),
                    (bench::drive, bench::finish_input)
                        .chain()
                        .run_if(in_state(RunState::Playing))
                        .run_if(resource_exists::<bench::BenchRun>),
                ),
            );
        perf::register(app);
        replay_ui::register(app);
        title::register(app);
        choice::register(app);
        toasts::register(app);
        results::register(app);
    }
}

fn load_fonts(mut commands: Commands, assets: Res<AssetServer>, mut next: ResMut<NextState<AppState>>) {
    let title: Handle<Font> = assets.load("fonts/MaShanZheng-subset.ttf");
    let _ = TITLE_FONT.set(title.id());
    commands.insert_resource(Fonts { title, body: assets.load("fonts/NotoSerifSC-subset.ttf") });
    // 没有需要等待的加载，直接进入标题。
    next.set(AppState::Title);
}

/// 标题字体（马善政毛笔楷书）的资源 ID。这套字体没有间隔号“·”，用它写的字把“·”换成“•”。
static TITLE_FONT: std::sync::OnceLock<AssetId<Font>> = std::sync::OnceLock::new();

pub(crate) fn text(font: &Handle<Font>, size: f32, color: Color, s: &str) -> impl Bundle {
    let s = if TITLE_FONT.get() == Some(&font.id()) { s.replace('·', "•") } else { s.to_string() };
    (Text::new(s), TextFont::from(font.clone()).with_font_size(size), TextColor(color))
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
