//! 夜主的招式（docs/BALANCE.md 第 12.2 节）、精英词缀“召”、敌方弹幕（狐火）。
//!
//! 九尾：一阶段放狐火环、召唤影妖；生命降到 60% 分出幻身（打不死、没有影子，在照见圈里待一会儿就散）；
//! 降到 25% 开始九尾扫（扇形，地面预警）；登场 120 秒后狂暴。三更起全程多一招狐火雨。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{AffixKind, Rule, Stat};
use lantern_core::step::DT;
use lantern_core::{StateHasher, Stream};

use crate::charms::Survival;
use crate::combat::{ActionQueue, HurtCtx, hurt_player};
use crate::enemies::Enemies;
use crate::reveal::Reveal;
use crate::run::{Director, RunPlan};
use crate::spawn::{soft_cap, spawn_enemy};
use crate::stats::{Effects, Stats};
use crate::{GameContent, Health, HurtBy, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;
const PI: f32 = std::f32::consts::PI;

/// 敌方弹幕。
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
            for v in [f.pos.x, f.pos.y, f.vel.x, f.vel.y, f.life] {
                h.write_f32(v);
            }
        }
    }

    fn ring(&mut self, pos: Vec2, n: u32, offset: f32, speed: f32, radius: f32, damage: f32, life: f32) {
        for k in 0..n {
            let (s, c) = ops::sin_cos(offset + k as f32 * TAU / n as f32);
            self.0.push(Foe { pos, prev: pos, vel: Vec2::new(c, s) * speed, radius, damage, life });
        }
    }
}

/// 九尾的幻身：绕着主角转，放狐火环；在照见圈里待满一会儿就散。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Illusion {
    pub pos: Vec2,
    pub prev: Vec2,
    pub angle: f32,
    pub volley_t: f32,
    /// 在照见圈里待了多久
    pub seen: f32,
}

/// 九尾扫：从 origin 朝 dir 方向的扇形，预警 warn 秒后结算。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Sweep {
    pub origin: Vec2,
    pub dir: f32,
    pub angle: f32,
    pub radius: f32,
    pub damage: f32,
    pub t: f32,
    pub warn: f32,
}

/// 狐火雨的一团：预警 warn 秒后落下。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RainDrop {
    pub pos: Vec2,
    pub radius: f32,
    pub damage: f32,
    pub t: f32,
    pub warn: f32,
}

/// 夜主战的状态（画面直接读它画幻身、扇形和落点预警）。
#[derive(Resource, Default, Debug)]
pub struct BossState {
    /// 1、2、3 阶段；0 表示夜主不在场
    pub phase: u8,
    pub enraged: bool,
    pub illusions: Vec<Illusion>,
    pub refill_t: f32,
    pub sweep_t: f32,
    pub sweeps: Vec<Sweep>,
    pub rain_t: f32,
    pub drops: Vec<RainDrop>,
}

impl BossState {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(u32::from(self.phase) | u32::from(self.enraged) << 8);
        for v in [self.refill_t, self.sweep_t, self.rain_t] {
            h.write_f32(v);
        }
        h.write_u32(self.illusions.len() as u32);
        for m in &self.illusions {
            for v in [m.pos.x, m.pos.y, m.angle, m.volley_t, m.seen] {
                h.write_f32(v);
            }
        }
        h.write_u32(self.sweeps.len() as u32);
        for s in &self.sweeps {
            for v in [s.origin.x, s.origin.y, s.dir, s.t] {
                h.write_f32(v);
            }
        }
        h.write_u32(self.drops.len() as u32);
        for d in &self.drops {
            for v in [d.pos.x, d.pos.y, d.t] {
                h.write_f32(v);
            }
        }
    }
}

