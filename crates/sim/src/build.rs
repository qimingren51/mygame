//! 构筑：心法、五行共鸣、升级选项、宝箱（docs/GAMEPLAY.md 第 5.5、5.6、5.8 节）。

use bevy_ecs::prelude::*;

use lantern_content::{Content, Effect, Element, Stat};
use lantern_core::{Pcg32, StateHasher};

use crate::RunSetup;
use crate::stats::Stats;
use crate::weapons::{Arsenal, Form, WeaponSlot};

/// 一门心法。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PassiveSlot {
    /// `passives.ron` 里的下标
    pub def: usize,
    pub level: u32,
}

/// 心法与五行共鸣。法器在 [`Arsenal`] 里。
#[derive(Resource, Clone, Debug, Default, PartialEq)]
pub struct Build {
    pub passives: Vec<PassiveSlot>,
    /// 各系共鸣点数（按 [`Element::ALL`] 的顺序）
    pub points: [u32; 5],
    /// 各系共鸣阶数 0..=4（4 是极境）
    pub tiers: [u8; 5],
    /// 相生是否点亮（按 `elements.ron` 的顺序）
    pub sheng: Vec<bool>,
    pub taiji: bool,
    /// 夜签选定的五行：开局多得的点数、选项偏向
    pub bonus: Option<(Element, u32)>,
    pub favor: Option<Element>,
    /// 本局正统进化与异化的次数（合璧不重复计数）
    pub evolutions: u32,
    /// 封印：永久移出本局卡池的法器、心法
    pub banished: Vec<Banned>,
    /// 已经开过几次升级（保底用）；前几次升级里出现过的新法器
    pub levelups: u32,
    pub early_new: Vec<usize>,
    /// 挂着的灯坠（`charms.ron` 下标）
    pub charms: Vec<usize>,
    /// 灯的本命五行、悟·五行：这一系的选项更容易出现
    pub lamp_element: Option<Element>,
    pub insight: Option<Element>,
    /// 这一局手上同时有过最多几件法器（成就用）
    pub max_weapons: u32,
}

/// 被封印的一项。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Banned {
    /// `weapons.ron` 下标
    Weapon(usize),
    /// `passives.ron` 下标
    Passive(usize),
    /// 只封印这个合璧，不封印材料
    Fusion(usize),
}

/// 共鸣变化的提示。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Awaken {
    Tier { element: Element, tier: u8 },
    Sheng(u8),
    Taiji,
}

impl Build {
    /// 开局：读出夜签对五行的影响。
    pub fn new(content: &Content, setup: &RunSetup) -> Self {
        let mut b = Build { sheng: vec![false; content.elements.sheng.len()], ..Default::default() };
        b.lamp_element = Some(content.lamps[setup.lamp_index(content)].element);
        b.insight = setup.insight;
        b.charms = setup.charms.iter().filter_map(|id| content.charm_index(id)).collect();
        if let Some(pick) = &setup.omen
            && let Some(i) = content.omen_index(&pick.id)
            && let Some(el) = pick.element
        {
            for e in &content.omens[i].effects {
                match e {
                    Effect::Points(n) => b.bonus = Some((el, *n)),
                    Effect::Favor => b.favor = Some(el),
                    _ => {}
                }
            }
        }
        b
    }

    pub fn passive_level(&self, def: usize) -> u32 {
        self.passives.iter().find(|p| p.def == def).map_or(0, |p| p.level)
    }

