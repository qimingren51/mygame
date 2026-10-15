//! 设置项（暂停界面和标题界面共用）：音乐音量、音效音量、全屏、震屏、顿帧、辉光、特效。
//! 左右键调整，改完立即生效并存盘。

use bevy::prelude::*;
use bevy::window::{MonitorSelection, PrimaryWindow, WindowMode};

use crate::controls::Controls;
use lantern_platform::{Actions, InputDevice, Settings};
use lantern_view::Feel;

use crate::{Fonts, INK, INK_DIM, text};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Item {
    Music,
    Sfx,
    Fullscreen,
    Shake,
    Hitstop,
    Bloom,
    Fx,
    Keyboard,
    Gamepad,
    DebugTools,
}

pub(crate) const ITEMS: [Item; 9] = [
    Item::Music,
    Item::Sfx,
    Item::Fullscreen,
    Item::Shake,
    Item::Hitstop,
    Item::Bloom,
    Item::Fx,
    Item::Keyboard,
    Item::Gamepad,
];

pub(crate) const ADVANCED_ITEMS: [Item; 1] = [Item::DebugTools];

/// 显示设置值的文字。
#[derive(Component)]
pub(crate) struct SettingValue(pub Item);

fn label(item: Item) -> &'static str {
    match item {
        Item::Music => "音乐",
        Item::Sfx => "音效",
        Item::Fullscreen => "全屏",
        Item::Shake => "震屏",
        Item::Hitstop => "顿帧",
        Item::Bloom => "辉光",
        Item::Fx => "特效",
        Item::Keyboard => "键盘按键",
        Item::Gamepad => "手柄按键",
        Item::DebugTools => "性能调试",
    }
}

fn value(item: Item, s: &Settings) -> String {
    let pct = |v: f32| format!("◀　{:>3}%　▶", (v * 100.0).round() as u32);
    match item {
        Item::Keyboard | Item::Gamepad => "设置".into(),
        Item::Music => pct(s.music_volume),
        Item::Sfx => pct(s.sfx_volume),
        Item::Shake => pct(s.shake),
        Item::Fullscreen => on_off(s.fullscreen),
        Item::Hitstop => on_off(s.hitstop),
        Item::Bloom => on_off(s.bloom),
        Item::Fx => if s.lite_fx { "精简" } else { "完整" }.into(),
        Item::DebugTools => on_off(s.debug_tools),
    }
}

fn on_off(on: bool) -> String {
    if on { "开" } else { "关" }.into()
}

/// 一行设置：名字在左，值在右。
pub(crate) fn spawn_row(p: &mut ChildSpawnerCommands, fonts: &Fonts, settings: &Settings, item: Item) {
    p.spawn(Node { width: percent(100), justify_content: JustifyContent::SpaceBetween, ..default() })
        .with_children(|r| {
            r.spawn(text(&fonts.title, 24.0, INK, label(item)));
            r.spawn((SettingValue(item), text(&fonts.body, 18.0, INK_DIM, &value(item, settings))));
        });
}

/// 处理一项设置的输入：左右调整，回车切换。返回是否改动。
pub(crate) fn adjust(
    item: Item,
    actions: &Actions,
    settings: &mut Settings,
    window: &mut Window,
    controls: &mut Controls,
) -> bool {
    if actions.confirm && matches!(item, Item::Keyboard | Item::Gamepad) {
        controls.open(if item == Item::Keyboard { InputDevice::Keyboard } else { InputDevice::Gamepad });
        return false;
    }
    let step = actions.nav.x as f32 * 0.1;
    let changed = match item {
        Item::Music if step != 0.0 => {
            settings.music_volume = ((settings.music_volume + step) * 10.0).round().clamp(0.0, 10.0) / 10.0;
            true
        }
        Item::Sfx if step != 0.0 => {
            settings.sfx_volume = ((settings.sfx_volume + step) * 10.0).round().clamp(0.0, 10.0) / 10.0;
            true
        }
        Item::Shake if step != 0.0 => {
            settings.shake = ((settings.shake + step * 2.5) * 4.0).round().clamp(0.0, 4.0) / 4.0;
            true
        }
        Item::Hitstop if actions.nav.x != 0 || actions.confirm => {
            settings.hitstop = !settings.hitstop;
            true
        }
        Item::Bloom if actions.nav.x != 0 || actions.confirm => {
            settings.bloom = !settings.bloom;
            true
        }
        Item::Fx if actions.nav.x != 0 || actions.confirm => {
            settings.lite_fx = !settings.lite_fx;
            true
        }
        Item::DebugTools if actions.nav.x != 0 || actions.confirm => {
            settings.debug_tools = !settings.debug_tools;
            true
        }
        Item::Fullscreen if actions.nav.x != 0 || actions.confirm => {
            settings.fullscreen = !settings.fullscreen;
            window.mode = if settings.fullscreen {
                WindowMode::BorderlessFullscreen(MonitorSelection::Current)
            } else {
                WindowMode::Windowed
            };
            true
        }
        _ => false,
    };
    if changed && let Err(e) = settings.save() {
        warn!("保存设置失败：{e}");
    }
    changed
}

/// 设置变了就刷新显示的值。
pub(crate) fn refresh_values(settings: Res<Settings>, mut q: Query<(&SettingValue, &mut Text)>) {
    if !settings.is_changed() {
        return;
    }
    for (v, mut t) in &mut q {
        t.0 = value(v.0, &settings);
    }
}

/// 画面层的手感开关跟着设置走（画面层不依赖平台层，由界面层同步）。
pub(crate) fn sync_feel(settings: Res<Settings>, mut feel: ResMut<Feel>) {
    if !settings.is_changed() {
        return;
    }
    let want = Feel {
        shake: settings.shake,
        hitstop: settings.hitstop,
        bloom: settings.bloom,
        lite: settings.lite_fx,
    };
    if *feel != want {
        *feel = want;
    }
}

pub(crate) type PrimaryWindowQuery<'w, 's> = Single<'w, 's, &'static mut Window, With<PrimaryWindow>>;
