//! 属性与触发器的汇总（docs/DESIGN.md 第 6.6 节）。
//!
//! 修正来源：心灯、夜签、心法、五行共鸣、相生、太极、古灯增益。任何来源变化时把 [`StatsDirty`]
//! 置位，下一个刷新点统一重算：属性值写进 [`Stats`]，触发器按时机分组写进 [`Effects`]。

use bevy_ecs::prelude::*;

use lantern_content::{Action, Cond, Content, Effect, Quad, Rule, Stat, When};

use crate::build::Build;
use crate::{Health, Player, RunSetup};

/// 主角的全部属性（按 [`Stat`] 编号）。
#[derive(Resource, Clone, Debug, PartialEq)]
pub struct Stats {
    v: [f32; Stat::COUNT],
    /// 生效中的规则开关（[`Rule::bit`]）
    rules: u32,
}

impl Stats {
    /// 只有基础值。
    pub fn base(content: &Content) -> Self {
        let mut v = [0.0; Stat::COUNT];
        for (i, d) in content.stats.iter().enumerate() {
            v[i] = d.base.clamp(d.min, d.max);
        }
        Stats { v, rules: 0 }
    }

    pub fn get(&self, s: Stat) -> f32 {
        self.v[s as usize]
    }

    pub fn rule(&self, r: Rule) -> bool {
        self.rules & r.bit() != 0
    }

    /// 法器数量加值。
    pub fn amount(&self) -> u32 {
        self.get(Stat::Amount).max(0.0) as u32
    }

    pub fn max_hp(&self) -> f32 {
        self.get(Stat::MaxHp)
    }

    /// 能否回复生命（夜签“贪婪”会关掉）。
    pub fn can_heal(&self) -> bool {
        self.get(Stat::Healing) > 0.0
    }

    pub fn hash_into(&self, h: &mut lantern_core::StateHasher) {
        for &x in &self.v {
            h.write_f32(x);
        }
        h.write_u32(self.rules);
    }
}

/// 一条生效中的触发器。
#[derive(Clone, Debug, PartialEq)]
pub struct ActiveTrigger {
    /// 来源 + 序号，重算时用来保留周期触发器的计时
    pub key: u32,
    pub chance: f32,
    pub only: Cond,
    pub action: Action,
    /// 周期触发器的间隔与已经过的时间
    pub period: f32,
    pub elapsed: f32,
}

/// 生效中的触发器（按时机分组）和护盾。
#[derive(Resource, Clone, Debug, Default, PartialEq)]
pub struct Effects {
    pub hit: Vec<ActiveTrigger>,
    pub crit: Vec<ActiveTrigger>,
    pub kill: Vec<ActiveTrigger>,
    pub shield_break: Vec<ActiveTrigger>,
    pub periodic: Vec<ActiveTrigger>,
    /// 护盾值（x 为分钟）；None 表示没有护盾
    pub shield: Option<Quad>,
}

/// 构筑变了，属性需要重算。
#[derive(Resource, Default, Debug)]
pub struct StatsDirty(pub bool);

/// 修正来源的种类，组成触发器的 key。
#[derive(Clone, Copy)]
enum Source {
    Meta = 1,
    Omen,
    Passive,
    Tier,
    Sheng,
    Taiji,
    Buff,
    Difficulty,
    Attribute,
    Lamp,
    Charm,
}

/// 属性的一项来源（局内属性面板悬停时列出）。下标指向内容里对应的列表。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StatSource {
    /// 主角等级（照见圈、灯光随等级变大）
    Level,
    Meta(usize),
    Attribute(usize),
    Lamp(usize),
    Charm(usize),
    Omen(usize),
    Difficulty(usize),
    Passive(usize),
    /// 五行下标、第几阶（从 0 起）
    Tier(usize, usize),
    Sheng(usize),
    Taiji,
    Buff(usize),
}

/// 一项来源给某个属性的加值和乘值。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StatContribution {
    pub from: StatSource,
    pub add: f32,
    pub mul: f32,
}

