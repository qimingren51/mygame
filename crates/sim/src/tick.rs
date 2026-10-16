//! 一局的开始与结束、步数、随机流、状态哈希（docs/DESIGN.md 第 7 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use bevy_state::prelude::*;

use lantern_content::Stat;
use lantern_core::step::{DT, HASH_INTERVAL};
use lantern_core::{StateHasher, Stream, Streams};

use crate::boss::{BossState, Foes};
use crate::build::Build;
use crate::charms::{Survival, Trail};
use crate::combat::{ActionQueue, DamageLog, Deaths, HitQueue, Strikes, SwordBudget};
use crate::crowd::Crowd;
use crate::encounters::Encounters;
use crate::enemies::Enemies;
use crate::flow::{Flow, Hold, SimPhase, StepGate};
use crate::gems::Gems;
use crate::gold::Coins;
use crate::lanterns::Lanterns;
use crate::pickups::Pickups;
use crate::player::DashHits;
use crate::reactions::{Discoveries, Herbs, Zones};
use crate::reveal::Reveal;
use crate::run::{Director, Endless, Progress, RunMode, RunPlan, SimView};
use crate::spatial::Grid;
use crate::stats::{StatsDirty, collect};
use crate::weapons::drop::{Fissures, Seals};
use crate::weapons::volley::Shots;
use crate::weapons::{Arsenal, WeaponSlot};
use crate::{
    Body, GameContent, Health, InputFrame, NextSimId, Player, Pos, PrevPos, RunEntity, RunSetup, RunState,
    SimCommands, SimId,
};

/// 游戏时间走过的步数（升级选择等阶段不计）。
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
    let plan = RunPlan::new(c, setup.mode, setup.god, &mut rng);
    let lanterns = if plan.is_bench() {
        Lanterns::default()
    } else {
        Lanterns::place(&c.run.lanterns, rng.get(Stream::Start))
    };
    // 起手法器跟着灯走；跑分模式用 player.ron 里的
    let lamp = &c.lamps[setup.lamp_index(c)];
    let start = if plan.is_bench() { &p.start_weapon } else { &lamp.start_weapon };
    let start_weapon = c.weapon_index(start).expect("内容校验保证引用存在");
    let arsenal = Arsenal(vec![WeaponSlot::new(start_weapon)]);
    let mut build = Build::new(c, &setup);
    build.max_weapons = 1;
    build.compute_resonance(c, &arsenal);
    let (stats, effects) = collect(c, &setup, &build, None, 1);
    let max_hp = stats.max_hp();
    let mut ids = NextSimId::default();
    commands.spawn((
        ids.alloc(),
        RunEntity,
        Pos(Vec2::ZERO),
        PrevPos(Vec2::ZERO),
        Body { radius: p.radius },
        Health { hp: max_hp, max: max_hp },
        Player { dash_ready: stats.get(Stat::DashCharges).round().max(1.0) as u32, ..Player::default() },
    ));
    let ev = &c.events;
    let encounters = Encounters {
        next_at: rng.get(Stream::Event).range_f32(ev.first.0, ev.first.1),
        ..Default::default()
    };
    let flow = Flow {
        rerolls: stats.get(Stat::Rerolls).round().max(0.0) as u32,
        banishes: stats.get(Stat::Banishes).round().max(0.0) as u32,
        // 余烬：开局心法三选一，选中的直接到节点等级（第一步结束时打开）
        ember: stats.get(Stat::StartPassive).round().max(0.0) as u32,
        ..Default::default()
    };
    commands.insert_resource(ids);
    commands.insert_resource(Tick(0));
    commands.insert_resource(SimRng(rng));
    commands.insert_resource(plan);
    commands.insert_resource(SimView::new(c));
    commands.insert_resource(stats);
    commands.insert_resource(effects);
    commands.insert_resource(StatsDirty(false));
    commands.insert_resource(build);
    commands.insert_resource(arsenal);
    commands.insert_resource(flow);
    commands.insert_resource(SimPhase::Play);
    commands.insert_resource(StepGate::default());
    commands.insert_resource(Hold::default());
    commands.insert_resource(Progress::default());
    commands.insert_resource(Director {
        endless: (setup.mode == RunMode::Endless).then(Endless::default),
        ..Default::default()
    });
    let mut enemies = Enemies::default();
    enemies.endless = setup.mode == RunMode::Endless;
    commands.insert_resource(enemies);
    commands.insert_resource(Gems::default());
    commands.insert_resource(Grid::default());
    commands.insert_resource(Crowd::default());
    commands.insert_resource(HitQueue::default());
    commands.insert_resource(Strikes::default());
    commands.insert_resource(ActionQueue::default());
    commands.insert_resource(Deaths::default());
    commands.insert_resource(DamageLog::default());
    commands.insert_resource(Shots::default());
    commands.insert_resource(Seals::default());
    commands.insert_resource(Fissures::default());
    commands.insert_resource(Foes::default());
    commands.insert_resource(Pickups::default());
    commands.insert_resource(Coins::default());
    commands.insert_resource(crate::bamboo::Bamboo::new(c.run.bamboo.as_ref()));
    commands.insert_resource(lanterns);
    commands.insert_resource(BossState::default());
    commands.insert_resource(Reveal::default());
    commands.insert_resource(Zones::default());
    commands.insert_resource(Herbs::default());
    commands.insert_resource(Discoveries::default());
    commands.insert_resource(DashHits::default());
    commands.insert_resource(Trail::default());
    commands.insert_resource(Survival::default());
    commands.insert_resource(SwordBudget(c.elements.bonus_sword_rate));
    commands.insert_resource(encounters);
    commands.insert_resource(HashLog::default());
    commands.insert_resource(InputFrame::default());
    commands.insert_resource(SimCommands::default());
}

