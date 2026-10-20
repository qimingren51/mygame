//! 游戏中的信息栏：用时、击杀、等级与经验条、生命与护盾、燃灯、法器与心法、五行共鸣、
//! 夜主血条、连斩、古灯增益、操作提示。

use bevy::prelude::*;

use lantern_content::{Element, Rank};
use lantern_core::step::TICK_HZ;
use lantern_sim::encounters::Encounters;
use lantern_sim::{
    AppState, Arsenal, Build, Director, Enemies, GameContent, Health, Player, Progress, RunMode, RunSetup,
    RunState, SimPhase, Tick,
};
use lantern_view::atlas::AtlasDb;

use crate::choice::spawn_icon;
use crate::describe::{element_color, hex, passive_color};
use crate::skin::Skin;
use crate::{DIM, Fonts, PAPER, text};

#[derive(Component)]
pub(crate) struct Clock;

#[derive(Component)]
pub(crate) struct Kills;

#[derive(Component)]
pub(crate) struct LevelLabel;

#[derive(Component)]
pub(crate) struct XpFill;

#[derive(Component)]
pub(crate) struct HpFill;

#[derive(Component)]
pub(crate) struct ShieldFill;

#[derive(Component)]
pub(crate) struct HpLabel;

#[derive(Component)]
pub(crate) struct UltFill;

#[derive(Component)]
pub(crate) struct UltLabel;

#[derive(Component)]
pub(crate) struct Slots;

#[derive(Component)]
pub(crate) struct ElementChip(Element);

/// 五行计数前面的图标（`ui/icon_el_*`），和点数一起变淡变亮。
#[derive(Component)]
pub(crate) struct ElementIcon(Element);

/// 五行图标的帧名后缀，按 `Element::index` 排
const ELEMENT_ICONS: [&str; 5] = ["metal", "wood", "water", "fire", "earth"];
/// 共鸣阶数的记号：一阶到三阶、极境
const TIER_MARKS: [&str; 5] = ["", "·一", "·二", "·三", "·极"];

#[derive(Component)]
pub(crate) struct BossBar;

#[derive(Component)]
pub(crate) struct BossFill;

#[derive(Component)]
pub(crate) struct BossName;

#[derive(Component)]
pub(crate) struct ComboLabel;

#[derive(Component)]
pub(crate) struct BuffLabel;

#[derive(Component)]
pub(crate) struct ControlHints;

#[derive(Component)]
pub(crate) struct HudFooter;

pub(crate) const FOOTER_BOTTOM: f32 = 14.0;

const GOLD: Color = Color::srgb(1.0, 0.85, 0.54);

fn abs(left: Option<f32>, right: Option<f32>, top: Option<f32>, bottom: Option<f32>) -> Node {
    Node {
        position_type: PositionType::Absolute,
        left: left.map_or(Val::Auto, px),
        right: right.map_or(Val::Auto, px),
        top: top.map_or(Val::Auto, px),
        bottom: bottom.map_or(Val::Auto, px),
        ..default()
    }
}

/// 进度条：底槽（毛笔横拖）里放一条填充，填充的宽度按百分比设。
fn bar(skin: &Skin, width: f32, height: f32, fill: impl Bundle, fill_skin: &str) -> impl Bundle {
    let inset = (height * 4.0 / 36.0).max(1.0);
    (
        Node { width: px(width), height: px(height), padding: UiRect::all(px(inset)), ..default() },
        skin.image("bar_track"),
        children![(
            fill,
            Node { width: percent(0), height: percent(100), ..default() },
            skin.image(fill_skin)
        )],
    )
}

