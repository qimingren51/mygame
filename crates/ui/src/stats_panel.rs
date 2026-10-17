//! 局内属性面板（docs/PLAYTEST.md 第 10 项；标签、说明、写法在 `stat_labels.ron`）。
//!
//! 暂停菜单的“属性”打开，可以移动焦点，焦点或鼠标所在的那一格在下方写含义和来源；对局中按住 Tab
//! 也能看（不暂停，松开就收起）。基础一组总是列全，其余组默认只列和初始值不同的，Tab 或确认键切换成全部。
//! 最后一组是法器：等级、进化还缺哪门心法。

use bevy::ecs::system::SystemParam;
use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_content::{Content, Stat, StatFormat};
use lantern_platform::{Actions, UiCue};
use lantern_sim::encounters::Encounters;
use lantern_sim::weapons::Form;
use lantern_sim::{
    AppState, Arsenal, Build, GameContent, Progress, RunSetup, RunState, StatSource, Stats, stats,
};

use lantern_view::atlas::AtlasDb;

use crate::responsive::FitViewport;
use crate::skin::Skin;
use crate::{Fonts, INK, INK_DIM, overlay_vignette, text};

/// 每行几格
const COLS: usize = 5;
const CHIP_W: f32 = 200.0;
const CHIP_H: f32 = 32.0;
const GAP: f32 = 8.0;
/// 左边组名那一列（图标加四五个字）
const GROUP_W: f32 = 132.0;
/// 格子里、组名前的数值图标
const ICON: f32 = 22.0;
const GROUP_ICON: f32 = 26.0;
const GRID_W: f32 = COLS as f32 * CHIP_W + (COLS - 1) as f32 * GAP;
/// 和初始值不同的数值用泥金写
const CHANGED: Color = Color::srgb(0.55, 0.30, 0.04);
/// 来源最多列几项
const MAX_SOURCES: usize = 6;

#[derive(Resource, Default)]
pub(crate) struct StatsPanel {
    /// 从暂停菜单打开
    pub(crate) open: bool,
    /// 刚打开的这一帧不处理按键，免得打开它的确认键再切换一次
    pub(crate) fresh: bool,
    /// 列全部；否则基础以外只列和初始值不同的
    all: bool,
    /// 要重画（切换了全部）
    redraw: bool,
    selected: usize,
    hovered: Option<usize>,
    /// 画着的格子
    items: Vec<Item>,
    /// 画着的时候是不是按住 Tab 看的
    drawn: Option<bool>,
}

impl StatsPanel {
    /// 暂停菜单里打开。
    pub(crate) fn show(&mut self) {
        self.open = true;
        self.fresh = true;
    }
}

/// 一组格子：组名、组图标的帧名、格子。
struct Group {
    name: String,
    icon: Option<String>,
    items: Vec<Item>,
}

#[derive(Clone, Debug, PartialEq)]
struct Item {
    /// 图标的帧名（`ui/stat_*`、法器图标）；图集里没有就不画
    icon: Option<String>,
    label: String,
    value: String,
    changed: bool,
    hint: String,
    /// 要列来源的属性
    stat: Option<(Stat, StatFormat)>,
    /// 网格里的行、列，方向键按它走
    row: usize,
    col: usize,
}

#[derive(Component)]
struct PanelRoot;

#[derive(Component)]
struct ChipFocus(usize);

#[derive(Component)]
struct HintText;

/// 画面板要读的模拟状态。
#[derive(SystemParam)]
struct RunData<'w> {
    content: Res<'w, GameContent>,
    stats: Res<'w, Stats>,
    build: Res<'w, Build>,
    arsenal: Res<'w, Arsenal>,
    setup: Res<'w, RunSetup>,
    encounters: Res<'w, Encounters>,
    progress: Res<'w, Progress>,
}

