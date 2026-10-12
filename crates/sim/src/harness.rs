//! 不开窗口、不读真实时间的模拟驱动器。测试、跑分、回放校验都用它。

use std::sync::Arc;

use bevy_app::prelude::*;
use bevy_ecs::prelude::*;
use bevy_state::prelude::*;

use lantern_content::Content;

use crate::{
    AppState, Enemies, GameContent, HashCheckpoint, HashLog, Health, InputFrame, Player, Progress, Replay,
    ReplayLog, ReplayPlayback, RunMode, RunSetup, RunState, SimCommand, SimCommands, SimEvent, SimOutbox,
    SimPlugin, Tick,
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
        let mut app = App::new();
        app.add_plugins((bevy_state::app::StatesPlugin, SimPlugin))
            .insert_resource(GameContent(Arc::new(content)))
            .insert_resource(RunSetup { seed, mode });
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Run);
        app.world_mut().run_schedule(StateTransition);
        SimHarness { app }
    }

    /// 从回放开局。之后用 [`SimHarness::step`] 推进（输入由回放提供，传入的参数被忽略），
    /// 直到 [`SimHarness::playback`] 报告结束。
    pub fn from_replay(content: Content, replay: Replay) -> Self {
        let mut sim = Self::with_mode(content, replay.seed, replay.mode);
        sim.app.insert_resource(ReplayPlayback::new(replay));
        sim
    }

    /// 开始录制本局的回放。
    pub fn record(&mut self, game_version: &str) {
        let world = self.app.world();
        let setup = world.resource::<RunSetup>().clone();
        let hash = world.resource::<GameContent>().0.hash;
        self.app.insert_resource(ReplayLog(Replay::new(game_version, hash, setup.seed, setup.mode)));
    }

    pub fn replay(&self) -> Option<&Replay> {
        self.app.world().get_resource::<ReplayLog>().map(|l| &l.0)
    }

    pub fn playback(&self) -> Option<&ReplayPlayback> {
        self.app.world().get_resource::<ReplayPlayback>()
    }

    /// 推进一步。本局结束后不再推进。
    pub fn step(&mut self, input: InputFrame, commands: &[SimCommand]) {
        let world = self.app.world_mut();
        *world.resource_mut::<InputFrame>() = input;
        world.resource_mut::<SimCommands>().0.extend_from_slice(commands);
        world.run_schedule(FixedUpdate);
        // 主角倒下时模拟会切到 Over 状态，这里立即生效
        world.run_schedule(StateTransition);
    }

    pub fn is_over(&self) -> bool {
        self.app.world().get_resource::<State<RunState>>().is_some_and(|s| *s.get() == RunState::Over)
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
