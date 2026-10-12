//! 屏幕上方的提示：精英、妖潮、夜主、共鸣、相生、奇遇、连斩……（移植自网页版 ui/toasts.ts）

use bevy::prelude::*;

use lantern_content::Rank;
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
    app.add_systems(OnEnter(AppState::Run), spawn_stack)
        .add_systems(Update, (read_events, fade).chain().run_if(in_state(AppState::Run)));
}

fn spawn_stack(mut commands: Commands) {
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
) {
    let c = &content.0;
    let mut count = toasts.iter().count();
    let mut oldest: Vec<(Entity, f32)> = toasts.iter().map(|(e, t)| (e, t.t)).collect();
    oldest.sort_by(|a, b| b.1.total_cmp(&a.1));
    for ev in &outbox.0 {
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
            SimEvent::BossPhase { phase: 2 } => {
                msg("九尾分出幻身", "幻身没有影子；照见圈能让它们散去", hex("#D8C8FF"), true)
            }
            SimEvent::BossPhase { phase: 3 } => msg("九尾扫", "躲开地上的扇形预警", hex("#FF6B5A"), true),
            SimEvent::BossEnraged => msg("夜主狂暴", "攻击变得更密", hex("#FF3B30"), false),
            SimEvent::BossArrived { kind } => msg(
                format!("夜主降临 · {}", c.enemies[kind as usize].name),
                "击败它，迎来天明",
                hex("#FF6B5A"),
                true,
            ),
            SimEvent::BossDefeated { .. } => msg("夜主伏诛", "天将破晓", hex("#FFF1C2"), true),
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
                if first {
                    msg(format!("反应 · {}", r.name), r.desc.clone(), color, true)
                } else {
                    msg(r.name.clone(), "", color, false)
                }
            }
            SimEvent::Sheng { index } => {
                let s = &c.elements.sheng[index as usize];
                msg(format!("相生 · {}", s.name), s.desc.clone(), element_color(c, s.to), false)
            }
            SimEvent::Taiji => msg(c.elements.taiji.name.clone(), c.elements.taiji.desc.clone(), PAPER, true),
            SimEvent::Combo { count } => msg(format!("连斩 {count}"), "", hex("#FFD98A"), count >= 500),
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
