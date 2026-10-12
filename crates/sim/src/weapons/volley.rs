//! 追踪齐射（符剑 / 万剑归宗），以及全部飞剑（含金·锐的追加飞剑）的飞行与命中。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{Element, Stat, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::SimEvent;
use crate::combat::{Hit, HitQueue, Source};
use crate::enemies::{Enemies, EnemyHandle};
use crate::spatial::Grid;

const PI: f32 = std::f32::consts::PI;
const TAU: f32 = std::f32::consts::TAU;

/// 同时存在的飞剑上限
pub const SHOT_CAP: usize = 512;
/// 每把剑记住最近命中过的几只妖物（穿透时不重复命中）
const HIT_MEMORY: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Shot {
    pub pos: Vec2,
    pub prev: Vec2,
    pub vel: Vec2,
    pub damage: f32,
    pub pierce: u32,
    pub life: f32,
    pub turn: f32,
    pub hit_radius: f32,
    pub knockback: f32,
    pub target: Option<EnemyHandle>,
    /// 进化后的大剑（画面用）
    pub big: bool,
    /// 金·锐追加的飞剑
    pub bonus: bool,
    /// 命中时带的标记（[`crate::combat`] 的 HIT_*）与五行
    pub flags: u8,
    pub element: Option<Element>,
    pub source: Source,
    hits: [Option<EnemyHandle>; HIT_MEMORY],
    hit_n: u8,
}

impl Shot {
    fn has_hit(&self, h: EnemyHandle) -> bool {
        self.hits.contains(&Some(h))
    }

    fn mark_hit(&mut self, h: EnemyHandle) {
        self.hits[self.hit_n as usize % HIT_MEMORY] = Some(h);
        self.hit_n = self.hit_n.wrapping_add(1);
    }
}

/// 发射一把飞剑需要的参数。
#[derive(Clone, Copy, Debug)]
pub struct ShotSpec {
    pub pos: Vec2,
    pub angle: f32,
    pub speed: f32,
    pub life: f32,
    pub turn: f32,
    pub hit_radius: f32,
    pub knockback: f32,
    pub damage: f32,
    pub pierce: u32,
    pub target: Option<EnemyHandle>,
    /// 不会命中这只（金刃从它身上迸出）
    pub skip: Option<EnemyHandle>,
    pub big: bool,
    pub bonus: bool,
    pub flags: u8,
    pub element: Option<Element>,
    pub source: Source,
}

#[derive(Resource, Default, Debug)]
pub struct Shots(pub Vec<Shot>);

impl Shots {
    pub fn fire(&mut self, s: ShotSpec) {
        if self.0.len() >= SHOT_CAP {
            return;
        }
        let (sin, cos) = ops::sin_cos(s.angle);
        let mut hits = [None; HIT_MEMORY];
        hits[0] = s.skip;
        self.0.push(Shot {
            pos: s.pos,
            prev: s.pos,
            vel: Vec2::new(cos, sin) * s.speed,
            damage: s.damage,
            pierce: s.pierce,
            life: s.life,
            turn: s.turn,
            hit_radius: s.hit_radius,
            knockback: s.knockback,
            target: s.target,
            big: s.big,
            bonus: s.bonus,
            flags: s.flags,
            element: s.element,
            source: s.source,
            hits,
            hit_n: u8::from(s.skip.is_some()),
        });
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for s in &self.0 {
            h.write_f32(s.pos.x);
            h.write_f32(s.pos.y);
            h.write_u32(s.pierce);
        }
    }
}

/// 冷却到了就朝最近的妖物齐射，扇形展开。
pub(crate) fn fire(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Volley { range, speed, life, turn, hit_radius, knockback, spread, retry } =
        *slot.behavior(ctx.content)
    else {
        return;
    };
    if !cooldown_ready(slot) {
        return;
    }
    let lv = slot.stats(ctx.content);
    let count = lv.count + ctx.stats.amount();
    let p = ctx.player;
    let element = Some(ctx.content.weapons[slot.def].element);
    let (speed, life) = (speed * ctx.stats.get(Stat::ProjSpeed), life * ctx.stats.get(Stat::ProjLife));
    ctx.grid.nearest_k(ctx.en, p.x, p.y, range, count as usize, ctx.found);
    let n = ctx.found.len();
    if n == 0 {
        slot.timer = retry;
        return;
    }
    slot.timer = lv.cooldown * ctx.stats.get(Stat::Cooldown);
    for i in 0..count {
        let t = ctx.found[i as usize % n] as usize;
        let base = ops::atan2(ctx.en.y[t] - p.y, ctx.en.x[t] - p.x);
        let angle = base + (i as f32 - (count as f32 - 1.0) / 2.0) * spread;
        ctx.shots.fire(ShotSpec {
            pos: p,
            angle,
            speed,
            life,
            turn,
            hit_radius,
            knockback,
            damage: lv.damage,
            pierce: lv.pierce,
            target: Some(ctx.en.handle(t)),
            skip: None,
            big: slot.evolved,
            bonus: false,
            flags: 0,
            element,
            source: Source::Weapon(slot.def as u16),
        });
    }
    ctx.outbox.0.push(SimEvent::SwordFired { weapon: slot.def as u16 });
}

/// 飞剑飞行：追踪目标（转向有上限），碰到妖物造成伤害，穿透次数用完或寿命到了就消失。
pub(crate) fn update_shots(
    grid: Res<Grid>,
    en: Res<Enemies>,
    mut shots: ResMut<Shots>,
    mut hits: ResMut<HitQueue>,
    mut found: Local<Vec<u32>>,
) {
    let list = &mut shots.0;
    let mut k = 0;
    while k < list.len() {
        let s = &mut list[k];
        s.prev = s.pos;
        s.life -= DT;
        if s.life <= 0.0 {
            list.swap_remove(k);
            continue;
        }
        if let Some(h) = s.target {
            match en.resolve(h) {
                Some(t) => {
                    let want = ops::atan2(en.y[t] - s.pos.y, en.x[t] - s.pos.x);
                    let cur = ops::atan2(s.vel.y, s.vel.x);
                    let mut diff = want - cur;
                    while diff > PI {
                        diff -= TAU;
                    }
                    while diff < -PI {
                        diff += TAU;
                    }
                    let step = diff.clamp(-s.turn * DT, s.turn * DT);
                    let sp = s.vel.length();
                    let (sin, cos) = ops::sin_cos(cur + step);
                    s.vel = Vec2::new(cos, sin) * sp;
                }
                None => s.target = None,
            }
        }
        s.pos += s.vel * DT;
        found.clear();
        grid.query_circle(&en, s.pos.x, s.pos.y, s.hit_radius, &mut found);
        let mut alive = true;
        for &e in found.iter() {
            let e = e as usize;
            if !en.alive[e] {
                continue;
            }
            let h = en.handle(e);
            if s.has_hit(h) {
                continue;
            }
            s.mark_hit(h);
            if s.target == Some(h) {
                s.target = None;
            }
            hits.0.push(
                Hit::new(h, s.damage, s.source).knock(s.knockback, s.pos).flags(s.flags).element(s.element),
            );
            s.pierce = s.pierce.saturating_sub(1);
            if s.pierce == 0 {
                alive = false;
                break;
            }
        }
        if alive {
            k += 1;
        } else {
            list.swap_remove(k);
        }
    }
}
