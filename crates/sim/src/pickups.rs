//! 拾取物：宝箱、引魂铃、莲子（移植自网页版 sim/step.ts 的 updatePickups）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use serde::{Deserialize, Serialize};

use lantern_content::Stat;
use lantern_core::StateHasher;
use lantern_core::step::DT;

use crate::combat::heal;
use crate::flow::{ChestSource, Flow};
use crate::gems::Gems;
use crate::stats::Stats;
use crate::{GameContent, Health, Player, Pos, SimEvent, SimOutbox};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum PickupKind {
    /// 宝箱：碰到后排队打开
    Chest,
    /// 引魂铃：场上全部魂火飞来
    Bell,
    /// 莲子：回复生命
    Lotus,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pickup {
    pub kind: PickupKind,
    pub pos: Vec2,
    /// 出现了多久（画面用）
    pub t: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Pickups(pub Vec<Pickup>);

impl Pickups {
    pub fn drop(&mut self, kind: PickupKind, pos: Vec2) {
        self.0.push(Pickup { kind, pos, t: 0.0 });
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for p in &self.0 {
            h.write_u32(p.kind as u32);
            h.write_f32(p.pos.x);
            h.write_f32(p.pos.y);
        }
    }
}

pub(crate) fn update_pickups(
    content: Res<GameContent>,
    stats: Res<Stats>,
    player: Single<(&Pos, &mut Health), With<Player>>,
    mut pickups: ResMut<Pickups>,
    mut gems: ResMut<Gems>,
    mut flow: ResMut<Flow>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let (pos, mut health) = player.into_inner();
    let reach = c.player.radius + c.run.drops.reach;
    let mut k = 0;
    while k < pickups.0.len() {
        let it = &mut pickups.0[k];
        it.t += DT;
        if it.pos.distance_squared(pos.0) >= reach * reach {
            k += 1;
            continue;
        }
        let it = pickups.0.remove(k);
        match it.kind {
            PickupKind::Chest => flow.chest_queue.push_back(ChestSource::Elite),
            PickupKind::Bell => {
                let n = gems.n;
                gems.pulled[..n].fill(true);
            }
            PickupKind::Lotus => {
                let amount = stats.max_hp() * c.run.drops.lotus_heal * stats.get(Stat::Healing);
                heal(&mut health, amount, &mut outbox);
            }
        }
        outbox.0.push(SimEvent::Pickup { kind: it.kind, pos: it.pos });
    }
}
