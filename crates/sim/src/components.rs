//! 模拟实体的组件。坐标是世界单位，y 轴向下（与网页版一致，画面层负责翻转）。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

/// 按创建顺序递增、永不复用的编号。对顺序敏感的逻辑用它打破平局，不依赖 `Entity` 编号。
#[derive(Component, Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SimId(pub u32);

/// 下一个可用的 [`SimId`]。
#[derive(Resource, Default, Debug)]
pub struct NextSimId(pub u32);

impl NextSimId {
    pub fn alloc(&mut self) -> SimId {
        let id = SimId(self.0);
        self.0 += 1;
        id
    }
}

#[derive(Component, Clone, Copy, Debug, Default, PartialEq)]
pub struct Pos(pub Vec2);

/// 上一步的位置，画面层在两者之间插值。
#[derive(Component, Clone, Copy, Debug, Default, PartialEq)]
pub struct PrevPos(pub Vec2);

#[derive(Component, Clone, Copy, Debug, PartialEq)]
pub struct Body {
    pub radius: f32,
}

#[derive(Component, Clone, Copy, Debug, PartialEq)]
pub struct Health {
    pub hp: f32,
    pub max: f32,
}

/// 主角的状态。
#[derive(Component, Clone, Copy, Debug, PartialEq)]
pub struct Player {
    /// 朝向（单位向量），闪避沿这个方向
    pub facing: Vec2,
    /// 本步移动的距离，画面层用来推进走路动画
    pub moved: f32,
    /// 剩余无敌时间
    pub iframe: f32,
    /// 剩余闪避时间
    pub dash_t: f32,
    /// 闪避：还能用几段、下一段的充能倒计时
    pub dash_ready: u32,
    pub dash_cd: f32,
    pub dash_vel: Vec2,
    /// 土·固的护盾：当前值、获得时的值、打破后重新获得的倒计时
    pub shield: f32,
    pub shield_max: f32,
    pub shield_t: f32,
}

impl Default for Player {
    fn default() -> Self {
        Player {
            facing: Vec2::X,
            moved: 0.0,
            iframe: 0.0,
            dash_t: 0.0,
            dash_ready: 1,
            dash_cd: 0.0,
            dash_vel: Vec2::ZERO,
            shield: 0.0,
            shield_max: 0.0,
            shield_t: 0.0,
        }
    }
}

/// 属于当前这一局的实体，一局结束时统一清除。
#[derive(Component, Clone, Copy, Debug, Default)]
pub struct RunEntity;
