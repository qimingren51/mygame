//! 主角：移动与闪避、回复、护盾、周期触发器、连斩计时（移植自网页版 sim/step.ts）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::Stat;
use lantern_core::Stream;
use lantern_core::step::DT;

use crate::combat::{ActionQueue, Deferred, Hit, HitQueue, Source, heal_overflow, passes};
use crate::enemies::{Enemies, EnemyHandle};
use crate::run::Progress;
use crate::spatial::Grid;
use crate::stats::{Effects, Stats};
use crate::weapons::Arsenal;
use crate::{GameContent, Health, InputFrame, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

/// 本次闪避已经伤到的妖物（轻功：每次闪避对同一只只算一次）。
#[derive(Resource, Default, Debug)]
pub struct DashHits(pub Vec<EnemyHandle>);

pub(crate) fn move_player(stats: Res<Stats>, input: Res<InputFrame>, mut q: Query<(&mut Pos, &mut Player)>) {
    let speed = stats.get(Stat::Speed);
    let charges = stats.get(Stat::DashCharges).round().max(1.0) as u32;
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
        // 闪避按段充能：冷却走完补一段，没满就接着冷却
        p.dash_ready = p.dash_ready.min(charges);
        if p.dash_ready < charges {
            if p.dash_cd <= 0.0 {
                p.dash_cd = stats.get(Stat::DashCooldown);
            }
            p.dash_cd -= DT;
            if p.dash_cd <= 0.0 {
                p.dash_ready += 1;
                p.dash_cd = if p.dash_ready < charges { stats.get(Stat::DashCooldown) } else { 0.0 };
            }
        } else {
            p.dash_cd = 0.0;
        }
        p.iframe = (p.iframe - DT).max(0.0);
    }
}

/// 轻功：闪避途中穿过的妖物受到“单次伤害最高的那件法器的基础伤害 × DashStrike”。
pub(crate) fn dash_strike(
    content: Res<GameContent>,
    stats: Res<Stats>,
    arsenal: Res<Arsenal>,
    grid: Res<Grid>,
    en: Res<Enemies>,
    player: Single<(&Pos, &Player)>,
    mut seen: ResMut<DashHits>,
    mut hits: ResMut<HitQueue>,
    mut found: Local<Vec<u32>>,
) {
    let (pos, p) = *player;
    let mult = stats.get(Stat::DashStrike);
    if p.dash_t <= 0.0 || mult <= 0.0 {
        return;
    }
    let c = &content.0;
    let best = arsenal.0.iter().map(|w| w.stats(c).damage).fold(0.0f32, f32::max);
    if best <= 0.0 {
        return;
    }
    found.clear();
    grid.query_circle(&en, pos.0.x, pos.0.y, c.player.radius + 6.0, &mut found);
    for &i in found.iter() {
        let h = en.handle(i as usize);
        if !seen.0.contains(&h) {
            seen.0.push(h);
            hits.0.push(
                Hit::new(h, best * mult, Source::Dash).knock(60.0, pos.0 - p.dash_vel.normalize_or(Vec2::X)),
            );
        }
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
    let regen =
        (stats.get(Stat::Regen) * stats.max_hp() + stats.get(Stat::RegenFlat)) * stats.get(Stat::Healing);
    let shield = effects.shield;
    let rng = rng.0.get(Stream::Combat);
    for (pos, mut p, mut h) in &mut q {
        if regen > 0.0 && h.hp > 0.0 {
            // 每步的回复量很小，不发回复事件
            let room = (h.max - h.hp).max(0.0);
            let amount = regen * DT;
            if amount <= room {
                h.hp += amount;
            } else {
                h.hp = h.max;
                heal_overflow(&mut p, &mut h, &stats, amount - room, &mut outbox);
            }
        }
        if let Some(amount) = shield
            && p.shield <= 0.0
        {
            p.shield_t -= DT;
            if p.shield_t <= 0.0 {
                p.shield = amount.at(minute) * stats.get(Stat::ShieldMult);
                p.shield_max = p.shield;
                outbox.0.push(SimEvent::ShieldUp);
            }
        }
        for t in &mut effects.periodic {
            t.elapsed += DT;
            if t.elapsed >= t.period {
                t.elapsed = 0.0;
                if passes(t, rng, false, 0, false) {
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
