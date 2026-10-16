//! 暂停内的只读查询。打开时从模拟取快照；暂停期间不会推进模拟。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;
use lantern_platform::{Actions, UiCue};
use lantern_sim::{Arsenal, Build, Flow, GameContent, Health, Player, Progress, RunState, Stats};

use crate::responsive::FitViewport;
use crate::skin::Skin;
use crate::{CINNABAR, Fonts, INK, INK_DIM, text};

mod build;
mod stats;

const GROUPS: [&str; 6] = ["法器与装备", "输出", "生存", "灯与照见", "构筑与收益", "今夜妖物"];
const PAGE_ROWS: usize = 10;

struct Row {
    label: String,
    value: String,
    detail: String,
    changed: bool,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Target {
    Tab(usize),
    Row(usize),
    Previous,
    Next,
    #[default]
    Close,
}

#[derive(Resource, Default)]
pub(crate) struct Inspector {
    open: bool,
    fresh: bool,
    dirty: bool,
    group: usize,
    page: usize,
    selected: Target,
    clicked: Option<Target>,
    hovered: Option<Target>,
    basic: Vec<Row>,
    groups: [Vec<Row>; 6],
    summary: String,
}

pub(super) fn register(app: &mut App) {
    app.init_resource::<Inspector>().add_systems(
        Update,
        (redraw, highlight).chain().after(super::input).run_if(in_state(RunState::Paused)),
    );
}

impl Inspector {
    pub(super) fn is_open(&self) -> bool {
        self.open
    }

    pub(super) fn open(&mut self) {
        *self = Self { open: true, fresh: true, dirty: true, selected: Target::Row(0), ..default() };
    }

    fn pages(&self) -> usize {
        self.groups[self.group].len().div_ceil(PAGE_ROWS).max(1)
    }

    fn visible(&self) -> &[Row] {
        let rows = &self.groups[self.group];
        let start = (self.page * PAGE_ROWS).min(rows.len());
        &rows[start..(start + PAGE_ROWS).min(rows.len())]
    }

    fn row(&self, index: usize) -> Option<&Row> {
        if index < self.basic.len() {
            self.basic.get(index)
        } else {
            self.visible().get(index - self.basic.len())
        }
    }

    fn select_group(&mut self, group: usize) {
        if self.group != group {
            self.group = group;
            self.page = 0;
            self.dirty = true;
        }
        self.selected =
            if self.visible().is_empty() { Target::Row(0) } else { Target::Row(self.basic.len()) };
    }

    pub(super) fn input(&mut self, actions: &Actions, cues: &mut MessageWriter<UiCue>) {
        if actions.back || actions.pause {
            self.open = false;
            self.dirty = true;
            self.clicked = None;
            self.hovered = None;
            cues.write(UiCue::Back);
            return;
        }
        let before = self.selected;
        if let Some(h) = self.hovered.take()
            && actions.pointer_moved
        {
            self.selected = h;
        }
        if actions.nav.x != 0 {
            let group = (self.group as i32 + actions.nav.x).rem_euclid(GROUPS.len() as i32) as usize;
            self.select_group(group);
        }
        if actions.nav.y != 0 {
            let mut targets: Vec<_> = (0..self.basic.len() + self.visible().len()).map(Target::Row).collect();
            if self.pages() > 1 {
                targets.extend([Target::Previous, Target::Next]);
            }
            targets.push(Target::Close);
            let i = targets.iter().position(|t| *t == self.selected).unwrap_or(0);
            self.selected = targets[(i as i32 + actions.nav.y).rem_euclid(targets.len() as i32) as usize];
        }
        let clicked = self.clicked.take();
        if let Some(target) = clicked {
            self.selected = target;
        }
        if actions.confirm || clicked.is_some() {
            match self.selected {
                Target::Tab(group) => self.select_group(group),
                Target::Previous | Target::Next => {
                    let delta = if self.selected == Target::Previous { -1 } else { 1 };
                    self.page = (self.page as i32 + delta).rem_euclid(self.pages() as i32) as usize;
                    self.dirty = true;
                }
                Target::Close => {
                    self.open = false;
                    self.dirty = true;
                }
                Target::Row(_) => {}
            }
            cues.write(UiCue::Confirm);
        } else if before != self.selected || actions.nav.x != 0 {
            cues.write(UiCue::Move);
        }
    }

