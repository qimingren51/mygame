//! 五行印记与反应（docs/GAMEPLAY.md 第 6.2、6.9 节，docs/BALANCE.md 第 7.2 节）。
//!
//! - 法器命中给妖物打上自己五行的印记，持续 3 秒；带着印记的妖物被另一系命中时发生反应，印记清空。
//! - 每只妖物每秒最多反应一次；冷却中被另一系命中只换印记。每一步最多结算 64 次反应，超出的丢弃。
//! - 反应不带五行、不打印记、不暴击；伤害以触发那一击的加成区伤害为基数，之后再乘一次易伤。
//! - 区域型反应（赤地、淤泥）：同一类对同一只妖物只算最强的一块；每类全场最多 64 块，超出替换最老的。

use bevy_ecs::prelude::*;
use bevy_ecs::system::SystemParam;
use bevy_math::Vec2;

use lantern_content::{Content, Element, Rank, ReactionEffect, Stat, ZoneKind};
use lantern_core::step::DT;
use lantern_core::{Pcg32, StateHasher};

use crate::combat::{
    HIT_DOT, HIT_NOCRIT, HIT_RAW, HIT_REACT, HIT_TRUE, Hard, Hit, HitQueue, Source, apply_confuse,
    apply_hard, apply_slow, heal_overflow,
};
use crate::enemies::{ENEMY_CAP, Enemies};
use crate::flow::Hold;
use crate::reveal::ZONE_TICK;
use crate::spatial::Grid;
use crate::stats::Stats;
use crate::weapons::volley::{ShotSpec, Shots};
use crate::{GameContent, Health, Player, Pos, SimEvent, SimOutbox, Tick};

const TAU: f32 = std::f32::consts::TAU;
/// 每类区域全场最多几块
pub const ZONE_CAP: usize = 64;
/// 第一次发生某种反应时模拟停顿的步数（0.3 秒）
pub const FIRST_HOLD: u32 = 18;
/// 同种反应的文字每 2 秒只提示一次
const LABEL_EVERY: f32 = 2.0;
/// 灵草的拾取距离（加上主角半径）
const HERB_REACH: f32 = 12.0;

/// 地面区域：赤地（持续伤害）、淤泥（减速、击退加倍）。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Zone {
    pub kind: ZoneKind,
    /// `elements.ron` 里 reactions 的下标
    pub reaction: u8,
    pub pos: Vec2,
    pub radius: f32,
    pub life: f32,
    pub max_life: f32,
    pub dps: f32,
    pub slow: f32,
    pub knock: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Zones(pub Vec<Zone>);

impl Zones {
    fn add(&mut self, z: Zone) {
        if self.0.iter().filter(|o| o.kind == z.kind).count() >= ZONE_CAP
            && let Some(k) = self.0.iter().position(|o| o.kind == z.kind)
        {
            // 列表按生成顺序，第一块就是最老的
            self.0.remove(k);
        }
        self.0.push(z);
    }
}

/// 灵草（滋生）：主角碰到回复生命。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Herb {
    pub pos: Vec2,
    pub life: f32,
    pub max_life: f32,
    pub heal: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Herbs {
    pub list: Vec<Herb>,
    /// 每秒最多回复多少，以及当前还能回复多少
    pub rate: f32,
    pub budget: f32,
}

/// 本局发生过的反应（位掩码）与每种反应上次提示文字的时刻。
#[derive(Resource, Debug)]
pub struct Discoveries {
    pub seen: u32,
    pub label_at: [f32; 32],
}

impl Default for Discoveries {
    fn default() -> Self {
        Discoveries { seen: 0, label_at: [f32::NEG_INFINITY; 32] }
    }
}

/// 反应用到的可变资源。
#[derive(SystemParam)]
pub(crate) struct ReactRes<'w, 's> {
    zones: ResMut<'w, Zones>,
    herbs: ResMut<'w, Herbs>,
    shots: ResMut<'w, Shots>,
    disc: ResMut<'w, Discoveries>,
    hold: ResMut<'w, Hold>,
    bamboo: ResMut<'w, crate::bamboo::Bamboo>,
    found: Local<'s, Vec<u32>>,
    /// 赤霄分剑找目标用（复用，不每次分配）
    split: Local<'s, Vec<u32>>,
}

