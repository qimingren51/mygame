//! 沧浪 / 北冥潮（docs/BALANCE.md 第 6.3 节）：推出去的浪碰到妖物就打一下、减速，再推着它走一段。
//!
//! 浪在 [`Waves`] 里，每步由 [`update_waves`] 推进。前沿扫过的妖物记进 `touched`（每道浪每只只打一次）；
//! 推的时候每步把它的击退速度设成浪速，推够了就松手，松手后击退余速还会再滑 speed / KNOCK_DECAY。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{Element, Rank, Stat, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::combat::{Hit, HitQueue, Source};
use crate::enemies::{Enemies, EnemyHandle};
use crate::movement::KNOCK_DECAY;
use crate::spatial::Grid;
use crate::{GameContent, SimEvent};

/// 被一道浪碰到的妖物：往哪推、还要推多远。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Touched {
    pub target: EnemyHandle,
    pub dir: Vec2,
    pub left: f32,
}

/// 一道浪。
#[derive(Clone, Debug, PartialEq)]
pub struct Wave {
    pub origin: Vec2,
    /// 直线浪的方向（环形浪不用）
    pub dir: Vec2,
    /// 前沿走了多远（环形浪：当前半径）；prev 是上一步的
    pub s: f32,
    pub prev: f32,
    /// 走到这里散掉（直线：travel；环形：radius）
    pub reach: f32,
    /// 直线浪的半宽
    pub half: f32,
    pub speed: f32,
    pub push: f32,
    pub damage: f32,
    pub slow: f32,
    pub slow_time: f32,
    pub freeze: f32,
    pub ring: bool,
    /// 下一次砍竹丛的位置（直线浪每走一个半宽砍一圈）
    pub next_cut: f32,
    pub source: Source,
    pub element: Option<Element>,
    pub evolved: bool,
    pub touched: Vec<Touched>,
}

#[derive(Resource, Default, Debug)]
pub struct Waves(pub Vec<Wave>);

impl Waves {
    /// 空的时候什么都不写：没带这件法器的局，哈希和加它之前一样。
    pub fn hash_into(&self, h: &mut StateHasher) {
        if self.0.is_empty() {
            return;
        }
        h.write_u32(self.0.len() as u32);
        for w in &self.0 {
            for v in [w.origin.x, w.origin.y, w.dir.x, w.dir.y, w.s, w.reach, w.half, w.damage] {
                h.write_f32(v);
            }
            h.write_u32(w.touched.len() as u32);
            for t in &w.touched {
                h.write_u32(t.target.raw());
                h.write_f32(t.left);
            }
        }
    }
}

fn rotate(v: Vec2, a: f32) -> Vec2 {
    let (s, c) = (ops::sin(a), ops::cos(a));
    Vec2::new(v.x * c - v.y * s, v.x * s + v.y * c)
}

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Wave { speed, travel, push, slow, slow_time, spread, ring, freeze } =
        *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let r = lv.radius * ctx.stats.get(Stat::Area);
    slot.radius = r;
    slot.count = lv.count + ctx.stats.amount();
    if !cooldown_ready(slot) {
        return;
    }
    slot.timer = lv.cooldown * ctx.stats.get(Stat::Cooldown);
    let p = ctx.player;
    // 走着就朝面向；站着不动时朝浪够得着的最近一只
    let aim = if ctx.moving {
        None
    } else {
        ctx.grid.nearest_k(ctx.en, p.x, p.y, travel + r, 1, ctx.found);
        ctx.found
            .first()
            .and_then(|&i| (Vec2::new(ctx.en.x[i as usize], ctx.en.y[i as usize]) - p).try_normalize())
    };
    let base = aim.or_else(|| ctx.facing.try_normalize()).unwrap_or(Vec2::X);
    // 环形浪只有一圈；直线浪按数量，第 2、3 道左右各偏 spread，再往外依次加
    let n = if ring { 1 } else { slot.count.max(1) };
    let source = Source::Weapon(slot.def as u16);
    let element = Some(ctx.content.weapons[slot.def].element);
    for k in 0..n {
        let side = if k % 2 == 1 { 1.0 } else { -1.0 };
        let dir = rotate(base, spread * k.div_ceil(2) as f32 * side);
        ctx.waves.0.push(Wave {
            origin: p,
            dir,
            s: 0.0,
            prev: 0.0,
            reach: if ring { r } else { travel },
            half: r,
            speed,
            push,
            damage: lv.damage,
            slow,
            slow_time,
            freeze,
            ring,
            next_cut: r,
            source,
            element,
            evolved: slot.transformed(),
            touched: Vec::new(),
        });
        ctx.outbox.0.push(SimEvent::Wave { pos: p, dir, radius: r, ring, evolved: slot.transformed() });
    }
}

