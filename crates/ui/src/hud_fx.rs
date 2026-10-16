//! 信息栏的动效（docs/FEEL.md 第 5 节）：掉血的白色残影慢半拍缩回、挨打时血条一抖，
//! 拾到铜钱时那一行字跳一下（“角落的计数跳动”），升级时等级字放大泛金，燃灯蓄满时燃灯条一呼一吸地发亮，
//! 燃灯未满时尝试燃灯，计量条一抖并短暂提示。
//! 开局时画面从黑里淡出来（灯笼同时点亮，见画面层的 `hero_glow`）。用现实时间。

use bevy::prelude::*;
use bevy::ui::Val2;

use lantern_sim::{AppState, Health, Player, Progress, SimEvent, SimOutbox};

use crate::PAPER;
use crate::hud::{Kills, LevelLabel, UltFill, UltLabel};

const GOLD: Color = Color::srgb(1.0, 0.85, 0.54);
const ULT_HINT_SECS: f32 = 1.2;

/// 燃灯的底槽和文字一起抖动，空槽也能看见；计时只留在界面层。
#[derive(Component, Default)]
pub(crate) struct UltBar {
    remaining: f32,
}

#[derive(Component)]
pub(crate) struct UltHint;

/// 血条的底槽（挨打时整条一抖）。
#[derive(Component)]
pub(crate) struct HpBar;

/// 掉血的残影。
#[derive(Component)]
pub(crate) struct HpTrail;

/// 开局的黑幕。
#[derive(Component)]
struct Curtain(f32);

#[derive(Resource, Default)]
struct HudFx {
    /// 残影现在的长度（0–1）和还要停多久才开始缩
    trail: f32,
    hold: f32,
    shake: f32,
    coin: f32,
    level: f32,
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<HudFx>()
        .add_systems(OnEnter(AppState::Run), (reset, spawn_curtain))
        .add_systems(Update, (animate, ult_feedback, curtain).run_if(in_state(AppState::Run)));
}

fn ult_feedback(
    time: Res<Time<Real>>,
    outbox: Res<SimOutbox>,
    progress: Option<Res<Progress>>,
    mut bars: Query<(&mut UltBar, &mut UiTransform)>,
    mut hints: Query<(&mut TextColor, &mut Node), With<UltHint>>,
) {
    let ready = progress.is_some_and(|p| p.ult >= 1.0);
    for (mut bar, mut tf) in &mut bars {
        bar.remaining = (bar.remaining - time.delta_secs().min(0.1)).max(0.0);
        for ev in &outbox.0 {
            match ev {
                SimEvent::UltNotReady => bar.remaining = ULT_HINT_SECS,
                SimEvent::Ult | SimEvent::UltReady => bar.remaining = 0.0,
                _ => {}
            }
        }
        if ready {
            bar.remaining = 0.0;
        }
        let age = ULT_HINT_SECS - bar.remaining;
        let shake = (1.0 - age / 0.3).max(0.0);
        tf.translation = Val2::px((age * 70.0).sin() * 6.0 * shake * shake, 0.0);
        for (mut color, mut node) in &mut hints {
            color.0 = GOLD.with_alpha((bar.remaining / 0.35).min(1.0));
            node.display = if bar.remaining > 0.0 { Display::Flex } else { Display::None };
        }
    }
}

fn reset(mut fx: ResMut<HudFx>) {
    *fx = HudFx { trail: 1.0, ..default() };
}

fn spawn_curtain(mut commands: Commands) {
    commands.spawn((
        Curtain(0.0),
        DespawnOnExit(AppState::Run),
        GlobalZIndex(30),
        Node {
            position_type: PositionType::Absolute,
            width: percent(100),
            height: percent(100),
            ..default()
        },
        BackgroundColor(Color::BLACK),
    ));
}

/// 开局黑幕：停 0.15 秒，0.9 秒淡开。
fn curtain(
    mut commands: Commands,
    time: Res<Time<Real>>,
    mut q: Query<(Entity, &mut Curtain, &mut BackgroundColor)>,
) {
    for (e, mut c, mut bg) in &mut q {
        c.0 += time.delta_secs().min(0.1);
        let a = 1.0 - ((c.0 - 0.15) / 0.9).clamp(0.0, 1.0);
        if a <= 0.0 {
            commands.entity(e).despawn();
        } else {
            bg.0.set_alpha(a * a);
        }
    }
}