/// 夜主出招。
#[allow(clippy::too_many_arguments)]
pub(crate) fn boss_attacks(
    content: Res<GameContent>,
    tick: Res<Tick>,
    stats: Res<Stats>,
    reveal: Res<Reveal>,
    director: Res<Director>,
    player: Single<&Pos, With<Player>>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut foes: ResMut<Foes>,
    mut state: ResMut<BossState>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let st = &mut *state;
    let Some(i) = director.boss.and_then(|h| en.resolve(h)) else {
        if st.phase != 0 {
            *st = BossState::default();
        }
        return;
    };
    let Some(b) = &c.enemies[en.kind[i] as usize].boss else { return };
    let t = tick.secs();
    let minute = t / 60.0;
    let p = player.0;
    let pos = Vec2::new(en.x[i], en.y[i]);
    let dmg_mult = stats.get(Stat::EnemyDamage);
    let shot = b.shot_damage * dmg_mult;

    // 阶段
    let frac = en.hp[i] / en.max_hp[i].max(1.0);
    let phase = 1
        + u8::from(b.illusions.is_some_and(|il| frac < il.at))
        + u8::from(b.sweep.is_some_and(|sw| frac < sw.at));
    if phase != st.phase {
        if st.phase != 0 {
            outbox.0.push(SimEvent::BossPhase { phase });
        }
        if phase >= 2 && st.phase < 2 {
            // 刚进二阶段：立刻分出幻身
            st.illusions.clear();
            st.refill_t = 0.0;
        }
        st.phase = phase;
    }
    let enraged = t - director.boss_since >= b.enrage_after;
    if enraged && !st.enraged {
        outbox.0.push(SimEvent::BossEnraged);
    }
    st.enraged = enraged;
    let pace = if enraged { b.enrage_mult } else { 1.0 };
    let combat = rng.0.get(Stream::Combat);

    // 狐火环
    en.atk_t[i] -= DT;
    if en.atk_t[i] <= 0.0 {
        let every = match b.sweep {
            Some(sw) if phase >= 3 => sw.volley_every,
            _ => b.volley_every,
        };
        en.atk_t[i] = every * pace;
        let off = combat.range_f32(0.0, TAU);
        foes.ring(pos, b.volley_count, off, b.shot_speed, b.shot_radius, shot, b.shot_life);
        outbox.0.push(SimEvent::BossVolley { pos });
    }
    // 召唤
    en.summon_t[i] -= DT;
    if en.summon_t[i] <= 0.0 {
        en.summon_t[i] = b.summon_every * pace;
        let kind = c.enemy_index(&b.summon).expect("内容校验保证引用存在") as u16;
        for k in 0..b.summon_count {
            let (s, co) = ops::sin_cos(k as f32 * TAU / b.summon_count as f32);
            let at = pos + Vec2::new(co, s) * b.summon_radius;
            spawn_enemy(c, &stats, &mut en, rng.0.get(Stream::Spawn), kind, at.x, at.y, minute);
        }
        outbox.0.push(SimEvent::BossSummon { pos });
    }
    let combat = rng.0.get(Stream::Combat);

    // 二阶段起：幻身
    if let Some(il) = b.illusions
        && phase >= 2
    {
        st.refill_t -= DT;
        if st.refill_t <= 0.0 {
            st.refill_t = il.refill;
            while (st.illusions.len() as u32) < il.count {
                let angle = combat.range_f32(0.0, TAU);
                let (s, co) = ops::sin_cos(angle);
                let at = p + Vec2::new(co, s) * il.distance;
                st.illusions.push(Illusion {
                    pos: at,
                    prev: at,
                    angle,
                    volley_t: combat.range_f32(0.5, il.volley_every),
                    seen: 0.0,
                });
            }
        }
        let r2 = reveal.radius * reveal.radius;
        let mut k = 0;
        while k < st.illusions.len() {
            let m = &mut st.illusions[k];
            m.prev = m.pos;
            m.angle += il.spin * DT;
            let (s, co) = ops::sin_cos(m.angle);
            m.pos = p + Vec2::new(co, s) * il.distance;
            m.volley_t -= DT;
            if m.volley_t <= 0.0 {
                m.volley_t = il.volley_every * pace;
                let off = combat.range_f32(0.0, TAU);
                foes.ring(m.pos, il.volley_count, off, b.shot_speed, b.shot_radius, shot, b.shot_life);
            }
            if m.pos.distance_squared(reveal.center) <= r2 {
                m.seen += DT;
            }
            if m.seen >= il.dispel {
                outbox.0.push(SimEvent::IllusionDispelled { pos: m.pos });
                st.illusions.swap_remove(k);
            } else {
                k += 1;
            }
        }
    }

    // 三阶段：九尾扫
    if let Some(sw) = b.sweep
        && phase >= 3
    {
        st.sweep_t -= DT;
        if st.sweep_t <= 0.0 {
            st.sweep_t = sw.every * pace;
            let dir = ops::atan2(p.y - pos.y, p.x - pos.x);
            st.sweeps.push(Sweep {
                origin: pos,
                dir,
                angle: sw.angle,
                radius: sw.radius,
                damage: sw.damage * dmg_mult,
                t: 0.0,
                warn: sw.warn,
            });
            outbox.0.push(SimEvent::SweepWarn { pos, dir });
        }
    }

    // 三更起：狐火雨
    if let Some(rn) = b.rain
        && stats.rule(Rule::BossExtra)
    {
        st.rain_t -= DT;
        if st.rain_t <= 0.0 {
            st.rain_t = rn.every * pace;
            for _ in 0..rn.count {
                let a = combat.range_f32(0.0, TAU);
                let d = combat.range_f32(0.0, rn.spread);
                let (s, co) = ops::sin_cos(a);
                st.drops.push(RainDrop {
                    pos: p + Vec2::new(co, s) * d,
                    radius: rn.radius,
                    damage: rn.damage * dmg_mult,
                    t: 0.0,
                    warn: rn.warn,
                });
            }
            outbox.0.push(SimEvent::RainWarn { count: rn.count as u8 });
        }
    }
}

