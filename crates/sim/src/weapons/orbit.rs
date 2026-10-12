//! 环绕：火焰绕着主角转，碰到的妖物受伤（灯火 / 不夜城）。

use bevy_math::Vec2;

use lantern_content::{Content, Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::WeaponSlot;
use crate::combat::{Hit, HitQueue, Source};
use crate::enemies::Enemies;
use crate::spatial::Grid;
use crate::stats::Stats;

pub(crate) fn update(
    content: &Content,
    stats: &Stats,
    grid: &Grid,
    en: &mut Enemies,
    p: Vec2,
    t: f32,
    slot: &mut WeaponSlot,
    hits: &mut HitQueue,
    found: &mut Vec<u32>,
) {
    let WeaponBehavior::Orbit { spin, hit_cooldown, knockback, size } = *slot.behavior(content) else {
        return;
    };
    let lv = slot.stats(content);
    let area = stats.get(Stat::Area);
    slot.prev_angle = slot.angle;
    slot.angle += spin.at(slot.level as f32) * DT;
    slot.count = lv.count + stats.amount();
    slot.radius = lv.radius * area;
    slot.size = size * area.sqrt();
    let source = Source::Weapon(slot.def as u16);
    for k in 0..slot.count {
        let c = p + slot.orbit_offset(slot.angle, k);
        found.clear();
        grid.query_circle(en, c.x, c.y, slot.size, found);
        for &i in found.iter() {
            let i = i as usize;
            if en.lamp_ready[i] > t {
                continue;
            }
            en.lamp_ready[i] = t + hit_cooldown;
            hits.0.push(Hit::new(en.handle(i), lv.damage, source).knock(knockback, p));
        }
    }
}
