//! 一局之内的公共资源：模拟视野、本局计划、属性、进度。

use bevy_ecs::prelude::*;

use lantern_content::Content;
use lantern_core::{Stream, Streams};

/// 模拟使用的视野，按最宽的宽高比计算，与实际窗口无关（结果才能复现）。
#[derive(Resource, Clone, Copy, Debug)]
pub struct SimView {
    pub half_w: f32,
    pub half_h: f32,
    /// 半对角线
    pub radius: f32,
}

impl SimView {
    pub fn new(content: &Content) -> Self {
        let half_h = content.run.view_height * 0.5;
        let half_w = half_h * content.run.max_aspect;
        SimView { half_w, half_h, radius: (half_w * half_w + half_h * half_h).sqrt() }
    }
}

/// 一局的玩法。跑分模式：保持场上妖物数量，主角无敌，不升级，没有精英、夜主和奇遇。
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum RunMode {
    Normal,
    Bench {
        enemies: u32,
    },
    /// 无尽夜：夜主倒下不天明，倒下才结束（docs/GAMEPLAY.md 第 3.4 节）
    Endless,
}

/// 无尽夜的进度。
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Endless {
    /// 10 分钟以后来过几次妖潮
    pub wave: u32,
    /// 妖潮结束、夜主该来的时刻（秒）
    pub boss_due: Option<f32>,
    /// 夜主来过、倒下几次
    pub arrivals: u32,
    pub downs: u32,
    /// 10 分钟以后的击杀（灯油另算）
    pub late_kills: u32,
}

impl Director {
    pub fn hash_into(&self, h: &mut lantern_core::StateHasher) {
        for v in
            [self.spawn_acc, self.next_pack, self.surge_t, self.surge_mult, self.boss_mult, self.boss_since]
        {
            h.write_f32(v);
        }
        h.write_u32(self.boss.map_or(u32::MAX, |b| b.raw()));
        let (c, r) = self.barrier.unwrap_or((bevy_math::Vec2::ZERO, -1.0));
        for v in [c.x, c.y, r, self.rush_release] {
            h.write_f32(v);
        }
        h.write_u32(self.encircle.len() as u32);
        for e in &self.encircle {
            h.write_u32(e.index as u32);
            h.write_f32(e.at);
        }
        if let Some(e) = &self.endless {
            e.hash_into(h);
        }
        h.write_u32(self.ambush_t.len() as u32);
        for &v in &self.ambush_t {
            h.write_f32(v);
        }
    }
}

impl RunPlan {
    /// 时间表的进度（配比开局就定了，由种子决定，不用写）。
    pub fn hash_into(&self, h: &mut lantern_core::StateHasher) {
        h.write_u32(self.schedule.len() as u32);
        for s in &self.schedule {
            h.write_u32(s.index as u32 | u32::from(s.done) << 31);
            h.write_f32(s.at);
        }
    }
}

impl Progress {
    pub fn hash_into(&self, h: &mut lantern_core::StateHasher) {
        for v in [self.level, self.pending_levels, self.kills, self.combo, self.best_combo] {
            h.write_u32(v);
        }
        for v in [self.xp, self.combo_t, self.ult, self.gold] {
            h.write_f32(v);
        }
    }
}

impl Endless {
    pub fn hash_into(&self, h: &mut lantern_core::StateHasher) {
        for v in [self.wave, self.arrivals, self.downs, self.late_kills] {
            h.write_u32(v);
        }
        h.write_f32(self.boss_due.unwrap_or(-1.0));
    }
}

