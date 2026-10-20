//! 信息栏的动效（docs/FEEL.md 第 5 节）：掉血的白色残影慢半拍缩回、挨打时血条一抖一亮，
//! 生命低于三成时血条跟着心跳泛红；拾到铜钱时那一行字跳一下（“角落的计数跳动”）；
//! 吃到魂火时经验条亮一下；升级时等级印像盖章一样砸下来、字泛金；
//! 燃灯刻度每点亮一格就跳一下，蓄满时整圈一呼一吸地发亮，燃灯那一下整圈一闪再熄掉；
//! 燃灯未满时尝试燃灯，头像章一抖并短暂提示。
//! 开局时画面从黑里淡出来（灯笼同时点亮，见画面层的 `hero_glow`）。用现实时间。

use bevy::prelude::*;
use bevy::ui::Val2;

use lantern_sim::{AppState, Health, Player, Progress, SimEvent, SimOutbox};

use crate::PAPER;
use crate::hud::{HpFill, Kills, LevelLabel, UltLabel, UltTick, XpFill};

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

/// 等级印（升级时盖章似的砸下来）。
#[derive(Component)]
pub(crate) struct LevelSeal;

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
    /// 升级后过了几秒（盖章的动作按它算）
    level_t: f32,
    /// 经验条的亮度和上一帧的经验
    xp_glow: f32,
    xp_last: Option<(u32, f32)>,
    /// 心跳的相位（和画面暗角同一个节奏）
    heart: f32,
    /// 燃灯刻度：上一帧点亮了几格、每格跳的余量、燃灯那一下的闪
    lit: usize,
    pops: [f32; TICKS],
    cast: f32,
}

/// 燃灯刻度的个数（和 hud.rs 的头像章一致）
const TICKS: usize = 12;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<HudFx>()
        .add_systems(OnEnter(AppState::Run), (reset, spawn_curtain))
        .add_systems(Update, (animate, ticks, ult_feedback, curtain).run_if(in_state(AppState::Run)));
}

fn ult_feedback(
    time: Res<Time<Real>>,
    outbox: Res<SimOutbox>,
    progress: Option<Res<Progress>>,
    mut bars: Query<(&mut UltBar, &mut UiTransform)>,
    mut hints: Query<&mut TextColor, With<UltHint>>,
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
        for mut color in &mut hints {
            color.0 = GOLD.with_alpha((bar.remaining / 0.35).min(1.0));
        }
    }
}

fn reset(mut fx: ResMut<HudFx>) {
    *fx = HudFx { trail: 1.0, level_t: 10.0, ..default() };
}

/// 盖章：从 2 倍砸到 0.9 倍（0.14 秒），再弹回原大（到 0.32 秒）。
fn stamp(t: f32) -> f32 {
    if t < 0.14 {
        let u = t / 0.14;
        2.0 - 1.1 * u * u
    } else if t < 0.32 {
        let u = (t - 0.14) / 0.18;
        0.9 + 0.1 * (1.0 - (1.0 - u) * (1.0 - u))
    } else {
        1.0
    }
}

/// 心跳“咚、咚”两下（同画面层 atmos.rs 的暗角）。
fn beat(h: f32) -> f32 {
    (-((h - 0.05) * 18.0).powi(2)).exp() + (-((h - 0.28) * 18.0).powi(2)).exp() * 0.7
}

