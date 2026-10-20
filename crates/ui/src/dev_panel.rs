//! 开发者面板（docs/PLAYTEST.md 第 13 项）。设置 → 高级里打开“开发者选项”以后：对局里按 F1、或在暂停菜单里点
//! “开发者”，标题和灯驿里按 F1。
//!
//! 局内的操作都发 `SimCommand::Dev`，回放照样复现，用过的局不计奖励和成绩；面板开着时对局暂停，合上以后生效。
//! 局外的全解锁、加灯油只改内存里的存档，之后本次启动不再存档。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::Content;
use lantern_platform::{Actions, Profile, Settings, UiCue};
use lantern_sim::run::RunPlan;
use lantern_sim::{AppState, Dev, DevCommand, GameContent, RunState, SimCommand, SimCommands, SimPhase};

use crate::responsive::FitViewport;
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, PAPER, overlay_vignette, text};

/// 对局里的页签；标题和灯驿里只有“局外”
const RUN_TABS: [&str; 6] = ["身板", "成长", "法器", "心法", "合璧", "局外"];
const META_TABS: [&str; 1] = ["局外"];
/// 伤害倍率的几档
const DAMAGE: [u16; 4] = [1, 10, 100, 1000];

#[derive(Resource, Default)]
pub(crate) struct DevPanel {
    pub(crate) open: bool,
    /// 对局里直接按 F1 打开的：合上就回到对局；从暂停菜单进来的回暂停菜单
    resume: bool,
    /// 刚打开的这一帧不处理按键，免得打开它的确认键再按到一个按钮
    fresh: bool,
    tab: usize,
    /// 焦点：第 0 行是页签，之后是按钮行
    row: usize,
    col: usize,
    clicked: Option<(usize, usize)>,
    hovered: Option<(usize, usize)>,
    /// 发出去还没生效的无敌、伤害倍率（面板开着时对局暂停，命令要等合上才执行）
    god: Option<bool>,
    damage: Option<u16>,
    /// 最近一次操作的回显
    note: String,
    dirty: bool,
}

impl DevPanel {
    /// 打开面板。resume：合上时回到对局。
    pub(crate) fn show(&mut self, resume: bool) {
        *self = DevPanel { open: true, resume, fresh: true, row: 1, dirty: true, ..default() };
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Action {
    Sim(DevCommand),
    /// 无敌开关：按现在的状态取反
    God,
    UnlockAll,
    AddMeta {
        oil: u32,
        gold: u32,
    },
}

struct Button {
    label: String,
    action: Action,
    /// 当前选中的那一档（无敌开着、正在用的伤害倍率）
    on: bool,
}

fn button(label: impl Into<String>, action: Action, on: bool) -> Button {
    Button { label: label.into(), action, on }
}

fn tabs(in_run: bool) -> &'static [&'static str] {
    if in_run { &RUN_TABS } else { &META_TABS }
}

/// 一页的按钮，按行排。
fn page(tab: &str, c: &Content, god: bool, damage: u16) -> Vec<Vec<Button>> {
    use DevCommand as D;
    let sim = Action::Sim;
    match tab {
        "身板" => vec![
            vec![button(if god { "无敌：开" } else { "无敌：关" }, Action::God, god)],
            DAMAGE.iter().map(|&n| button(format!("伤害 ×{n}"), sim(D::Damage(n)), damage == n)).collect(),
        ],
        "成长" => vec![
            vec![
                button("升 1 级", sim(D::Levels(1)), false),
                button("升 5 级", sim(D::Levels(5)), false),
                button("燃灯加满", sim(D::FillUlt), false),
            ],
            vec![
                button("铜钱 +100", sim(D::Gold(100)), false),
                button("铜钱 +1000", sim(D::Gold(1000)), false),
            ],
        ],
        "法器" => c
            .weapons
            .iter()
            .enumerate()
            .map(|(d, w)| {
                let d = d as u16;
                let mut row = vec![
                    button(format!("{} +1", w.name), sim(D::Weapon(d)), false),
                    button("满级", sim(D::MaxWeapon(d)), false),
                ];
                if w.evolution.is_some() {
                    row.push(button("进化", sim(D::Evolve(d)), false));
                }
                if w.mutation.is_some() {
                    row.push(button("异化", sim(D::Mutate(d)), false));
                }
                row
            })
            .collect(),
        "心法" => c
            .passives
            .iter()
            .enumerate()
            .map(|(k, p)| button(format!("{} +1", p.name), sim(D::Passive(k as u16)), false))
            .collect::<Vec<_>>()
            .chunks(4)
            .map(|row| row.iter().map(|b| button(b.label.clone(), b.action, false)).collect())
            .collect(),
        "合璧" => vec![
            c.fusions
                .iter()
                .enumerate()
                .map(|(f, def)| button(&def.name, sim(D::Fuse(f as u16)), false))
                .collect(),
        ],
        _ => vec![
            vec![button("全解锁（本次启动）", Action::UnlockAll, false)],
            vec![
                button("灯油 +5000", Action::AddMeta { oil: 5000, gold: 0 }, false),
                button("铜钱 +2000", Action::AddMeta { oil: 0, gold: 2000 }, false),
            ],
        ],
    }
}

#[derive(Component)]
struct Root;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<DevPanel>().add_systems(
        Update,
        (input, redraw)
            .chain()
            // 排在暂停菜单、标题界面之后：合上面板的那一下返回键，不再让它们也处理
            .after(crate::pause::input)
            .after(crate::title::input),
    );
}

