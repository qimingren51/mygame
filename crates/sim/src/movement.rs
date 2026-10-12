//! 妖物移动（移植自网页版 sim/step.ts 的 updateEnemies）。互相推开见 crowd 模块。

use bevy_ecs::prelude::*;
use bevy_math::ops;

use lantern_content::{Movement, Rank};
use lantern_core::Stream;
use lantern_core::step::DT;

use crate::combat::{PlayerHurt, hurt_player};
use crate::enemies::Enemies;
use crate::run::{RunPlan, SimView};
use crate::spatial::Grid;
use crate::{GameContent, Health, Player, Pos, SimOutbox, SimRng, Tick};

/// 以玩家为中心重建空间网格。
pub(crate) fn build_grid(
    view: Res<SimView>,
    player: Single<&Pos, With<Player>>,
    en: Res<Enemies>,
    mut grid: ResMut<Grid>,
) {
    let r = view.radius * 1.8;
    grid.build(&en, player.0.x, player.0.y, r, r);
}

/// 追击（或逃跑）、击退衰减、离得太远的普通妖物绕到玩家前方、接触伤害。
pub(crate) fn update_enemies(
    content: Res<GameContent>,
    plan: Res<RunPlan>,
    view: Res<SimView>,
    tick: Res<Tick>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut outbox: ResMut<SimOutbox>,
    player: Single<(&Pos, &mut Player, &mut Health)>,
) {
    let content = &content.0;
    let (pos, mut player, mut health) = player.into_inner();
    let (px, py) = (pos.0.x, pos.0.y);
    let pr = content.player.radius;
    let t = tick.secs();
    let decay = ops::exp(-8.0 * DT);
    let relocate_dist = view.radius * content.run.spawn.relocate;
    let spread = content.run.spawn.relocate_spread;
    let face_angle = ops::atan2(player.facing.y, player.facing.x);
    let god = plan.is_bench();
    let en = &mut *en;

    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        en.flash[i] = (en.flash[i] - DT).max(0.0);
        let def = &content.enemies[en.kind[i] as usize];

        let (mut x, mut y) = (en.x[i], en.y[i]);
        let (dx, dy) = (px - x, py - y);
        let d = (dx * dx + dy * dy).sqrt().max(1e-3);

        x += en.kx[i] * DT;
        y += en.ky[i] * DT;
        en.kx[i] *= decay;
        en.ky[i] *= decay;

        if en.frozen[i] > 0.0 {
            en.frozen[i] -= DT;
        } else if en.stun[i] > 0.0 {
            en.stun[i] -= DT;
        } else {
            let mut sp = en.speed[i];
            if en.slow_t[i] > 0.0 {
                en.slow_t[i] -= DT;
                sp *= 1.0 - en.slow_amount[i];
                if en.slow_t[i] <= 0.0 {
                    en.slow_amount[i] = 0.0;
                }
            }
            match def.movement {
                Movement::Chase => {
                    x += dx / d * sp * DT;
                    y += dy / d * sp * DT;
                }
                Movement::Flee => {
                    // 背着玩家逃，路线左右摇摆，略慢于玩家，追得上
                    let (s, c) = ops::sin_cos(ops::sin(t * 3.0 + en.wob[i]) * 0.6);
                    let (ax, ay) = (-dx / d, -dy / d);
                    x += (ax * c - ay * s) * sp * DT;
                    y += (ax * s + ay * c) * sp * DT;
                }
            }
        }

        // 离得太远的普通妖物绕到玩家前方；上一步位置一起改，画面插值不会拖出残影
        if def.rank == Rank::Normal && def.movement == Movement::Chase && d > relocate_dist {
            let a = face_angle + rng.0.get(Stream::Spawn).range_f32(-spread, spread);
            let (s, c) = ops::sin_cos(a);
            let r = view.radius + content.run.spawn.ring_extra;
            x = px + c * r;
            y = py + s * r;
            en.px[i] = x;
            en.py[i] = y;
        }
        en.x[i] = x;
        en.y[i] = y;

        if d < en.r[i] + pr && en.damage[i] > 0.0 && !god {
            let hurt = PlayerHurt { amount: en.damage[i], iframe: content.player.hurt_iframe };
            hurt_player(&mut player, &mut health, hurt, &mut outbox);
        }
    }
}
