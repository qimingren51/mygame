//! 扇形挥击（铜钱剑 / 天罡，docs/BALANCE.md 第 6.3 节）：每次冷却好了朝最近的妖物挥一道扇形剑气，
//! 扇形里按距离从近到远最多打 count 只；天罡是一整圈，暴击的那一下再斩一次（在命中结算里）。

use bevy_math::{Vec2, ops};
use lantern_content::{Stat, WeaponBehavior};

use super::{Ctx, TAU, WeaponSlot, cooldown_ready};
use crate::SimEvent;
use crate::combat::{Hit, Source};

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Sweep { arc, aim, knockback, crit_bonus, echo } = *slot.behavior(ctx.content) else {
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
    let en = ctx.en;
    let full = arc >= TAU - 1e-3;
    // 方向：radius + aim 以内最近的妖物（锁定不到的不算），没有就朝面向
    ctx.grid.nearest_k(en, p.x, p.y, r + aim, 1, ctx.found);
    let dir = ctx
        .found
        .first()
        .and_then(|&i| (Vec2::new(en.x[i as usize], en.y[i as usize]) - p).try_normalize())
        .or_else(|| ctx.facing.try_normalize())
        .unwrap_or(Vec2::X);
    slot.prev_angle = slot.angle;
    slot.angle = ops::atan2(dir.y, dir.x);
    // 扇形里的妖物：距离加上妖物半径（同范围打击），角度看妖物中心；按距离从近到远，同距离按槽位
    ctx.found.clear();
    ctx.grid.query_circle(en, p.x, p.y, r, ctx.found);
    let cos_half = ops::cos(arc * 0.5);
    ctx.found.retain(|&i| {
        let to = Vec2::new(en.x[i as usize], en.y[i as usize]) - p;
        full || to.length_squared() < 1e-6 || to.normalize().dot(dir) >= cos_half
    });
    ctx.found.sort_by(|&a, &b| {
        let da = Vec2::new(en.x[a as usize], en.y[a as usize]).distance_squared(p);
        let db = Vec2::new(en.x[b as usize], en.y[b as usize]).distance_squared(p);
        da.total_cmp(&db).then(a.cmp(&b))
    });
    ctx.found.truncate(slot.count as usize);
    let source = Source::Weapon(slot.def as u16);
    let element = Some(ctx.content.weapons[slot.def].element);
    for &i in ctx.found.iter() {
        let mut hit = Hit::new(en.handle(i as usize), lv.damage, source).knock(knockback, p).element(element);
        hit.crit_bonus = crit_bonus;
        hit.echo = echo;
        ctx.hits.0.push(hit);
    }
    // 竹丛：一整圈按圆，扇形按扇心的一个圆近似
    if full {
        ctx.bamboo.circle(p, r, lv.damage);
    } else {
        ctx.bamboo.circle(p + dir * r * 0.5, r * 0.5, lv.damage);
    }
    ctx.outbox.0.push(SimEvent::Sweep {
        pos: p,
        dir,
        arc,
        radius: r,
        weapon: slot.def as u16,
        evolved: full,
    });
}