/// 局内的状态：无敌、伤害倍率、能不能执行（选卡、宝箱、演出时不行）。
#[derive(bevy::ecs::system::SystemParam)]
struct RunInfo<'w> {
    plan: Option<Res<'w, RunPlan>>,
    dev: Option<Res<'w, Dev>>,
    phase: Option<Res<'w, SimPhase>>,
}

impl RunInfo<'_> {
    fn god(&self, panel: &DevPanel) -> bool {
        panel.god.unwrap_or(self.plan.as_ref().is_some_and(|p| p.god))
    }

    fn damage(&self, panel: &DevPanel) -> u16 {
        panel.damage.unwrap_or(self.dev.as_ref().map_or(1, |d| d.damage.round() as u16))
    }
}

#[allow(clippy::too_many_arguments)]
fn input(
    keys: Res<ButtonInput<KeyCode>>,
    actions: Res<Actions>,
    settings: Res<Settings>,
    content: Res<GameContent>,
    states: (Res<State<AppState>>, Option<Res<State<RunState>>>),
    mut next_run: ResMut<NextState<RunState>>,
    mut panel: ResMut<DevPanel>,
    run: RunInfo,
    (mut sim, mut profile): (ResMut<SimCommands>, ResMut<Profile>),
    mut cues: MessageWriter<UiCue>,
    title: Option<ResMut<crate::title::TitleUi>>,
) {
    let (app_state, run_state) = states;
    let in_run = *app_state.get() == AppState::Run;
    let close = |panel: &mut DevPanel, next_run: &mut NextState<RunState>| {
        panel.open = false;
        if panel.resume && in_run {
            next_run.set(RunState::Playing);
        }
    };
    if !settings.dev_tools {
        if panel.open {
            close(&mut panel, &mut next_run);
        }
        return;
    }
    if keys.just_pressed(KeyCode::F1) {
        if panel.open {
            close(&mut panel, &mut next_run);
            cues.write(UiCue::Back);
        } else if in_run {
            let playing = run_state.as_ref().is_some_and(|s| *s.get() == RunState::Playing);
            if playing {
                next_run.set(RunState::Paused);
            }
            panel.show(playing);
            cues.write(UiCue::Confirm);
        } else if *app_state.get() == AppState::Title {
            panel.show(false);
            cues.write(UiCue::Confirm);
        }
        return;
    }
    if !panel.open {
        return;
    }
    if panel.fresh {
        panel.fresh = false;
        panel.clicked = None;
        return;
    }
    if actions.back {
        close(&mut panel, &mut next_run);
        cues.write(UiCue::Back);
        return;
    }
    let names = tabs(in_run);
    panel.tab = panel.tab.min(names.len() - 1);
    let c = &content.0;
    let rows = page(names[panel.tab], c, run.god(&panel), run.damage(&panel));
    let width = |row: usize| if row == 0 { names.len() } else { rows.get(row - 1).map_or(1, Vec::len) };
    let before = (panel.tab, panel.row, panel.col);
    if let Some(h) = panel.hovered.take()
        && actions.pointer_moved
    {
        (panel.row, panel.col) = h;
    }
    if actions.nav.y != 0 {
        let from = panel.row;
        panel.row = (panel.row as i32 + actions.nav.y).rem_euclid(rows.len() as i32 + 1) as usize;
        // 回到页签行对准当前页；从页签行下来从第一个按钮开始
        panel.col = if panel.row == 0 {
            panel.tab
        } else if from == 0 {
            0
        } else {
            panel.col.min(width(panel.row) - 1)
        };
    }
    if actions.nav.x != 0 {
        panel.col = (panel.col as i32 + actions.nav.x).rem_euclid(width(panel.row) as i32) as usize;
        // 页签那一行左右就是翻页
        if panel.row == 0 {
            panel.tab = panel.col;
        }
    }
    let clicked = panel.clicked.take();
    if let Some(at) = clicked {
        (panel.row, panel.col) = at;
    }
    if actions.confirm || clicked.is_some() {
        if panel.row == 0 {
            panel.tab = panel.col;
        } else if let Some(b) = rows.get(panel.row - 1).and_then(|r| r.get(panel.col)) {
            let label = b.label.clone();
            panel.note = act(b.action, &label, c, &mut panel, &run, &mut sim, &mut profile);
            // 局外改了存档：灯驿、图鉴跟着重画
            if matches!(b.action, Action::UnlockAll | Action::AddMeta { .. })
                && let Some(mut t) = title
            {
                t.dirty = true;
            }
        }
        panel.dirty = true;
        cues.write(UiCue::Confirm);
    } else if before != (panel.tab, panel.row, panel.col) {
        panel.dirty = true;
        cues.write(UiCue::Move);
    }
}

