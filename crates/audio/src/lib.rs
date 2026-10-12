//! 音频层（docs/DESIGN.md 第 10 节）。只消费模拟事件，不影响模拟。
//!
//! 启动时用代码合成几种音色（不用音频文件），运行时只负责播放：
//! 命中是木鱼，击杀和闪避是古筝拨弦，拾取魂火音高一路爬升，受伤是低沉的闷响，升级是编钟。
//! 同类声音每帧限量，几百次命中也不会炸耳朵。程序生成的背景音乐在 M2 移植。

use std::f32::consts::TAU;
use std::sync::Arc;

use bevy::prelude::*;
use kira::sound::static_sound::{StaticSoundData, StaticSoundSettings};
use kira::{AudioManager, AudioManagerSettings, DefaultBackend, Frame};

use lantern_sim::{AppState, SimEvent, SimOutbox};

const SAMPLE_RATE: u32 = 48_000;

/// D 羽调五声音阶（D F G A C），从 D4 起两个八度。
const PENTATONIC: [f32; 10] = [293.66, 349.23, 392.0, 440.0, 523.25, 587.33, 698.46, 783.99, 880.0, 1046.5];

pub struct AudioPlugin;

impl Plugin for AudioPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, init_audio)
            .add_systems(OnEnter(AppState::Run), |mut audio: NonSendMut<Audio>| audio.start_run())
            .add_systems(Update, play_sim_events.run_if(in_state(AppState::Run)));
    }
}

/// kira 的后端在部分平台上不能跨线程传递，所以作为 NonSend 资源放在主线程。
pub struct Audio {
    manager: Option<AudioManager>,
    pluck: StaticSoundData,
    wood: StaticSoundData,
    thud: StaticSoundData,
    bell: StaticSoundData,
    /// 拾取魂火的音阶位置；停顿一会儿回到起点
    pickup_step: usize,
    pickup_idle: f32,
    kill_step: usize,
}

impl Audio {
    fn play(&mut self, sound: StaticSoundData) {
        let Some(manager) = &mut self.manager else { return };
        if let Err(e) = manager.play(sound) {
            warn!("播放失败：{e}");
        }
    }

    /// 以 D4 为基准合成的音色，按目标音高变速播放。
    fn note(&mut self, base: &StaticSoundData, hz: f32, volume_db: f32) {
        let rate = f64::from(hz / PENTATONIC[0]);
        let sound = base.playback_rate(rate).volume(volume_db);
        self.play(sound);
    }

    fn start_run(&mut self) {
        self.pickup_step = 0;
        self.kill_step = 0;
        let pluck = self.pluck.clone();
        self.note(&pluck, PENTATONIC[0], -4.0);
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
    world.insert_non_send(Audio {
        manager,
        pluck: pluck(PENTATONIC[0], 1.4),
        wood: woodblock(),
        thud: thud(),
        bell: bell(PENTATONIC[0], 2.2),
        pickup_step: 0,
        pickup_idle: 0.0,
        kill_step: 0,
    });
}

fn play_sim_events(time: Res<Time>, outbox: Res<SimOutbox>, mut audio: NonSendMut<Audio>) {
    audio.pickup_idle += time.delta_secs();
    if audio.pickup_idle > 0.6 {
        audio.pickup_step = 0;
    }
    // 同类声音每帧限量
    let (mut hits, mut kills, mut picks) = (0, 0, 0);
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { crit, .. } if hits < 2 => {
                hits += 1;
                let wood = audio.wood.clone();
                audio.note(
                    &wood,
                    if crit { PENTATONIC[2] } else { PENTATONIC[0] },
                    if crit { -8.0 } else { -14.0 },
                );
            }
            SimEvent::Kill { .. } if kills < 2 => {
                kills += 1;
                audio.kill_step = (audio.kill_step + 3) % 5;
                let hz = PENTATONIC[audio.kill_step] * 0.5;
                let pluck = audio.pluck.clone();
                audio.note(&pluck, hz, -12.0);
            }
            SimEvent::GemPicked { .. } if picks < 1 => {
                picks += 1;
                audio.pickup_idle = 0.0;
                let hz = PENTATONIC[audio.pickup_step.min(PENTATONIC.len() - 1)] * 2.0;
                audio.pickup_step = (audio.pickup_step + 1).min(PENTATONIC.len() - 1);
                let pluck = audio.pluck.clone();
                audio.note(&pluck, hz, -16.0);
            }
            SimEvent::Dash { .. } => {
                let pluck = audio.pluck.clone();
                audio.note(&pluck, PENTATONIC[3], -6.0);
            }
            SimEvent::PlayerHurt { .. } => {
                let thud = audio.thud.clone();
                audio.play(thud.volume(-4.0));
            }
            SimEvent::LevelUp { .. } => {
                let bell = audio.bell.clone();
                audio.note(&bell, PENTATONIC[5], -6.0);
            }
            SimEvent::PlayerDied => {
                let bell = audio.bell.clone();
                audio.note(&bell, PENTATONIC[0] * 0.5, -2.0);
            }
            _ => {}
        }
    }
}