/// 燃灯刻度：每点亮一格那一格跳一下、泛金；蓄满后整圈一呼一吸；燃灯那一下整圈一闪再熄。
fn ticks(
    time: Res<Time<Real>>,
    outbox: Res<SimOutbox>,
    progress: Option<Res<Progress>>,
    mut fx: ResMut<HudFx>,
    mut q: Query<(&UltTick, &mut ImageNode, &mut UiTransform)>,
) {
    let dt = time.delta_secs().min(0.1);
    let ult = progress.map_or(0.0, |p| p.ult);
    let lit = if ult >= 1.0 { TICKS } else { ((ult * TICKS as f32) as usize).min(TICKS) };
    if outbox.0.iter().any(|e| matches!(e, SimEvent::Ult)) {
        fx.cast = 1.0;
    }
    // 一帧点亮了好几格时（开局读档、拾到大魂火）依次错开一点跳
    if lit > fx.lit {
        for k in fx.lit..lit {
            fx.pops[k] = 1.0 + (k - fx.lit) as f32 * 0.12;
        }
    }
    fx.lit = lit;
    fx.cast = (fx.cast - dt * 2.5).max(0.0);
    for p in &mut fx.pops {
        *p = (*p - dt * 4.0).max(0.0);
    }
    let breath = if ult >= 1.0 { 0.5 + 0.5 * (time.elapsed_secs() * 4.0).sin() } else { 0.0 };
    for (tick, mut img, mut tf) in &mut q {
        let pop = fx.pops.get(tick.0).copied().unwrap_or(0.0).min(1.0);
        let k = pop * pop;
        tf.scale = Vec2::splat(1.0 + 0.55 * k + 0.25 * fx.cast);
        let glow = breath.max(k).max(fx.cast);
        let hot = if fx.cast > 0.0 { Color::srgb(2.2, 2.0, 1.6) } else { Color::srgb(1.6, 1.35, 0.8) };
        img.color = Color::WHITE.mix(&hot, glow);
    }
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
    mut level: Query<&mut TextColor, With<LevelLabel>>,
    progress: Option<Res<lantern_sim::Progress>>,
    mut seal: Query<&mut UiTransform, (With<LevelSeal>, Without<HpBar>, Without<Kills>, Without<LevelLabel>)>,
    mut fills: ParamSet<(Query<&mut ImageNode, With<XpFill>>, Query<&mut ImageNode, With<HpFill>>)>,
    mut ult_label: Query<
        &mut UiTransform,
        (With<UltLabel>, Without<HpBar>, Without<Kills>, Without<LevelLabel>, Without<LevelSeal>),
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
            SimEvent::LevelUp { .. } => {
                fx.level = 1.0;
                fx.level_t = 0.0;
            }
            _ => {}
        }
    }
    // 残影：回血时立刻跟上，掉血时停一下再缩；只画当前血量到残影之间的那一截
    let mut hp = fx.trail;
    let mut low = 0.0;
    if let Ok(h) = player.single() {
        hp = (h.hp / h.max.max(1.0)).clamp(0.0, 1.0);
        low = ((0.3 - hp) / 0.2).clamp(0.0, 1.0);
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
    // 血条：挨打那一下白一闪；生命低于三成时跟着心跳泛红（越低越急、越红）
    fx.heart = (fx.heart + dt * (1.1 + low * 0.6)).fract();
    let red = low * (0.25 + 0.75 * beat(fx.heart));
    for mut img in &mut fills.p1() {
        img.color = Color::WHITE
            .mix(&Color::srgb(1.9, 0.5, 0.42), red * 0.85)
            .mix(&Color::srgb(2.4, 2.2, 2.0), s_hit(fx.shake));
    }
    // 经验条：吃到魂火亮一下，一下子吃得多亮得多；升级那一刻经验归零，不算
    if let Some(p) = progress.as_deref() {
        if let Some((lv, xp)) = fx.xp_last
            && lv == p.level
            && p.xp > xp
        {
            fx.xp_glow = (fx.xp_glow + 0.25 + (p.xp - xp) * 0.02).min(1.0);
        }
        fx.xp_last = Some((p.level, p.xp));
    }
    fx.xp_glow = (fx.xp_glow - dt * 2.5).max(0.0);
    for mut img in &mut fills.p0() {
        img.color = Color::WHITE.mix(&Color::srgb(1.7, 1.55, 1.1), fx.xp_glow * 0.7);
    }
    // 燃灯蓄满：按键字跟着刻度一起轻轻起伏（刻度的呼吸在 `ticks`）
    let ready = progress.is_some_and(|p| p.ult >= 1.0);
    let breath = if ready { 0.5 + 0.5 * (time.elapsed_secs() * 4.0).sin() } else { 0.0 };
    for mut tf in &mut ult_label {
        tf.scale = Vec2::splat(1.0 + 0.06 * breath);
    }
    // 升级：等级印盖章似的砸下来，字泛金后慢慢退回纸色
    fx.level = (fx.level - dt * 2.0).max(0.0);
    fx.level_t += dt;
    for mut tf in &mut seal {
        tf.scale = Vec2::splat(stamp(fx.level_t));
    }
    for mut color in &mut level {
        color.0 = PAPER.mix(&GOLD, fx.level * fx.level);
    }
}

