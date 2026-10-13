//! 四种低声压的立体声环境底层，循环接缝交叠，换场交叉淡化。

use std::sync::Arc;

use kira::Frame;
use kira::sound::static_sound::{StaticSoundData, StaticSoundHandle, StaticSoundSettings};
use kira::track::TrackHandle;

use crate::mixer::tween;
use crate::space::Scene;
use crate::synth::{Buf, FilterKind, NoiseOpts, SAMPLE_RATE};

pub(crate) struct Ambience {
    sounds: [StaticSoundData; 4],
    current: Option<Scene>,
    handle: Option<StaticSoundHandle>,
}

impl Ambience {
    pub fn new() -> Self {
        Self { sounds: Scene::ALL.map(render), current: None, handle: None }
    }

    pub fn set_scene(&mut self, scene: Scene, track: Option<&mut TrackHandle>) {
        if self.current == Some(scene) {
            return;
        }
        self.current = Some(scene);
        if let Some(mut handle) = self.handle.take() {
            handle.stop(tween(1200));
        }
        if let Some(track) = track {
            match track.play(self.sounds[scene as usize].fade_in_tween(tween(1200))) {
                Ok(handle) => self.handle = Some(handle),
                Err(error) => bevy::log::warn!("环境声播放失败：{error}"),
            }
        }
    }
}

fn render(scene: Scene) -> StaticSoundData {
    let mut b = Buf::new(12.5);
    b.seed_noise(0x7213_31ab + scene as u32 * 179);
    let (freq, vol) = match scene {
        Scene::Title => (380.0, 0.06),
        Scene::Hub => (220.0, 0.045),
        Scene::Night => (620.0, 0.07),
        Scene::Boss => (150.0, 0.095),
    };
    for at in [0.0, 3.2, 6.4, 9.6] {
        b.noise(at, 4.5, vol, NoiseOpts { kind: FilterKind::Low, freq, attack: 1.8, ..Default::default() });
    }
    match scene {
        Scene::Hub => {
            // 灯芯轻响，听感贴近人物；不使用显眼的节拍。
            for (i, at) in [0.7, 2.3, 5.1, 5.4, 8.7, 10.8].into_iter().enumerate() {
                b.noise(
                    at,
                    0.045,
                    0.013,
                    NoiseOpts { freq: 1100.0 + i as f32 * 130.0, ..Default::default() },
                );
            }
        }
        Scene::Night => {
            for at in [1.3, 4.6, 8.4] {
                for j in 0..3 {
                    b.sine(2700.0 + j as f32 * 110.0, at + j as f32 * 0.13, 0.09, 0.004);
                }
            }
        }
        Scene::Boss => {
            b.noise(0.0, 12.5, 0.07, NoiseOpts { freq: 72.0, q: 1.5, attack: 4.0, ..Default::default() });
        }
        Scene::Title => {}
    }
    let overlap = SAMPLE_RATE as usize / 2;
    let len = b.data.len() - overlap;
    // 头半秒与尾半秒交叠；循环边界两侧来自原采样的相邻位置。
    for i in 0..overlap {
        let x = i as f32 / overlap as f32;
        b.data[i] = b.data[len + i] * (1.0 - x) + b.data[i] * x;
    }
    let delay = SAMPLE_RATE as usize * 17 / 1000;
    let frames: Vec<_> =
        (0..len).map(|i| Frame::new(b.data[i], b.data[(i + len - delay) % len] * 0.94)).collect();
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default().loop_region(..),
        slice: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn beds_are_stereo_quiet_and_seamless() {
        for scene in Scene::ALL {
            let s = render(scene);
            let peak = s.frames.iter().map(|f| f.left.abs().max(f.right.abs())).fold(0.0, f32::max);
            assert!((0.001..0.2).contains(&peak), "{scene:?}: {peak}");
            assert!(s.frames.iter().any(|f| f.left != f.right));
            assert!(s.frames.iter().all(|f| f.left.is_finite() && f.right.is_finite()));
            let seam = *s.frames.first().unwrap() - *s.frames.last().unwrap();
            assert!(seam.left.abs() < 0.005 && seam.right.abs() < 0.005, "{scene:?} 循环爆音");
        }
    }
}
