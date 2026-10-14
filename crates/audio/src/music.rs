//! 背景音乐（移植自网页版 audio/music.ts）：持续的低音 + 随机生成并逐渐变奏的五声旋律 + 随局势加强的鼓点。
//!
//! 按真实时间走（暂停时音乐不停，只是变闷）。每帧往前排 0.2 秒内要响的音，用延迟启动交给音频线程，
//! 节拍不受帧率影响。旋律的随机数用这一局的种子，同一局每次听到的旋律一样。

use std::time::Duration;

use kira::sound::static_sound::{StaticSoundData, StaticSoundHandle};
use kira::track::TrackHandle;
use kira::{Decibels, StartTime, Tween};

use lantern_core::Pcg32;

use crate::sfx::Instruments;
use crate::synth::{drone, pent};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MusicMode {
    None,
    Title,
    Play,
    Boss,
}

const LOOKAHEAD: f64 = 0.2;
const BASS: [i32; 4] = [0, 3, 2, 0];

pub struct Music {
    inst: Instruments,
    pub mode: MusicMode,
    /// 局势 0–2（Play 模式下鼓点逐级加强）
    pub intensity: u8,
    step: u64,
    bar: u64,
    /// 下一个八分音符的时刻（真实时间，秒）
    next: f64,
    rng: Pcg32,
    motif: [Option<i32>; 16],
    drone: StaticSoundData,
    drone_boss: StaticSoundData,
    drone_handle: Option<StaticSoundHandle>,
    drone_is_boss: bool,
    /// 上一次 tick 的时刻；用来把延迟换算成音频线程的时间
    now: f64,
}

/// 线性振幅换成分贝（播放时的音量）。
fn amp(v: f32) -> Decibels {
    Decibels(20.0 * v.max(1e-4).log10())
}

impl Music {
    pub fn new(inst: Instruments) -> Self {
        let mut m = Music {
            inst,
            mode: MusicMode::None,
            intensity: 0,
            step: 0,
            bar: 0,
            next: 0.0,
            rng: Pcg32::new(1, 9),
            motif: [None; 16],
            drone: drone(pent(-5), pent(-2) * 2f32.powf(4.0 / 1200.0)),
            drone_boss: drone(pent(-5), pent(-5) * 2f32.powf(6.0 / 12.0)),
            drone_handle: None,
            drone_is_boss: false,
            now: 0.0,
        };
        m.motif = m.make_motif(0.55);
        m
    }

    fn rand(&mut self) -> f32 {
        self.rng.next_f32()
    }

    /// 16 个八分音符的旋律动机：随机游走，留出呼吸。
    fn make_motif(&mut self, rest: f32) -> [Option<i32>; 16] {
        let mut out = [None; 16];
        let mut d = 10 + (self.rand() * 4.0) as i32;
        for (i, slot) in out.iter_mut().enumerate() {
            if self.rand() < rest || (i % 4 == 3 && self.rand() < 0.5) {
                continue;
            }
            d = (d + (self.rand() * 5.0) as i32 - 2).clamp(7, 17);
            *slot = Some(d);
        }
        out
    }

    fn mutate(&mut self) {
        for i in 0..16 {
            if self.rand() > 0.3 {
                continue;
            }
            self.motif[i] = match self.motif[i] {
                None => (self.rand() < 0.5).then(|| 10 + (self.rand() * 6.0) as i32),
                Some(n) => Some((n + (self.rand() * 5.0) as i32 - 2).clamp(7, 17)),
            };
        }
    }

    fn bpm(&self) -> f64 {
        match self.mode {
            MusicMode::None => 120.0,
            MusicMode::Title => 66.0,
            MusicMode::Play => 84.0 + f64::from(self.intensity) * 5.0,
            MusicMode::Boss => 104.0,
        }
    }

    /// 切换模式；seed 用于让同一局的旋律可复现。
    pub fn set_mode(&mut self, mode: MusicMode, seed: Option<u64>, track: Option<&mut TrackHandle>) {
        if mode == self.mode && seed.is_none() {
            return;
        }
        let was = self.mode;
        self.mode = mode;
        if let Some(s) = seed {
            self.rng = Pcg32::new(s, 9);
        }
        if mode != MusicMode::Boss || was == MusicMode::None {
            self.motif = self.make_motif(if mode == MusicMode::Title { 0.55 } else { 0.35 });
        }
        self.step = 0;
        self.bar = 0;
        self.next = self.now + 0.1;
        self.update_drone(track);
    }

    fn update_drone(&mut self, track: Option<&mut TrackHandle>) {
        let (level, boss) = match self.mode {
            MusicMode::None => (0.0, self.drone_is_boss),
            MusicMode::Title => (0.05, false),
            MusicMode::Play => (0.04, false),
            MusicMode::Boss => (0.07, true),
        };
        self.set_drone(level, boss, track);
    }

    /// 持续音：淡入淡出；夜主出场时换成三全音，更不安。
    fn set_drone(&mut self, level: f32, boss: bool, track: Option<&mut TrackHandle>) {
        let fade = Tween { duration: Duration::from_millis(1600), ..Default::default() };
        if boss != self.drone_is_boss || self.drone_handle.is_none() {
            if let Some(h) = &mut self.drone_handle {
                h.stop(fade);
            }
            self.drone_handle = None;
            self.drone_is_boss = boss;
            if level > 0.0
                && let Some(t) = track
            {
                let data = if boss { &self.drone_boss } else { &self.drone };
                self.drone_handle = t.play(data.volume(Decibels::SILENCE)).ok();
            }
        }
        if let Some(h) = &mut self.drone_handle {
            h.set_volume(if level > 0.0 { amp(level * 8.0) } else { Decibels::SILENCE }, fade);
        }
    }

