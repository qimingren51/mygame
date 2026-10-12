//! 主角：移动与闪避、回复、护盾、周期触发器、连斩计时（移植自网页版 sim/step.ts）。

use bevy_ecs::prelude::*;

use lantern_content::Stat;
use lantern_core::Stream;
use lantern_core::step::DT;

use crate::combat::{ActionQueue, Deferred, passes};
use crate::run::Progress;
use crate::stats::{Effects, Stats};
use crate::{Health, InputFrame, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

pub(crate) fn move_player(stats: Res<Stats>, input: Res<InputFrame>, mut q: Query<(&mut Pos, &mut Player)>) {
    let speed = stats.get(Stat::Speed);
    let dir = input.dir();
    for (mut pos, mut p) in &mut q {
        let before = pos.0;
        if p.dash_t > 0.0 {
            p.dash_t -= DT;
            pos.0 += p.dash_vel * DT;
        } else {
            pos.0 += dir * speed * DT;
        }
        if dir.length_squared() > 1e-6 {
            p.facing = dir.normalize();
        }
        p.moved = before.distance(pos.0);
        p.dash_cd = (p.dash_cd - DT).max(0.0);
        p.iframe = (p.iframe - DT).max(0.0);
    }
}

/// 每步的被动效果：生命回复、护盾恢复、周期触发器、连斩计时。
pub(crate) fn upkeep(
    stats: Res<Stats>,
    tick: Res<Tick>,
    mut effects: ResMut<Effects>,
    mut rng: ResMut<SimRng>,
    mut queue: ResMut<ActionQueue>,
    mut progress: ResMut<Progress>,
    mut outbox: ResMut<SimOutbox>,
    mut q: Query<(&Pos, &mut Player, &mut Health)>,
) {
    let minute = tick.secs() / 60.0;
    let regen = stats.get(Stat::Regen) * stats.max_hp() * stats.get(Stat::Healing);
    let shield = effects.shield;
    let rng = rng.0.get(Stream::Combat);
    for (pos, mut p, mut h) in &mut q {
        if regen > 0.0 && h.hp > 0.0 {
            h.hp = (h.hp + regen * DT).min(h.max);
        }
        if let Some(amount) = shield
            && p.shield <= 0.0
        {
            p.shield_t -= DT;
            if p.shield_t <= 0.0 {
                p.shield = amount.at(minute);
                p.shield_max = p.shield;
                outbox.0.push(SimEvent::ShieldUp);
            }
        }
        for t in &mut effects.periodic {
            t.elapsed += DT;
            if t.elapsed >= t.period {
                t.elapsed = 0.0;
                if passes(t, rng, false, 0) {
                    queue.0.push(Deferred { action: t.action, pos: pos.0, target: None });
                }
            }
        }
    }
    progress.combo_t -= DT;
    if progress.combo_t <= 0.0 {
        progress.combo = 0;
    }
}