pub(crate) fn spawn_hud(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    setup: Res<RunSetup>,
    db: Option<Res<AtlasDb>>,
) {
    let c = &content.0;
    let db = db.as_deref();
    let run = DespawnOnExit(AppState::Run);
    // 顶部三块放在同一张画布里：窗口比 1280×720 小时一起等比缩小，不互相压住
    commands
        .spawn((
            run.clone(),
            crate::responsive::FitViewport::default(),
            Pickable::IGNORE,
            Node { position_type: PositionType::Absolute, ..default() },
        ))
        .with_children(|canvas| {
            // 左上：头像章（燃灯刻度、等级印）；右边血条、经验条、法器格、心法格
            canvas
                .spawn(Node {
                    column_gap: px(10),
                    align_items: AlignItems::Start,
                    ..abs(Some(16.0), None, Some(12.0), None)
                })
                .with_children(|p| {
                    p.spawn(Node {
                        flex_direction: FlexDirection::Column,
                        align_items: AlignItems::Center,
                        width: px(PORTRAIT),
                        ..default()
                    })
                    .with_children(|col| {
                        portrait(col, db, &fonts, &skin);
                        col.spawn((
                            UltLabel,
                            UiTransform::default(),
                            Node { margin: UiRect::top(px(4)), ..default() },
                            text(&fonts.body, 15.0, GOLD, ""),
                        ));
                        col.spawn((
                            crate::hud_fx::UltHint,
                            Node {
                                position_type: PositionType::Absolute,
                                top: px(PORTRAIT + 4.0),
                                width: px(120),
                                justify_content: JustifyContent::Center,
                                ..default()
                            },
                            TextLayout::justify(Justify::Center),
                            text(&fonts.body, 15.0, GOLD.with_alpha(0.0), "燃灯未满"),
                        ));
                    });
                    p.spawn(Node { flex_direction: FlexDirection::Column, row_gap: px(4), ..default() })
                        .with_children(|col| {
                            col.spawn(hp_bar(&fonts, &skin));
                            col.spawn((
                                Node {
                                    width: px(BAR_WIDTH),
                                    height: px(10),
                                    padding: UiRect::all(px(2)),
                                    ..default()
                                },
                                skin.image("hud_xp_track"),
                                children![(
                                    XpFill,
                                    Node { width: percent(0), height: percent(100), ..default() },
                                    skin.image("bar_fill_xp")
                                )],
                            ));
                            col.spawn((
                                Slots,
                                Node {
                                    flex_direction: FlexDirection::Column,
                                    row_gap: px(4),
                                    margin: UiRect::top(px(6)),
                                    ..default()
                                },
                            ));
                        });
                });
            // 顶部中间：用时
            canvas.spawn((
                Node {
                    justify_content: JustifyContent::Center,
                    ..abs(Some(0.0), Some(0.0), Some(10.0), None)
                },
                children![(Clock, text(&fonts.body, 30.0, PAPER, "00:00"))],
            ));
            // 右上：五行共鸣；下面击杀与收获、夜签、古灯增益
            canvas
                .spawn(Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::End,
                    row_gap: px(6),
                    ..abs(None, Some(16.0), Some(12.0), None)
                })
                .with_children(|p| {
                    element_chips(p, c, db, &fonts, &skin);
                    p.spawn((Kills, UiTransform::default(), text(&fonts.body, 16.0, PAPER, "击杀 0")));
                    if let Some(o) = &setup.omen {
                        p.spawn(Node { align_items: AlignItems::Center, column_gap: px(6), ..default() })
                            .with_children(|row| {
                                if let Some(db) = db {
                                    let icon = format!("ui/icon_omen_{}", o.id);
                                    spawn_icon(row, db, &fonts, Some(&icon), "签", DIM, 26.0);
                                }
                                row.spawn(text(&fonts.body, 15.0, DIM, &lantern_sim::omens::omen_name(c, o)));
                            });
                    }
                    p.spawn((BuffLabel, text(&fonts.body, 16.0, GOLD, "")));
                });
            // 右侧：连斩
            canvas.spawn((
                abs(None, Some(28.0), Some(260.0), None),
                children![(ComboLabel, text(&fonts.title, 36.0, GOLD, ""))],
            ));
        });
    // 底部共用纵向布局：夜主血条、操作提示；提示换行时向上让位，边缘箭头按它的高度让开。
    commands.spawn((
        run,
        HudFooter,
        Node {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            row_gap: px(4),
            padding: UiRect::horizontal(px(20)),
            ..abs(Some(0.0), Some(0.0), None, Some(FOOTER_BOTTOM))
        },
        children![
            (
                BossBar,
                Visibility::Hidden,
                Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    row_gap: px(4),
                    ..default()
                },
                children![
                    (BossName, text(&fonts.title, 26.0, hex("#FF6B5A"), "")),
                    bar(&skin, 560.0, 18.0, BossFill, "bar_fill_boss"),
                ],
            ),
            (
                ControlHints,
                Node {
                    display: Display::None,
                    max_width: percent(100),
                    margin: UiRect::top(px(10)),
                    ..default()
                },
                TextLayout::justify(Justify::Center),
                crate::prompts::hint(
                    &fonts.body,
                    16.0,
                    DIM,
                    "{move} 移动　{dash} 闪避　{ult} 燃灯　{pause} 暂停"
                ),
            ),
        ],
    ));
}

