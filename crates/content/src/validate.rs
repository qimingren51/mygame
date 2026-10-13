//! 加载后的整体校验：数值范围、ID 唯一、引用存在。

use std::collections::BTreeSet;
use std::path::Path;

use crate::{
    Action, Content, ContentError, Effect, Element, Rank, ReactionEffect, Stat, WeaponBehavior, When,
};

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
            if let Effect::Mul(Stat::Damage, _) = e {
                return self
                    .fail(file, format!("\"{owner}\"：伤害加成要写成 Add(Damage, …)，加成区是相加的"));
            }
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
                Effect::Rule(_) => {}
                Effect::ByTiers { on, off, all, .. } => {
                    if !(on.is_finite() && off.is_finite() && all.is_finite()) {
                        return self.fail(file, format!("\"{owner}\" 的 ByTiers 不是有限数"));
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
            Action::Explode { radius, freeze, ignite, .. } => {
                self.positive(file, &[("Explode.radius", *radius)])?;
                self.non_negative(file, &[("Explode.freeze", *freeze), ("Explode.ignite", *ignite)])
            }
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

    fn reaction(&self, file: &str, id: &str, e: &ReactionEffect) -> Res {
        let f = file;
        match *e {
            ReactionEffect::Spread { count, radius, mult, duration, burn_ratio } => {
                if count == 0 {
                    return self.fail(f, format!("反应 \"{id}\"：Spread.count 至少为 1"));
                }
                self.positive(
                    f,
                    &[("radius", radius), ("mult", mult), ("duration", duration), ("burn_ratio", burn_ratio)],
                )
            }
            ReactionEffect::Zone { radius, duration, dps_ratio, slow, knock_mult, .. } => {
                self.positive(f, &[("radius", radius), ("duration", duration), ("knock_mult", knock_mult)])?;
                self.non_negative(f, &[("dps_ratio", dps_ratio)])?;
                self.fraction(f, "slow", slow)
            }
            ReactionEffect::Blades { count, ratio, pierce, speed, life, hit_radius } => {
                if count == 0 || pierce == 0 {
                    return self.fail(f, format!("反应 \"{id}\"：Blades.count、pierce 至少为 1"));
                }
                self.positive(
                    f,
                    &[("ratio", ratio), ("speed", speed), ("life", life), ("hit_radius", hit_radius)],
                )
            }
            ReactionEffect::Frost { freeze, radius, slow, slow_time } => {
                self.positive(f, &[("freeze", freeze), ("radius", radius), ("slow_time", slow_time)])?;
                self.fraction(f, "slow", slow)
            }
            ReactionEffect::Bloom { radius, root, herb_life, heal, heal_per_second } => self.positive(
                f,
                &[
                    ("radius", radius),
                    ("root", root),
                    ("herb_life", herb_life),
                    ("heal", heal),
                    ("heal_per_second", heal_per_second),
                ],
            ),
            ReactionEffect::Steam { radius, ratio, per_level, confuse } => {
                self.positive(f, &[("radius", radius), ("ratio", ratio), ("confuse", confuse)])?;
                self.non_negative(f, &[("per_level", per_level)])
            }
            ReactionEffect::Melt { vuln, duration } => {
                self.positive(f, &[("vuln", vuln), ("duration", duration)])
            }
            ReactionEffect::Sever { ratio, execute } => {
                self.positive(f, &[("ratio", ratio)])?;
                self.fraction(f, "execute", execute)
            }
            ReactionEffect::Rupture { radius, stun, ratio } => {
                self.positive(f, &[("radius", radius), ("stun", stun), ("ratio", ratio)])
            }
        }
    }

    fn behavior(&self, file: &str, id: &str, b: &WeaponBehavior) -> Res {
        match b {
            WeaponBehavior::Orbit { hit_cooldown, size, inner, .. } => {
                self.positive(file, &[("Orbit.hit_cooldown", *hit_cooldown), ("Orbit.size", *size)])?;
                if let Some(f) = inner {
                    self.positive(
                        file,
                        &[("inner.radius", f.radius), ("inner.every", f.every), ("inner.ratio", f.ratio)],
                    )?;
                }
                Ok(())
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
                ("ult.clear_seconds", p.ult.clear_seconds),
            ],
        )?;
        c.non_negative(
            "player.ron",
            &[
                ("hurt_iframe", p.hurt_iframe),
                ("dash.iframe", p.dash.iframe),
                ("ult.charge_elite", p.ult.charge_elite),
                ("ult.knockback", p.ult.knockback),
                ("ult.boss_fraction", p.ult.boss_fraction),
            ],
        )?;
        c.non_negative(
            "player.ron",
            &[
                ("reveal.per_level", p.reveal.per_level),
                ("reveal.light_per_level", p.reveal.light_per_level),
                ("reveal.band_per_rank", p.reveal.band_per_rank),
            ],
        )?;
        c.positive("player.ron", &[("reveal.band_width", p.reveal.band_width)])?;
        let (ct, rs) = (&p.charms, &p.rescue);
        c.positive(
            "player.ron",
            &[
                ("charms.trail_gap", ct.trail_gap),
                ("charms.trail_radius", ct.trail_radius),
                ("charms.trail_life", ct.trail_life),
                ("rescue.radius", rs.radius),
            ],
        )?;
        c.non_negative(
            "player.ron",
            &[
                ("charms.still_after", ct.still_after),
                ("charms.thorn_freeze", ct.thorn_freeze),
                ("rescue.knockback", rs.knockback),
                ("rescue.iframe", rs.iframe),
            ],
        )?;
        c.fraction("player.ron", "rescue.last_stand_heal", rs.last_stand_heal)?;
        c.fraction("player.ron", "rescue.revive_heal", rs.revive_heal)?;
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
        c.positive("run.ron", &[("spawn.scale", s.scale)])?;
        if s.soft_cap.is_empty()
            || s.soft_cap[0].0 > 0.0
            || s.soft_cap.windows(2).any(|w| w[0].0 >= w[1].0)
            || s.soft_cap.iter().any(|&(_, n)| n > s.hard_cap)
        {
            return c.fail(
                "run.ron",
                "spawn.soft_cap 要从第 0 分钟写起、按分钟递增，而且都不超过 hard_cap".into(),
            );
        }
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
                crate::PlanEvent::Boss { enemy, spawn_mult, barrier } => {
                    c.non_negative(
                        "run.ron",
                        &[("Boss.spawn_mult", *spawn_mult), ("Boss.barrier", *barrier)],
                    )?;
                    std::slice::from_ref(enemy)
                }
                crate::PlanEvent::MiniBoss { enemy, chest_min, .. } => {
                    if *chest_min == 0 {
                        return c.fail("run.ron", "MiniBoss.chest_min 至少为 1".into());
                    }
                    std::slice::from_ref(enemy)
                }
                crate::PlanEvent::Encircle { count, extra, speed_mult, release, warn, enemy } => {
                    c.positive(
                        "run.ron",
                        &[("Encircle.count", count.at(0.0)), ("Encircle.speed_mult", *speed_mult)],
                    )?;
                    c.non_negative(
                        "run.ron",
                        &[
                            ("Encircle.extra", *extra),
                            ("Encircle.release", *release),
                            ("Encircle.warn", *warn),
                        ],
                    )?;
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
        c.positive("run.ron", &[("late.after", r.late.after)])?;
        c.non_negative("run.ron", &[("late.spawn", r.late.spawn), ("late.hp", r.late.hp)])?;
        let e = &r.endless;
        c.positive("run.ron", &[("endless.every", e.every)])?;
        c.non_negative(
            "run.ron",
            &[("endless.oil_per_second", e.oil_per_second), ("endless.oil_per_kill", e.oil_per_kill)],
        )?;
        c.fraction("run.ron", "endless.gold", e.gold)?;
        if e.boss_growth < 1.0 {
            return c.fail("run.ron", "endless.boss_growth 不能小于 1".into());
        }
        // 无尽夜照时间表里的妖潮和夜主再来
        let has = |f: fn(&crate::PlanEvent) -> bool| r.schedule.iter().any(|s| f(&s.event));
        if !has(|e| matches!(e, crate::PlanEvent::Surge { .. }))
            || !has(|e| matches!(e, crate::PlanEvent::Boss { .. }))
        {
            return c.fail("run.ron", "schedule 里要有妖潮和夜主（无尽夜照它们再来）".into());
        }
        let g = &r.gems;
        c.positive("run.ron", &[("gems.accel", g.accel), ("gems.max_speed", g.max_speed)])?;
        if g.cap == 0 || g.elite_split == 0 {
            return c.fail("run.ron", "gems.cap 和 gems.elite_split 至少为 1".into());
        }
        let gd = &r.gold;
        c.fraction("run.ron", "gold.normal_chance", gd.normal_chance)?;
        if gd.coin_value == 0 || gd.cap == 0 || gd.chest.0 > gd.chest.1 {
            return c.fail("run.ron", "gold.coin_value、gold.cap 至少为 1，chest 要写成 (小, 大)".into());
        }
        let l = &r.lanterns;
        c.range("run.ron", "lanterns.distance", l.distance)?;
        c.positive(
            "run.ron",
            &[
                ("lanterns.light_radius", l.light_radius),
                ("lanterns.light_time", l.light_time),
                ("lanterns.zone_radius", l.zone_radius),
                ("lanterns.boss_hp", l.boss_hp),
            ],
        )?;
        c.fraction("run.ron", "lanterns.zone_slow", l.zone_slow)?;
        c.fraction("run.ron", "lanterns.heal", l.heal)?;
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
        c.fraction("run.ron", "choices.pity.key_chance", ch.pity.key_chance)?;
        c.fraction("run.ron", "choices.heal", ch.heal)?;
        c.fraction("run.ron", "choices.elite_charm", ch.elite_charm)?;
        if ch.charm_offers == 0 {
            return c.fail("run.ron", "choices.charm_offers 至少为 1".into());
        }
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
            if let Some(ch) = &e.charge {
                c.positive(
                    "enemies.ron",
                    &[
                        ("charge.range", ch.range),
                        ("charge.every", ch.every),
                        ("charge.windup", ch.windup),
                        ("charge.speed", ch.speed),
                        ("charge.duration", ch.duration),
                        ("charge.damage_mult", ch.damage_mult),
                    ],
                )?;
                c.non_negative("enemies.ron", &[("charge.recover", ch.recover), ("charge.lock", ch.lock)])?;
                if ch.lock > ch.windup {
                    return c.fail("enemies.ron", format!("{} 的 charge.lock 不能超过 windup", e.id));
                }
            }
            if let Some(b) = &e.boss {
                c.positive(
                    "enemies.ron",
                    &[
                        ("boss.volley_every", b.volley_every),
                        ("boss.summon_every", b.summon_every),
                        ("boss.shot_speed", b.shot_speed),
                        ("boss.shot_life", b.shot_life),
                        ("boss.enrage_mult", b.enrage_mult),
                    ],
                )?;
                enemy_ref("enemies.ron", "boss.summon", &b.summon)?;
                if let Some(i) = &b.illusions {
                    c.fraction("enemies.ron", "illusions.at", i.at)?;
                    c.positive(
                        "enemies.ron",
                        &[("illusions.volley_every", i.volley_every), ("illusions.refill", i.refill)],
                    )?;
                }
                if let Some(sw) = &b.sweep {
                    c.fraction("enemies.ron", "sweep.at", sw.at)?;
                    c.positive(
                        "enemies.ron",
                        &[
                            ("sweep.every", sw.every),
                            ("sweep.radius", sw.radius),
                            ("sweep.volley_every", sw.volley_every),
                        ],
                    )?;
                }
                if let Some(l) = &b.lines
                    && [&l.arrive, &l.phase2, &l.phase3, &l.defeat, &l.retreat, &l.again]
                        .iter()
                        .any(|t| t.is_empty())
                {
                    return c.fail("enemies.ron", format!("{} 的台词不能留空", e.id));
                }
                if let Some(rn) = &b.rain {
                    c.positive("enemies.ron", &[("rain.every", rn.every), ("rain.radius", rn.radius)])?;
                }
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
            if p.per_level.is_empty() && p.levels.is_empty() {
                return c.fail("passives.ron", format!("心法 \"{}\" 要写 per_level 或 levels", p.id));
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
        if el.thresholds.len() != 4 || el.thresholds.windows(2).any(|w| w[0] >= w[1]) || el.thresholds[0] == 0
        {
            return c.fail("elements.ron", "thresholds 要写 4 个从小到大的正整数（一阶到极境）".into());
        }
        let max_weapon_level = self.weapons.iter().map(|w| w.levels.len()).max().unwrap_or(0);
        let max_passive_level = self.passives.iter().map(|p| p.max_level as usize).max().unwrap_or(0);
        if el.points.weapon.len() < max_weapon_level || el.points.passive.len() < max_passive_level {
            return c.fail("elements.ron", "points.weapon、points.passive 要覆盖法器和心法的全部等级".into());
        }
        c.positive(
            "elements.ron",
            &[
                ("marks.duration", el.marks.duration),
                ("marks.react_cooldown", el.marks.react_cooldown),
                ("zones.vuln_cap", el.zones.vuln_cap),
                ("zones.counter", el.zones.counter),
                ("zones.same", el.zones.same),
                ("bonus_sword_rate", el.bonus_sword_rate),
            ],
        )?;
        c.unique("elements.ron", "反应", el.reactions.iter().map(|r| r.id.as_str()))?;
        for (i, r) in el.reactions.iter().enumerate() {
            if r.a == r.b {
                return c.fail("elements.ron", format!("反应 \"{}\" 的两系不能相同", r.id));
            }
            if el.reactions[..i].iter().any(|o| (o.a, o.b) == (r.a, r.b) || (o.a, o.b) == (r.b, r.a)) {
                return c.fail("elements.ron", format!("反应 \"{}\" 和前面的反应是同一对五行", r.id));
            }
            c.reaction("elements.ron", &r.id, &r.effect)?;
        }
        if el.elements.len() != Element::ALL.len()
            || el.elements.iter().zip(Element::ALL).any(|(d, e)| d.id != e)
        {
            return c.fail("elements.ron", "elements 要按 Metal、Wood、Water、Fire、Earth 的顺序写全".into());
        }
        for e in &el.elements {
            c.color("elements.ron", &e.name, &e.color)?;
            if e.tiers.len() != el.thresholds.len() {
                return c.fail("elements.ron", format!("\"{}\" 要写 {} 阶共鸣", e.name, el.thresholds.len()));
            }
            if e.tiers.last().is_some_and(|t| t.superseded) {
                return c.fail("elements.ron", format!("\"{}\" 的最后一阶不能写 superseded", e.name));
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
                crate::EventKind::Merchant { radius, .. } => {
                    c.positive("events.ron", &[("Merchant.radius", *radius)])?
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

        // ---- affixes.ron ----
        c.unique("affixes.ron", "词缀", self.affixes.iter().map(|a| a.id.as_str()))?;
        if self.affixes.len() > 16 {
            return c.fail("affixes.ron", "词缀最多 16 个".into());
        }
        for a in &self.affixes {
            match &a.kind {
                crate::AffixKind::Swift { speed } => c.positive("affixes.ron", &[("Swift.speed", *speed)])?,
                crate::AffixKind::Tough { above, reduction } => {
                    c.fraction("affixes.ron", "Tough.above", *above)?;
                    c.fraction("affixes.ron", "Tough.reduction", *reduction)?;
                }
                crate::AffixKind::Split { count, hp, radius, .. } => {
                    if *count == 0 {
                        return c.fail("affixes.ron", "Split.count 至少为 1".into());
                    }
                    c.positive("affixes.ron", &[("Split.hp", *hp), ("Split.radius", *radius)])?;
                }
                crate::AffixKind::Summon { every, enemy, .. } => {
                    c.positive("affixes.ron", &[("Summon.every", *every)])?;
                    enemy_ref("affixes.ron", "Summon.enemy", enemy)?;
                }
                crate::AffixKind::Cloak => {}
                crate::AffixKind::Frenzy { below, boost } => {
                    c.fraction("affixes.ron", "Frenzy.below", *below)?;
                    c.non_negative("affixes.ron", &[("Frenzy.boost", *boost)])?;
                }
            }
        }

        // ---- difficulty.ron ----
        if self.difficulty.is_empty() {
            return c.fail("difficulty.ron", "至少要有一更".into());
        }
        for d in &self.difficulty {
            c.effects("difficulty.ron", &d.name, &d.effects, false)?;
        }

        // ---- meta.ron ----
        let m = &self.meta;
        c.positive("meta.ron", &[("cost_exp", m.cost_exp), ("cost_round", m.cost_round)])?;
        c.unique("meta.ron", "心灯", m.nodes.iter().map(|n| n.id.as_str()))?;
        for n in &m.nodes {
            if n.max_level == 0 {
                return c.fail("meta.ron", format!("心灯 \"{}\" 的 max_level 至少为 1", n.id));
            }
            if !n.levels.is_empty() && n.levels.len() != n.max_level as usize {
                return c.fail("meta.ron", format!("心灯 \"{}\" 的 levels 要有 max_level 项", n.id));
            }
            if n.insight.is_some() && n.max_level != 1 {
                return c.fail("meta.ron", format!("悟 \"{}\" 只能有 1 级", n.id));
            }
            c.positive("meta.ron", &[("base_cost", n.base_cost)])?;
            c.effects("meta.ron", &n.id, &n.per_level, false)?;
            for lv in &n.levels {
                c.effects("meta.ron", &n.id, lv, false)?;
            }
        }

        // ---- attributes.ron ----
        let at = &self.attributes;
        c.non_negative("attributes.ron", &[("inflation", at.inflation)])?;
        c.unique("attributes.ron", "属性", at.list.iter().map(|a| a.id.as_str()))?;
        for a in &at.list {
            if a.max_level == 0 || a.base == 0 {
                return c.fail("attributes.ron", format!("属性 \"{}\" 的 max_level、base 至少为 1", a.id));
            }
            c.effects("attributes.ron", &a.id, &a.per_level, false)?;
        }

        // ---- lamps.ron ----
        c.unique("lamps.ron", "灯", self.lamps.iter().map(|l| l.id.as_str()))?;
        if !self.lamps.iter().any(|l| l.initial) {
            return c.fail("lamps.ron", "至少要有一盏 initial 的灯".into());
        }
        for l in &self.lamps {
            c.color("lamps.ron", &l.id, &l.color)?;
            if self.weapon_index(&l.start_weapon).is_none() {
                return c
                    .fail("lamps.ron", format!("灯 \"{}\" 的起手法器 \"{}\" 不存在", l.id, l.start_weapon));
            }
            c.effects("lamps.ron", &l.id, &l.effects, false)?;
        }

        // ---- charms.ron ----
        c.unique("charms.ron", "灯坠", self.charms.iter().map(|x| x.id.as_str()))?;
        for x in &self.charms {
            c.effects("charms.ron", &x.id, &x.effects, false)?;
        }

        // ---- achievements.ron ----
        c.unique("achievements.ron", "成就", self.achievements.iter().map(|a| a.id.as_str()))?;
        for a in &self.achievements {
            for r in &a.rewards {
                match r {
                    crate::Reward::Lamp(id) if self.lamp_index(id).is_none() => {
                        return c
                            .fail("achievements.ron", format!("成就 \"{}\" 奖励的灯 \"{id}\" 不存在", a.id));
                    }
                    crate::Reward::Charm(id) if self.charm_index(id).is_none() => {
                        return c.fail(
                            "achievements.ron",
                            format!("成就 \"{}\" 奖励的灯坠 \"{id}\" 不存在", a.id),
                        );
                    }
                    crate::Reward::Tier(t) if *t == 0 || *t as usize > self.difficulty.len() => {
                        return c
                            .fail("achievements.ron", format!("成就 \"{}\" 开放的第 {t} 更不存在", a.id));
                    }
                    _ => {}
                }
            }
        }
        Ok(())
    }
}