    /// 重算共鸣点数、阶数、相生、太极，返回新点亮的项。按投入计点（`elements.ron` 的 points）。
    pub fn compute_resonance(&mut self, content: &Content, arsenal: &Arsenal) -> Vec<Awaken> {
        let el = &content.elements;
        let mut points = [0u32; 5];
        for w in &arsenal.0 {
            let def = &content.weapons[w.def];
            points[def.element.index()] += el.weapon_points(w.level, w.transformed());
            if let Form::Fused(f) = w.form {
                for id in &content.fusions[f].weapons {
                    let other = content.weapon_index(id).expect("已校验的合璧材料");
                    if other != w.def {
                        points[content.weapons[other].element.index()] += el.points.evolved;
                    }
                }
            }
        }
        for p in &self.passives {
            // 无属性心法不计点
            if let Some(e) = content.passives[p.def].element {
                points[e.index()] += el.passive_points(p.level);
            }
        }
        if let Some((el, n)) = self.bonus {
            points[el.index()] += n;
        }
        let th = &content.elements.thresholds;
        let mut out = Vec::new();
        for e in Element::ALL {
            let n = points[e.index()];
            let tier = th.iter().filter(|&&t| n >= t).count() as u8;
            if tier > self.tiers[e.index()] {
                out.push(Awaken::Tier { element: e, tier });
            }
            self.tiers[e.index()] = tier;
        }
        self.points = points;
        self.sheng.resize(content.elements.sheng.len(), false);
        for (i, s) in content.elements.sheng.iter().enumerate() {
            let on = self.tiers[s.from.index()] >= 1 && self.tiers[s.to.index()] >= 1;
            if on && !self.sheng[i] {
                out.push(Awaken::Sheng(i as u8));
            }
            self.sheng[i] = on;
        }
        let taiji = self.tiers.iter().all(|&t| t >= 1);
        if taiji && !self.taiji {
            out.push(Awaken::Taiji);
        }
        self.taiji = taiji;
        out
    }

    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.passives.len() as u32);
        for p in &self.passives {
            h.write_u32(p.def as u32);
            h.write_u32(p.level);
        }
        for &p in &self.points {
            h.write_u32(p);
        }
        h.write_u32(self.evolutions);
        h.write_u32(self.banished.len() as u32);
    }

    /// 封印了哪些东西（法器、心法、合璧）。
    pub fn hash_banished(&self, h: &mut StateHasher) {
        for b in &self.banished {
            let (kind, id) = match b {
                Banned::Weapon(k) => (0, k),
                Banned::Passive(k) => (1, k),
                Banned::Fusion(k) => (2, k),
            };
            h.write_u32(kind);
            h.write_u32(*id as u32);
        }
    }

    fn is_banned(&self, b: Banned) -> bool {
        self.banished.contains(&b)
    }
}

/// 升级或宝箱给出的一项。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Offer {
    /// 进化第 k 件法器
    Evolve(usize),
    /// 与正统互斥的异化
    Mutate(usize),
    /// 合璧：两件材料在法器栏里的位置、`fusions.ron` 下标
    Fuse { a: usize, b: usize, fusion_id: usize },
    /// 第 k 件法器升一级
    WeaponUp(usize),
    /// 新法器（`weapons.ron` 下标）
    NewWeapon(usize),
    /// 第 k 门心法升一级
    PassiveUp(usize),
    /// 新心法（`passives.ron` 下标）
    NewPassive(usize),
    /// 补给：回复生命
    Heal,
    /// 补给：灯油
    Oil,
}

impl Offer {
    /// 选项所属的五行；补给、无属性心法没有。
    pub fn element(self, content: &Content, arsenal: &Arsenal, build: &Build) -> Option<Element> {
        match self {
            Offer::Evolve(k) | Offer::Mutate(k) | Offer::WeaponUp(k) => {
                Some(content.weapons[arsenal.0[k].def].element)
            }
            Offer::Fuse { a, .. } => Some(content.weapons[arsenal.0[a].def].element),
            Offer::NewWeapon(d) => Some(content.weapons[d].element),
            Offer::PassiveUp(k) => content.passives[build.passives[k].def].element,
            Offer::NewPassive(d) => content.passives[d].element,
            Offer::Heal | Offer::Oil => None,
        }
    }

