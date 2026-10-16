//! 环绕：火焰绕着主角转，碰到的妖物受伤（灯火 / 不夜城）。不夜城另有一圈贴身的内环火海（持续伤害，不打印记）。

use bevy_math::Vec2;

use lantern_content::{Content, Element, Stat, WeaponBehavior};
use lantern_core::step::DT;

use super::WeaponSlot;
use crate::bamboo::Bamboo;
use crate::combat::{HIT_DOT, HIT_NOCRIT, Hit, HitQueue, Source};
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
    bamboo: &mut Bamboo,
    found: &mut Vec<u32>,
) {
    let WeaponBehavior::Orbit { spin, hit_cooldown, knockback, size, inner, ice_fire } =
        *slot.behavior(content)
    else {
        return;
    };
    let lv = slot.stats(content);
    let area = stats.get(Stat::Area);
    slot.prev_angle = slot.angle;
    slot.angle += spin.at(slot.level as f32) * DT;
    // 冰火两重天固定十盏，冰火各半，不吃数量加成
    slot.count = if ice_fire.is_some() { lv.count } else { lv.count + stats.amount() };
    slot.radius = lv.radius * area;
    slot.size = size * area;
    let source = Source::Weapon(slot.def as u16);
    let element = Some(content.weapons[slot.def].element);
    for k in 0..slot.count {
        let c = p + slot.orbit_offset(slot.angle, k);
        bamboo.circle(c, slot.size, lv.damage);
        found.clear();
        grid.query_circle(en, c.x, c.y, slot.size, found);
        for &i in found.iter() {
            let i = i as usize;
            if en.lamp_ready[i] > t {
                continue;
            }
            en.lamp_ready[i] = t + hit_cooldown;
            let mut hit = Hit::new(en.handle(i), lv.damage, source).knock(knockback, p).element(element);
            if let Some(f) = ice_fire {
                if k % 2 == 0 {
                    hit.element = Some(Element::Water);
                    hit.freeze = f.freeze;
                } else {
                    hit.element = Some(Element::Fire);
                    hit.ignite = f.ignite;
                }
            }
            hits.0.push(hit);
        }
    }
    if let Some(f) = inner {
        slot.inner_t -= DT;
        if slot.inner_t <= 0.0 {
            slot.inner_t = f.every;
            bamboo.circle(p, f.radius * area, lv.damage * f.ratio);
            found.clear();
            grid.query_circle(en, p.x, p.y, f.radius * area, found);
            for &i in found.iter() {
                let h = en.handle(i as usize);
                hits.0.push(Hit::new(h, lv.damage * f.ratio, source).flags(HIT_DOT | HIT_NOCRIT));
            }
        }
    }
}
