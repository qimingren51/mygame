//! 构筑的通用语言：属性、修正、触发器（docs/DESIGN.md 第 6.6 节）。
//!
//! 心法、五行共鸣、相生、夜签、心灯、古灯增益都写成 [`Effect`] 列表。模拟把当前生效的全部
//! 效果汇总成属性值和触发器表；新增一种效果只需要给枚举加一个变体，再在模拟里写处理函数。

use serde::{Deserialize, Serialize};

use crate::Quad;

/// 属性。最终值 = clamp((基础值 + Σ加值) × (1 + Σ乘值), 下限, 上限)，基础值和上下限在 `stats.ron`。
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Stat {
    // ---- 输出 ----
    /// 伤害倍率
    Damage,
    /// 范围倍率
    Area,
    /// 冷却倍率
    Cooldown,
    /// 法器数量加值
    Amount,
    CritChance,
    CritMult,
    /// 击退倍率
    Knockback,
    /// 灼烧伤害倍率
    BurnDamage,
    /// 灼烧最多叠几层
    BurnStacks,
    /// 对冰冻目标的额外伤害（0.5 表示 ×1.5）
    FrozenDamage,
    /// 大于 0 时，被击晕的目标必定暴击
    StunCrit,
    // ---- 生存 ----
    MaxHp,
    /// 每次受伤减去的固定值
    Armor,
    /// 减伤比例
    Reduction,
    /// 每秒回复生命上限的比例
    Regen,
    /// 护盾打破后多少秒重新获得
    ShieldCooldown,
    /// 治疗倍率（0 表示无法回复）
    Healing,
    // ---- 移动与拾取 ----
    Speed,
    Magnet,
    /// 灯光半径倍率
    Light,
    /// 魂火价值倍率
    XpGain,
    // ---- 构筑 ----
    Rerolls,
    /// 升级时的选项数
    Choices,
    /// 宝箱至少开几个
    ChestMin,
    /// 宝箱多开的运气
    ChestLuck,
    // ---- 单局规则 ----
    SpawnRate,
    EnemyHp,
    EnemySpeed,
    /// 每次出几只精英
    EliteCount,
    /// 奇遇出现频率
    EventRate,
    /// 灯油收益倍率
    OilGain,
}

impl Stat {
    pub const ALL: [Stat; 31] = [
        Stat::Damage,
        Stat::Area,
        Stat::Cooldown,
        Stat::Amount,
        Stat::CritChance,
        Stat::CritMult,
        Stat::Knockback,
        Stat::BurnDamage,
        Stat::BurnStacks,
        Stat::FrozenDamage,
        Stat::StunCrit,
        Stat::MaxHp,
        Stat::Armor,
        Stat::Reduction,
        Stat::Regen,
        Stat::ShieldCooldown,
        Stat::Healing,
        Stat::Speed,
        Stat::Magnet,
        Stat::Light,
        Stat::XpGain,
        Stat::Rerolls,
        Stat::Choices,
        Stat::ChestMin,
        Stat::ChestLuck,
        Stat::SpawnRate,
        Stat::EnemyHp,
        Stat::EnemySpeed,
        Stat::EliteCount,
        Stat::EventRate,
        Stat::OilGain,
    ];
    pub const COUNT: usize = Stat::ALL.len();
}

/// 属性的基础值与上下限（`stats.ron`）。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct StatDef {
    pub base: f32,
    #[serde(default = "neg_inf")]
    pub min: f32,
    #[serde(default = "pos_inf")]
    pub max: f32,
}

fn neg_inf() -> f32 {
    f32::NEG_INFINITY
}

fn pos_inf() -> f32 {
    f32::INFINITY
}

/// 一条效果。
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub enum Effect {
    /// 属性加值
    Add(Stat, f32),
    /// 属性乘值（同一属性的乘值先相加，再乘到加值之后）
    Mul(Stat, f32),
    /// 在某个时机做某件事
    Trigger {
        on: When,
        /// 触发概率
        #[serde(default = "one")]
        chance: f32,
        #[serde(default)]
        only: Cond,
        action: Action,
    },
    /// 护盾：打破后经过 [`Stat::ShieldCooldown`] 秒重新获得，护盾值随分钟数增长
    Shield { amount: Quad },
    /// 夜签选定的五行多得几点共鸣
    Points(u32),
    /// 升级选项偏向夜签选定的五行
    Favor,
}

fn one() -> f32 {
    1.0
}

/// 触发时机。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
pub enum When {
    /// 命中（持续伤害和连锁爆炸不算）
    Hit,
    /// 暴击
    Crit,
    /// 击杀
    Kill,
    /// 护盾被打破
    ShieldBreak,
    /// 每隔几秒
    Periodic(f32),
}

/// 触发条件。
#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
pub enum Cond {
    #[default]
    Always,
    /// 目标处于冰冻
    TargetFrozen,
    /// 这次命中不是追加飞剑造成的（追加的飞剑不再触发追加）
    NotBonus,
}

/// 连锁爆炸的种类（画面用不同颜色）。
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum BlastKind {
    Fire,
    Ice,
}

/// 触发后做的事。伤害曲线的 x 是分钟数，追加飞剑的 x 是主角等级。
#[derive(Clone, Copy, Debug, Deserialize, PartialEq)]
pub enum Action {
    /// 灼烧：每层每秒伤害 = 命中伤害 × ratio × [`Stat::BurnDamage`]，层数上限 [`Stat::BurnStacks`]
    Burn {
        duration: f32,
        ratio: f32,
    },
    Slow {
        amount: f32,
        duration: f32,
    },
    /// 冰冻（夜主免疫）
    Freeze {
        duration: f32,
    },
    /// 从主角朝目标射出一把追踪飞剑（追加的飞剑命中时不再触发 [`Cond::NotBonus`] 的效果）
    BonusSword {
        damage: Quad,
        pierce: u32,
        speed: f32,
        life: f32,
        turn: f32,
        hit_radius: f32,
        knockback: f32,
    },
    /// 回复生命
    Heal(f32),
    /// 在目标位置爆炸（下一步结算，不暴击）
    Explode {
        radius: f32,
        damage: Quad,
        kind: BlastKind,
    },
    /// 以主角为中心震地：伤害、击退、击晕
    Quake {
        radius: f32,
        damage: Quad,
        knockback: f32,
        stun: f32,
    },
    /// 对视野内所有妖物造成伤害，对夜主单次不超过 boss_cap
    ScreenDamage {
        damage: Quad,
        boss_cap: f32,
    },
    /// 在主角附近落下一个宝箱
    DropChest {
        distance: f32,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn effects_parse_from_ron() {
        let text = "[
            Add(CritChance, 0.1),
            Mul(Area, 0.1),
            Trigger(on: Hit, action: Burn(duration: 3.0, ratio: 0.2)),
            Trigger(on: Crit, chance: 0.5, only: NotBonus, action: BonusSword(damage: (10.0, 1.0, 0.0), pierce: 2,
                speed: 380.0, life: 1.5, turn: 8.0, hit_radius: 6.0, knockback: 30.0)),
            Trigger(on: Periodic(30.0), action: ScreenDamage(damage: (40.0, 16.0, 0.0), boss_cap: 600.0)),
            Shield(amount: (20.0, 5.0, 0.0)),
            Points(2),
            Favor,
        ]";
        let v: Vec<Effect> = ron::from_str(text).unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(v.len(), 8);
        assert!(matches!(v[3], Effect::Trigger { chance, only: Cond::NotBonus, .. } if chance == 0.5));
        assert!(matches!(v[2], Effect::Trigger { chance, only: Cond::Always, .. } if chance == 1.0));
    }
}
