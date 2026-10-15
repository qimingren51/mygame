//! 青丘主题：E 角调式，四小节问句、四小节答句，共享六条同步分轨。
//!
//! 后台合成长曲式采样库；音频线程按采样位置轮转，主线程只在乐句边界调配器。
//! 天明从主题开头完整播放一次，结算和返回标题都不会截掉答句。

use std::sync::{Arc, mpsc};
use std::time::Duration;

use kira::clock::{ClockHandle, ClockTime};
use kira::track::{TrackBuilder, TrackHandle};
use kira::{Decibels, Easing, Panning, StartTime, Tween};

use crate::synth::SAMPLE_RATE;

mod playback;
mod score;

use playback::{StemData, StemHandle};
use score::Score;

// 约 84 BPM、4/4 拍。八分音符取整采样数，循环长度和音频时钟不会逐圈漂移。
const STEP_FRAMES: usize = 17_143;
const STEP: f64 = STEP_FRAMES as f64 / SAMPLE_RATE as f64;
const BAR: f64 = STEP * 8.0;
const PHRASE: f64 = BAR * 4.0;
const THEME: f64 = PHRASE * 2.0;
const FRAMES: usize = STEP_FRAMES * 64;
const LAYERS: usize = 6;
const LEAD: f64 = 0.04;
/// 低锣在 0.6 秒、晨钟在 1.6 秒，等晨鸟说完再让主题进入。
pub const DAWN_DELAY: f64 = 5.6;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MusicMode {
    #[default]
    None,
    Title,
    Explore,
    Siege,
    Boss,
    Dawn,
}

impl MusicMode {
    /// 低音持续层、主题拨弦、箫、行进织体、战鼓、晨钟；密度增加时给主旋律留出余量。
    fn levels(self) -> [f32; LAYERS] {
        match self {
            Self::None => [0.0; LAYERS],
            Self::Title => [0.48, 0.72, 0.18, 0.0, 0.0, 0.0],
            Self::Explore => [0.65, 0.86, 0.48, 0.0, 0.0, 0.0],
            Self::Siege => [0.72, 0.82, 0.58, 0.85, 0.52, 0.0],
            Self::Boss => [0.82, 0.78, 0.78, 1.0, 1.0, 0.15],
            Self::Dawn => [0.75, 0.92, 1.0, 0.3, 0.3, 1.0],
        }
    }
}

/// 振幅转分贝；六条分轨最终一起经过原音乐总线的音量、低通和混响发送。
fn amp(v: f32) -> Decibels {
    if v <= 0.0 { Decibels::SILENCE } else { Decibels(20.0 * v.log10()) }
}

fn fade(at: StartTime, secs: f64) -> Tween {
    Tween { start_time: at, duration: Duration::from_secs_f64(secs), easing: Easing::InOutPowi(2) }
}

/// 输入来自只读模拟快照；远处数量的权重低于近身妖物，时间本身不能触发围攻。
#[derive(Clone, Copy, Default)]
pub struct PressureInput {
    pub enemies: usize,
    pub nearby: usize,
    pub hp_ratio: f32,
    pub progress: f32,
}

impl PressureInput {
    fn value(self, hurt: f32) -> f32 {
        (0.25 * (self.enemies as f32 / 160.0).min(1.0)
            + 0.45 * (self.nearby as f32 / 18.0).min(1.0)
            + 0.16 * (1.0 - self.hp_ratio.clamp(0.0, 1.0))
            + 0.09 * self.progress.clamp(0.0, 1.0)
            + 0.22 * hurt)
            .clamp(0.0, 1.0)
    }
}

#[derive(Default)]
pub struct Pressure {
    smoothed: f32,
    hurt: f32,
    siege: bool,
}

impl Pressure {
    pub fn hurt(&mut self) {
        self.hurt = (self.hurt + 0.55).min(1.0);
    }

