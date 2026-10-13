//! 屏幕上方的提示：精英、妖潮、夜主、共鸣、相生、奇遇、连斩……（移植自网页版 ui/toasts.ts）

use bevy::prelude::*;

use lantern_content::{BossLines, Content, PlanEvent, Rank};
use lantern_sim::{AppState, GameContent, SimEvent, SimOutbox};

use crate::describe::{element_color, hex};
use crate::skin::Skin;
use crate::{DIM, Fonts, PAPER, text};

const MAX: usize = 4;

#[derive(Component)]
pub(crate) struct ToastStack;

#[derive(Component)]
pub(crate) struct Toast {
    t: f32,
    life: f32,
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Muted>()
        .add_systems(OnEnter(AppState::Run), spawn_stack)
        .add_systems(Update, (read_events, fade).chain().run_if(in_state(AppState::Run)));
}

/// 天明之后不再出提示。
#[derive(Resource, Default)]
struct Muted(bool);

fn spawn_stack(mut commands: Commands) {
    commands.insert_resource(Muted(false));
    commands.spawn((
        ToastStack,
        DespawnOnExit(AppState::Run),
        Node {
            position_type: PositionType::Absolute,
            left: px(0),
            right: px(0),
            top: px(64),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            row_gap: px(6),
            ..default()
        },
    ));
}

struct Msg {
    title: String,
    body: String,
    color: Color,
    big: bool,
}

/// 这一夜夜主（时间表里的那一个）的一句台词。
fn boss_line(c: &Content, pick: impl Fn(&BossLines) -> &String) -> Option<&str> {
    let id = c.run.schedule.iter().find_map(|s| match &s.event {
        PlanEvent::Boss { enemy, .. } => Some(enemy),
        _ => None,
    })?;
    let lines = c.enemies[c.enemy_index(id)?].boss.as_ref()?.lines.as_ref()?;
    Some(pick(lines).as_str())
}

fn msg(title: impl Into<String>, body: impl Into<String>, color: Color, big: bool) -> Option<Msg> {
    Some(Msg { title: title.into(), body: body.into(), color, big })
}

