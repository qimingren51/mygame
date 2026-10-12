//! 游戏中的信息栏：用时、击杀、等级与经验条、生命与护盾、燃灯、法器与心法、五行共鸣、
//! 夜主血条、连斩、古灯增益、操作提示。

use bevy::prelude::*;

use lantern_content::{Element, Rank};
use lantern_core::step::TICK_HZ;
use lantern_sim::encounters::Encounters;
use lantern_sim::{
    AppState, Arsenal, Build, Director, Enemies, GameContent, Health, Player, Progress, RunSetup, Tick,
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

const BAR_BG: Color = Color::srgba(0.0, 0.0, 0.0, 0.45);
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
) {
    let c = &content.0;
    let run = DespawnOnExit(AppState::Run);
    // 顶端经验条
    commands.spawn((
        run.clone(),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            top: px(0),
            height: px(7),
            ..default()
        },
        BackgroundColor(BAR_BG),
        children![(
            XpFill,
            Node { width: percent(0), height: percent(100), ..default() },
            skin.image("bar_fill_xp")
        )],
    ));
    // 左上：用时、击杀、种子、夜签
    let omen = setup
        .omen
        .as_ref()
        .and_then(|o| c.omen_index(&o.id))
        .map_or(String::new(), |i| format!("　夜签 · {}", c.omens[i].name));
    commands.spawn((
        run.clone(),
        Node { flex_direction: FlexDirection::Column, ..abs(Some(20.0), None, Some(14.0), None) },
        children![
            (Clock, text(&fonts.body, 28.0, PAPER, "00:00")),
            (Kills, text(&fonts.body, 18.0, PAPER, "击杀 0")),
            text(&fonts.body, 14.0, DIM, &format!("种子 {}{omen}", setup.seed)),
            (BuffLabel, text(&fonts.body, 16.0, GOLD, "")),
        ],
    ));
    // 右上：等级、法器与心法、五行共鸣
    commands
        .spawn((
            run.clone(),
            Node {
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::End,
                row_gap: px(6),
                ..abs(None, Some(20.0), Some(14.0), None)
            },
        ))
        .with_children(|p| {
            p.spawn((LevelLabel, text(&fonts.body, 22.0, PAPER, "等级 1")));
            p.spawn((
                Slots,
                Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::End,
                    row_gap: px(4),
                    ..default()
                },
            ));
            p.spawn(Node { column_gap: px(6), ..default() }).with_children(|row| {
                for e in Element::ALL {
                    row.spawn((
                        Node { padding: UiRect::axes(px(10), px(3)), ..default() },
                        skin.image("chip_dark"),
                    ))
                    .with_child((
                        ElementChip(e),
                        text(
                            &fonts.body,
                            15.0,
                            element_color(c, e).with_alpha(0.35),
                            &format!("{} 0", c.element(e).name),
                        ),
                    ));
                }
            });
        });
    // 顶部中间：夜主血条
    commands.spawn((
        run.clone(),
        BossBar,
        Visibility::Hidden,
        Node {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            row_gap: px(4),
            ..abs(Some(0.0), Some(0.0), Some(16.0), None)
        },
        children![
            (BossName, text(&fonts.title, 26.0, hex("#FF6B5A"), "")),
            bar(&skin, 560.0, 18.0, BossFill, "bar_fill_boss"),
        ],
    ));
    // 右侧：连斩
    commands.spawn((
        run.clone(),
        abs(None, Some(28.0), Some(260.0), None),
        children![(ComboLabel, text(&fonts.title, 36.0, GOLD, ""))],
    ));
    // 底部中间：生命、护盾、燃灯
    commands.spawn((
        run.clone(),
        Node {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            row_gap: px(4),
            ..abs(Some(0.0), Some(0.0), None, Some(40.0))
        },
        children![
            (HpLabel, text(&fonts.body, 14.0, DIM, "生命 100 / 100")),
            (
                Node { width: px(280), height: px(18), padding: UiRect::all(px(2)), ..default() },
                skin.image("bar_track"),
                children![
                    (
                        HpFill,
                        Node { width: percent(100), height: percent(100), ..default() },
                        skin.image("bar_fill_hp")
                    ),
                    (
                        ShieldFill,
                        Node {
                            position_type: PositionType::Absolute,
                            left: px(2),
                            top: px(1),
                            width: percent(0),
                            height: px(6),
                            ..default()
                        },
                        skin.image("bar_fill_shield")
                    ),
                ],
            ),
            bar(&skin, 200.0, 12.0, UltFill, "bar_fill_xp"),
            (UltLabel, text(&fonts.body, 13.0, DIM, "燃灯")),
        ],
    ));
    // 左下：操作提示
    commands.spawn((
        run,
        abs(Some(20.0), None, None, Some(14.0)),
        children![text(
            &fonts.body,
            16.0,
            DIM,
            "WASD / 方向键 / 左摇杆　移动　　空格 / 手柄 A　闪避　　E / 手柄 Y　燃灯　　Esc　暂停　　F3　性能"
        )],
    ));
}

