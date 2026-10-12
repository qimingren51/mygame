//! 一局的开始与结束、步数、随机流、状态哈希（docs/DESIGN.md 第 7 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use bevy_state::prelude::*;

use lantern_core::step::{DT, HASH_INTERVAL};
use lantern_core::{StateHasher, Streams};

use crate::combat::HitQueue;
use crate::crowd::Crowd;
use crate::enemies::Enemies;
use crate::gems::Gems;
use crate::run::{Director, Progress, RunPlan, SimView, Stats};
use crate::spatial::Grid;
use crate::weapons::{Arsenal, WeaponSlot};
use crate::{
    Body, GameContent, Health, InputFrame, NextSimId, Player, Pos, PrevPos, RunEntity, RunSetup, RunState,
    SimCommands, SimId,
};

/// 已经完成的步数。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Tick(pub u64);

impl Tick {
    /// 本局已经过的时间（秒）。
    pub fn secs(self) -> f32 {
        self.0 as f32 * DT
    }
}

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
    let c = &content.0;
    let p = &c.player;
    let mut rng = Streams::new(setup.seed);
    let plan = RunPlan::new(c, setup.mode, &mut rng);
    let mut ids = NextSimId::default();
    commands.spawn((
        ids.alloc(),
        RunEntity,
        Pos(Vec2::ZERO),
        PrevPos(Vec2::ZERO),
        Body { radius: p.radius },
        Health { hp: p.max_hp, max: p.max_hp },
        Player::default(),
    ));
    let start_weapon = c.weapon_index(&p.start_weapon).expect("内容校验保证引用存在");
    commands.insert_resource(ids);
    commands.insert_resource(Tick(0));
    commands.insert_resource(SimRng(rng));
    commands.insert_resource(plan);
    commands.insert_resource(SimView::new(c));
    commands.insert_resource(Stats::base(p));
    commands.insert_resource(Progress::default());
    commands.insert_resource(Director::default());
    commands.insert_resource(Arsenal(vec![WeaponSlot::new(start_weapon)]));
    commands.insert_resource(Enemies::default());
    commands.insert_resource(Gems::default());
    commands.insert_resource(Grid::default());
    commands.insert_resource(Crowd::default());
    commands.insert_resource(HitQueue::default());
    commands.insert_resource(HashLog::default());
    commands.insert_resource(InputFrame::default());
    commands.insert_resource(SimCommands::default());
}

pub(crate) fn end_run(mut commands: Commands, q: Query<Entity, With<RunEntity>>) {
    for e in &q {
        commands.entity(e).despawn();
    }
    commands.remove_resource::<Tick>();
    commands.remove_resource::<SimRng>();
    commands.remove_resource::<NextSimId>();
    commands.remove_resource::<RunPlan>();
    commands.remove_resource::<Enemies>();
    commands.remove_resource::<Gems>();
    commands.remove_resource::<Grid>();
    commands.remove_resource::<Crowd>();
}

pub(crate) fn save_prev_pos(
    mut q: Query<(&Pos, &mut PrevPos)>,
    mut en: ResMut<Enemies>,
    mut gems: ResMut<Gems>,
) {
    for (pos, mut prev) in &mut q {
        prev.0 = pos.0;
    }
    let en = &mut *en;
    let hi = en.hi;
    en.px[..hi].copy_from_slice(&en.x[..hi]);
    en.py[..hi].copy_from_slice(&en.y[..hi]);
    let n = gems.n;
    let gems = &mut *gems;
    gems.px[..n].copy_from_slice(&gems.x[..n]);
    gems.py[..n].copy_from_slice(&gems.y[..n]);
}

/// 主角倒下后进入结束状态，模拟停下。
pub(crate) fn check_over(player: Single<&Health, With<Player>>, mut next: ResMut<NextState<RunState>>) {
    if player.hp <= 0.0 {
        next.set(RunState::Over);
    }
}

pub(crate) fn advance_tick(mut tick: ResMut<Tick>) {
    tick.0 += 1;
}

pub(crate) fn record_hash(
    tick: Res<Tick>,
    rng: Res<SimRng>,
    en: Res<Enemies>,
    gems: Res<Gems>,
    arsenal: Res<Arsenal>,
    progress: Res<Progress>,
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
    en.hash_into(&mut h);
    gems.hash_into(&mut h);
    arsenal.hash_into(&mut h);
    h.write_f32(progress.xp);
    h.write_u32(progress.level);
    h.write_u32(progress.kills);
    log.0.push(HashCheckpoint { tick: tick.0, hash: h.finish() });
}
