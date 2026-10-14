//! 无音频设备时显示角落提示，恢复后自动隐藏。

use bevy::camera::visibility::VisibilitySystems;
use bevy::prelude::*;
use lantern_audio::AudioStatus;

use crate::{DIM, Fonts, text};

#[derive(Component)]
struct NoAudioDevice;

pub(crate) fn register(app: &mut App) {
    app.add_systems(PostStartup, spawn_indicator)
        .add_systems(PostUpdate, update_indicator.before(VisibilitySystems::VisibilityPropagate));
}

fn spawn_indicator(mut commands: Commands, fonts: Res<Fonts>) {
    commands.spawn((
        NoAudioDevice,
        Node { position_type: PositionType::Absolute, right: px(16), bottom: px(12), ..default() },
        text(&fonts.body, 14.0, DIM, "无音频设备"),
        GlobalZIndex(40),
        Pickable::IGNORE,
        Visibility::Hidden,
    ));
}

fn update_indicator(
    status: Option<Res<AudioStatus>>,
    mut indicators: Query<&mut Visibility, With<NoAudioDevice>>,
) {
    let visibility = if status.as_deref() == Some(&AudioStatus::NoDevice) {
        Visibility::Inherited
    } else {
        Visibility::Hidden
    };
    for mut indicator in &mut indicators {
        indicator.set_if_neq(visibility);
    }
}