fn read_events(
    mut commands: Commands,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    outbox: Res<SimOutbox>,
    stack: Single<Entity, With<ToastStack>>,
    toasts: Query<(Entity, &Toast)>,
    mut muted: ResMut<Muted>,
) {
    let c = &content.0;
    let mut count = toasts.iter().count();
    let mut oldest: Vec<(Entity, f32)> = toasts.iter().map(|(e, t)| (e, t.t)).collect();
    oldest.sort_by(|a, b| b.1.total_cmp(&a.1));
    for ev in &outbox.0 {
        // 夜主伏诛之后让给天明的演出，清掉现有的提示，也不再出新的（无尽夜不天明，照常提示）
        if matches!(ev, SimEvent::BossDefeated { dawn: true, .. }) {
            for (e, _) in &toasts {
                commands.entity(e).despawn();
            }
            muted.0 = true;
        }
        if muted.0 {
            continue;
        }
        let m = match *ev {
            SimEvent::Elite { kind, count } => {
                let e = &c.enemies[kind as usize];
                let title =
                    e.title.as_deref().unwrap_or(if e.rank == Rank::Boss { "夜主" } else { "精英" });
                let body = if count > 1 { format!("{count} 只出现了") } else { "出现了".into() };
                msg(format!("{title} · {}", e.name), body, hex(&e.eye), false)
            }
            SimEvent::Surge => msg("妖潮来袭", "妖物大量涌来，撑过去", hex("#B07CF0"), true),
            SimEvent::EncircleWarn { .. } => msg("合围", "妖物从四面合拢，找缺口突围", hex("#FF6B5A"), true),
            SimEvent::LanternLit { lit, all, .. } => {
                if all {
                    msg("灯阵完整", "五盏石灯笼全部点亮：夜主少两成生命", hex("#FFD98A"), true)
                } else {
                    msg(format!("点亮石灯笼 {lit} / 5"), "光区里的妖物减速、易伤", hex("#FFD98A"), false)
                }
            }
            // 换阶段：夜主的台词，下面一行写怎么打
            SimEvent::BossPhase { phase: 2 } => msg(
                boss_line(c, |l| &l.phase2).unwrap_or("九尾分出幻身"),
                "分出幻身：幻身没有影子，照见圈能让它们散去",
                hex("#D8C8FF"),
                true,
            ),
            SimEvent::BossPhase { phase: 3 } => msg(
                boss_line(c, |l| &l.phase3).unwrap_or("九尾扫"),
                "九尾扫：躲开地上的扇形预警",
                hex("#FF6B5A"),
                true,
            ),
            SimEvent::BossEnraged => msg("夜主狂暴", "攻击变得更密", hex("#FF3B30"), false),
            SimEvent::BossDefeated { dawn: false, .. } => msg(
                boss_line(c, |l| &l.retreat).unwrap_or("夜主退去"),
                "夜主退去：梦太深，光透不上来，下一次妖潮过后它还会回来",
                hex("#FFD98A"),
                true,
            ),
            // 夜主登场、伏诛有专门的演出（moments.rs）
            SimEvent::Resonance { element, tier } => {
                let e = c.element(element);
                let name = ["一阶", "二阶", "三阶", "极境"].get(tier as usize - 1).copied().unwrap_or("");
                let desc = e.tiers.get(tier as usize - 1).map(|t| t.desc.as_str()).unwrap_or("");
                msg(
                    format!("{} · {} 共鸣{name}", e.name, e.resonance),
                    desc,
                    element_color(c, element),
                    tier >= 3,
                )
            }
            // 第一次发生：大字盖章并写出说明；之后同种反应每 2 秒最多提示一次
            SimEvent::Reaction { kind, first, label, .. } if label => {
                let r = &c.elements.reactions[kind as usize];
                let color = element_color(c, r.b);
                // 之后同种反应的名字在发生的地方飘出来（画面层），不占提示栏
                if first { msg(format!("反应 · {}", r.name), r.desc.clone(), color, true) } else { None }
            }
            SimEvent::Sheng { index } => {
                let s = &c.elements.sheng[index as usize];
                msg(format!("相生 · {}", s.name), s.desc.clone(), element_color(c, s.to), false)
            }
            SimEvent::Taiji => msg(c.elements.taiji.name.clone(), c.elements.taiji.desc.clone(), PAPER, true),
            // 连斩里程碑在屏幕左边竖着题字（moments.rs）
            SimEvent::UltReady => msg("燃灯已满", "E / 手柄 Y　释放", hex("#FFD98A"), false),
            SimEvent::Encounter { kind, .. } => {
                let k = &c.events.kinds[kind as usize];
                msg(format!("奇遇 · {}", k.name), k.hint.clone(), hex(&k.color), false)
            }
            SimEvent::CritterFled { .. } => msg("金蟾遁走了", "下次快一点", DIM, false),
            SimEvent::CritterLooted { .. } => msg("金蟾散财", "魂火与灯油", hex("#FFD98A"), false),
            SimEvent::Buff { index } => {
                let b = &c.events.buffs[index as usize];
                let secs = c
                    .events
                    .kinds
                    .iter()
                    .find_map(|k| match k.kind {
                        lantern_content::EventKind::Shrine { duration, .. } => Some(duration),
                        _ => None,
                    })
                    .unwrap_or(30.0);
                msg(format!("古灯 · {}", b.name), format!("{}，持续 {secs} 秒", b.desc), hex(&b.color), true)
            }
            SimEvent::Sacrifice { amount } => {
                msg("血祭", format!("失去 {} 生命，换一个宝箱", amount.round()), hex("#FF6B5A"), false)
            }
            SimEvent::LastStand { .. } => msg("回光", "灯焰一暗又亮，震开了周围的妖物", hex("#FFD98A"), true),
            SimEvent::Revived { .. } => msg("九转金丹", "金丹化开，长明火又亮了起来", hex("#FFD98A"), true),
            SimEvent::CharmTaken { index } => {
                let d = &c.charms[index as usize];
                msg(format!("灯坠 · {}", d.name), d.good.clone(), hex("#B07CF0"), false)
            }
            SimEvent::ShieldBroken => None,
            _ => None,
        };
        let Some(m) = m else { continue };
        // 太多时顶掉最早的
        if count >= MAX
            && let Some((e, _)) = oldest.first().copied()
        {
            commands.entity(e).despawn();
            oldest.remove(0);
            count -= 1;
        }
        let life = if m.big { 3.6 } else { 2.6 };
        let toast = commands
            .spawn((
                Toast { t: 0.0, life },
                Node {
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    padding: UiRect::axes(px(48), px(if m.big { 12.0 } else { 8.0 })),
                    ..default()
                },
                skin.image(if m.big { "toast_big" } else { "toast" }),
            ))
            .with_children(|t| {
                t.spawn(text(&fonts.title, if m.big { 40.0 } else { 28.0 }, m.color, &m.title));
                if !m.body.is_empty() {
                    t.spawn(text(&fonts.body, 15.0, PAPER, &m.body));
                }
            })
            .id();
        commands.entity(*stack).add_child(toast);
        count += 1;
    }
}

fn fade(
    mut commands: Commands,
    time: Res<Time>,
    mut toasts: Query<(Entity, &mut Toast, &mut ImageNode, &Children)>,
    mut texts: Query<&mut TextColor>,
) {
    for (e, mut t, mut bg, children) in &mut toasts {
        t.t += time.delta_secs();
        if t.t >= t.life {
            commands.entity(e).despawn();
            continue;
        }
        let a = ((t.life - t.t) / 0.5).min(1.0);
        bg.color.set_alpha(a);
        for c in children {
            if let Ok(mut tc) = texts.get_mut(*c) {
                tc.0.set_alpha(a);
            }
        }
    }
}
