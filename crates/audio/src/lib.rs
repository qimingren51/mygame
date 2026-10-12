//! 音频层（docs/DESIGN.md 第 10 节）。只消费模拟事件，不影响模拟。
//!
//! M0 只合成一个古筝式拨弦音，在出发和闪避时播放，用来确认各平台的音频输出正常。
//! 完整的乐器、音序器和混音总线在 M1、M2 移植。

use std::sync::Arc;

use bevy::prelude::*;
use kira::sound::static_sound::{StaticSoundData, StaticSoundSettings};
use kira::{AudioManager, AudioManagerSettings, DefaultBackend, Frame};

use lantern_sim::{AppState, SimEvent, SimOutbox};

const SAMPLE_RATE: u32 = 48_000;

pub struct AudioPlugin;

impl Plugin for AudioPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, init_audio)
            .add_systems(OnEnter(AppState::Run), |mut audio: NonSendMut<Audio>| audio.play(Note::D4))
            .add_systems(Update, play_sim_events.run_if(in_state(AppState::Run)));
    }
}

#[derive(Clone, Copy)]
enum Note {
    D4,
    A4,
}

impl Note {
    fn hz(self) -> f32 {
        match self {
            Note::D4 => 293.66,
            Note::A4 => 440.0,
        }
    }
}

/// kira 的后端在部分平台上不能跨线程传递，所以作为 NonSend 资源放在主线程。
pub struct Audio {
    manager: Option<AudioManager>,
    plucks: Vec<StaticSoundData>,
}

impl Audio {
    fn play(&mut self, note: Note) {
        let Some(manager) = &mut self.manager else { return };
        if let Err(e) = manager.play(self.plucks[note as usize].clone()) {
            warn!("播放失败：{e}");
        }
    }
}

fn init_audio(world: &mut World) {
    let manager = match AudioManager::<DefaultBackend>::new(AudioManagerSettings::default()) {
        Ok(m) => Some(m),
        Err(e) => {
            warn!("没有可用的音频输出，静音运行：{e}");
            None
        }
    };
    let plucks = [Note::D4, Note::A4].map(|n| pluck(n.hz(), 1.6)).to_vec();
    world.insert_non_send(Audio { manager, plucks });
}

fn play_sim_events(outbox: Res<SimOutbox>, mut audio: NonSendMut<Audio>) {
    for ev in &outbox.0 {
        // 其他事件的音效在 M1 后半移植（命中、击杀、拾取、受伤）
        if let SimEvent::Dash { .. } = ev {
            audio.play(Note::A4);
        }
    }
}

/// Karplus-Strong 拨弦：一段噪声在延迟线里反复低通衰减，听起来像古筝的弦。
fn pluck(hz: f32, secs: f32) -> StaticSoundData {
    let len = (SAMPLE_RATE as f32 / hz).round() as usize;
    let mut seed = 0x2545_f491_u32;
    let mut noise = || {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        seed as f32 / u32::MAX as f32 * 2.0 - 1.0
    };
    let mut line: Vec<f32> = (0..len).map(|_| noise()).collect();
    let total = (SAMPLE_RATE as f32 * secs) as usize;
    let fade = SAMPLE_RATE as usize / 50;
    let mut frames = Vec::with_capacity(total);
    for i in 0..total {
        let j = i % len;
        let next = line[(j + 1) % len];
        let s = line[j];
        line[j] = 0.996 * 0.5 * (s + next);
        let tail = if i + fade > total { (total - i) as f32 / fade as f32 } else { 1.0 };
        frames.push(Frame::from_mono(s * 0.35 * tail));
    }
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default(),
        slice: None,
    }
}
