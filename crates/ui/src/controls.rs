//! 标题与暂停共用的改键面板：双列、焦点框、即时存档与可恢复的错误反馈。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;
use lantern_platform::bindings::{BindError, RebindFeedback, button_label, key_label};
use lantern_platform::{Action, Actions, ActiveInput, InputDevice, Rebind, Settings};

use crate::prompts::hint;
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, PAPER, text};

#[derive(Resource, Default)]
pub(crate) struct Controls {
    device: Option<InputDevice>,
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
    fresh: bool,
}

impl Controls {
    pub(crate) fn is_open(&self) -> bool {
        self.device.is_some()
    }
    pub(crate) fn open(&mut self, device: InputDevice) {
        *self = Self { device: Some(device), fresh: true, ..default() };
    }
}

#[derive(Component)]
struct ControlsRoot;
#[derive(Component)]
struct ControlFocus(usize);
#[derive(Component)]
struct BindingValue(Action);
#[derive(Component)]
struct Feedback;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Controls>().add_systems(
        Update,
        (input, redraw, refresh).chain().after(crate::title::input).after(crate::pause::input),
    );
}

fn actions(device: InputDevice) -> &'static [Action] {
    match device {
        InputDevice::Keyboard => &Action::ALL,
        InputDevice::Gamepad => &Action::BUTTONS,
    }
}

fn label(action: Action) -> &'static str {
    match action {
        Action::Up => "向上移动",
        Action::Down => "向下移动",
        Action::Left => "向左移动",
        Action::Right => "向右移动",
        Action::Dash => "闪避",
        Action::Ult => "燃灯",
        Action::Interact => "交互",
        Action::Pause => "暂停",
        Action::Confirm => "确定",
        Action::Back => "返回",
        Action::Reroll => "重抽",
        Action::Skip => "跳过",
        Action::Banish => "封印",
        Action::Hub => "灯驿",
    }
}

fn input(
    actions: Res<Actions>,
    mut ui: ResMut<Controls>,
    mut rebind: ResMut<Rebind>,
    mut settings: ResMut<Settings>,
) {
    let Some(device) = ui.device else { return };
    if ui.fresh {
        return;
    }
    if rebind.target.is_some() {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
    let count = self::actions(device).len();
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h;
    }
    ui.selected = crate::navigation::grid(ui.selected, actions.nav, count + 2, 2);
    let clicked = ui.clicked.take();
    if let Some(i) = clicked {
        ui.selected = i;
    }
    if actions.back || ((actions.confirm || clicked.is_some()) && ui.selected == count + 1) {
        ui.device = None;
    } else if actions.confirm || clicked.is_some() {
        if ui.selected == count {
            settings.bindings.reset(device);
            rebind.feedback =
                if settings.save().is_ok() { RebindFeedback::Saved } else { RebindFeedback::SaveFailed };
        } else if let Some(&action) = self::actions(device).get(ui.selected) {
            rebind.begin(device, action);
        }
    }
}