impl RunData<'_> {
    fn changed(&self) -> bool {
        self.stats.is_changed() || self.build.is_changed() || self.arsenal.is_changed()
    }

    fn sources(&self, stat: Stat) -> Vec<lantern_sim::StatContribution> {
        let buff = self.encounters.buff.map(|b| b.0);
        stats::sources(&self.content.0, &self.setup, &self.build, buff, self.progress.level, stat)
    }
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<StatsPanel>()
        .add_systems(OnExit(AppState::Run), |mut panel: ResMut<StatsPanel>| *panel = StatsPanel::default())
        .add_systems(
            Update,
            (sync, input.after(crate::pause::input), highlight)
                .chain()
                .run_if(in_state(AppState::Run))
                .run_if(resource_exists::<Stats>),
        );
}

/// 格子：基础一组列全，其余按 `all` 只列变了的；最后是法器。按组返回（组名、格子）。
fn collect_items(c: &Content, stats: &Stats, build: &Build, arsenal: &Arsenal, all: bool) -> Vec<Group> {
    let base = Stats::base(c);
    let mut groups = Vec::new();
    for g in &c.stat_labels {
        let mut items = Vec::new();
        for l in &g.stats {
            let v = stats.get(l.stat);
            let mut value = l.format.show(v);
            let mut changed = (v - base.get(l.stat)).abs() > 1e-4;
            if let Some(t) = l.times {
                let m = stats.get(t);
                changed |= (m - base.get(t)).abs() > 1e-4;
                if v >= 1.0 && (m - 1.0).abs() > 1e-4 {
                    value = format!("{value} {}", StatFormat::Times.show(m));
                }
            }
            if g.always || all || changed {
                items.push(Item {
                    icon: (!l.icon.is_empty()).then(|| format!("ui/stat_{}", l.icon)),
                    label: l.label.clone(),
                    value,
                    changed,
                    hint: l.hint.clone(),
                    stat: Some((l.stat, l.format)),
                    row: 0,
                    col: 0,
                });
            }
        }
        if !items.is_empty() {
            let icon = (!g.icon.is_empty()).then(|| format!("ui/stat_group_{}", g.icon));
            groups.push(Group { name: g.name.clone(), icon, items });
        }
    }
    let weapons: Vec<Item> = arsenal.0.iter().map(|w| weapon_item(c, build, w)).collect();
    if !weapons.is_empty() {
        groups.push(Group {
            name: "法器".into(),
            icon: Some("ui/stat_group_weapons".into()),
            items: weapons,
        });
    }
    // 网格位置：每组从新的一行开始
    let mut row = 0;
    for g in &mut groups {
        for (k, item) in g.items.iter_mut().enumerate() {
            item.row = row + k / COLS;
            item.col = k % COLS;
        }
        row += g.items.len().div_ceil(COLS);
    }
    groups
}

/// 法器一格：等级、进化还缺哪门心法；变过形的写形态。
fn weapon_item(c: &Content, build: &Build, w: &lantern_sim::weapons::WeaponSlot) -> Item {
    let def = &c.weapons[w.def];
    let max = def.levels.len();
    let key = def.evolution.as_ref().and_then(|e| c.passive_index(&e.passive));
    let (value, changed, hint) = match w.form {
        Form::Evolved => ("进化".into(), true, w.desc(c).to_string()),
        Form::Mutated => ("异化".into(), true, w.desc(c).to_string()),
        Form::Fused(_) => ("合璧".into(), true, w.desc(c).to_string()),
        Form::Base if w.can_evolve(c, build) => {
            (format!("Lv{}/{max}", w.level), true, "已满级，下次升级可进化".to_string())
        }
        Form::Base => match key {
            Some(p) if build.passive_level(p) == 0 => {
                let name = &c.passives[p].name;
                (
                    format!("Lv{}/{max} 缺{name}", w.level),
                    false,
                    format!("满级后配心法「{name}」可进化，还没拿到"),
                )
            }
            Some(p) => (
                format!("Lv{}/{max}", w.level),
                false,
                format!("心法「{}」已有，满级后可进化", c.passives[p].name),
            ),
            None => (format!("Lv{}/{max}", w.level), false, def.desc.clone()),
        },
    };
    let icon =
        if w.transformed() { format!("ui/icon_{}_evo", def.id) } else { format!("ui/icon_{}", def.id) };
    Item { icon: Some(icon), label: w.name(c).to_string(), value, changed, hint, stat: None, row: 0, col: 0 }
}

