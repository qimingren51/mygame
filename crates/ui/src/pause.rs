//! 暂停：继续、音乐与音效音量、全屏、回到标题。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_platform::{Actions, Settings};
use lantern_sim::{AppState, RunState};

use crate::settings_ui::{self, ITEMS, PrimaryWindowQuery};
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, overlay_vignette, text};

/// 菜单行：继续、设置项、回到标题。
const ROWS: usize = ITEMS.len() + 2;

#[derive(Resource, Default)]
pub(crate) struct PauseUi {
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
}

#[derive(Component)]
pub(crate) struct PauseFocus(usize);

pub(crate) fn register(app: &mut App) {
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
) {
    *ui = PauseUi::default();
    commands
        .spawn((
            DespawnOnExit(RunState::Paused),
            GlobalZIndex(30),
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
                for (k, &item) in ITEMS.iter().enumerate() {
                    let mut row = p.spawn(row_node());
                    row.with_children(|r| {
                        r.spawn(focus(&skin, k + 1));
                        settings_ui::spawn_row(r, &fonts, &settings, item);
                    });
                    hook(&mut row, k + 1);
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
    mut ui: ResMut<PauseUi>,
    mut settings: ResMut<Settings>,
    mut controls: ResMut<crate::controls::Controls>,
    mut window: PrimaryWindowQuery,
    mut next_run: ResMut<NextState<RunState>>,
    mut next_app: ResMut<NextState<AppState>>,
) {
    if controls.is_open() {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
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
    } else if (1..=ITEMS.len()).contains(&sel) {
        let mut a = *actions;
        // 点击设置项等同回车（全屏切换），音量用左右键
        a.confirm |= clicked.is_some();
        settings_ui::adjust(ITEMS[sel - 1], &a, &mut settings, &mut window, &mut controls);
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

    #[test]
    fn pause_navigates_settings_and_modal_blocks_resume() {
        let mut app = App::new();
        app.init_resource::<Actions>()
            .init_resource::<PauseUi>()
            .init_resource::<Settings>()
            .init_resource::<crate::controls::Controls>()
            .init_resource::<NextState<RunState>>()
            .init_resource::<NextState<AppState>>()
            .add_systems(Update, input);
        app.world_mut().spawn((Window::default(), bevy::window::PrimaryWindow));
        app.world_mut().resource_mut::<Actions>().nav = IVec2::Y;
        for _ in 0..9 {
            app.update();
        }
        assert_eq!(app.world().resource::<PauseUi>().selected, 9);
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        assert!(app.world().resource::<crate::controls::Controls>().is_open());
        *app.world_mut().resource_mut::<Actions>() = Actions { pause: true, back: true, ..default() };
        app.update();
        assert!(matches!(app.world().resource::<NextState<RunState>>(), NextState::Unchanged));
    }
}