    pub fn update(&mut self, input: PressureInput, dt: f32) -> MusicMode {
        // 升压约 1.2 秒、释压约 4 秒；受伤记忆约 3 秒消退。暂停时调用方冻结快照。
        let target = input.value(self.hurt);
        let tau = if target > self.smoothed { 1.2 } else { 4.0 };
        self.smoothed += (target - self.smoothed) * (1.0 - (-dt.max(0.0) / tau).exp());
        self.hurt *= (-dt.max(0.0) / 3.0).exp();
        if self.smoothed >= 0.56 {
            self.siege = true;
        }
        if self.smoothed <= 0.36 {
            self.siege = false;
        }
        if self.siege { MusicMode::Siege } else { MusicMode::Explore }
    }
}

#[derive(Clone, Copy, Debug)]
struct Transition {
    mode: MusicMode,
    at: f64,
}

/// 纯调度状态，与声卡无关；已经交给音频线程的边界不再受渲染帧率影响。
#[derive(Default)]
struct Conductor {
    mode: MusicMode,
    desired: MusicMode,
    origin: f64,
    pending: Option<Transition>,
    /// 天明含前奏等待和整段主题；RunOver 重复通知不能重启。
    dawn_end: Option<f64>,
    dawn_done: bool,
}

impl Conductor {
    fn begin(&mut self, mode: MusicMode, at: f64) {
        *self = Self { mode, desired: mode, origin: at, ..Self::default() };
    }

    fn dawn(&mut self, now: f64) -> Option<f64> {
        if self.dawn_end.is_some() || self.dawn_done {
            return None;
        }
        let at = now + DAWN_DELAY;
        self.begin(MusicMode::Dawn, at);
        self.dawn_end = Some(at + THEME);
        Some(at)
    }

    fn request(&mut self, mode: MusicMode) {
        if self.dawn_end.is_some() || self.dawn_done {
            // 自动局势不能覆盖天明；返回标题的请求等完整主题收尾后兑现。
            if mode == MusicMode::Title {
                self.desired = mode;
            }
        } else {
            self.desired = mode;
        }
    }

    fn advance(&mut self, now: f64) -> Option<Transition> {
        if let Some(end) = self.dawn_end {
            if now < end {
                return None;
            }
            self.dawn_end = None;
            self.dawn_done = true;
            self.mode = MusicMode::None;
            if self.desired != MusicMode::Title {
                self.desired = MusicMode::None;
            }
        }
        if let Some(p) = self.pending {
            if now >= p.at {
                self.mode = p.mode;
                self.pending = None;
            } else if p.mode == self.desired {
                return None;
            }
        }
        if self.mode == self.desired && self.pending.is_none() {
            return None;
        }
        // 边界尚未到时可以覆盖音频线程中的音量指令：夜主不必等已排队的四小节，
        // 压力退去也能撤销围攻。撤销使用当前配器作为目标，实际音量不会跳动。
        let quantum = if self.desired == MusicMode::Boss { BAR } else { PHRASE };
        let at = self.origin + ((now + LEAD - self.origin) / quantum).ceil().max(0.0) * quantum;
        let transition = Transition { mode: self.desired, at };
        self.pending = Some(transition);
        Some(transition)
    }
}

pub struct Music {
    score: Option<Arc<Score>>,
    loading: Option<mpsc::Receiver<Arc<Score>>>,
    waiting: Option<(MusicMode, f64)>,
    tracks: [Option<TrackHandle>; LAYERS],
    voices: [Option<StemHandle>; LAYERS],
    clock: Option<ClockHandle>,
    conductor: Conductor,
    pub pressure: Pressure,
}

