//! 暂停：继续、属性（`stats_panel.rs`）、开发者（`dev_panel.rs`，设置里打开了才有）、设置项（四类音量、画面、按键）、回到标题。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_platform::{Actions, Settings, UiCue};
use lantern_sim::{AppState, RunState};

use crate::settings_ui::{self, ITEMS, PrimaryWindowQuery};
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, overlay_vignette, text};

/// 菜单行：继续、属性、（开发者）、设置项、回到标题。开发者那一行只在设置里打开了开发者选项时有。
#[derive(Clone, Copy)]
struct Rows {
    dev: Option<usize>,
    /// 第一个设置项的行号
    first_item: usize,
    count: usize,
}

fn rows(settings: &Settings) -> Rows {
    let first_item = 2 + usize::from(settings.dev_tools);
    Rows { dev: settings.dev_tools.then_some(2), first_item, count: first_item + ITEMS.len() + 1 }
}

#[derive(Resource, Default)]
pub(crate) struct PauseUi {
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
}

#[derive(Component)]
pub(crate) struct PauseFocus(usize);

/// 暂停菜单的根节点；属性面板打开时藏起来。
#[derive(Component)]
struct PauseRoot;

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
    let lay = rows(&settings);
    commands
        .spawn((
            PauseRoot,
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
                let mut stats = p.spawn(row_node());
                stats.with_children(|r| {
                    r.spawn(focus(&skin, 1));
                    r.spawn(text(&fonts.title, 28.0, INK, "属性"));
                    r.spawn((
                        text(&fonts.body, 14.0, INK_DIM, "Tab"),
                        Node {
                            position_type: PositionType::Absolute,
                            right: px(18),
                            top: px(12),
                            ..default()
                        },
                    ));
                });
                hook(&mut stats, 1);
                if let Some(i) = lay.dev {
                    let mut dev = p.spawn(row_node());
                    dev.with_children(|r| {
                        r.spawn(focus(&skin, i));
                        r.spawn(text(&fonts.title, 28.0, INK, "开发者"));
                        r.spawn((
                            text(&fonts.body, 14.0, INK_DIM, "F1"),
                            Node {
                                position_type: PositionType::Absolute,
                                right: px(18),
                                top: px(12),
                                ..default()
                            },
                        ));
                    });
                    hook(&mut dev, i);
                }
                for (k, &item) in ITEMS.iter().enumerate() {
                    let mut row = p.spawn(row_node());
                    row.with_children(|r| {
                        r.spawn(focus(&skin, k + lay.first_item));
                        settings_ui::spawn_row(r, &fonts, &settings, item);
                    });
                    hook(&mut row, k + lay.first_item);
                }
                let mut quit = p.spawn(row_node());
                quit.with_children(|r| {
                    r.spawn(focus(&skin, lay.count - 1));
                    r.spawn(text(&fonts.title, 28.0, INK, "回到标题"));
                });
                hook(&mut quit, lay.count - 1);
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
    mut settings: ResMut<Settings>,
    mut controls: ResMut<crate::controls::Controls>,
    mut stats: ResMut<crate::stats_panel::StatsPanel>,
    mut dev: ResMut<crate::dev_panel::DevPanel>,
    mut window: PrimaryWindowQuery,
    mut next_run: ResMut<NextState<RunState>>,
    mut next_app: ResMut<NextState<AppState>>,
    mut cues: MessageWriter<UiCue>,
) {
    if controls.is_open() || transition.active() || stats.open || dev.open {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
    let lay = rows(&settings);
    let before_selected = ui.selected;
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h;
    }
    if actions.nav.y != 0 {
        ui.selected = (ui.selected as i32 + actions.nav.y).rem_euclid(lay.count as i32) as usize;
    }
    let clicked = ui.clicked.take();
    if let Some(c) = clicked {
        ui.selected = c;
    }
    let sel = ui.selected;
    if actions.quit_to_title || ((actions.confirm || clicked.is_some()) && sel == lay.count - 1) {
        next_app.set(AppState::Title);
    } else if actions.pause || actions.back || ((actions.confirm || clicked.is_some()) && sel == 0) {
        next_run.set(RunState::Playing);
    } else if actions.stats_toggle || ((actions.confirm || clicked.is_some()) && sel == 1) {
        stats.show();
    } else if lay.dev == Some(sel) && (actions.confirm || clicked.is_some()) {
        dev.show(false);
    } else if (lay.first_item..lay.first_item + ITEMS.len()).contains(&sel) {
        let mut a = *actions;
        // 点击设置项等同回车（全屏切换），音量用左右键
        a.confirm |= clicked.is_some();
        settings_ui::adjust(ITEMS[sel - lay.first_item], &a, &mut settings, &mut window, &mut controls);
    }
    if actions.pause || actions.back || actions.quit_to_title {
        cues.write(UiCue::Back);
    } else if actions.confirm || clicked.is_some() || actions.stats_toggle {
        cues.write(UiCue::Confirm);
    } else if before_selected != ui.selected || actions.nav.x != 0 {
        cues.write(UiCue::Move);
    }
}

fn highlight(
    ui: Res<PauseUi>,
    stats: Res<crate::stats_panel::StatsPanel>,
    dev: Res<crate::dev_panel::DevPanel>,
    mut q: Query<(&PauseFocus, &mut Visibility), Without<PauseRoot>>,
    mut root: Query<&mut Visibility, With<PauseRoot>>,
) {
    for (f, mut v) in &mut q {
        v.set_if_neq(if f.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
    for mut v in &mut root {
        v.set_if_neq(if stats.open || dev.open { Visibility::Hidden } else { Visibility::Inherited });
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
            .init_resource::<crate::stats_panel::StatsPanel>()
            .init_resource::<crate::dev_panel::DevPanel>()
            .init_resource::<crate::transition::InkTransition>()
            .init_resource::<NextState<RunState>>()
            .init_resource::<NextState<AppState>>()
            .add_message::<UiCue>()
            .add_systems(Update, input);
        app.world_mut().spawn((Window::default(), bevy::window::PrimaryWindow));
        // 第二行是属性：确认打开属性面板，面板开着时暂停菜单不动
        app.world_mut().resource_mut::<Actions>().nav = IVec2::Y;
        app.update();
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        assert!(app.world().resource::<crate::stats_panel::StatsPanel>().open);
        *app.world_mut().resource_mut::<Actions>() = Actions { back: true, ..default() };
        app.update();
        assert!(matches!(app.world().resource::<NextState<RunState>>(), NextState::Unchanged));
        app.world_mut().resource_mut::<crate::stats_panel::StatsPanel>().open = false;
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::Y, ..default() };
        for _ in 0..ITEMS.len() {
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
}
