//! 暂停：继续、属性与构筑、设置项（四类音量、画面、按键）、回到标题。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_platform::{Actions, Settings, UiCue};
use lantern_sim::{AppState, RunState};

use crate::settings_ui::{self, ITEMS, PrimaryWindowQuery};
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, overlay_vignette, text};

mod inspection;

/// 菜单行：继续、属性与构筑、设置项、回到标题。
const ROWS: usize = ITEMS.len() + 3;

#[derive(Resource, Default)]
pub(crate) struct PauseUi {
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
}

#[derive(Component)]
pub(crate) struct PauseFocus(usize);

pub(crate) fn register(app: &mut App) {
    inspection::register(app);
    app.init_resource::<PauseUi>()
        .add_systems(OnEnter(RunState::Paused), spawn)
        .add_systems(Update, (input, highlight).chain().run_if(in_state(RunState::Paused)));
}

fn row_node() -> Node {
    Node {
        width: percent(100),
        padding: UiRect::axes(px(18), px(3)),
        justify_content: JustifyContent::Center,
        ..default()
    }
}

fn hook(e: &mut EntityCommands, i: usize) {
    e.observe(move |_: On<PointerClick>, mut ui: ResMut<PauseUi>| ui.clicked = Some(i));
    e.observe(move |_: On<PointerOver>, mut ui: ResMut<PauseUi>| ui.hovered = Some(i));
}

fn focus(skin: &Skin, i: usize) -> impl Bundle {
    (
        PauseFocus(i),
        Visibility::Hidden,
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            top: px(0),
            bottom: px(0),
            ..default()
        },
        skin.image("focus_ring"),
    )
}