/// 来源的名字。
fn source_name(c: &Content, s: StatSource) -> String {
    match s {
        StatSource::Level => "等级".into(),
        StatSource::Meta(i) => format!("心灯·{}", c.meta.nodes[i].name),
        StatSource::Attribute(i) => format!("属性·{}", c.attributes.list[i].name),
        StatSource::Lamp(i) => c.lamps[i].name.clone(),
        StatSource::Charm(i) => c.charms[i].name.clone(),
        StatSource::Omen(i) => format!("夜签·{}", c.omens[i].name),
        StatSource::Difficulty(i) => c.difficulty[i].name.clone(),
        StatSource::Passive(i) => c.passives[i].name.clone(),
        StatSource::Tier(e, k) => format!("{}·{}阶", c.elements.elements[e].resonance, k + 1),
        StatSource::Sheng(i) => c.elements.sheng[i].name.clone(),
        StatSource::Taiji => "太极".into(),
        StatSource::Buff(i) => c.events.buffs[i].name.clone(),
    }
}

/// 焦点那一格的说明：含义，再加一行来源。
fn hint_text(data: &RunData, item: &Item) -> String {
    let mut s = format!("{}：{}", item.label, item.hint);
    if let Some((stat, format)) = item.stat {
        let c = &data.content.0;
        let found = data.sources(stat);
        if !found.is_empty() {
            let parts: Vec<String> = found
                .iter()
                .take(MAX_SOURCES)
                .map(|f| {
                    let mut v = Vec::new();
                    if f.add != 0.0 {
                        v.push(format.delta(f.add));
                    }
                    if f.mul != 0.0 {
                        v.push(StatFormat::Multiplier.delta(f.mul));
                    }
                    format!("{} {}", source_name(c, f.from), v.join(" "))
                })
                .collect();
            let more = if found.len() > MAX_SOURCES { "……" } else { "" };
            s.push_str(&format!("\n来源：{}{more}", parts.join("、")));
        }
    }
    s
}

/// 打开、收起、构筑变了时重画。
#[allow(clippy::too_many_arguments)]
fn sync(
    mut commands: Commands,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    actions: Res<Actions>,
    state: Option<Res<State<RunState>>>,
    data: RunData,
    db: Option<Res<AtlasDb>>,
    mut panel: ResMut<StatsPanel>,
    roots: Query<Entity, With<PanelRoot>>,
) {
    let state = state.map(|s| *s.get());
    let paused = state == Some(RunState::Paused);
    if panel.open && !paused {
        panel.open = false;
    }
    let peek = !panel.open && state == Some(RunState::Playing) && actions.stats_held;
    let show = panel.open || peek;
    if !show {
        if panel.drawn.take().is_some() {
            for e in &roots {
                commands.entity(e).despawn();
            }
        }
        return;
    }
    if panel.drawn == Some(peek) && !panel.redraw && !data.changed() {
        return;
    }
    let first = panel.drawn != Some(peek);
    panel.redraw = false;
    panel.drawn = Some(peek);
    for e in &roots {
        commands.entity(e).despawn();
    }
    let groups = collect_items(&data.content.0, &data.stats, &data.build, &data.arsenal, panel.all);
    // 切换全部后尽量停在同一格
    let keep = panel.items.get(panel.selected).map(|i| i.label.clone());
    panel.items = groups.iter().flat_map(|g| g.items.iter().cloned()).collect();
    panel.selected =
        if first { 0 } else { keep.and_then(|l| panel.items.iter().position(|i| i.label == l)).unwrap_or(0) };
    let rows = groups.iter().map(|g| g.items.len().div_ceil(COLS)).sum::<usize>();
    spawn(&mut commands, &fonts, &skin, db.as_deref(), &groups, rows, peek, panel.all);
}

