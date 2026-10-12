//! 属性与触发器的汇总（docs/DESIGN.md 第 6.6 节）。
//!
//! 修正来源：心灯、夜签、心法、五行共鸣、相生、太极、古灯增益。任何来源变化时把 [`StatsDirty`]
//! 置位，下一个刷新点统一重算：属性值写进 [`Stats`]，触发器按时机分组写进 [`Effects`]。

use bevy_ecs::prelude::*;

use lantern_content::{Action, Cond, Content, Effect, Quad, Stat, When};

use crate::build::Build;
use crate::{Health, Player, RunSetup};

/// 主角的全部属性（按 [`Stat`] 编号）。
#[derive(Resource, Clone, Debug, PartialEq)]
pub struct Stats {
    v: [f32; Stat::COUNT],
}

impl Stats {
    /// 只有基础值。
    pub fn base(content: &Content) -> Self {
        let mut v = [0.0; Stat::COUNT];
        for (i, d) in content.stats.iter().enumerate() {
            v[i] = d.base.clamp(d.min, d.max);
        }
        Stats { v }
    }

    pub fn get(&self, s: Stat) -> f32 {
        self.v[s as usize]
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
}

struct Acc {
    add: [f32; Stat::COUNT],
    mul: [f32; Stat::COUNT],
    effects: Effects,
}

impl Acc {
    fn apply(&mut self, list: &[Effect], times: f32, source: Source, index: usize) {
        for (k, e) in list.iter().enumerate() {
            let key = ((source as u32) << 24) | ((index as u32 & 0xffff) << 8) | (k as u32 & 0xff);
            match e {
                Effect::Add(s, v) => self.add[*s as usize] += v * times,
                Effect::Mul(s, v) => self.mul[*s as usize] += v * times,
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
                // 共鸣点数和选项偏向在构筑里处理
                Effect::Points(_) | Effect::Favor => {}
            }
        }
    }
}

/// 汇总全部修正来源。`buff` 是古灯增益在 `events.ron` 里的下标。
pub fn collect(content: &Content, setup: &RunSetup, build: &Build, buff: Option<usize>) -> (Stats, Effects) {
    let mut acc = Acc { add: [0.0; Stat::COUNT], mul: [0.0; Stat::COUNT], effects: Effects::default() };
    for (i, line) in content.meta.lines.iter().enumerate() {
        let lv = setup.meta.get(&line.id).copied().unwrap_or(0).min(content.meta.max_level);
        if lv > 0 {
            acc.apply(&line.per_level, lv as f32, Source::Meta, i);
        }
    }
    if let Some(i) = setup.omen.as_ref().and_then(|o| content.omen_index(&o.id)) {
        acc.apply(&content.omens[i].effects, 1.0, Source::Omen, i);
    }
    for slot in &build.passives {
        let def = &content.passives[slot.def];
        acc.apply(&def.per_level, slot.level as f32, Source::Passive, slot.def);
        for lv in def.levels.iter().take(slot.level as usize) {
            acc.apply(lv, 1.0, Source::Passive, slot.def);
        }
    }
    for (e, def) in content.elements.elements.iter().enumerate() {
        for (k, tier) in def.tiers.iter().enumerate().take(build.tiers[e] as usize) {
            acc.apply(&tier.effects, 1.0, Source::Tier, e * 8 + k);
        }
    }
    for (i, s) in content.elements.sheng.iter().enumerate() {
        if build.sheng.get(i).copied().unwrap_or(false) {
            acc.apply(&s.effects, 1.0, Source::Sheng, i);
        }
    }
    if build.taiji {
        acc.apply(&content.elements.taiji.effects, 1.0, Source::Taiji, 0);
    }
    if let Some(b) = buff {
        acc.apply(&content.events.buffs[b].effects, 1.0, Source::Buff, b);
    }
    let mut v = [0.0; Stat::COUNT];
    for (i, d) in content.stats.iter().enumerate() {
        v[i] = ((d.base + acc.add[i]) * (1.0 + acc.mul[i])).clamp(d.min, d.max);
    }
    v[Stat::MaxHp as usize] = v[Stat::MaxHp as usize].round();
    (Stats { v }, acc.effects)
}

/// 构筑变化后重算属性。周期触发器保留已经过的时间；生命上限提高时当前生命同时加上差值。
pub(crate) fn refresh_stats(
    content: Res<crate::GameContent>,
    setup: Res<RunSetup>,
    build: Res<Build>,
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
    let (new_stats, mut new_effects) = collect(&content.0, &setup, &build, encounters.buff.map(|b| b.0));
    for t in &mut new_effects.periodic {
        if let Some(old) = effects.periodic.iter().find(|o| o.key == t.key) {
            t.elapsed = old.elapsed;
        }
    }
    let prev_max = stats.max_hp();
    *stats = new_stats;
    *effects = new_effects;
    for mut h in &mut player {
        let max = stats.max_hp();
        if max > prev_max {
            h.hp += max - prev_max;
        }
        h.max = max;
        h.hp = h.hp.min(max);
    }
}