#[derive(bevy::ecs::system::SystemParam)]
pub(crate) struct HudState<'w> {
    content: Res<'w, GameContent>,
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
        Query<&mut Node, With<UltFill>>,
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
                "击杀 {}　金币 {}　石灯笼 {}/{}",
                progress.kills,
                progress.gold.floor(),
                lamps.0,
                lamps.1
            ),
        );
    }
    for mut t in &mut texts.p2() {
        set(&mut t, format!("等级 {}", progress.level));
    }
    let need = c.run.xp_need.at(progress.level as f32).max(1.0);
    for mut n in &mut fills.p0() {
        n.width = percent((progress.xp / need * 100.0).clamp(0.0, 100.0));
    }
    if let Ok((h, p)) = player.single() {
        for mut t in &mut texts.p3() {
            set(&mut t, format!("生命 {} / {}", h.hp.ceil() as i32, h.max.round() as i32));
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
    for mut n in &mut fills.p3() {
        n.width = percent(progress.ult * 100.0);
    }
    for (mut t, mut color) in &mut texts.p4() {
        let ready = progress.ult >= 1.0;
        set(
            &mut t,
            if ready {
                "燃灯　E / 手柄 Y".into()
            } else {
                format!("燃灯 {}%", (progress.ult * 100.0) as u32)
            },
        );
        color.0 = if ready { GOLD } else { DIM };
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
            for mut n in &mut fills.p4() {
                n.width = percent((en.hp[i] / en.max_hp[i] * 100.0).clamp(0.0, 100.0));
            }
        }
    }
}

/// 五行共鸣的点数和阶数。
pub(crate) fn update_chips(
    content: Res<GameContent>,
    build: Option<Res<Build>>,
    mut chips: Query<(&ElementChip, &mut Text, &mut TextColor)>,
) {
    let Some(build) = build else { return };
    if !build.is_changed() {
        return;
    }
    let c = &content.0;
    for (chip, mut t, mut color) in &mut chips {
        let i = chip.0.index();
        let pts = build.points[i];
        let tier = build.tiers[i];
        let name = &c.element(chip.0).name;
        let stars = ["", "·一", "·二", "·三"][tier as usize];
        t.0 = format!("{name} {pts}{stars}");
        color.0 = element_color(c, chip.0).with_alpha(if pts == 0 {
            0.35
        } else if tier == 0 {
            0.7
        } else {
            1.0
        });
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
    mut shown: Local<Vec<(u8, usize, u32, bool)>>,
) {
    let (Some(arsenal), Some(build)) = (arsenal, build) else { return };
    let c = &content.0;
    let now: Vec<(u8, usize, u32, bool)> = arsenal
        .0
        .iter()
        .map(|w| (0, w.def, w.level, w.evolved))
        .chain(build.passives.iter().map(|p| (1, p.def, p.level, false)))
        .collect();
    if *shown == now {
        return;
    }
    *shown = now;
    commands.entity(*slots).despawn_related::<Children>();
    commands.entity(*slots).with_children(|p| {
        p.spawn(Node { column_gap: px(4), ..default() }).with_children(|row| {
            for w in &arsenal.0 {
                let def = &c.weapons[w.def];
                let color = element_color(c, def.element);
                let name =
                    if w.evolved { format!("ui/icon_{}_evo", def.id) } else { format!("ui/icon_{}", def.id) };
                row.spawn(Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    ..default()
                })
                .with_children(|cell| {
                    cell.spawn((
                        Node {
                            width: px(48),
                            height: px(48),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            ..default()
                        },
                        skin.image(if w.evolved { "slot_l_evo" } else { "slot_l" }),
                    ))
                    .with_children(|slot| spawn_icon(slot, &db, &fonts, Some(&name), &def.icon, color, 38.0));
                    let lv = if w.evolved { "★".to_string() } else { format!("{}", w.level) };
                    cell.spawn(text(&fonts.body, 12.0, if w.evolved { GOLD } else { PAPER }, &lv));
                });
            }
        });
        p.spawn(Node { column_gap: px(4), ..default() }).with_children(|row| {
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
                            width: px(34),
                            height: px(34),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            ..default()
                        },
                        skin.image("slot_s"),
                    ))
                    .with_children(|slot| spawn_icon(slot, &db, &fonts, Some(&name), &glyph, color, 26.0));
                    cell.spawn(text(&fonts.body, 11.0, PAPER, &format!("{}", s.level)));
                });
            }
        });
    });
}
