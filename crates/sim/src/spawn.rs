//! 刷怪（docs/BALANCE.md 第 4.1、4.6 节）：常规刷怪、成群涌来、本局时间表（精英、合围、小头目、妖潮、夜主）。
//!
//! 常规刷怪受分段的常规上限限制；妖群、合围、妖潮不受常规上限限制；任何刷怪都不超过硬上限。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{AffixKind, Content, PlanEvent, Rank, SpawnDef, Stat};
use lantern_core::step::DT;
use lantern_core::{Pcg32, Stream};

use crate::charms::Survival;
use crate::enemies::{Enemies, TAG_MINIBOSS};
use crate::lanterns::Lanterns;
use crate::run::{Director, PendingEncircle, RunMode, RunPlan, SimView};
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;

/// 在 (x, y) 刷一只 kind 类妖物；池满或到了硬上限时返回 `None`。
pub fn spawn_enemy(
    content: &Content,
    stats: &Stats,
    en: &mut Enemies,
    rng: &mut Pcg32,
    kind: u16,
    x: f32,
    y: f32,
    minute: f32,
) -> Option<usize> {
    if en.count >= content.run.spawn.hard_cap as usize {
        return None;
    }
    let def = &content.enemies[kind as usize];
    let i = en.alloc()?;
    let run = &content.run;
    let hp_scale = match def.rank {
        Rank::Boss => stats.get(Stat::BossHp),
        Rank::Elite => run.late_at(run.elite_hp_scale, run.late.hp, minute) * stats.get(Stat::EnemyHp),
        Rank::Normal | Rank::Critter => {
            run.late_at(run.enemy_hp_scale, run.late.hp, minute) * stats.get(Stat::EnemyHp)
        }
    };
    let speed_scale = if def.rank == Rank::Critter { 1.0 } else { stats.get(Stat::EnemySpeed) };
    let (lo, hi) = run.spawn.speed_jitter;
    en.kind[i] = kind;
    en.x[i] = x;
    en.y[i] = y;
    en.px[i] = x;
    en.py[i] = y;
    en.r[i] = def.radius;
    en.hp[i] = def.hp * hp_scale;
    en.max_hp[i] = en.hp[i];
    en.spawned_hp += f64::from(en.hp[i]);
    en.speed[i] = def.speed * rng.range_f32(lo, hi) * speed_scale;
    en.damage[i] = def.damage * run.enemy_damage_scale.at(minute) * stats.get(Stat::EnemyDamage);
    en.wob[i] = rng.range_f32(0.0, TAU);
    if let Some(b) = &def.boss {
        en.atk_t[i] = b.volley_first;
        en.summon_t[i] = b.summon_every;
    }
    if let Some(ch) = &def.charge {
        en.charge_t[i] = ch.every;
    }
    Some(i)
}

/// 给精英随机挑 n 个不重复的词缀（二更起）。
pub(crate) fn give_affixes(content: &Content, en: &mut Enemies, i: usize, n: u32, rng: &mut Pcg32) {
    let total = content.affixes.len() as u32;
    let mut picked = 0;
    while picked < n.min(total) {
        let k = rng.below(total);
        if en.affix[i] & (1 << k) != 0 {
            continue;
        }
        en.affix[i] |= 1 << k;
        picked += 1;
        match content.affixes[k as usize].kind {
            AffixKind::Swift { speed } => en.speed[i] *= 1.0 + speed,
            AffixKind::Summon { every, .. } => en.summon_t[i] = every,
            _ => {}
        }
    }
}

/// 当前分钟的常规刷怪上限。
pub(crate) fn soft_cap(s: &SpawnDef, minute: f32) -> usize {
    s.soft_cap.iter().rev().find(|(m, _)| minute >= *m).map_or(0, |&(_, n)| n as usize)
}

