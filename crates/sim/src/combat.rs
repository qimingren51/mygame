//! 伤害管线（docs/DESIGN.md 第 6.5 节，数值移植自网页版 sim/combat.ts）。
//!
//! - 法器、飞剑、范围打击把 [`Hit`] 按顺序放进 [`HitQueue`]，Damage 阶段统一结算：
//!   暴击 → 扣血 → 命中触发器（灼烧、减速、冰冻……）→ 击退 → 死亡进 [`Deaths`]。
//! - 范围打击（寒波、石印、爆炸、震地、太极、燃灯）先排进 [`Strikes`]，在 Weapons 阶段末尾
//!   按空间网格找到目标，再变成逐个的 [`Hit`]。
//! - 触发器里不针对单个目标的动作（回复、爆炸、震地、全屏伤害、追加飞剑、天降宝箱）先排进
//!   [`ActionQueue`]，下一个 Weapons 阶段统一执行。这样所有“产生伤害”的入口只有一处。
//! - Death 阶段处理死亡：掉落、击杀触发器、连斩、燃灯充能、击败夜主。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{Action, BlastKind, Cond, Content, Rank, Stat};
use lantern_core::step::DT;
use lantern_core::{Pcg32, Stream};

use crate::enemies::{Enemies, EnemyHandle};
use crate::flow::Flow;
use crate::gems::Gems;
use crate::pickups::{PickupKind, Pickups};
use crate::run::{Director, Progress, SimView};
use crate::spatial::Grid;
use crate::stats::{ActiveTrigger, Effects, Stats};
use crate::weapons::volley::Shots;
use crate::{GameContent, Health, HitKind, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

const TAU: f32 = std::f32::consts::TAU;

/// 不判定暴击
pub const HIT_NOCRIT: u8 = 1;
/// 持续伤害：不触发命中效果、不击退
pub const HIT_DOT: u8 = 2;
/// 追加飞剑造成的命中（不再触发追加）
pub const HIT_BONUS: u8 = 4;

/// 伤害来源，平衡统计用。
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Source {
    /// 法器（`weapons.ron` 下标）
    Weapon(u16),
    BonusSword,
    Burn,
    Blast,
    Quake,
    Screen,
    Ult,
}

#[derive(Clone, Copy, Debug)]
pub struct Hit {
    pub target: EnemyHandle,
    /// 基础伤害，结算时乘以伤害倍率
    pub damage: f32,
    pub knockback: f32,
    /// 击退方向的来源点
    pub from: Vec2,
    pub flags: u8,
    /// 大于 0 时，对夜主的单次伤害不超过它
    pub boss_cap: f32,
    /// 命中后（目标还活着时）附加的击晕、减速；冰冻在结算伤害之前附加（夜主免疫）
    pub stun: f32,
    pub freeze: f32,
    pub slow: f32,
    pub slow_time: f32,
    pub source: Source,
}

impl Hit {
    pub fn new(target: EnemyHandle, damage: f32, source: Source) -> Self {
        Hit {
            target,
            damage,
            knockback: 0.0,
            from: Vec2::ZERO,
            flags: 0,
            boss_cap: 0.0,
            stun: 0.0,
            freeze: 0.0,
            slow: 0.0,
            slow_time: 0.0,
            source,
        }
    }

    pub fn knock(mut self, knockback: f32, from: Vec2) -> Self {
        self.knockback = knockback;
        self.from = from;
        self
    }

    pub fn flags(mut self, flags: u8) -> Self {
        self.flags = flags;
        self
    }
}

/// 本步待结算的命中，按产生顺序。
#[derive(Resource, Default, Debug)]
pub struct HitQueue(pub Vec<Hit>);

/// 范围打击的形状。
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Area {
    /// 圆（判定距离加上妖物半径）
    Circle(f32),
    /// 视野内（每边再放宽 margin）
    Screen(f32),
}

/// 范围打击的画面效果。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StrikeFx {
    None,
    /// 霜铃寒波
    Pulse,
    /// 寒山钟全屏钟鸣
    Toll,
    /// 石印落地
    Seal {
        evolved: bool,
    },
    Blast(BlastKind),
    Quake,
    Taiji,
    Ult,
}