impl Music {
    pub fn new(clock: Option<ClockHandle>, mut parent: Option<&mut TrackHandle>) -> Self {
        if clock.is_none() {
            parent = None;
        }
        let tracks = std::array::from_fn(|_| {
            parent
                .as_deref_mut()
                .and_then(|t| t.add_sub_track(TrackBuilder::new().volume(Decibels::SILENCE)).ok())
        });
        // 没有声卡时不合成；工作线程只持有采样，不触碰 Bevy 或音频后端。
        // 系统不给开线程时只是没有音乐，不让游戏崩。
        let loading = tracks.iter().any(Option::is_some).then(|| {
            let (tx, rx) = mpsc::channel();
            std::thread::Builder::new()
                .name("music".into())
                .spawn(move || {
                    let _ = tx.send(Arc::new(Score::new()));
                })
                .map_err(|e| bevy::log::warn!("开不了合成音乐的线程：{e}"))
                .ok()
                .map(|_| rx)
        });
        let loading = loading.flatten();
        Self {
            score: None,
            loading,
            waiting: None,
            tracks,
            voices: std::array::from_fn(|_| None),
            clock,
            conductor: Conductor::default(),
            pressure: Pressure::default(),
        }
    }

    pub fn start_clock(&mut self) {
        if let Some(clock) = &mut self.clock {
            clock.start();
        }
    }

    fn now(&self, fallback: f64) -> f64 {
        self.clock.as_ref().map_or(fallback, |c| {
            let t = c.time();
            t.ticks as f64 + t.fraction
        })
    }

    fn start_time(&self, at: f64) -> StartTime {
        self.clock.as_ref().map_or(StartTime::Immediate, |c| ClockTime::from_ticks_f64(c, at).into())
    }

    fn stop_voices(&mut self, secs: f64) {
        for voice in &mut self.voices {
            if let Some(mut v) = voice.take() {
                v.stop(secs);
            }
        }
    }

    fn play(&mut self, mode: MusicMode, at: f64) {
        self.stop_voices(0.06);
        self.waiting = None;
        let Some(score) = &self.score else {
            if self.loading.is_some() {
                self.waiting = Some((mode, at));
            }
            return;
        };
        let start = self.start_time(at);
        for (i, &level) in mode.levels().iter().enumerate() {
            if let Some(track) = &mut self.tracks[i] {
                track.set_volume(amp(level), fade(StartTime::Immediate, 0.03));
                self.voices[i] = track
                    .play(StemData {
                        score: Arc::clone(score),
                        layer: i,
                        dawn: mode == MusicMode::Dawn,
                        start,
                        pan: Panning([-0.05, -0.22, 0.20, -0.30, 0.0, 0.32][i]),
                    })
                    .ok();
            }
        }
    }

    /// 非阻塞收取后台结果；等待期间的新局、标题、死亡和天明以最新请求为准。
    fn poll_score(&mut self, now: f64) {
        if let Some(rx) = &self.loading {
            match rx.try_recv() {
                Ok(score) => {
                    self.score = Some(score);
                    self.loading = None;
                }
                Err(mpsc::TryRecvError::Empty) => return,
                Err(mpsc::TryRecvError::Disconnected) => {
                    bevy::log::warn!("音乐采样合成线程未完成，继续静音运行");
                    self.loading = None;
                    self.waiting = None;
                    return;
                }
            }
        }
        if self.score.is_some()
            && let Some((mode, requested)) = self.waiting.take()
        {
            let at = requested.max(now + 0.1);
            if mode == MusicMode::Dawn {
                // 极慢设备在天明前尚未合成完，也必须从第一音奏完，不跳过任何小节。
                self.conductor.origin = at;
                self.conductor.dawn_end = Some(at + THEME);
            } else {
                let desired = self.conductor.desired;
                self.conductor.begin(mode, at);
                self.conductor.request(desired);
            }
            self.play(mode, at);
        }
    }

    /// 明确开始一局时重置压力；配乐不取模拟随机数，也不需要随机主题。
    pub fn start_run(&mut self, real_now: f64) {
        let at = self.now(real_now) + 0.1;
        self.pressure = Pressure::default();
        self.conductor.begin(MusicMode::Explore, at);
        self.play(MusicMode::Explore, at);
    }

    pub fn title(&mut self, real_now: f64) {
        if self.conductor.dawn_end.is_some() {
            self.conductor.request(MusicMode::Title);
            return;
        }
        let at = self.now(real_now) + 0.1;
        self.conductor.begin(MusicMode::Title, at);
        self.play(MusicMode::Title, at);
    }

