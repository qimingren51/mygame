//! 信息栏的动效（docs/FEEL.md 第 5 节）：掉血的白色残影慢半拍缩回、挨打时血条一抖，
//! 拾到铜钱时那一行字跳一下（“角落的计数跳动”），升级时等级字放大泛金。用现实时间。

use bevy::prelude::*;
use bevy::ui::Val2;

use lantern_sim::{AppState, Health, Player, SimEvent, SimOutbox};

use crate::PAPER;
use crate::hud::{Kills, LevelLabel};

const GOLD: Color = Color::srgb(1.0, 0.85, 0.54);

/// 血条的底槽（挨打时整条一抖）。
#[derive(Component)]
pub(crate) struct HpBar;

/// 掉血的残影。
#[derive(Component)]
pub(crate) struct HpTrail;

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
        .add_systems(OnEnter(AppState::Run), |mut fx: ResMut<HudFx>| *fx = HudFx { trail: 1.0, ..default() })
        .add_systems(Update, animate.run_if(in_state(AppState::Run)));
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
    fx.level = (fx.level - dt * 2.0).max(0.0);
    for (mut tf, mut color) in &mut level {
        let k = fx.level * fx.level;
        tf.scale = Vec2::splat(1.0 + 0.35 * k);
        color.0 = PAPER.mix(&GOLD, k);
    }
}