    pub fn tick(&mut self, now: f64, mut track: Option<&mut TrackHandle>) {
        self.now = now;
        if self.mode == MusicMode::None || track.is_none() {
            return;
        }
        // 启动时没有设备也会切换音乐模式；轨道恢复后补上当时未能启动的持续音。
        if self.drone_handle.is_none() {
            self.update_drone(track.as_deref_mut());
        }
        if self.next < now {
            self.next = now + 0.05;
        }
        while self.next < now + LOOKAHEAD {
            let at = self.next - now;
            self.play_step(at, track.as_deref_mut());
            self.next += 60.0 / self.bpm() / 2.0;
            self.step += 1;
        }
    }

    fn note(track: &mut Option<&mut TrackHandle>, data: &StaticSoundData, at: f64, rate: f32, vol: f32) {
        if let Some(t) = track {
            let sound = data
                .playback_rate(f64::from(rate))
                .volume(amp(vol))
                .start_time(StartTime::Delayed(Duration::from_secs_f64(at.max(0.0))));
            let _ = t.play(sound);
        }
    }

    fn pluck(&self, track: &mut Option<&mut TrackHandle>, at: f64, note: i32, vol: f32, decay: f32) {
        let i = self.inst.pluck_decays.iter().position(|&d| d >= decay).unwrap_or(2);
        Self::note(track, &self.inst.pluck[i], at, pent(note) / pent(0), vol);
    }

    fn play_step(&mut self, at: f64, track: Option<&mut TrackHandle>) {
        let mut track = track;
        let s = self.step % 16;
        if s == 0 {
            self.bar += 1;
            if self.bar.is_multiple_of(4) {
                if self.rand() < 0.35 {
                    self.motif = self.make_motif(if self.mode == MusicMode::Title { 0.55 } else { 0.35 });
                } else {
                    self.mutate();
                }
            }
        }
        let mode = self.mode;
        let title = mode == MusicMode::Title;
        let boss = mode == MusicMode::Boss;
        let lvl: i32 = match mode {
            MusicMode::Boss => 3,
            MusicMode::Title | MusicMode::None => -1,
            MusicMode::Play => i32::from(self.intensity),
        };
        // 网页版的音量是 Web Audio 的线性增益，这里整体放大到相近的响度
        const GAIN: f32 = 2.2;
        // 低音拨弦
        if s.is_multiple_of(8) {
            let root = BASS[((self.step / 8) % 4) as usize] + if boss { -1 } else { 0 };
            self.pluck(&mut track, at, root, if title { 0.12 } else { 0.15 } * GAIN, 1.6);
        }
        // 旋律
        if let Some(n) = self.motif[s as usize]
            && (!title || s.is_multiple_of(2))
        {
            let n = n + if boss { -1 } else { 0 };
            self.pluck(&mut track, at, n, 0.1 * GAIN, if title { 1.8 } else { 1.1 });
        }
        // 打击乐随局势加强
        let inst = &self.inst;
        if lvl >= 1 && s.is_multiple_of(2) {
            let (vol, pitch) = if s.is_multiple_of(8) { (0.08, 820.0) } else { (0.045, 1050.0) };
            Self::note(&mut track, &inst.wood, at, pitch / 900.0, vol * GAIN);
        }
        if lvl >= 2 && (s == 0 || s == 8) {
            Self::note(&mut track, &inst.drum, at, 1.0, 0.3 * GAIN);
        }
        if lvl >= 3 {
            if s == 6 || s == 12 || s == 14 {
                Self::note(&mut track, &inst.drum, at, 0.85, 0.26 * GAIN);
            }
            if s % 2 == 1 {
                Self::note(&mut track, &inst.wood, at, 1400.0 / 900.0, 0.03 * GAIN);
            }
            if s == 0 && self.bar.is_multiple_of(4) {
                Self::note(&mut track, &inst.gong, at, 1.0, 0.12 * GAIN);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use kira::backend::mock::MockBackend;
    use kira::track::TrackBuilder;
    use kira::{AudioManager, AudioManagerSettings};

    #[test]
    fn output_recovery_resumes_current_music_without_reseeding_or_catch_up() {
        let mut music = Music::new(Instruments::new());
        let mut manager = AudioManager::<MockBackend>::new(AudioManagerSettings::default()).unwrap();
        for mode in [MusicMode::Title, MusicMode::Play, MusicMode::Boss] {
            music.set_mode(mode, Some(42), None);
            music.intensity = 2;
            let motif = music.motif;
            let rng = music.rng.clone();
            let step = music.step;
            // 无设备运行很久，恢复时只安排眼前的一拍，不补播静音期间的音符。
            music.tick(music.now + 3600.0, None);
            assert!(music.drone_handle.is_none());
            let mut track = manager.add_sub_track(TrackBuilder::new()).unwrap();
            music.tick(music.now + 0.1, Some(&mut track));
            assert!(music.drone_handle.take().is_some());
            assert!(track.num_sounds() >= 2);
            assert_eq!(music.mode, mode);
            assert_eq!(music.intensity, 2);
            assert_eq!(music.motif, motif);
            assert_eq!(music.rng, rng);
            assert_eq!(music.step, step + 1);
        }

        music.set_mode(MusicMode::None, None, None);
        let mut track = manager.add_sub_track(TrackBuilder::new()).unwrap();
        music.tick(music.now + 0.1, Some(&mut track));
        assert!(music.drone_handle.is_none());
        assert_eq!(track.num_sounds(), 0);
    }
}