#[derive(Clone, Copy, Debug)]
pub struct Strike {
    pub pos: Vec2,
    pub area: Area,
    pub damage: f32,
    pub knockback: f32,
    pub flags: u8,
    pub boss_cap: f32,
    /// 大于 0 时，对夜主改为最大生命的这个比例（不暴击、不击退）
    pub boss_fraction: f32,
    pub stun: f32,
    pub freeze: f32,
    pub slow: f32,
    pub slow_time: f32,
    pub source: Source,
    pub fx: StrikeFx,
}

impl Strike {
    pub fn new(pos: Vec2, area: Area, damage: f32, source: Source, fx: StrikeFx) -> Self {
        Strike {
            pos,
            area,
            damage,
            knockback: 0.0,
            flags: 0,
            boss_cap: 0.0,
            boss_fraction: 0.0,
            stun: 0.0,
            freeze: 0.0,
            slow: 0.0,
            slow_time: 0.0,
            source,
            fx,
        }
    }
}

/// 待处理的范围打击。
#[derive(Resource, Default, Debug)]
pub struct Strikes(pub Vec<Strike>);

/// 触发器排队的动作：在 pos 处执行，target 是触发它的妖物（追加飞剑朝它飞）。
#[derive(Clone, Copy, Debug)]
pub struct Deferred {
    pub action: Action,
    pub pos: Vec2,
    pub target: Option<EnemyHandle>,
}

#[derive(Resource, Default, Debug)]
pub struct ActionQueue(pub Vec<Deferred>);

/// 一只妖物的死亡，Death 阶段处理。
#[derive(Clone, Copy, Debug)]
pub struct Death {
    pub pos: Vec2,
    pub kind: u16,
    /// 死时处于冰冻（水·凝 三阶的冰爆）
    pub frozen: bool,
}

#[derive(Resource, Default, Debug)]
pub struct Deaths(pub Vec<Death>);

/// 各来源造成的总伤害（平衡统计）。
#[derive(Resource, Default, Debug, Clone)]
pub struct DamageLog(pub Vec<(Source, f64)>);

impl DamageLog {
    pub fn add(&mut self, source: Source, dmg: f32) {
        match self.0.iter_mut().find(|(s, _)| *s == source) {
            Some((_, v)) => *v += f64::from(dmg),
            None => self.0.push((source, f64::from(dmg))),
        }
    }
}

/// 触发器的条件和概率。概率小于 1 时才消耗随机数。
pub(crate) fn passes(t: &ActiveTrigger, rng: &mut Pcg32, frozen: bool, flags: u8) -> bool {
    let ok = match t.only {
        Cond::Always => true,
        Cond::TargetFrozen => frozen,
        Cond::NotBonus => flags & HIT_BONUS == 0,
    };
    ok && (t.chance >= 1.0 || rng.chance(t.chance))
}

/// 在妖物 i 身上立即生效的动作；其余排队。
fn on_enemy(
    t: &ActiveTrigger,
    stats: &Stats,
    en: &mut Enemies,
    i: usize,
    boss: bool,
    dmg: f32,
    queue: &mut ActionQueue,
) {
    match t.action {
        Action::Burn { duration, ratio } => {
            en.burn_t[i] = duration;
            en.burn_stacks[i] = (en.burn_stacks[i] + 1.0).min(stats.get(Stat::BurnStacks));
            en.burn_dps[i] = (en.burn_dps[i] * 0.9).max(dmg * ratio * stats.get(Stat::BurnDamage));
        }
        Action::Slow { amount, duration } => {
            en.slow_t[i] = en.slow_t[i].max(duration);
            en.slow_amount[i] = en.slow_amount[i].max(amount);
        }
        Action::Freeze { duration } => {
            if !boss {
                en.frozen[i] = en.frozen[i].max(duration);
            }
        }
        action => {
            queue.0.push(Deferred { action, pos: Vec2::new(en.x[i], en.y[i]), target: Some(en.handle(i)) })
        }
    }
}

