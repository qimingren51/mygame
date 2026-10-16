//! 四类用户总线：音乐、音效、界面、环境。音效下再分普通战斗、前景提示和危险预警，
//! 给预警和高光保留声部。混响插在各总线上，按场所切换（[`crate::space`]）。
//!
//! ```text
//! 音乐（低通、混响）── 六条配乐分轨
//! 音效 ─┬─ 压缩 ─┬─ 战斗（混响，高光时闪避）
//!       │        └─ 前景（混响，夜主倒下时静半拍）
//!       └─ 预警（干声，不压缩）
//! 界面（干声）
//! 环境（混响）
//! ```

use std::time::Duration;

use kira::backend::Backend;
use kira::effect::compressor::CompressorBuilder;
use kira::effect::filter::{FilterBuilder, FilterHandle};
use kira::effect::reverb::{ReverbBuilder, ReverbHandle};
use kira::sound::PlaybackState;
use kira::sound::static_sound::{StaticSoundData, StaticSoundHandle};
use kira::track::{TrackBuilder, TrackHandle};
use kira::{AudioManager, Decibels, ResourceLimitReached, Tween};
use lantern_platform::Settings;

use crate::space::Scene;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Lane {
    Combat,
    Foreground,
    Warning,
    Ui,
}

pub(crate) fn tween(millis: u64) -> Tween {
    Tween { duration: Duration::from_millis(millis), ..Default::default() }
}

/// 兜住手改设置文件的非法值；静音不叠加补偿增益。
fn gain(volume: f32, boost: f32, duck: f32) -> f32 {
    if !volume.is_finite() || volume <= 0.001 {
        Decibels::SILENCE.0
    } else {
        (20.0 * volume.min(1.0).log10() + boost + duck).max(Decibels::SILENCE.0)
    }
}

pub(crate) struct Mixer {
    pub music: TrackHandle,
    sfx: TrackHandle,
    /// 战斗和前景共用的压缩器（留着句柄，否则轨道会被移除）
    _body: TrackHandle,
    ui: TrackHandle,
    pub ambience: TrackHandle,
    combat: TrackHandle,
    foreground: TrackHandle,
    warning: TrackHandle,
    filter: FilterHandle,
    reverbs: Vec<(ReverbHandle, f32)>,
    voices: Vec<(Lane, StaticSoundHandle)>,
    volumes: [f32; 4],
    applied: [f32; 5],
    foreground_muted: bool,
    pub scene: Scene,
}

impl Mixer {
    pub fn new<B: Backend>(
        manager: &mut AudioManager<B>,
        settings: &Settings,
    ) -> Result<Self, ResourceLimitReached> {
        let scene = Scene::Title;
        let mut reverbs = Vec::new();
        let mut spatial = |capacity, scale| {
            let mut track = TrackBuilder::new().sound_capacity(capacity);
            let mut reverb = track.add_effect(ReverbBuilder::new());
            scene.space().apply(&mut reverb, scale, tween(0));
            reverbs.push((reverb, scale));
            track
        };
        // 配乐分轨（crate::music）作为子轨道挂在这里，总线本身不直接放声音。
        let mut music = spatial(8, 0.85);
        let filter = music.add_effect(FilterBuilder::new().cutoff(18_000.0));
        let music = manager.add_sub_track(music)?;
        let ambience = manager.add_sub_track(spatial(8, 1.0))?;
        let mut sfx = manager.add_sub_track(TrackBuilder::new().sound_capacity(0).sub_track_capacity(2))?;
        let mut body = sfx.add_sub_track(
            TrackBuilder::new().sound_capacity(0).sub_track_capacity(2).with_effect(
                CompressorBuilder::new()
                    .threshold(-10.0)
                    .ratio(3.0)
                    .attack_duration(Duration::from_millis(4))
                    .release_duration(Duration::from_millis(120)),
            ),
        )?;
        let combat = body.add_sub_track(spatial(64, 0.65))?;
        let foreground = body.add_sub_track(spatial(32, 0.8))?;
        // 危险预警保留单独的容量与干声，不经过压缩器，不被长锣、奖励和命中抢占，繁忙战斗中仍有清楚的起音。
        let warning = sfx.add_sub_track(TrackBuilder::new().sound_capacity(16))?;
        // 菜单和奖励确认保持近、干、居中，不染上夜主的大空间。
        let ui = manager.add_sub_track(TrackBuilder::new().sound_capacity(32))?;
        let mut mixer = Self {
            music,
            sfx,
            _body: body,
            ui,
            ambience,
            combat,
            foreground,
            warning,
            filter,
            reverbs,
            voices: Vec::new(),
            volumes: [0.0; 4],
            applied: [f32::NAN; 5],
            foreground_muted: false,
            scene,
        };
        mixer.settings(settings);
        mixer.update([0.0; 3], tween(0));
        Ok(mixer)
    }

