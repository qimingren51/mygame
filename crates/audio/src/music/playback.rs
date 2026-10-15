//! 在音频线程读取共享曲式采样：不合成、不分配、不加锁，也不依赖游戏帧补排下一段。

use std::convert::Infallible;
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicU64, Ordering},
};

use kira::command::{CommandReader, CommandWriter, command_writer_and_reader};
use kira::info::{Info, WhenToStart};
use kira::sound::{Sound, SoundData};
use kira::{Frame, Panning, Parameter, StartTime, interpolate_frame};

use super::{
    FRAMES, SAMPLE_RATE, fade,
    score::{CYCLE_FRAMES, Score},
};

pub(super) struct StemData {
    pub score: Arc<Score>,
    pub layer: usize,
    pub dawn: bool,
    pub start: StartTime,
    pub pan: Panning,
}

struct Shared {
    position: AtomicU64,
    stopped: AtomicBool,
    removed: AtomicBool,
}

pub(super) struct StemHandle {
    stop: CommandWriter<f64>,
    shared: Arc<Shared>,
}

impl StemHandle {
    pub(super) fn stop(&mut self, seconds: f64) {
        self.stop.write(seconds);
    }
    #[cfg(test)]
    pub(super) fn position(&self) -> f64 {
        f64::from_bits(self.shared.position.load(Ordering::Relaxed))
    }
    #[cfg(test)]
    pub(super) fn stopped(&self) -> bool {
        self.shared.stopped.load(Ordering::Relaxed)
    }
}

impl Drop for StemHandle {
    fn drop(&mut self) {
        // 控制端消失时结束无限循环；不覆盖调用者已经发送的淡出时长。
        if Arc::strong_count(&self.shared) > 1 {
            self.shared.removed.store(true, Ordering::Relaxed);
        }
    }
}

struct Stem {
    data: StemData,
    stop: CommandReader<f64>,
    shared: Arc<Shared>,
    position: f64,
    envelope: Parameter<f32>,
    stopping: bool,
    finished: bool,
    started: bool,
    pan: Frame,
}

impl SoundData for StemData {
    type Error = Infallible;
    type Handle = StemHandle;

    fn into_sound(self) -> Result<(Box<dyn Sound>, StemHandle), Infallible> {
        let (stop_write, stop_read) = command_writer_and_reader();
        let shared = Arc::new(Shared {
            position: AtomicU64::new(0),
            stopped: AtomicBool::new(false),
            removed: AtomicBool::new(false),
        });
        let pan = Frame::from_mono(1.0).panned(self.pan);
        let mut envelope = Parameter::new(0.0.into(), 0.0);
        envelope.set(1.0.into(), fade(StartTime::Immediate, 0.02));
        let sound = Stem {
            data: self,
            stop: stop_read,
            shared: Arc::clone(&shared),
            position: 0.0,
            envelope,
            stopping: false,
            finished: false,
            started: false,
            pan,
        };
        Ok((Box::new(sound), StemHandle { stop: stop_write, shared }))
    }
}

impl Sound for Stem {
    fn on_start_processing(&mut self) {
        let stop = self.stop.read();
        if let Some(seconds) = stop {
            self.envelope.set(0.0.into(), fade(StartTime::Immediate, seconds));
            self.stopping = true;
        } else if self.shared.removed.load(Ordering::Relaxed) && !self.stopping {
            self.envelope.set(0.0.into(), fade(StartTime::Immediate, 0.06));
            self.stopping = true;
        }
        self.shared.position.store((self.position / f64::from(SAMPLE_RATE)).to_bits(), Ordering::Relaxed);
    }