/// 头像章的边长；燃灯刻度沿圆环排一圈，等级印压在右下角。
const PORTRAIT: f32 = 104.0;
/// 燃灯刻度的个数和尺寸（长边沿着圆周）
const TICKS: usize = 12;
const TICK: Vec2 = Vec2::new(17.0, 10.0);
/// 血条、经验条的宽度
const BAR_WIDTH: f32 = 460.0;
/// 血条底槽的内边距：填充画在里面
const HP_INSET: f32 = 7.0;

/// 法器格、心法格的边长
const SLOT_L: f32 = 64.0;
const SLOT_S: f32 = 44.0;

/// 燃灯刻度：第 k 个在燃灯到 (k+1)/12 时点亮，蓄满时整圈换成满格。
#[derive(Component)]
pub(crate) struct UltTick(pub(crate) usize);

fn portrait(p: &mut ChildSpawnerCommands, db: Option<&AtlasDb>, fonts: &Fonts, skin: &Skin) {
    p.spawn((
        crate::hud_fx::UltBar::default(),
        UiTransform::default(),
        Node { width: px(PORTRAIT), height: px(PORTRAIT), ..default() },
    ))
    .with_children(|seal| {
        // 胸像画在圆章底下，自带的毛笔圈藏在漆环后面
        let hero = 92.0;
        let inset = (PORTRAIT - hero) / 2.0;
        if let Some(f) = db.and_then(|db| db.find("ui/portrait_hero").map(|f| db.ui_image(f))) {
            seal.spawn((
                Node { width: px(hero), height: px(hero), ..abs(Some(inset), None, Some(inset), None) },
                f,
            ));
        }
        seal.spawn((
            Node { width: percent(100), height: percent(100), ..abs(Some(0.0), None, Some(0.0), None) },
            skin.image("hud_portrait"),
        ));
        let r = PORTRAIT / 2.0 - TICK.y / 2.0 - 3.5;
        for k in 0..TICKS {
            let a = k as f32 / TICKS as f32 * std::f32::consts::TAU;
            let at = Vec2::new(PORTRAIT / 2.0 + r * a.sin(), PORTRAIT / 2.0 - r * a.cos()) - TICK / 2.0;
            seal.spawn((
                UltTick(k),
                UltFill,
                Node { width: px(TICK.x), height: px(TICK.y), ..abs(Some(at.x), None, Some(at.y), None) },
                UiTransform { rotation: Rot2::radians(a), ..default() },
                skin.image("hud_ult_tick"),
            ));
        }
        seal.spawn((
            crate::hud_fx::LevelSeal,
            UiTransform::default(),
            Node {
                width: px(30),
                height: px(30),
                justify_content: JustifyContent::Center,
                align_items: AlignItems::Center,
                ..abs(None, Some(-2.0), None, Some(0.0))
            },
            skin.image("hud_level_seal"),
            children![(LevelLabel, UiTransform::default(), text(&fonts.title, 17.0, PAPER, "1"))],
        ));
    });
}