struct Acc {
    add: [f32; Stat::COUNT],
    mul: [f32; Stat::COUNT],
    rules: u32,
    effects: Effects,
    /// 要列来源的属性（界面用；模拟里是 None）
    trace: Option<Stat>,
    found: Vec<StatContribution>,
}

impl Acc {
    fn note(&mut self, from: StatSource, s: Stat, add: f32, mul: f32) {
        if self.trace != Some(s) {
            return;
        }
        match self.found.last_mut() {
            Some(last) if last.from == from => {
                last.add += add;
                last.mul += mul;
            }
            _ => self.found.push(StatContribution { from, add, mul }),
        }
    }

    fn apply(&mut self, list: &[Effect], times: f32, source: Source, index: usize, from: StatSource) {
        for (k, e) in list.iter().enumerate() {
            let key = ((source as u32) << 24) | ((index as u32 & 0xffff) << 8) | (k as u32 & 0xff);
            match e {
                Effect::Add(s, v) => {
                    self.add[*s as usize] += v * times;
                    self.note(from, *s, v * times, 0.0);
                }
                Effect::Mul(s, v) => {
                    self.mul[*s as usize] += v * times;
                    self.note(from, *s, 0.0, v * times);
                }
                Effect::Trigger { on, chance, only, action } => {
                    let t = ActiveTrigger {
                        key,
                        chance: *chance,
                        only: *only,
                        action: *action,
                        period: if let When::Periodic(p) = on { *p } else { 0.0 },
                        elapsed: 0.0,
                    };
                    match on {
                        When::Hit => self.effects.hit.push(t),
                        When::Crit => self.effects.crit.push(t),
                        When::Kill => self.effects.kill.push(t),
                        When::ShieldBreak => self.effects.shield_break.push(t),
                        When::Periodic(_) => self.effects.periodic.push(t),
                    }
                }
                Effect::Shield { amount } => self.effects.shield = Some(*amount),
                Effect::Rule(r) => self.rules |= r.bit(),
                // 按共鸣阶数算，汇总时另外处理
                Effect::ByTiers { .. } => {}
                // 共鸣点数和选项偏向在构筑里处理
                Effect::Points(_) | Effect::Favor => {}
            }
        }
    }
}

/// 汇总全部修正来源。`buff` 是古灯增益在 `events.ron` 里的下标，`level` 是主角等级
/// （照见圈、灯光随等级变大）。
pub fn collect(
    content: &Content,
    setup: &RunSetup,
    build: &Build,
    buff: Option<usize>,
    level: u32,
) -> (Stats, Effects) {
    let acc = accumulate(content, setup, build, buff, level, None);
    let mut v = [0.0; Stat::COUNT];
    for (i, d) in content.stats.iter().enumerate() {
        v[i] = ((d.base + acc.add[i]) * (1.0 + acc.mul[i])).clamp(d.min, d.max);
    }
    v[Stat::MaxHp as usize] = v[Stat::MaxHp as usize].round();
    // 载物：每点护甲让加成区再加一点
    v[Stat::Damage as usize] += v[Stat::Armor as usize] * v[Stat::ArmorToDamage as usize];
    (Stats { v, rules: acc.rules }, acc.effects)
}

/// 某一项属性的来源明细（局内属性面板用），和 [`collect`] 走同一套汇总；加值、乘值都是 0 的不列。
pub fn sources(
    content: &Content,
    setup: &RunSetup,
    build: &Build,
    buff: Option<usize>,
    level: u32,
    stat: Stat,
) -> Vec<StatContribution> {
    let mut found = accumulate(content, setup, build, buff, level, Some(stat)).found;
    found.retain(|c| c.add != 0.0 || c.mul != 0.0);
    found
}

