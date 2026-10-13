//! 周期震波（霜铃 / 寒山钟）：以主角为中心震出一圈，伤害、击退、减速；
//! 进化后另有全屏钟鸣，冻结视野内的妖物（夜主除外）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_content::{Element, Rank, Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::{Ctx, WeaponSlot, cooldown_ready};
use crate::combat::{Area, HIT_DOT, HIT_NOCRIT, HIT_SHATTER, Source, Strike, StrikeFx};

pub(crate) fn update(ctx: &mut Ctx, slot: &mut WeaponSlot) {
    let WeaponBehavior::Pulse { knockback, slow, slow_time, toll, permafrost, ice_rain } =
        *slot.behavior(ctx.content)
    else {
        return;
    };
    let lv = slot.stats(ctx.content);
    let cd = ctx.stats.get(Stat::Cooldown);
    let source = Source::Weapon(slot.def as u16);
    slot.radius = lv.radius * ctx.stats.get(Stat::Area);
    if cooldown_ready(slot) {
        slot.timer = if permafrost.is_some() { lv.cooldown } else { lv.cooldown * cd };
        let r = lv.radius * ctx.stats.get(Stat::Area);
        let mut s = Strike::new(ctx.player, Area::Circle(r), lv.damage, source, StrikeFx::Pulse);
        if permafrost.is_some() {
            s.flags = HIT_DOT | HIT_NOCRIT;
            s.fx = StrikeFx::None;
        } else {
            s.element = Some(ctx.content.weapons[slot.def].element);
        }
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
            s.element = Some(ctx.content.weapons[slot.def].element);
            s.freeze = toll.freeze;
            s.boss_cap = toll.boss_cap;
            ctx.strikes.0.push(s);
            if let Some(rain) = ice_rain {
                // 两排错列冰剑覆盖视野，自上而下贯穿；数量固定，不受数量加成放大。
                let half_h = ctx.content.run.view_height * 0.5;
                let width = ctx.content.run.view_height * ctx.content.run.max_aspect;
                for k in 0..rain.count {
                    let col = k / 2;
                    let columns = rain.count.div_ceil(2);
                    let x = -width * 0.5 + width * (col as f32 + 0.5) / columns as f32;
                    let y = if k % 2 == 0 { -half_h - 20.0 } else { -20.0 };
                    ctx.shots.fire(super::volley::ShotSpec {
                        pos: ctx.player + Vec2::new(x, y),
                        angle: std::f32::consts::FRAC_PI_2,
                        speed: rain.speed,
                        life: rain.life,
                        turn: 0.0,
                        hit_radius: 15.0,
                        knockback: 0.0,
                        damage: rain.damage,
                        pierce: 999,
                        target: None,
                        skip: None,
                        big: true,
                        bonus: false,
                        flags: 0,
                        element: Some(Element::Water),
                        source,
                        effects: super::volley::ShotEffects {
                            freeze: rain.freeze,
                            boss_cap: rain.boss_cap,
                            ..Default::default()
                        },
                    });
                }
            }
        }
    }
}

/// 冻土内的小妖碎裂。每步至多八次；碎裂本身无印记、不能再触发碎裂。
pub(crate) fn shatter_deaths(
    content: Res<crate::GameContent>,
    stats: Res<crate::Stats>,
    arsenal: Res<super::Arsenal>,
    player: Single<&crate::Pos, With<crate::Player>>,
    deaths: Res<crate::combat::Deaths>,
    mut strikes: ResMut<crate::combat::Strikes>,
) {
    let mut budget = 8;
    for w in &arsenal.0 {
        let WeaponBehavior::Pulse { permafrost: Some(f), .. } = w.behavior(&content.0) else { continue };
        let lv = w.stats(&content.0);
        let radius = lv.radius * stats.get(Stat::Area);
        for d in &deaths.0 {
            if budget == 0 {
                return;
            }
            if !d.shatter
                || content.0.enemies[d.kind as usize].rank != Rank::Normal
                || d.pos.distance_squared(player.0) > radius * radius
            {
                continue;
            }
            let mut s = Strike::new(
                d.pos,
                Area::Circle(f.shatter_radius),
                lv.damage * f.shatter_ratio,
                Source::Weapon(w.def as u16),
                StrikeFx::Blast(lantern_content::BlastKind::Ice),
            );
            s.flags = HIT_DOT | HIT_NOCRIT | HIT_SHATTER;
            strikes.0.push(s);
            budget -= 1;
        }
    }
}
