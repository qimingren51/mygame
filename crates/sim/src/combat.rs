//! 伤害管线（docs/DESIGN.md 第 6.5 节，公式见 docs/BALANCE.md 第 3.1 节）。
//!
//! - 法器、飞剑、范围打击把 [`Hit`] 按顺序放进 [`HitQueue`]，Damage 阶段统一结算：
//!   加成区 → 暴击区 → 易伤区 → 克制区 → 扣血 → 命中触发器（灼烧、减速、冰冻……）→ 击退
//!   → 五行印记与反应（见 [`crate::reactions`]）→ 死亡进 [`Deaths`]。
//! - 反应产生的伤害直接追加到同一个队列，本步结算；反应伤害不带五行，所以不会再引起反应。
//! - 范围打击（寒波、石印、爆炸、震地、太极、燃灯）先排进 [`Strikes`]，在 Weapons 阶段末尾
//!   按空间网格找到目标，再变成逐个的 [`Hit`]。
//! - 触发器里不针对单个目标的动作（回复、爆炸、震地、全屏伤害、追加飞剑、天降宝箱）先排进
//!   [`ActionQueue`]，下一个 Weapons 阶段统一执行。这样所有“产生伤害”的入口只有一处。
//! - Death 阶段处理死亡：掉落、击杀触发器、连斩、燃灯充能、击败夜主。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{Action, AffixKind, BlastKind, Cond, Content, Element, Rank, Stat};
use lantern_core::step::DT;
use lantern_core::{Pcg32, Stream};

use crate::charms::{Survival, stance, try_rescue};
use crate::enemies::{Enemies, EnemyHandle, TAG_CHILD, TAG_FRENZY, TAG_MINIBOSS};
use crate::flow::Flow;
use crate::gems::Gems;
use crate::gold::Coins;
use crate::pickups::{PickupKind, Pickups};
use crate::reactions::{ReactCtx, ReactRes, mark};
use crate::reveal::{Reveal, Vuln};
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
/// 五行反应造成的伤害（显示用）
pub const HIT_REACT: u8 = 8;
/// 伤害已经乘过加成区（以触发伤害为基数的反应、赤地）
pub const HIT_RAW: u8 = 16;
/// 伤害原样扣除，不乘任何乘区（斩杀）
pub const HIT_TRUE: u8 = 32;
/// 冰爆：这样冻住的妖物再死不触发冰爆
pub const HIT_BLAST: u8 = 64;

/// 灼烧：每层每秒 = 命中伤害（暴击前）× 20%，持续 3 秒（docs/BALANCE.md 第 3.3 节）。
/// 冰爆、火·极境的爆炸直接点上灼烧时用。
pub const BURN_RATIO: f32 = 0.2;
pub const BURN_TIME: f32 = 3.0;

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
    /// 五行反应（`elements.ron` 里 reactions 的下标）
    Reaction(u8),
    /// 灯焰带
    Band,
    /// 轻功：闪避穿过的妖物
    Dash,
    /// 风火轮的火痕
    Trail,
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
    /// 法器命中带的五行：打印记、引起反应；反应、持续伤害、共鸣效果没有
    pub element: Option<Element>,
    /// 直接点上几层灼烧（以这一击加成区之后的伤害为基数）
    pub ignite: f32,
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
            element: None,
            ignite: 0.0,
        }
    }

    pub fn element(mut self, element: Option<Element>) -> Self {
        self.element = element;
        self
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
    /// 大于 0 时，对夜主每次不超过它最大生命的这个比例（不暴击、不击退）
    pub boss_fraction: f32,
    pub stun: f32,
    pub freeze: f32,
    pub slow: f32,
    pub slow_time: f32,
    pub source: Source,
    pub fx: StrikeFx,
    pub element: Option<Element>,
    pub ignite: f32,
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
            element: None,
            ignite: 0.0,
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
    pub handle: EnemyHandle,
    pub pos: Vec2,
    pub kind: u16,
    /// 死时处于冰冻（水·凝 三阶的冰爆）；被冰爆冻住的不算
    pub frozen: bool,
    /// 死时处于冰冻，冰爆冻住的也算（冰魄珠）
    pub iced: bool,
    pub max_hp: f32,
    pub radius: f32,
    /// 词缀与标记（分裂、小头目……）
    pub affix: u16,
    pub tags: u8,
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

/// 触发器的条件和概率。概率小于 1 时才消耗随机数。`third` 表示这是对同一只妖物的第 3n 次命中。
pub(crate) fn passes(t: &ActiveTrigger, rng: &mut Pcg32, frozen: bool, flags: u8, third: bool) -> bool {
    let ok = match t.only {
        Cond::Always => true,
        Cond::TargetFrozen => frozen,
        Cond::NotBonus => flags & HIT_BONUS == 0,
        Cond::ThirdHit => third,
    };
    ok && (t.chance >= 1.0 || rng.chance(t.chance))
}

/// 硬控：冰冻、击晕、定身。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Hard {
    Freeze { blast: bool },
    Stun,
    Root,
}

