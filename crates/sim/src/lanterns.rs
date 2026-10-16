//! 点灯（docs/GAMEPLAY.md 第 8.3 节）：每夜几盏熄灭的石灯笼，开局按种子摆好（出生点周围每个扇区一盏）。
//! 站在旁边累计几秒就点亮（中途离开不清零）；点亮后成为永久光区，并给一次三选一奖励。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::LanternsDef;
use lantern_core::step::DT;
use lantern_core::{Pcg32, StateHasher};

use crate::flow::Flow;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox};

const TAU: f32 = std::f32::consts::TAU;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Lantern {
    pub pos: Vec2,
    /// 已经站了多少秒
    pub progress: f32,
    pub lit: bool,
}

#[derive(Resource, Default, Debug)]
pub struct Lanterns(pub Vec<Lantern>);

impl Lanterns {
    /// 把出生点周围分成 count 个扇区，每个扇区一盏，离出生点 distance 范围内。
    pub fn place(def: &LanternsDef, rng: &mut Pcg32) -> Self {
        let n = def.count.max(1);
        let list = (0..def.count)
            .map(|k| {
                let a = (k as f32 + rng.range_f32(0.1, 0.9)) * TAU / n as f32;
                let r = rng.range_f32(def.distance.0, def.distance.1);
                let (s, c) = ops::sin_cos(a);
                Lantern { pos: Vec2::new(c, s) * r, progress: 0.0, lit: false }
            })
            .collect();
        Lanterns(list)
    }

    pub fn lit(&self) -> u32 {
        self.0.iter().filter(|l| l.lit).count() as u32
    }

    /// 灯阵完整：全部点亮。
    pub fn complete(&self) -> bool {
        !self.0.is_empty() && self.0.iter().all(|l| l.lit)
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        for l in &self.0 {
            h.write_f32(l.progress);
        }
    }
}

/// 站在没点亮的灯旁计时，满了就点亮，排队一次三选一奖励。
pub(crate) fn update_lanterns(
    content: Res<GameContent>,
    player: Single<&Pos, With<Player>>,
    mut lanterns: ResMut<Lanterns>,
    mut story: ResMut<crate::story::Story>,
    mut rng: ResMut<crate::SimRng>,
    mut flow: ResMut<Flow>,
    mut outbox: ResMut<SimOutbox>,
) {
    let def = &content.0.run.lanterns;
    let p = player.0;
    let r2 = def.light_radius * def.light_radius;
    let mut lit_now = None;
    for (k, l) in lanterns.0.iter_mut().enumerate() {
        if l.lit || l.pos.distance_squared(p) > r2 {
            continue;
        }
        l.progress += DT;
        if l.progress >= def.light_time {
            l.lit = true;
            lit_now = Some(k);
        }
        // 一次只点一盏
        break;
    }
    if let Some(k) = lit_now {
        flow.lamp_queue += 1;
        story.find_journal(&mut rng, &mut outbox);
        let lit = lanterns.lit();
        outbox.0.push(SimEvent::LanternLit { index: k as u8, lit: lit as u8, all: lanterns.complete() });
    }
}
