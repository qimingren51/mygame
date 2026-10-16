//! 法器（移植自网页版 sim/weapons.ts）。一种行为一个文件，数值来自 `weapons.ron`：
//! - [`orbit`] 环绕（灯火 / 不夜城）
//! - [`volley`] 追踪齐射（符剑 / 万剑归宗），也负责全部飞剑的飞行
//! - [`pulse`] 周期震波（霜铃 / 寒山钟）
//! - [`seeker`] 扑击（纸鹤 / 千鹤引）
//! - [`drop`] 落印（山印 / 镇岳），以及进化后的地裂
//! - [`sweep`] 扇形挥击（铜钱剑 / 天罡）
//! - [`sky_lantern`] 孔明灯（孔明灯 / 万灯升）
//! - [`wave`] 推浪（沧浪 / 北冥潮）
//! - [`vine`] 连藤（青藤 / 万木春）

use bevy_ecs::prelude::*;
use bevy_ecs::system::SystemParam;
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
pub mod sky_lantern;
pub mod sweep;
pub mod vine;
pub mod volley;
pub mod wave;

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

/// 一件法器只有一条已选定的路径；合璧记内容下标，不能再次进化或异化。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Form {
    #[default]
    Base,
    Evolved,
    Mutated,
    Fused(usize),
}