pub(crate) fn resolve_hits(
    content: Res<GameContent>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    mut rng: ResMut<SimRng>,
    mut hits: ResMut<HitQueue>,
    mut en: ResMut<Enemies>,
    mut deaths: ResMut<Deaths>,
    mut queue: ResMut<ActionQueue>,
    mut log: ResMut<DamageLog>,
    mut outbox: ResMut<SimOutbox>,
) {
    let content = &content.0;
    let rng = rng.0.get(Stream::Combat);
    let en = &mut *en;
    let crit_chance = stats.get(Stat::CritChance);
    let stun_crit = stats.get(Stat::StunCrit) > 0.0;
    let frozen_bonus = stats.get(Stat::FrozenDamage);
    for hit in hits.0.drain(..) {
        let Some(i) = en.resolve(hit.target) else { continue };
        let def = &content.enemies[en.kind[i] as usize];
        let boss = def.rank == Rank::Boss;
        if hit.freeze > 0.0 && !boss {
            en.frozen[i] = en.frozen[i].max(hit.freeze);
        }
        let mut dmg = hit.damage * stats.get(Stat::Damage);
        let crit =
            hit.flags & HIT_NOCRIT == 0 && (rng.next_f32() < crit_chance || (en.stun[i] > 0.0 && stun_crit));
        if crit {
            dmg *= stats.get(Stat::CritMult);
        }
        if en.frozen[i] > 0.0 && frozen_bonus > 0.0 {
            dmg *= 1.0 + frozen_bonus;
        }
        if boss && hit.boss_cap > 0.0 {
            dmg = dmg.min(hit.boss_cap);
        }
        // 统计只计实际打掉的血（溢出的不算）
        log.add(hit.source, dmg.min(en.hp[i].max(0.0)));
        en.hp[i] -= dmg;
        en.flash[i] = 0.08;
        let pos = Vec2::new(en.x[i], en.y[i]);
        let kind = if hit.flags & HIT_DOT != 0 {
            HitKind::Dot
        } else if hit.flags & HIT_BONUS != 0 {
            HitKind::Bonus
        } else {
            HitKind::Normal
        };
        outbox.0.push(SimEvent::Hit { pos: pos - Vec2::new(0.0, en.r[i] + 4.0), damage: dmg, crit, kind });

        if hit.flags & HIT_DOT == 0 {
            let frozen = en.frozen[i] > 0.0;
            for t in &effects.hit {
                if passes(t, rng, frozen, hit.flags) {
                    on_enemy(t, &stats, en, i, boss, dmg, &mut queue);
                }
            }
            if crit {
                for t in &effects.crit {
                    if passes(t, rng, frozen, hit.flags) {
                        on_enemy(t, &stats, en, i, boss, dmg, &mut queue);
                    }
                }
            }
            if hit.knockback > 0.0 && !boss {
                let d = pos - hit.from;
                let len = d.length().max(1e-3);
                let f = hit.knockback * stats.get(Stat::Knockback)
                    / if def.rank == Rank::Elite { 3.0 } else { 1.0 };
                en.kx[i] += d.x / len * f;
                en.ky[i] += d.y / len * f;
            }
        }

        if en.hp[i] > 0.0 {
            if hit.stun > 0.0 {
                en.stun[i] = en.stun[i].max(hit.stun);
            }
            if hit.slow > 0.0 {
                en.slow_t[i] = en.slow_t[i].max(hit.slow_time);
                en.slow_amount[i] = en.slow_amount[i].max(hit.slow);
            }
        } else {
            kill(en, i, def.rank, &mut deaths, &mut outbox);
        }
    }
}

/// 妖物死亡：移出池子，记下死亡等 Death 阶段处理。
pub(crate) fn kill(en: &mut Enemies, i: usize, rank: Rank, deaths: &mut Deaths, outbox: &mut SimOutbox) {
    let pos = Vec2::new(en.x[i], en.y[i]);
    let kind = en.kind[i];
    deaths.0.push(Death { pos, kind, frozen: en.frozen[i] > 0.0 });
    en.kill(i);
    outbox.0.push(SimEvent::Kill { pos, kind, rank });
}