    /// 封印这一项时移出卡池的东西；补给不能封印。
    pub fn banned(self, arsenal: &Arsenal, build: &Build) -> Option<Banned> {
        match self {
            Offer::Evolve(k) | Offer::Mutate(k) | Offer::WeaponUp(k) => {
                Some(Banned::Weapon(arsenal.0[k].def))
            }
            Offer::Fuse { fusion_id, .. } => Some(Banned::Fusion(fusion_id)),
            Offer::NewWeapon(d) => Some(Banned::Weapon(d)),
            Offer::PassiveUp(k) => Some(Banned::Passive(build.passives[k].def)),
            Offer::NewPassive(d) => Some(Banned::Passive(d)),
            Offer::Heal | Offer::Oil => None,
        }
    }

    /// 宝箱只自动应用升级与正统进化；调用方还需排除已有异化分岔的进化。
    pub fn is_upgrade(self) -> bool {
        matches!(self, Offer::Evolve(_) | Offer::WeaponUp(_) | Offer::PassiveUp(_))
    }
}

/// 当前可以出现的全部选项和权重。
pub fn offers(content: &Content, arsenal: &Arsenal, build: &Build, secs: f32) -> Vec<(Offer, f32)> {
    let ch = &content.run.choices;
    let mut out = Vec::new();
    let banned_w = |d: usize| build.is_banned(Banned::Weapon(d));
    let banned_p = |d: usize| build.is_banned(Banned::Passive(d));
    for (k, w) in arsenal.0.iter().enumerate() {
        if w.can_evolve(content, build) && !banned_w(w.def) {
            out.push((Offer::Evolve(k), ch.weight_evolve));
            if w.can_mutate(content, build, arsenal) {
                out.push((Offer::Mutate(k), ch.weight_evolve));
            }
        }
    }
    if content.run.transformations {
        for (f, fusion) in content.fusions.iter().enumerate() {
            let slot = |id: &String| arsenal.0.iter().position(|w| content.weapons[w.def].id == *id);
            if let (Some(a), Some(b)) = (slot(&fusion.weapons[0]), slot(&fusion.weapons[1]))
                && can_fuse(content, arsenal, build, a, b, f)
            {
                out.push((Offer::Fuse { a, b, fusion_id: f }, ch.weight_evolve));
            }
        }
    }
    for (k, w) in arsenal.0.iter().enumerate() {
        if !w.transformed() && (w.level as usize) < content.weapons[w.def].levels.len() && !banned_w(w.def) {
            out.push((Offer::WeaponUp(k), ch.weight_weapon_up));
        }
    }
    if occupied_slots(content, arsenal, build) < weapon_slots(content, build) {
        let weight = if secs < ch.late_after { ch.weight_new_weapon } else { ch.weight_new_weapon_late };
        for d in 0..content.weapons.len() {
            if !arsenal.0.iter().any(|w| w.contains(content, d)) && !banned_w(d) {
                out.push((Offer::NewWeapon(d), weight));
            }
        }
    }
    for (k, p) in build.passives.iter().enumerate() {
        if p.level < content.passives[p.def].max_level && !banned_p(p.def) {
            out.push((Offer::PassiveUp(k), ch.weight_passive_up));
        }
    }
    if (build.passives.len() as u32) < ch.slots {
        for d in 0..content.passives.len() {
            if !build.passives.iter().any(|p| p.def == d) && !banned_p(d) {
                out.push((Offer::NewPassive(d), ch.weight_new_passive));
            }
        }
    }
    // 已到一阶的五行更容易出现，帮助玩家凑共鸣
    for (o, w) in &mut out {
        if matches!(o, Offer::Evolve(_) | Offer::Mutate(_) | Offer::Fuse { .. }) {
            continue;
        }
        let Some(el) = o.element(content, arsenal, build) else { continue };
        if build.tiers[el.index()] >= 1 {
            *w *= ch.owned_element_mult;
        }
        if let Some(f) = build.favor {
            *w *= if el == f { ch.favor_mult } else { ch.unfavor_mult };
        }
        if build.lamp_element == Some(el) {
            *w *= ch.lamp_mult;
        }
        if build.insight == Some(el) {
            *w *= ch.insight_mult;
        }
    }
    if let Some(weights) = &ch.build_rhythm {
        for (offer, weight) in &mut out {
            if let Offer::NewPassive(d) = *offer
                && arsenal.0.iter().any(|w| {
                    !w.transformed()
                        && !build.is_banned(Banned::Weapon(w.def))
                        && content.weapons[w.def]
                            .evolution
                            .as_ref()
                            .is_some_and(|e| content.passive_index(&e.passive) == Some(d))
                })
            {
                *weight *= weights.owned_key_mult;
            }
        }
        normalize_new_offers(content, &mut out, secs);
    }
    out
}

