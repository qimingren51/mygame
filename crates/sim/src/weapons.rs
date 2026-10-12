//! 法器（移植自网页版 sim/weapons.ts）。每种行为一个分支，数值来自 `weapons.ron`。
//! M1 只有环绕（灯火）；符剑、霜铃、纸鹤、山印与进化在 M2 加入。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::WeaponBehavior;
use lantern_core::StateHasher;
use lantern_core::step::DT;

use crate::combat::{Hit, HitQueue};
use crate::enemies::Enemies;
use crate::run::Stats;
use crate::spatial::Grid;
use crate::{GameContent, Player, Pos, Tick};

const TAU: f32 = std::f32::consts::TAU;

#[derive(Clone, Debug)]
pub struct WeaponSlot {
    /// `weapons.ron` 里的下标
    pub def: usize,
    /// 等级，从 1 开始
    pub level: u32,
    /// 环绕类法器的当前角度与上一步角度（画面插值用）
    pub angle: f32,
    pub prev_angle: f32,
    /// 本步实际生效的数量、半径、判定大小（画面直接照着画）
    pub count: u32,
    pub radius: f32,
    pub size: f32,
}

impl WeaponSlot {
    pub fn new(def: usize) -> Self {
        WeaponSlot { def, level: 1, angle: 0.0, prev_angle: 0.0, count: 0, radius: 0.0, size: 0.0 }
    }

    /// 第 k 个环绕物在给定角度下相对主角的位置。
    pub fn orbit_offset(&self, angle: f32, k: u32) -> Vec2 {
        let a = angle + k as f32 * TAU / self.count.max(1) as f32;
        let (s, c) = ops::sin_cos(a);
        Vec2::new(c, s) * self.radius
    }
}

/// 主角身上的法器。
#[derive(Resource, Default, Debug)]
pub struct Arsenal(pub Vec<WeaponSlot>);

impl Arsenal {
    pub fn hash_into(&self, h: &mut StateHasher) {
        for w in &self.0 {
            h.write_u32(w.def as u32);
            h.write_u32(w.level);
            h.write_f32(w.angle);
        }
    }
}

pub(crate) fn update_weapons(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    player: Single<&Pos, With<Player>>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut arsenal: ResMut<Arsenal>,
    mut hits: ResMut<HitQueue>,
    mut found: Local<Vec<u32>>,
) {
    let p = player.0;
    let t = tick.secs();
    for slot in &mut arsenal.0 {
        let def = &content.0.weapons[slot.def];
        let lv = &def.levels[(slot.level as usize).clamp(1, def.levels.len()) - 1];
        match &def.behavior {
            WeaponBehavior::Orbit { spin, hit_cooldown, knockback, size } => {
                slot.prev_angle = slot.angle;
                slot.angle += spin.at(slot.level as f32) * DT;
                slot.count = lv.count + stats.amount;
                slot.radius = lv.radius * stats.area;
                slot.size = size * stats.area.sqrt();
                for k in 0..slot.count {
                    let c = p + slot.orbit_offset(slot.angle, k);
                    found.clear();
                    grid.query_circle(&en, c.x, c.y, slot.size, &mut found);
                    for &i in found.iter() {
                        let i = i as usize;
                        if en.lamp_ready[i] > t {
                            continue;
                        }
                        en.lamp_ready[i] = t + hit_cooldown;
                        hits.0.push(Hit {
                            target: en.handle(i),
                            damage: lv.damage,
                            knockback: *knockback,
                            from: p,
                            flags: 0,
                        });
                    }
                }
            }
        }
    }
}
