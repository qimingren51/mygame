//! 模拟与外界的接口：输入、命令、事件（docs/DESIGN.md 第 6.7 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_content::{Element, Rank};

use crate::combat::StrikeFx;
use crate::flow::ChestSource;
use crate::pickups::PickupKind;

/// 每一步的移动输入。方向先量化成 i8，实际游玩和回放看到的数值完全一样。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputFrame {
    pub mx: i8,
    pub my: i8,
}

impl InputFrame {
    const SCALE: f32 = 127.0;

    /// 把摇杆或键盘方向（长度不超过 1，y 向下）量化。
    pub fn quantize(dir: Vec2) -> Self {
        let d = if dir.length_squared() > 1.0 { dir.normalize() } else { dir };
        let q = |v: f32| (v * Self::SCALE).round().clamp(-127.0, 127.0) as i8;
        InputFrame { mx: q(d.x), my: q(d.y) }
    }

    /// 模拟使用的方向，长度不超过 1。
    pub fn dir(self) -> Vec2 {
        let v = Vec2::new(f32::from(self.mx), f32::from(self.my)) / Self::SCALE;
        if v.length_squared() > 1.0 { v.normalize() } else { v }
    }
}

/// 改变模拟的命令。回放会记录每条命令和它生效的步数。
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum SimCommand {
    Dash,
    /// 燃灯（充满时才生效）
    Ult,
    /// 升级时选第 i 个选项
    Choose(u8),
    /// 重抽升级选项
    Reroll,
    /// 跳过这次升级（得到灯油）
    Skip,
    /// 封印第 i 个选项：永久移出本局卡池，换一个新选项
    Banish(u8),
    /// 确认宝箱、进化演出
    Ack,
    /// 跑分模式下改变场上保持的妖物数量（分段跑分用）；普通模式下忽略
    BenchTarget(u32),
}

/// 伤害数字的种类。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HitKind {
    Normal,
    /// 持续伤害（灼烧、地裂）、连锁爆炸
    Dot,
    /// 追加飞剑
    Bonus,
    /// 五行反应
    Reaction,
}

/// 主角是被什么打伤的（平衡统计、死因）。kind 是 `enemies.ron` 里的下标。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HurtBy {
    /// 碰到妖物
    Contact { kind: u16 },
    /// 冲锋撞上
    Charge { kind: u16 },
    /// 弹幕
    Shot,
    /// 九尾扫
    Sweep,
    /// 狐火雨
    Rain,
}

/// 等待下一步处理的命令。
#[derive(Resource, Default, Debug)]
pub struct SimCommands(pub Vec<SimCommand>);