pub(crate) struct ReactCtx<'a, 'w, 's> {
    content: &'a Content,
    stats: &'a Stats,
    grid: &'a Grid,
    level: u32,
    secs: f32,
    res: &'a mut ReactRes<'w, 's>,
    /// 本步已经结算的反应次数
    count: u32,
}

impl<'a, 'w, 's> ReactCtx<'a, 'w, 's> {
    /// 赤霄分剑要用的飞剑池、网格和找目标的缓冲。
    pub(crate) fn split_parts(&mut self) -> (&mut Shots, &Grid, &mut Vec<u32>) {
        (&mut self.res.shots, self.grid, &mut self.res.split)
    }

    pub fn new(
        content: &'a Content,
        stats: &'a Stats,
        grid: &'a Grid,
        level: u32,
        secs: f32,
        res: &'a mut ReactRes<'w, 's>,
    ) -> Self {
        ReactCtx { content, stats, grid, level, secs, res, count: 0 }
    }
}

/// 法器命中带着五行 e：打印记，或者和已有的印记发生反应。
#[allow(clippy::too_many_arguments)]
pub(crate) fn mark(
    ctx: &mut ReactCtx,
    en: &mut Enemies,
    i: usize,
    e: Element,
    base: f32,
    hits: &mut Vec<Hit>,
    rng: &mut Pcg32,
    outbox: &mut SimOutbox,
) {
    let m = &ctx.content.elements.marks;
    let code = e.index() as u8 + 1;
    let cur = if en.mark_t[i] > 0.0 { en.mark[i] } else { 0 };
    let reaction = if cur == 0 || cur == code || en.react_cd[i] > 0.0 || ctx.count >= m.max_per_step {
        None
    } else {
        ctx.content.elements.reaction_between(Element::ALL[cur as usize - 1], e)
    };
    match reaction {
        None => {
            en.mark[i] = code;
            en.mark_t[i] = m.duration;
        }
        Some(r) => {
            en.mark[i] = 0;
            en.mark_t[i] = 0.0;
            en.react_cd[i] = m.react_cooldown;
            ctx.count += 1;
            react(ctx, en, i, r, base, hits, rng, outbox);
        }
    }
}

fn set_burn(en: &mut Enemies, i: usize, dps: f32, stacks: f32, time: f32) {
    en.burn_t[i] = en.burn_t[i].max(time);
    en.burn_stacks[i] = en.burn_stacks[i].max(stacks);
    en.burn_dps[i] = en.burn_dps[i].max(dps);
}

fn rank_of(content: &Content, en: &Enemies, j: usize) -> Rank {
    content.enemies[en.kind[j] as usize].rank
}