/// 控制递减（docs/BALANCE.md 第 3.3 节）：精英时长减半，6 秒内第二次 × 0.5、第三次起 × 0.25。
fn diminish(n: &mut u8, t: &mut f32) -> f32 {
    if *t <= 0.0 {
        *n = 0;
    }
    let m = match *n {
        0 => 1.0,
        1 => 0.5,
        _ => 0.25,
    };
    *n = n.saturating_add(1);
    *t = 6.0;
    m * 0.5
}

/// 施加硬控。夜主免疫；精英减半并递减。冰冻时长另乘 [`Stat::FreezeTime`]（调用方算好）。
pub(crate) fn apply_hard(en: &mut Enemies, i: usize, rank: Rank, kind: Hard, duration: f32) {
    if duration <= 0.0 || rank == Rank::Boss {
        return;
    }
    let d = if rank == Rank::Elite {
        duration * diminish(&mut en.hard_n[i], &mut en.hard_t[i])
    } else {
        duration
    };
    match kind {
        Hard::Freeze { blast } => {
            // 已经冻住的，冰爆不改变来源；新冻住的记下来源
            if en.frozen[i] <= 0.0 || !blast {
                en.blast_frozen[i] = blast;
            }
            en.frozen[i] = en.frozen[i].max(d);
        }
        Hard::Stun => en.stun[i] = en.stun[i].max(d),
        Hard::Root => en.root[i] = en.root[i].max(d),
    }
}

/// 晕头（软控）：朝随机方向乱走。夜主免疫；精英减半并递减。
pub(crate) fn apply_confuse(en: &mut Enemies, i: usize, rank: Rank, duration: f32, dir: f32) {
    if rank == Rank::Boss {
        return;
    }
    let d = if rank == Rank::Elite {
        duration * diminish(&mut en.soft_n[i], &mut en.soft_t[i])
    } else {
        duration
    };
    if d > en.confuse[i] {
        en.confuse[i] = d;
        en.confuse_dir[i] = dir;
    }
}

/// 减速：效果加上 [`Stat::SlowPower`]、最多 70%，时长乘 [`Stat::SlowTime`]；夜主减半。同类取最大，不叠加。
pub(crate) fn apply_slow(en: &mut Enemies, i: usize, rank: Rank, stats: &Stats, amount: f32, duration: f32) {
    let mut a = (amount + stats.get(Stat::SlowPower)).clamp(0.0, 0.7);
    if rank == Rank::Boss {
        a *= 0.5;
    }
    en.slow_t[i] = en.slow_t[i].max(duration * stats.get(Stat::SlowTime));
    en.slow_amount[i] = en.slow_amount[i].max(a);
}