/// 模拟发出的事件。保持小而且可复制，预热之后不再分配内存。
/// 画面、音频、界面据此播放效果；需要持续显示的状态（法器、弹幕、奇遇……）直接读资源。
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SimEvent {
    Dash {
        pos: Vec2,
    },
    /// 命中妖物；pos 是伤害数字的位置，element 是这一击的五行（画面按它上色）
    Hit {
        pos: Vec2,
        damage: f32,
        crit: bool,
        kind: HitKind,
        element: Option<Element>,
    },
    /// 击杀；kind 是 `enemies.ron` 里的下标
    Kill {
        pos: Vec2,
        kind: u16,
        rank: Rank,
    },
    GemPicked {
        value: f32,
    },
    PlayerHurt {
        amount: f32,
        by: HurtBy,
    },
    PlayerHealed {
        amount: f32,
    },
    ShieldUp,
    ShieldBroken,
    PlayerDied,
    /// 回光：致命一击留下 1 点生命，震退周围
    LastStand {
        pos: Vec2,
    },
    /// 九转金丹：复活，震退全屏，金丹碎掉
    Revived {
        pos: Vec2,
    },
    /// 挂上了一枚灯坠；index 是 `charms.ron` 下标
    CharmTaken {
        index: u16,
    },
    LevelUp {
        level: u32,
    },
    /// 符剑齐射；weapon 是 `weapons.ron` 下标
    SwordFired {
        weapon: u16,
    },
    CraneStrike {
        pos: Vec2,
    },
    /// 范围打击：寒波、钟鸣、石印落地、爆炸、震地、太极、燃灯
    Strike {
        pos: Vec2,
        radius: f32,
        fx: StrikeFx,
    },
    /// 共鸣升阶
    Resonance {
        element: Element,
        tier: u8,
    },
    /// 相生点亮；index 是 `elements.ron` 里 sheng 的下标
    Sheng {
        index: u8,
    },
    /// 五行反应；kind 是 `elements.ron` 里 reactions 的下标。first：本局第一次（盖章，停顿 0.3 秒）；
    /// label：这次要显示名字（同种反应每 2 秒最多一次）
    Reaction {
        kind: u8,
        pos: Vec2,
        first: bool,
        label: bool,
    },
    /// 封印了一个选项
    Banished,
    /// 合围预警：warn 秒后四面合拢
    EncircleWarn {
        warn: f32,
    },
    Encircle {
        count: u16,
    },
    /// 夜主进入新阶段、狂暴
    BossPhase {
        phase: u8,
    },
    BossEnraged,
    /// 幻身在照见圈里散了
    IllusionDispelled {
        pos: Vec2,
    },
    /// 九尾扫：预警开始、落下（dir 是扇形朝向的角度，世界坐标）
    SweepWarn {
        pos: Vec2,
        dir: f32,
    },
    SweepStrike {
        pos: Vec2,
        dir: f32,
    },
    /// 狐火雨：预警、落下
    RainWarn {
        count: u8,
    },
    RainStrike {
        pos: Vec2,
    },
    /// 点亮了一盏石灯笼；all：灯阵完整
    LanternLit {
        index: u8,
        lit: u8,
        all: bool,
    },
    CoinPicked {
        value: f32,
    },
    /// 货郎：打开、买了东西
    ShopOpened,
    Bought,
    Taiji,
    /// 进化演出开始
    Evolve {
        weapon: u16,
    },
    ChestOpened {
        count: u8,
        source: ChestSource,
    },
    /// 精英出场
    Elite {
        kind: u16,
        count: u8,
    },
    Surge,
    BossArrived {
        kind: u16,
    },
    BossVolley {
        pos: Vec2,
    },
    BossSummon {
        pos: Vec2,
    },
    BossDefeated {
        pos: Vec2,
    },
    Pickup {
        kind: PickupKind,
        pos: Vec2,
    },
    /// 连斩达到提示的数
    Combo {
        count: u32,
    },
    UltReady,
    Ult,
    /// 奇遇出现；kind 是 `events.ron` 里 kinds 的下标
    Encounter {
        kind: u16,
        pos: Vec2,
    },
    CritterFled {
        pos: Vec2,
    },
    CritterLooted {
        pos: Vec2,
    },
    /// 古灯增益；index 是 `events.ron` 里 buffs 的下标
    Buff {
        index: u16,
    },
    /// 血祭坛：失去的生命
    Sacrifice {
        amount: f32,
    },
    RunOver {
        won: bool,
    },
}

/// 一帧内累积的事件。画面、音频、界面在 `Update` 里读取，`Last` 阶段统一清空。
#[derive(Resource, Default, Debug)]
pub struct SimOutbox(pub Vec<SimEvent>);

pub(crate) fn clear_outbox(mut outbox: ResMut<SimOutbox>) {
    outbox.0.clear();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantize_roundtrip_keeps_length_at_most_one() {
        for dir in [Vec2::new(1.0, 1.0), Vec2::new(0.3, -0.2), Vec2::ZERO, Vec2::new(-5.0, 0.0)] {
            let q = InputFrame::quantize(dir);
            assert!(q.dir().length() <= 1.0 + 1e-6, "{dir:?} -> {q:?}");
        }
        assert_eq!(InputFrame::quantize(Vec2::X), InputFrame { mx: 127, my: 0 });
    }
}
