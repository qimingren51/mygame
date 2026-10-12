//! 设置项（暂停界面和标题界面共用）：音乐音量、音效音量、全屏。
//! 左右键调整，改完立即生效并存盘。

use bevy::prelude::*;
use bevy::window::{MonitorSelection, PrimaryWindow, WindowMode};

use lantern_platform::{Actions, Settings};

use crate::{Fonts, INK, INK_DIM, text};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Item {
    Music,
    Sfx,
    Fullscreen,
}

pub(crate) const ITEMS: [Item; 3] = [Item::Music, Item::Sfx, Item::Fullscreen];

/// 显示设置值的文字。
#[derive(Component)]
pub(crate) struct SettingValue(pub Item);

fn label(item: Item) -> &'static str {
    match item {
        Item::Music => "音乐",
        Item::Sfx => "音效",
        Item::Fullscreen => "全屏",
    }
}

fn value(item: Item, s: &Settings) -> String {
    let pct = |v: f32| format!("◀　{:>3}%　▶", (v * 100.0).round() as u32);
    match item {
        Item::Music => pct(s.music_volume),
        Item::Sfx => pct(s.sfx_volume),
        Item::Fullscreen => if s.fullscreen { "开" } else { "关" }.into(),
    }
}

/// 一行设置：名字在左，值在右。
pub(crate) fn spawn_row(p: &mut ChildSpawnerCommands, fonts: &Fonts, settings: &Settings, item: Item) {
    p.spawn(Node { width: percent(100), justify_content: JustifyContent::SpaceBetween, ..default() })
        .with_children(|r| {
            r.spawn(text(&fonts.title, 30.0, INK, label(item)));
            r.spawn((SettingValue(item), text(&fonts.body, 20.0, INK_DIM, &value(item, settings))));
        });
}

/// 处理一项设置的输入：左右调整，回车切换。返回是否改动。
pub(crate) fn adjust(item: Item, actions: &Actions, settings: &mut Settings, window: &mut Window) -> bool {
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

pub(crate) type PrimaryWindowQuery<'w, 's> = Single<'w, 's, &'static mut Window, With<PrimaryWindow>>;
