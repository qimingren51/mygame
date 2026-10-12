//! 主角：移动与闪避（移植自 lantern-next src/sim/step.ts）。

use bevy_ecs::prelude::*;

use lantern_core::step::DT;

use crate::run::{RunMode, RunPlan, Stats};
use crate::{GameContent, InputFrame, Player, Pos, SimCommand, SimCommands, SimEvent, SimOutbox};

pub(crate) fn apply_commands(
    content: Res<GameContent>,
    mut plan: ResMut<RunPlan>,
    mut commands: ResMut<SimCommands>,
    mut outbox: ResMut<SimOutbox>,
    mut q: Query<(&Pos, &mut Player)>,
) {
    let dash = &content.0.player.dash;
    for cmd in commands.0.drain(..) {
        match cmd {
            SimCommand::Dash => {
                for (pos, mut p) in &mut q {
                    if p.dash_cd > 0.0 {
                        continue;
                    }
                    p.dash_t = dash.duration;
                    p.dash_vel = p.facing * dash.speed;
                    p.iframe = p.iframe.max(dash.iframe);
                    p.dash_cd = dash.cooldown;
                    outbox.0.push(SimEvent::Dash { pos: pos.0 });
                }
            }
            SimCommand::BenchTarget(n) => {
                if let RunMode::Bench { enemies } = &mut plan.mode {
                    *enemies = n;
                }
            }
        }
    }
}

pub(crate) fn move_player(stats: Res<Stats>, input: Res<InputFrame>, mut q: Query<(&mut Pos, &mut Player)>) {
    let speed = stats.speed;
    let dir = input.dir();
    for (mut pos, mut p) in &mut q {
        let before = pos.0;
        if p.dash_t > 0.0 {
            p.dash_t -= DT;
            pos.0 += p.dash_vel * DT;
        } else {
            pos.0 += dir * speed * DT;
        }
        if dir.length_squared() > 1e-6 {
            p.facing = dir.normalize();
        }
        p.moved = before.distance(pos.0);
        p.dash_cd = (p.dash_cd - DT).max(0.0);
        p.iframe = (p.iframe - DT).max(0.0);
    }
}