/// 执行排队的动作。
pub(crate) fn run_actions(
    stats: Res<Stats>,
    tick: Res<Tick>,
    progress: Res<Progress>,
    en: Res<Enemies>,
    player: Single<(&Pos, &mut Health), With<Player>>,
    mut rng: ResMut<SimRng>,
    mut queue: ResMut<ActionQueue>,
    mut strikes: ResMut<Strikes>,
    mut shots: ResMut<Shots>,
    mut pickups: ResMut<Pickups>,
    mut outbox: ResMut<SimOutbox>,
) {
    let (pos, mut health) = player.into_inner();
    let p = pos.0;
    let minute = tick.secs() / 60.0;
    for d in queue.0.drain(..) {
        match d.action {
            Action::Heal(v) => heal(&mut health, v * stats.get(Stat::Healing), &mut outbox),
            Action::Explode { radius, damage, kind } => {
                let mut s = Strike::new(
                    d.pos,
                    Area::Circle(radius),
                    damage.at(minute),
                    Source::Blast,
                    StrikeFx::Blast(kind),
                );
                s.flags = HIT_NOCRIT | HIT_DOT;
                strikes.0.push(s);
            }
            Action::Quake { radius, damage, knockback, stun } => {
                let mut s =
                    Strike::new(p, Area::Circle(radius), damage.at(minute), Source::Quake, StrikeFx::Quake);
                s.knockback = knockback;
                s.stun = stun;
                strikes.0.push(s);
            }
            Action::ScreenDamage { damage, boss_cap } => {
                let mut s =
                    Strike::new(p, Area::Screen(30.0), damage.at(minute), Source::Screen, StrikeFx::Taiji);
                s.boss_cap = boss_cap;
                strikes.0.push(s);
            }
            Action::BonusSword { damage, pierce, speed, life, turn, hit_radius, knockback } => {
                let target = d.target.and_then(|h| en.resolve(h).map(|i| (h, Vec2::new(en.x[i], en.y[i]))));
                let angle = match target {
                    Some((_, t)) => ops::atan2(t.y - p.y, t.x - p.x),
                    None => ops::atan2(d.pos.y - p.y, d.pos.x - p.x),
                };
                shots.fire(crate::weapons::volley::ShotSpec {
                    pos: p,
                    angle,
                    speed,
                    life,
                    turn,
                    hit_radius,
                    knockback,
                    damage: damage.at(progress.level as f32),
                    pierce,
                    target: target.map(|(h, _)| h),
                    big: false,
                    bonus: true,
                    source: Source::BonusSword,
                });
            }
            Action::DropChest { distance } => {
                let a = rng.0.get(Stream::Drop).range_f32(0.0, TAU);
                let (s, c) = ops::sin_cos(a);
                pickups.drop(PickupKind::Chest, p + Vec2::new(c, s) * distance);
            }
            // 只作用于单个目标的动作在结算命中时已经生效
            Action::Burn { .. } | Action::Slow { .. } | Action::Freeze { .. } => {}
        }
    }
}

/// 回复生命（不超过上限）。
pub(crate) fn heal(health: &mut Health, amount: f32, outbox: &mut SimOutbox) {
    if amount <= 0.0 || health.hp <= 0.0 {
        return;
    }
    let before = health.hp;
    health.hp = (health.hp + amount).min(health.max);
    if health.hp > before {
        outbox.0.push(SimEvent::PlayerHealed { amount: health.hp - before });
    }
}

