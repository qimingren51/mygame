//! 一局之内的公共资源：模拟视野、本局计划、属性、进度。

use bevy_ecs::prelude::*;

use lantern_content::{Content, PlayerDef};
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

/// 跑分模式：保持场上妖物数量，主角无敌，不升级。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunMode {
    Normal,
    Bench { enemies: u32 },
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

/// 本局计划：把内容数据里的字符串 ID 换成下标，并在开局随机好配比。
#[derive(Resource, Clone, Debug)]
pub struct RunPlan {
    pub mode: RunMode,
    pub base_kind: u16,
    pub mix: Vec<MixEntry>,
    pub pack_mix: Vec<PackMixEntry>,
    pub bench_kind: u16,
    pub bench_alt_kind: u16,
}

impl RunPlan {
    pub fn new(content: &Content, mode: RunMode, rng: &mut Streams) -> Self {
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
        RunPlan {
            mode,
            base_kind: idx(&s.base),
            mix,
            pack_mix,
            bench_kind: idx(&content.run.bench.enemy),
            bench_alt_kind: idx(&content.run.bench.alt_enemy),
        }
    }

    pub fn is_bench(&self) -> bool {
        matches!(self.mode, RunMode::Bench { .. })
    }
}

/// 刷怪计时。
#[derive(Resource, Clone, Debug, Default)]
pub struct Director {
    /// 常规刷怪的累积量，满 1 刷一只
    pub spawn_acc: f32,
    /// 下一群妖物来的时刻（秒）
    pub next_pack: f32,
}

/// 主角的属性（M2 起由心法、共鸣、夜签等修正来源汇总，docs/DESIGN.md 第 6.6 节）。
#[derive(Resource, Clone, Debug)]
pub struct Stats {
    pub speed: f32,
    pub magnet: f32,
    pub area: f32,
    pub damage: f32,
    pub crit_chance: f32,
    pub crit_mult: f32,
    pub knockback: f32,
    pub amount: u32,
    pub max_hp: f32,
    pub regen: f32,
}

impl Stats {
    pub fn base(p: &PlayerDef) -> Self {
        Stats {
            speed: p.speed,
            magnet: p.magnet,
            area: 1.0,
            damage: 1.0,
            crit_chance: p.crit_chance,
            crit_mult: p.crit_mult,
            knockback: 1.0,
            amount: 0,
            max_hp: p.max_hp,
            regen: 0.0,
        }
    }
}

/// 经验、等级、击杀。
#[derive(Resource, Clone, Debug)]
pub struct Progress {
    pub xp: f32,
    pub level: u32,
    /// 还没选择的升级次数（M2 的升级界面消费）
    pub pending_levels: u32,
    pub kills: u32,
}

impl Default for Progress {
    fn default() -> Self {
        Progress { xp: 0.0, level: 1, pending_levels: 0, kills: 0 }
    }
}