fn accumulate(
    content: &Content,
    setup: &RunSetup,
    build: &Build,
    buff: Option<usize>,
    level: u32,
    trace: Option<Stat>,
) -> Acc {
    let mut acc = Acc {
        add: [0.0; Stat::COUNT],
        mul: [0.0; Stat::COUNT],
        rules: 0,
        effects: Effects::default(),
        trace,
        found: Vec::new(),
    };
    let grown = level.saturating_sub(1) as f32;
    for (s, per) in [
        (Stat::Reveal, content.player.reveal.per_level),
        (Stat::Light, content.player.reveal.light_per_level),
    ] {
        acc.mul[s as usize] += per * grown;
        acc.note(StatSource::Level, s, 0.0, per * grown);
    }
    for (i, node) in content.meta.nodes.iter().enumerate() {
        let lv = setup.meta.get(&node.id).copied().unwrap_or(0).min(node.max_level);
        if lv > 0 {
            acc.apply(&node.per_level, lv as f32, Source::Meta, i, StatSource::Meta(i));
            for (k, step) in node.levels.iter().take(lv as usize).enumerate() {
                acc.apply(step, 1.0, Source::Meta, i * 8 + k, StatSource::Meta(i));
            }
        }
    }
    for (i, a) in content.attributes.list.iter().enumerate() {
        let lv = setup.attributes.get(&a.id).copied().unwrap_or(0).min(a.max_level);
        if lv > 0 {
            acc.apply(&a.per_level, lv as f32, Source::Attribute, i, StatSource::Attribute(i));
        }
    }
    let lamp = setup.lamp_index(content);
    acc.apply(&content.lamps[lamp].effects, 1.0, Source::Lamp, lamp, StatSource::Lamp(lamp));
    for &k in &build.charms {
        acc.apply(&content.charms[k].effects, 1.0, Source::Charm, k, StatSource::Charm(k));
    }
    if let Some(i) = setup.omen.as_ref().and_then(|o| content.omen_index(&o.id)) {
        acc.apply(&content.omens[i].effects, 1.0, Source::Omen, i, StatSource::Omen(i));
    }
    // 难度“更”：第 n 更包含前面各更的规则（difficulty.ron 里每一更写的是相对一更的修正）
    let tier = (setup.tier.max(1) as usize - 1).min(content.difficulty.len() - 1);
    acc.apply(&content.difficulty[tier].effects, 1.0, Source::Difficulty, tier, StatSource::Difficulty(tier));
    for slot in &build.passives {
        let def = &content.passives[slot.def];
        acc.apply(
            &def.per_level,
            slot.level as f32,
            Source::Passive,
            slot.def,
            StatSource::Passive(slot.def),
        );
        for lv in def.levels.iter().take(slot.level as usize) {
            acc.apply(lv, 1.0, Source::Passive, slot.def, StatSource::Passive(slot.def));
        }
    }
    for (e, def) in content.elements.elements.iter().enumerate() {
        let reached = build.tiers[e] as usize;
        for (k, tier) in def.tiers.iter().enumerate().take(reached) {
            // 到了下一阶，被加强版取代的这一阶不再生效
            if tier.superseded && k + 1 < reached {
                continue;
            }
            acc.apply(&tier.effects, 1.0, Source::Tier, e * 8 + k, StatSource::Tier(e, k));
        }
    }
    let no_sheng = acc.rules & Rule::NoSheng.bit() != 0;
    for (i, s) in content.elements.sheng.iter().enumerate() {
        if !no_sheng && build.sheng.get(i).copied().unwrap_or(false) {
            acc.apply(&s.effects, 1.0, Source::Sheng, i, StatSource::Sheng(i));
        }
    }
    if build.taiji {
        acc.apply(&content.elements.taiji.effects, 1.0, Source::Taiji, 0, StatSource::Taiji);
    }
    if let Some(b) = buff {
        acc.apply(&content.events.buffs[b].effects, 1.0, Source::Buff, b, StatSource::Buff(b));
    }
    // 五帝钱这类按共鸣阶数算的效果
    let on = build.tiers.iter().filter(|&&t| t >= 1).count() as f32;
    for &k in &build.charms {
        for e in &content.charms[k].effects {
            if let Effect::ByTiers { stat, on: per_on, off, all } = *e {
                let mut v = per_on * on + off * (5.0 - on);
                if on >= 5.0 {
                    v += all;
                }
                acc.add[stat as usize] += v;
                acc.note(StatSource::Charm(k), stat, v, 0.0);
            }
        }
    }
    acc
}