/// 只归一化新牌；已有升级、进化仍保留各自权重。类别没有合法候选时不挪用它的预算。
fn normalize_new_offers(content: &Content, pool: &mut [(Offer, f32)], secs: f32) {
    let ch = &content.run.choices;
    let Some(weights) = &ch.build_rhythm else { return };
    let weapon_budget = if secs < ch.late_after { weights.new_weapon } else { weights.new_weapon_late };
    for (weapon, budget) in [(true, weapon_budget), (false, weights.new_passive)] {
        let in_category = |offer: Offer| {
            if weapon { matches!(offer, Offer::NewWeapon(_)) } else { matches!(offer, Offer::NewPassive(_)) }
        };
        let total: f32 = pool.iter().filter(|(o, _)| in_category(*o)).map(|(_, w)| w).sum();
        if total > 0.0 {
            for (_, weight) in pool.iter_mut().filter(|(o, _)| in_category(*o)) {
                *weight *= budget / total;
            }
        }
    }
}

/// 升级选项与封印补牌按类别抽取；每抽走一张重新分配剩余类别的预算。
/// 否则同一屏的第二、三抽仍会因类别条目增多而稀释已有升级。
pub fn pick_choice_offers(
    content: &Content,
    rng: &mut Pcg32,
    pool: &[(Offer, f32)],
    secs: f32,
    n: usize,
) -> Vec<Offer> {
    if content.run.choices.build_rhythm.is_none() {
        return pick_weighted(rng, pool, n);
    }
    let mut pool = pool.to_vec();
    let mut picks = Vec::with_capacity(n);
    while picks.len() < n && !pool.is_empty() {
        normalize_new_offers(content, &mut pool, secs);
        let Some(offer) = pick_weighted(rng, &pool, 1).first().copied() else { break };
        picks.push(offer);
        pool.retain(|(o, _)| *o != offer);
    }
    picks
}

/// 合璧只接受两件正统进化，且两系投入均达二阶；每次应用时重新验证。
/// 异化与合璧没打开（`run.ron` 的 transformations）时一律不能合璧。
pub fn can_fuse(content: &Content, arsenal: &Arsenal, build: &Build, a: usize, b: usize, f: usize) -> bool {
    let (Some(wa), Some(wb), Some(def)) = (arsenal.0.get(a), arsenal.0.get(b), content.fusions.get(f)) else {
        return false;
    };
    if !content.run.transformations
        || a == b
        || wa.form != Form::Evolved
        || wb.form != Form::Evolved
        || build.is_banned(Banned::Fusion(f))
        || build.is_banned(Banned::Weapon(wa.def))
        || build.is_banned(Banned::Weapon(wb.def))
    {
        return false;
    }
    let da = &content.weapons[wa.def];
    let db = &content.weapons[wb.def];
    let mut actual = build.clone();
    actual.compute_resonance(content, arsenal);
    def.weapons.contains(&da.id)
        && def.weapons.contains(&db.id)
        && content.elements.sheng.iter().any(|s| {
            (s.from == da.element && s.to == db.element) || (s.to == da.element && s.from == db.element)
        })
        && actual.tiers[da.element.index()] >= 2
        && actual.tiers[db.element.index()] >= 2
}