#[derive(Clone, Debug, PartialEq)]
pub struct WeaponSlot {
    /// `weapons.ron` 里的下标
    pub def: usize,
    /// 等级，从 1 开始
    pub level: u32,
    pub form: Form,
    /// 冷却计时
    pub timer: f32,
    /// 寒山钟的全屏钟鸣计时（进化后才有）
    pub toll: Option<f32>,
    /// 不夜城内环火海的计时
    pub inner_t: f32,
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
            form: Form::Base,
            timer: 0.6,
            toll: None,
            inner_t: 0.0,
            angle: 0.0,
            prev_angle: 0.0,
            count: 0,
            radius: 0.0,
            size: 0.0,
            cranes: Vec::new(),
        }
    }

    /// 当前形态的行为参数。
    pub fn behavior<'a>(&self, content: &'a Content) -> &'a WeaponBehavior {
        let def = &content.weapons[self.def];
        match self.form {
            Form::Evolved => &def.evolution.as_ref().expect("正统进化数据").behavior,
            Form::Mutated => &def.mutation.as_ref().expect("异化数据").behavior,
            Form::Fused(f) => &content.fusions[f].behavior,
            Form::Base => &def.behavior,
        }
    }

    /// 当前等级的数值。
    pub fn stats<'a>(&self, content: &'a Content) -> &'a WeaponLevel {
        let def = &content.weapons[self.def];
        match self.form {
            Form::Evolved => &def.evolution.as_ref().expect("正统进化数据").level,
            Form::Mutated => &def.mutation.as_ref().expect("异化数据").level,
            Form::Fused(f) => &content.fusions[f].level,
            Form::Base => &def.levels[(self.level as usize).clamp(1, def.levels.len()) - 1],
        }
    }

    pub fn is_max_level(&self, content: &Content) -> bool {
        self.level as usize >= content.weapons[self.def].levels.len()
    }

    /// 满级、没进化、持有对应心法时可以进化。
    pub fn can_evolve(&self, content: &Content, build: &Build) -> bool {
        let def = &content.weapons[self.def];
        let Some(evo) = &def.evolution else { return false };
        self.form == Form::Base
            && self.is_max_level(content)
            && content.passive_index(&evo.passive).is_some_and(|p| build.passive_level(p) > 0)
    }

    pub fn transformed(&self) -> bool {
        self.form != Form::Base
    }

    pub fn name<'a>(&self, content: &'a Content) -> &'a str {
        let d = &content.weapons[self.def];
        match self.form {
            Form::Base => &d.name,
            Form::Evolved => &d.evolution.as_ref().expect("进化数据").name,
            Form::Mutated => &d.mutation.as_ref().expect("异化数据").name,
            Form::Fused(f) => &content.fusions[f].name,
        }
    }

    pub fn desc<'a>(&self, content: &'a Content) -> &'a str {
        let d = &content.weapons[self.def];
        match self.form {
            Form::Base => &d.desc,
            Form::Evolved => &d.evolution.as_ref().expect("进化数据").desc,
            Form::Mutated => &d.mutation.as_ref().expect("异化数据").desc,
            Form::Fused(f) => &content.fusions[f].desc,
        }
    }

    /// 卡片和进化演出上的一句话描述（各形态各自一句）。
    pub fn flavor<'a>(&self, content: &'a Content) -> &'a str {
        let d = &content.weapons[self.def];
        match self.form {
            Form::Base => &d.flavor,
            Form::Evolved => &d.evolution.as_ref().expect("进化数据").flavor,
            Form::Mutated => &d.mutation.as_ref().expect("异化数据").flavor,
            Form::Fused(f) => &content.fusions[f].flavor,
        }
    }

    /// 已合璧的材料仍视为持有，防止重新拿取同一法器。
    pub fn contains(&self, content: &Content, def: usize) -> bool {
        self.def == def
            || matches!(self.form, Form::Fused(f)
            if content.fusions[f].weapons.contains(&content.weapons[def].id))
    }

    /// 可以异化：异化与合璧已打开（`run.ron` 的 transformations）、能正统进化，另持有克制本系的满级法器。
    pub fn can_mutate(&self, content: &Content, build: &Build, arsenal: &Arsenal) -> bool {
        let d = &content.weapons[self.def];
        content.run.transformations
            && d.mutation.is_some()
            && self.can_evolve(content, build)
            && arsenal.0.iter().any(|w| {
                w.is_max_level(content)
                    && content
                        .weapons
                        .iter()
                        .enumerate()
                        .any(|(k, other)| w.contains(content, k) && other.element.overcomes(d.element))
            })
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
            h.write_u32(match w.form {
                Form::Base => 0,
                Form::Evolved => 1,
                Form::Mutated => 2,
                Form::Fused(f) => 3 + f as u32,
            });
            h.write_f32(w.angle);
            h.write_f32(w.timer);
            for c in &w.cranes {
                h.write_f32(c.pos.x);
                h.write_f32(c.pos.y);
            }
        }
    }

    /// 法器内部的计时和召唤物状态（钟鸣、火海、巨凤计时，纸鹤的休息、扑击、速度）。
    pub fn hash_detail(&self, h: &mut StateHasher) {
        for w in &self.0 {
            h.write_f32(w.inner_t);
            h.write_f32(w.toll.unwrap_or(-1.0));
            for c in &w.cranes {
                h.write_f32(c.rest);
                h.write_u32(u32::from(c.striking));
                h.write_f32(c.vel.x);
                h.write_f32(c.vel.y);
            }
        }
    }
}

/// 法器放到场上、之后各自更新的东西（飞剑、山印、孔明灯、浪、藤、地裂）。
/// 合成一个参数，免得 `update_weapons` 超过 Bevy 的参数个数上限。
#[derive(SystemParam)]
pub(crate) struct Props<'w> {
    shots: ResMut<'w, volley::Shots>,
    seals: ResMut<'w, drop::Seals>,
    lanterns: ResMut<'w, sky_lantern::SkyLanterns>,
    waves: ResMut<'w, wave::Waves>,
    vines: ResMut<'w, vine::Vines>,
    ground: ResMut<'w, drop::Fissures>,
}

