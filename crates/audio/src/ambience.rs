//! 四种低声压的环境底层，循环接缝交叠，换场交叉淡化。
//!
//! 采样按单声道 16 位存（每种约 1.1 MiB，立体声浮点要 4.4 MiB）；播放时右声道取 17 毫秒前的
//! 采样并略轻一点，展开成立体声。

use std::convert::Infallible;
use std::sync::Arc;
use std::time::Duration;

use kira::command::{CommandReader, CommandWriter, command_writer_and_reader};
use kira::info::Info;
use kira::sound::{Sound, SoundData};
use kira::track::TrackHandle;
use kira::{Easing, Frame, Parameter, StartTime, Tween, interpolate_frame};

use crate::space::Scene;
use crate::synth::{Buf, FilterKind, NoiseOpts, SAMPLE_RATE};

/// 换场时旧的淡出、新的淡入（秒）。
const CROSSFADE: f64 = 1.2;
/// 右声道比左声道晚的采样数（17 毫秒）。
const DELAY: i64 = SAMPLE_RATE as i64 * 17 / 1000;

/// 一段循环的环境声：单声道 16 位，`gain` 还原到原来的电平。
struct Bed {
    pcm: Box<[i16]>,
    gain: f32,
}

impl Bed {
    fn at(&self, i: i64) -> f32 {
        f32::from(self.pcm[i.rem_euclid(self.pcm.len() as i64) as usize]) * self.gain
    }

    /// 循环位置 `pos`（采样，可带小数）处的一帧。
    fn frame(&self, pos: f64) -> Frame {
        let i = pos.floor() as i64;
        let x = pos.fract() as f32;
        let cubic = |i: i64| {
            let s = |k: i64| Frame::from_mono(self.at(i + k));
            interpolate_frame(s(-1), s(0), s(1), s(2), x).left
        };
        Frame::new(cubic(i), cubic(i - DELAY) * 0.94)
    }
}

pub(crate) struct Ambience {
    beds: [Arc<Bed>; 4],
    current: Option<Scene>,
    handle: Option<BedHandle>,
}

impl Ambience {
    pub fn new() -> Self {
        Self { beds: Scene::ALL.map(|s| Arc::new(render(s))), current: None, handle: None }
    }

    pub fn set_scene(&mut self, scene: Scene, track: Option<&mut TrackHandle>) {
        if self.current == Some(scene) {
            return;
        }
        self.current = Some(scene);
        if let Some(mut handle) = self.handle.take() {
            handle.stop(CROSSFADE);
        }
        if let Some(track) = track {
            match track.play(BedData { bed: Arc::clone(&self.beds[scene as usize]), fade_in: CROSSFADE }) {
                Ok(handle) => self.handle = Some(handle),
                Err(error) => bevy::log::warn!("环境声播放失败：{error}"),
            }
        }
    }

    #[cfg(test)]
    pub(crate) fn pcm_bytes(&self) -> usize {
        self.beds.iter().map(|b| b.pcm.len() * size_of::<i16>()).sum()
    }
}

fn fade(secs: f64) -> Tween {
    Tween {
        start_time: StartTime::Immediate,
        duration: Duration::from_secs_f64(secs),
        easing: Easing::InOutPowi(2),
    }
}

struct BedData {
    bed: Arc<Bed>,
    fade_in: f64,
}

/// 控制端：`stop` 淡出；丢掉控制端时也很快淡出，不留无限循环。
struct BedHandle {
    stop: CommandWriter<f64>,
    stopping: bool,
}

impl BedHandle {
    fn stop(&mut self, secs: f64) {
        self.stopping = true;
        self.stop.write(secs);
    }
}

impl Drop for BedHandle {
    fn drop(&mut self) {
        if !self.stopping {
            self.stop.write(0.06);
        }
    }
}

struct BedVoice {
    bed: Arc<Bed>,
    stop: CommandReader<f64>,
    position: f64,
    envelope: Parameter<f32>,
    stopping: bool,
    finished: bool,
}

impl SoundData for BedData {
    type Error = Infallible;
    type Handle = BedHandle;