pub(crate) fn end_run(mut commands: Commands, q: Query<Entity, With<RunEntity>>) {
    for e in &q {
        commands.entity(e).despawn();
    }
    // 大块的池子立即释放；结算界面还要读的（进度、构筑、流程）留到下一局开局时覆盖
    commands.remove_resource::<SimRng>();
    commands.remove_resource::<NextSimId>();
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

/// 模拟进入结束阶段后，界面层的状态跟着切到 Over。
pub(crate) fn sync_run_state(phase: Res<SimPhase>, mut next: ResMut<NextState<RunState>>) {
    if *phase == SimPhase::Over {
        next.set(RunState::Over);
    }
}

pub(crate) fn advance_tick(mut tick: ResMut<Tick>) {
    tick.0 += 1;
}

#[derive(bevy_ecs::system::SystemParam)]
pub(crate) struct HashParams<'w, 's> {
    tick: Res<'w, Tick>,
    rng: Res<'w, SimRng>,
    en: Res<'w, Enemies>,
    gems: Res<'w, Gems>,
    arsenal: Res<'w, Arsenal>,
    build: Res<'w, Build>,
    stats: Res<'w, crate::stats::Stats>,
    progress: Res<'w, Progress>,
    shots: Res<'w, Shots>,
    ground: Res<'w, Fissures>,
    seals: Res<'w, Seals>,
    foes: Res<'w, Foes>,
    pickups: Res<'w, Pickups>,
    encounters: Res<'w, Encounters>,
    zones: Res<'w, Zones>,
    herbs: Res<'w, Herbs>,
    coins: Res<'w, Coins>,
    lanterns: Res<'w, Lanterns>,
    boss: Res<'w, BossState>,
    trail: Res<'w, Trail>,
    survival: Res<'w, Survival>,
    director: Res<'w, Director>,
    plan: Res<'w, RunPlan>,
    flow: Res<'w, crate::flow::Flow>,
    bamboo: Res<'w, crate::bamboo::Bamboo>,
    q: Query<'w, 's, (&'static SimId, &'static Pos, Option<&'static Health>, Option<&'static Player>)>,
}

/// 流程里排队的东西和次数（选项本身由随机流和构筑决定，选完体现在构筑里）。
fn hash_flow(f: &crate::flow::Flow, h: &mut StateHasher) {
    for v in [
        f.rerolls,
        f.banishes,
        f.lamp_queue,
        f.ember,
        f.charm_queue,
        f.oil_bonus,
        f.chest_queue.len() as u32,
        f.pending_evos.len() as u32,
    ] {
        h.write_u32(v);
    }
    h.write_f32(f.won_at.unwrap_or(-1.0));
}

pub(crate) fn record_hash(p: HashParams, mut log: ResMut<HashLog>) {
    if !p.tick.0.is_multiple_of(HASH_INTERVAL) {
        return;
    }
    let mut h = StateHasher::new();
    h.write_u64(p.tick.0);
    p.rng.0.hash_into(&mut h);
    let mut rows: Vec<_> = p.q.iter().collect();
    rows.sort_unstable_by_key(|(id, ..)| **id);
    for (id, pos, health, player) in rows {
        h.write_u32(id.0);
        h.write_f32(pos.0.x);
        h.write_f32(pos.0.y);
        if let Some(hp) = health {
            h.write_f32(hp.hp);
            h.write_f32(hp.max);
        }
        if let Some(pl) = player {
            for v in [pl.facing.x, pl.facing.y, pl.iframe, pl.dash_t, pl.dash_cd, pl.shield, pl.still_t] {
                h.write_f32(v);
            }
            h.write_u32(pl.dash_ready);
        }
    }
    p.en.hash_into(&mut h);
    p.gems.hash_into(&mut h);
    p.arsenal.hash_into(&mut h);
    p.build.hash_into(&mut h);
    p.stats.hash_into(&mut h);
    p.shots.hash_into(&mut h);
    // 法器内部计时、飞行物的寿命与效果、地面区域、待落石印、封印明细
    p.arsenal.hash_detail(&mut h);
    p.shots.hash_detail(&mut h);
    p.ground.hash_into(&mut h);
    p.seals.hash_into(&mut h);
    p.build.hash_banished(&mut h);
    p.foes.hash_into(&mut h);
    p.pickups.hash_into(&mut h);
    p.encounters.hash_into(&mut h);
    crate::reactions::hash_into(&p.zones, &p.herbs, &mut h);
    p.coins.hash_into(&mut h);
    p.lanterns.hash_into(&mut h);
    p.boss.hash_into(&mut h);
    p.trail.hash_into(&mut h);
    p.survival.hash_into(&mut h);
    p.bamboo.hash_into(&mut h);
    p.director.hash_into(&mut h);
    p.plan.hash_into(&mut h);
    p.progress.hash_into(&mut h);
    hash_flow(&p.flow, &mut h);
    log.0.push(HashCheckpoint { tick: p.tick.0, hash: h.finish() });
}
