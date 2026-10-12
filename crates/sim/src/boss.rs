//! 夜主的招式（移植自网页版 sim/spawn.ts 的 updateBoss）和弹幕（狐火）。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_core::step::DT;
use lantern_core::{StateHasher, Stream};

use crate::combat::{ActionQueue, HurtCtx, hurt_player};
use crate::enemies::Enemies;
use crate::run::RunPlan;
use crate::spawn::spawn_enemy;
use crate::stats::{Effects, Stats};
use crate::{GameContent, Health, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;

/// 夜主的弹幕。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Foe {
    pub pos: Vec2,
    pub prev: Vec2,
    pub vel: Vec2,
    pub radius: f32,
    pub damage: f32,
    pub life: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Foes(pub Vec<Foe>);

impl Foes {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for f in &self.0 {
            h.write_f32(f.pos.x);
            h.write_f32(f.pos.y);
        }
    }
}

/// 夜主每隔一段时间放一圈弹幕、召唤小妖。
pub(crate) fn boss_attacks(
    content: Res<GameContent>,
    tick: Res<Tick>,
    stats: Res<Stats>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut foes: ResMut<Foes>,
    mut outbox: ResMut<SimOutbox>,
    mut bosses: Local<Vec<usize>>,
) {
    let c = &content.0;
    bosses.clear();
    bosses.extend(en.iter_alive().filter(|&i| c.enemies[en.kind[i] as usize].boss.is_some()));
    let minute = tick.secs() / 60.0;
    for &i in bosses.iter() {
        let Some(b) = &c.enemies[en.kind[i] as usize].boss else { continue };
        let pos = Vec2::new(en.x[i], en.y[i]);
        en.atk_t[i] -= DT;
        if en.atk_t[i] <= 0.0 {
            en.atk_t[i] = b.volley_every;
            let off = rng.0.get(Stream::Combat).range_f32(0.0, TAU);
            for k in 0..b.volley_count {
                let (s, co) = ops::sin_cos(off + k as f32 * TAU / b.volley_count as f32);
                foes.0.push(Foe {
                    pos,
                    prev: pos,
                    vel: Vec2::new(co, s) * b.shot_speed,
                    radius: b.shot_radius,
                    damage: b.shot_damage,
                    life: b.shot_life,
                });
            }
            outbox.0.push(SimEvent::BossVolley { pos });
        }
        en.summon_t[i] -= DT;
        if en.summon_t[i] <= 0.0 {
            en.summon_t[i] = b.summon_every;
            let kind = c.enemy_index(&b.summon).expect("内容校验保证引用存在") as u16;
            for k in 0..b.summon_count {
                let (s, co) = ops::sin_cos(k as f32 * TAU / b.summon_count as f32);
                let at = pos + Vec2::new(co, s) * b.summon_radius;
                spawn_enemy(c, &stats, &mut en, rng.0.get(Stream::Spawn), kind, at.x, at.y, minute);
            }
            outbox.0.push(SimEvent::BossSummon { pos });
        }
    }
}

/// 弹幕飞行，碰到主角造成伤害。
pub(crate) fn update_foes(
    content: Res<GameContent>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    plan: Res<RunPlan>,
    mut rng: ResMut<SimRng>,
    mut foes: ResMut<Foes>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    player: Single<(&Pos, &mut Player, &mut Health)>,
) {
    let c = &content.0;
    let (pos, mut player, mut health) = player.into_inner();
    let reach = c.player.radius;
    let mut ctx = HurtCtx {
        content: c,
        stats: &stats,
        effects: &effects,
        queue: &mut queue,
        rng: rng.0.get(Stream::Combat),
        god: plan.god,
        outbox: &mut outbox,
    };
    let mut k = 0;
    while k < foes.0.len() {
        let f = &mut foes.0[k];
        f.prev = f.pos;
        f.life -= DT;
        f.pos += f.vel * DT;
        let rr = f.radius + reach;
        if f.pos.distance_squared(pos.0) < rr * rr {
            let dmg = f.damage;
            foes.0.remove(k);
            hurt_player(&mut player, &mut health, pos.0, dmg, &mut ctx);
            continue;
        }
        if f.life <= 0.0 {
            foes.0.remove(k);
        } else {
            k += 1;
        }
    }
}
