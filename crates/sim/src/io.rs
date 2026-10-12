//! 模拟与外界的接口：输入、命令、事件（docs/DESIGN.md 第 6.7 节）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;
use lantern_content::Rank;

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
    /// 跑分模式下改变场上保持的妖物数量（分段跑分用）；普通模式下忽略
    BenchTarget(u32),
}

/// 等待下一步处理的命令。
#[derive(Resource, Default, Debug)]
pub struct SimCommands(pub Vec<SimCommand>);

/// 模拟发出的事件。保持小而且可复制，预热之后不再分配内存。
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SimEvent {
    Dash {
        pos: Vec2,
    },
    /// 命中妖物；pos 是伤害数字的位置
    Hit {
        pos: Vec2,
        damage: f32,
        crit: bool,
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
    },
    PlayerDied,
    LevelUp {
        level: u32,
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