/// 无窗口排版测试用：按给定的状态画一张面板。
#[cfg(test)]
pub(crate) fn spawn_preview(
    commands: &mut Commands,
    c: &Content,
    fonts: &Fonts,
    skin: &Skin,
    db: Option<&AtlasDb>,
    stats: &Stats,
    arsenal: &Arsenal,
    all: bool,
) {
    let groups = collect_items(c, stats, &Build::default(), arsenal, all);
    let rows = groups.iter().map(|g| g.items.len().div_ceil(COLS)).sum::<usize>();
    spawn(commands, fonts, skin, db, &groups, rows, false, all);
}

#[allow(clippy::too_many_arguments)]
fn spawn(
    commands: &mut Commands,
    fonts: &Fonts,
    skin: &Skin,
    db: Option<&AtlasDb>,
    groups: &[Group],
    rows: usize,
    peek: bool,
    all: bool,
) {
    // 行多时画布变高、整页等比缩小；只列变了的时候一般放得下 720
    let height = (230.0 + rows as f32 * (CHIP_H + GAP) + groups.len() as f32 * 6.0).max(720.0);
    commands
        .spawn((
            PanelRoot,
            FitViewport::Fixed(Vec2::new(1280.0, height)),
            DespawnOnExit(AppState::Run),
            GlobalZIndex(31),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            BackgroundColor(Color::srgba(0.03, 0.04, 0.07, if peek { 0.6 } else { 0.8 })),
        ))
        .with_children(|root| {
            root.spawn(overlay_vignette(skin));
            root.spawn((
                Node {
                    flex_direction: FlexDirection::Column,
                    padding: UiRect::axes(px(32), px(20)),
                    row_gap: px(8),
                    ..default()
                },
                skin.image("panel"),
            ))
            .with_children(|p| {
                p.spawn(Node {
                    width: px(GROUP_W + 12.0 + GRID_W),
                    align_items: AlignItems::Center,
                    justify_content: JustifyContent::SpaceBetween,
                    ..default()
                })
                .with_children(|head| {
                    head.spawn(Node { align_items: AlignItems::Baseline, column_gap: px(16), ..default() })
                        .with_children(|t| {
                            t.spawn(text(&fonts.title, 40.0, INK, "属性"));
                            let mode = if all { "全部" } else { "基础，和变了的" };
                            t.spawn(text(&fonts.body, 15.0, INK_DIM, mode));
                        });
                    let keys = if peek {
                        "松开 Tab 收起"
                    } else {
                        "{nav} 选择　Tab / {confirm} 切换全部　{back} 返回"
                    };
                    head.spawn(crate::prompts::hint(&fonts.body, 15.0, INK_DIM, keys));
                });
                p.spawn((Node { width: percent(100), height: px(12), ..default() }, skin.image("divider")));
                let mut i = 0;
                for g in groups {
                    p.spawn(Node { column_gap: px(12), margin: UiRect::bottom(px(6)), ..default() })
                        .with_children(|row| {
                            row.spawn(Node {
                                width: px(GROUP_W),
                                height: px(CHIP_H),
                                align_items: AlignItems::Center,
                                column_gap: px(6),
                                ..default()
                            })
                            .with_children(|head| {
                                atlas_icon(head, db, g.icon.as_deref(), GROUP_ICON);
                                head.spawn(text(&fonts.title, 20.0, INK, &g.name));
                            });
                            row.spawn(Node {
                                width: px(GRID_W),
                                flex_wrap: FlexWrap::Wrap,
                                column_gap: px(GAP),
                                row_gap: px(GAP),
                                ..default()
                            })
                            .with_children(|grid| {
                                for item in &g.items {
                                    chip(grid, fonts, skin, db, i, item);
                                    i += 1;
                                }
                            });
                        });
                }
                p.spawn((Node { width: percent(100), height: px(12), ..default() }, skin.image("divider")));
                p.spawn(Node { width: px(GROUP_W + 12.0 + GRID_W), min_height: px(46), ..default() })
                    .with_child((HintText, text(&fonts.body, 16.0, INK, "")));
            });
        });
}