    fn process(&mut self, out: &mut [Frame], dt: f64, info: &Info) {
        out.fill(Frame::ZERO);
        if self.finished {
            return;
        }
        if !self.started {
            let ready = match &mut self.data.start {
                StartTime::Immediate => true,
                StartTime::ClockTime(at) => match info.when_to_start(*at) {
                    WhenToStart::Now => true,
                    WhenToStart::Later => false,
                    WhenToStart::Never => {
                        self.finished = true;
                        false
                    }
                },
                StartTime::Delayed(remaining) => {
                    *remaining =
                        remaining.saturating_sub(std::time::Duration::from_secs_f64(dt * out.len() as f64));
                    remaining.is_zero()
                }
            };
            // 尚未开始的旧曲也必须响应 stop，否则天明或新局后会幽灵般响起。
            if self.stopping {
                self.finished = true;
            }
            if !ready || self.finished {
                if self.finished {
                    self.shared.stopped.store(true, Ordering::Relaxed);
                }
                return;
            }
            self.started = true;
        }
        let count = out.len();
        let completed = self.envelope.update(dt * count as f64, info);
        let length = if self.data.dawn { FRAMES } else { CYCLE_FRAMES } as f64;
        for (i, frame) in out.iter_mut().enumerate() {
            if self.position >= length {
                if self.data.dawn {
                    self.finished = true;
                    break;
                }
                self.position %= length;
            }
            let index = self.position.floor() as i64;
            let sample = |offset| {
                Frame::from_mono(self.data.score.sample(self.data.layer, index + offset, self.data.dawn))
            };
            let value =
                interpolate_frame(sample(-1), sample(0), sample(1), sample(2), self.position.fract() as f32)
                    .left;
            *frame = self.pan * (value * self.envelope.interpolated_value((i + 1) as f64 / count as f64));
            self.position += dt * f64::from(SAMPLE_RATE);
        }
        if completed && self.stopping {
            self.finished = true;
        }
        if self.finished {
            self.shared.stopped.store(true, Ordering::Relaxed);
        }
    }

    fn finished(&self) -> bool {
        self.finished
    }
}

#[cfg(test)]
mod tests {
    use super::super::score::test_score;
    use super::*;
    use kira::info::MockInfoBuilder;

    #[test]
    fn actual_playback_follows_all_section_boundaries_and_loops_only_after_three_minutes() {
        let score = test_score();
        let (mut sound, handle) = StemData {
            score: Arc::clone(&score),
            layer: 1,
            dawn: false,
            start: StartTime::Immediate,
            pan: Panning::CENTER,
        }
        .into_sound()
        .unwrap();
        let info = MockInfoBuilder::new().build();
        let mut block = [Frame::ZERO; 128];
        // 穿过完整曲式及下一轮第一句，每个输出采样必须来自该时刻应奏的段落。
        for start in (0..CYCLE_FRAMES + FRAMES / 2).step_by(block.len()) {
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
            for (offset, frame) in block.iter().enumerate() {
                let index = start + offset;
                if index >= 1024 {
                    assert!(
                        (frame.left - score.sample(1, index as i64, false)).abs() < 1e-6,
                        "采样 {index} 提前或推迟了曲式边界"
                    );
                }
            }
        }
        assert!(!handle.stopped());
        drop(handle);
        sound.on_start_processing();
        for _ in 0..30 {
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
        }
        assert!(sound.finished(), "丢弃控制端必须释放无限循环声部");
    }

    #[test]
    fn dawn_supports_other_device_rates_and_cancels_queued_starts() {
        let info = MockInfoBuilder::new().build();
        for rate in [44_100, 96_000] {
            let (mut sound, handle) = StemData {
                score: test_score(),
                layer: 2,
                dawn: true,
                start: StartTime::Immediate,
                pan: Panning::CENTER,
            }
            .into_sound()
            .unwrap();
            let mut block = [Frame::ZERO; 128];
            let blocks = (super::super::THEME * f64::from(rate) / 128.0).ceil() as usize;
            for _ in 0..blocks {
                sound.on_start_processing();
                sound.process(&mut block, 1.0 / f64::from(rate), &info);
            }
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(rate), &info);
            assert!(handle.stopped());
            assert!((handle.position() - super::super::THEME).abs() < 0.0001);
        }
        let (mut sound, mut handle) = StemData {
            score: test_score(),
            layer: 1,
            dawn: false,
            start: StartTime::Delayed(std::time::Duration::from_secs(5)),
            pan: Panning::CENTER,
        }
        .into_sound()
        .unwrap();
        handle.stop(0.06);
        sound.on_start_processing();
        assert_eq!(sound.process_one(1.0 / 48_000.0, &info), Frame::ZERO);
        assert!(sound.finished() && handle.stopped());
    }
}
