//! 奇遇（移植自网页版 lantern/game.js 的 spawnEvent / updateEvents）：夜主出场前，每隔一段时间
//! 在主角附近随机出现一个。金蟾会逃跑，打死散财；灵泉回血；古灯给 30 秒随机增益；
//! 血祭坛以血换宝箱；妖潮裂隙涌出一群妖物和一个守卫精英。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{EventKind, Stat};
use lantern_core::step::DT;
use lantern_core::{StateHasher, Stream};

use crate::enemies::{Enemies, EnemyHandle};
use crate::flow::{ChestSource, Flow};
use crate::run::{Director, RunPlan};
use crate::spawn::spawn_enemy;
use crate::stats::{Stats, StatsDirty};
use crate::{GameContent, Health, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;

/// 场上的一个奇遇。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Encounter {
    /// `events.ron` 里 kinds 的下标
    pub kind: usize,
    pub pos: Vec2,
    pub t: f32,
    /// 金蟾、裂隙守卫
    pub enemy: Option<EnemyHandle>,
}

#[derive(Resource, Debug, Default)]
pub struct Encounters {
    /// 下一个奇遇出现的时刻
    pub next_at: f32,
    pub list: Vec<Encounter>,
    /// 古灯增益：(`events.ron` 里 buffs 的下标, 剩余时间)
    pub buff: Option<(usize, f32)>,
}

impl Encounters {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_f32(self.next_at);
        h.write_u32(self.list.len() as u32);
        for e in &self.list {
            h.write_u32(e.kind as u32);
            h.write_f32(e.t);
        }
        if let Some((b, t)) = self.buff {
            h.write_u32(b as u32);
            h.write_f32(t);
        }
    }
}

/// 到时间就挑一种奇遇放到主角附近。
pub(crate) fn spawn_encounters(
    content: Res<GameContent>,
    stats: Res<Stats>,
    plan: Res<RunPlan>,
    director: Res<Director>,
    tick: Res<Tick>,
    player: Single<&Pos, With<Player>>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut encounters: ResMut<Encounters>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let t = tick.secs();
    if plan.is_bench() || director.boss.is_some() || t < encounters.next_at {
        return;
    }
    let ev = &c.events;
    let rng = rng.0.get(Stream::Event);
    encounters.next_at = t + rng.range_f32(ev.interval.0, ev.interval.1) / stats.get(Stat::EventRate);
    // 无法回复生命时不出灵泉
    let allowed =
        |k: &lantern_content::EventDef| stats.can_heal() || !matches!(k.kind, EventKind::Spring { .. });
    let total: f32 = ev.kinds.iter().filter(|k| allowed(k)).map(|k| k.weight).sum();
    let mut r = rng.next_f32() * total;
    let mut kind = ev.kinds.iter().position(&allowed).unwrap_or(0);
    for (i, k) in ev.kinds.iter().enumerate().filter(|(_, k)| allowed(k)) {
        kind = i;
        r -= k.weight;
        if r <= 0.0 {
            break;
        }
    }
    let def = &ev.kinds[kind];
    let (s, co) = ops::sin_cos(rng.range_f32(0.0, TAU));
    let pos = player.0 + Vec2::new(co, s) * def.distance;
    let minute = t / 60.0;
    let mut enemy = None;
    match &def.kind {
        EventKind::Critter { enemy: id } => {
            let k = c.enemy_index(id).expect("内容校验保证引用存在") as u16;
            enemy = spawn_enemy(c, &stats, &mut en, rng, k, pos.x, pos.y, minute).map(|i| en.handle(i));
        }
        EventKind::Rift { minions, spread, base, alt, alt_share, guards, late_guards, late_minute } => {
            let base = c.enemy_index(base).expect("内容校验保证引用存在") as u16;
            let alt = c.enemy_index(alt).expect("内容校验保证引用存在") as u16;
            for _ in 0..minions.at(minute).floor().max(0.0) as u32 {
                let (s, co) = ops::sin_cos(rng.range_f32(0.0, TAU));
                let at = pos + Vec2::new(co, s) * rng.range_f32(spread.0, spread.1);
                let k = if rng.chance(*alt_share) { alt } else { base };
                spawn_enemy(c, &stats, &mut en, rng, k, at.x, at.y, minute);
            }
            let n = guards.len() + if minute > *late_minute { late_guards.len() } else { 0 };
            let pick = rng.below(n as u32) as usize;
            let id = guards.get(pick).unwrap_or_else(|| &late_guards[pick - guards.len()]);
            let k = c.enemy_index(id).expect("内容校验保证引用存在") as u16;
            enemy = spawn_enemy(c, &stats, &mut en, rng, k, pos.x, pos.y, minute).map(|i| en.handle(i));
        }
        _ => {}
    }
    encounters.list.push(Encounter { kind, pos, t: 0.0, enemy });
    outbox.0.push(SimEvent::Encounter { kind: kind as u16, pos });
}