/// 按材料数算的法器件数：合璧算两件。限制法器件数的灯坠（断剑）按这个口径检查。
pub fn material_slots(arsenal: &Arsenal) -> u32 {
    arsenal.0.iter().map(|w| if matches!(w.form, Form::Fused(_)) { 2 } else { 1 }).sum()
}

/// 已占的法器格：合璧通常腾出一格；带着限制法器件数的灯坠（断剑）时，合璧仍占两格。
pub fn occupied_slots(content: &Content, arsenal: &Arsenal, build: &Build) -> u32 {
    if build.charms.iter().any(|&k| content.charms[k].max_weapons.is_some()) {
        material_slots(arsenal)
    } else {
        arsenal.0.len() as u32
    }
}

/// 法器栏的格数（灯坠断剑会减少）。
pub fn weapon_slots(content: &Content, build: &Build) -> u32 {
    let mut n = content.stat(Stat::WeaponSlots).base;
    for &k in &build.charms {
        for e in &content.charms[k].effects {
            if let Effect::Add(Stat::WeaponSlots, v) = e {
                n += v;
            }
        }
    }
    let d = content.stat(Stat::WeaponSlots);
    n.clamp(d.min, d.max).round() as u32
}

/// 按权重不放回地抽 n 个。
pub fn pick_weighted(rng: &mut Pcg32, pool: &[(Offer, f32)], n: usize) -> Vec<Offer> {
    let mut pool = pool.to_vec();
    let mut out = Vec::with_capacity(n);
    while out.len() < n && !pool.is_empty() {
        let total: f32 = pool.iter().map(|(_, w)| w).sum();
        let mut r = rng.next_f32() * total;
        let mut i = 0;
        while i < pool.len() - 1 {
            r -= pool[i].1;
            if r <= 0.0 {
                break;
            }
            i += 1;
        }
        out.push(pool.remove(i).0);
    }
    out
}