#[allow(clippy::too_many_arguments)]
fn react(
    ctx: &mut ReactCtx,
    en: &mut Enemies,
    i: usize,
    r: usize,
    base: f32,
    hits: &mut Vec<Hit>,
    rng: &mut Pcg32,
    outbox: &mut SimOutbox,
) {
    let c = ctx.content;
    let stats = ctx.stats;
    let pos = Vec2::new(en.x[i], en.y[i]);
    let rank = rank_of(c, en, i);
    // 相生、相克反应各有自己的倍率（夜签逆克让相克反应翻倍）
    let rd = &c.elements.reactions[r];
    let sheng =
        c.elements.sheng.iter().any(|s| (s.from, s.to) == (rd.a, rd.b) || (s.from, s.to) == (rd.b, rd.a));
    let mult = stats.get(Stat::ReactionDamage)
        * stats.get(if sheng { Stat::ShengReaction } else { Stat::KeReaction });
    let source = Source::Reaction(r as u8);
    let flags = HIT_RAW | HIT_NOCRIT | HIT_DOT | HIT_REACT;
    let alive = en.hp[i] > 0.0;
    let me = en.handle(i);
    let found = &mut *ctx.res.found;
    found.clear();
    match c.elements.reactions[r].effect {
        ReactionEffect::Spread { count, radius, mult: m, duration, burn_ratio } => {
            let dps = en.burn_dps[i].max(base * burn_ratio * stats.get(Stat::BurnDamage)) * m * mult;
            let stacks = en.burn_stacks[i].max(1.0);
            ctx.grid.nearest_k(en, pos.x, pos.y, radius, count as usize + 1, found);
            if alive {
                set_burn(en, i, dps, stacks, duration);
            }
            let mut n = 0;
            for &j in found.iter() {
                let j = j as usize;
                if j != i && n < count {
                    set_burn(en, j, dps, stacks, duration);
                    n += 1;
                }
            }
        }
        ReactionEffect::Zone { zone, radius, duration, dps_ratio, slow, knock_mult } => {
            ctx.res.zones.add(Zone {
                kind: zone,
                reaction: r as u8,
                pos,
                radius,
                life: duration,
                max_life: duration,
                dps: base * dps_ratio * mult,
                slow,
                knock: knock_mult,
            });
        }
        ReactionEffect::Blades { count, ratio, pierce, speed, life, hit_radius } => {
            let a0 = rng.range_f32(0.0, TAU);
            for k in 0..count {
                ctx.res.shots.fire(ShotSpec {
                    effects: Default::default(),
                    pos,
                    angle: a0 + k as f32 * TAU / count as f32,
                    speed: speed * stats.get(Stat::ProjSpeed),
                    life: life * stats.get(Stat::ProjLife),
                    turn: 0.0,
                    hit_radius,
                    knockback: 0.0,
                    damage: base * ratio * mult,
                    pierce,
                    target: None,
                    skip: Some(me),
                    big: false,
                    bonus: false,
                    flags,
                    element: None,
                    source,
                });
            }
        }
        ReactionEffect::Frost { freeze, radius, slow, slow_time } => {
            if alive {
                apply_hard(en, i, rank, Hard::Freeze { blast: false }, freeze * stats.get(Stat::FreezeTime));
            }
            ctx.grid.query_circle(en, pos.x, pos.y, radius, found);
            for &j in found.iter() {
                let j = j as usize;
                let rk = rank_of(c, en, j);
                apply_slow(en, j, rk, stats, slow, slow_time);
            }
        }
        ReactionEffect::Bloom { radius, root, herb_life, heal, heal_per_second } => {
            ctx.grid.query_circle(en, pos.x, pos.y, radius, found);
            for &j in found.iter() {
                let j = j as usize;
                let rk = rank_of(c, en, j);
                apply_hard(en, j, rk, Hard::Root, root);
            }
            let herbs = &mut *ctx.res.herbs;
            herbs.rate = heal_per_second;
            herbs.list.push(Herb { pos, life: herb_life, max_life: herb_life, heal });
        }
        ReactionEffect::Steam { radius, ratio, per_level, confuse } => {
            let dmg = (base * ratio + ctx.level as f32 * per_level) * mult;
            ctx.res.bamboo.circle(pos, radius, dmg);
            ctx.grid.query_circle(en, pos.x, pos.y, radius, found);
            for &j in found.iter() {
                let j = j as usize;
                hits.push(Hit::new(en.handle(j), dmg, source).flags(flags));
                let rk = rank_of(c, en, j);
                apply_confuse(en, j, rk, confuse, rng.range_f32(0.0, TAU));
            }
        }
        ReactionEffect::Melt { vuln, duration } => {
            if alive {
                en.melt[i] = if en.melt_t[i] > 0.0 { en.melt[i].max(vuln) } else { vuln };
                en.melt_t[i] = en.melt_t[i].max(duration);
            }
        }
        ReactionEffect::Sever { ratio, execute } => {
            if alive {
                if rank == Rank::Normal && en.hp[i] < en.max_hp[i] * execute {
                    hits.push(
                        Hit::new(me, en.hp[i] + 1.0, source)
                            .flags(HIT_TRUE | HIT_NOCRIT | HIT_DOT | HIT_REACT),
                    );
                } else {
                    hits.push(Hit::new(me, base * ratio * mult, source).flags(flags));
                }
            }
        }
        ReactionEffect::Rupture { radius, stun, ratio } => {
            ctx.res.bamboo.circle(pos, radius, base * ratio * mult);
            ctx.grid.query_circle(en, pos.x, pos.y, radius, found);
            for &j in found.iter() {
                let j = j as usize;
                hits.push(Hit::new(en.handle(j), base * ratio * mult, source).flags(flags));
                let rk = rank_of(c, en, j);
                apply_hard(en, j, rk, Hard::Stun, stun);
            }
        }
    }
    let disc = &mut *ctx.res.disc;
    let bit = 1u32 << r;
    let first = disc.seen & bit == 0;
    disc.seen |= bit;
    let label = first || ctx.secs - disc.label_at[r] >= LABEL_EVERY;
    if label {
        disc.label_at[r] = ctx.secs;
    }
    if first {
        ctx.res.hold.0 = ctx.res.hold.0.max(FIRST_HOLD);
    }
    outbox.0.push(SimEvent::Reaction { kind: r as u8, pos, first, label });
}

