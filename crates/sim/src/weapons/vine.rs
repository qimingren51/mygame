//! 青藤保留当前连线，拉远、隐身或死亡后才换目标；伤害与回复均走实际命中结算。

use bevy_math::Vec2;
use lantern_content::{Content, Stat, WeaponBehavior};
use lantern_core::{StateHasher, step::DT};

use super::{WeaponSlot, cooldown_ready};
use crate::combat::{Hard, Hit, HitQueue, Source, apply_hard};
use crate::enemies::{Enemies, EnemyHandle};
use crate::spatial::Grid;
use crate::stats::Stats;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VineLink {
    pub target: Option<EnemyHandle>,
    pub reconnect: f32,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VineState {
    pub links: Vec<VineLink>,
    pub bind_t: Option<f32>,
    pub heal_t: f32,
    pub heal_left: f32,
}

impl VineState {
    pub(crate) fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.links.len() as u32);
        for link in &self.links {
            h.write_u32(link.target.map_or(u32::MAX, EnemyHandle::raw));
            h.write_f32(link.reconnect);
        }
        h.write_f32(self.bind_t.unwrap_or(-1.0));
        h.write_f32(self.heal_t);
        h.write_f32(self.heal_left);
    }

    /// 一个法器共用一秒回复预算，不能因多目标、暴击或过量伤害突破。
    pub(crate) fn drain(&mut self, requested: f32) -> f32 {
        let amount = requested.max(0.0).min(self.heal_left);
        self.heal_left -= amount;
        amount
    }
}

pub(crate) fn update(
    content: &Content,
    stats: &Stats,
    grid: &Grid,
    en: &mut Enemies,
    player: Vec2,
    slot: &mut WeaponSlot,
    hits: &mut HitQueue,
    found: &mut Vec<u32>,
) {
    let WeaponBehavior::Vine { break_extra, reconnect, leech, heal_per_second, bind } =
        *slot.behavior(content)
    else {
        return;
    };
    let lv = slot.stats(content);
    slot.radius = lv.radius * stats.get(Stat::Area);
    // 与空间网格的单次近邻预算一致；正式构筑的数量远低于此值。
    slot.count = (lv.count + stats.amount()).min(64);
    let pulse = cooldown_ready(slot);
    if pulse {
        slot.timer = lv.cooldown * stats.get(Stat::Cooldown);
    }
    let state = slot.vine.get_or_insert_with(VineState::default);
    state.heal_t -= DT;
    if state.heal_t <= 0.0 {
        state.heal_t += 1.0;
        state.heal_left = heal_per_second.at(slot.level as f32);
    }
    state.links.resize_with(slot.count as usize, VineLink::default);
    let break_range = slot.radius + break_extra;
    let break_range2 = break_range * break_range;
    for link in &mut state.links {
        if let Some(target) = link.target {
            let valid = en.resolve(target).is_some_and(|i| {
                !en.cloaked[i] && Vec2::new(en.x[i], en.y[i]).distance_squared(player) <= break_range2
            });
            if !valid {
                link.target = None;
                link.reconnect = reconnect;
            }
        } else {
            link.reconnect = (link.reconnect - DT).max(0.0);
        }
    }
    if state.links.iter().any(|link| link.target.is_none() && link.reconnect <= 0.0) {
        grid.nearest_k(en, player.x, player.y, slot.radius, 64, found);
        let mut held: Vec<_> = state.links.iter().filter_map(|link| link.target).collect();
        for link in &mut state.links {
            if link.target.is_some() || link.reconnect > 0.0 {
                continue;
            }
            if let Some(target) = found.iter().map(|&i| en.handle(i as usize)).find(|h| !held.contains(h)) {
                link.target = Some(target);
                held.push(target);
            }
        }
    }
    let bind_now = bind.is_some_and(|b| {
        let period = b.every * stats.get(Stat::Cooldown);
        let timer = state.bind_t.get_or_insert(period);
        *timer -= DT;
        if *timer > 0.0 {
            false
        } else {
            *timer += period;
            true
        }
    });
    for link in &state.links {
        let Some(target) = link.target else { continue };
        let Some(i) = en.resolve(target) else { continue };
        if bind_now {
            let rank = content.enemies[en.kind[i] as usize].rank;
            apply_hard(en, i, rank, Hard::Root, bind.expect("缠绕参数").duration);
        }
        if pulse {
            let mut hit = Hit::new(target, lv.damage, Source::Weapon(slot.def as u16))
                .element(Some(content.weapons[slot.def].element))
                .knock(0.0, player);
            hit.leech = leech;
            hits.0.push(hit);
        }
    }
}
