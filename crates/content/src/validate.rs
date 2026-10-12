//! 加载后的整体校验：数值范围、ID 唯一、引用存在。

use std::collections::BTreeSet;
use std::path::Path;

use crate::{Action, Content, ContentError, Effect, Element, Rank, WeaponBehavior, When};

struct Checker<'a> {
    dir: &'a Path,
}

type Res = Result<(), ContentError>;

impl Checker<'_> {
    fn fail(&self, file: &str, msg: String) -> Res {
        Err(ContentError::Invalid { file: self.dir.join(file), msg })
    }

    fn positive(&self, file: &str, fields: &[(&str, f32)]) -> Res {
        for &(field, v) in fields {
            if !(v.is_finite() && v > 0.0) {
                return self.fail(file, format!("{field} 必须是正数，现在是 {v}"));
            }
        }
        Ok(())
    }

    fn non_negative(&self, file: &str, fields: &[(&str, f32)]) -> Res {
        for &(field, v) in fields {
            if !(v.is_finite() && v >= 0.0) {
                return self.fail(file, format!("{field} 不能为负数，现在是 {v}"));
            }
        }
        Ok(())
    }

    fn fraction(&self, file: &str, field: &str, v: f32) -> Res {
        if !(v.is_finite() && (0.0..=1.0).contains(&v)) {
            return self.fail(file, format!("{field} 必须在 0 到 1 之间，现在是 {v}"));
        }
        Ok(())
    }

    fn range(&self, file: &str, field: &str, (lo, hi): (f32, f32)) -> Res {
        if !(lo.is_finite() && hi.is_finite() && lo <= hi) {
            return self.fail(file, format!("{field} 的范围不对：({lo}, {hi})"));
        }
        Ok(())
    }

    fn color(&self, file: &str, owner: &str, v: &str) -> Res {
        let hex = v.strip_prefix('#').unwrap_or("");
        if hex.len() != 6 || u32::from_str_radix(hex, 16).is_err() {
            return self.fail(file, format!("\"{owner}\" 的颜色要写成 #RRGGBB，现在是 \"{v}\""));
        }
        Ok(())
    }

    fn unique<'s>(&self, file: &str, what: &str, ids: impl Iterator<Item = &'s str>) -> Res {
        let mut seen = BTreeSet::new();
        for id in ids {
            if !seen.insert(id) {
                return self.fail(file, format!("{what} ID \"{id}\" 重复"));
            }
        }
        Ok(())
    }

    /// 效果列表。`element_context` 为 true 时允许作用于选定五行的效果（只有夜签有）。
    fn effects(&self, file: &str, owner: &str, list: &[Effect], element_context: bool) -> Res {
        for e in list {
            match e {
                Effect::Add(_, v) | Effect::Mul(_, v) => {
                    if !v.is_finite() {
                        return self.fail(file, format!("\"{owner}\" 的属性修正不是有限数"));
                    }
                }
                Effect::Trigger { on, chance, action, .. } => {
                    if !(*chance > 0.0 && *chance <= 1.0) {
                        return self.fail(file, format!("\"{owner}\" 的触发概率必须在 (0, 1] 之间"));
                    }
                    if let When::Periodic(p) = on {
                        self.positive(file, &[("Periodic", *p)])?;
                    }
                    self.action(file, action)?;
                }
                Effect::Shield { amount } => {
                    if amount.at(0.0) <= 0.0 {
                        return self.fail(file, format!("\"{owner}\" 的护盾值必须是正数"));
                    }
                }
                Effect::Points(_) | Effect::Favor => {
                    if !element_context {
                        return self.fail(
                            file,
                            format!("\"{owner}\"：Points 和 Favor 只能用在 pick_element 的夜签里"),
                        );
                    }
                }
            }
        }
        Ok(())
    }

    fn action(&self, file: &str, action: &Action) -> Res {
        match action {
            Action::Burn { duration, ratio } => {
                self.positive(file, &[("Burn.duration", *duration), ("Burn.ratio", *ratio)])
            }
            Action::Slow { amount, duration } => {
                self.fraction(file, "Slow.amount", *amount)?;
                self.positive(file, &[("Slow.duration", *duration)])
            }
            Action::Freeze { duration } => self.positive(file, &[("Freeze.duration", *duration)]),
            Action::BonusSword { pierce, speed, life, hit_radius, .. } => {
                if *pierce == 0 {
                    return self.fail(file, "BonusSword.pierce 至少为 1".into());
                }
                self.positive(
                    file,
                    &[
                        ("BonusSword.speed", *speed),
                        ("BonusSword.life", *life),
                        ("BonusSword.hit_radius", *hit_radius),
                    ],
                )
            }
            Action::Heal(v) => self.positive(file, &[("Heal", *v)]),
            Action::Explode { radius, .. } => self.positive(file, &[("Explode.radius", *radius)]),
            Action::Quake { radius, knockback, stun, .. } => {
                self.positive(file, &[("Quake.radius", *radius)])?;
                self.non_negative(file, &[("Quake.knockback", *knockback), ("Quake.stun", *stun)])
            }
            Action::ScreenDamage { boss_cap, .. } => {
                self.non_negative(file, &[("ScreenDamage.boss_cap", *boss_cap)])
            }
            Action::DropChest { distance } => self.non_negative(file, &[("DropChest.distance", *distance)]),
        }
    }

    fn behavior(&self, file: &str, id: &str, b: &WeaponBehavior) -> Res {
        match b {
            WeaponBehavior::Orbit { hit_cooldown, size, .. } => {
                self.positive(file, &[("Orbit.hit_cooldown", *hit_cooldown), ("Orbit.size", *size)])
            }
            WeaponBehavior::Volley { range, speed, life, hit_radius, retry, .. } => self.positive(
                file,
                &[
                    ("Volley.range", *range),
                    ("Volley.speed", *speed),
                    ("Volley.life", *life),
                    ("Volley.hit_radius", *hit_radius),
                    ("Volley.retry", *retry),
                ],
            ),
            WeaponBehavior::Pulse { slow, slow_time, toll, .. } => {
                self.fraction(file, "Pulse.slow", *slow)?;
                self.non_negative(file, &[("Pulse.slow_time", *slow_time)])?;
                if let Some(t) = toll {
                    self.positive(file, &[("toll.period", t.period), ("toll.damage", t.damage)])?;
                }
                Ok(())
            }
            WeaponBehavior::Seeker { range, pick, rest, steer, .. } => {
                if *pick == 0 {
                    return self.fail(file, format!("\"{id}\"：Seeker.pick 至少为 1"));
                }
                self.positive(file, &[("Seeker.range", *range), ("Seeker.steer", *steer)])?;
                self.non_negative(file, &[("Seeker.rest", *rest)])
            }
            WeaponBehavior::Drop { range, candidates, delay, stagger, amount_div, fissure, .. } => {
                if *candidates == 0 || *amount_div == 0 {
                    return self.fail(file, format!("\"{id}\"：Drop.candidates 和 amount_div 至少为 1"));
                }
                self.positive(file, &[("Drop.range", *range)])?;
                self.non_negative(file, &[("Drop.delay", *delay), ("Drop.stagger", *stagger)])?;
                if let Some(f) = fissure {
                    self.positive(file, &[("fissure.life", f.life), ("fissure.tick", f.tick)])?;
                    self.fraction(file, "fissure.slow", f.slow)?;
                }
                Ok(())
            }
        }
    }
}

