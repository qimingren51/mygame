//! 灯坠的局内机制与救命（docs/GAMEPLAY.md 第 5.7、11.3 节）：风火轮的火痕、回光与九转金丹、局内灯坠三选一的选项。
//!
//! 数值类灯坠（长命锁、断剑……）只是属性修正，在 stats 模块汇总；这里只放需要每步结算的规则。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::{CharmTuning, Content, Effect, Rank, Rule, Stat};
use lantern_core::step::DT;
use lantern_core::{Pcg32, StateHasher};

use crate::boss::Foes;
use crate::build::Build;
use crate::combat::{HIT_DOT, HIT_NOCRIT, Hit, HitQueue, Source};
use crate::enemies::{Enemies, EnemyHandle};
use crate::spatial::Grid;
use crate::stats::{Stats, StatsDirty};
use crate::weapons::Arsenal;
use crate::{GameContent, Health, Player, Pos, RunSetup, SimEvent, SimOutbox};

/// 火痕最多同时几段（老的先灭）。
const TRAIL_CAP: usize = 48;
/// 火痕每 0.5 秒结算一次伤害。
const TRAIL_TICK: u32 = 30;

/// 风火轮留下的火痕：每一段是一个小圆。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Ember {
    pub pos: Vec2,
    pub life: f32,
}

#[derive(Resource, Default, Debug)]
pub struct Trail {
    pub list: Vec<Ember>,
    /// 上一段的位置（本次闪避还没留过就是 None）
    last: Option<Vec2>,
    /// 结算伤害的步数计数
    tick: u32,
}

impl Trail {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.list.len() as u32);
        for e in &self.list {
            h.write_f32(e.pos.x);
            h.write_f32(e.pos.y);
            h.write_f32(e.life);
        }
    }
}

/// 受伤与救命的记录。
#[derive(Resource, Default, Debug)]
pub struct Survival {
    /// 本局掉过几次血、一共掉了多少（护盾挡下的不算）
    pub hurts: u32,
    pub taken: f32,
    /// 回光、九转金丹已经用过
    pub last_stand: bool,
    pub revived: bool,
    /// 待结算的震退：位置和半径（全屏为无穷大）；是否清掉弹幕
    pub quake: Option<(Vec2, f32, bool)>,
    /// 在场的精英和它出场时的受伤次数；不受伤击败的精英数（成就）
    pub watch: Vec<(EnemyHandle, u32)>,
    pub flawless: u32,
}

impl Survival {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.hurts);
        h.write_f32(self.taken);
        h.write_u32(u32::from(self.last_stand) | (u32::from(self.revived) << 1));
        h.write_u32(self.flawless);
    }

    /// 精英出场：记下此刻的受伤次数。
    pub(crate) fn watch(&mut self, h: EnemyHandle) {
        self.watch.push((h, self.hurts));
    }

    /// 精英倒下：从出场到现在没掉过血就记一次无伤。
    pub(crate) fn elite_down(&mut self, h: EnemyHandle) {
        if let Some(k) = self.watch.iter().position(|&(w, _)| w == h) {
            let (_, at) = self.watch.swap_remove(k);
            if at == self.hurts {
                self.flawless += 1;
            }
        }
    }
}

/// 致命的一击落下前，依次试回光、九转金丹。救下来时返回 true（生命已经改好）。
pub(crate) fn try_rescue(
    content: &Content,
    stats: &Stats,
    survival: &mut Survival,
    player: &mut Player,
    health: &mut Health,
    pos: Vec2,
    outbox: &mut SimOutbox,
) -> bool {
    let max = health.max;
    let r = &content.player.rescue;
    let last_stand = stats.get(Stat::LastStand);
    if last_stand >= 1.0 && !survival.last_stand {
        survival.last_stand = true;
        health.hp = 1.0 + if last_stand >= 2.0 { max * r.last_stand_heal } else { 0.0 };
        survival.quake = Some((pos, r.radius, false));
        outbox.0.push(SimEvent::LastStand { pos });
    } else if stats.rule(Rule::Revive) && !survival.revived {
        survival.revived = true;
        health.hp = max * r.revive_heal;
        survival.quake = Some((pos, f32::INFINITY, true));
        outbox.0.push(SimEvent::Revived { pos });
    } else {
        return false;
    }
    player.iframe = player.iframe.max(r.iframe);
    true
}

/// 闪避途中每走一段距离留一段火痕。
pub(crate) fn lay_trail(
    content: Res<GameContent>,
    stats: Res<Stats>,
    mut trail: ResMut<Trail>,
    player: Single<(&Pos, &Player)>,
) {
    let (pos, p) = *player;
    trail.list.retain_mut(|e| {
        e.life -= DT;
        e.life > 0.0
    });
    if p.dash_t <= 0.0 || stats.get(Stat::TrailDamage) <= 0.0 {
        trail.last = None;
        return;
    }
    let def = &content.0.player.charms;
    if trail.last.is_some_and(|l| l.distance_squared(pos.0) < def.trail_gap * def.trail_gap) {
        return;
    }
    if trail.list.len() >= TRAIL_CAP {
        trail.list.remove(0);
    }
    trail.list.push(Ember { pos: pos.0, life: def.trail_life });
    trail.last = Some(pos.0);
}

