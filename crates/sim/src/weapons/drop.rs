//! 落印（山印 / 镇岳）：从附近的妖物里随机选落点，预警之后依次落下，范围伤害并击晕；
//! 进化后落点留下地裂，持续伤害并减速。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{Element, FissureDef, Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::combat::{Area, HIT_DOT, HIT_NOCRIT, Source, Strike, StrikeFx, Strikes};

/// 一枚正在落下的石印。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SealDrop {
    pub pos: Vec2,
    pub radius: f32,
    /// 从负数开始计时（依次落下），到 delay 时落地
    pub t: f32,
    pub delay: f32,
    pub damage: f32,
    pub knockback: f32,
    pub stun: f32,
    pub fissure: Option<FissureDef>,
    pub evolved: bool,
    pub source: Source,
    pub element: Option<Element>,
}

#[derive(Resource, Default, Debug)]
pub struct Seals(pub Vec<SealDrop>);

/// 地裂。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Fissure {
    pub pos: Vec2,
    pub radius: f32,
    pub life: f32,
    pub max_life: f32,
    pub tick: f32,
    pub every: f32,
    pub damage: f32,
    pub slow: f32,
    pub slow_time: f32,
    pub source: Source,
}

#[derive(Resource, Default, Debug)]
pub struct Fissures(pub Vec<Fissure>);

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Drop {
        range,
        candidates,
        delay,
        stagger,
        knockback,
        stun,
        scatter,
        amount_div,
        fissure,
    } = *slot.behavior(ctx.content)
    else {
        return;
    };
    if !cooldown_ready(slot) {
        return;
    }
    let lv = slot.stats(ctx.content);
    slot.timer = lv.cooldown * ctx.stats.get(Stat::Cooldown);
    let count = lv.count + ctx.stats.amount() / amount_div;
    let radius = lv.radius * ctx.stats.get(Stat::Area);
    let p = ctx.player;
    ctx.grid.nearest_k(ctx.en, p.x, p.y, range, candidates as usize, ctx.found);
    for i in 0..count {
        let pos = if ctx.found.is_empty() {
            p + Vec2::new(ctx.rng.range_f32(-scatter.0, scatter.0), ctx.rng.range_f32(-scatter.1, scatter.1))
        } else {
            // 从候选里随机取一个并移除
            let j = ctx.rng.below(ctx.found.len() as u32) as usize;
            let e = ctx.found.swap_remove(j) as usize;
            Vec2::new(ctx.en.x[e], ctx.en.y[e])
        };
        ctx.seals.0.push(SealDrop {
            pos,
            radius,
            t: -(i as f32) * stagger,
            delay,
            damage: lv.damage,
            knockback,
            stun,
            fissure,
            evolved: slot.evolved,
            source: Source::Weapon(slot.def as u16),
            element: Some(ctx.content.weapons[slot.def].element),
        });
    }
}

/// 石印落地、地裂跳伤害。
pub(crate) fn update_seals(
    mut seals: ResMut<Seals>,
    mut fissures: ResMut<Fissures>,
    mut strikes: ResMut<Strikes>,
) {
    let mut k = 0;
    while k < seals.0.len() {
        let s = &mut seals.0[k];
        s.t += DT;
        if s.t < s.delay {
            k += 1;
            continue;
        }
        let s = seals.0.remove(k);
        let mut strike = Strike::new(
            s.pos,
            Area::Circle(s.radius),
            s.damage,
            s.source,
            StrikeFx::Seal { evolved: s.evolved },
        );
        strike.knockback = s.knockback;
        strike.stun = s.stun;
        strike.element = s.element;
        strikes.0.push(strike);
        if let Some(f) = s.fissure {
            fissures.0.push(Fissure {
                pos: s.pos,
                radius: s.radius * f.radius_scale,
                life: f.life,
                max_life: f.life,
                tick: 0.0,
                every: f.tick,
                damage: s.damage * f.damage_scale,
                slow: f.slow,
                slow_time: f.slow_time,
                source: s.source,
            });
        }
    }
    let mut k = 0;
    while k < fissures.0.len() {
        let f = &mut fissures.0[k];
        f.life -= DT;
        f.tick -= DT;
        if f.tick <= 0.0 {
            f.tick = f.every;
            let mut s = Strike::new(f.pos, Area::Circle(f.radius), f.damage, f.source, StrikeFx::None);
            s.flags = HIT_DOT | HIT_NOCRIT;
            s.slow = f.slow;
            s.slow_time = f.slow_time;
            strikes.0.push(s);
        }
        if f.life <= 0.0 {
            fissures.0.remove(k);
        } else {
            k += 1;
        }
    }
}