/// 大血条：填充在底槽里面，掉血残影画在填充后面，护盾一道细线压在上沿，数字写在右端。
fn hp_bar(fonts: &Fonts, skin: &Skin) -> impl Bundle {
    let inner = || Node {
        position_type: PositionType::Absolute,
        left: px(HP_INSET),
        right: px(HP_INSET),
        top: px(HP_INSET),
        bottom: px(HP_INSET),
        ..default()
    };
    (
        crate::hud_fx::HpBar,
        UiTransform::default(),
        Node { width: px(BAR_WIDTH), height: px(30), padding: UiRect::all(px(HP_INSET)), ..default() },
        skin.image("hud_hp_track"),
        children![
            // 掉血的残影：只画掉掉的那一截，比血条慢半拍缩回（hud_fx.rs）
            (
                inner(),
                children![(
                    crate::hud_fx::HpTrail,
                    Node {
                        position_type: PositionType::Absolute,
                        left: percent(100),
                        width: percent(0),
                        height: percent(100),
                        ..default()
                    },
                    skin.image("bar_fill_trail"),
                )],
            ),
            (
                HpFill,
                Node { width: percent(100), height: percent(100), ..default() },
                skin.image("bar_fill_hp")
            ),
            (
                inner(),
                children![(
                    ShieldFill,
                    Node { width: percent(0), height: px(5), ..default() },
                    skin.image("bar_fill_shield")
                )],
            ),
            (
                Node { position_type: PositionType::Absolute, right: px(16), top: px(5), ..default() },
                children![(HpLabel, text(&fonts.body, 15.0, PAPER, "100 / 100"))],
            ),
        ],
    )
}

/// 五行：图标加点数（图集里没有图标时写字）
fn element_chips(
    p: &mut ChildSpawnerCommands,
    c: &lantern_content::Content,
    db: Option<&AtlasDb>,
    fonts: &Fonts,
    skin: &Skin,
) {
    p.spawn(Node { column_gap: px(6), ..default() }).with_children(|row| {
        for e in Element::ALL {
            let icon = db.and_then(|db| {
                db.find(&format!("ui/icon_el_{}", ELEMENT_ICONS[e.index()])).map(|f| db.ui_image(f))
            });
            let label = if icon.is_some() { "0".to_string() } else { format!("{} 0", c.element(e).name) };
            row.spawn((
                Node {
                    padding: UiRect::new(px(6), px(10), px(2), px(2)),
                    align_items: AlignItems::Center,
                    column_gap: px(4),
                    ..default()
                },
                skin.image("chip_dark"),
            ))
            .with_children(|chip| {
                if let Some(img) = icon {
                    chip.spawn((
                        ElementIcon(e),
                        Node { width: px(22), height: px(22), ..default() },
                        img.with_color(Color::WHITE.with_alpha(0.35)),
                    ));
                }
                chip.spawn((
                    ElementChip(e),
                    text(&fonts.body, 15.0, element_color(c, e).with_alpha(0.35), &label),
                ));
            });
        }
    });
}

/// 结算的底部收益区不再透出战斗按键；模拟结束的当帧就收起，无须等状态切换。
pub(crate) fn update_control_hints(
    state: Res<State<RunState>>,
    phase: Res<SimPhase>,
    setup: Res<RunSetup>,
    profile: Option<Res<lantern_platform::Profile>>,
    mut hints: Query<&mut Node, With<ControlHints>>,
) {
    // 前两局之后不再显示底部的按键提示（试玩反馈：文字太多）
    let novice = profile.is_none_or(|p| p.runs < 2);
    let visible = novice
        && *state.get() == RunState::Playing
        && *phase == SimPhase::Play
        && !matches!(setup.mode, RunMode::Bench { .. });
    for mut node in &mut hints {
        let display = if visible { Display::Flex } else { Display::None };
        if node.display != display {
            node.display = display;
        }
    }
}

