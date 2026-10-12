//! 不开窗口、不读真实时间的模拟驱动器。测试、跑分、回放校验都用它。

use std::sync::Arc;

use bevy_app::prelude::*;
use bevy_ecs::prelude::*;
use bevy_state::prelude::*;

use lantern_content::Content;

use crate::build::{Awaken, Build, PassiveSlot};
use crate::combat::DamageLog;
use crate::encounters::Encounters;
use crate::flow::Flow;
use crate::run::{Director, RunPlan};
use crate::spawn::spawn_enemy;
use crate::stats::collect;
use crate::weapons::WeaponSlot;
use crate::{
    AppState, Arsenal, Enemies, GameContent, HashCheckpoint, HashLog, Health, InputFrame, Player, Progress,
    Replay, ReplayLog, ReplayPlayback, RunMode, RunSetup, SimCommand, SimCommands, SimEvent, SimOutbox,
    SimPhase, SimPlugin, SimRng, Stats, Tick,
};

pub struct SimHarness {
    app: App,
}

impl SimHarness {
    /// 用给定内容和种子开始一局（普通模式）。
    pub fn new(content: Content, seed: u64) -> Self {
        Self::with_mode(content, seed, RunMode::Normal)
    }

    pub fn with_mode(content: Content, seed: u64, mode: RunMode) -> Self {
        Self::with_setup(content, RunSetup::new(seed, mode))
    }