/// 执行一个按钮，返回回显。
fn act(
    action: Action,
    label: &str,
    c: &Content,
    panel: &mut DevPanel,
    run: &RunInfo,
    sim: &mut SimCommands,
    profile: &mut Profile,
) -> String {
    let mut send = |cmd: DevCommand| {
        // 只在战斗中执行；选卡、宝箱、演出时模拟会丢掉
        if run.phase.as_deref().is_some_and(|p| *p != SimPhase::Play) {
            return format!("{label}：选卡、宝箱、演出时用不了，先回到战斗");
        }
        sim.0.push(SimCommand::Dev(cmd));
        format!("{label}：合上面板后生效。这一局不计奖励")
    };
    match action {
        Action::Sim(cmd) => {
            if let DevCommand::Damage(n) = cmd {
                panel.damage = Some(n);
            }
            send(cmd)
        }
        Action::God => {
            let on = !run.god(panel);
            panel.god = Some(on);
            send(DevCommand::God(on))
        }
        Action::UnlockAll => {
            profile.dev_unlock_all(c);
            "全解锁了。本次启动不再存档，重开游戏恢复原来的进度".into()
        }
        Action::AddMeta { oil, gold } => {
            profile.dev_add(oil, gold);
            format!("{label}。本次启动不再存档，重开游戏恢复原来的进度")
        }
    }
}