impl Content {
    pub(crate) fn validate(&self, dir: &Path) -> Res {
        let c = Checker { dir };
        let enemy_ref = |file: &str, field: &str, id: &str| -> Res {
            if self.enemy_index(id).is_none() {
                return c.fail(file, format!("{field} 引用了不存在的妖物 \"{id}\""));
            }
            Ok(())
        };

        // ---- player.ron ----
        let p = &self.player;
        c.positive(
            "player.ron",
            &[
                ("radius", p.radius),
                ("dash.duration", p.dash.duration),
                ("dash.speed", p.dash.speed),
                ("ult.charge_normal", p.ult.charge_normal),
                ("ult.charge_elite", p.ult.charge_elite),
            ],
        )?;
        c.non_negative(
            "player.ron",
            &[
                ("hurt_iframe", p.hurt_iframe),
                ("dash.cooldown", p.dash.cooldown),
                ("dash.iframe", p.dash.iframe),
                ("ult.knockback", p.ult.knockback),
                ("ult.boss_fraction", p.ult.boss_fraction),
            ],
        )?;
        if self.weapon_index(&p.start_weapon).is_none() {
            return c.fail("player.ron", format!("start_weapon 引用了不存在的法器 \"{}\"", p.start_weapon));
        }

        // ---- stats.ron ----
        for (s, d) in crate::Stat::ALL.iter().zip(&self.stats) {
            if !d.base.is_finite() || d.min > d.max {
                return c.fail("stats.ron", format!("{s:?} 的基础值或上下限不对"));
            }
        }

        // ---- run.ron ----
        let r = &self.run;
        c.positive("run.ron", &[("duration", r.duration), ("view_height", r.view_height)])?;
        if r.max_aspect < 1.0 {
            return c.fail("run.ron", "max_aspect 不能小于 1".into());
        }
        let s = &r.spawn;
        c.non_negative("run.ron", &[("spawn.ring_extra", s.ring_extra), ("spawn.relocate", s.relocate)])?;
        c.range("run.ron", "spawn.speed_jitter", s.speed_jitter)?;
        enemy_ref("run.ron", "spawn.base", &s.base)?;
        for m in &s.mix {
            enemy_ref("run.ron", "spawn.mix", &m.enemy)?;
            c.range("run.ron", "spawn.mix.share", m.share)?;
        }
        c.range("run.ron", "spawn.packs.interval", s.packs.interval)?;
        for m in &s.packs.mix {
            enemy_ref("run.ron", "spawn.packs.mix", &m.enemy)?;
            if !s.mix.iter().any(|x| x.enemy == m.enemy) {
                return c.fail(
                    "run.ron",
                    format!("spawn.packs.mix 里的 \"{}\" 必须也出现在 spawn.mix 里", m.enemy),
                );
            }
        }
        let mut last = f32::NEG_INFINITY;
        for step in &r.schedule {
            c.range("run.ron", "schedule.at", step.at)?;
            if step.at.0 < last {
                return c.fail("run.ron", "schedule 要按时间排列".into());
            }
            last = step.at.0;
            let pool: &[String] = match &step.event {
                crate::PlanEvent::Elite(pool) => pool,
                crate::PlanEvent::Surge { duration, rate_mult, elites } => {
                    c.positive("run.ron", &[("Surge.duration", *duration), ("Surge.rate_mult", *rate_mult)])?;
                    elites
                }
                crate::PlanEvent::Boss { enemy, spawn_mult } => {
                    c.non_negative("run.ron", &[("Boss.spawn_mult", *spawn_mult)])?;
                    std::slice::from_ref(enemy)
                }
            };
            if pool.is_empty() {
                return c.fail("run.ron", "schedule 里的妖物列表不能为空".into());
            }
            for id in pool {
                enemy_ref("run.ron", "schedule", id)?;
            }
        }
        c.non_negative("run.ron", &[("win_delay", r.win_delay)])?;
        let g = &r.gems;
        c.positive("run.ron", &[("gems.accel", g.accel), ("gems.max_speed", g.max_speed)])?;
        if g.cap == 0 || g.elite_split == 0 {
            return c.fail("run.ron", "gems.cap 和 gems.elite_split 至少为 1".into());
        }
        let d = &r.drops;
        c.non_negative("run.ron", &[("drops.reach", d.reach)])?;
        c.fraction("run.ron", "drops.bell_chance", d.bell_chance)?;
        c.fraction("run.ron", "drops.lotus_chance", d.lotus_chance)?;
        c.fraction("run.ron", "drops.lotus_heal", d.lotus_heal)?;
        let ch = &r.choices;
        if ch.slots == 0 {
            return c.fail("run.ron", "choices.slots 至少为 1".into());
        }
        c.positive(
            "run.ron",
            &[
                ("choices.weight_evolve", ch.weight_evolve),
                ("choices.weight_weapon_up", ch.weight_weapon_up),
                ("choices.weight_new_weapon", ch.weight_new_weapon),
                ("choices.weight_new_weapon_late", ch.weight_new_weapon_late),
                ("choices.weight_passive_up", ch.weight_passive_up),
                ("choices.weight_new_passive", ch.weight_new_passive),
                ("choices.owned_element_mult", ch.owned_element_mult),
                ("choices.favor_mult", ch.favor_mult),
                ("choices.unfavor_mult", ch.unfavor_mult),
            ],
        )?;
        c.fraction("run.ron", "choices.inspiration", ch.inspiration)?;
        c.fraction("run.ron", "choices.heal", ch.heal)?;
        if ch.chest_odds.windows(2).any(|w| w[0].0 < w[1].0) {
            return c.fail("run.ron", "choices.chest_odds 要按阈值从高到低排列".into());
        }
        c.positive("run.ron", &[("combo.window", r.combo.window)])?;
        c.non_negative(
            "run.ron",
            &[
                ("oil.per_second", r.oil.per_second),
                ("oil.per_kill", r.oil.per_kill),
                ("oil.max_seconds", r.oil.max_seconds),
            ],
        )?;
        enemy_ref("run.ron", "bench.enemy", &r.bench.enemy)?;
        enemy_ref("run.ron", "bench.alt_enemy", &r.bench.alt_enemy)?;

        // ---- enemies.ron ----
        c.unique("enemies.ron", "妖物", self.enemies.iter().map(|e| e.id.as_str()))?;
        for e in &self.enemies {
            c.positive("enemies.ron", &[("radius", e.radius), ("hp", e.hp)])?;
            c.non_negative("enemies.ron", &[("speed", e.speed), ("damage", e.damage), ("xp", e.xp)])?;
            c.color("enemies.ron", &e.id, &e.eye)?;
            if let Some(b) = &e.boss {
                c.positive(
                    "enemies.ron",
                    &[
                        ("boss.volley_every", b.volley_every),
                        ("boss.summon_every", b.summon_every),
                        ("boss.shot_speed", b.shot_speed),
                        ("boss.shot_life", b.shot_life),
                    ],
                )?;
                enemy_ref("enemies.ron", "boss.summon", &b.summon)?;
            }
            if let Some(l) = &e.loot {
                if l.gems == 0 {
                    return c.fail("enemies.ron", format!("\"{}\" 的 loot.gems 至少为 1", e.id));
                }
                c.range("enemies.ron", "loot.scatter", l.scatter)?;
            }
        }

        // ---- weapons.ron ----
        c.unique("weapons.ron", "法器", self.weapons.iter().map(|w| w.id.as_str()))?;
        for w in &self.weapons {
            if w.levels.is_empty() {
                return c.fail("weapons.ron", format!("法器 \"{}\" 没有等级数据", w.id));
            }
            c.behavior("weapons.ron", &w.id, &w.behavior)?;
            let mut all: Vec<_> = w.levels.iter().collect();
            if let Some(evo) = &w.evolution {
                c.behavior("weapons.ron", &w.id, &evo.behavior)?;
                if std::mem::discriminant(&evo.behavior) != std::mem::discriminant(&w.behavior) {
                    return c.fail("weapons.ron", format!("\"{}\" 进化后的行为必须和进化前是同一种", w.id));
                }
                if self.passive_index(&evo.passive).is_none() {
                    return c.fail(
                        "weapons.ron",
                        format!("\"{}\" 的进化引用了不存在的心法 \"{}\"", w.id, evo.passive),
                    );
                }
                all.push(&evo.level);
            }
            for (i, lv) in all.into_iter().enumerate() {
                let needs_count = !matches!(w.behavior, WeaponBehavior::Pulse { .. });
                let needs_cd =
                    !matches!(w.behavior, WeaponBehavior::Orbit { .. } | WeaponBehavior::Seeker { .. });
                let needs_radius = matches!(
                    w.behavior,
                    WeaponBehavior::Orbit { .. } | WeaponBehavior::Pulse { .. } | WeaponBehavior::Drop { .. }
                );
                let needs_pierce = matches!(w.behavior, WeaponBehavior::Volley { .. });
                if lv.damage <= 0.0
                    || (needs_count && lv.count == 0)
                    || (needs_cd && lv.cooldown <= 0.0)
                    || (needs_radius && lv.radius <= 0.0)
                    || (needs_pierce && lv.pierce == 0)
                {
                    return c.fail(
                        "weapons.ron",
                        format!("\"{}\" 第 {} 组数值缺少这种行为需要的字段（或不是正数）", w.id, i + 1),
                    );
                }
            }
        }

        // ---- passives.ron ----
        c.unique("passives.ron", "心法", self.passives.iter().map(|p| p.id.as_str()))?;
        for p in &self.passives {
            if p.max_level == 0 {
                return c.fail("passives.ron", format!("心法 \"{}\" 的 max_level 至少为 1", p.id));
            }
            if p.per_level.is_empty() == p.levels.is_empty() {
                return c.fail("passives.ron", format!("心法 \"{}\" 要写 per_level 或 levels 之一", p.id));
            }
            if !p.levels.is_empty() && p.levels.len() != p.max_level as usize {
                return c.fail("passives.ron", format!("心法 \"{}\" 的 levels 要有 max_level 项", p.id));
            }
            c.effects("passives.ron", &p.id, &p.per_level, false)?;
            for lv in &p.levels {
                c.effects("passives.ron", &p.id, lv, false)?;
            }
        }

        // ---- elements.ron ----
        let el = &self.elements;
        if el.thresholds.len() != 3 || el.thresholds.windows(2).any(|w| w[0] >= w[1]) || el.thresholds[0] == 0
        {
            return c.fail("elements.ron", "thresholds 要写 3 个从小到大的正整数".into());
        }
        if el.elements.len() != Element::ALL.len()
            || el.elements.iter().zip(Element::ALL).any(|(d, e)| d.id != e)
        {
            return c.fail("elements.ron", "elements 要按 Metal、Wood、Water、Fire、Earth 的顺序写全".into());
        }
        for e in &el.elements {
            c.color("elements.ron", &e.name, &e.color)?;
            if e.tiers.len() != 3 {
                return c.fail("elements.ron", format!("\"{}\" 要写 3 阶共鸣", e.name));
            }
            for t in &e.tiers {
                c.effects("elements.ron", &e.name, &t.effects, false)?;
            }
        }
        for s in &el.sheng {
            if s.from == s.to {
                return c.fail("elements.ron", format!("相生 \"{}\" 的两系不能相同", s.name));
            }
            c.effects("elements.ron", &s.name, &s.effects, false)?;
        }
        c.effects("elements.ron", &el.taiji.name, &el.taiji.effects, false)?;

        // ---- omens.ron ----
        c.unique("omens.ron", "夜签", self.omens.iter().map(|o| o.id.as_str()))?;
        if self.omens.len() < 3 {
            return c.fail("omens.ron", "夜签至少要有 3 张（开局三选一）".into());
        }
        for o in &self.omens {
            c.effects("omens.ron", &o.id, &o.effects, o.pick_element)?;
        }

        // ---- events.ron ----
        let ev = &self.events;
        c.range("events.ron", "first", ev.first)?;
        c.range("events.ron", "interval", ev.interval)?;
        if ev.interval.0 <= 0.0 {
            return c.fail("events.ron", "interval 必须是正数".into());
        }
        c.unique("events.ron", "奇遇", ev.kinds.iter().map(|k| k.id.as_str()))?;
        if ev.kinds.is_empty() || ev.buffs.is_empty() {
            return c.fail("events.ron", "kinds 和 buffs 不能为空".into());
        }
        for k in &ev.kinds {
            c.color("events.ron", &k.id, &k.color)?;
            c.positive("events.ron", &[("weight", k.weight), ("life", k.life)])?;
            match &k.kind {
                crate::EventKind::Critter { enemy } => {
                    enemy_ref("events.ron", "Critter.enemy", enemy)?;
                    let e = &self.enemies[self.enemy_index(enemy).unwrap_or(0)];
                    if e.rank != Rank::Critter || e.loot.is_none() {
                        return c.fail(
                            "events.ron",
                            format!("Critter 的妖物 \"{enemy}\" 必须是 rank: Critter 并写好 loot"),
                        );
                    }
                }
                crate::EventKind::Spring { radius, heal } => {
                    c.positive("events.ron", &[("Spring.radius", *radius), ("Spring.heal", *heal)])?
                }
                crate::EventKind::Shrine { radius, duration } => {
                    c.positive("events.ron", &[("Shrine.radius", *radius), ("Shrine.duration", *duration)])?
                }
                crate::EventKind::Altar { radius, cost, .. } => {
                    c.positive("events.ron", &[("Altar.radius", *radius)])?;
                    c.fraction("events.ron", "Altar.cost", *cost)?;
                }
                crate::EventKind::Rift { base, alt, guards, late_guards, spread, alt_share, .. } => {
                    c.range("events.ron", "Rift.spread", *spread)?;
                    c.fraction("events.ron", "Rift.alt_share", *alt_share)?;
                    if guards.is_empty() {
                        return c.fail("events.ron", "Rift.guards 不能为空".into());
                    }
                    for id in [base, alt].into_iter().chain(guards).chain(late_guards) {
                        enemy_ref("events.ron", "Rift", id)?;
                    }
                }
            }
        }
        c.unique("events.ron", "增益", ev.buffs.iter().map(|b| b.id.as_str()))?;
        for b in &ev.buffs {
            c.color("events.ron", &b.id, &b.color)?;
            c.effects("events.ron", &b.id, &b.effects, false)?;
        }

        // ---- meta.ron ----
        let m = &self.meta;
        if m.max_level == 0 || m.lines.is_empty() {
            return c.fail("meta.ron", "max_level 至少为 1，lines 不能为空".into());
        }
        c.positive("meta.ron", &[("cost_base", m.cost_base), ("cost_round", m.cost_round)])?;
        c.unique("meta.ron", "心灯", m.lines.iter().map(|l| l.id.as_str()))?;
        for l in &m.lines {
            c.effects("meta.ron", &l.id, &l.per_level, false)?;
        }
        Ok(())
    }
}