#[derive(bevy::ecs::system::SystemParam)]
pub(crate) struct HudState<'w> {
    content: Res<'w, GameContent>,
    active: Res<'w, lantern_platform::ActiveInput>,
    settings: Res<'w, lantern_platform::Settings>,
    tick: Option<Res<'w, Tick>>,
    progress: Option<Res<'w, Progress>>,
    director: Option<Res<'w, Director>>,
    enemies: Option<Res<'w, Enemies>>,
    encounters: Option<Res<'w, Encounters>>,
    lanterns: Option<Res<'w, lantern_sim::lanterns::Lanterns>>,
}

pub(crate) fn update_hud(
    s: HudState,
    player: Query<(&Health, &Player)>,
    mut texts: ParamSet<(
        Query<&mut Text, With<Clock>>,
        Query<&mut Text, With<Kills>>,
        Query<&mut Text, With<LevelLabel>>,
        Query<&mut Text, With<HpLabel>>,
        Query<(&mut Text, &mut TextColor), With<UltLabel>>,
        Query<&mut Text, With<ComboLabel>>,
        Query<&mut Text, With<BuffLabel>>,
        Query<&mut Text, With<BossName>>,
    )>,
    mut fills: ParamSet<(
        Query<&mut Node, With<XpFill>>,
        Query<&mut Node, With<HpFill>>,
        Query<&mut Node, With<ShieldFill>>,
        Query<&mut Node, With<BossFill>>,
    )>,
    mut boss_bar: Query<&mut Visibility, With<BossBar>>,
) {
    let c = &s.content.0;
    let (Some(tick), Some(progress)) = (s.tick, s.progress) else { return };
    let set = |t: &mut Text, v: String| {
        if t.0 != v {
            t.0 = v;
        }
    };
    let secs = tick.0 / u64::from(TICK_HZ);
    for mut t in &mut texts.p0() {
        set(&mut t, format!("{:02}:{:02}", secs / 60, secs % 60));
    }
    let lamps = s.lanterns.as_ref().map_or((0, 0), |l| (l.lit(), l.0.len()));
    for mut t in &mut texts.p1() {
        set(
            &mut t,
            format!(
                "击杀 {}　铜钱 {}　石灯笼 {}/{}",
                progress.kills,
                progress.gold.floor(),
                lamps.0,
                lamps.1
            ),
        );
    }
    for mut t in &mut texts.p2() {
        set(&mut t, progress.level.to_string());
    }
    let need = c.run.xp_need.at(progress.level as f32).max(1.0);
    for mut n in &mut fills.p0() {
        n.width = percent((progress.xp / need * 100.0).clamp(0.0, 100.0));
    }
    if let Ok((h, p)) = player.single() {
        for mut t in &mut texts.p3() {
            set(&mut t, format!("{} / {}", h.hp.ceil() as i32, h.max.round() as i32));
        }
        for mut n in &mut fills.p1() {
            n.width = percent((h.hp / h.max * 100.0).clamp(0.0, 100.0));
        }
        for mut n in &mut fills.p2() {
            n.width = percent(if p.shield_max > 0.0 {
                (p.shield / p.shield_max * 100.0).clamp(0.0, 100.0)
            } else {
                0.0
            });
        }
    }
    // 燃灯的进度画在头像章的刻度上（update_ult_ticks），蓄满了才写按键
    for (mut t, mut color) in &mut texts.p4() {
        let ready = progress.ult >= 1.0;
        set(
            &mut t,
            if ready {
                crate::prompts::render("燃灯 {ult}", &s.active, &s.settings)
            } else {
                String::new()
            },
        );
        color.0 = GOLD;
    }
    for mut t in &mut texts.p5() {
        set(&mut t, if progress.combo >= 10 { format!("连斩 {}", progress.combo) } else { String::new() });
    }
    if let Some(enc) = &s.encounters {
        let v = enc.buff.map_or(String::new(), |(b, t)| {
            let def = &c.events.buffs[b];
            format!("古灯 · {}　{}　{} 秒", def.name, def.desc, t.ceil() as u32)
        });
        for mut t in &mut texts.p6() {
            set(&mut t, v.clone());
        }
    }
    // 夜主血条
    let boss =
        s.director.as_ref().and_then(|d| d.boss).and_then(|h| s.enemies.as_ref()?.resolve(h).map(|i| (h, i)));
    for mut v in &mut boss_bar {
        v.set_if_neq(if boss.is_some() { Visibility::Inherited } else { Visibility::Hidden });
    }
    if let (Some((_, i)), Some(en)) = (boss, &s.enemies) {
        let def = &c.enemies[en.kind[i] as usize];
        if def.rank == Rank::Boss {
            for mut t in &mut texts.p7() {
                // 标题字体没有“·”
                set(&mut t, def.name.replace('·', "•"));
            }
            for mut n in &mut fills.p3() {
                n.width = percent((en.hp[i] / en.max_hp[i] * 100.0).clamp(0.0, 100.0));
            }
        }
    }
}