/// 奇遇的计时、触碰效果、古灯增益到期。
pub(crate) fn update_encounters(
    content: Res<GameContent>,
    stats: Res<Stats>,
    player: Single<(&Pos, &mut Health), With<Player>>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut encounters: ResMut<Encounters>,
    mut flow: ResMut<Flow>,
    mut dirty: ResMut<StatsDirty>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let (pos, mut health) = player.into_inner();
    let p = pos.0;
    let encounters = &mut *encounters;
    if let Some((_, t)) = &mut encounters.buff {
        *t -= DT;
        if *t <= 0.0 {
            encounters.buff = None;
            dirty.0 = true;
        }
    }
    let mut k = 0;
    while k < encounters.list.len() {
        let e = &mut encounters.list[k];
        e.t += DT;
        let def = &c.events.kinds[e.kind];
        let near = |r: f32| e.pos.distance_squared(p) < r * r;
        let mut done = e.t >= def.life;
        match def.kind {
            EventKind::Critter { .. } => {
                // 金蟾跑了：时间到还没打死就消失
                match e.enemy.and_then(|h| en.resolve(h)) {
                    None => done = true,
                    Some(i) if done => {
                        outbox.0.push(SimEvent::CritterFled { pos: Vec2::new(en.x[i], en.y[i]) });
                        en.kill(i);
                    }
                    Some(i) => e.pos = Vec2::new(en.x[i], en.y[i]),
                }
            }
            EventKind::Spring { radius, heal: rate } => {
                if !done && near(radius) && health.hp < health.max {
                    let amount = health.max * rate * stats.get(Stat::Healing) * DT;
                    health.hp = (health.hp + amount).min(health.max);
                }
            }
            EventKind::Shrine { radius, duration } => {
                if !done && near(radius) {
                    let b = rng.0.get(Stream::Event).below(c.events.buffs.len() as u32) as usize;
                    encounters.buff = Some((b, duration));
                    dirty.0 = true;
                    outbox.0.push(SimEvent::Buff { index: b as u16 });
                    done = true;
                }
            }
            EventKind::Altar { radius, cost, chests } => {
                if !done && near(radius) {
                    let amount = (health.max * cost).round();
                    let before = health.hp;
                    health.hp = (health.hp - amount).max(1.0);
                    for _ in 0..chests {
                        flow.chest_queue.push_back(ChestSource::Altar);
                    }
                    outbox.0.push(SimEvent::Sacrifice { amount: before - health.hp });
                    done = true;
                }
            }
            EventKind::Merchant { radius, chest_cost, charm_cost } => {
                // 货郎：碰到就摆摊（本步结束时打开），逛完就走
                if !done && near(radius) {
                    flow.shop = Some(crate::flow::Shop { chest_cost, charm_cost });
                    done = true;
                }
            }
            EventKind::Rift { .. } => {}
        }
        if done {
            encounters.list.remove(k);
        } else {
            k += 1;
        }
    }
}
