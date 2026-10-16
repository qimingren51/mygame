//! 孔明灯 / 万灯升（docs/BALANCE.md 第 6.3 节）：放飞的灯飘向妖物最密的地方，到时间落地爆燃，留下火海。
//!
//! 灯在 [`SkyLanterns`] 里，每步由 [`update_sky_lanterns`] 推进；火海进地裂的区域池（`drop::Fissures`）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{Element, FissureDef, Stat, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready, densest};
use crate::combat::{Area, Source, Strike, StrikeFx, Strikes};
use crate::enemies::Enemies;
use crate::spatial::Grid;
use crate::{GameContent, SimEvent, SimOutbox};

/// 一盏飘着的孔明灯。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SkyLantern {
    pub pos: Vec2,
    pub prev: Vec2,
    /// 要落的地方（每 retarget 秒在附近重新找）
    pub target: Vec2,
    /// 放飞了多久；到 fuse 落地
    pub t: f32,
    pub fuse: f32,
    pub next_retarget: f32,
    pub retarget: f32,
    pub speed: f32,
    pub radius: f32,
    pub damage: f32,
    pub cluster: f32,
    pub pick: u32,
    pub zone: FissureDef,
    pub source: Source,
    pub evolved: bool,
}

#[derive(Resource, Default, Debug)]
pub struct SkyLanterns(pub Vec<SkyLantern>);

impl SkyLanterns {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for l in &self.0 {
            for v in
                [l.pos.x, l.pos.y, l.target.x, l.target.y, l.t, l.fuse, l.next_retarget, l.radius, l.damage]
            {
                h.write_f32(v);
            }
        }
    }
}

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::SkyLantern { range, pick, cluster, spread, speed, fuse, retarget, zone } =
        *slot.behavior(ctx.content)
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
        let target = densest(ctx.grid, ctx.en, p, (range, pick, cluster, spread), &chosen, ctx.found)
            // 附近没有妖物（或都挨着已选的落点）：落在前方，几盏错开
            .unwrap_or_else(|| {
                let side = Vec2::new(-ctx.facing.y, ctx.facing.x)
                    * spread
                    * (k as f32 - (slot.count - 1) as f32 * 0.5);
                p + ctx.facing * 150.0 + side
            });
        chosen.push(target);
        ctx.lanterns.0.push(SkyLantern {
            pos: p,
            prev: p,
            target,
            t: 0.0,
            fuse,
            next_retarget: retarget,
            retarget,
            speed,
            radius,
            damage: lv.damage,
            cluster,
            pick,
            zone,
            source: Source::Weapon(slot.def as u16),
            evolved: slot.transformed(),
        });
    }
}

/// 灯飘过去、到时间落地：爆燃一圈（点 1 层灼烧），留下火海。
pub(crate) fn update_sky_lanterns(
    content: Res<GameContent>,
    grid: Res<Grid>,
    en: Res<Enemies>,
    mut lanterns: ResMut<SkyLanterns>,
    mut fissures: ResMut<super::drop::Fissures>,
    mut strikes: ResMut<Strikes>,
    mut outbox: ResMut<SimOutbox>,
    mut found: Local<Vec<u32>>,
) {
    let cap = content.0.run.ground_cap as usize;
    let mut k = 0;
    while k < lanterns.0.len() {
        let l = &mut lanterns.0[k];
        l.prev = l.pos;
        l.t += DT;
        if l.t >= l.next_retarget && l.t < l.fuse {
            l.next_retarget += l.retarget;
            // 在原落点附近重新找妖物最密的地方，跟着妖群走
            if let Some(t) =
                densest(&grid, &en, l.target, (l.cluster * 1.5, l.pick, l.cluster, 0.0), &[], &mut found)
            {
                l.target = t;
            }
        }
        let to = l.target - l.pos;
        let step = l.speed * DT;
        l.pos = if to.length() <= step { l.target } else { l.pos + to.normalize() * step };
        if l.t < l.fuse {
            k += 1;
            continue;
        }
        let l = lanterns.0.remove(k);
        let mut s = Strike::new(l.pos, Area::Circle(l.radius), l.damage, l.source, StrikeFx::None);
        s.element = Some(Element::Fire);
        s.ignite = 1.0;
        strikes.0.push(s);
        fissures.add(l.pos, l.radius, l.damage, l.source, l.zone, cap);
        outbox.0.push(SimEvent::LanternBurst { pos: l.pos, radius: l.radius, evolved: l.evolved });
    }
}
