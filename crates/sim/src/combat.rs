//! 伤害管线（docs/DESIGN.md 第 6.5 节，数值移植自网页版 sim/combat.ts）：
//! 法器等命中来源把 [`Hit`] 按顺序放进 [`HitQueue`]，Damage 阶段统一结算：
//! 暴击 → 扣血 → 受击闪白、击退 → 死亡时掉魂火、计击杀。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::Rank;
use lantern_core::Stream;

use crate::enemies::{Enemies, EnemyHandle};
use crate::gems::Gems;
use crate::run::{Progress, Stats};
use crate::{GameContent, Health, Player, SimEvent, SimOutbox, SimRng, Tick};

/// 不判定暴击
pub const HIT_NOCRIT: u8 = 1;

#[derive(Clone, Copy, Debug)]
pub struct Hit {
    pub target: EnemyHandle,
    /// 基础伤害，结算时乘以属性里的伤害倍率
    pub damage: f32,
    pub knockback: f32,
    /// 击退方向的来源点
    pub from: Vec2,
    pub flags: u8,
}

/// 本步待结算的命中，按产生顺序。
#[derive(Resource, Default, Debug)]
pub struct HitQueue(pub Vec<Hit>);

pub(crate) fn resolve_hits(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    mut rng: ResMut<SimRng>,
    mut hits: ResMut<HitQueue>,
    mut en: ResMut<Enemies>,
    mut gems: ResMut<Gems>,
    mut progress: ResMut<Progress>,
    mut outbox: ResMut<SimOutbox>,
) {
    let content = &content.0;
    let minute = tick.secs() / 60.0;
    for hit in hits.0.drain(..) {
        let Some(i) = en.resolve(hit.target) else { continue };
        let def = &content.enemies[en.kind[i] as usize];
        let mut dmg = hit.damage * stats.damage;
        let crit = hit.flags & HIT_NOCRIT == 0 && rng.0.get(Stream::Combat).next_f32() < stats.crit_chance;
        if crit {
            dmg *= stats.crit_mult;
        }
        en.hp[i] -= dmg;
        en.flash[i] = 0.08;
        let pos = Vec2::new(en.x[i], en.y[i]);
        outbox.0.push(SimEvent::Hit { pos: pos - Vec2::new(0.0, en.r[i] + 4.0), damage: dmg, crit });

        if hit.knockback > 0.0 && def.rank != Rank::Boss {
            let d = pos - hit.from;
            let len = d.length().max(1e-3);
            let f = hit.knockback * stats.knockback / if def.rank == Rank::Elite { 3.0 } else { 1.0 };
            en.kx[i] += d.x / len * f;
            en.ky[i] += d.y / len * f;
        }

        if en.hp[i] <= 0.0 {
            let kind = en.kind[i];
            en.kill(i);
            outbox.0.push(SimEvent::Kill { pos, kind, rank: def.rank });
            if def.rank == Rank::Critter {
                continue;
            }
            progress.kills += 1;
            if def.xp > 0.0 {
                let value = def.xp * content.run.gem_value_scale.at(minute);
                let g = &content.run.gems;
                if def.rank == Rank::Elite {
                    let loot = rng.0.get(Stream::Drop);
                    let n = g.elite_split;
                    for _ in 0..n {
                        let off = Vec2::new(
                            loot.range_f32(-g.elite_scatter, g.elite_scatter),
                            loot.range_f32(-g.elite_scatter, g.elite_scatter),
                        );
                        gems.drop(pos + off, value / n as f32, g.cap);
                    }
                } else {
                    gems.drop(pos, value, g.cap);
                }
            }
        }
    }
}

pub(crate) struct PlayerHurt {
    pub amount: f32,
    pub iframe: f32,
}

/// 主角受伤：无敌或闪避中不受伤；受伤后进入无敌时间。
pub(crate) fn hurt_player(
    player: &mut Player,
    health: &mut Health,
    hurt: PlayerHurt,
    outbox: &mut SimOutbox,
) {
    if player.iframe > 0.0 || player.dash_t > 0.0 || health.hp <= 0.0 {
        return;
    }
    let dmg = hurt.amount.max(1.0);
    player.iframe = hurt.iframe;
    health.hp = (health.hp - dmg).max(0.0);
    outbox.0.push(SimEvent::PlayerHurt { amount: dmg });
    if health.hp <= 0.0 {
        outbox.0.push(SimEvent::PlayerDied);
    }
}