/// 混进常规刷怪的妖物，比例已经在开局随机好。
#[derive(Clone, Copy, Debug)]
pub struct MixEntry {
    pub kind: u16,
    pub from_minute: f32,
    pub share: f32,
    pub late_minute: f32,
    pub late_mult: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct PackMixEntry {
    pub kind: u16,
    pub from_minute: f32,
    pub share: f32,
}

/// 时间表的一项：出场时刻已经随机好。
#[derive(Clone, Copy, Debug)]
pub struct PlannedStep {
    pub at: f32,
    /// `run.ron` 里 schedule 的下标
    pub index: usize,
    pub done: bool,
}

/// 本局计划：把内容数据里的字符串 ID 换成下标，并在开局随机好配比和时间表。
#[derive(Resource, Clone, Debug)]
pub struct RunPlan {
    pub mode: RunMode,
    /// 主角不会受伤（跑分模式，或测试用的无敌）
    pub god: bool,
    pub base_kind: u16,
    pub mix: Vec<MixEntry>,
    pub pack_mix: Vec<PackMixEntry>,
    pub schedule: Vec<PlannedStep>,
    pub bench_kind: u16,
    pub bench_alt_kind: u16,
}

impl RunPlan {
    pub fn new(content: &Content, mode: RunMode, god: bool, rng: &mut Streams) -> Self {
        let idx = |id: &str| content.enemy_index(id).expect("内容校验保证引用存在") as u16;
        let s = &content.run.spawn;
        let start = rng.get(Stream::Start);
        let mix: Vec<MixEntry> = s
            .mix
            .iter()
            .map(|m| MixEntry {
                kind: idx(&m.enemy),
                from_minute: m.from_minute,
                share: start.range_f32(m.share.0, m.share.1),
                late_minute: m.late_minute,
                late_mult: m.late_mult,
            })
            .collect();
        let pack_mix = s
            .packs
            .mix
            .iter()
            .map(|p| {
                let kind = idx(&p.enemy);
                let base = mix.iter().find(|m| m.kind == kind).map_or(0.0, |m| m.share);
                PackMixEntry { kind, from_minute: p.from_minute, share: base * p.share_scale }
            })
            .collect();
        let bench = matches!(mode, RunMode::Bench { .. });
        let schedule = if bench {
            Vec::new()
        } else {
            content
                .run
                .schedule
                .iter()
                .enumerate()
                .map(|(index, step)| PlannedStep {
                    at: start.range_f32(step.at.0, step.at.1),
                    index,
                    done: false,
                })
                .collect()
        };
        RunPlan {
            mode,
            god: god || bench,
            base_kind: idx(&s.base),
            mix,
            pack_mix,
            schedule,
            bench_kind: idx(&content.run.bench.enemy),
            bench_alt_kind: idx(&content.run.bench.alt_enemy),
        }
    }

    pub fn is_bench(&self) -> bool {
        matches!(self.mode, RunMode::Bench { .. })
    }
}

/// 已经预警、即将合拢的合围。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PendingEncircle {
    /// 出现的时刻（秒）
    pub at: f32,
    /// `run.ron` 里 schedule 的下标
    pub index: usize,
}

/// 刷怪计时、妖潮、合围、夜主与结界。
#[derive(Resource, Clone, Debug)]
pub struct Director {
    /// 常规刷怪的累积量，满 1 刷一只
    pub spawn_acc: f32,
    /// 下一群妖物来的时刻（秒）
    pub next_pack: f32,
    /// 妖潮剩余时间与刷怪倍率
    pub surge_t: f32,
    pub surge_mult: f32,
    /// 场上的夜主
    pub boss: Option<crate::enemies::EnemyHandle>,
    /// 夜主在场时的刷怪倍率
    pub boss_mult: f32,
    /// 夜主登场的时刻（秒）
    pub boss_since: f32,
    /// 夜主的结界：(圆心, 半径)，主角出不去
    pub barrier: Option<(bevy_math::Vec2, f32)>,
    pub encircle: Vec<PendingEncircle>,
    /// 合围的妖物进入这个距离以内恢复原速
    pub rush_release: f32,
    /// 无尽夜的进度；普通一夜是 None
    pub endless: Option<Endless>,
    /// 每条伏击（`run.ron` 的 `spawn.ambush`）下一次出的时刻（秒）；开局第一步按 from 填上
    pub ambush_t: Vec<f32>,
}

impl Default for Director {
    fn default() -> Self {
        Director {
            spawn_acc: 0.0,
            next_pack: 0.0,
            surge_t: 0.0,
            surge_mult: 1.0,
            boss: None,
            boss_mult: 1.0,
            boss_since: 0.0,
            barrier: None,
            encircle: Vec::new(),
            rush_release: 0.0,
            endless: None,
            ambush_t: Vec::new(),
        }
    }
}

/// 经验、等级、击杀、连斩、燃灯充能。
#[derive(Resource, Clone, Debug)]
pub struct Progress {
    pub xp: f32,
    pub level: u32,
    /// 还没选择的升级次数
    pub pending_levels: u32,
    pub kills: u32,
    pub combo: u32,
    /// 连斩剩余时间：归零前再击杀就接上
    pub combo_t: f32,
    pub best_combo: u32,
    /// 燃灯充能 0..=1
    pub ult: f32,
    /// 本局捡到的铜钱
    pub gold: f32,
}

impl Default for Progress {
    fn default() -> Self {
        Progress {
            xp: 0.0,
            level: 1,
            pending_levels: 0,
            kills: 0,
            combo: 0,
            combo_t: 0.0,
            best_combo: 0,
            ult: 0.0,
            gold: 0.0,
        }
    }
}