fn animate(
    time: Res<Time<Real>>,
    outbox: Res<SimOutbox>,
    player: Query<&Health, With<Player>>,
    mut fx: ResMut<HudFx>,
    mut trail: Query<&mut Node, With<HpTrail>>,
    mut bar: Query<&mut UiTransform, (With<HpBar>, Without<Kills>, Without<LevelLabel>)>,
    mut kills: Query<&mut UiTransform, (With<Kills>, Without<HpBar>, Without<LevelLabel>)>,
    mut level: Query<(&mut UiTransform, &mut TextColor), (With<LevelLabel>, Without<HpBar>, Without<Kills>)>,
    progress: Option<Res<lantern_sim::Progress>>,
    mut ult: Query<&mut ImageNode, With<UltFill>>,
    mut ult_label: Query<
        &mut UiTransform,
        (With<UltLabel>, Without<HpBar>, Without<Kills>, Without<LevelLabel>),
    >,
) {
    let dt = time.delta_secs().min(0.1);
    for ev in &outbox.0 {
        match ev {
            SimEvent::PlayerHurt { .. } | SimEvent::Sacrifice { .. } => {
                fx.hold = 0.35;
                fx.shake = 1.0;
            }
            SimEvent::CoinPicked { .. } => fx.coin = 1.0,
            SimEvent::LevelUp { .. } => fx.level = 1.0,
            _ => {}
        }
    }
    // 残影：回血时立刻跟上，掉血时停一下再缩；只画当前血量到残影之间的那一截
    let mut hp = fx.trail;
    if let Ok(h) = player.single() {
        hp = (h.hp / h.max.max(1.0)).clamp(0.0, 1.0);
        if hp >= fx.trail {
            fx.trail = hp;
        } else if fx.hold > 0.0 {
            fx.hold -= dt;
        } else {
            fx.trail = (fx.trail - dt * 0.6).max(hp);
        }
    }
    for mut n in &mut trail {
        n.left = percent(hp * 100.0);
        n.width = percent((fx.trail - hp).max(0.0) * 100.0);
    }
    fx.shake = (fx.shake - dt * 4.0).max(0.0);
    for mut tf in &mut bar {
        let s = fx.shake * fx.shake;
        tf.translation = Val2::px((time.elapsed_secs() * 70.0).sin() * 5.0 * s, 0.0);
    }
    fx.coin = (fx.coin - dt * 5.0).max(0.0);
    for mut tf in &mut kills {
        tf.scale = Vec2::splat(1.0 + 0.06 * fx.coin);
    }
    // 燃灯蓄满：燃灯条一呼一吸地发亮，字跟着轻轻起伏
    let ready = progress.is_some_and(|p| p.ult >= 1.0);
    let breath = if ready { 0.5 + 0.5 * (time.elapsed_secs() * 4.0).sin() } else { 0.0 };
    for mut img in &mut ult {
        img.color = Color::WHITE.mix(&Color::srgb(1.6, 1.35, 0.8), breath);
    }
    for mut tf in &mut ult_label {
        tf.scale = Vec2::splat(1.0 + 0.06 * breath);
    }
    fx.level = (fx.level - dt * 2.0).max(0.0);
    for (mut tf, mut color) in &mut level {
        let k = fx.level * fx.level;
        tf.scale = Vec2::splat(1.0 + 0.35 * k);
        color.0 = PAPER.mix(&GOLD, k);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn empty_ult_bar_shakes_and_hint_fades_or_clears_when_ready() {
        let mut app = App::new();
        app.init_resource::<Time<Real>>()
            .init_resource::<SimOutbox>()
            .init_resource::<Progress>()
            .add_systems(Update, ult_feedback);
        let bar = app.world_mut().spawn((UltBar::default(), UiTransform::default())).id();
        let hint = app.world_mut().spawn((UltHint, TextColor(GOLD.with_alpha(0.0)), Node::default())).id();
        app.world_mut().resource_mut::<Time<Real>>().advance_by(Duration::from_millis(50));
        app.update();
        assert_eq!(app.world().get::<TextColor>(hint).unwrap().0.alpha(), 0.0);

        app.world_mut().resource_mut::<SimOutbox>().0.push(SimEvent::UltNotReady);
        app.update();
        app.world_mut().resource_mut::<SimOutbox>().0.clear();
        app.update();
        assert_eq!(app.world().resource::<Progress>().ult, 0.0);
        assert_eq!(app.world().get::<TextColor>(hint).unwrap().0.alpha(), 1.0);
        assert_ne!(app.world().get::<UiTransform>(bar).unwrap().translation, Val2::px(0.0, 0.0));
        for _ in 0..18 {
            app.update();
        }
        let alpha = app.world().get::<TextColor>(hint).unwrap().0.alpha();
        assert!(alpha > 0.0 && alpha < 1.0, "提示渐隐");
        assert_eq!(app.world().get::<UiTransform>(bar).unwrap().translation, Val2::px(0.0, 0.0));
        for _ in 0..8 {
            app.update();
        }
        assert_eq!(app.world().get::<TextColor>(hint).unwrap().0.alpha(), 0.0);

        app.world_mut().resource_mut::<SimOutbox>().0.push(SimEvent::UltNotReady);
        app.update();
        assert_eq!(app.world().get::<TextColor>(hint).unwrap().0.alpha(), 1.0, "再次按键重新提示");
        app.world_mut().resource_mut::<SimOutbox>().0.clear();
        app.world_mut().resource_mut::<Progress>().ult = 1.0;
        app.update();
        assert_eq!(app.world().get::<TextColor>(hint).unwrap().0.alpha(), 0.0, "蓄满后及时撤下提示");
        assert_eq!(app.world().get::<UiTransform>(bar).unwrap().translation, Val2::px(0.0, 0.0));
    }
}