/// 燃灯刻度：到了第 k 格的进度就点亮，蓄满整圈换成满格；只换图，不碰颜色（蓄满时的呼吸在 hud_fx.rs）。
pub(crate) fn update_ult_ticks(
    skin: Res<Skin>,
    progress: Option<Res<Progress>>,
    mut ticks: Query<(&UltTick, &mut ImageNode)>,
) {
    let Some(progress) = progress else { return };
    for (tick, mut img) in &mut ticks {
        let name = tick_skin(tick.0, progress.ult);
        let want = skin.image(name);
        if img.image != want.image {
            img.image = want.image;
            img.image_mode = want.image_mode;
        }
    }
}

fn tick_skin(k: usize, ult: f32) -> &'static str {
    if ult >= 1.0 {
        "hud_ult_tick_full"
    } else if ult * TICKS as f32 >= (k + 1) as f32 {
        "hud_ult_tick_on"
    } else {
        "hud_ult_tick"
    }
}

/// 五行共鸣的点数和阶数：没有点数的淡，有点数没到一阶的半亮，到了一阶全亮。
pub(crate) fn update_chips(
    content: Res<GameContent>,
    build: Option<Res<Build>>,
    mut chips: Query<(&ElementChip, &mut Text, &mut TextColor)>,
    mut icons: Query<(&ElementIcon, &mut ImageNode)>,
) {
    let Some(build) = build else { return };
    if !build.is_changed() {
        return;
    }
    let c = &content.0;
    let alpha = |e: Element| {
        let (pts, tier) = (build.points[e.index()], build.tiers[e.index()]);
        if pts == 0 {
            0.35
        } else if tier == 0 {
            0.7
        } else {
            1.0
        }
    };
    let iconed: Vec<Element> = icons.iter().map(|(i, _)| i.0).collect();
    for (chip, mut t, mut color) in &mut chips {
        let i = chip.0.index();
        let marks = TIER_MARKS[(build.tiers[i] as usize).min(TIER_MARKS.len() - 1)];
        let pts = build.points[i];
        // 有图标的只写点数
        t.0 = if iconed.contains(&chip.0) {
            format!("{pts}{marks}")
        } else {
            format!("{} {pts}{marks}", c.element(chip.0).name)
        };
        color.0 = element_color(c, chip.0).with_alpha(alpha(chip.0));
    }
    for (icon, mut img) in &mut icons {
        img.color = Color::WHITE.with_alpha(alpha(icon.0));
    }
}

