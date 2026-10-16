//! 界面上发生、要出声的事（docs/FEEL.md 第 6 节）。音频原本只听模拟事件；开场卷轴、灯驿这些
//! 界面上的演出和菜单操作由界面发一条 [`UiCue`]，音频照着播。界面不依赖音频，只写这里的类型。

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
    /// 菜单里换了一项，或把设置调了一格
    Move,
    /// 菜单确认、换面板
    Confirm,
    /// 菜单返回
    Back,
}

impl UiCue {
    /// 菜单操作音：一帧里只响最后一个，连按也不会叠。演出音每个都要响。
    pub fn is_menu(self) -> bool {
        matches!(self, Self::Move | Self::Confirm | Self::Back)
    }
}

/// 音频输出不可用（没有声卡、设备被占用）时音频插入这个资源，恢复后移除；界面据此在角落提示。
/// 玩家把音量调成零不算不可用。
#[derive(Resource, Clone, Copy, Debug, PartialEq, Eq)]
pub struct AudioUnavailable;

/// 标题界面此刻在哪：音频按它换环境声和混响。界面写，音频读。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MenuSoundscape {
    #[default]
    Title,
    /// 灯驿长卷和里面的四处
    Hub,
}