/// 精英词缀“召”：每隔一段时间在身边召出一圈小妖（计入常规刷怪上限，满了就不召）。
pub(crate) fn elite_summons(
    content: Res<GameContent>,
    tick: Res<Tick>,
    stats: Res<Stats>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut list: Local<Vec<usize>>,
) {
    let c = &content.0;
    let Some(k) = c.affixes.iter().position(|a| matches!(a.kind, AffixKind::Summon { .. })) else { return };
    let AffixKind::Summon { every, count, enemy, radius } = &c.affixes[k].kind else { return };
    let bit = 1u16 << k;
    list.clear();
    list.extend(en.iter_alive().filter(|&i| en.affix[i] & bit != 0));
    if list.is_empty() {
        return;
    }
    let minute = tick.secs() / 60.0;
    let cap = soft_cap(&c.run.spawn, minute);
    let kind = c.enemy_index(enemy).expect("内容校验保证引用存在") as u16;
    let rng = rng.0.get(Stream::Spawn);
    for &i in list.iter() {
        en.summon_t[i] -= DT;
        if en.summon_t[i] > 0.0 {
            continue;
        }
        en.summon_t[i] = *every;
        let pos = Vec2::new(en.x[i], en.y[i]);
        for j in 0..*count {
            if en.count >= cap {
                break;
            }
            let (s, co) = ops::sin_cos(j as f32 * TAU / *count as f32);
            let at = pos + Vec2::new(co, s) * *radius;
            spawn_enemy(c, &stats, &mut en, rng, kind, at.x, at.y, minute);
        }
    }
}

/// 弹幕飞行，碰到主角造成伤害；九尾扫、狐火雨到时结算。
#[allow(clippy::too_many_arguments)]
pub(crate) fn update_foes(
    content: Res<GameContent>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    plan: Res<RunPlan>,
    mut rng: ResMut<SimRng>,
    mut foes: ResMut<Foes>,
    mut state: ResMut<BossState>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut survival: ResMut<Survival>,
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
        survival: &mut survival,
    };
    let mut k = 0;
    while k < foes.0.len() {
        let f = &mut foes.0[k];
        f.prev = f.pos;
        f.life -= DT;
        f.pos += f.vel * DT;
        let rr = f.radius + reach;
        if f.pos.distance_squared(pos.0) < rr * rr {
            let (dmg, from) = (f.damage, f.pos);
            foes.0.remove(k);
            hurt_player(&mut player, &mut health, pos.0, dmg, (HurtBy::Shot, from), &mut ctx);
            continue;
        }
        if f.life <= 0.0 {
            foes.0.remove(k);
        } else {
            k += 1;
        }
    }
    let st = &mut *state;
    let mut k = 0;
    while k < st.sweeps.len() {
        let sw = &mut st.sweeps[k];
        sw.t += DT;
        if sw.t < sw.warn {
            k += 1;
            continue;
        }
        let d = pos.0 - sw.origin;
        let mut diff = ops::atan2(d.y, d.x) - sw.dir;
        while diff > PI {
            diff -= TAU;
        }
        while diff < -PI {
            diff += TAU;
        }
        let hit = d.length() <= sw.radius + reach && diff.abs() <= sw.angle * 0.5;
        let (origin, dir, dmg) = (sw.origin, sw.dir, sw.damage);
        st.sweeps.swap_remove(k);
        ctx.outbox.0.push(SimEvent::SweepStrike { pos: origin, dir });
        if hit {
            hurt_player(&mut player, &mut health, pos.0, dmg, (HurtBy::Sweep, origin), &mut ctx);
        }
    }
    let mut k = 0;
    while k < st.drops.len() {
        let r = &mut st.drops[k];
        r.t += DT;
        if r.t < r.warn {
            k += 1;
            continue;
        }
        let rr = r.radius + reach;
        let hit = r.pos.distance_squared(pos.0) <= rr * rr;
        let (at, dmg) = (r.pos, r.damage);
        st.drops.swap_remove(k);
        ctx.outbox.0.push(SimEvent::RainStrike { pos: at });
        if hit {
            hurt_player(&mut player, &mut health, pos.0, dmg, (HurtBy::Rain, at), &mut ctx);
        }
    }
}