/// 把范围打击变成逐个的命中。
pub(crate) fn process_strikes(
    content: Res<GameContent>,
    view: Res<SimView>,
    grid: Res<Grid>,
    en: Res<Enemies>,
    mut strikes: ResMut<Strikes>,
    mut hits: ResMut<HitQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut found: Local<Vec<u32>>,
) {
    let content = &content.0;
    for s in strikes.0.drain(..) {
        found.clear();
        let radius = match s.area {
            Area::Circle(r) => {
                grid.query_circle(&en, s.pos.x, s.pos.y, r, &mut found);
                r
            }
            Area::Screen(margin) => {
                let (hw, hh) = (view.half_w + margin, view.half_h + margin);
                found.extend(
                    en.iter_alive()
                        .filter(|&i| (en.x[i] - s.pos.x).abs() < hw && (en.y[i] - s.pos.y).abs() < hh)
                        .map(|i| i as u32),
                );
                view.radius
            }
        };
        if s.fx != StrikeFx::None {
            outbox.0.push(SimEvent::Strike { pos: s.pos, radius, fx: s.fx });
        }
        for &i in found.iter() {
            let i = i as usize;
            let boss = content.enemies[en.kind[i] as usize].rank == Rank::Boss;
            let mut hit = Hit {
                target: en.handle(i),
                damage: s.damage,
                knockback: s.knockback,
                from: s.pos,
                flags: s.flags,
                boss_cap: s.boss_cap,
                stun: s.stun,
                freeze: s.freeze,
                slow: s.slow,
                slow_time: s.slow_time,
                source: s.source,
            };
            if boss && s.boss_fraction > 0.0 {
                hit.damage = en.max_hp[i] * s.boss_fraction;
                hit.flags |= HIT_NOCRIT;
                hit.knockback = 0.0;
            }
            hits.0.push(hit);
        }
    }
}

/// 灼烧：每步扣血，累计满 1 点、每 0.5 秒冒一个数字。
pub(crate) fn burn(
    content: Res<GameContent>,
    mut en: ResMut<Enemies>,
    mut deaths: ResMut<Deaths>,
    mut log: ResMut<DamageLog>,
    mut outbox: ResMut<SimOutbox>,
) {
    let en = &mut *en;
    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        if en.burn_t[i] <= 0.0 {
            en.burn_stacks[i] = 0.0;
            en.burn_dps[i] = 0.0;
            continue;
        }
        en.burn_t[i] -= DT;
        let dmg = en.burn_dps[i] * en.burn_stacks[i] * DT;
        log.add(Source::Burn, dmg.min(en.hp[i].max(0.0)));
        en.hp[i] -= dmg;
        en.burn_acc[i] += dmg;
        en.burn_show[i] -= DT;
        if en.burn_show[i] <= 0.0 && en.burn_acc[i] >= 1.0 {
            outbox.0.push(SimEvent::Hit {
                pos: Vec2::new(en.x[i], en.y[i] - en.r[i]),
                damage: en.burn_acc[i],
                crit: false,
                kind: HitKind::Dot,
            });
            en.burn_acc[i] = 0.0;
            en.burn_show[i] = 0.5;
        }
        if en.hp[i] <= 0.0 {
            let rank = content.0.enemies[en.kind[i] as usize].rank;
            kill(en, i, rank, &mut deaths, &mut outbox);
        }
    }
}

