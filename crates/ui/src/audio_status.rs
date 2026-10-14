//! 无音频设备时显示角落提示，恢复后自动隐藏。

use bevy::camera::visibility::VisibilitySystems;
use bevy::prelude::*;
use lantern_audio::AudioUnavailable;

use crate::{Fonts, PAPER, text};

#[derive(Component)]
struct NoAudioDevice;

pub(crate) fn register(app: &mut App) {
    app.add_systems(PostStartup, spawn_indicator)
        .add_systems(PostUpdate, update_indicator.before(VisibilitySystems::VisibilityPropagate));
}

fn spawn_indicator(mut commands: Commands, fonts: Res<Fonts>) {
    commands.spawn((
        NoAudioDevice,
        Node {
            position_type: PositionType::Absolute,
            right: px(16),
            bottom: px(12),
            padding: UiRect::axes(px(8), px(4)),
            ..default()
        },
        text(&fonts.body, 14.0, PAPER, "无音频设备"),
        BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.65)),
        GlobalZIndex(40),
        Pickable::IGNORE,
        Visibility::Hidden,
    ));
}

fn update_indicator(
    unavailable: Option<Res<AudioUnavailable>>,
    mut indicators: Query<&mut Visibility, With<NoAudioDevice>>,
) {
    let visibility = if unavailable.is_some() { Visibility::Inherited } else { Visibility::Hidden };
    for mut indicator in &mut indicators {
        indicator.set_if_neq(visibility);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indicator_follows_device_availability_without_a_game_state() {
        for unavailable_at_start in [false, true] {
            let mut app = App::new();
            app.insert_resource(Fonts { title: default(), body: default() });
            if unavailable_at_start {
                app.insert_resource(AudioUnavailable);
            }
            register(&mut app);
            app.update();
            check_indicator(&mut app, unavailable_at_start);

            app.insert_resource(AudioUnavailable);
            app.update();
            check_indicator(&mut app, true);

            // 模拟 Update 中恢复设备；同一帧的 PostUpdate 就应隐藏提示。
            app.add_systems(Update, |mut commands: Commands| {
                commands.remove_resource::<AudioUnavailable>();
            });
            app.update();
            check_indicator(&mut app, false);
        }
    }

    fn check_indicator(app: &mut App, visible: bool) {
        let world = app.world_mut();
        let mut query = world.query_filtered::<(&Text, &Visibility, &Pickable), With<NoAudioDevice>>();
        let (text, visibility, pickable) = query.single(world).unwrap();
        assert_eq!(text.0, "无音频设备");
        assert_eq!(*visibility, if visible { Visibility::Inherited } else { Visibility::Hidden });
        assert!(!pickable.should_block_lower);
        assert!(!pickable.is_hoverable);
    }
}
