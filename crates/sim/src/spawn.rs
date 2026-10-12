//! 刷怪（移植自网页版 sim/spawn.ts）：常规刷怪、成群涌来、本局时间表（精英、妖潮、夜主）。

use bevy_ecs::prelude::*;
use bevy_math::ops;

use lantern_content::{PlanEvent, Rank, Stat};
use lantern_core::step::DT;
use lantern_core::{Pcg32, Stream};

use crate::enemies::Enemies;
use crate::run::{Director, RunMode, RunPlan, SimView};
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;

/// 在 (x, y) 刷一只 kind 类妖物；池满时返回 `None`。
pub fn spawn_enemy(
    content: &lantern_content::Content,
    stats: &Stats,
    en: &mut Enemies,
    rng: &mut Pcg32,
    kind: u16,
    x: f32,
    y: f32,
    minute: f32,
) -> Option<usize> {
    let def = &content.enemies[kind as usize];
    let i = en.alloc()?;
    let hp_scale = match def.rank {
        Rank::Boss => 1.0,
        _ => content.run.enemy_hp_scale.at(minute) * stats.get(Stat::EnemyHp),
    };
    let speed_scale = if def.rank == Rank::Critter { 1.0 } else { stats.get(Stat::EnemySpeed) };
    let (lo, hi) = content.run.spawn.speed_jitter;
    en.kind[i] = kind;
    en.x[i] = x;
    en.y[i] = y;
    en.px[i] = x;
    en.py[i] = y;
    en.r[i] = def.radius;
    en.hp[i] = def.hp * hp_scale;
    en.max_hp[i] = en.hp[i];
    en.speed[i] = def.speed * rng.range_f32(lo, hi) * speed_scale;
    en.damage[i] = def.damage * content.run.enemy_damage_scale.at(minute);
    en.wob[i] = rng.range_f32(0.0, TAU);
    if let Some(b) = &def.boss {
        en.atk_t[i] = b.volley_first;
        en.summon_t[i] = b.summon_every;
    }
    Some(i)
}

/// 视野外一圈上的随机位置。
pub(crate) fn ring_pos(rng: &mut Pcg32, view: &SimView, px: f32, py: f32, extra: f32) -> (f32, f32) {
    let a = rng.range_f32(0.0, TAU);
    let r = view.radius + extra;
    let (s, c) = ops::sin_cos(a);
    (px + c * r, py + s * r)
}

pub(crate) fn update_spawns(
    content: Res<GameContent>,
    stats: Res<Stats>,
    mut plan: ResMut<RunPlan>,
    view: Res<SimView>,
    tick: Res<Tick>,
    player: Single<&Pos, With<Player>>,
    mut director: ResMut<Director>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut outbox: ResMut<SimOutbox>,
) {
    let content = &content.0;
    let s = &content.run.spawn;
    let p = player.0;
    let t = tick.secs();
    let m = t / 60.0;
    let rng = rng.0.get(Stream::Spawn);

    if let RunMode::Bench { enemies } = plan.mode {
        let missing =
            (enemies as usize).saturating_sub(en.count).min(content.run.bench.refill_per_tick as usize);
        for _ in 0..missing {
            let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
            let kind =
                if rng.chance(content.run.bench.alt_share) { plan.bench_alt_kind } else { plan.bench_kind };
            spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m);
        }
        return;
    }

    let mut rate = s.rate.at(m) * stats.get(Stat::SpawnRate);
    if director.surge_t > 0.0 {
        director.surge_t -= DT;
        rate *= director.surge_mult;
    }
    if director.boss.is_some() {
        rate *= director.boss_mult;
    }
    if en.count as u32 > s.soft_cap {
        rate = 0.0;
    }
    director.spawn_acc += rate * DT;
    while director.spawn_acc >= 1.0 {
        director.spawn_acc -= 1.0;
        let r = rng.next_f32();
        let mut kind = plan.base_kind;
        let mut acc = 0.0;
        for mix in &plan.mix {
            if m < mix.from_minute {
                continue;
            }
            acc += mix.share * if m >= mix.late_minute { mix.late_mult } else { 1.0 };
            if r < acc {
                kind = mix.kind;
                break;
            }
        }
        let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
        spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m);
    }

    // 每隔一段时间从随机方向涌来一群，制造“妖潮”的方向感
    let packs = &s.packs;
    if director.next_pack == 0.0 {
        director.next_pack = packs.start;
    }
    if t >= director.next_pack && (en.count as u32) < packs.max_alive {
        director.next_pack = t + rng.range_f32(packs.interval.0, packs.interval.1);
        let (bx, by) = ring_pos(rng, &view, p.x, p.y, s.ring_extra + 20.0);
        let n = (packs.size.at(m) * stats.get(Stat::SpawnRate)).round() as u32;
        for _ in 0..n {
            let mut kind = plan.base_kind;
            for mix in &plan.pack_mix {
                if m >= mix.from_minute && rng.chance(mix.share) {
                    kind = mix.kind;
                    break;
                }
            }
            let x = bx + rng.range_f32(-packs.spread, packs.spread);
            let y = by + rng.range_f32(-packs.spread, packs.spread);
            spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m);
        }
    }

    // 按本局时间表出场
    let elites = stats.get(Stat::EliteCount).round().max(0.0) as u32;
    for step in &mut plan.schedule {
        if step.done || t < step.at {
            continue;
        }
        step.done = true;
        let spawn_elite = |pool: &[String], rng: &mut Pcg32, en: &mut Enemies, outbox: &mut SimOutbox| {
            let id = &pool[rng.below(pool.len() as u32) as usize];
            let kind = content.enemy_index(id).expect("内容校验保证引用存在") as u16;
            for _ in 0..elites {
                let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
                spawn_enemy(content, &stats, en, rng, kind, x, y, m);
            }
            outbox.0.push(SimEvent::Elite { kind, count: elites as u8 });
        };
        match &content.run.schedule[step.index].event {
            PlanEvent::Elite(pool) => spawn_elite(pool, rng, &mut en, &mut outbox),
            PlanEvent::Surge { duration, rate_mult, elites: pool } => {
                director.surge_t = *duration;
                director.surge_mult = *rate_mult;
                outbox.0.push(SimEvent::Surge);
                spawn_elite(pool, rng, &mut en, &mut outbox);
            }
            PlanEvent::Boss { enemy, spawn_mult } => {
                let kind = content.enemy_index(enemy).expect("内容校验保证引用存在") as u16;
                let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
                if let Some(i) = spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m) {
                    director.boss = Some(en.handle(i));
                    director.boss_mult = *spawn_mult;
                    outbox.0.push(SimEvent::BossArrived { kind });
                }
            }
        }
    }
}
