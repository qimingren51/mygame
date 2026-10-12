//! 不开窗口、不读真实时间的模拟驱动器。测试、跑分、回放校验都用它。

use std::sync::Arc;

use bevy_app::prelude::*;
use bevy_ecs::prelude::*;
use bevy_state::prelude::*;

use lantern_content::Content;

use crate::{
    AppState, GameContent, HashCheckpoint, HashLog, InputFrame, RunSetup, SimCommand, SimCommands, SimEvent,
    SimOutbox, SimPlugin, Tick,
};

pub struct SimHarness {
    app: App,
}

impl SimHarness {
    /// 用给定内容和种子开始一局。
    pub fn new(content: Content, seed: u64) -> Self {
        let mut app = App::new();
        app.add_plugins((bevy_state::app::StatesPlugin, SimPlugin))
            .insert_resource(GameContent(Arc::new(content)))
            .insert_resource(RunSetup { seed });
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Run);
        app.world_mut().run_schedule(StateTransition);
        SimHarness { app }
    }

    /// 推进一步。
    pub fn step(&mut self, input: InputFrame, commands: &[SimCommand]) {
        let world = self.app.world_mut();
        *world.resource_mut::<InputFrame>() = input;
        world.resource_mut::<SimCommands>().0.extend_from_slice(commands);
        world.run_schedule(FixedUpdate);
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
