//! 铜钱（docs/GAMEPLAY.md 第 11.1 节，docs/BALANCE.md 第 10.2 节）。
//!
//! 和魂火一样放在模拟里（掉落、吸附、拾取都在模拟里，回放能复现），但不会自己飞回来：
//! 要走过去捡，拾取范围会把它吸过来，引魂铃也吸铜钱。天明时地上剩下的全部飞来。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::Stat;
use lantern_core::step::DT;
use lantern_core::{Pcg32, StateHasher};

use crate::run::Progress;
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox};

const TAU: f32 = std::f32::consts::TAU;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Coin {
    pub pos: Vec2,
    pub prev: Vec2,
    pub vel: Vec2,
    pub value: f32,
    /// 被吸住了，一路飞向主角
    pub pulled: bool,
}

#[derive(Resource, Default, Debug)]
pub struct Coins(pub Vec<Coin>);

impl Coins {
    /// 掉一枚；超过 cap 时并入最近的一枚。
    pub fn drop(&mut self, pos: Vec2, value: f32, cap: u32) {
        if value <= 0.0 {
            return;
        }
        if self.0.len() >= cap as usize {
            let near = self
                .0
                .iter_mut()
                .min_by(|a, b| a.pos.distance_squared(pos).total_cmp(&b.pos.distance_squared(pos)));
            if let Some(c) = near {
                c.value += value;
            }
            return;
        }
        self.0.push(Coin { pos, prev: pos, vel: Vec2::ZERO, value, pulled: false });
    }

    /// 掉一笔铜钱：按 per_coin 拆成几枚，散在 pos 周围。
    pub fn scatter(&mut self, rng: &mut Pcg32, pos: Vec2, total: f32, per_coin: f32, spread: f32, cap: u32) {
        let n = (total / per_coin).ceil().max(1.0) as u32;
        for _ in 0..n {
            let a = rng.range_f32(0.0, TAU);
            let r = rng.range_f32(0.0, spread);
            let (s, c) = ops::sin_cos(a);
            self.drop(pos + Vec2::new(c, s) * r, total / n as f32, cap);
        }
    }

    /// 全部吸过来（引魂铃、天明）。
    pub fn pull_all(&mut self) {
        for c in &mut self.0 {
            c.pulled = true;
        }
    }

    /// 地上剩下的总额。
    pub fn total(&self) -> f32 {
        self.0.iter().map(|c| c.value).sum()
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for c in &self.0 {
            h.write_f32(c.pos.x);
            h.write_f32(c.pos.y);
            h.write_f32(c.value);
        }
    }
}

/// 进入拾取范围的铜钱飞向主角，碰到即拾取。
pub(crate) fn update_coins(
    content: Res<GameContent>,
    stats: Res<Stats>,
    player: Single<&Pos, With<Player>>,
    mut coins: ResMut<Coins>,
    mut progress: ResMut<Progress>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let g = &c.run.gems;
    let p = player.0;
    let magnet = stats.get(Stat::Magnet);
    let reach = c.player.radius + g.reach;
    let mut k = 0;
    while k < coins.0.len() {
        let coin = &mut coins.0[k];
        coin.prev = coin.pos;
        let d = p - coin.pos;
        let dist = d.length();
        if !coin.pulled && dist < magnet {
            coin.pulled = true;
        }
        if coin.pulled {
            let sp = (coin.vel.length() + g.accel * DT).min(g.max_speed);
            coin.vel = d / dist.max(1e-3) * sp;
            coin.pos += coin.vel * DT;
        }
        if dist < reach {
            let value = coin.value;
            progress.gold += value;
            outbox.0.push(SimEvent::CoinPicked { value });
            coins.0.swap_remove(k);
            continue;
        }
        k += 1;
    }
}