/// 法器与心法的格子：构筑变化时重画。
pub(crate) fn update_slots(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    db: Res<AtlasDb>,
    skin: Res<Skin>,
    arsenal: Option<Res<Arsenal>>,
    build: Option<Res<Build>>,
    slots: Single<Entity, With<Slots>>,
    mut shown: Local<Vec<(u8, usize, u32, lantern_sim::weapons::Form)>>,
) {
    let (Some(arsenal), Some(build)) = (arsenal, build) else { return };
    let c = &content.0;
    // 空格子画到上限：法器栏会被灯坠改，合璧可能腾出一格
    let free_weapons = lantern_sim::build::weapon_slots(c, &build)
        .saturating_sub(lantern_sim::build::occupied_slots(c, &arsenal, &build))
        as usize;
    let free_passives = (c.run.choices.slots as usize).saturating_sub(build.passives.len());
    let now: Vec<(u8, usize, u32, lantern_sim::weapons::Form)> = arsenal
        .0
        .iter()
        .map(|w| (0, w.def, w.level, w.form))
        .chain(build.passives.iter().map(|p| (1, p.def, p.level, lantern_sim::weapons::Form::Base)))
        .chain([(2, free_weapons, free_passives as u32, lantern_sim::weapons::Form::Base)])
        .collect();
    if *shown == now {
        return;
    }
    *shown = now;
    commands.entity(*slots).despawn_related::<Children>();
    commands.entity(*slots).with_children(|p| {
        p.spawn(Node { column_gap: px(8), ..default() }).with_children(|row| {
            for w in &arsenal.0 {
                let def = &c.weapons[w.def];
                let color = element_color(c, def.element);
                let name = if w.transformed() {
                    format!("ui/icon_{}_evo", def.id)
                } else {
                    format!("ui/icon_{}", def.id)
                };
                row.spawn(Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    ..default()
                })
                .with_children(|cell| {
                    cell.spawn((
                        Node {
                            width: px(SLOT_L),
                            height: px(SLOT_L),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            ..default()
                        },
                        skin.image(if w.transformed() { "slot_l_evo" } else { "slot_l" }),
                    ))
                    .with_children(|slot| {
                        spawn_icon(slot, &db, &fonts, Some(&name), &def.icon, color, SLOT_L * 0.78)
                    });
                    let lv = match w.form {
                        lantern_sim::weapons::Form::Base => w.level.to_string(),
                        // 异化与合璧关着时只有正统进化一种，照旧画星
                        lantern_sim::weapons::Form::Evolved if !c.run.transformations => "★".into(),
                        lantern_sim::weapons::Form::Evolved => "正".into(),
                        lantern_sim::weapons::Form::Mutated => "异".into(),
                        lantern_sim::weapons::Form::Fused(f) => {
                            let names: Vec<_> = c.fusions[f]
                                .weapons
                                .iter()
                                .map(|id| {
                                    c.element(c.weapons[c.weapon_index(id).expect("合璧材料")].element)
                                        .name
                                        .chars()
                                        .next()
                                        .unwrap()
                                })
                                .collect();
                            format!("合·{}{}", names[0], names[1])
                        }
                    };
                    let badge =
                        if w.form == lantern_sim::weapons::Form::Mutated { hex("#CF8CDB") } else { GOLD };
                    cell.spawn(text(&fonts.body, 13.0, if w.transformed() { badge } else { PAPER }, &lv));
                });
            }
            for _ in 0..free_weapons {
                row.spawn((
                    Node { width: px(SLOT_L), height: px(SLOT_L), ..default() },
                    skin.image("slot_l_empty"),
                ));
            }
        });
        p.spawn(Node { column_gap: px(8), ..default() }).with_children(|row| {
            for s in &build.passives {
                let def = &c.passives[s.def];
                let color = passive_color(c, def.element);
                let name = format!("ui/icon_{}", def.id);
                let glyph: String = def.name.chars().take(1).collect();
                row.spawn(Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    ..default()
                })
                .with_children(|cell| {
                    cell.spawn((
                        Node {
                            width: px(SLOT_S),
                            height: px(SLOT_S),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            ..default()
                        },
                        skin.image("slot_s"),
                    ))
                    .with_children(|slot| {
                        spawn_icon(slot, &db, &fonts, Some(&name), &glyph, color, SLOT_S * 0.78)
                    });
                    cell.spawn(text(&fonts.body, 12.0, PAPER, &format!("{}", s.level)));
                });
            }
            for _ in 0..free_passives {
                row.spawn((
                    Node { width: px(SLOT_S), height: px(SLOT_S), ..default() },
                    skin.image("slot_s_empty"),
                ));
            }
        });
    });
}