/// 图集里有这帧就画一个方形图标，没有就什么也不画。
fn atlas_icon(p: &mut ChildSpawnerCommands, db: Option<&AtlasDb>, name: Option<&str>, size: f32) {
    if let Some(img) = db.zip(name).and_then(|(db, n)| db.find(n).map(|f| db.ui_image(f))) {
        p.spawn((Node { width: px(size), height: px(size), flex_shrink: 0.0, ..default() }, img));
    }
}

fn chip(
    grid: &mut ChildSpawnerCommands,
    fonts: &Fonts,
    skin: &Skin,
    db: Option<&AtlasDb>,
    i: usize,
    item: &Item,
) {
    let mut chip = grid.spawn((
        Node {
            width: px(CHIP_W),
            height: px(CHIP_H),
            padding: UiRect::horizontal(px(10)),
            align_items: AlignItems::Center,
            justify_content: JustifyContent::SpaceBetween,
            ..default()
        },
        BackgroundColor(INK.with_alpha(0.06)),
    ));
    chip.with_children(|c| {
        c.spawn((
            ChipFocus(i),
            Visibility::Hidden,
            Node {
                position_type: PositionType::Absolute,
                left: px(-3),
                right: px(-3),
                top: px(-3),
                bottom: px(-3),
                ..default()
            },
            skin.image("focus_ring"),
        ));
        c.spawn(Node { align_items: AlignItems::Center, column_gap: px(6), ..default() }).with_children(
            |l| {
                atlas_icon(l, db, item.icon.as_deref(), ICON);
                l.spawn(text(&fonts.body, 15.0, INK_DIM, &item.label));
            },
        );
        c.spawn(text(&fonts.body, 16.0, if item.changed { CHANGED } else { INK }, &item.value));
    });
    chip.observe(move |_: On<PointerOver>, mut panel: ResMut<StatsPanel>| panel.hovered = Some(i));
    chip.observe(move |_: On<PointerClick>, mut panel: ResMut<StatsPanel>| panel.hovered = Some(i));
}

/// 方向键在网格里走：左右按顺序（循环），上下到相邻一行里列最近的一格。
fn step(items: &[Item], from: usize, nav: IVec2) -> usize {
    let n = items.len();
    if n == 0 {
        return 0;
    }
    let from = from.min(n - 1);
    if nav.x != 0 {
        return (from as i32 + nav.x).rem_euclid(n as i32) as usize;
    }
    if nav.y == 0 {
        return from;
    }
    let rows = items.iter().map(|i| i.row).max().unwrap_or(0) + 1;
    let row = (items[from].row as i32 + nav.y).rem_euclid(rows as i32) as usize;
    let col = items[from].col;
    items
        .iter()
        .enumerate()
        .filter(|(_, i)| i.row == row)
        .min_by_key(|(_, i)| i.col.abs_diff(col))
        .map_or(from, |(k, _)| k)
}

/// 在暂停菜单里打开时：移动焦点、切换全部、返回。按住 Tab 看的时候只跟鼠标。
fn input(actions: Res<Actions>, mut panel: ResMut<StatsPanel>, mut cues: MessageWriter<UiCue>) {
    if panel.drawn.is_none() {
        panel.hovered = None;
        return;
    }
    if let Some(h) = panel.hovered.take()
        && actions.pointer_moved
        && h < panel.items.len()
    {
        panel.selected = h;
    }
    if !panel.open {
        return;
    }
    if std::mem::take(&mut panel.fresh) {
        return;
    }
    if actions.back || actions.pause {
        panel.open = false;
        cues.write(UiCue::Back);
        return;
    }
    if actions.stats_toggle || actions.confirm {
        panel.all = !panel.all;
        panel.redraw = true;
        cues.write(UiCue::Confirm);
        return;
    }
    let next = step(&panel.items, panel.selected, actions.nav);
    if next != panel.selected {
        panel.selected = next;
        cues.write(UiCue::Move);
    }
}

