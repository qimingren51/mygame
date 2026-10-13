//! 使用真正的 kira 渲染器检查总线输出，不需要声卡。

use std::sync::Arc;

use kira::backend::{Backend, Renderer};
use kira::sound::static_sound::StaticSoundSettings;
use kira::{AudioManagerSettings, Frame, StartTime};

use super::*;
use crate::synth::SAMPLE_RATE;

struct Offline {
    renderer: Option<Renderer>,
}

impl Backend for Offline {
    type Settings = ();
    type Error = ();

    fn setup(_: (), _: usize) -> Result<(Self, u32), ()> {
        Ok((Self { renderer: None }, SAMPLE_RATE))
    }

    fn start(&mut self, renderer: Renderer) -> Result<(), ()> {
        self.renderer = Some(renderer);
        Ok(())
    }
}

impl Offline {
    fn energy(&mut self, seconds: f32) -> f32 {
        let renderer = self.renderer.as_mut().unwrap();
        let mut samples = vec![0.0; (seconds * SAMPLE_RATE as f32) as usize * 2];
        for chunk in samples.chunks_mut(256) {
            renderer.on_start_processing();
            renderer.process(chunk, 2);
        }
        assert!(samples.iter().all(|s| s.is_finite()));
        samples.iter().map(|s| s * s).sum::<f32>() / samples.len() as f32
    }
}

fn tone() -> StaticSoundData {
    let frames: Vec<_> = (0..4800)
        .map(|i| Frame::from_mono((i as f32 * std::f32::consts::TAU / 120.0).sin() * 0.03))
        .collect();
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default().loop_region(..),
        slice: None,
    }
}

fn setup() -> (AudioManager<Offline>, Mixer, Settings) {
    let mut manager = AudioManager::<Offline>::new(AudioManagerSettings::default()).unwrap();
    let mut settings = Settings::default();
    settings.music_volume = 1.0;
    settings.sfx_volume = 1.0;
    settings.ui_volume = 1.0;
    settings.ambience_volume = 1.0;
    let mixer = Mixer::new(&mut manager, &settings).unwrap();
    (manager, mixer, settings)
}

fn route(mixer: &mut Mixer, index: usize, sound: StaticSoundData) {
    match index {
        0 => {
            mixer.music.play(sound).unwrap();
        }
        1 => mixer.play(Lane::Combat, sound),
        2 => mixer.play(Lane::Foreground, sound),
        3 => mixer.play(Lane::Ui, sound),
        4 => {
            mixer.ambience.play(sound).unwrap();
        }
        5 => mixer.play(Lane::Warning, sound),
        _ => unreachable!(),
    }
}

fn volume(settings: &mut Settings, index: usize) -> &mut f32 {
    match index {
        0 => &mut settings.music_volume,
        1 | 2 | 5 => &mut settings.sfx_volume,
        3 => &mut settings.ui_volume,
        4 => &mut settings.ambience_volume,
        _ => unreachable!(),
    }
}

#[test]
fn each_bus_mutes_its_dry_signal_and_reverb_tail_independently() {
    for index in 0..6 {
        let (mut manager, mut mixer, mut settings) = setup();
        mixer.set_scene(Scene::Boss);
        route(&mut mixer, index, tone());
        manager.backend_mut().energy(1.0);
        let full = manager.backend_mut().energy(0.2);
        assert!(full > 1e-5, "总线 {index} 没有输出");

        *volume(&mut settings, index) = 0.0;
        mixer.settings(&settings);
        mixer.update([0.0; 3], tween(0));
        // kira 仍在首个处理块插值以免爆音，等 10ms 后检查持续输出。
        manager.backend_mut().energy(0.01);
        assert!(manager.backend_mut().energy(0.2) < 1e-12, "总线 {index} 静音后仍漏音");

        // 其他总线静音不会影响当前总线；恢复时采用最新设置。
        settings.music_volume = 0.0;
        settings.sfx_volume = 0.0;
        settings.ui_volume = 0.0;
        settings.ambience_volume = 0.0;
        *volume(&mut settings, index) = 0.25;
        mixer.settings(&settings);
        mixer.update([0.0; 3], tween(0));
        manager.backend_mut().energy(0.01);
        let quarter = manager.backend_mut().energy(0.2);
        assert!(quarter > full * 0.02 && quarter < full * 0.12, "总线 {index} 音量耦合或未生效");
    }
}

#[test]
fn ducking_leaves_foreground_and_ui_audible_and_uses_latest_settings() {
    for index in 0..6 {
        let (mut manager, mut mixer, mut settings) = setup();
        route(&mut mixer, index, tone());
        mixer.update([-60.0; 3], tween(0));
        manager.backend_mut().energy(0.01);
        let energy = manager.backend_mut().energy(0.2);
        if matches!(index, 2 | 3 | 5) {
            assert!(energy > 1e-5, "高光或界面被自己的闪避吞掉");
        } else {
            assert!(energy < 1e-12, "普通声部没有闪避");
        }
        *volume(&mut settings, index) = 0.0;
        mixer.settings(&settings);
        mixer.update([0.0; 3], tween(0));
        manager.backend_mut().energy(0.01);
        assert!(manager.backend_mut().energy(0.2) < 1e-12, "闪避释放覆盖了用户静音");
    }
}

#[test]
fn combat_saturation_cannot_steal_foreground_voices() {
    let (mut manager, mut mixer, _) = setup();
    for _ in 0..80 {
        mixer.play(Lane::Combat, tone());
    }
    mixer.play(Lane::Foreground, tone());
    mixer.play(Lane::Warning, tone());
    assert_eq!(mixer.combat.num_sounds(), 64);
    assert_eq!(mixer.foreground.num_sounds(), 1);
    assert_eq!(mixer.warning.num_sounds(), 1);
    mixer.update([-60.0; 3], tween(0));
    assert!(manager.backend_mut().energy(0.2) > 1e-5);
}

#[test]
fn leaving_scene_cancels_delayed_cues() {
    let (mut manager, mut mixer, _) = setup();
    mixer.play(Lane::Foreground, tone().start_time(StartTime::Delayed(Duration::from_millis(400))));
    assert!(manager.backend_mut().energy(0.1) < 1e-12);
    mixer.clear_sounds();
    assert!(manager.backend_mut().energy(0.8) < 1e-12, "旧场景的延迟声串场");
}

#[test]
fn death_silence_removes_old_accents_then_allows_the_delayed_gong() {
    let (mut manager, mut mixer, _) = setup();
    mixer.play(Lane::Foreground, tone());
    manager.backend_mut().energy(0.1);
    mixer.clear_foreground();
    mixer.silence_foreground(true);
    mixer.play(Lane::Foreground, tone().start_time(StartTime::Delayed(Duration::from_millis(600))));
    manager.backend_mut().energy(0.05);
    assert!(manager.backend_mut().energy(0.5) < 1e-12, "旧高光或混响破坏静半拍");
    mixer.silence_foreground(false);
    manager.backend_mut().energy(0.06);
    assert!(manager.backend_mut().energy(0.1) > 1e-5, "延迟低锣被自身闪避吞掉");
}