fn redraw(
    mut commands: Commands,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    mut ui: ResMut<Controls>,
    mut rebind: ResMut<Rebind>,
    roots: Query<Entity, With<ControlsRoot>>,
) {
    if !ui.is_open() {
        for root in &roots {
            commands.entity(root).despawn();
        }
        return;
    }
    if !ui.fresh {
        return;
    }
    ui.fresh = false;
    *rebind = Rebind::default();
    let device = ui.device.unwrap();
    commands
        .spawn((
            ControlsRoot,
            GlobalZIndex(60),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            BackgroundColor(Color::srgba(0.02, 0.025, 0.04, 0.92)),
        ))
        .with_children(|root| {
            root.spawn((
                Node {
                    width: px(860),
                    padding: UiRect::axes(px(48), px(28)),
                    row_gap: px(12),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|panel| {
                panel.spawn(text(
                    &fonts.title,
                    48.0,
                    INK,
                    if device == InputDevice::Keyboard { "键盘按键" } else { "手柄按键" },
                ));
                panel.spawn(text(
                    &fonts.body,
                    16.0,
                    INK_DIM,
                    if device == InputDevice::Keyboard {
                        "方向键与 Esc 始终可用；选择一项后按下新按键"
                    } else {
                        "面键位置：A 下 · B 右 · X 左 · Y 上；十字键与左摇杆保持导航"
                    },
                ));
                panel
                    .spawn(Node {
                        width: percent(100),
                        flex_wrap: FlexWrap::Wrap,
                        row_gap: px(6),
                        ..default()
                    })
                    .with_children(|grid| {
                        let list = actions(device);
                        for i in 0..list.len() + 2 {
                            let mut row = grid.spawn(Node {
                                width: percent(50),
                                height: px(44),
                                padding: UiRect::axes(px(18), px(6)),
                                align_items: AlignItems::Center,
                                justify_content: JustifyContent::SpaceBetween,
                                ..default()
                            });
                            row.observe(move |_: On<PointerClick>, mut ui: ResMut<Controls>| {
                                ui.clicked = Some(i)
                            });
                            row.observe(move |_: On<PointerOver>, mut ui: ResMut<Controls>| {
                                ui.hovered = Some(i)
                            });
                            row.with_children(|r| {
                                r.spawn((
                                    ControlFocus(i),
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
                                if let Some(&action) = list.get(i) {
                                    r.spawn(text(&fonts.body, 20.0, INK, label(action)));
                                    r.spawn((BindingValue(action), text(&fonts.body, 18.0, INK_DIM, "")));
                                } else {
                                    r.spawn(text(
                                        &fonts.title,
                                        26.0,
                                        INK,
                                        if i == list.len() { "恢复本页默认" } else { "返回设置" },
                                    ));
                                }
                            });
                        }
                    });
                panel.spawn((
                    Feedback,
                    Node { min_height: px(44), ..default() },
                    text(&fonts.body, 17.0, INK, ""),
                ));
                panel.spawn(hint(&fonts.body, 16.0, INK_DIM, "{nav} 选择　{confirm} 改键　{back} 返回"));
            });
            root.spawn((
                Node { position_type: PositionType::Absolute, bottom: px(22), ..default() },
                text(&fonts.body, 14.0, PAPER, "按键立即生效，并保存在设置中"),
            ));
        });
}

fn refresh(
    active: Res<ActiveInput>,
    ui: Res<Controls>,
    rebind: Res<Rebind>,
    settings: Res<Settings>,
    mut focus: Query<(&ControlFocus, &mut Visibility)>,
    mut values: Query<(&BindingValue, &mut Text), Without<Feedback>>,
    mut feedback: Query<&mut Text, (With<Feedback>, Without<BindingValue>)>,
) {
    let Some(device) = ui.device else { return };
    for (index, mut visible) in &mut focus {
        *visible = if ui.selected == index.0 { Visibility::Inherited } else { Visibility::Hidden };
    }
    for (action, mut value) in &mut values {
        value.0 = if rebind.target.is_some_and(|(_, a)| a == action.0) {
            "等待按键…".into()
        } else if device == InputDevice::Keyboard {
            key_label(settings.bindings.key(action.0))
        } else {
            button_label(settings.bindings.button(action.0))
        };
    }
    let cancel_action =
        if rebind.target.is_some_and(|(_, a)| a == Action::Back) { Action::Confirm } else { Action::Back };
    let cancel = if active.device == InputDevice::Keyboard {
        "Esc".into()
    } else {
        button_label(settings.bindings.button(cancel_action))
    };
    for mut value in &mut feedback {
        value.0 = match rebind.feedback {
            RebindFeedback::Idle => "同一场景的按键不能重复；可随时恢复默认".into(),
            RebindFeedback::Listening => format!("请先松开按键，再按新按键；{cancel} 取消"),
            RebindFeedback::Saved => "按键已保存".into(),
            RebindFeedback::Cancelled => "已取消，保留原按键".into(),
            RebindFeedback::Error(BindError::Reserved) => {
                format!("这个按键用于系统或导航，请换一个；{cancel} 取消")
            }
            RebindFeedback::Error(BindError::Conflict(action)) => {
                format!("已用于「{}」，请换一个；{cancel} 取消", label(action))
            }
            RebindFeedback::SaveFailed => "按键已生效，但写入失败，请检查存档目录".into(),
        };
    }
}
