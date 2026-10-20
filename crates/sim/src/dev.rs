//! 开发者选项（docs/PLAYTEST.md 第 13 项）：测试用的操作，都走 [`SimCommand::Dev`](crate::SimCommand)，
//! 回放照样能复现。用过任何一条，这一局就记成“开发者局”，和 `--god` 一样不计奖励和成绩。
//! 只在 `SimPhase::Play` 里处理，选卡、宝箱、演出时发来的丢掉。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::Rank;
use lantern_core::Stream;

use crate::enemies::Enemies;
use crate::run::Director;
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, SimRng, Tick};

/// 开发者操作。下标都是内容表里的下标（`weapons.ron`、`passives.ron`、`fusions.ron`）。
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum DevCommand {
    /// 无敌开关
    God(bool),
    /// 主角打出的伤害 × n（1 为原样）
    Damage(u16),
    /// 连升 n 级（照常弹出选卡）
    Levels(u8),
    /// 燃灯充满
    FillUlt,
    /// 加铜钱（货郎用）
    Gold(u32),
    /// 拿一件法器；已经有了就升一级
    Weapon(u16),
    /// 法器直接满级（没有就先拿）
    MaxWeapon(u16),
    /// 拿一门心法；已经有了就升一级
    Passive(u16),
    /// 立刻进化、异化（没有就先拿、先满级，不看心法和克制的条件），照常演出
    Evolve(u16),
    Mutate(u16),
    /// 立刻合璧：两件材料没有就先拿，先进化，再合
    Fuse(u16),
    /// 时间跳到第几秒（只往后跳）；跳过的时间表不再触发，正好在这一刻的照常发生（夜主 9:30）
    SkipTo(u16),
    /// 在主角右边刷一只指定的妖物（`enemies.ron` 下标；夜主要走时间表，这里不刷）
    Spawn(u16),
    /// 清屏：夜主以外的妖物全部消失，不掉魂火、不算击杀
    Clear,
    /// 常规刷怪、成群、伏击的开关（时间表照常）
    Spawning(bool),
}

/// 这一局的开发者状态。每局开始时重置。
#[derive(Resource, Clone, Debug, PartialEq)]
pub struct Dev {
    /// 用过开发者操作：结算不计奖励和成绩
    pub used: bool,
    /// 主角打出的伤害倍率
    pub damage: f32,
    /// 停了常规刷怪
    pub no_spawn: bool,
    /// 要动妖物池的操作（刷妖、清屏），命令处理完在 [`apply`] 里做
    pub(crate) queue: Vec<DevCommand>,
}

impl Default for Dev {
    fn default() -> Self {
        Dev { used: false, damage: 1.0, no_spawn: false, queue: Vec::new() }
    }
}

/// 刷出来的妖物离主角多远（在主角右边）
const SPAWN_OFFSET: f32 = 220.0;

/// 刷妖、清屏：紧跟在处理命令之后。
pub(crate) fn apply(
    content: Res<GameContent>,
    stats: Res<Stats>,
    tick: Res<Tick>,
    director: Res<Director>,
    player: Query<&Pos, With<Player>>,
    mut dev: ResMut<Dev>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
) {
    let Ok(player) = player.single() else { return };
    if dev.queue.is_empty() {
        return;
    }
    let c = &content.0;
    for cmd in std::mem::take(&mut dev.queue) {
        match cmd {
            DevCommand::Spawn(kind) => {
                if c.enemies.get(usize::from(kind)).is_none_or(|e| e.rank == Rank::Boss) {
                    continue;
                }
                let at = player.0 + Vec2::new(SPAWN_OFFSET, 0.0);
                let rng = rng.0.get(Stream::Spawn);
                crate::spawn::spawn_enemy(c, &stats, &mut en, rng, kind, at.x, at.y, tick.secs() / 60.0);
            }
            DevCommand::Clear => {
                let alive: Vec<usize> = en.iter_alive().collect();
                for i in alive {
                    if director.boss != Some(en.handle(i)) {
                        en.kill(i);
                    }
                }
            }
            _ => {}
        }
    }
}