/// 构筑变化后重算属性。周期触发器保留已经过的时间；生命上限提高时当前生命同时加上差值。
pub(crate) fn refresh_stats(
    content: Res<crate::GameContent>,
    setup: Res<RunSetup>,
    build: Res<Build>,
    progress: Res<crate::run::Progress>,
    encounters: Res<crate::encounters::Encounters>,
    mut dirty: ResMut<StatsDirty>,
    mut stats: ResMut<Stats>,
    mut effects: ResMut<Effects>,
    mut player: Query<&mut Health, With<Player>>,
) {
    if !dirty.0 {
        return;
    }
    dirty.0 = false;
    let collected = collect(&content.0, &setup, &build, encounters.buff.map(|b| b.0), progress.level);
    apply_collected(collected, &mut stats, &mut effects, player.iter_mut());
}

/// 即时刷新和调度刷新共用：保留周期计时，统一应用生命上限变化。
pub(crate) fn apply_collected<'a>(
    (new_stats, mut new_effects): (Stats, Effects),
    stats: &mut Stats,
    effects: &mut Effects,
    player: impl Iterator<Item = Mut<'a, Health>>,
) {
    for t in &mut new_effects.periodic {
        if let Some(old) = effects.periodic.iter().find(|o| o.key == t.key) {
            t.elapsed = old.elapsed;
        }
    }
    let prev_max = stats.max_hp();
    *stats = new_stats;
    *effects = new_effects;
    for mut h in player {
        let max = stats.max_hp();
        if h.hp > 0.0 && max > prev_max {
            h.hp += max - prev_max;
        }
        h.max = max;
        h.hp = h.hp.min(max);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn applying_stats_preserves_trigger_clocks_and_health_invariants() {
        let mut stats = Stats { v: [0.0; Stat::COUNT], rules: 0 };
        stats.v[Stat::MaxHp as usize] = 100.0;
        let trigger = |key, elapsed| ActiveTrigger {
            key,
            chance: 1.0,
            only: Cond::Always,
            action: Action::Heal(1.0),
            period: 10.0,
            elapsed,
        };
        let mut effects = Effects { periodic: vec![trigger(1, 4.0), trigger(2, 8.0)], ..Effects::default() };
        let mut world = World::new();
        let living = world.spawn(Health { hp: 60.0, max: 100.0 }).id();
        let dead = world.spawn(Health { hp: 0.0, max: 100.0 }).id();
        let mut new_stats = stats.clone();
        new_stats.v[Stat::MaxHp as usize] = 150.0;
        let new_effects = Effects { periodic: vec![trigger(1, 0.0), trigger(3, 0.0)], ..Effects::default() };
        apply_collected(
            (new_stats, new_effects),
            &mut stats,
            &mut effects,
            world.query::<&mut Health>().iter_mut(&mut world),
        );
        assert_eq!(
            effects.periodic.iter().map(|t| (t.key, t.elapsed)).collect::<Vec<_>>(),
            [(1, 4.0), (3, 0.0)]
        );
        assert_eq!(*world.get::<Health>(living).unwrap(), Health { hp: 110.0, max: 150.0 });
        assert_eq!(*world.get::<Health>(dead).unwrap(), Health { hp: 0.0, max: 150.0 });
        let mut new_stats = stats.clone();
        new_stats.v[Stat::MaxHp as usize] = 80.0;
        apply_collected(
            (new_stats, Effects::default()),
            &mut stats,
            &mut effects,
            world.query::<&mut Health>().iter_mut(&mut world),
        );
        assert_eq!(*world.get::<Health>(living).unwrap(), Health { hp: 80.0, max: 80.0 });
    }
}
