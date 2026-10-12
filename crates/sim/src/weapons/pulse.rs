//! 周期震波（霜铃 / 寒山钟）：以主角为中心震出一圈，伤害、击退、减速；
//! 进化后另有全屏钟鸣，冻结视野内的妖物（夜主除外）。

use lantern_content::{Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::combat::{Area, Source, Strike, StrikeFx};

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Pulse { knockback, slow, slow_time, toll } = *slot.behavior(ctx.content) else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let cd = ctx.stats.get(Stat::Cooldown);
    let source = Source::Weapon(slot.def as u16);
    if cooldown_ready(slot) {
        slot.timer = lv.cooldown * cd;
        let r = lv.radius * ctx.stats.get(Stat::Area);
        let mut s = Strike::new(ctx.player, Area::Circle(r), lv.damage, source, StrikeFx::Pulse);
        s.knockback = knockback;
        s.slow = slow;
        s.slow_time = slow_time;
        ctx.strikes.0.push(s);
    }
    if let Some(toll) = toll {
        let t = slot.toll.get_or_insert(toll.period);
        *t -= DT;
        if *t <= 0.0 {
            *t = toll.period * cd;
            let mut s = Strike::new(ctx.player, Area::Screen(30.0), toll.damage, source, StrikeFx::Toll);
            s.freeze = toll.freeze;
            s.boss_cap = toll.boss_cap;
            ctx.strikes.0.push(s);
        }
    }
}