/// 升级时抽选项，返回选项和是否“灵光一闪”（多一个选项）。
/// `fresh` 表示这是一次新的升级（不是重抽），保底按新升级的次数计。
pub fn roll_choices(
    content: &Content,
    arsenal: &Arsenal,
    build: &mut Build,
    stats: &Stats,
    secs: f32,
    rng: &mut Pcg32,
    fresh: bool,
) -> (Vec<Offer>, bool) {
    let pool = offers(content, arsenal, build, secs);
    if pool.is_empty() {
        let v = if stats.can_heal() { vec![Offer::Heal, Offer::Oil] } else { vec![Offer::Oil] };
        return (v, false);
    }
    if fresh {
        build.levelups += 1;
    }
    let mut n = stats.get(Stat::Choices).round().max(1.0) as usize;
    let mut inspired = false;
    if n >= 3 && rng.chance(stats.get(Stat::Inspiration)) {
        n += 1;
        inspired = true;
    }
    let mut picks = pick_choice_offers(content, rng, &pool, secs, n);
    let pity = &content.run.choices.pity;
    let keys: Vec<_> = arsenal
        .0
        .iter()
        .filter_map(|w| {
            if w.transformed() || build.is_banned(Banned::Weapon(w.def)) || w.level < pity.key_level {
                return None;
            }
            let evo = content.weapons[w.def].evolution.as_ref()?;
            let pd = content.passive_index(&evo.passive)?;
            let offer = Offer::NewPassive(pd);
            (build.passive_level(pd) == 0 && pool.iter().any(|(o, _)| *o == offer))
                .then_some((offer, w.is_max_level(content)))
        })
        .collect();
    // 先保护已抽中的合法钥匙，再处理任何补牌；否则靠后的法器钥匙会被前者挤掉。
    let mut pinned: Vec<Offer> =
        picks.iter().copied().filter(|offer| keys.iter().any(|(key, _)| key == offer)).collect();
    let early = build.levelups <= pity.early_levels;
    if early && content.run.choices.build_rhythm.is_some() {
        let upgrades: Vec<_> =
            pool.iter().copied().filter(|(o, _)| matches!(o, Offer::WeaponUp(_))).collect();
        let shown = picks.iter().copied().find(|o| matches!(o, Offer::WeaponUp(_)));
        if let Some(offer) = shown.or_else(|| pick_weighted(rng, &upgrades, 1).first().copied()) {
            pin_choice(&mut picks, offer, &mut pinned);
        }
    }
    if early {
        // 到剩余次数恰好够用时保留新法器；之前自然抽到的仍由最终展示结果计数。
        let have = build.early_new.len() as u32;
        let left = pity.early_levels - build.levelups + 1;
        let fresh_new = |o: &Offer| matches!(o, Offer::NewWeapon(d) if !build.early_new.contains(d));
        if have < pity.early_new_weapons && pity.early_new_weapons - have >= left {
            let shown = picks.iter().copied().find(fresh_new);
            let cands: Vec<_> = pool.iter().copied().filter(|(o, _)| fresh_new(o)).collect();
            if let Some(offer) = shown.or_else(|| pick_weighted(rng, &cands, 1).first().copied()) {
                pin_choice(&mut picks, offer, &mut pinned);
            }
        }
    }
    // 最后一格心法用掉之前，至少给一次当前法器的配对选择；封印/满栏仍以合法池为准。
    if content.run.choices.build_rhythm.is_some()
        && build.passives.len() as u32 + 1 == content.run.choices.slots
    {
        let key = arsenal
            .0
            .iter()
            .enumerate()
            .filter_map(|(k, w)| {
                if w.transformed() || build.is_banned(Banned::Weapon(w.def)) {
                    return None;
                }
                let evo = content.weapons[w.def].evolution.as_ref()?;
                let offer = Offer::NewPassive(content.passive_index(&evo.passive)?);
                pool.iter().any(|(o, _)| *o == offer).then_some((w.level, std::cmp::Reverse(k), offer))
            })
            .max_by_key(|(level, order, _)| (*level, *order));
        if let Some((_, _, offer)) = key {
            pin_choice(&mut picks, offer, &mut pinned);
        }
    }
    // 保底二：法器练到 key_level 以上却缺进化心法时，按概率把那门心法放进选项；
    // key_guarantee_after 秒以后满级仍缺心法时必放（不再掷骰）
    for (offer, max_level) in keys {
        if !picks.contains(&offer)
            && ((secs >= pity.key_guarantee_after && max_level) || rng.chance(pity.key_chance))
        {
            pin_choice(&mut picks, offer, &mut pinned);
        }
    }
    if content.run.transformations {
        picks = arrange_forms(&pool, picks, &pinned, n);
    }
    // 后续保底和质变排卡可能换掉自然抽中的牌；只有最终出现在这一屏上的才算“见过”。
    record_shown_weapons(content, build, &picks);
    (picks, inspired)
}

pub(crate) fn record_shown_weapons(content: &Content, build: &mut Build, choices: &[Offer]) {
    if build.levelups <= content.run.choices.pity.early_levels {
        for offer in choices {
            if let Offer::NewWeapon(d) = *offer
                && !build.early_new.contains(&d)
            {
                build.early_new.push(d);
            }
        }
    }
}