fn redraw(
    mut commands: Commands,
    mut panel: ResMut<DevPanel>,
    content: Res<GameContent>,
    app_state: Res<State<AppState>>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    run: RunInfo,
    roots: Query<Entity, With<Root>>,
) {
    if panel.open && !panel.dirty && !roots.is_empty() {
        return;
    }
    if !panel.open && roots.is_empty() {
        return;
    }
    for e in &roots {
        commands.entity(e).despawn();
    }
    if !panel.open {
        return;
    }
    panel.dirty = false;
    let in_run = *app_state.get() == AppState::Run;
    let names = tabs(in_run);
    let tab = panel.tab.min(names.len() - 1);
    let rows = page(names[tab], &content.0, run.god(&panel), run.damage(&panel));
    let focus = (panel.row, panel.col);
    commands
        .spawn((
            Root,
            GlobalZIndex(70),
            FitViewport::Fixed(Vec2::new(1280.0, 720.0)),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            BackgroundColor(Color::srgba(0.02, 0.025, 0.03, 0.9)),
        ))
        .with_children(|root| {
            root.spawn(overlay_vignette(&skin));
            root.spawn((
                Node {
                    width: px(1120),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    padding: UiRect::axes(px(40), px(22)),
                    row_gap: px(10),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|p| {
                p.spawn(text(&fonts.title, 40.0, INK, "开发者"));
                p.spawn(Node { column_gap: px(18), ..default() }).with_children(|r| {
                    for (k, name) in names.iter().enumerate() {
                        let on = k == tab;
                        chip(r, &fonts, &skin, name, on, focus == (0, k), (0, k));
                    }
                });
                p.spawn((Node { width: percent(100), height: px(12), ..default() }, skin.image("divider")));
                for (i, row) in rows.iter().enumerate() {
                    p.spawn(Node { column_gap: px(10), flex_wrap: FlexWrap::Wrap, ..default() })
                        .with_children(|r| {
                            for (j, b) in row.iter().enumerate() {
                                chip(r, &fonts, &skin, &b.label, b.on, focus == (i + 1, j), (i + 1, j));
                            }
                        });
                }
                if !panel.note.is_empty() {
                    p.spawn(text(&fonts.body, 16.0, INK, &panel.note));
                }
                let note = if in_run {
                    "局内的操作进回放；用过的局不计灯油、铜钱和成绩"
                } else {
                    "局外的操作只改这次启动，期间不存档"
                };
                p.spawn(text(&fonts.body, 15.0, INK_DIM, note));
                p.spawn(crate::prompts::hint(
                    &fonts.body,
                    16.0,
                    INK_DIM,
                    "{nav} 选择　{confirm} 执行　{back} 合上　F1 合上",
                ));
            });
        });
}

/// 一个按钮：药丸底，焦点处加一圈。
fn chip(
    p: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    skin: &Skin,
    label: &str,
    on: bool,
    focused: bool,
    at: (usize, usize),
) {
    let mut e = p.spawn((
        Node { padding: UiRect::axes(px(14), px(4)), ..default() },
        skin.image(if on { "pill_on" } else { "pill" }),
    ));
    e.with_children(|c| {
        if focused {
            c.spawn((
                Node {
                    position_type: PositionType::Absolute,
                    left: px(-4),
                    right: px(-4),
                    top: px(-4),
                    bottom: px(-4),
                    ..default()
                },
                skin.image("focus_ring"),
            ));
        }
        c.spawn(text(&fonts.body, 18.0, if on { PAPER } else { INK }, label));
    });
    e.observe(move |_: On<PointerClick>, mut panel: ResMut<DevPanel>| panel.clicked = Some(at));
    e.observe(move |_: On<PointerOver>, mut panel: ResMut<DevPanel>| panel.hovered = Some(at));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn content() -> Content {
        Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).unwrap()
    }

    /// 每页都有按钮；法器页一件一行，进化、异化按数据有没有给
    #[test]
    fn every_tab_has_buttons_and_weapon_rows_follow_the_data() {
        let c = content();
        for name in RUN_TABS {
            let rows = page(name, &c, false, 1);
            assert!(!rows.is_empty() && rows.iter().all(|r| !r.is_empty()), "{name}");
        }
        let weapons = page("法器", &c, false, 1);
        assert_eq!(weapons.len(), c.weapons.len());
        for (row, w) in weapons.iter().zip(&c.weapons) {
            assert_eq!(row.len(), 2 + usize::from(w.evolution.is_some()) + usize::from(w.mutation.is_some()));
        }
        let passives: usize = page("心法", &c, false, 1).iter().map(Vec::len).sum();
        assert_eq!(passives, c.passives.len());
        // 当前的那一档点亮
        assert!(page("身板", &c, true, 100)[0][0].on);
        assert!(page("身板", &c, false, 100)[1].iter().any(|b| b.on && b.label == "伤害 ×100"));
    }

    fn app(state: AppState) -> App {
        let mut app = App::new();
        app.add_plugins(bevy::state::app::StatesPlugin)
            .insert_resource(GameContent(std::sync::Arc::new(content())))
            .insert_resource({
                let mut s = Settings::default();
                s.dev_tools = true;
                s
            })
            .init_resource::<Actions>()
            .init_resource::<ButtonInput<KeyCode>>()
            .init_resource::<DevPanel>()
            .init_resource::<SimCommands>()
            .init_resource::<Profile>()
            .insert_state(state)
            .add_sub_state::<RunState>()
            .add_message::<UiCue>()
            .add_systems(Update, input);
        if state == AppState::Run {
            app.insert_resource(SimPhase::Play);
        }
        app
    }

    fn press_f1(app: &mut App) {
        app.world_mut().resource_mut::<ButtonInput<KeyCode>>().press(KeyCode::F1);
        app.update();
        app.world_mut().resource_mut::<ButtonInput<KeyCode>>().clear();
        app.world_mut().resource_mut::<ButtonInput<KeyCode>>().release(KeyCode::F1);
    }

    /// 对局里按 F1：暂停、打开面板；“成长”页按“升 1 级”发出开发者命令；返回键合上并回到对局
    #[test]
    fn f1_pauses_the_run_and_buttons_send_dev_commands() {
        let mut app = app(AppState::Run);
        app.update();
        press_f1(&mut app);
        assert!(app.world().resource::<DevPanel>().open);
        assert!(matches!(
            app.world().resource::<NextState<RunState>>(),
            NextState::Pending(RunState::Paused)
        ));
        app.update();
        // 到页签行，往右翻到“成长”，再下到第一行按确认
        let set = |app: &mut App, a: Actions| *app.world_mut().resource_mut::<Actions>() = a;
        set(&mut app, Actions { nav: IVec2::NEG_Y, ..default() });
        app.update();
        set(&mut app, Actions { nav: IVec2::X, ..default() });
        app.update();
        assert_eq!(app.world().resource::<DevPanel>().tab, 1);
        set(&mut app, Actions { nav: IVec2::Y, ..default() });
        app.update();
        set(&mut app, Actions { confirm: true, ..default() });
        app.update();
        assert_eq!(app.world().resource::<SimCommands>().0, vec![SimCommand::Dev(DevCommand::Levels(1))]);
        set(&mut app, Actions { back: true, ..default() });
        app.update();
        assert!(!app.world().resource::<DevPanel>().open);
        assert!(matches!(
            app.world().resource::<NextState<RunState>>(),
            NextState::Pending(RunState::Playing)
        ));
    }

    /// 设置里没打开开发者选项时，F1 没反应
    #[test]
    fn f1_does_nothing_unless_enabled() {
        let mut app = app(AppState::Title);
        app.world_mut().resource_mut::<Settings>().dev_tools = false;
        app.update();
        press_f1(&mut app);
        assert!(!app.world().resource::<DevPanel>().open);
    }

    /// 标题里只有“局外”：全解锁只改内存
    #[test]
    fn title_panel_unlocks_everything_in_memory() {
        let mut app = app(AppState::Title);
        app.update();
        press_f1(&mut app);
        assert!(app.world().resource::<DevPanel>().open);
        app.update();
        *app.world_mut().resource_mut::<Actions>() = Actions { confirm: true, ..default() };
        app.update();
        let profile = app.world().resource::<Profile>();
        assert!(profile.dev_session());
        assert!(profile.basics);
        assert!(app.world().resource::<SimCommands>().0.is_empty());
    }
}