fn spawn(
    mut commands: Commands,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    settings: Res<Settings>,
    mut ui: ResMut<PauseUi>,
    mut inspection: ResMut<inspection::Inspector>,
) {
    *ui = PauseUi::default();
    *inspection = inspection::Inspector::default();
    commands
        .spawn((
            DespawnOnExit(RunState::Paused),
            GlobalZIndex(30),
            crate::responsive::FitViewport::Fixed(Vec2::new(640.0, 780.0)),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                row_gap: px(14),
                ..default()
            },
            BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.8)),
        ))
        .with_children(|root| {
            root.spawn(overlay_vignette(&skin));
            root.spawn((
                Node {
                    width: px(580),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    padding: UiRect::axes(px(42), px(20)),
                    row_gap: px(2),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|p| {
                p.spawn(text(&fonts.title, 48.0, INK, "暂停"));
                p.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
                let mut resume = p.spawn(row_node());
                resume.with_children(|r| {
                    r.spawn(focus(&skin, 0));
                    r.spawn(text(&fonts.title, 28.0, INK, "继续"));
                });
                hook(&mut resume, 0);
                let mut inspect = p.spawn(row_node());
                inspect.with_children(|r| {
                    r.spawn(focus(&skin, 1));
                    r.spawn(text(&fonts.title, 28.0, INK, "属性与构筑"));
                });
                hook(&mut inspect, 1);
                for (k, &item) in ITEMS.iter().enumerate() {
                    let mut row = p.spawn(row_node());
                    row.with_children(|r| {
                        r.spawn(focus(&skin, k + 2));
                        settings_ui::spawn_row(r, &fonts, &settings, item);
                    });
                    hook(&mut row, k + 2);
                }
                let mut quit = p.spawn(row_node());
                quit.with_children(|r| {
                    r.spawn(focus(&skin, ROWS - 1));
                    r.spawn(text(&fonts.title, 28.0, INK, "回到标题"));
                });
                hook(&mut quit, ROWS - 1);
                p.spawn(Node { height: px(8), ..default() });
                p.spawn(text(&fonts.body, 14.0, INK_DIM, "回到标题时，这一局不计灯油"));
                p.spawn(crate::prompts::hint(
                    &fonts.body,
                    14.0,
                    INK_DIM,
                    "{nav} 选择 / 调整　{confirm} 确定　{back} 继续",
                ));
            });
        });
}

pub(crate) fn input(
    actions: Res<Actions>,
    transition: Res<crate::transition::InkTransition>,
    mut ui: ResMut<PauseUi>,
    mut inspection: ResMut<inspection::Inspector>,
    mut settings: ResMut<Settings>,
    mut controls: ResMut<crate::controls::Controls>,
    mut window: PrimaryWindowQuery,
    mut next_run: ResMut<NextState<RunState>>,
    mut next_app: ResMut<NextState<AppState>>,
    mut cues: MessageWriter<UiCue>,
) {
    if controls.is_open() || transition.active() {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
    // 查询面板独占本帧输入；返回只收起查询，不同时恢复游戏或调整设置。
    if inspection.is_open() {
        ui.clicked = None;
        ui.hovered = None;
        if actions.quit_to_title {
            next_app.set(AppState::Title);
            cues.write(UiCue::Back);
        } else {
            inspection.input(&actions, &mut cues);
        }
        return;
    }
    let before_selected = ui.selected;
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h;
    }
    if actions.nav.y != 0 {
        ui.selected = (ui.selected as i32 + actions.nav.y).rem_euclid(ROWS as i32) as usize;
    }
    let clicked = ui.clicked.take();
    if let Some(c) = clicked {
        ui.selected = c;
    }
    let sel = ui.selected;
    if actions.quit_to_title || ((actions.confirm || clicked.is_some()) && sel == ROWS - 1) {
        next_app.set(AppState::Title);
    } else if actions.pause || actions.back || ((actions.confirm || clicked.is_some()) && sel == 0) {
        next_run.set(RunState::Playing);
    } else if sel == 1 && (actions.confirm || clicked.is_some()) {
        inspection.open();
    } else if (2..=ITEMS.len() + 1).contains(&sel) {
        let mut a = *actions;
        // 点击设置项等同回车（全屏切换），音量用左右键
        a.confirm |= clicked.is_some();
        settings_ui::adjust(ITEMS[sel - 2], &a, &mut settings, &mut window, &mut controls);
    }
    if actions.pause || actions.back || actions.quit_to_title {
        cues.write(UiCue::Back);
    } else if actions.confirm || clicked.is_some() {
        cues.write(UiCue::Confirm);
    } else if before_selected != ui.selected || actions.nav.x != 0 {
        cues.write(UiCue::Move);
    }
}

fn highlight(ui: Res<PauseUi>, mut q: Query<(&PauseFocus, &mut Visibility)>) {
    for (f, mut v) in &mut q {
        v.set_if_neq(if f.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input_app() -> App {
        let mut app = App::new();
        app.init_resource::<Actions>()
            .init_resource::<PauseUi>()
            .init_resource::<inspection::Inspector>()
            .init_resource::<Settings>()
            .init_resource::<crate::controls::Controls>()
            .init_resource::<crate::transition::InkTransition>()
            .init_resource::<NextState<RunState>>()
            .init_resource::<NextState<AppState>>()
            .add_message::<UiCue>()
            .add_systems(Update, input);
        app.world_mut().spawn((Window::default(), bevy::window::PrimaryWindow));
        app
    }

    #[test]
    fn pause_navigates_settings_and_modal_blocks_resume() {
        let mut app = input_app();
        app.world_mut().resource_mut::<Actions>().nav = IVec2::Y;
        for _ in 0..ITEMS.len() + 1 {
            app.update();
        }
        // 最后一项是手柄按键
        assert_eq!(app.world().resource::<PauseUi>().selected, ITEMS.len() + 1);
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        assert!(app.world().resource::<crate::controls::Controls>().is_open());
        *app.world_mut().resource_mut::<Actions>() = Actions { pause: true, back: true, ..default() };
        app.update();
        assert!(matches!(app.world().resource::<NextState<RunState>>(), NextState::Unchanged));
    }

    #[test]
    fn inspection_back_consumes_input_before_resume_and_settings() {
        let mut app = input_app();
        app.world_mut().resource_mut::<PauseUi>().clicked = Some(1);
        app.update();
        assert!(app.world().resource::<inspection::Inspector>().is_open());
        let music = app.world().resource::<Settings>().music_volume;
        // 即使底层留下设置行点击，也不能穿透查询面板。
        app.world_mut().resource_mut::<PauseUi>().clicked = Some(2);
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::X, ..default() };
        app.update();
        assert_eq!(app.world().resource::<Settings>().music_volume, music);
        *app.world_mut().resource_mut::<Actions>() = Actions { pause: true, back: true, ..default() };
        app.update();
        assert!(!app.world().resource::<inspection::Inspector>().is_open());
        assert!(matches!(app.world().resource::<NextState<RunState>>(), NextState::Unchanged));
        app.update();
        assert!(matches!(
            app.world().resource::<NextState<RunState>>(),
            NextState::Pending(RunState::Playing)
        ));
    }
}