/// 基础刷怪曲线每秒刷出的总血量（以默认妖物计，不含妖潮和属性倍率）。燃灯按它充能。
pub fn base_spawn_hp(content: &Content, minute: f32) -> f32 {
    let s = &content.run.spawn;
    let base = content.enemy_index(&s.base).map_or(10.0, |k| content.enemies[k].hp);
    let run = &content.run;
    run.late_at(s.rate, run.late.spawn, minute)
        * s.scale
        * base
        * run.late_at(run.enemy_hp_scale, run.late.hp, minute)
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
    lanterns: Res<Lanterns>,
    player: Single<&Pos, With<Player>>,
    mut director: ResMut<Director>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut outbox: ResMut<SimOutbox>,
    mut survival: ResMut<Survival>,
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

    let mut rate =
        content.run.late_at(s.rate, content.run.late.spawn, m) * s.scale * stats.get(Stat::SpawnRate);
    if director.surge_t > 0.0 {
        director.surge_t -= DT;
        rate *= director.surge_mult;
    }
    if director.boss.is_some() {
        rate *= director.boss_mult;
    }
    // 妖潮期间不受常规上限限制
    if en.count >= soft_cap(s, m) && director.surge_t <= 0.0 {
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

    // 每隔一段时间从随机方向涌来一群，制造“妖潮”的方向感；不受常规上限限制
    let packs = &s.packs;
    if director.next_pack == 0.0 {
        director.next_pack = packs.start;
    }
    if t >= director.next_pack {
        director.next_pack = t + rng.range_f32(packs.interval.0, packs.interval.1);
        let (bx, by) = ring_pos(rng, &view, p.x, p.y, s.ring_extra + 20.0);
        let n = (packs.size.at(m) * s.scale * stats.get(Stat::SpawnRate)).round() as u32;
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

    // 合围：预警之后在视野外围成一圈，加速合拢
    let mut k = 0;
    while k < director.encircle.len() {
        let pe = director.encircle[k];
        if t < pe.at {
            k += 1;
            continue;
        }
        director.encircle.remove(k);
        if let PlanEvent::Encircle { count, extra, speed_mult, release, enemy, .. } =
            &content.run.schedule[pe.index].event
        {
            let kind = content.enemy_index(enemy).expect("内容校验保证引用存在") as u16;
            let n = (count.at(m) * s.scale * stats.get(Stat::SpawnRate)).round().max(1.0) as u32;
            let r = view.radius + extra;
            let a0 = rng.range_f32(0.0, TAU);
            director.rush_release = *release;
            for j in 0..n {
                let (sn, cs) = ops::sin_cos(a0 + j as f32 * TAU / n as f32);
                if let Some(i) =
                    spawn_enemy(content, &stats, &mut en, rng, kind, p.x + cs * r, p.y + sn * r, m)
                {
                    en.rush[i] = *speed_mult;
                }
            }
            outbox.0.push(SimEvent::Encircle { count: n as u16 });
        }
    }

    // 按本局时间表出场；无尽夜在 10 分钟以后再按间隔补上妖潮和夜主
    let elites = stats.get(Stat::EliteCount).round().max(0.0) as u32;
    let affixes = stats.get(Stat::Affixes).round().max(0.0) as u32;
    let schedule = &content.run.schedule;
    let mut due: Vec<usize> = Vec::new();
    for step in &mut plan.schedule {
        if !step.done && t >= step.at {
            step.done = true;
            due.push(step.index);
        }
    }
    if let Some(mut e) = director.endless {
        let ed = &content.run.endless;
        let find = |f: fn(&PlanEvent) -> bool| schedule.iter().position(|s| f(&s.event));
        let next = (content.run.late.after + ed.every * (e.wave + 1) as f32) * 60.0;
        if t >= next
            && let Some(k) = find(|ev| matches!(ev, PlanEvent::Surge { .. }))
        {
            e.wave += 1;
            due.push(k);
            if let PlanEvent::Surge { duration, .. } = schedule[k].event {
                e.boss_due = Some(t + duration);
            }
        }
        // 上一个夜主还在场就等它倒下
        if e.boss_due.is_some_and(|at| t >= at)
            && director.boss.is_none()
            && let Some(k) = find(|ev| matches!(ev, PlanEvent::Boss { .. }))
        {
            e.boss_due = None;
            due.push(k);
        }
        director.endless = Some(e);
    }
    for index in due {
        let spawn_elite = |pool: &[String],
                           rng: &mut Pcg32,
                           en: &mut Enemies,
                           outbox: &mut SimOutbox,
                           survival: &mut Survival| {
            let id = &pool[rng.below(pool.len() as u32) as usize];
            let kind = content.enemy_index(id).expect("内容校验保证引用存在") as u16;
            for _ in 0..elites {
                let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
                if let Some(i) = spawn_enemy(content, &stats, en, rng, kind, x, y, m) {
                    give_affixes(content, en, i, affixes, rng);
                    survival.watch(en.handle(i));
                }
            }
            outbox.0.push(SimEvent::Elite { kind, count: elites as u8 });
        };
        match &schedule[index].event {
            PlanEvent::Elite(pool) => spawn_elite(pool, rng, &mut en, &mut outbox, &mut survival),
            PlanEvent::Surge { duration, rate_mult, elites: pool } => {
                director.surge_t = *duration;
                director.surge_mult = *rate_mult;
                outbox.0.push(SimEvent::Surge);
                spawn_elite(pool, rng, &mut en, &mut outbox, &mut survival);
            }
            PlanEvent::MiniBoss { enemy, .. } => {
                let kind = content.enemy_index(enemy).expect("内容校验保证引用存在") as u16;
                let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
                if let Some(i) = spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m) {
                    en.tags[i] |= TAG_MINIBOSS;
                    survival.watch(en.handle(i));
                }
                outbox.0.push(SimEvent::Elite { kind, count: 1 });
            }
            PlanEvent::Encircle { warn, .. } => {
                director.encircle.push(PendingEncircle { at: t + warn, index });
                outbox.0.push(SimEvent::EncircleWarn { warn: *warn });
            }
            PlanEvent::Boss { enemy, spawn_mult, barrier } => {
                let kind = content.enemy_index(enemy).expect("内容校验保证引用存在") as u16;
                let (x, y) = ring_pos(rng, &view, p.x, p.y, s.ring_extra);
                if let Some(i) = spawn_enemy(content, &stats, &mut en, rng, kind, x, y, m) {
                    // 灯阵完整：夜主少两成生命；无尽夜第 k 次再来 × boss_growth^k
                    let mut hp = en.hp[i];
                    if lanterns.complete() {
                        hp *= content.run.lanterns.boss_hp;
                    }
                    if let Some(e) = &mut director.endless {
                        hp *= (0..e.arrivals).fold(1.0, |a, _| a * content.run.endless.boss_growth);
                        e.arrivals += 1;
                    }
                    en.set_hp(i, hp);
                    director.boss = Some(en.handle(i));
                    director.boss_mult = *spawn_mult;
                    director.boss_since = t;
                    if *barrier > 0.0 {
                        director.barrier = Some((Vec2::new(p.x, p.y), *barrier));
                    }
                    outbox.0.push(SimEvent::BossArrived { kind });
                }
            }
        }
    }
}