#[cfg(test)]
mod hint_tests {
    use super::*;

    /// 操作提示只在正常游玩时显示（按键文字由 prompts 按设备填）。
    #[test]
    fn hints_show_only_while_playing() {
        let mut app = App::new();
        app.insert_resource(State::new(RunState::Playing))
            .insert_resource(SimPhase::Play)
            .insert_resource(RunSetup::new(1, RunMode::Normal))
            .add_systems(Update, update_control_hints);
        let hints = app.world_mut().spawn((ControlHints, Node::default())).id();
        let shown = |app: &App| app.world().get::<Node>(hints).unwrap().display == Display::Flex;
        app.update();
        assert!(shown(&app));
        // 模拟先结束、界面状态下一帧才切换；这一帧也不能残留提示。
        app.insert_resource(SimPhase::Over);
        app.update();
        assert!(!shown(&app));
        for state in [RunState::Over, RunState::Paused] {
            app.insert_resource(SimPhase::Play);
            app.insert_resource(State::new(state));
            app.update();
            assert!(!shown(&app));
        }
        app.insert_resource(State::new(RunState::Playing));
        app.insert_resource(SimPhase::LevelUp);
        app.update();
        assert!(!shown(&app));
        app.insert_resource(SimPhase::Play);
        app.update();
        assert!(shown(&app));
        app.insert_resource(RunSetup::new(1, RunMode::Bench { enemies: 250 }));
        app.update();
        assert!(!shown(&app));
    }
}

#[cfg(test)]
mod chip_tests {
    use super::*;

    /// 五行计数：有图标的只写点数，极境不越界，图标跟着点数变淡变亮。
    #[test]
    fn element_chips_show_points_and_every_tier_including_the_peak() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
        let content = lantern_content::Content::load(&path).unwrap();
        let mut app = App::new();
        app.insert_resource(GameContent(content.into()))
            .insert_resource(Build { points: [12, 3, 0, 0, 0], tiers: [4, 0, 0, 0, 0], ..default() })
            .add_systems(Update, update_chips);
        let metal =
            app.world_mut().spawn((ElementChip(Element::Metal), Text::default(), TextColor::default())).id();
        app.world_mut().spawn((ElementIcon(Element::Metal), ImageNode::default()));
        let wood =
            app.world_mut().spawn((ElementChip(Element::Wood), Text::default(), TextColor::default())).id();
        let water = app.world_mut().spawn((ElementIcon(Element::Water), ImageNode::default())).id();
        app.update();
        assert_eq!(app.world().get::<Text>(metal).unwrap().0, "12·极");
        // 没有图标的照旧写字
        assert!(app.world().get::<Text>(wood).unwrap().0.ends_with(" 3"));
        assert_eq!(app.world().get::<ImageNode>(water).unwrap().color.alpha(), 0.35);
    }
}

#[cfg(test)]
mod tick_tests {
    use super::*;

    /// 燃灯刻度：到第 k 格的进度才亮，差一点不亮；蓄满整圈换满格。
    #[test]
    fn ticks_light_one_by_one_and_all_turn_full_when_ready() {
        assert_eq!(tick_skin(0, 0.0), "hud_ult_tick");
        assert_eq!(tick_skin(0, 1.0 / 12.0), "hud_ult_tick_on");
        assert_eq!(tick_skin(1, 1.0 / 12.0), "hud_ult_tick");
        assert_eq!(tick_skin(10, 0.99), "hud_ult_tick_on");
        assert_eq!(tick_skin(11, 0.99), "hud_ult_tick");
        assert!((0..TICKS).all(|k| tick_skin(k, 1.0) == "hud_ult_tick_full"));
    }
}