/// 地面区域：淤泥每步减速并让击退加倍；赤地每 0.5 秒结算一次伤害（同一只妖物只算最强的一块）。
pub(crate) fn update_zones(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut zones: ResMut<Zones>,
    mut hits: ResMut<HitQueue>,
    mut bamboo: ResMut<crate::bamboo::Bamboo>,
    mut scratch: Local<Scratch>,
) {
    zones.0.retain_mut(|z| {
        z.life -= DT;
        z.life > 0.0
    });
    if zones.0.is_empty() {
        return;
    }
    let c = &content.0;
    let en = &mut *en;
    let lava_tick = tick.0.is_multiple_of(ZONE_TICK);
    let sc = &mut *scratch;
    if sc.best.len() < ENEMY_CAP {
        sc.best = vec![0.0; ENEMY_CAP];
        sc.from = vec![0; ENEMY_CAP];
    }
    sc.touched.clear();
    for z in &zones.0 {
        if z.kind == ZoneKind::Lava && !lava_tick {
            continue;
        }
        if z.kind == ZoneKind::Lava {
            bamboo.circle(z.pos, z.radius, z.dps * ZONE_TICK as f32 * DT);
        }
        sc.found.clear();
        grid.query_circle(en, z.pos.x, z.pos.y, z.radius, &mut sc.found);
        for &j in sc.found.iter() {
            let j = j as usize;
            match z.kind {
                ZoneKind::Mud => {
                    en.mud[j] = en.mud[j].max(z.knock);
                    if z.slow > 0.0 {
                        let rk = c.enemies[en.kind[j] as usize].rank;
                        apply_slow(en, j, rk, &stats, z.slow, 0.1);
                    }
                }
                ZoneKind::Lava => {
                    if sc.best[j] == 0.0 {
                        sc.touched.push(j as u32);
                    }
                    if z.dps > sc.best[j] {
                        sc.best[j] = z.dps;
                        sc.from[j] = z.reaction;
                    }
                }
            }
        }
    }
    let dt = ZONE_TICK as f32 * DT;
    for &j in &sc.touched {
        let j = j as usize;
        let dmg = sc.best[j] * dt;
        sc.best[j] = 0.0;
        if dmg > 0.0 {
            hits.0.push(
                Hit::new(en.handle(j), dmg, Source::Reaction(sc.from[j]))
                    .flags(HIT_RAW | HIT_NOCRIT | HIT_DOT | HIT_REACT),
            );
        }
    }
}

/// update_zones 复用的临时数组。
#[derive(Default)]
pub(crate) struct Scratch {
    best: Vec<f32>,
    from: Vec<u8>,
    touched: Vec<u32>,
    found: Vec<u32>,
}

/// 灵草：到时间枯萎；主角碰到就回复生命（每秒总量有上限）。
pub(crate) fn update_herbs(
    content: Res<GameContent>,
    stats: Res<Stats>,
    mut herbs: ResMut<Herbs>,
    mut outbox: ResMut<SimOutbox>,
    player: Single<(&Pos, &mut Player, &mut Health)>,
) {
    let h = &mut *herbs;
    h.budget = (h.budget + h.rate * DT).min(h.rate);
    if h.list.is_empty() {
        return;
    }
    let (pos, mut pl, mut health) = player.into_inner();
    let reach = content.0.player.radius + HERB_REACH;
    let mut k = 0;
    while k < h.list.len() {
        let herb = &mut h.list[k];
        herb.life -= DT;
        let touched = herb.pos.distance_squared(pos.0) <= reach * reach;
        if touched && h.budget > 0.0 {
            let amount = herb.heal.min(h.budget) * stats.get(Stat::Healing);
            h.budget -= herb.heal.min(h.budget);
            heal_overflow(&mut pl, &mut health, &stats, amount, &mut outbox);
            h.list.swap_remove(k);
        } else if herb.life <= 0.0 {
            h.list.swap_remove(k);
        } else {
            k += 1;
        }
    }
}

pub(crate) fn hash_into(zones: &Zones, herbs: &Herbs, h: &mut StateHasher) {
    h.write_u32(zones.0.len() as u32);
    h.write_u32(herbs.list.len() as u32);
}
