//! 法器（移植自网页版 sim/weapons.ts）。一种行为一个文件，数值来自 `weapons.ron`：
//! - [`orbit`] 环绕（灯火 / 不夜城）
//! - [`volley`] 追踪齐射（符剑 / 万剑归宗），也负责全部飞剑的飞行
//! - [`pulse`] 周期震波（霜铃 / 寒山钟）
//! - [`seeker`] 扑击（纸鹤 / 千鹤引）
//! - [`drop`] 落印（山印 / 镇岳），以及进化后的地裂

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{Content, WeaponBehavior, WeaponLevel};
use lantern_core::StateHasher;
use lantern_core::step::DT;

use crate::build::Build;
use crate::combat::{HitQueue, Strikes};
use crate::enemies::{Enemies, EnemyHandle};
use crate::spatial::Grid;
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimOutbox, SimRng, Tick};

pub mod drop;
pub mod orbit;
pub mod pulse;
pub mod seeker;
pub mod volley;

pub(crate) const TAU: f32 = std::f32::consts::TAU;

/// 纸鹤。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Crane {
    pub pos: Vec2,
    pub prev: Vec2,
    pub vel: Vec2,
    /// true：正在扑击；false：绕身休息
    pub striking: bool,
    /// 休息剩余时间
    pub rest: f32,
    pub target: Option<EnemyHandle>,
    /// 朝向（画面用）
    pub angle: f32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct WeaponSlot {
    /// `weapons.ron` 里的下标
    pub def: usize,
    /// 等级，从 1 开始
    pub level: u32,
    pub evolved: bool,
    /// 冷却计时
    pub timer: f32,
    /// 寒山钟的全屏钟鸣计时（进化后才有）
    pub toll: Option<f32>,
    /// 环绕类法器的当前角度与上一步角度（画面插值用）
    pub angle: f32,
    pub prev_angle: f32,
    /// 本步实际生效的数量、半径、判定大小（画面直接照着画）
    pub count: u32,
    pub radius: f32,
    pub size: f32,
    pub cranes: Vec<Crane>,
}

impl WeaponSlot {
    pub fn new(def: usize) -> Self {
        WeaponSlot {
            def,
            level: 1,
            evolved: false,
            timer: 0.6,
            toll: None,
            angle: 0.0,
            prev_angle: 0.0,
            count: 0,
            radius: 0.0,
            size: 0.0,
            cranes: Vec::new(),
        }
    }

    /// 当前的行为参数（进化后用进化的那一套）。
    pub fn behavior<'a>(&self, content: &'a Content) -> &'a WeaponBehavior {
        let def = &content.weapons[self.def];
        match (&def.evolution, self.evolved) {
            (Some(evo), true) => &evo.behavior,
            _ => &def.behavior,
        }
    }

    /// 当前等级的数值。
    pub fn stats<'a>(&self, content: &'a Content) -> &'a WeaponLevel {
        let def = &content.weapons[self.def];
        match (&def.evolution, self.evolved) {
            (Some(evo), true) => &evo.level,
            _ => &def.levels[(self.level as usize).clamp(1, def.levels.len()) - 1],
        }
    }

    pub fn is_max_level(&self, content: &Content) -> bool {
        self.level as usize >= content.weapons[self.def].levels.len()
    }

    /// 满级、没进化、持有对应心法时可以进化。
    pub fn can_evolve(&self, content: &Content, build: &Build) -> bool {
        let def = &content.weapons[self.def];
        let Some(evo) = &def.evolution else { return false };
        !self.evolved
            && self.is_max_level(content)
            && content.passive_index(&evo.passive).is_some_and(|p| build.passive_level(p) > 0)
    }

    /// 第 k 个环绕物在给定角度下相对主角的位置。
    pub fn orbit_offset(&self, angle: f32, k: u32) -> Vec2 {
        let a = angle + k as f32 * TAU / self.count.max(1) as f32;
        let (s, c) = ops::sin_cos(a);
        Vec2::new(c, s) * self.radius
    }
}

/// 主角身上的法器，按获得顺序。
#[derive(Resource, Default, Debug)]
pub struct Arsenal(pub Vec<WeaponSlot>);

impl Arsenal {
    pub fn hash_into(&self, h: &mut StateHasher) {
        h.write_u32(self.0.len() as u32);
        for w in &self.0 {
            h.write_u32(w.def as u32);
            h.write_u32(w.level);
            h.write_u32(u32::from(w.evolved));
            h.write_f32(w.angle);
            h.write_f32(w.timer);
            for c in &w.cranes {
                h.write_f32(c.pos.x);
                h.write_f32(c.pos.y);
            }
        }
    }
}

/// 法器在一步里需要的东西。
pub(crate) struct Ctx<'a> {
    pub content: &'a Content,
    pub stats: &'a Stats,
    pub grid: &'a Grid,
    pub en: &'a Enemies,
    pub player: Vec2,
    pub secs: f32,
    pub rng: &'a mut lantern_core::Pcg32,
    pub hits: &'a mut HitQueue,
    pub strikes: &'a mut Strikes,
    pub shots: &'a mut volley::Shots,
    pub seals: &'a mut drop::Seals,
    pub outbox: &'a mut SimOutbox,
    pub found: &'a mut Vec<u32>,
}

pub(crate) fn update_weapons(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    player: Single<&Pos, With<Player>>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut rng: ResMut<SimRng>,
    mut arsenal: ResMut<Arsenal>,
    mut hits: ResMut<HitQueue>,
    mut strikes: ResMut<Strikes>,
    mut shots: ResMut<volley::Shots>,
    mut seals: ResMut<drop::Seals>,
    mut outbox: ResMut<SimOutbox>,
    mut found: Local<Vec<u32>>,
) {
    let content = &content.0;
    let t = tick.secs();
    let en = &mut *en;
    for slot in &mut arsenal.0 {
        if let WeaponBehavior::Orbit { .. } = slot.behavior(content) {
            // 灯火要写每只妖物的命中冷却，单独处理
            orbit::update(content, &stats, &grid, en, player.0, t, slot, &mut hits, &mut found);
            continue;
        }
        let mut ctx = Ctx {
            content,
            stats: &stats,
            grid: &grid,
            en,
            player: player.0,
            secs: t,
            rng: rng.0.get(lantern_core::Stream::Combat),
            hits: &mut hits,
            strikes: &mut strikes,
            shots: &mut shots,
            seals: &mut seals,
            outbox: &mut outbox,
            found: &mut found,
        };
        match slot.behavior(content) {
            WeaponBehavior::Orbit { .. } => {}
            WeaponBehavior::Volley { .. } => volley::fire(&mut ctx, slot),
            WeaponBehavior::Pulse { .. } => pulse::update(&mut ctx, slot),
            WeaponBehavior::Seeker { .. } => seeker::update(&mut ctx, slot),
            WeaponBehavior::Drop { .. } => drop::update(&mut ctx, slot),
        }
    }
}

/// 冷却计时：到点返回 true（调用方负责重置）。
pub(crate) fn cooldown_ready(slot: &mut WeaponSlot) -> bool {
    slot.timer -= DT;
    slot.timer <= 0.0
}
