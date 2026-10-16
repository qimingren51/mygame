//! 落印（山印 / 镇岳）：从附近的妖物里随机选落点，预警之后依次落下，范围伤害并击晕；
//! 进化后落点留下地裂，持续伤害并减速。
//!
//! 地裂和异化、合璧留下的凤火、竹墙、剑林共用 [`Fissures`] 这个区域池（docs/DESIGN.md 第 6.5 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{Element, FissureDef, GroundKind, Stat, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::GameContent;
use crate::combat::{Area, HIT_DOT, HIT_NOCRIT, Hit, HitQueue, Source, Strike, StrikeFx, Strikes};

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

impl Seals {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for s in &self.0 {
            for v in [s.pos.x, s.pos.y, s.radius, s.t, s.delay, s.damage] {
                h.write_f32(v);
            }
            h.write_u32(s.fissure.map_or(0, |f| f.kind as u32 + 1));
        }
    }
}

/// 地裂（以及凤火、竹墙、剑林）。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Fissure {
    pub kind: GroundKind,
    pub pos: Vec2,
    pub radius: f32,
    pub life: f32,
    pub max_life: f32,
    pub tick: f32,
    pub every: f32,
    pub damage: f32,
    pub slow: f32,
    pub slow_time: f32,
    /// 软墙：普通妖物在区域里的移速倍率（不是墙时为 None）
    pub wall: Option<f32>,
    pub source: Source,
}

#[derive(Resource, Default, Debug)]
pub struct Fissures(pub Vec<Fissure>);

/// 一块竹墙：移动阶段每步收集一次，查询时只看墙，不扫整个区域池。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Wall {
    pub pos: Vec2,
    pub r2: f32,
    pub speed: f32,
}

impl Fissures {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for z in &self.0 {
            h.write_u32(z.kind as u32);
            for v in [z.pos.x, z.pos.y, z.radius, z.life, z.tick, z.damage] {
                h.write_f32(v);
            }
        }
    }

    /// 放一块区域；池里已有 cap 块时先去掉最早的一块。
    pub fn add(&mut self, pos: Vec2, radius: f32, damage: f32, source: Source, f: FissureDef, cap: usize) {
        if self.0.len() >= cap.max(1) {
            self.0.remove(0);
        }
        self.0.push(Fissure {
            kind: f.kind,
            pos,
            radius: radius * f.radius_scale,
            life: f.life,
            max_life: f.life,
            tick: 0.0,
            every: f.tick,
            damage: damage * f.damage_scale,
            slow: f.slow,
            slow_time: f.slow_time,
            wall: f.wall,
            source,
        });
    }

    /// 收集还在的竹墙（每步一次）。
    pub fn collect_walls(&self, out: &mut Vec<Wall>) {
        out.clear();
        out.extend(
            self.0
                .iter()
                .filter(|f| f.life > 0.0)
                .filter_map(|f| f.wall.map(|speed| Wall { pos: f.pos, r2: f.radius * f.radius, speed })),
        );
    }

    /// 某点的竹墙移速倍率（叠在一起取最慢的一块；不在墙里为 1）。
    pub fn wall_speed(walls: &[Wall], pos: Vec2) -> f32 {
        walls.iter().filter(|w| w.pos.distance_squared(pos) < w.r2).fold(1.0, |m, w| m.min(w.speed))
    }
}

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
            evolved: slot.transformed(),
            source: Source::Weapon(slot.def as u16),
            element: Some(ctx.content.weapons[slot.def].element),
        });
    }
}

/// 石印落地、留下区域。
pub(crate) fn update_seals(
    content: Res<GameContent>,
    mut seals: ResMut<Seals>,
    mut fissures: ResMut<Fissures>,
    mut strikes: ResMut<Strikes>,
) {
    let cap = content.0.run.ground_cap as usize;
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
            match s.fissure.map(|f| f.kind) {
                Some(GroundKind::Bamboo) => StrikeFx::Bamboo,
                Some(GroundKind::Sword) => StrikeFx::SwordGrove,
                _ => StrikeFx::Seal { evolved: s.evolved },
            },
        );
        strike.knockback = s.knockback;
        strike.stun = s.stun;
        strike.element = s.element;
        strikes.0.push(strike);
        if let Some(f) = s.fissure {
            fissures.add(s.pos, s.radius, s.damage, s.source, f, cap);
        }
    }
}

/// 区域跳伤害：同类区域覆盖同一只妖物时只算每秒伤害最高的一块（相同取最早的），地裂、剑林、凤火都不叠加。
/// 跳伤害时也打竹丛，和范围打击一样。
pub(crate) fn update_ground(
    mut fissures: ResMut<Fissures>,
    grid: Res<crate::spatial::Grid>,
    en: Res<crate::enemies::Enemies>,
    mut hits: ResMut<HitQueue>,
    mut bamboo: ResMut<crate::bamboo::Bamboo>,
    mut found: Local<Vec<u32>>,
) {
    for f in &mut fissures.0 {
        f.life -= DT;
        f.tick -= DT;
    }
    fissures.0.retain(|f| f.life > 0.0);
    let zones = &fissures.0;
    for (k, f) in zones.iter().enumerate() {
        // 竹墙不造成伤害，由移动阶段阻挡，不制造零伤害数字与受击闪白
        if f.tick > 0.0 || (f.damage <= 0.0 && f.slow <= 0.0) {
            continue;
        }
        bamboo.circle(f.pos, f.radius, f.damage);
        let rate = f.damage / f.every;
        found.clear();
        grid.query_circle(&en, f.pos.x, f.pos.y, f.radius, &mut found);
        for &i in found.iter() {
            let i = i as usize;
            let pos = Vec2::new(en.x[i], en.y[i]);
            let stronger = zones.iter().enumerate().any(|(j, other)| {
                if j == k || other.kind != f.kind {
                    return false;
                }
                let reach = other.radius + en.r[i];
                let r = other.damage / other.every;
                other.pos.distance_squared(pos) <= reach * reach && (r > rate || (r == rate && j < k))
            });
            if stronger {
                continue;
            }
            let mut hit = Hit::new(en.handle(i), f.damage, f.source).flags(HIT_DOT | HIT_NOCRIT);
            hit.from = f.pos;
            hit.slow = f.slow;
            hit.slow_time = f.slow_time;
            hits.0.push(hit);
        }
    }
    for f in &mut fissures.0 {
        if f.tick <= 0.0 {
            f.tick = f.every;
        }
    }
}
