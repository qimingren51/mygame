//! 开发者选项（docs/PLAYTEST.md 第 13 项）：测试用的操作，都走 [`SimCommand::Dev`](crate::SimCommand)，
//! 回放照样能复现。用过任何一条，这一局就记成“开发者局”，和 `--god` 一样不计奖励和成绩。
//! 只在 `SimPhase::Play` 里处理，选卡、宝箱、演出时发来的丢掉。

use bevy_ecs::prelude::*;

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
}

/// 这一局的开发者状态。每局开始时重置。
#[derive(Resource, Clone, Copy, Debug, PartialEq)]
pub struct Dev {
    /// 用过开发者操作：结算不计奖励和成绩
    pub used: bool,
    /// 主角打出的伤害倍率
    pub damage: f32,
}

impl Default for Dev {
    fn default() -> Self {
        Dev { used: false, damage: 1.0 }
    }
}
