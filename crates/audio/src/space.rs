//! 场所的声音记忆：标题空阔、灯驿温近、夜战开阔、夜主低沉。

use bevy::math::Vec2;
use kira::effect::reverb::ReverbHandle;
use kira::{Mix, Tween};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) enum Scene {
    #[default]
    Title,
    Hub,
    Night,
    Boss,
}

#[derive(Clone, Copy)]
pub(crate) struct Space {
    pub feedback: f64,
    pub damping: f64,
    pub width: f64,
    pub wet: f32,
    pan_distance: f32,
    falloff: f32,
}

impl Scene {
    pub const ALL: [Self; 4] = [Self::Title, Self::Hub, Self::Night, Self::Boss];

    pub fn space(self) -> Space {
        match self {
            Self::Title => Space {
                feedback: 0.78,
                damping: 0.48,
                width: 0.95,
                wet: 0.22,
                pan_distance: 440.0,
                falloff: 520.0,
            },
            Self::Hub => Space {
                feedback: 0.42,
                damping: 0.72,
                width: 0.55,
                wet: 0.10,
                pan_distance: 300.0,
                falloff: 350.0,
            },
            Self::Night => Space {
                feedback: 0.56,
                damping: 0.62,
                width: 1.0,
                wet: 0.12,
                pan_distance: 340.0,
                falloff: 420.0,
            },
            Self::Boss => Space {
                feedback: 0.83,
                damping: 0.67,
                width: 0.90,
                wet: 0.25,
                pan_distance: 400.0,
                falloff: 560.0,
            },
        }
    }
}

impl Space {
    pub fn apply(self, reverb: &mut ReverbHandle, scale: f32, tween: Tween) {
        reverb.set_feedback(self.feedback, tween);
        reverb.set_damping(self.damping, tween);
        reverb.set_stereo_width(self.width, tween);
        reverb.set_mix(Mix(self.wet * scale), tween);
    }

    /// 全屏提示不经过此函数，保留正中央的清晰起音。
    pub fn place(self, offset: Vec2) -> (f32, f32) {
        ((offset.x / self.pan_distance).clamp(-0.75, 0.75), (offset.length() / self.falloff * 6.0).min(9.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scenes_have_distinct_bounded_spaces() {
        for scene in Scene::ALL {
            let s = scene.space();
            assert!(s.feedback < 0.9 && s.wet < 0.3);
            assert_eq!(s.place(Vec2::ZERO), (0.0, 0.0));
            assert_eq!(s.place(Vec2::splat(10000.0)), (0.75, 9.0));
            let (left, _) = s.place(Vec2::new(-100.0, 0.0));
            assert!(left < 0.0);
        }
        assert!(Scene::Hub.space().feedback < Scene::Night.space().feedback);
        assert!(Scene::Night.space().wet < Scene::Boss.space().wet);
        assert_ne!(Scene::Title.space().width, Scene::Hub.space().width);
    }
}