/// 火痕每 0.5 秒烧一次踩在上面的妖物（同一只只算一次）。
pub(crate) fn burn_trail(
    content: Res<GameContent>,
    stats: Res<Stats>,
    arsenal: Res<Arsenal>,
    grid: Res<Grid>,
    en: Res<Enemies>,
    mut trail: ResMut<Trail>,
    mut hits: ResMut<HitQueue>,
    mut bamboo: ResMut<crate::bamboo::Bamboo>,
    mut found: Local<Vec<u32>>,
    mut seen: Local<Vec<u32>>,
) {
    if trail.list.is_empty() {
        trail.tick = 0;
        return;
    }
    trail.tick += 1;
    if !trail.tick.is_multiple_of(TRAIL_TICK) {
        return;
    }
    let c = &content.0;
    let best = arsenal.0.iter().map(|w| w.stats(c).damage).fold(0.0f32, f32::max);
    let dmg = best * stats.get(Stat::TrailDamage) * TRAIL_TICK as f32 * DT;
    if dmg <= 0.0 {
        return;
    }
    seen.clear();
    let r = c.player.charms.trail_radius;
    for e in &trail.list {
        bamboo.circle(e.pos, r, dmg);
        found.clear();
        grid.query_circle(&en, e.pos.x, e.pos.y, r, &mut found);
        for &i in found.iter() {
            if !seen.contains(&i) {
                seen.push(i);
                hits.0.push(Hit::new(en.handle(i as usize), dmg, Source::Trail).flags(HIT_DOT | HIT_NOCRIT));
            }
        }
    }
}

/// 回光、九转金丹救下之后：震退周围（九转金丹震退全屏、清掉弹幕），九转金丹碎掉。
pub(crate) fn apply_rescue(
    content: Res<GameContent>,
    mut survival: ResMut<Survival>,
    mut en: ResMut<Enemies>,
    mut foes: ResMut<Foes>,
    mut build: ResMut<Build>,
    mut dirty: ResMut<StatsDirty>,
) {
    let Some((at, radius, full)) = survival.quake.take() else { return };
    let c = &content.0;
    let force = c.player.rescue.knockback;
    let en = &mut *en;
    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        let rank = c.enemies[en.kind[i] as usize].rank;
        let d = Vec2::new(en.x[i], en.y[i]) - at;
        let len = d.length();
        if rank == Rank::Boss || len > radius {
            continue;
        }
        let f = if rank == Rank::Elite { force / 3.0 } else { force };
        let dir = if len > 1e-3 { d / len } else { Vec2::X };
        en.kx[i] += dir.x * f;
        en.ky[i] += dir.y * f;
    }
    if full {
        foes.0.clear();
        // 九转金丹用过就碎
        let before = build.charms.len();
        build.charms.retain(|&k| !c.charms[k].effects.contains(&Effect::Rule(Rule::Revive)));
        if build.charms.len() != before {
            dirty.0 = true;
        }
    }
}

/// 定海神针：站定时的伤害加成，移动时的伤害减成（加成区）。
pub(crate) fn stance(stats: &Stats, def: &CharmTuning, p: &Player) -> f32 {
    if p.still_t >= def.still_after {
        stats.get(Stat::StillDamage)
    } else if p.moved > 1e-3 {
        stats.get(Stat::MovingDamage)
    } else {
        0.0
    }
}

/// 灯坠栏有几格。
pub fn charm_slots(stats: &Stats) -> usize {
    stats.get(Stat::CharmSlots).round().max(0.0) as usize
}

/// 局内灯坠三选一能抽的灯坠：已解锁的，不出已经挂着的、不出这一局碎掉的；法器太多时不出断剑。
pub fn charm_candidates(
    content: &Content,
    setup: &RunSetup,
    build: &Build,
    survival: &Survival,
    weapons: usize,
) -> Vec<usize> {
    let mut pool: Vec<usize> = setup
        .charm_pool
        .iter()
        .filter_map(|id| content.charm_index(id))
        .filter(|&k| {
            let d = &content.charms[k];
            !build.charms.contains(&k)
                && d.max_weapons.is_none_or(|m| weapons <= m as usize)
                && !(survival.revived && d.effects.contains(&Effect::Rule(Rule::Revive)))
        })
        .collect();
    pool.sort_unstable();
    pool.dedup();
    pool
}

/// 局内灯坠三选一的选项：从 [`charm_candidates`] 里不放回地抽。
pub fn roll_charms(
    content: &Content,
    setup: &RunSetup,
    build: &Build,
    survival: &Survival,
    weapons: usize,
    rng: &mut Pcg32,
) -> Vec<usize> {
    let mut pool = charm_candidates(content, setup, build, survival, weapons);
    let n = (content.run.choices.charm_offers as usize).min(pool.len());
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        let k = rng.below(pool.len() as u32) as usize;
        out.push(pool.swap_remove(k));
    }
    out
}
