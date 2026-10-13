//! 扑击（纸鹤 / 千鹤引）：平时绕身，休息够了就随机扑向附近的妖物，撞到后折返。

use bevy_math::{Vec2, ops};

use lantern_content::{Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::{Crane, Ctx, TAU, WeaponSlot};
use crate::SimEvent;
use crate::combat::{Hit, Source};

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Seeker {
        orbit_radius,
        orbit_spin,
        range,
        pick,
        rest,
        knockback,
        speed,
        steer,
        reach,
    } = *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let p = ctx.player;
    // 召唤物数量再乘木·极境的倍率（向上取整）
    let n = ((lv.count + ctx.stats.amount()) as f32 * ctx.stats.get(Stat::SummonMult)).ceil() as usize;
    while slot.cranes.len() < n {
        slot.cranes.push(Crane {
            pos: p,
            prev: p,
            vel: Vec2::ZERO,
            striking: false,
            rest: 0.2,
            target: None,
            angle: 0.0,
        });
    }
    let speed = speed.at(slot.level as f32);
    let source = Source::Weapon(slot.def as u16);
    let element = Some(ctx.content.weapons[slot.def].element);
    let total = slot.cranes.len();
    let en = ctx.en;
    for (i, c) in slot.cranes.iter_mut().enumerate() {
        c.prev = c.pos;
        c.rest -= DT;
        let goal = if !c.striking {
            let a = ctx.secs * orbit_spin + i as f32 * TAU / total as f32;
            let (s, co) = ops::sin_cos(a);
            if c.rest <= 0.0 {
                c.striking = true;
            }
            p + Vec2::new(co, s) * orbit_radius
        } else {
            let mut t = c.target.and_then(|h| en.resolve(h));
            if t.is_none_or(|t| Vec2::new(en.x[t], en.y[t]).distance_squared(p) > range * range) {
                ctx.grid.nearest_k(en, c.pos.x, c.pos.y, range, pick as usize, ctx.found);
                t = if ctx.found.is_empty() {
                    None
                } else {
                    Some(ctx.found[ctx.rng.below(ctx.found.len() as u32) as usize] as usize)
                };
                c.target = t.map(|t| en.handle(t));
            }
            let Some(t) = t else {
                c.striking = false;
                c.rest = 0.3;
                continue;
            };
            let target = Vec2::new(en.x[t], en.y[t]);
            if target.distance(c.pos) < en.r[t] + reach {
                ctx.hits
                    .0
                    .push(Hit::new(en.handle(t), lv.damage, source).knock(knockback, c.pos).element(element));
                ctx.outbox.0.push(SimEvent::CraneStrike { pos: c.pos });
                ctx.bamboo.circle(c.pos, reach, lv.damage);
                c.striking = false;
                c.rest = rest;
            }
            target
        };
        let d = goal - c.pos;
        let len = d.length().max(1e-3);
        let k = (DT * steer).min(1.0);
        c.vel += (d / len * speed - c.vel) * k;
        c.pos += c.vel * DT;
        c.angle = ops::atan2(c.vel.y, c.vel.x);
    }
}
