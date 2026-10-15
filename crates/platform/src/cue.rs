//! 界面上发生、要出声的事（docs/FEEL.md 第 6 节）。音频原本只听模拟事件；开场卷轴、灯驿这些
//! 界面上的演出由界面发一条 [`UiCue`]，音频照着播。

use bevy::prelude::*;

#[derive(Message, Clone, Copy, Debug, PartialEq, Eq)]
pub enum UiCue {
    /// 开场卷轴开始展开
    ScrollUnroll,
    /// 卷轴旁白的第几行开始浮出（从 0 起，音高按行往上走）
    ScrollLine(u8),
    /// 灯驿里一盏心灯点亮
    LampLit,
    /// 灯驿远山的晨光开始铺开
    DawnSpread,
}
