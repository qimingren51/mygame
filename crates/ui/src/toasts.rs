//! 屏幕上方的提示：精英、妖潮、夜主、共鸣、相生、奇遇、连斩……（移植自网页版 ui/toasts.ts）

use bevy::prelude::*;

use lantern_content::Rank;
use lantern_sim::{AppState, GameContent, SimEvent, SimOutbox};

use crate::describe::{element_color, hex};
use crate::skin::Skin;
use crate::{DIM, Fonts, PAPER, text};

/// 同时最多几条（试玩反馈：文字太多）
const MAX: usize = 2;

#[derive(Component)]
pub(crate) struct ToastStack;

#[derive(Component)]
pub(crate) struct Toast {
    t: f32,
    life: f32,
    /// “燃灯已满”：燃灯放出去就撤掉，不挂到超时
    ult_ready: bool,
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

/// 有短句用短句（docs/LORE-TEXT.md 第 6 节），没写就用说明全文。
fn short_or<'a>(short: &'a str, desc: &'a str) -> &'a str {
    if short.is_empty() { desc } else { short }
}

/// 只讲一次的说明：讲过以后提示条只出标题。
fn tip(ev: &SimEvent) -> Option<&'static str> {
    Some(match ev {
        SimEvent::Surge => "surge",
        SimEvent::NightDeeper { .. } => "night_deeper",
        SimEvent::EncircleWarn { .. } => "encircle",
        SimEvent::LanternLit { all: false, .. } => "lantern",
        SimEvent::LanternLit { all: true, .. } => "lantern_all",
        SimEvent::BossPhase { phase: 2 } => "illusions",
        SimEvent::BossPhase { phase: 3 } => "sweep",
        SimEvent::BossEnraged => "enraged",
        _ => return None,
    })
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
    mut profile: ResMut<lantern_platform::Profile>,
    replay: Option<Res<lantern_sim::ReplayPlayback>>,
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
        if matches!(ev, SimEvent::Ult) {
            for (e, t) in &toasts {
                if t.ult_ready && oldest.iter().any(|&(o, _)| o == e) {
                    commands.entity(e).despawn();
                    oldest.retain(|&(o, _)| o != e);
                    count -= 1;
                }
            }
        }
        let m = match *ev {
            SimEvent::Elite { kind, count } => {
                let e = &c.enemies[kind as usize];
                let title =
                    e.title.as_deref().unwrap_or(if e.rank == Rank::Boss { "夜主" } else { "精英" });
                let body = if count > 1 { format!("{count} 只出现了") } else { "出现了".into() };
                msg(format!("{title} · {}", e.name), body, hex(&e.eye), false)
            }
            SimEvent::Surge => msg("妖潮来袭", "撑过去", hex("#B07CF0"), true),
            // 无尽夜每 5 分钟深一层（docs/BALANCE.md 第 4.7 节）
            SimEvent::NightDeeper { layer } => {
                msg(format!("夜深 · 第 {layer} 层"), "妖物更硬更快", hex("#7C6CF0"), true)
            }
            SimEvent::EncircleWarn { .. } => msg("合围", "找缺口突围", hex("#FF6B5A"), true),
            SimEvent::LanternLit { lit, all, .. } => {
                if all {
                    msg("灯阵完整", "夜主生命 -20%", hex("#FFD98A"), true)
                } else {
                    msg(format!("点亮石灯笼 {lit} / 5"), "光里妖物减速易伤", hex("#FFD98A"), false)
                }
            }
            // 换阶段：标题写新招式，下面一行写怎么打；夜主的台词由 moments.rs 在画面下方写出来
            SimEvent::BossPhase { phase: 2 } => msg("分出幻身", "幻身无影，照见即散", hex("#D8C8FF"), true),
            SimEvent::BossPhase { phase: 3 } => msg("九尾扫", "躲开扇形预警", hex("#FF6B5A"), true),
            SimEvent::BossEnraged => msg("夜主狂暴", "攻击更密", hex("#FF3B30"), false),
            // 退场那句台词写在画面下方（moments.rs），提示条只写结果
            SimEvent::BossDefeated { dawn: false, .. } => {
                msg("夜主退去", "妖潮过后再来", hex("#FFD98A"), true)
            }
            // 夜主登场、伏诛有专门的演出（moments.rs）
            SimEvent::Resonance { element, tier } => {
                let e = c.element(element);
                let name = ["一阶", "二阶", "三阶", "极境"].get(tier as usize - 1).copied().unwrap_or("");
                let desc = e.tiers.get(tier as usize - 1).map(|t| short_or(&t.short, &t.desc)).unwrap_or("");
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
                if first {
                    msg(format!("反应 · {}", r.name), short_or(&r.short, &r.desc), color, true)
                } else {
                    None
                }
            }
            SimEvent::Sheng { index } => {
                let s = &c.elements.sheng[index as usize];
                msg(format!("相生 · {}", s.name), short_or(&s.short, &s.desc), element_color(c, s.to), false)
            }
            SimEvent::Taiji => msg(c.elements.taiji.name.clone(), "每 30 秒轮转五行", PAPER, true),
            // 连斩里程碑在屏幕左边竖着题字（moments.rs）
            SimEvent::UltReady => msg("燃灯已满", "{ult} 释放", hex("#FFD98A"), false),
            SimEvent::Encounter { kind, .. } => {
                let k = &c.events.kinds[kind as usize];
                msg(format!("奇遇 · {}", k.name), k.hint.clone(), hex(&k.color), false)
            }
            SimEvent::CritterFled { .. } => msg("金蟾遁走了", "下次快一点", DIM, false),
            SimEvent::CritterLooted { .. } => msg("金蟾散财", "魂火与铜钱", hex("#FFD98A"), false),
            // 古灯：只写增益，不写秒数
            SimEvent::Buff { index } => {
                let b = &c.events.buffs[index as usize];
                msg(format!("古灯 · {}", b.name), b.desc.clone(), hex(&b.color), true)
            }
            SimEvent::Sacrifice { amount } => {
                msg("血祭", format!("献血 {}，换宝箱", amount.round()), hex("#FF6B5A"), false)
            }
            SimEvent::LastStand { .. } => msg("回光", "灯焰一暗又亮", hex("#FFD98A"), true),
            SimEvent::Revived { .. } => msg("九转金丹", "长明火又亮了", hex("#FFD98A"), true),
            SimEvent::CharmTaken { index } => {
                let d = &c.charms[index as usize];
                msg(format!("灯坠 · {}", d.name), d.good.clone(), hex("#B07CF0"), false)
            }
            SimEvent::ShieldBroken => None,
            _ => None,
        };
        let Some(mut m) = m else { continue };
        // 讲过一次的说明以后只出标题（存档记住）；看回放不算讲过
        if let Some(key) = tip(ev) {
            if profile.tips.contains(key) {
                m.body.clear();
            } else if replay.is_none() {
                profile.tips.insert(key.into());
                if let Err(e) = profile.save() {
                    warn!("保存提示进度失败：{e}");
                }
            }
        }
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
                Toast { t: 0.0, life, ult_ready: matches!(ev, SimEvent::UltReady) },
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
                    t.spawn(crate::prompts::hint(&fonts.body, 15.0, PAPER, &m.body));
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