    pub fn request(&mut self, mode: MusicMode) {
        self.conductor.request(mode);
    }

    /// 返回是否第一次进入天明；事件层只在第一次安排静默、低锣、晨鸟。
    pub fn dawn(&mut self, real_now: f64) -> bool {
        let Some(at) = self.conductor.dawn(self.now(real_now)) else {
            return false;
        };
        self.play(MusicMode::Dawn, at);
        true
    }

    pub fn is_dawn(&self) -> bool {
        self.conductor.dawn_end.is_some() || self.conductor.dawn_done
    }

    pub fn stop(&mut self) {
        self.stop_voices(0.25);
        self.waiting = None;
        self.conductor = Conductor::default();
    }

    pub fn tick(&mut self, real_now: f64) {
        let now = self.now(real_now);
        self.poll_score(now);
        // 采样未就绪时冻结曲式；天明请求不能在后台合成期间被当作已经奏完。
        if self.waiting.is_some() {
            return;
        }
        let was_dawn = self.conductor.dawn_end.is_some();
        let transition = self.conductor.advance(now);
        if was_dawn && self.conductor.dawn_done {
            if self.conductor.desired == MusicMode::Title {
                self.title(real_now);
            }
            return;
        }
        if let Some(Transition { mode, at }) = transition {
            let start = self.start_time(at);
            for (track, level) in self.tracks.iter_mut().zip(mode.levels()) {
                if let Some(t) = track {
                    t.set_volume(amp(level), fade(start, STEP * 2.0));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pressure_uses_combat_smooths_spikes_and_has_hysteresis() {
        let calm = PressureInput { hp_ratio: 1.0, progress: 1.0, ..Default::default() };
        let crowd = PressureInput { enemies: 180, nearby: 22, ..calm };
        let mut p = Pressure::default();
        for _ in 0..100 {
            assert_eq!(p.update(calm, 0.2), MusicMode::Explore);
        }
        assert_eq!(p.update(crowd, 0.2), MusicMode::Explore, "单次尖峰不能换配器");
        for _ in 0..25 {
            p.update(crowd, 0.2);
        }
        assert!(p.siege);
        let middle = PressureInput { enemies: 150, nearby: 5, ..calm };
        assert!((0.36..0.56).contains(&middle.value(0.0)));
        for _ in 0..100 {
            assert_eq!(p.update(middle, 0.2), MusicMode::Siege);
        }
        for _ in 0..100 {
            p.update(calm, 0.2);
        }
        assert!(!p.siege);
        for _ in 0..100 {
            assert_eq!(p.update(middle, 0.2), MusicMode::Explore);
        }
        p.hurt();
        let memory = p.hurt;
        assert!(middle.value(memory) > middle.value(0.0));
        p.update(calm, 3.0);
        assert!(p.hurt < memory * 0.38);
        assert!(PressureInput { hp_ratio: 0.2, ..calm }.value(0.0) > calm.value(0.0));
    }

    #[test]
    fn transitions_use_phrase_boundaries_and_boss_preempts_at_next_bar() {
        let mut c = Conductor::default();
        c.begin(MusicMode::Explore, 10.0);
        c.request(MusicMode::Siege);
        let siege = c.advance(10.4).unwrap();
        assert_eq!(siege.at, 10.0 + PHRASE);
        assert_eq!(c.mode, MusicMode::Explore);
        c.request(MusicMode::Boss);
        let boss = c.advance(11.0).unwrap();
        assert_eq!(boss.at, 10.0 + BAR);
        assert!(boss.at < siege.at);
        assert!(c.advance(boss.at - 0.001).is_none());
        assert_eq!(c.mode, MusicMode::Explore);
        assert!(c.advance(boss.at).is_none());
        assert_eq!(c.mode, MusicMode::Boss);
        c.request(MusicMode::Explore);
        let exit = c.advance(boss.at + 0.1).unwrap();
        assert_eq!(exit.at, 10.0 + PHRASE);
        c.advance(exit.at);
        assert_eq!(c.mode, MusicMode::Explore);
    }

    #[test]
    fn pending_pressure_change_can_be_cancelled_and_long_frames_do_not_shift_grid() {
        let mut c = Conductor::default();
        c.begin(MusicMode::Explore, 0.0);
        c.request(MusicMode::Siege);
        c.advance(1.0);
        c.request(MusicMode::Explore);
        let cancel = c.advance(2.0).unwrap();
        assert_eq!(cancel.mode, MusicMode::Explore);
        c.advance(PHRASE);
        assert_eq!(c.mode, MusicMode::Explore);
        c.request(MusicMode::Siege);
        let t = c.advance(137.0).unwrap();
        assert!((t.at / PHRASE - (t.at / PHRASE).round()).abs() < 1e-10);
        assert!(t.at > 137.0);
    }

    #[test]
    fn dawn_waits_then_finishes_every_bar_despite_results_title_or_repeated_events() {
        let mut c = Conductor::default();
        c.begin(MusicMode::Boss, 0.0);
        let start = c.dawn(7.0).unwrap();
        assert_eq!(start, 7.0 + DAWN_DELAY);
        assert!(c.dawn(7.6).is_none(), "结算事件不能重奏开头");
        c.request(MusicMode::Title);
        c.request(MusicMode::Siege);
        let end = c.dawn_end.unwrap();
        assert!(c.advance(start - 0.1).is_none());
        for bar in 0..8 {
            assert!(c.advance(start + bar as f64 * BAR).is_none());
            assert_eq!(c.mode, MusicMode::Dawn);
            assert!(!c.dawn_done);
        }
        assert!(c.advance(end - 0.001).is_none());
        c.advance(end);
        assert!(c.dawn_done);
        assert_eq!(c.desired, MusicMode::Title);
        assert!(c.dawn(end + 1.0).is_none());
        c.begin(MusicMode::Explore, end + 1.0);
        assert!(!c.dawn_done, "新一局必须清除上一局的完成状态");
    }

    #[test]
    fn background_loading_preserves_latest_request_and_full_dawn() {
        let mut m = Music::new(None, None);
        assert!(m.loading.is_none(), "没有声卡不应浪费内存合成");
        let (tx, rx) = mpsc::channel();
        m.loading = Some(rx);
        m.title(0.0);
        m.start_run(1.0);
        m.request(MusicMode::Boss);
        m.tick(2.0);
        assert_eq!(m.waiting.unwrap().0, MusicMode::Explore);
        assert!(m.conductor.pending.is_none());
        assert!(m.dawn(3.0));
        m.title(4.0);
        m.tick(100.0);
        assert!(!m.conductor.dawn_done, "后台尚未完成时不能跳过主题");
        tx.send(score::test_score()).unwrap();
        m.tick(101.0);
        assert!(m.waiting.is_none());
        assert_eq!(m.conductor.origin, 101.1);
        assert_eq!(m.conductor.dawn_end, Some(101.1 + THEME));
        assert_eq!(m.conductor.desired, MusicMode::Title);
        m.tick(101.1 + THEME - 0.01);
        assert_eq!(m.conductor.mode, MusicMode::Dawn);
        m.tick(101.1 + THEME);
        assert_eq!(m.conductor.mode, MusicMode::Title);

        let (tx, rx) = mpsc::channel();
        m.score = None;
        m.loading = Some(rx);
        m.start_run(200.0);
        m.stop();
        tx.send(score::test_score()).unwrap();
        m.tick(201.0);
        assert!(m.waiting.is_none());
        assert_eq!(m.conductor.mode, MusicMode::None, "死亡取消尚未开始的配乐");
    }

    /// 直接运行 Kira 的音频线程渲染器，验证真实采样调度，而非只验证状态枚举。
    #[test]
    fn audio_clock_preserves_sync_silence_and_complete_dawn_without_render_ticks() {
        use kira::backend::{Backend, Renderer};
        use kira::clock::ClockSpeed;
        use kira::{AudioManager, AudioManagerSettings};

        struct Offline {
            renderer: Option<Renderer>,
            block: Vec<f32>,
        }
        impl Backend for Offline {
            type Settings = ();
            type Error = ();
            fn setup(_: (), size: usize) -> Result<(Self, u32), ()> {
                Ok((Self { renderer: None, block: vec![0.0; size * 2] }, SAMPLE_RATE))
            }
            fn start(&mut self, renderer: Renderer) -> Result<(), ()> {
                self.renderer = Some(renderer);
                Ok(())
            }
        }
        impl Offline {
            fn advance(&mut self, seconds: f64) -> f32 {
                let blocks =
                    (seconds * f64::from(SAMPLE_RATE) / (self.block.len() / 2) as f64).ceil() as usize;
                let renderer = self.renderer.as_mut().unwrap();
                let mut peak = 0.0f32;
                for _ in 0..blocks {
                    renderer.on_start_processing();
                    renderer.process(&mut self.block, 2);
                    peak = self.block.iter().map(|x| x.abs()).fold(peak, f32::max);
                }
                peak
            }
        }

        let mut manager = AudioManager::<Offline>::new(AudioManagerSettings {
            backend_settings: (),
            internal_buffer_size: 128,
            ..Default::default()
        })
        .unwrap();
        let clock = manager.add_clock(ClockSpeed::TicksPerSecond(1.0)).unwrap();
        let mut parent = manager.add_sub_track(TrackBuilder::new()).unwrap();
        let mut m = Music::new(Some(clock), Some(&mut parent));
        // 离线渲染跑得比真实时间快，先收取后台结果，不让测试依赖线程调度速度。
        m.score = Some(m.loading.take().unwrap().recv().unwrap());
        m.start_clock();
        m.start_run(0.0);
        assert!(manager.backend_mut().advance(0.3) > 0.01);
        // 主线程长时间不 tick，音频线程仍保持六轨循环对齐。
        assert!(manager.backend_mut().advance(THEME * 8.0) < 0.7);
        let positions: Vec<f64> = m.voices.iter().map(|v| v.as_ref().unwrap().position()).collect();
        assert!(positions.iter().all(|p| (p - positions[0]).abs() < 1e-6));
        assert!((0.18..0.23).contains(&positions[0]));
        m.request(MusicMode::Siege);
        m.tick(0.0);
        let boundary = m.conductor.pending.unwrap().at;
        manager.backend_mut().advance(boundary - m.now(0.0) + 1.0);
        m.tick(0.0);
        assert_eq!(m.conductor.mode, MusicMode::Siege);
        assert!(m.dawn(0.0));
        manager.backend_mut().advance(0.2);
        assert!(manager.backend_mut().advance(5.2) < 1e-5, "静默及锣鸟前奏期间不能漏出旧配乐");
        assert!(m.voices.iter().all(|v| v.as_ref().unwrap().position() == 0.0));
        assert!(manager.backend_mut().advance(0.4) > 0.01);
        m.title(0.0);
        assert!(!m.dawn(0.0), "RunOver 不能重启正在回归的主题");
        m.request(MusicMode::Boss);
        m.tick(0.0);
        manager.backend_mut().advance(THEME / 2.0);
        assert!(m.voices.iter().all(|v| v.as_ref().unwrap().position() > PHRASE));
        manager.backend_mut().advance(THEME / 2.0 + 1.0);
        assert!(m.voices.iter().all(|v| v.as_ref().unwrap().stopped()));
        assert!(manager.backend_mut().advance(0.2) < 1e-5, "完整主题只奏一次");
        m.tick(0.0);
        assert_eq!(m.conductor.mode, MusicMode::Title);
        assert!(manager.backend_mut().advance(0.4) > 0.01);
        m.pressure.hurt();
        m.start_run(0.0);
        assert_eq!(m.pressure.hurt, 0.0);
        assert!(!m.is_dawn());
    }
}