    /// 用完整的开局设置（夜签、心灯、无敌）开始一局。
    pub fn with_setup(content: Content, setup: RunSetup) -> Self {
        let mut app = App::new();
        app.add_plugins((bevy_state::app::StatesPlugin, SimPlugin))
            .insert_resource(GameContent(Arc::new(content)))
            .insert_resource(setup);
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Run);
        app.world_mut().run_schedule(StateTransition);
        SimHarness { app }
    }

    /// 从回放开局。之后用 [`SimHarness::step`] 推进（输入由回放提供，传入的参数被忽略），
    /// 直到 [`SimHarness::playback`] 报告结束。
    pub fn from_replay(content: Content, replay: Replay) -> Self {
        let mut sim = Self::with_setup(content, replay.setup.clone());
        sim.app.insert_resource(ReplayPlayback::new(replay));
        sim
    }

    /// 开始录制本局的回放。
    pub fn record(&mut self, game_version: &str) {
        let world = self.app.world();
        let setup = world.resource::<RunSetup>().clone();
        let hash = world.resource::<GameContent>().0.hash;
        self.app.insert_resource(ReplayLog(Replay::new(game_version, hash, setup)));
    }

    pub fn replay(&self) -> Option<&Replay> {
        self.app.world().get_resource::<ReplayLog>().map(|l| &l.0)
    }

    pub fn playback(&self) -> Option<&ReplayPlayback> {
        self.app.world().get_resource::<ReplayPlayback>()
    }

    /// 推进一步（选择阶段游戏时间不走，只处理命令）。本局结束后不再推进。
    pub fn step(&mut self, input: InputFrame, commands: &[SimCommand]) {
        let world = self.app.world_mut();
        *world.resource_mut::<InputFrame>() = input;
        world.resource_mut::<SimCommands>().0.extend_from_slice(commands);
        world.run_schedule(FixedUpdate);
    }

    pub fn phase(&self) -> SimPhase {
        *self.app.world().resource::<SimPhase>()
    }

    pub fn is_over(&self) -> bool {
        self.phase() == SimPhase::Over
    }

    pub fn flow(&self) -> &Flow {
        self.app.world().resource::<Flow>()
    }

    pub fn arsenal(&self) -> &Arsenal {
        self.app.world().resource::<Arsenal>()
    }

    pub fn build(&self) -> &Build {
        self.app.world().resource::<Build>()
    }

    pub fn stats(&self) -> &Stats {
        self.app.world().resource::<Stats>()
    }

    pub fn damage_log(&self) -> &DamageLog {
        self.app.world().resource::<DamageLog>()
    }

    // ---- 测试用：直接摆出场景 ----

    /// 换掉法器和心法（ID + 等级，法器还有是否进化），立即重算共鸣和属性。返回新点亮的共鸣。
    pub fn set_build(&mut self, weapons: &[(&str, u32, bool)], passives: &[(&str, u32)]) -> Vec<Awaken> {
        let world = self.app.world_mut();
        let content = world.resource::<GameContent>().0.clone();
        let mut arsenal = Arsenal::default();
        for &(id, level, evolved) in weapons {
            let mut w = WeaponSlot::new(content.weapon_index(id).unwrap_or_else(|| panic!("没有法器 {id}")));
            w.level = level;
            w.evolved = evolved;
            arsenal.0.push(w);
        }
        let mut build = world.resource::<Build>().clone();
        build.passives = passives
            .iter()
            .map(|&(id, level)| PassiveSlot {
                def: content.passive_index(id).unwrap_or_else(|| panic!("没有心法 {id}")),
                level,
            })
            .collect();
        let awakened = build.compute_resonance(&content, &arsenal);
        let setup = world.resource::<RunSetup>().clone();
        let (stats, effects) = collect(&content, &setup, &build, None);
        let max = stats.max_hp();
        world.insert_resource(arsenal);
        world.insert_resource(build);
        world.insert_resource(stats);
        world.insert_resource(effects);
        let mut q = world.query_filtered::<&mut Health, With<Player>>();
        for mut h in q.iter_mut(world) {
            *h = Health { hp: max, max };
        }
        awakened
    }

    /// 关掉常规刷怪、成群、时间表和奇遇，只留下测试自己摆的妖物。
    pub fn quiet(&mut self) {
        let world = self.app.world_mut();
        let mut d = world.resource_mut::<Director>();
        d.spawn_acc = f32::NEG_INFINITY;
        d.next_pack = f32::INFINITY;
        world.resource_mut::<RunPlan>().schedule.clear();
        world.resource_mut::<Encounters>().next_at = f32::INFINITY;
    }

    /// 在 pos 刷一只妖物。
    pub fn spawn(&mut self, id: &str, pos: bevy_math::Vec2) -> Option<usize> {
        let world = self.app.world_mut();
        let content = world.resource::<GameContent>().0.clone();
        let kind = content.enemy_index(id).unwrap_or_else(|| panic!("没有妖物 {id}")) as u16;
        let minute = world.resource::<Tick>().secs() / 60.0;
        let stats = world.resource::<Stats>().clone();
        world.resource_scope(|world, mut rng: Mut<SimRng>| {
            let mut en = world.resource_mut::<Enemies>();
            spawn_enemy(
                &content,
                &stats,
                &mut en,
                rng.0.get(lantern_core::Stream::Spawn),
                kind,
                pos.x,
                pos.y,
                minute,
            )
        })
    }

    /// 测试里直接改流程状态（例如排一个宝箱、加一次待升级）。
    pub fn flow_mut(&mut self) -> Mut<'_, Flow> {
        self.app.world_mut().resource_mut::<Flow>()
    }

    pub fn progress_mut(&mut self) -> Mut<'_, Progress> {
        self.app.world_mut().resource_mut::<Progress>()
    }

    pub fn enemies(&self) -> &Enemies {
        self.app.world().resource::<Enemies>()
    }

    pub fn progress(&self) -> &Progress {
        self.app.world().resource::<Progress>()
    }

    pub fn player_hp(&mut self) -> f32 {
        let world = self.app.world_mut();
        world.query_filtered::<&Health, bevy_ecs::query::With<Player>>().single(world).map_or(0.0, |h| h.hp)
    }

    pub fn tick(&self) -> u64 {
        self.app.world().resource::<Tick>().0
    }

    pub fn hashes(&self) -> &[HashCheckpoint] {
        &self.app.world().resource::<HashLog>().0
    }

    /// 取走累积的事件。
    pub fn take_events(&mut self) -> Vec<SimEvent> {
        std::mem::take(&mut self.app.world_mut().resource_mut::<SimOutbox>().0)
    }

    pub fn world(&self) -> &World {
        self.app.world()
    }

    pub fn world_mut(&mut self) -> &mut World {
        self.app.world_mut()
    }
}
