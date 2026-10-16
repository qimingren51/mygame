//! 青藤 / 万木春（docs/BALANCE.md 第 6.3 节）：和附近最近的几只妖物各连一根藤，定时跳伤害、给主角回血；
//! 万木春每隔几秒把连着的妖物缠住。
//!
//! 连着谁记在 [`Vines`] 里（一件法器一组）；画面直接读它画藤。每跳回血走 `Action::Heal`，下一步结算。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{Action, Stat, WeaponBehavior};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::SimEvent;
use crate::combat::{Deferred, Hit, Source};
use crate::enemies::EnemyHandle;

/// 一根藤：连着谁；断了以后还要等多久才接新的。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Link {
    pub target: Option<EnemyHandle>,
    pub relink: f32,
}

/// 一件青藤的全部藤。
#[derive(Clone, Debug, PartialEq)]
pub struct VineSet {
    /// 哪件法器（`WeaponSlot.def`）
    pub def: usize,
    pub links: Vec<Link>,
    /// 离下一次缠绕还有多久（万木春）
    pub bind_t: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Vines(pub Vec<VineSet>);

impl Vines {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for v in &self.0 {
            h.write_u32(v.def as u32);
            h.write_f32(v.bind_t);
            h.write_u32(v.links.len() as u32);
            for l in &v.links {
                h.write_u32(l.target.map_or(u32::MAX, |t| t.raw()));
                h.write_f32(l.relink);
            }
        }
    }
}

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Vine { leash, relink, lifesteal, heal_cap, heal_per_level, bind_every, bind } =
        *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let reach = lv.radius * ctx.stats.get(Stat::Area);
    slot.radius = reach;
    slot.count = lv.count + ctx.stats.amount();
    let p = ctx.player;
    let en = ctx.en;
    let k = match ctx.vines.0.iter().position(|v| v.def == slot.def) {
        Some(k) => k,
        None => {
            ctx.vines.0.push(VineSet { def: slot.def, links: Vec::new(), bind_t: bind_every });
            ctx.vines.0.len() - 1
        }
    };
    let set = &mut ctx.vines.0[k];
    set.links.resize(slot.count as usize, Link { target: None, relink: 0.0 });
    // 断藤：目标死了或走出 reach + leash
    let at = |i: usize| Vec2::new(en.x[i], en.y[i]);
    for l in &mut set.links {
        if let Some(t) = l.target {
            let keep = en.resolve(t).is_some_and(|i| at(i).distance(p) <= reach + leash);
            if !keep {
                l.target = None;
                l.relink = relink;
            }
        }
    }
    // 接藤：断了的等 relink 秒，再接 reach 以内还没连上的最近一只
    let mut looked = false;
    for j in 0..set.links.len() {
        if set.links[j].target.is_some() {
            continue;
        }
        set.links[j].relink -= DT;
        if set.links[j].relink > 0.0 {
            continue;
        }
        if !looked {
            ctx.grid.nearest_k(en, p.x, p.y, reach, 64, ctx.found);
            looked = true;
        }
        let taken = |h: EnemyHandle| set.links.iter().any(|l| l.target == Some(h));
        if let Some(&i) = ctx.found.iter().find(|&&i| !taken(en.handle(i as usize))) {
            set.links[j].target = Some(en.handle(i as usize));
        }
    }
    if bind_every > 0.0 {
        set.bind_t -= DT;
    }
    if !cooldown_ready(slot) {
        return;
    }
    let every = lv.cooldown * ctx.stats.get(Stat::Cooldown);
    slot.timer = every;
    // 缠绕跟着到点后的这一跳一起上
    let binding = bind_every > 0.0 && set.bind_t <= 0.0;
    if binding {
        set.bind_t = bind_every;
    }
    let source = Source::Weapon(slot.def as u16);
    let element = Some(ctx.content.weapons[slot.def].element);
    let mut dealt = 0.0;
    for l in &set.links {
        let Some(i) = l.target.and_then(|t| en.resolve(t)) else {
            continue;
        };
        let mut hit = Hit::new(en.handle(i), lv.damage, source).element(element);
        if binding {
            hit.root = bind;
        }
        ctx.hits.0.push(hit);
        dealt += lv.damage;
        ctx.outbox.0.push(SimEvent::VineDrain { pos: at(i), bind: binding, evolved: slot.transformed() });
    }
    // 回血按这一跳的基础伤害乘伤害倍率算；每秒上限折到这一跳
    let cap = (heal_cap + heal_per_level * slot.level as f32) * every;
    let heal = (dealt * ctx.stats.get(Stat::Damage) * lifesteal).min(cap);
    if heal > 0.0 {
        ctx.actions.0.push(Deferred { action: Action::Heal(heal), pos: p, target: None });
    }
}
