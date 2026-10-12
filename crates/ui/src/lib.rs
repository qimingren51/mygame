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
mod pause;
mod perf;
mod replay_ui;
mod results;
mod settings_ui;
mod skin;
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
/// 纸面上的墨色：正文、次要文字
pub(crate) const INK: Color = Color::srgb(0.090, 0.078, 0.059);
pub(crate) const INK_DIM: Color = Color::srgb(0.31, 0.286, 0.259);

/// 夜里看着顺眼的淡彩，写在纸上太浅：压暗一些。
pub(crate) fn on_paper(c: Color) -> Color {
    let l = c.to_linear();
    Color::linear_rgb(l.red * 0.32, l.green * 0.32, l.blue * 0.32)
}

/// 全屏压暗的墨云（叠在半透明夜色上）。
pub(crate) fn overlay_vignette(skin: &skin::Skin) -> impl Bundle {
    (
        Node {
            position_type: PositionType::Absolute,
            width: percent(100),
            height: percent(100),
            ..default()
        },
        skin.image("overlay_vignette"),
    )
}

pub struct UiPlugin;

impl Plugin for UiPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<SeedOverride>()
            .add_systems(Startup, (load_fonts, skin::load_skin))
            .add_systems(OnEnter(AppState::Run), hud::spawn_hud)
            .add_systems(OnExit(AppState::Run), bench::cleanup)
            .add_systems(
                Update,
                (
                    playing_input.run_if(in_state(RunState::Playing)),
                    settings_ui::refresh_values,
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
        pause::register(app);
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