/// 处理本步的死亡：掉落、击杀触发器、连斩、燃灯充能、击败夜主。
pub(crate) fn process_deaths(
    content: Res<GameContent>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    tick: Res<Tick>,
    mut rng: ResMut<SimRng>,
    mut deaths: ResMut<Deaths>,
    mut gems: ResMut<Gems>,
    mut pickups: ResMut<Pickups>,
    mut progress: ResMut<Progress>,
    mut director: ResMut<Director>,
    mut flow: ResMut<Flow>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
) {
    let c = &content.0;
    let t = tick.secs();
    let minute = t / 60.0;
    let g = &c.run.gems;
    let drops = &c.run.drops;
    for d in deaths.0.drain(..) {
        let def = &c.enemies[d.kind as usize];
        if let Some(loot) = &def.loot {
            // 金蟾：散落大量魂火和灯油，不计击杀
            let total = c.run.xp_need.at(progress.level as f32) * loot.xp_levels;
            let r = rng.0.get(Stream::Drop);
            for _ in 0..loot.gems {
                let a = r.range_f32(0.0, TAU);
                let dist = r.range_f32(loot.scatter.0, loot.scatter.1);
                let (s, co) = ops::sin_cos(a);
                gems.drop(d.pos + Vec2::new(co, s) * dist, total / loot.gems as f32, g.cap);
            }
            flow.oil_bonus += loot.oil;
            outbox.0.push(SimEvent::CritterLooted { pos: d.pos });
            continue;
        }
        if def.rank == Rank::Critter {
            continue;
        }
        let p = &mut *progress;
        p.kills += 1;
        p.combo = if p.combo_t > 0.0 { p.combo + 1 } else { 1 };
        p.combo_t = c.run.combo.window;
        p.best_combo = p.best_combo.max(p.combo);
        if c.run.combo.milestones.contains(&p.combo) {
            outbox.0.push(SimEvent::Combo { count: p.combo });
        }
        let elite = def.rank == Rank::Elite;
        let charge = if elite { c.player.ult.charge_elite } else { c.player.ult.charge_normal };
        let was_ready = p.ult >= 1.0;
        p.ult = (p.ult + charge).min(1.0);
        if p.ult >= 1.0 && !was_ready {
            outbox.0.push(SimEvent::UltReady);
        }

        let loot = rng.0.get(Stream::Drop);
        if def.xp > 0.0 {
            let value = def.xp * c.run.gem_value_scale.at(minute) * stats.get(Stat::XpGain);
            if elite {
                let n = g.elite_split;
                for _ in 0..n {
                    let off = Vec2::new(
                        loot.range_f32(-g.elite_scatter, g.elite_scatter),
                        loot.range_f32(-g.elite_scatter, g.elite_scatter),
                    );
                    gems.drop(d.pos + off, value / n as f32, g.cap);
                }
            } else {
                gems.drop(d.pos, value, g.cap);
            }
        }
        if elite {
            pickups.drop(PickupKind::Chest, d.pos);
            pickups.drop(PickupKind::Bell, d.pos + Vec2::new(24.0, 0.0));
        } else if loot.chance(drops.bell_chance) {
            pickups.drop(PickupKind::Bell, d.pos);
        } else if stats.can_heal() && loot.chance(drops.lotus_chance) {
            pickups.drop(PickupKind::Lotus, d.pos);
        }

        let combat = rng.0.get(Stream::Combat);
        for trig in &effects.kill {
            if passes(trig, combat, d.frozen, 0) {
                queue.0.push(Deferred { action: trig.action, pos: d.pos, target: None });
            }
        }

        if def.rank == Rank::Boss {
            director.boss = None;
            flow.won_at = Some(t + c.run.win_delay);
            outbox.0.push(SimEvent::BossDefeated { pos: d.pos });
        }
    }
}

/// 主角受伤需要的东西。
pub(crate) struct HurtCtx<'a> {
    pub content: &'a Content,
    pub stats: &'a Stats,
    pub effects: &'a Effects,
    pub queue: &'a mut ActionQueue,
    pub rng: &'a mut Pcg32,
    pub god: bool,
    pub outbox: &'a mut SimOutbox,
}

/// 主角受伤：无敌或闪避中不受伤；减伤、护甲、护盾依次生效；之后进入无敌时间。
pub(crate) fn hurt_player(
    player: &mut Player,
    health: &mut Health,
    pos: Vec2,
    amount: f32,
    ctx: &mut HurtCtx,
) {
    if player.iframe > 0.0 || player.dash_t > 0.0 || health.hp <= 0.0 {
        return;
    }
    let s = ctx.stats;
    let mut dmg = (amount * (1.0 - s.get(Stat::Reduction)) - s.get(Stat::Armor)).max(1.0);
    if player.shield > 0.0 {
        let absorbed = player.shield.min(dmg);
        player.shield -= absorbed;
        dmg -= absorbed;
        if player.shield <= 0.0 {
            player.shield = 0.0;
            player.shield_t = s.get(Stat::ShieldCooldown);
            ctx.outbox.0.push(SimEvent::ShieldBroken);
            for t in &ctx.effects.shield_break {
                if passes(t, ctx.rng, false, 0) {
                    ctx.queue.0.push(Deferred { action: t.action, pos, target: None });
                }
            }
        }
    }
    player.iframe = ctx.content.player.hurt_iframe;
    if dmg <= 0.0 || ctx.god {
        return;
    }
    health.hp = (health.hp - dmg).max(0.0);
    ctx.outbox.0.push(SimEvent::PlayerHurt { amount: dmg });
    if health.hp <= 0.0 {
        ctx.outbox.0.push(SimEvent::PlayerDied);
    }
}
