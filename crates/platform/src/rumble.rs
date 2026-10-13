//! 手柄震动（docs/FEEL.md 第 2 节）：和镜头的震屏同一张手感表，强度跟着设置里的“震屏”走，
//! 设成 0 就不震。只读模拟事件，不影响模拟。

use std::time::Duration;

use bevy::input::gamepad::{GamepadRumbleIntensity, GamepadRumbleRequest};
use bevy::prelude::*;

use lantern_content::Rank;
use lantern_sim::combat::StrikeFx;
use lantern_sim::{AppState, SimEvent, SimOutbox};

use crate::Settings;

pub(crate) fn register(app: &mut App) {
    app.add_systems(Update, rumble.run_if(in_state(AppState::Run)).run_if(resource_exists::<SimOutbox>));
}

/// 一次震动：强马达（低频、沉）、弱马达（高频、脆）、持续秒数。
fn pattern(ev: &SimEvent) -> Option<(f32, f32, f32)> {
    Some(match *ev {
        SimEvent::PlayerHurt { .. } => (0.5, 0.2, 0.12),
        SimEvent::Kill { rank: Rank::Elite, .. } => (0.25, 0.4, 0.15),
        SimEvent::Hit { damage, crit: true, .. } if damage >= 1000.0 => (0.0, 0.3, 0.06),
        SimEvent::Dash { .. } => (0.0, 0.18, 0.06),
        SimEvent::Strike { fx: StrikeFx::Seal { evolved: true }, .. } => (0.3, 0.0, 0.1),
        SimEvent::Strike { fx: StrikeFx::Quake, .. } => (0.5, 0.1, 0.2),
        SimEvent::Strike { fx: StrikeFx::Ult, .. } => (0.7, 0.5, 0.35),
        SimEvent::SweepStrike { .. } => (0.5, 0.2, 0.2),
        SimEvent::LastStand { .. } | SimEvent::Revived { .. } => (0.8, 0.4, 0.4),
        SimEvent::BossArrived { .. } => (0.5, 0.0, 0.6),
        SimEvent::BossPhase { .. } => (0.6, 0.2, 0.3),
        SimEvent::BossDefeated { .. } => (0.9, 0.6, 0.8),
        SimEvent::PlayerDied => (0.7, 0.3, 0.5),
        _ => return None,
    })
}

fn rumble(
    outbox: Res<SimOutbox>,
    settings: Res<Settings>,
    gamepads: Query<Entity, With<Gamepad>>,
    mut requests: MessageWriter<GamepadRumbleRequest>,
) {
    if settings.shake <= 0.0 || gamepads.is_empty() {
        return;
    }
    // 一帧里取最强的一次，免得满屏命中叠成一直在震
    let Some((strong, weak, secs)) =
        outbox.0.iter().filter_map(pattern).max_by(|a, b| a.0.max(a.1).total_cmp(&b.0.max(b.1)))
    else {
        return;
    };
    let k = settings.shake.min(1.0);
    for gamepad in &gamepads {
        requests.write(GamepadRumbleRequest::Add {
            gamepad,
            intensity: GamepadRumbleIntensity { strong_motor: strong * k, weak_motor: weak * k },
            duration: Duration::from_secs_f32(secs),
        });
    }
}