fn sound(frames: Vec<Frame>) -> StaticSoundData {
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default(),
        slice: None,
    }
}

/// 简单的 xorshift 噪声，合成时用；固定种子，每次启动合成的音色一样。
struct Noise(u32);

impl Noise {
    fn next(&mut self) -> f32 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 17;
        self.0 ^= self.0 << 5;
        self.0 as f32 / u32::MAX as f32 * 2.0 - 1.0
    }
}

/// Karplus-Strong 拨弦：一段噪声在延迟线里反复低通衰减，听起来像古筝的弦。
fn pluck(hz: f32, secs: f32) -> StaticSoundData {
    let len = (SAMPLE_RATE as f32 / hz).round() as usize;
    let mut noise = Noise(0x2545_f491);
    let mut line: Vec<f32> = (0..len).map(|_| noise.next()).collect();
    let total = (SAMPLE_RATE as f32 * secs) as usize;
    let fade = SAMPLE_RATE as usize / 50;
    let frames = (0..total)
        .map(|i| {
            let j = i % len;
            let s = line[j];
            line[j] = 0.996 * 0.5 * (s + line[(j + 1) % len]);
            let tail = if i + fade > total { (total - i) as f32 / fade as f32 } else { 1.0 };
            Frame::from_mono(s * 0.35 * tail)
        })
        .collect();
    sound(frames)
}

/// 木鱼：短促的正弦加一点噪声的敲击声。
fn woodblock() -> StaticSoundData {
    let total = SAMPLE_RATE as usize / 10;
    let mut noise = Noise(0x1234_5678);
    let frames = (0..total)
        .map(|i| {
            let t = i as f32 / SAMPLE_RATE as f32;
            let env = (-t * 60.0).exp();
            let tone =
                (TAU * PENTATONIC[0] * 3.0 * t).sin() * 0.6 + (TAU * PENTATONIC[0] * 4.7 * t).sin() * 0.25;
            let click = noise.next() * (-t * 400.0).exp() * 0.4;
            Frame::from_mono((tone * env + click) * 0.5)
        })
        .collect();
    sound(frames)
}

/// 受伤：低沉的闷响（下滑的低频正弦加噪声）。
fn thud() -> StaticSoundData {
    let total = SAMPLE_RATE as usize * 3 / 10;
    let mut noise = Noise(0x0bad_cafe);
    let mut phase = 0.0f32;
    let frames = (0..total)
        .map(|i| {
            let t = i as f32 / SAMPLE_RATE as f32;
            let hz = 110.0 * (-t * 6.0).exp() + 50.0;
            phase += TAU * hz / SAMPLE_RATE as f32;
            let env = (-t * 12.0).exp();
            Frame::from_mono((phase.sin() * 0.8 + noise.next() * 0.15 * (-t * 30.0).exp()) * env * 0.7)
        })
        .collect();
    sound(frames)
}

/// 编钟：几个不成整数倍的泛音，各自衰减。
fn bell(hz: f32, secs: f32) -> StaticSoundData {
    let partials = [(1.0, 1.0, 1.2), (2.76, 0.5, 2.5), (5.4, 0.25, 4.0), (8.93, 0.12, 6.0)];
    let total = (SAMPLE_RATE as f32 * secs) as usize;
    let frames = (0..total)
        .map(|i| {
            let t = i as f32 / SAMPLE_RATE as f32;
            let attack = (t * 400.0).min(1.0);
            let s: f32 =
                partials.iter().map(|&(m, a, d)| (TAU * hz * m * t).sin() * a * (-t * d).exp()).sum();
            Frame::from_mono(s * attack * 0.25)
        })
        .collect();
    sound(frames)
}