/// 点上灼烧：每层每秒 base × ratio × 灼烧倍率，层数加 stacks（不超过上限）。
pub(crate) fn ignite(
    en: &mut Enemies,
    i: usize,
    stats: &Stats,
    base: f32,
    ratio: f32,
    stacks: f32,
    time: f32,
) {
    en.burn_t[i] = en.burn_t[i].max(time);
    en.burn_stacks[i] = (en.burn_stacks[i] + stacks).min(stats.get(Stat::BurnStacks)).max(1.0);
    en.burn_dps[i] = (en.burn_dps[i] * 0.9).max(base * ratio * stats.get(Stat::BurnDamage));
}

/// 在妖物 i 身上立即生效的动作；其余排队。`base` 是这一击加成区之后、暴击和易伤之前的伤害。
fn on_enemy(
    t: &ActiveTrigger,
    stats: &Stats,
    en: &mut Enemies,
    i: usize,
    rank: Rank,
    base: f32,
    queue: &mut ActionQueue,
) {
    match t.action {
        Action::Burn { duration, ratio } => {
            en.burn_t[i] = duration;
            en.burn_stacks[i] = (en.burn_stacks[i] + 1.0).min(stats.get(Stat::BurnStacks));
            en.burn_dps[i] = (en.burn_dps[i] * 0.9).max(base * ratio * stats.get(Stat::BurnDamage));
        }
        Action::Slow { amount, duration } => apply_slow(en, i, rank, stats, amount, duration),
        Action::Freeze { duration } => {
            apply_hard(en, i, rank, Hard::Freeze { blast: false }, duration * stats.get(Stat::FreezeTime))
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
    reveal: Res<Reveal>,
    grid: Res<Grid>,
    progress: Res<Progress>,
    tick: Res<Tick>,
    mut rng: ResMut<SimRng>,
    mut hits: ResMut<HitQueue>,
    mut en: ResMut<Enemies>,
    mut deaths: ResMut<Deaths>,
    mut queue: ResMut<ActionQueue>,
    mut log: ResMut<DamageLog>,
    mut outbox: ResMut<SimOutbox>,
    mut react: ReactRes,
    player: Single<&Player>,
) {
    let content = &content.0;
    let rng = rng.0.get(Stream::Combat);
    let en = &mut *en;
    let crit_chance = stats.get(Stat::CritChance);
    let crit_mult = stats.get(Stat::CritMult);
    // 加成区：定海神针的站定、移动加成也算在这里
    let dmg_mult = stats.get(Stat::Damage) + stance(&stats, &content.player.charms, &player);
    let stun_crit = stats.get(Stat::StunCrit) > 0.0;
    let freeze_time = stats.get(Stat::FreezeTime);
    let zones = &content.elements.zones;
    let dark = stats.get(Stat::DarkDamage);
    let affixes = AffixTable::new(content);
    let vuln = Vuln::new(&reveal, &stats, zones.vuln_cap);
    // 反应产生的命中追加在队尾，本步一起结算
    let mut list = std::mem::take(&mut hits.0);
    let mut ctx = ReactCtx::new(content, &stats, &grid, progress.level, tick.secs(), &mut react);
    let mut k = 0;
    while k < list.len() {
        let hit = list[k];
        k += 1;
        let Some(i) = en.resolve(hit.target) else { continue };
        let def = &content.enemies[en.kind[i] as usize];
        let rank = def.rank;
        let boss = rank == Rank::Boss;
        if hit.freeze > 0.0 {
            let blast = hit.flags & HIT_BLAST != 0;
            apply_hard(en, i, rank, Hard::Freeze { blast }, hit.freeze * freeze_time);
        }
        let pos = Vec2::new(en.x[i], en.y[i]);
        // 加成区；夜签“无月”：照见圈外（也不在光区里）的妖物再加一截
        let bonus = if dark > 0.0 && !reveal.covers(pos) { dmg_mult + dark } else { dmg_mult };
        let base = if hit.flags & (HIT_RAW | HIT_TRUE) != 0 { hit.damage } else { hit.damage * bonus };
        let crit = hit.flags & (HIT_NOCRIT | HIT_TRUE) == 0
            && (rng.next_f32() < crit_chance || (en.stun[i] > 0.0 && stun_crit));
        let mut dmg = base;
        if hit.flags & HIT_TRUE == 0 {
            if crit {
                dmg *= crit_mult;
            }
            dmg *= vuln.of(en, i);
            // 克制区：只对法器的直接命中
            if let (Some(a), Some(b)) = (hit.element, def.element)
                && hit.flags & HIT_RAW == 0
            {
                if a.overcomes(b) {
                    dmg *= zones.counter;
                } else if a == b {
                    dmg *= zones.same;
                }
            }
        }
        // 词缀“坚”：生命高于一半时减伤
        if en.affix[i] != 0
            && let Some((above, reduction)) = affixes.tough(en.affix[i])
            && en.hp[i] > en.max_hp[i] * above
        {
            dmg *= 1.0 - reduction;
        }
        if boss && hit.boss_cap > 0.0 {
            dmg = dmg.min(hit.boss_cap);
        }
        // 统计只计实际打掉的血（溢出的不算）
        log.add(hit.source, dmg.min(en.hp[i].max(0.0)));
        en.hp[i] -= dmg;
        en.flash[i] = 0.08;
        // 词缀“狂”：生命低于一半后移速和接触伤害提高
        if en.affix[i] != 0
            && en.tags[i] & TAG_FRENZY == 0
            && let Some((below, boost)) = affixes.frenzy(en.affix[i])
            && en.hp[i] > 0.0
            && en.hp[i] < en.max_hp[i] * below
        {
            en.tags[i] |= TAG_FRENZY;
            en.speed[i] *= 1.0 + boost;
            en.damage[i] *= 1.0 + boost;
        }
        let kind = if hit.flags & HIT_REACT != 0 {
            HitKind::Reaction
        } else if hit.flags & HIT_DOT != 0 {
            HitKind::Dot
        } else if hit.flags & HIT_BONUS != 0 {
            HitKind::Bonus
        } else {
            HitKind::Normal
        };
        outbox.0.push(SimEvent::Hit { pos: pos - Vec2::new(0.0, en.r[i] + 4.0), damage: dmg, crit, kind });

        if hit.flags & HIT_DOT == 0 {
            en.hit_n[i] = en.hit_n[i].wrapping_add(1);
            let third = en.hit_n[i].is_multiple_of(3);
            let frozen = en.frozen[i] > 0.0;
            for t in &effects.hit {
                if passes(t, rng, frozen, hit.flags, third) {
                    on_enemy(t, &stats, en, i, rank, base, &mut queue);
                }
            }
            if crit {
                for t in &effects.crit {
                    if passes(t, rng, frozen, hit.flags, third) {
                        on_enemy(t, &stats, en, i, rank, base, &mut queue);
                    }
                }
            }
            if hit.knockback > 0.0 && !boss {
                let d = pos - hit.from;
                let len = d.length().max(1e-3);
                let mut f = hit.knockback * stats.get(Stat::Knockback);
                if rank == Rank::Elite {
                    f /= 3.0;
                }
                if en.mud[i] > 0.0 {
                    f *= en.mud[i];
                }
                en.kx[i] += d.x / len * f;
                en.ky[i] += d.y / len * f;
            }
        }
        if hit.ignite > 0.0 {
            ignite(en, i, &stats, base, BURN_RATIO, hit.ignite, BURN_TIME);
        }
        if let Some(e) = hit.element
            && hit.flags & (HIT_RAW | HIT_TRUE) == 0
        {
            mark(&mut ctx, en, i, e, base, &mut list, rng, &mut outbox);
        }

        if en.hp[i] > 0.0 {
            if hit.stun > 0.0 {
                apply_hard(en, i, rank, Hard::Stun, hit.stun);
            }
            if hit.slow > 0.0 {
                apply_slow(en, i, rank, &stats, hit.slow, hit.slow_time);
            }
        } else {
            kill(en, i, rank, &mut deaths, &mut outbox);
        }
    }
    list.clear();
    hits.0 = list;
}

/// 妖物死亡：移出池子，记下死亡等 Death 阶段处理。
pub(crate) fn kill(en: &mut Enemies, i: usize, rank: Rank, deaths: &mut Deaths, outbox: &mut SimOutbox) {
    let pos = Vec2::new(en.x[i], en.y[i]);
    let kind = en.kind[i];
    deaths.0.push(Death {
        handle: en.handle(i),
        pos,
        kind,
        frozen: en.frozen[i] > 0.0 && !en.blast_frozen[i],
        iced: en.frozen[i] > 0.0,
        max_hp: en.max_hp[i],
        radius: en.r[i],
        affix: en.affix[i],
        tags: en.tags[i],
    });
    en.kill(i);
    outbox.0.push(SimEvent::Kill { pos, kind, rank });
}

/// 追加飞剑的额度：每秒补充 `bonus_sword_rate` 把，最多攒这么多（金·极境的上限）。
#[derive(Resource, Default, Debug)]
pub struct SwordBudget(pub f32);

/// 执行排队的动作。
pub(crate) fn run_actions(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    progress: Res<Progress>,
    en: Res<Enemies>,
    player: Single<(&Pos, &mut Player, &mut Health)>,
    mut rng: ResMut<SimRng>,
    mut queue: ResMut<ActionQueue>,
    mut strikes: ResMut<Strikes>,
    mut shots: ResMut<Shots>,
    mut pickups: ResMut<Pickups>,
    mut budget: ResMut<SwordBudget>,
    mut outbox: ResMut<SimOutbox>,
) {
    let (pos, mut pl, mut health) = player.into_inner();
    let p = pos.0;
    let minute = tick.secs() / 60.0;
    let rate = content.0.elements.bonus_sword_rate;
    budget.0 = (budget.0 + rate * DT).min(rate);
    for d in queue.0.drain(..) {
        match d.action {
            Action::Heal(v) => {
                heal_overflow(&mut pl, &mut health, &stats, v * stats.get(Stat::Healing), &mut outbox)
            }
            Action::Explode { radius, damage, kind, freeze, ignite } => {
                let mut s = Strike::new(
                    d.pos,
                    Area::Circle(radius),
                    damage.at(minute),
                    Source::Blast,
                    StrikeFx::Blast(kind),
                );
                s.flags = HIT_NOCRIT | HIT_DOT;
                if freeze > 0.0 {
                    s.freeze = freeze;
                    s.flags |= HIT_BLAST;
                }
                s.ignite = ignite;
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
                if budget.0 < 1.0 {
                    continue;
                }
                budget.0 -= 1.0;
                let target = d.target.and_then(|h| en.resolve(h).map(|i| (h, Vec2::new(en.x[i], en.y[i]))));
                let angle = match target {
                    Some((_, t)) => ops::atan2(t.y - p.y, t.x - p.x),
                    None => ops::atan2(d.pos.y - p.y, d.pos.x - p.x),
                };
                shots.fire(crate::weapons::volley::ShotSpec {
                    pos: p,
                    angle,
                    speed: speed * stats.get(Stat::ProjSpeed),
                    life: life * stats.get(Stat::ProjLife),
                    turn,
                    hit_radius,
                    knockback,
                    damage: damage.at(progress.level as f32),
                    pierce,
                    target: target.map(|(h, _)| h),
                    skip: None,
                    big: false,
                    bonus: true,
                    flags: HIT_BONUS,
                    element: Some(Element::Metal),
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

/// 回复生命；满血时多出的部分按 [`Stat::OverhealShield`] 转成护盾（木·极境）。
pub(crate) fn heal_overflow(
    player: &mut Player,
    health: &mut Health,
    stats: &Stats,
    amount: f32,
    outbox: &mut SimOutbox,
) {
    if amount <= 0.0 || health.hp <= 0.0 {
        return;
    }
    let room = health.max - health.hp;
    heal(health, amount, outbox);
    let cap = stats.get(Stat::OverhealShield) * health.max;
    let extra = amount - room.max(0.0);
    if cap > 0.0 && extra > 0.0 && player.shield < cap {
        player.shield = (player.shield + extra).min(cap);
        player.shield_max = player.shield_max.max(player.shield);
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
                element: s.element,
                ignite: s.ignite,
            };
            // 燃灯对夜主：每次不超过它最大生命的一定比例
            if boss && s.boss_fraction > 0.0 {
                hit.boss_cap = en.max_hp[i] * s.boss_fraction;
                hit.flags |= HIT_NOCRIT;
                hit.knockback = 0.0;
            }
            hits.0.push(hit);
        }
    }
}

/// 灼烧：每步扣血（每跳乘一次易伤），累计满 1 点、每 0.5 秒冒一个数字。
pub(crate) fn burn(
    content: Res<GameContent>,
    stats: Res<Stats>,
    reveal: Res<Reveal>,
    mut en: ResMut<Enemies>,
    mut deaths: ResMut<Deaths>,
    mut log: ResMut<DamageLog>,
    mut outbox: ResMut<SimOutbox>,
) {
    let en = &mut *en;
    let vuln = Vuln::new(&reveal, &stats, content.0.elements.zones.vuln_cap);
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
        let dmg = en.burn_dps[i] * en.burn_stacks[i] * DT * vuln.of(en, i);
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

/// 处理本步的死亡：掉落、击杀触发器、连斩、燃灯充能、分裂、击败夜主。
#[allow(clippy::too_many_arguments)]
pub(crate) fn process_deaths(
    content: Res<GameContent>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    tick: Res<Tick>,
    mut rng: ResMut<SimRng>,
    mut deaths: ResMut<Deaths>,
    mut en: ResMut<Enemies>,
    mut gems: ResMut<Gems>,
    mut coins: ResMut<Coins>,
    mut pickups: ResMut<Pickups>,
    mut progress: ResMut<Progress>,
    mut director: ResMut<Director>,
    mut flow: ResMut<Flow>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut survival: ResMut<Survival>,
) {
    let c = &content.0;
    let t = tick.secs();
    let minute = t / 60.0;
    let g = &c.run.gems;
    let frozen_xp = 1.0 + stats.get(Stat::FrozenXp);
    let gd = &c.run.gold;
    let drops = &c.run.drops;
    let gold_mult = stats.get(Stat::GoldGain);
    // 燃灯按清怪量充能：基础刷怪曲线每秒刷出的总血量 × clear_seconds 充满一次。
    // 更和夜签改了妖物生命、刷怪速度时分母一起乘上，充能节奏不随难度变快（docs/BALANCE.md 第 2.6 节）
    let clear = crate::spawn::base_spawn_hp(c, minute)
        * stats.get(Stat::EnemyHp)
        * stats.get(Stat::SpawnRate)
        * c.player.ult.clear_seconds;
    let ult_mult = stats.get(Stat::UltCharge);
    for d in deaths.0.drain(..) {
        let def = &c.enemies[d.kind as usize];
        if let Some(loot) = &def.loot {
            // 金蟾：散落大量魂火和铜钱，不计击杀
            let total = c.run.xp_need.at(progress.level as f32) * loot.xp_levels;
            let r = rng.0.get(Stream::Drop);
            for _ in 0..loot.gems {
                let a = r.range_f32(0.0, TAU);
                let dist = r.range_f32(loot.scatter.0, loot.scatter.1);
                let (s, co) = ops::sin_cos(a);
                gems.drop(d.pos + Vec2::new(co, s) * dist, total / loot.gems as f32, g.cap);
            }
            let amount = loot.gold as f32 * gold_mult;
            coins.scatter(r, d.pos, amount, gd.coin_value as f32 * gold_mult, gd.scatter * 1.5, gd.cap);
            outbox.0.push(SimEvent::CritterLooted { pos: d.pos });
            continue;
        }
        if def.rank == Rank::Critter {
            continue;
        }
        let child = d.tags & TAG_CHILD != 0;
        let miniboss = d.tags & TAG_MINIBOSS != 0;
        let elite = def.rank == Rank::Elite && !child;
        if elite {
            survival.elite_down(d.handle);
        }
        let p = &mut *progress;
        p.kills += 1;
        p.combo = if p.combo_t > 0.0 { p.combo + 1 } else { 1 };
        p.combo_t = c.run.combo.window;
        p.best_combo = p.best_combo.max(p.combo);
        if c.run.combo.milestones.contains(&p.combo) {
            outbox.0.push(SimEvent::Combo { count: p.combo });
        }
        let mut charge = if clear > 0.0 { d.max_hp / clear } else { 0.0 };
        if elite {
            charge += c.player.ult.charge_elite;
        }
        let was_ready = p.ult >= 1.0;
        p.ult = (p.ult + charge * ult_mult).min(1.0);
        if p.ult >= 1.0 && !was_ready {
            outbox.0.push(SimEvent::UltReady);
        }

        let loot = rng.0.get(Stream::Drop);
        let split = split_affix(c, d.affix);
        // 分出来的小号魂火固定
        let xp = if child {
            c.affixes
                .iter()
                .find_map(|a| match a.kind {
                    AffixKind::Split { xp, .. } => Some(xp),
                    _ => None,
                })
                .unwrap_or(def.xp)
        } else {
            def.xp
        };
        if xp > 0.0 {
            let mut value = xp * c.run.gem_value_scale.at(minute) * stats.get(Stat::XpGain);
            // 冰魄珠：冰冻中被击杀的妖物魂火翻倍
            if d.iced {
                value *= frozen_xp;
            }
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
        let per_coin = gd.coin_value as f32 * gold_mult;
        if elite {
            let kind = if miniboss { PickupKind::BossChest } else { PickupKind::Chest };
            pickups.drop(kind, d.pos);
            pickups.drop(PickupKind::Bell, d.pos + Vec2::new(24.0, 0.0));
            let amount = if miniboss { gd.miniboss } else { gd.elite } as f32 * gold_mult;
            coins.scatter(loot, d.pos, amount, per_coin, gd.scatter, gd.cap);
        } else if def.rank == Rank::Boss {
            coins.scatter(loot, d.pos, gd.boss as f32 * gold_mult, per_coin * 2.0, gd.scatter * 2.0, gd.cap);
        } else if !child {
            if loot.chance(drops.bell_chance) {
                pickups.drop(PickupKind::Bell, d.pos);
            } else if stats.can_heal() && loot.chance(drops.lotus_chance) {
                pickups.drop(PickupKind::Lotus, d.pos);
            }
            if loot.chance(gd.normal_chance) {
                coins.drop(d.pos, gold_mult, gd.cap);
            }
        }

        // 词缀“分”：死后分成几只小号（小号不算精英，不再分裂）
        if let Some((count, hp, radius)) = split
            && !child
        {
            let sp = rng.0.get(Stream::Spawn);
            for k in 0..count {
                let a = k as f32 * TAU / count as f32;
                let (s, co) = ops::sin_cos(a);
                let at = d.pos + Vec2::new(co, s) * d.radius * 0.6;
                if let Some(i) = crate::spawn::spawn_enemy(c, &stats, &mut en, sp, d.kind, at.x, at.y, minute)
                {
                    en.tags[i] |= TAG_CHILD;
                    en.hp[i] = d.max_hp * hp;
                    en.max_hp[i] = en.hp[i];
                    en.r[i] = d.radius * radius;
                }
            }
        }

        let combat = rng.0.get(Stream::Combat);
        for trig in &effects.kill {
            if passes(trig, combat, d.frozen, 0, false) {
                queue.0.push(Deferred { action: trig.action, pos: d.pos, target: None });
            }
        }

        if def.rank == Rank::Boss {
            director.boss = None;
            director.barrier = None;
            flow.won_at = Some(t + c.run.win_delay);
            coins.pull_all();
            outbox.0.push(SimEvent::BossDefeated { pos: d.pos });
        }
    }
}

/// 结算命中时要查的词缀（按位）。
struct AffixTable {
    tough: Option<(u16, f32, f32)>,
    frenzy: Option<(u16, f32, f32)>,
}

impl AffixTable {
    fn new(c: &Content) -> Self {
        let mut t = AffixTable { tough: None, frenzy: None };
        for (k, a) in c.affixes.iter().enumerate() {
            match a.kind {
                AffixKind::Tough { above, reduction } => t.tough = Some((1 << k, above, reduction)),
                AffixKind::Frenzy { below, boost } => t.frenzy = Some((1 << k, below, boost)),
                _ => {}
            }
        }
        t
    }

    fn tough(&self, affix: u16) -> Option<(f32, f32)> {
        self.tough.filter(|&(bit, ..)| affix & bit != 0).map(|(_, a, r)| (a, r))
    }

    fn frenzy(&self, affix: u16) -> Option<(f32, f32)> {
        self.frenzy.filter(|&(bit, ..)| affix & bit != 0).map(|(_, b, k)| (b, k))
    }
}

/// 带“分”词缀时返回 (只数, 生命比例, 半径比例)。
fn split_affix(c: &Content, affix: u16) -> Option<(u32, f32, f32)> {
    if affix == 0 {
        return None;
    }
    c.affixes.iter().enumerate().find_map(|(k, a)| match a.kind {
        AffixKind::Split { count, hp, radius, .. } if affix & (1 << k) != 0 => Some((count, hp, radius)),
        _ => None,
    })
}

/// 主角减伤的合计上限。
const REDUCTION_CAP: f32 = 0.6;

/// 主角受伤需要的东西。
pub(crate) struct HurtCtx<'a> {
    pub content: &'a Content,
    pub stats: &'a Stats,
    pub effects: &'a Effects,
    pub queue: &'a mut ActionQueue,
    pub rng: &'a mut Pcg32,
    pub god: bool,
    pub outbox: &'a mut SimOutbox,
    pub survival: &'a mut Survival,
}

/// 主角受伤：无敌或闪避中不受伤；减伤（含定海神针的站定减伤）、护甲、护盾依次生效；之后进入无敌时间。
/// 致命时先试回光、九转金丹。这一下落到了主角身上（哪怕被护盾挡下）时返回 true。
pub(crate) fn hurt_player(
    player: &mut Player,
    health: &mut Health,
    pos: Vec2,
    amount: f32,
    ctx: &mut HurtCtx,
) -> bool {
    if player.iframe > 0.0 || player.dash_t > 0.0 || health.hp <= 0.0 {
        return false;
    }
    let s = ctx.stats;
    let mut reduction = s.get(Stat::Reduction);
    if player.still_t >= ctx.content.player.charms.still_after {
        reduction += s.get(Stat::StillReduction);
    }
    // 减伤合计（含站定减伤）最多 60%（docs/BALANCE.md 第 3.2 节）
    let mut dmg = (amount * (1.0 - reduction.min(REDUCTION_CAP)) - s.get(Stat::Armor)).max(1.0);
    if player.shield > 0.0 {
        let absorbed = player.shield.min(dmg);
        player.shield -= absorbed;
        dmg -= absorbed;
        if player.shield <= 0.0 {
            player.shield = 0.0;
            player.shield_t = s.get(Stat::ShieldCooldown);
            ctx.outbox.0.push(SimEvent::ShieldBroken);
            for t in &ctx.effects.shield_break {
                if passes(t, ctx.rng, false, 0, false) {
                    ctx.queue.0.push(Deferred { action: t.action, pos, target: None });
                }
            }
        }
    }
    player.iframe = ctx.content.player.hurt_iframe;
    if dmg <= 0.0 || ctx.god {
        return true;
    }
    ctx.survival.hurts += 1;
    ctx.survival.taken += dmg.min(health.hp);
    health.hp = (health.hp - dmg).max(0.0);
    ctx.outbox.0.push(SimEvent::PlayerHurt { amount: dmg });
    if health.hp <= 0.0 && !try_rescue(ctx.content, s, ctx.survival, player, health, pos, ctx.outbox) {
        ctx.outbox.0.push(SimEvent::PlayerDied);
    }
    true
}
