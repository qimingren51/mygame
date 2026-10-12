//! 加载后的整体校验：数值范围、ID 唯一、引用存在。

use std::collections::BTreeSet;
use std::path::Path;

use crate::{Content, ContentError, WeaponBehavior};

struct Checker<'a> {
    dir: &'a Path,
}

impl Checker<'_> {
    fn fail(&self, file: &str, msg: String) -> Result<(), ContentError> {
        Err(ContentError::Invalid { file: self.dir.join(file), msg })
    }

    fn positive(&self, file: &str, fields: &[(&str, f32)]) -> Result<(), ContentError> {
        for &(field, v) in fields {
            if !(v.is_finite() && v > 0.0) {
                return self.fail(file, format!("{field} 必须是正数，现在是 {v}"));
            }
        }
        Ok(())
    }

    fn non_negative(&self, file: &str, fields: &[(&str, f32)]) -> Result<(), ContentError> {
        for &(field, v) in fields {
            if !(v.is_finite() && v >= 0.0) {
                return self.fail(file, format!("{field} 不能为负数，现在是 {v}"));
            }
        }
        Ok(())
    }

    fn range(&self, file: &str, field: &str, (lo, hi): (f32, f32)) -> Result<(), ContentError> {
        if !(lo.is_finite() && hi.is_finite() && lo <= hi) {
            return self.fail(file, format!("{field} 的范围不对：({lo}, {hi})"));
        }
        Ok(())
    }
}

impl Content {
    pub(crate) fn validate(&self, dir: &Path) -> Result<(), ContentError> {
        let c = Checker { dir };
        let enemy_ref = |file: &str, field: &str, id: &str| -> Result<(), ContentError> {
            if self.enemy_index(id).is_none() {
                return c.fail(file, format!("{field} 引用了不存在的妖物 \"{id}\""));
            }
            Ok(())
        };

        let p = &self.player;
        c.positive(
            "player.ron",
            &[
                ("radius", p.radius),
                ("speed", p.speed),
                ("max_hp", p.max_hp),
                ("crit_mult", p.crit_mult),
                ("dash.duration", p.dash.duration),
                ("dash.speed", p.dash.speed),
            ],
        )?;
        c.non_negative(
            "player.ron",
            &[
                ("magnet", p.magnet),
                ("hurt_iframe", p.hurt_iframe),
                ("crit_chance", p.crit_chance),
                ("dash.cooldown", p.dash.cooldown),
                ("dash.iframe", p.dash.iframe),
            ],
        )?;
        if self.weapon_index(&p.start_weapon).is_none() {
            return c.fail("player.ron", format!("start_weapon 引用了不存在的法器 \"{}\"", p.start_weapon));
        }

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
        let g = &r.gems;
        c.positive("run.ron", &[("gems.accel", g.accel), ("gems.max_speed", g.max_speed)])?;
        if g.cap == 0 || g.elite_split == 0 {
            return c.fail("run.ron", "gems.cap 和 gems.elite_split 至少为 1".into());
        }
        enemy_ref("run.ron", "bench.enemy", &r.bench.enemy)?;
        enemy_ref("run.ron", "bench.alt_enemy", &r.bench.alt_enemy)?;

        let mut ids = BTreeSet::new();
        for e in &self.enemies {
            if !ids.insert(e.id.as_str()) {
                return c.fail("enemies.ron", format!("妖物 ID \"{}\" 重复", e.id));
            }
            c.positive("enemies.ron", &[("radius", e.radius), ("hp", e.hp)])?;
            c.non_negative("enemies.ron", &[("speed", e.speed), ("damage", e.damage), ("xp", e.xp)])?;
            let hex = e.eye.strip_prefix('#').unwrap_or("");
            if hex.len() != 6 || u32::from_str_radix(hex, 16).is_err() {
                return c.fail(
                    "enemies.ron",
                    format!("\"{}\" 的 eye 要写成 #RRGGBB，现在是 \"{}\"", e.id, e.eye),
                );
            }
        }

        let mut ids = BTreeSet::new();
        for w in &self.weapons {
            if !ids.insert(w.id.as_str()) {
                return c.fail("weapons.ron", format!("法器 ID \"{}\" 重复", w.id));
            }
            if w.levels.is_empty() {
                return c.fail("weapons.ron", format!("法器 \"{}\" 没有等级数据", w.id));
            }
            match &w.behavior {
                WeaponBehavior::Orbit { hit_cooldown, size, .. } => {
                    c.positive(
                        "weapons.ron",
                        &[("Orbit.hit_cooldown", *hit_cooldown), ("Orbit.size", *size)],
                    )?;
                    for (i, lv) in w.levels.iter().enumerate() {
                        if lv.count == 0 || lv.radius <= 0.0 || lv.damage <= 0.0 {
                            return c.fail(
                                "weapons.ron",
                                format!("\"{}\" 第 {} 级：Orbit 需要正的 count、radius、damage", w.id, i + 1),
                            );
                        }
                    }
                }
            }
        }
        Ok(())
    }
}