/// 焦点框和下方说明。
fn highlight(
    panel: Res<StatsPanel>,
    data: RunData,
    mut focus: Query<(&ChipFocus, &mut Visibility)>,
    mut hint: Query<&mut Text, With<HintText>>,
    added: Query<(), Added<HintText>>,
) {
    if !panel.is_changed() && added.is_empty() {
        return;
    }
    for (f, mut v) in &mut focus {
        v.set_if_neq(if f.0 == panel.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
    if let (Some(item), Ok(mut t)) = (panel.items.get(panel.selected), hint.single_mut()) {
        let s = hint_text(&data, item);
        if t.0 != s {
            t.0 = s;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn content() -> Content {
        Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data")).unwrap()
    }

    #[test]
    fn only_changed_stats_are_listed_unless_all_is_on() {
        let c = content();
        let mut stats = Stats::base(&c);
        let groups = collect_items(&c, &stats, &Build::default(), &Arsenal::default(), false);
        // 什么都没变时只有基础一组
        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].items.len(), 12);
        // 基础 12 项和组都带图标
        assert!(groups[0].items.iter().all(|i| i.icon.as_deref().is_some_and(|n| n.starts_with("ui/stat_"))));
        assert_eq!(groups[0].icon.as_deref(), Some("ui/stat_group_base"));
        let all = collect_items(&c, &stats, &Build::default(), &Arsenal::default(), true);
        assert_eq!(all.iter().map(|g| g.items.len()).sum::<usize>(), Stat::COUNT - 1);
        // 改一项进阶属性：它所在的组出现，数值标成变了
        stats = {
            let mut setup = RunSetup::new(1, lantern_sim::RunMode::Normal);
            setup.attributes.insert("magnet".into(), 2);
            setup.attributes.insert("xp".into(), 1);
            stats::collect(&c, &setup, &Build::default(), None, 1).0
        };
        let groups = collect_items(&c, &stats, &Build::default(), &Arsenal::default(), false);
        let xp = groups.iter().flat_map(|g| &g.items).find(|i| i.label == "魂火").unwrap();
        assert!(xp.changed);
        assert_eq!(xp.value, "+4%");
        let magnet = groups[0].items.iter().find(|i| i.label == "拾取").unwrap();
        assert!(magnet.changed);
    }

    #[test]
    fn grid_navigation_moves_between_rows_and_wraps() {
        let item = |row, col| Item {
            icon: None,
            label: String::new(),
            value: String::new(),
            changed: false,
            hint: String::new(),
            stat: None,
            row,
            col,
        };
        // 两行五格，第三行两格
        let items: Vec<Item> = (0..12).map(|k| item(k / 5, k % 5)).collect();
        assert_eq!(step(&items, 0, IVec2::X), 1);
        assert_eq!(step(&items, 0, IVec2::NEG_X), 11);
        assert_eq!(step(&items, 3, IVec2::Y), 8);
        // 下一行没有那么多列：落到最近的一格
        assert_eq!(step(&items, 9, IVec2::Y), 11);
        // 最上一行往上回到最下一行
        assert_eq!(step(&items, 0, IVec2::NEG_Y), 10);
    }

    #[test]
    fn weapons_show_the_missing_evolution_key() {
        let c = content();
        let lamp = c.weapon_index("lamp").unwrap();
        let w = lantern_sim::weapons::WeaponSlot::new(lamp);
        let item = weapon_item(&c, &Build::default(), &w);
        let key =
            &c.passives[c.passive_index(&c.weapons[lamp].evolution.as_ref().unwrap().passive).unwrap()].name;
        assert!(item.value.contains(key.as_str()), "{}", item.value);
        assert!(item.hint.contains("还没拿到"));
    }
}
