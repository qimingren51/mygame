//! 镇妖塔 / 玲珑塔（docs/BALANCE.md 第 6.3 节）：在妖物最密的地方落塔，砸晕一片，再把周围的妖物吸到塔下、
//! 定时跳伤害；玲珑塔到时间炸开。
//!
//! 塔在 [`Towers`] 里，每步由 [`update_towers`] 推进；落地、每跳和炸开都是范围打击（`Strikes`）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{Element, Rank, Stat, TowerBurstDef, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready, densest};
use crate::combat::{Area, Source, Strike, StrikeFx, Strikes};
use crate::enemies::Enemies;
use crate::spatial::Grid;
use crate::{GameContent, SimEvent, SimOutbox};

/// 一座塔。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tower {
    pub pos: Vec2,
    /// 还有多久落地（落地前画预警圈）
    pub warn: f32,
    /// 落地后还能立多久
    pub life: f32,
    /// 离下一跳还有多久
    pub tick_t: f32,
    pub radius: f32,
    pub damage: f32,
    pub stun: f32,
    pub pull: f32,
    pub pull_speed: f32,
    pub tick: f32,
    pub tick_scale: f32,
    pub burst: Option<TowerBurstDef>,
    pub source: Source,
    pub element: Option<Element>,
    pub evolved: bool,
}

#[derive(Resource, Default, Debug)]
pub struct Towers(pub Vec<Tower>);

impl Towers {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for t in &self.0 {
            for v in [t.pos.x, t.pos.y, t.warn, t.life, t.tick_t, t.radius, t.damage] {
                h.write_f32(v);
            }
        }
    }
}

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Tower {
        range,
        pick,
        cluster,
        spread,
        warn,
        stun,
        life,
        pull,
        pull_speed,
        tick,
        tick_scale,
        burst,
    } = *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let radius = lv.radius * ctx.stats.get(Stat::Area);
    slot.radius = radius;
    slot.count = lv.count + ctx.stats.amount();
    if !cooldown_ready(slot) {
        return;
    }
    slot.timer = lv.cooldown * ctx.stats.get(Stat::Cooldown);
    let p = ctx.player;
    let mut chosen: Vec<Vec2> = Vec::with_capacity(slot.count as usize);
    for k in 0..slot.count {
        let at = densest(ctx.grid, ctx.en, p, (range, pick, cluster, spread), &chosen, ctx.found)
            // 附近没有妖物：落在前方，几座错开
            .unwrap_or_else(|| {
                let side = Vec2::new(-ctx.facing.y, ctx.facing.x)
                    * spread
                    * (k as f32 - (slot.count - 1) as f32 * 0.5);
                p + ctx.facing * 150.0 + side
            });
        chosen.push(at);
        ctx.towers.0.push(Tower {
            pos: at,
            warn,
            life,
            tick_t: tick,
            radius,
            damage: lv.damage,
            stun,
            pull: pull * radius,
            pull_speed,
            tick,
            tick_scale,
            burst,
            source: Source::Weapon(slot.def as u16),
            element: Some(ctx.content.weapons[slot.def].element),
            evolved: slot.transformed(),
        });
    }
}

fn strike(t: &Tower, radius: f32, damage: f32, stun: f32) -> Strike {
    let mut s = Strike::new(t.pos, Area::Circle(radius), damage, t.source, StrikeFx::None);
    s.stun = stun;
    s.element = t.element;
    s
}

/// 落塔：预警、落地、立着吸妖跳伤害、到时间收走（玲珑塔炸开）。
pub(crate) fn update_towers(
    content: Res<GameContent>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut towers: ResMut<Towers>,
    mut strikes: ResMut<Strikes>,
    mut outbox: ResMut<SimOutbox>,
    mut found: Local<Vec<u32>>,
) {
    let en = &mut *en;
    let mut k = 0;
    while k < towers.0.len() {
        let t = &mut towers.0[k];
        if t.warn > 0.0 {
            t.warn -= DT;
            if t.warn <= 0.0 {
                strikes.0.push(strike(t, t.radius, t.damage, t.stun));
                outbox.0.push(SimEvent::TowerLand { pos: t.pos, radius: t.radius, evolved: t.evolved });
            }
            k += 1;
            continue;
        }
        // 往塔下吸：精英一半，夜主不吸；吸到塔底就停
        found.clear();
        grid.query_circle(en, t.pos.x, t.pos.y, t.pull, &mut found);
        for &i in found.iter() {
            let i = i as usize;
            let speed = match content.0.enemies[en.kind[i] as usize].rank {
                Rank::Boss => continue,
                Rank::Elite => t.pull_speed * 0.5,
                _ => t.pull_speed,
            };
            let to = t.pos - Vec2::new(en.x[i], en.y[i]);
            let d = to.length();
            if d <= 1.0 {
                continue;
            }
            let step = (speed * DT).min(d - 1.0);
            en.x[i] += to.x / d * step;
            en.y[i] += to.y / d * step;
        }
        t.tick_t -= DT;
        if t.tick_t <= 0.0 {
            t.tick_t += t.tick;
            strikes.0.push(strike(t, t.radius, t.damage * t.tick_scale, 0.0));
        }
        t.life -= DT;
        if t.life > 0.0 {
            k += 1;
            continue;
        }
        let t = towers.0.remove(k);
        if let Some(b) = t.burst {
            strikes.0.push(strike(&t, b.radius, b.damage, b.stun));
            outbox.0.push(SimEvent::TowerBurst { pos: t.pos, radius: b.radius });
        }
    }
}