/// 法器在一步里需要的东西。
pub(crate) struct Ctx<'a> {
    pub content: &'a Content,
    pub stats: &'a Stats,
    pub grid: &'a Grid,
    pub en: &'a Enemies,
    pub player: Vec2,
    /// 主角面向（移动方向），朝向类法器没有目标时用
    pub facing: Vec2,
    /// 这一步主角走动了（沧浪：站着不动时朝最近的妖物推浪）
    pub moving: bool,
    pub secs: f32,
    pub rng: &'a mut lantern_core::Pcg32,
    pub hits: &'a mut HitQueue,
    pub strikes: &'a mut Strikes,
    pub shots: &'a mut volley::Shots,
    pub seals: &'a mut drop::Seals,
    pub lanterns: &'a mut sky_lantern::SkyLanterns,
    pub waves: &'a mut wave::Waves,
    pub vines: &'a mut vine::Vines,
    /// 排到下一步执行的动作（青藤回血）
    pub actions: &'a mut crate::combat::ActionQueue,
    pub ground: &'a mut drop::Fissures,
    pub outbox: &'a mut SimOutbox,
    pub bamboo: &'a mut crate::bamboo::Bamboo,
    pub found: &'a mut Vec<u32>,
}

pub(crate) fn update_weapons(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    player: Single<(&Pos, &Player)>,
    grid: Res<Grid>,
    mut en: ResMut<Enemies>,
    mut rng: ResMut<SimRng>,
    mut arsenal: ResMut<Arsenal>,
    mut hits: ResMut<HitQueue>,
    mut strikes: ResMut<Strikes>,
    mut props: Props,
    mut actions: ResMut<crate::combat::ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut bamboo: ResMut<crate::bamboo::Bamboo>,
    mut found: Local<Vec<u32>>,
) {
    let content = &content.0;
    let t = tick.secs();
    let en = &mut *en;
    let (pos, hero) = *player;
    let props = &mut props;
    // 法器没了（合璧用掉）就把它的藤收掉
    props.vines.0.retain(|v| arsenal.0.iter().any(|w| w.def == v.def));
    for slot in &mut arsenal.0 {
        if let WeaponBehavior::Orbit { .. } = slot.behavior(content) {
            // 灯火要写每只妖物的命中冷却，单独处理
            orbit::update(content, &stats, &grid, en, pos.0, t, slot, &mut hits, &mut bamboo, &mut found);
            continue;
        }
        let mut ctx = Ctx {
            content,
            stats: &stats,
            grid: &grid,
            en,
            player: pos.0,
            facing: hero.facing,
            moving: hero.moved > 0.0,
            secs: t,
            rng: rng.0.get(lantern_core::Stream::Combat),
            hits: &mut hits,
            strikes: &mut strikes,
            shots: &mut props.shots,
            seals: &mut props.seals,
            lanterns: &mut props.lanterns,
            waves: &mut props.waves,
            vines: &mut props.vines,
            actions: &mut actions,
            ground: &mut props.ground,
            outbox: &mut outbox,
            bamboo: &mut bamboo,
            found: &mut found,
        };
        match slot.behavior(content) {
            WeaponBehavior::Orbit { .. } => {}
            WeaponBehavior::Volley { .. } => volley::fire(&mut ctx, slot),
            WeaponBehavior::Pulse { .. } => pulse::update(&mut ctx, slot),
            WeaponBehavior::Seeker { .. } => seeker::update(&mut ctx, slot),
            WeaponBehavior::Drop { .. } => drop::update(&mut ctx, slot),
            WeaponBehavior::Sweep { .. } => sweep::update(&mut ctx, slot),
            WeaponBehavior::SkyLantern { .. } => sky_lantern::update(&mut ctx, slot),
            WeaponBehavior::Wave { .. } => wave::update(&mut ctx, slot),
            WeaponBehavior::Vine { .. } => vine::update(&mut ctx, slot),
        }
    }
}

/// 冷却计时：到点返回 true（调用方负责重置）。
pub(crate) fn cooldown_ready(slot: &mut WeaponSlot) -> bool {
    slot.timer -= DT;
    slot.timer <= 0.0
}