/// 浪往前走：前沿扫过的妖物打一下、记下来，推着走；走到头散掉。
pub(crate) fn update_waves(
    content: Res<GameContent>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut waves: ResMut<Waves>,
    mut hits: ResMut<HitQueue>,
    mut bamboo: ResMut<crate::bamboo::Bamboo>,
    mut found: Local<Vec<u32>>,
) {
    let en = &mut *en;
    let mut k = 0;
    while k < waves.0.len() {
        let w = &mut waves.0[k];
        w.prev = w.s;
        w.s = (w.s + w.speed * DT).min(w.reach);
        // 前沿这一步扫过的带子：直线浪是 [prev, s] × 半宽的长条，环形浪是 prev 到 s 的圆环
        found.clear();
        if w.ring {
            grid.query_circle(en, w.origin.x, w.origin.y, w.s, &mut found);
            bamboo.ring(w.origin, w.prev, w.s, w.damage);
        } else {
            let c = w.origin + w.dir * (w.prev + w.s) * 0.5;
            let r = (w.half * w.half + (w.s - w.prev) * (w.s - w.prev) * 0.25).sqrt();
            grid.query_circle(en, c.x, c.y, r, &mut found);
            while w.next_cut <= w.s {
                bamboo.circle(w.origin + w.dir * w.next_cut, w.half, w.damage);
                w.next_cut += w.half;
            }
        }
        for &i in found.iter() {
            let i = i as usize;
            let h = en.handle(i);
            if w.touched.iter().any(|t| t.target == h) {
                continue;
            }
            let at = Vec2::new(en.x[i], en.y[i]);
            let er = en.r[i];
            let rel = at - w.origin;
            let swept = if w.ring {
                let d = rel.length();
                d + er >= w.prev && d - er <= w.s
            } else {
                let along = rel.dot(w.dir);
                along + er >= w.prev && along - er <= w.s && rel.perp_dot(w.dir).abs() <= w.half + er
            };
            if !swept {
                continue;
            }
            let mut hit = Hit::new(h, w.damage, w.source).element(w.element);
            hit.slow = w.slow;
            hit.slow_time = w.slow_time;
            hit.freeze = w.freeze;
            hits.0.push(hit);
            let push = match content.0.enemies[en.kind[i] as usize].rank {
                Rank::Boss => 0.0,
                Rank::Elite => w.push * 0.5,
                _ => w.push,
            };
            let dir = if w.ring { rel.try_normalize().unwrap_or(w.dir) } else { w.dir };
            // 松手后击退余速还会滑 speed / KNOCK_DECAY，先扣掉
            w.touched.push(Touched { target: h, dir, left: (push - w.speed / KNOCK_DECAY).max(0.0) });
        }
        // 推着走：击退速度设成浪速，下一步移动时生效
        for t in &mut w.touched {
            if t.left <= 0.0 {
                continue;
            }
            match en.resolve(t.target) {
                Some(i) => {
                    en.kx[i] = t.dir.x * w.speed;
                    en.ky[i] = t.dir.y * w.speed;
                    t.left -= w.speed * DT;
                }
                None => t.left = 0.0,
            }
        }
        if w.s >= w.reach {
            waves.0.remove(k);
        } else {
            k += 1;
        }
    }
}
