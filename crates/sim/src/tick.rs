//! 一局的开始与结束、步数、随机流、状态哈希（docs/DESIGN.md 第 7 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_core::step::HASH_INTERVAL;
use lantern_core::{StateHasher, Streams};

use crate::{
    Body, GameContent, Health, InputFrame, NextSimId, Player, Pos, PrevPos, RunEntity, RunSetup, SimCommands,
    SimId,
};

/// 已经完成的步数。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Tick(pub u64);

/// 本局的全部随机流。
#[derive(Resource, Clone, Debug)]
pub struct SimRng(pub Streams);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HashCheckpoint {
    pub tick: u64,
    pub hash: u64,
}

/// 每秒一个状态哈希，写进回放并用于黄金测试。
#[derive(Resource, Default, Debug)]
pub struct HashLog(pub Vec<HashCheckpoint>);

pub(crate) fn start_run(mut commands: Commands, content: Res<GameContent>, setup: Res<RunSetup>) {
    let p = &content.0.player;
    let mut ids = NextSimId::default();
    commands.insert_resource(Tick(0));
    commands.insert_resource(SimRng(Streams::new(setup.seed)));
    commands.insert_resource(HashLog::default());
    commands.insert_resource(InputFrame::default());
    commands.insert_resource(SimCommands::default());
    commands.spawn((
        ids.alloc(),
        RunEntity,
        Pos(Vec2::ZERO),
        PrevPos(Vec2::ZERO),
        Body { radius: p.radius },
        Health { hp: p.max_hp, max: p.max_hp },
        Player::default(),
    ));
    commands.insert_resource(ids);
}

pub(crate) fn end_run(mut commands: Commands, q: Query<Entity, With<RunEntity>>) {
    for e in &q {
        commands.entity(e).despawn();
    }
    commands.remove_resource::<Tick>();
    commands.remove_resource::<SimRng>();
    commands.remove_resource::<NextSimId>();
}

pub(crate) fn save_prev_pos(mut q: Query<(&Pos, &mut PrevPos)>) {
    // 每个实体只写自己，可以并行。
    q.par_iter_mut().for_each(|(pos, mut prev)| prev.0 = pos.0);
}

pub(crate) fn advance_tick(mut tick: ResMut<Tick>) {
    tick.0 += 1;
}

pub(crate) fn record_hash(
    tick: Res<Tick>,
    rng: Res<SimRng>,
    mut log: ResMut<HashLog>,
    q: Query<(&SimId, &Pos, Option<&Health>, Option<&Player>)>,
) {
    if !tick.0.is_multiple_of(HASH_INTERVAL) {
        return;
    }
    let mut h = StateHasher::new();
    h.write_u64(tick.0);
    rng.0.hash_into(&mut h);
    let mut rows: Vec<_> = q.iter().collect();
    rows.sort_unstable_by_key(|(id, ..)| **id);
    for (id, pos, health, player) in rows {
        h.write_u32(id.0);
        h.write_f32(pos.0.x);
        h.write_f32(pos.0.y);
        if let Some(hp) = health {
            h.write_f32(hp.hp);
        }
        if let Some(p) = player {
            for v in [p.facing.x, p.facing.y, p.iframe, p.dash_t, p.dash_cd] {
                h.write_f32(v);
            }
        }
    }
    log.0.push(HashCheckpoint { tick: tick.0, hash: h.finish() });
}