    fn into_sound(self) -> Result<(Box<dyn Sound>, BedHandle), Infallible> {
        let (writer, reader) = command_writer_and_reader();
        let mut envelope = Parameter::new(0.0.into(), 0.0);
        envelope.set(1.0.into(), fade(self.fade_in));
        let voice = BedVoice {
            bed: self.bed,
            stop: reader,
            position: 0.0,
            envelope,
            stopping: false,
            finished: false,
        };
        Ok((Box::new(voice), BedHandle { stop: writer, stopping: false }))
    }
}

impl Sound for BedVoice {
    fn on_start_processing(&mut self) {
        if let Some(secs) = self.stop.read() {
            self.envelope.set(0.0.into(), fade(secs));
            self.stopping = true;
        }
    }

    fn process(&mut self, out: &mut [Frame], dt: f64, info: &Info) {
        if self.finished {
            out.fill(Frame::ZERO);
            return;
        }
        let count = out.len();
        let done = self.envelope.update(dt * count as f64, info);
        let len = self.bed.pcm.len() as f64;
        for (i, frame) in out.iter_mut().enumerate() {
            let gain = self.envelope.interpolated_value((i + 1) as f64 / count as f64);
            *frame = self.bed.frame(self.position) * gain;
            // 设备采样率不同时按时间推进
            self.position = (self.position + dt * f64::from(SAMPLE_RATE)) % len;
        }
        if done && self.stopping {
            self.finished = true;
        }
    }

    fn finished(&self) -> bool {
        self.finished
    }
}

fn render(scene: Scene) -> Bed {
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
    let peak = b.data[..len].iter().fold(0.0_f32, |m, s| m.max(s.abs())).max(1e-6);
    let pcm = b.data[..len].iter().map(|s| (s / peak * 32767.0).round() as i16).collect();
    Bed { pcm, gain: peak / 32767.0 }
}

#[cfg(test)]
mod tests {
    use super::*;
    use kira::info::MockInfoBuilder;

    fn play(bed: Arc<Bed>, blocks: usize) -> (Box<dyn Sound>, BedHandle, Vec<Frame>) {
        let (mut sound, handle) = BedData { bed, fade_in: 0.0 }.into_sound().unwrap();
        let info = MockInfoBuilder::new().build();
        let mut out = Vec::new();
        let mut block = [Frame::ZERO; 256];
        for _ in 0..blocks {
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
            out.extend_from_slice(&block);
        }
        (sound, handle, out)
    }

    #[test]
    fn beds_are_stereo_quiet_and_seamless() {
        for scene in Scene::ALL {
            let bed = Arc::new(render(scene));
            let peak = bed.pcm.iter().map(|&s| f32::from(s).abs() * bed.gain).fold(0.0, f32::max);
            assert!((0.001..0.2).contains(&peak), "{scene:?}: {peak}");
            let seam = bed.at(0) - bed.at(-1);
            assert!(seam.abs() < 0.005, "{scene:?} 循环爆音");
            // 播放穿过循环边界：立体声、有限、没有跳变
            let blocks = bed.pcm.len() / 256 + 8;
            let (_, _, out) = play(Arc::clone(&bed), blocks);
            assert!(out.iter().any(|f| (f.left - f.right).abs() > 1e-4));
            assert!(out.iter().all(|f| f.left.is_finite() && f.right.is_finite()));
            let jump = out.windows(2).map(|w| (w[1].left - w[0].left).abs()).fold(0.0, f32::max);
            assert!(jump < 0.02, "{scene:?} 采样跳变 {jump}");
        }
    }

    #[test]
    fn stopping_or_dropping_the_handle_fades_out() {
        let bed = Arc::new(render(Scene::Night));
        let info = MockInfoBuilder::new().build();
        let mut block = [Frame::ZERO; 256];
        let (mut sound, mut handle, _) = play(Arc::clone(&bed), 4);
        handle.stop(0.05);
        for _ in 0..20 {
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
        }
        assert!(sound.finished());
        let (mut sound, handle, _) = play(bed, 4);
        drop(handle);
        for _ in 0..20 {
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
        }
        assert!(sound.finished(), "丢掉控制端必须结束无限循环");
    }
}