/// 质变卡保底（异化与合璧打开时）：合璧每次必展示；有分岔时正统与异化成对展示，优先最先持有的一件；
/// 没有分岔时保一张正统进化。保底的新法器、心法钥匙（pinned）也一定留住，卡多了就多展示几张。
fn arrange_forms(pool: &[(Offer, f32)], picks: Vec<Offer>, pinned: &[Offer], n: usize) -> Vec<Offer> {
    let mut keep: Vec<Offer> =
        pool.iter().filter_map(|(o, _)| matches!(o, Offer::Fuse { .. }).then_some(*o)).collect();
    let branch = pool.iter().find_map(|(o, _)| if let Offer::Mutate(k) = o { Some(*k) } else { None });
    if let Some(k) = branch {
        keep.extend([Offer::Evolve(k), Offer::Mutate(k)]);
    } else if let Some((o, _)) = pool.iter().find(|(o, _)| matches!(o, Offer::Evolve(_))) {
        keep.push(*o);
    }
    if keep.is_empty() {
        return picks;
    }
    let pity: Vec<Offer> =
        picks.iter().copied().filter(|o| pinned.contains(o) && !keep.contains(o)).collect();
    // 同一屏只展示一个完整分岔，避免另一件的异化单独挤掉其正统牌
    let other_branch = |o: &Offer| {
        matches!(o, Offer::Evolve(k) | Offer::Mutate(k)
            if Some(*k) != branch && pool.iter().any(|(p, _)| *p == Offer::Mutate(*k)))
    };
    let rest: Vec<Offer> = picks
        .iter()
        .copied()
        .filter(|o| !pinned.contains(o) && !keep.contains(o) && !other_branch(o))
        .collect();
    let wanted = n.max(keep.len() + pity.len());
    keep.extend(pity);
    keep.extend(rest);
    keep.truncate(wanted);
    keep
}

/// 保底项已有时直接保护；补入时只替换未保护项，不能挤掉自然抽中的另一项保底。
fn pin_choice(picks: &mut Vec<Offer>, offer: Offer, pinned: &mut Vec<Offer>) {
    if !picks.contains(&offer) {
        if let Some(slot) = picks.iter_mut().rev().find(|o| !pinned.contains(o)) {
            *slot = offer;
        } else {
            picks.push(offer);
        }
    }
    if !pinned.contains(&offer) {
        pinned.push(offer);
    }
}

/// 应用一个选项。返回需要演出的进化（法器在 [`Arsenal`] 里的位置）。
/// 回复生命和灯油由调用方处理（需要主角的生命和本局的结算）。
pub fn apply_offer(
    content: &Content,
    arsenal: &mut Arsenal,
    build: &mut Build,
    offer: Offer,
) -> Option<usize> {
    match offer {
        Offer::Evolve(k) => {
            let w = &mut arsenal.0[k];
            if w.form == Form::Base {
                w.form = Form::Evolved;
                build.evolutions += 1;
                return Some(k);
            }
        }
        Offer::Mutate(k) => {
            let w = arsenal.0.get(k)?;
            if !build.is_banned(Banned::Weapon(w.def)) && w.can_mutate(content, build, arsenal) {
                arsenal.0[k].form = Form::Mutated;
                build.evolutions += 1;
                return Some(k);
            }
        }
        Offer::Fuse { a, b, fusion_id } => {
            if can_fuse(content, arsenal, build, a, b, fusion_id) {
                let primary = content.weapon_index(&content.fusions[fusion_id].weapons[0]).expect("合璧材料");
                let mut w = WeaponSlot::new(primary);
                w.level = content.weapons[primary].levels.len() as u32;
                w.form = Form::Fused(fusion_id);
                let k = a.min(b);
                arsenal.0.remove(a.max(b));
                arsenal.0[k] = w;
                return Some(k);
            }
        }
        Offer::WeaponUp(k) => {
            let w = &mut arsenal.0[k];
            if !w.transformed() {
                w.level = (w.level + 1).min(content.weapons[w.def].levels.len() as u32);
            }
        }
        Offer::NewWeapon(d) => {
            if occupied_slots(content, arsenal, build) < weapon_slots(content, build)
                && !arsenal.0.iter().any(|w| w.contains(content, d))
            {
                arsenal.0.push(WeaponSlot::new(d));
                build.max_weapons = build.max_weapons.max(arsenal.0.len() as u32);
            }
        }
        Offer::PassiveUp(k) => {
            let p = &mut build.passives[k];
            p.level = (p.level + 1).min(content.passives[p.def].max_level);
        }
        Offer::NewPassive(d) => {
            if !build.passives.iter().any(|p| p.def == d) {
                build.passives.push(PassiveSlot { def: d, level: 1 });
            }
        }
        Offer::Heal | Offer::Oil => {}
    }
    None
}
