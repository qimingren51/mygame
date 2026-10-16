//! 扑击（纸鹤 / 千鹤引）：平时绕身，休息够了就随机扑向附近的妖物，撞到后折返。

use bevy_math::{Vec2, ops};

use lantern_content::{Element, Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::{Crane, Ctx, TAU, WeaponSlot};
use crate::SimEvent;
use crate::combat::{Area, HIT_DOT, HIT_NOCRIT, Hit, Source, Strike, StrikeFx};

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
        feather,
        execute,
        count_cap,
        on_hit,
        escort,
    } = *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let p = ctx.player;
    // 召唤物数量再乘木·极境的倍率（向上取整）；铁鹤固定只数，不吃加成
    let n = match count_cap {
        Some(cap) => {
            let n = lv.count.min(cap) as usize;
            slot.cranes.truncate(n);
            n
        }
        None => ((lv.count + ctx.stats.amount()) as f32 * ctx.stats.get(Stat::SummonMult)).ceil() as usize,
    };
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
    let element = Some(if on_hit.is_some() { Element::Fire } else { ctx.content.weapons[slot.def].element });
    if let Some(e) = escort {
        // 绕身巨凤：沿环路转，每 every 秒对所在位置一击并点燃
        slot.prev_angle = slot.angle;
        slot.angle += e.spin * DT;
        slot.count = 1;
        slot.radius = e.radius * ctx.stats.get(Stat::Area);
        slot.size = e.size;
        slot.inner_t -= DT;
        if slot.inner_t <= 0.0 {
            slot.inner_t = e.every;
            let mut s = Strike::new(
                p + slot.orbit_offset(slot.angle, 0),
                Area::Circle(slot.size),
                lv.damage * e.ratio,
                source,
                StrikeFx::None,
            );
            s.element = Some(Element::Fire);
            s.ignite = 1.0;
            ctx.strikes.0.push(s);
        }
    }
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
                let mut hit = Hit::new(en.handle(t), lv.damage, source)
                    .knock(knockback, c.pos)
                    .incoming(c.vel)
                    .element(element);
                hit.execute = execute;
                ctx.hits.0.push(hit);
                if let Some(f) = feather {
                    // 铁羽：沿扑击方向穿出，伤害是扑击的 ratio 倍
                    let direction = if c.vel.length_squared() > 0.01 { c.vel } else { target - p };
                    ctx.shots.fire(super::volley::ShotSpec {
                        pos: target,
                        angle: ops::atan2(direction.y, direction.x),
                        speed: f.speed,
                        life: f.life,
                        turn: 0.0,
                        hit_radius: reach,
                        knockback,
                        damage: lv.damage * f.ratio,
                        pierce: f.pierce,
                        target: None,
                        skip: Some(en.handle(t)),
                        big: false,
                        bonus: false,
                        flags: 0,
                        element,
                        source,
                        effects: super::volley::ShotEffects { execute, ..Default::default() },
                    });
                }
                if let Some(impact) = on_hit {
                    let radius = impact.radius * ctx.stats.get(Stat::Area);
                    let mut s = Strike::new(
                        target,
                        Area::Circle(radius),
                        lv.damage * impact.ratio,
                        source,
                        StrikeFx::Blast(lantern_content::BlastKind::Fire),
                    );
                    // 扑击打印记，余爆与火海不打印记，也不触发命中连锁
                    s.flags = HIT_DOT | HIT_NOCRIT;
                    ctx.strikes.0.push(s);
                    ctx.ground.add(
                        target,
                        radius,
                        lv.damage,
                        source,
                        impact.zone,
                        ctx.content.run.ground_cap as usize,
                    );
                }
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