    pub fn settings(&mut self, s: &Settings) {
        self.volumes = [s.music_volume, s.sfx_volume, s.ui_volume, s.ambience_volume];
    }

    pub fn set_scene(&mut self, scene: Scene) {
        if self.scene == scene {
            return;
        }
        self.scene = scene;
        for (reverb, scale) in &mut self.reverbs {
            scene.space().apply(reverb, *scale, tween(900));
        }
    }

    pub fn muffle(&mut self, on: bool) {
        self.filter.set_cutoff(if on { 650.0 } else { 18_000.0 }, tween(150));
    }

    pub fn update(&mut self, duck: [f32; 3], tween: Tween) {
        let [music, sfx, ui, ambience] = self.volumes;
        let gains = [
            gain(music, 0.0, duck[1]),
            gain(sfx, 7.0, 0.0),
            gain(ui, 4.0, 0.0),
            gain(ambience, 0.0, duck[2]),
            duck[0],
        ];
        // kira 的轨道音量位于效果器之后：静音和闪避都能压住已经响起的混响尾巴。
        for ((track, old), new) in
            [&mut self.music, &mut self.sfx, &mut self.ui, &mut self.ambience, &mut self.combat]
                .into_iter()
                .zip(&mut self.applied)
                .zip(gains)
        {
            if *old != new {
                track.set_volume(Decibels(new), tween);
                *old = new;
            }
        }
        self.voices.retain(|(_, h)| h.state() != PlaybackState::Stopped);
    }

    pub fn play(&mut self, lane: Lane, sound: StaticSoundData) {
        let track = match lane {
            Lane::Combat => &mut self.combat,
            Lane::Foreground => &mut self.foreground,
            Lane::Warning => &mut self.warning,
            Lane::Ui => &mut self.ui,
        };
        if track.num_sounds() >= track.sound_capacity() {
            return;
        }
        match track.play(sound) {
            Ok(handle) => self.voices.push((lane, handle)),
            Err(error) => bevy::log::warn!("播放失败：{error}"),
        }
    }

    pub fn clear_sounds(&mut self) {
        // 包括尚未开始的低锣与晨鸟，返回标题或重开时不能串场。
        for (lane, voice) in &mut self.voices {
            if *lane != Lane::Ui {
                voice.stop(tween(0));
            }
        }
        // 出发的确认声跨过状态切换，保留完整起音。
        self.voices.retain(|(lane, _)| *lane == Lane::Ui);
    }

    pub fn clear_foreground(&mut self) {
        for (lane, voice) in &mut self.voices {
            if *lane == Lane::Foreground {
                voice.stop(tween(25));
            }
        }
    }

    pub fn silence_foreground(&mut self, on: bool) {
        if self.foreground_muted == on {
            return;
        }
        self.foreground_muted = on;
        self.foreground.set_volume(if on { Decibels::SILENCE } else { Decibels::IDENTITY }, tween(25));
    }
}

#[cfg(test)]
#[path = "mixer_tests.rs"]
mod render_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mute_survives_boost_duck_and_invalid_settings() {
        for v in [0.0, -1.0, f32::NAN, f32::INFINITY] {
            assert_eq!(gain(v, 7.0, -16.0), Decibels::SILENCE.0);
            assert_eq!(gain(v, 7.0, 0.0), Decibels::SILENCE.0);
        }
        assert_eq!(gain(2.0, 7.0, 0.0), 7.0);
        assert!(gain(0.4, 7.0, -10.0) < gain(0.8, 7.0, -10.0));
    }
}