    fn explanation(&self) -> String {
        match self.selected {
            Target::Row(i) => self
                .row(i)
                .map(|row| format!("{}　{}\n{}", row.label, row.value, row.detail))
                .unwrap_or_default(),
            Target::Tab(i) => format!("{}：点击切换，或用左右方向切换分组。", GROUPS[i]),
            Target::Previous | Target::Next => format!(
                "{} · 第 {} / {} 页。确认翻页；左右切换分组。",
                GROUPS[self.group],
                self.page + 1,
                self.pages()
            ),
            Target::Close => "返回暂停菜单；再次按返回可继续夜行。".into(),
        }
    }
}

#[derive(Component)]
struct InspectionRoot;

#[derive(Component)]
struct InspectionFocus(Target);

#[derive(Component)]
struct Explanation;

fn hook(row: &mut EntityCommands, target: Target) {
    row.observe(move |_: On<PointerClick>, mut ui: ResMut<Inspector>| ui.clicked = Some(target));
    row.observe(move |_: On<PointerOver>, mut ui: ResMut<Inspector>| ui.hovered = Some(target));
}

fn focus(skin: &Skin, target: Target) -> impl Bundle {
    (
        InspectionFocus(target),
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

fn row(parent: &mut ChildSpawnerCommands, fonts: &Fonts, skin: &Skin, info: &Row, index: usize) {
    let target = Target::Row(index);
    let mut entity = parent.spawn(Node {
        width: percent(100),
        height: px(30),
        flex_shrink: 0.0,
        padding: UiRect::axes(px(9), px(2)),
        align_items: AlignItems::Center,
        justify_content: JustifyContent::SpaceBetween,
        ..default()
    });
    hook(&mut entity, target);
    entity.with_children(|r| {
        r.spawn(focus(skin, target));
        r.spawn(text(&fonts.body, 18.0, INK, &info.label));
        r.spawn(text(&fonts.body, 18.0, if info.changed { CINNABAR } else { INK }, &info.value));
    });
}

fn button(
    parent: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    skin: &Skin,
    label: &str,
    target: Target,
    active: bool,
    width: f32,
) {
    let mut entity = parent.spawn((
        Node {
            width: px(width),
            height: px(32),
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            ..default()
        },
        BackgroundColor(if active { Color::srgba(0.65, 0.28, 0.13, 0.13) } else { Color::NONE }),
    ));
    hook(&mut entity, target);
    entity.with_children(|b| {
        b.spawn(focus(skin, target));
        b.spawn(text(&fonts.body, 18.0, if active { CINNABAR } else { INK }, label));
    });
}

fn redraw(
    mut commands: Commands,
    mut ui: ResMut<Inspector>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    content: Res<GameContent>,
    stats: Res<Stats>,
    flow: Res<Flow>,
    arsenal: Res<Arsenal>,
    build: Res<Build>,
    progress: Res<Progress>,
    player: Query<(&Health, &Player)>,
    roots: Query<Entity, With<InspectionRoot>>,
) {
    if !ui.dirty {
        return;
    }
    for root in &roots {
        commands.entity(root).despawn();
    }
    ui.dirty = false;
    ui.hovered = None;
    if !ui.open {
        return;
    }
    if ui.fresh {
        ui.fresh = false;
        let [basic, output, survival, light, economy, enemies] =
            stats::rows(&content.0, &stats, &flow, &arsenal, &build);
        ui.basic = basic;
        ui.groups = [build::rows(&content.0, &arsenal, &build), output, survival, light, economy, enemies];
        ui.summary = player
            .single()
            .map(|(h, p)| {
                format!(
                    "Lv{}　生命 {} / {}　护盾 {}　闪避 {} 段",
                    progress.level,
                    stats::number(h.hp),
                    stats::number(h.max),
                    stats::number(p.shield),
                    p.dash_ready
                )
            })
            .unwrap_or_else(|_| format!("Lv{}", progress.level));
    }
    commands
        .spawn((
            InspectionRoot,
            DespawnOnExit(RunState::Paused),
            GlobalZIndex(45),
            FitViewport::Fixed(Vec2::new(1120.0, 700.0)),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.96)),
        ))
        .with_children(|root| {
            root.spawn((
                Node {
                    width: px(1080),
                    height: px(660),
                    padding: UiRect::axes(px(32), px(18)),
                    flex_direction: FlexDirection::Column,
                    row_gap: px(10),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|panel| {
                panel
                    .spawn(Node {
                        height: px(40),
                        flex_shrink: 0.0,
                        width: percent(100),
                        align_items: AlignItems::Center,
                        justify_content: JustifyContent::SpaceBetween,
                        ..default()
                    })
                    .with_children(|header| {
                        header.spawn(text(&fonts.title, 32.0, INK, "属性与构筑"));
                        header.spawn(text(&fonts.body, 18.0, INK_DIM, &ui.summary));
                    });
                panel
                    .spawn(Node {
                        width: percent(100),
                        height: px(410),
                        flex_shrink: 0.0,
                        column_gap: px(20),
                        ..default()
                    })
                    .with_children(|body| {
                        body.spawn(Node {
                            width: px(300),
                            flex_shrink: 0.0,
                            flex_direction: FlexDirection::Column,
                            ..default()
                        })
                        .with_children(|basic| {
                            basic.spawn((
                                Node { height: px(30), ..default() },
                                text(&fonts.title, 24.0, INK, "基础属性"),
                            ));
                            for (i, info) in ui.basic.iter().enumerate() {
                                row(basic, &fonts, &skin, info, i);
                            }
                        });
                        body.spawn(Node {
                            flex_grow: 1.0,
                            min_width: px(0),
                            flex_direction: FlexDirection::Column,
                            row_gap: px(6),
                            ..default()
                        })
                        .with_children(|advanced| {
                            advanced
                                .spawn(Node { width: percent(100), flex_wrap: FlexWrap::Wrap, ..default() })
                                .with_children(|tabs| {
                                    for (i, label) in GROUPS.iter().enumerate() {
                                        button(
                                            tabs,
                                            &fonts,
                                            &skin,
                                            label,
                                            Target::Tab(i),
                                            ui.group == i,
                                            222.0,
                                        );
                                    }
                                });
                            advanced
                                .spawn(Node {
                                    width: percent(100),
                                    flex_direction: FlexDirection::Column,
                                    ..default()
                                })
                                .with_children(|list| {
                                    if ui.visible().is_empty() {
                                        list.spawn(text(&fonts.body, 18.0, INK_DIM, "尚未持有法器或装备"));
                                    }
                                    for (i, info) in ui.visible().iter().enumerate() {
                                        row(list, &fonts, &skin, info, ui.basic.len() + i);
                                    }
                                });
                            advanced.spawn(text(
                                &fonts.body,
                                16.0,
                                INK_DIM,
                                &format!("{} · 第 {} / {} 页", GROUPS[ui.group], ui.page + 1, ui.pages()),
                            ));
                        });
                    });
                panel
                    .spawn((
                        Node {
                            width: percent(100),
                            height: px(104),
                            flex_shrink: 0.0,
                            padding: UiRect::axes(px(12), px(4)),
                            ..default()
                        },
                        BackgroundColor(Color::srgba(0.20, 0.15, 0.08, 0.06)),
                    ))
                    .with_children(|help| {
                        help.spawn((
                            Explanation,
                            Node { width: percent(100), ..default() },
                            text(&fonts.body, 17.0, INK, &ui.explanation()),
                        ));
                    });
                panel
                    .spawn(Node {
                        width: percent(100),
                        height: px(36),
                        align_items: AlignItems::Center,
                        justify_content: JustifyContent::SpaceBetween,
                        ..default()
                    })
                    .with_children(|footer| {
                        footer.spawn(Node { column_gap: px(4), ..default() }).with_children(|buttons| {
                            if ui.pages() > 1 {
                                button(buttons, &fonts, &skin, "上一页", Target::Previous, false, 84.0);
                                button(buttons, &fonts, &skin, "下一页", Target::Next, false, 84.0);
                            }
                            button(buttons, &fonts, &skin, "返回暂停", Target::Close, false, 100.0);
                        });
                        footer.spawn(crate::prompts::hint(
                            &fonts.body,
                            15.0,
                            INK_DIM,
                            "左右切组　上下查看　{confirm} 确定　{back} 返回",
                        ));
                    });
            });
        });
}

fn highlight(
    ui: Res<Inspector>,
    mut focus: Query<(&InspectionFocus, &mut Visibility)>,
    mut help: Query<&mut Text, With<Explanation>>,
) {
    if !ui.open {
        return;
    }
    for (target, mut visibility) in &mut focus {
        visibility.set_if_neq(if target.0 == ui.selected {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        });
    }
    for mut text in &mut help {
        let next = ui.explanation();
        if text.0 != next {
            text.0 = next;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paging_focus_and_group_switch_keep_visible_rows_addressable() {
        let mut app = App::new();
        app.init_resource::<Inspector>().init_resource::<Actions>().add_message::<UiCue>().add_systems(
            Update,
            |actions: Res<Actions>, mut ui: ResMut<Inspector>, mut cues: MessageWriter<UiCue>| {
                ui.input(&actions, &mut cues)
            },
        );
        {
            let mut ui = app.world_mut().resource_mut::<Inspector>();
            ui.open();
            ui.groups[0] = (0..13)
                .map(|i| Row {
                    label: i.to_string(),
                    value: String::new(),
                    detail: format!("说明 {i}"),
                    changed: false,
                })
                .collect();
            ui.clicked = Some(Target::Next);
        }
        app.update();
        assert_eq!(app.world().resource::<Inspector>().page, 1);
        app.world_mut().resource_mut::<Inspector>().clicked = Some(Target::Row(2));
        app.update();
        assert!(app.world().resource::<Inspector>().explanation().contains("说明 12"));
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::X, ..default() };
        app.update();
        let ui = app.world().resource::<Inspector>();
        assert_eq!((ui.group, ui.page), (1, 0));
        assert!(ui.visible().is_empty());
        *app.world_mut().resource_mut::<Actions>() = Actions { nav: IVec2::Y, ..default() };
        app.update();
        assert_eq!(app.world().resource::<Inspector>().selected, Target::Close);
    }
}