/// 挨打时血条白一闪的量：抖动的前一小段（抖动从 1 往下掉，掉到 0.7 以下就不闪了）。
fn s_hit(shake: f32) -> f32 {
    ((shake - 0.7) / 0.3).clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    /// 等级印：先放大砸下去、压过头一点，再回到原大
    #[test]
    fn level_seal_stamps_down_and_settles() {
        assert!((stamp(0.0) - 2.0).abs() < 1e-6);
        assert!(stamp(0.14) < 0.95);
        assert!((stamp(0.32) - 1.0).abs() < 1e-3);
        assert_eq!(stamp(5.0), 1.0);
    }

    /// 燃灯每点亮一格，那一格跳一下；蓄满后整圈呼吸；燃灯那一下整圈一闪
    #[test]
    fn ult_ticks_pop_as_they_light_and_flash_on_cast() {
        let mut app = App::new();
        app.init_resource::<Time<Real>>()
            .init_resource::<SimOutbox>()
            .init_resource::<Progress>()
            .init_resource::<HudFx>()
            .add_systems(Update, ticks);
        let ids: Vec<Entity> = (0..TICKS)
            .map(|k| app.world_mut().spawn((UltTick(k), ImageNode::default(), UiTransform::default())).id())
            .collect();
        let step = |app: &mut App| {
            app.world_mut().resource_mut::<Time<Real>>().advance_by(Duration::from_millis(16));
            app.update();
        };
        let scale = |app: &App, k: usize| app.world().get::<UiTransform>(ids[k]).unwrap().scale.x;
        step(&mut app);
        assert!((0..TICKS).all(|k| scale(&app, k) == 1.0));
        // 蓄到两格多：第 0、1 格跳，第 2 格不动
        app.world_mut().resource_mut::<Progress>().ult = 2.5 / TICKS as f32;
        step(&mut app);
        assert!(scale(&app, 0) > 1.3 && scale(&app, 1) > 1.3);
        assert_eq!(scale(&app, 2), 1.0);
        for _ in 0..30 {
            step(&mut app);
        }
        assert_eq!(scale(&app, 0), 1.0, "跳完回到原大");
        // 燃灯：整圈一闪
        app.world_mut().resource_mut::<Progress>().ult = 0.0;
        app.world_mut().resource_mut::<SimOutbox>().0.push(SimEvent::Ult);
        step(&mut app);
        app.world_mut().resource_mut::<SimOutbox>().0.clear();
        assert!((0..TICKS).all(|k| scale(&app, k) > 1.1));
        assert_ne!(app.world().get::<ImageNode>(ids[5]).unwrap().color, Color::WHITE);
        for _ in 0..40 {
            step(&mut app);
        }
        assert!((0..TICKS).all(|k| scale(&app, k) == 1.0));
        assert_eq!(app.world().get::<ImageNode>(ids[5]).unwrap().color, Color::WHITE);
    }

    #[test]
    fn empty_ult_bar_shakes_and_hint_fades_or_clears_when_ready() {
        let mut app = App::new();
        app.init_resource::<Time<Real>>()
            .init_resource::<SimOutbox>()
            .init_resource::<Progress>()
            .add_systems(Update, ult_feedback);
        let bar = app.world_mut().spawn((UltBar::default(), UiTransform::default())).id();
        let hint = app.world_mut().spawn((UltHint, TextColor(GOLD.with_alpha(0.0)))).id();
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
