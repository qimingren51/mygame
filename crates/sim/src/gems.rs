//! 魂火（经验，移植自网页版 sim/gems.ts 与 step.ts 的 updateGems）：
//! 按字段分数组存储，删除时用末尾元素填补空位；超过上限时并入最近的一颗。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_core::StateHasher;
use lantern_core::step::DT;

use crate::run::{Progress, RunPlan};
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox};

/// 池子的硬上限；内容数据里的 `gems.cap` 是软上限，必须小于它。
pub const GEM_CAPACITY: usize = 2048;

#[derive(Resource)]
pub struct Gems {
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub px: Vec<f32>,
    pub py: Vec<f32>,
    pub value: Vec<f32>,
    pub vx: Vec<f32>,
    pub vy: Vec<f32>,
    pub age: Vec<f32>,
    pub pulled: Vec<bool>,
    pub n: usize,
}

impl Default for Gems {
    fn default() -> Self {
        let f = || vec![0.0f32; GEM_CAPACITY];
        Gems {
            x: f(),
            y: f(),
            px: f(),
            py: f(),
            value: f(),
            vx: f(),
            vy: f(),
            age: f(),
            pulled: vec![false; GEM_CAPACITY],
            n: 0,
        }
    }
}

impl Gems {
    /// 掉落一颗魂火；超过 `cap` 时并入最近的一颗，避免数量失控。
    pub fn drop(&mut self, pos: Vec2, value: f32, cap: u32) {
        if self.n >= (cap as usize).min(GEM_CAPACITY) {
            let mut near = 0;
            let mut nd = f32::INFINITY;
            for i in 0..self.n {
                let (dx, dy) = (self.x[i] - pos.x, self.y[i] - pos.y);
                let d = dx * dx + dy * dy;
                if d < nd {
                    nd = d;
                    near = i;
                }
            }
            if self.n > 0 {
                self.value[near] += value;
            }
            return;
        }
        let i = self.n;
        self.n += 1;
        self.x[i] = pos.x;
        self.y[i] = pos.y;
        self.px[i] = pos.x;
        self.py[i] = pos.y;
        self.value[i] = value;
        self.vx[i] = 0.0;
        self.vy[i] = 0.0;
        self.age[i] = 0.0;
        self.pulled[i] = false;
    }

    fn remove(&mut self, i: usize) {
        self.n -= 1;
        let last = self.n;
        if i == last {
            return;
        }
        self.x[i] = self.x[last];
        self.y[i] = self.y[last];
        self.px[i] = self.px[last];
        self.py[i] = self.py[last];
        self.value[i] = self.value[last];
        self.vx[i] = self.vx[last];
        self.vy[i] = self.vy[last];
        self.age[i] = self.age[last];
        self.pulled[i] = self.pulled[last];
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.n as u32);
        for i in 0..self.n {
            for v in [self.x[i], self.y[i], self.value[i]] {
                h.write_f32(v);
            }
        }
    }
}

/// 进入吸附范围、或落地太久的魂火飞向主角，碰到即拾取。
pub(crate) fn update_gems(
    content: Res<GameContent>,
    stats: Res<Stats>,
    player: Single<&Pos, With<Player>>,
    mut gems: ResMut<Gems>,
    mut progress: ResMut<Progress>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let g = &c.run.gems;
    let p = player.0;
    let magnet = stats.get(lantern_content::Stat::Magnet);
    let mag2 = magnet * magnet;
    let reach = c.player.radius + g.reach;
    let mut i = 0;
    while i < gems.n {
        let (dx, dy) = (p.x - gems.x[i], p.y - gems.y[i]);
        let d2 = dx * dx + dy * dy;
        gems.age[i] += DT;
        if !gems.pulled[i] && (d2 < mag2 || gems.age[i] > g.return_after) {
            gems.pulled[i] = true;
        }
        if !gems.pulled[i] {
            i += 1;
            continue;
        }
        let d = d2.sqrt().max(1e-3);
        let v = (gems.vx[i] * gems.vx[i] + gems.vy[i] * gems.vy[i]).sqrt();
        let sp = (v + g.accel * DT).min(g.max_speed);
        gems.vx[i] = dx / d * sp;
        gems.vy[i] = dy / d * sp;
        gems.x[i] += gems.vx[i] * DT;
        gems.y[i] += gems.vy[i] * DT;
        if d < reach {
            let value = gems.value[i];
            progress.xp += value;
            outbox.0.push(SimEvent::GemPicked { value });
            gems.remove(i);
            continue;
        }
        i += 1;
    }
}

/// 经验满了就升级。跑分模式不升级。
pub(crate) fn level_up(
    content: Res<GameContent>,
    plan: Res<RunPlan>,
    mut progress: ResMut<Progress>,
    mut dirty: ResMut<crate::stats::StatsDirty>,
    mut outbox: ResMut<SimOutbox>,
) {
    if plan.is_bench() {
        return;
    }
    loop {
        let need = content.0.run.xp_need.at(progress.level as f32);
        if !need.is_finite()
            || need <= 0.0
            || !progress.xp.is_finite()
            || progress.xp < need
            || progress.xp - need >= progress.xp
            || progress.level == u32::MAX
            || progress.pending_levels == u32::MAX
        {
            break;
        }
        progress.xp -= need;
        progress.level += 1;
        progress.pending_levels += 1;
        // 照见圈、灯光随等级变大
        dirty.0 = true;
        outbox.0.push(SimEvent::LevelUp { level: progress.level });
    }
}
