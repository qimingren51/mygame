//! 环境声（docs/FEEL.md 第 6 节）：每个场所一段循环的底子，夜里再叠一层虫鸣，偶尔远处一声鸮啼、狐鸣。
//!
//! - 底子跟着场所交叉淡化。标题、夜战、夜主是风：阵风一紧一松，紧的时候上面多一道呜呜的哨音；
//!   夜主的风更紧，底下压一层低频的闷响。灯驿是屋里灯芯的轻响。
//! - 虫鸣：四只蟋蟀一串一串地叫，偶尔歇一会儿，底下一层很淡的远处虫声。标题轻一些。
//! - 跟着局势变：夜主登场虫声骤停（万籁俱寂），退去 20 秒后慢慢回来；妖潮时停 18 秒；天明后不再有虫声、
//!   风小一半；无尽夜每深一层，风的音高低 5%、虫声弱三成；升级选择、暂停时都压低。
//! - 远处的叫声：平时约半分钟一声鸮啼；6 分钟后换成狐鸣，越接近夜主登场（9:30）越密、越响。
//!   夜主在场、天明以后不叫。
//!
//! 循环的底子按单声道 16 位存（每种约 1.1 MiB，立体声浮点要 4.4 MiB）；播放时右声道取 17 毫秒前的
//! 采样并略轻一点，展开成立体声。叫声是短的单声道，按左右随机做声像。全部走环境总线（音量跟
//! “环境”设置，挂场所混响）。用现实时间，不碰模拟；随机数用音频自己的流。

use std::convert::Infallible;
use std::f32::consts::{FRAC_PI_2, PI, TAU};
use std::sync::Arc;
use std::time::Duration;

use bevy::prelude::*;
use kira::command::{CommandReader, CommandWriter, command_writer_and_reader};
use kira::info::Info;
use kira::sound::static_sound::{StaticSoundData, StaticSoundSettings};
use kira::sound::{Sound, SoundData};
use kira::track::TrackHandle;
use kira::{Decibels, Easing, Frame, Panning, Parameter, StartTime, Tween, interpolate_frame};

use lantern_core::Pcg32;
use lantern_core::step::TICK_HZ;
use lantern_sim::{AppState, Director, RunState, SimEvent, SimOutbox, SimPhase, Tick};

use crate::Audio;
use crate::space::Scene;
use crate::synth::{Buf, FilterKind, Noise, NoiseOpts, SAMPLE_RATE};

const SR: f32 = SAMPLE_RATE as f32;
/// 换场时旧的淡出、新的淡入（秒）。
const CROSSFADE: f64 = 1.2;
/// 右声道比左声道晚的采样数（17 毫秒）。
const DELAY: i64 = SAMPLE_RATE as i64 * 17 / 1000;
/// 底子渲染的长度；末尾半秒交叠进开头，实际循环 12 秒
const BED_SECS: f32 = 12.5;
const OVERLAP: f32 = 0.5;
/// 虫鸣循环 16 秒
const BUGS_SECS: f32 = 16.0;

/// 虫鸣在各场所的音量（线性，相对虫鸣本身）
const BUGS_TITLE: f32 = 0.5;
/// 天明后风小一半；升级选择、暂停时整体压到这么多
const DAWN_WIND: f32 = 0.5;
const MENU: f32 = 0.45;
/// 无尽夜每深一层：风的音高 × (1 − 这么多)，虫声 × 这么多
const DEEP_RATE: f64 = 0.05;
const DEEP_BUGS: f32 = 0.7;
/// 夜主退去、妖潮过后，虫声多久回来（秒）
const BUGS_BACK: f64 = 20.0;
const SURGE_HUSH: f64 = 18.0;
/// 狐鸣：几秒起开始有，到几秒最密（夜主 9:30 登场）
const FOX_FROM: f32 = 360.0;
const FOX_PEAK: f32 = 560.0;

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

    /// 浮点采样压成 16 位。
    fn quantize(data: &[f32]) -> Self {
        let peak = data.iter().fold(0.0_f32, |m, s| m.max(s.abs())).max(1e-6);
        let pcm = data.iter().map(|s| (s / peak * 32767.0).round() as i16).collect();
        Bed { pcm, gain: peak / 32767.0 }
    }
}

pub(crate) struct Ambience {
    beds: [Arc<Bed>; 4],
    bugs: Arc<Bed>,
    owl: StaticSoundData,
    fox: StaticSoundData,
    current: Option<Scene>,
    handle: Option<BedHandle>,
    bugs_handle: Option<BedHandle>,
    // ---- 局势（一局开始时重置）
    rng: Pcg32,
    last_state: Option<AppState>,
    dawn: bool,
    boss: bool,
    depth: u32,
    /// 虫声在这个时刻之前保持安静（妖潮、夜主刚退去）
    hush_until: f64,
    /// 下一声鸟兽叫的时刻
    next_call: f64,
    /// 上一次发给底子和虫鸣的（音量、音高、虫鸣音量）；变了才发
    sent: (f32, f64, f32),
}

impl Ambience {
    pub fn new() -> Self {
        Self {
            beds: Scene::ALL.map(|s| Arc::new(render(s))),
            bugs: Arc::new(bugs()),
            owl: owl(),
            fox: fox(),
            current: None,
            handle: None,
            bugs_handle: None,
            rng: Pcg32::new(0x0a3b_1e57, 5),
            last_state: None,
            dawn: false,
            boss: false,
            depth: 0,
            hush_until: 0.0,
            next_call: 0.0,
            sent: (f32::NAN, f64::NAN, f32::NAN),
        }
    }

    pub fn set_scene(&mut self, scene: Scene, mut track: Option<&mut TrackHandle>) {
        if self.current == Some(scene) {
            return;
        }
        self.current = Some(scene);
        // 换了底子，音量、音高都要重新发
        self.sent = (f32::NAN, f64::NAN, self.sent.2);
        if let Some(mut handle) = self.handle.take() {
            handle.stop(CROSSFADE);
        }
        if let Some(track) = track.as_deref_mut() {
            let data =
                BedData { bed: Arc::clone(&self.beds[scene as usize]), fade_in: CROSSFADE, level: 1.0 };
            match track.play(data) {
                Ok(handle) => self.handle = Some(handle),
                Err(error) => bevy::log::warn!("环境声播放失败：{error}"),
            }
        }
        // 虫鸣在标题和野外一直放着（音量由局势定）；灯驿在屋里，没有
        let outdoors = scene != Scene::Hub;
        if !outdoors && let Some(mut h) = self.bugs_handle.take() {
            h.stop(CROSSFADE);
        }
        if outdoors
            && self.bugs_handle.is_none()
            && let Some(track) = track
        {
            let data = BedData { bed: Arc::clone(&self.bugs), fade_in: 0.0, level: 0.0 };
            match track.play(data) {
                Ok(handle) => {
                    self.bugs_handle = Some(handle);
                    self.sent.2 = 0.0;
                }
                Err(error) => bevy::log::warn!("虫鸣播放失败：{error}"),
            }
        }
    }

    /// 一局开始：局势归零，第一声叫在 8–20 秒后。
    fn start_run(&mut self, now: f64) {
        self.dawn = false;
        self.boss = false;
        self.depth = 0;
        self.hush_until = 0.0;
        self.next_call = now + f64::from(self.rng.range_f32(8.0, 20.0));
    }

    #[cfg(test)]
    pub(crate) fn pcm_bytes(&self) -> usize {
        self.beds.iter().chain([&self.bugs]).map(|b| b.pcm.len() * size_of::<i16>()).sum()
    }
}

/// 跟着局势调底子和虫鸣，偶尔叫一声。排在 `sync_scene` 后面。
pub(crate) fn update_ambience(
    time: Res<Time<Real>>,
    state: Res<State<AppState>>,
    outbox: Option<Res<SimOutbox>>,
    tick: Option<Res<Tick>>,
    director: Option<Res<Director>>,
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    mut audio: NonSendMut<Audio>,
) {
    let now = time.elapsed_secs_f64();
    let Audio { ambience: a, mixer, .. } = &mut *audio;
    let state = *state.get();
    let in_run = state == AppState::Run;
    if in_run && a.last_state != Some(AppState::Run) {
        a.start_run(now);
    }
    if state == AppState::Title {
        a.dawn = false;
    }
    a.last_state = Some(state);
    if in_run {
        for ev in outbox.iter().flat_map(|o| o.0.iter()) {
            match *ev {
                SimEvent::Surge => a.hush_until = a.hush_until.max(now + SURGE_HUSH),
                SimEvent::BossDefeated { dawn: true, .. } => a.dawn = true,
                SimEvent::NightDeeper { layer } => a.depth = layer.min(4),
                _ => {}
            }
        }
        let boss = director.is_some_and(|d| d.boss.is_some());
        if a.boss && !boss {
            a.hush_until = a.hush_until.max(now + BUGS_BACK);
        }
        a.boss = boss;
    }
    let menu = in_run
        && (phase.as_deref().is_some_and(|p| *p != SimPhase::Play)
            || run.is_some_and(|r| *r.get() != RunState::Playing));
    let scene = a.current.unwrap_or(Scene::Title);

    // ---- 目标：底子的音量、音高，虫鸣的音量
    let duck = if menu { MENU } else { 1.0 };
    let bed = if a.dawn { DAWN_WIND } else { 1.0 } * duck;
    let wild = matches!(scene, Scene::Night | Scene::Boss);
    let rate = if wild { 1.0 - DEEP_RATE * f64::from(a.depth) } else { 1.0 };
    let quiet = a.boss || a.dawn || now < a.hush_until;
    let bugs = match scene {
        Scene::Title => BUGS_TITLE,
        Scene::Night if !quiet => DEEP_BUGS.powi(a.depth as i32),
        _ => 0.0,
    } * duck;
    let (old_bed, old_rate, old_bugs) = a.sent;
    if let Some(h) = &mut a.handle {
        if bed != old_bed {
            h.set_level(bed, 2.0);
        }
        if rate != old_rate {
            h.set_rate(rate, 3.0);
        }
    }
    if bugs != old_bugs
        && let Some(h) = &mut a.bugs_handle
    {
        // 停要停得干脆（夜主登场那一下），回来要慢
        let secs = if bugs < old_bugs {
            if a.boss { 0.8 } else { 1.5 }
        } else if old_bugs <= 0.0 {
            6.0
        } else {
            1.5
        };
        h.set_level(bugs, secs);
    }
    a.sent = (bed, rate, bugs);

    // ---- 远处偶尔一声：平时是鸮，夜主快来时换成狐，越来越密；夜主在场、天明以后不叫
    if now < a.next_call || !matches!(scene, Scene::Title | Scene::Night) {
        return;
    }
    let secs = tick.map_or(0.0, |t| t.0 as f32 / TICK_HZ as f32);
    let fox_k = if in_run { ((secs - FOX_FROM) / (FOX_PEAK - FOX_FROM)).clamp(0.0, 1.0) } else { 0.0 };
    let gap = if fox_k > 0.0 { 30.0 - 16.0 * fox_k } else { 34.0 };
    a.next_call = now + f64::from(gap * a.rng.range_f32(0.7, 1.4));
    if menu || a.boss || a.dawn {
        return;
    }
    let Some(track) = mixer.as_mut().map(|m| &mut m.ambience) else { return };
    let fox = fox_k > 0.0 && a.rng.chance(0.35 + 0.6 * fox_k);
    // 越近越响
    let (data, vol) =
        if fox { (&a.fox, -8.0 + 6.0 * fox_k) } else { (&a.owl, if in_run { -9.0 } else { -12.0 }) };
    let pan = a.rng.range_f32(-0.7, 0.7);
    let rate = f64::from(a.rng.range_f32(0.94, 1.06));
    let _ = track.play(data.playback_rate(rate).volume(Decibels(vol)).panning(Panning(pan)));
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
    /// 开始时的音量（线性）
    level: f32,
}

/// 控制端：`stop` 淡出，`set_level`、`set_rate` 慢慢改音量和音高；丢掉控制端时也很快淡出，不留无限循环。
struct BedHandle {
    stop: CommandWriter<f64>,
    level: CommandWriter<(f32, f64)>,
    rate: CommandWriter<(f64, f64)>,
    stopping: bool,
}

impl BedHandle {
    fn stop(&mut self, secs: f64) {
        self.stopping = true;
        self.stop.write(secs);
    }

    fn set_level(&mut self, level: f32, secs: f64) {
        self.level.write((level, secs));
    }

    fn set_rate(&mut self, rate: f64, secs: f64) {
        self.rate.write((rate, secs));
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
    level_cmd: CommandReader<(f32, f64)>,
    rate_cmd: CommandReader<(f64, f64)>,
    position: f64,
    envelope: Parameter<f32>,
    level: Parameter<f32>,
    rate: Parameter<f64>,
    stopping: bool,
    finished: bool,
}

impl SoundData for BedData {
    type Error = Infallible;
    type Handle = BedHandle;

    fn into_sound(self) -> Result<(Box<dyn Sound>, BedHandle), Infallible> {
        let (stop, stop_reader) = command_writer_and_reader();
        let (level, level_reader) = command_writer_and_reader();
        let (rate, rate_reader) = command_writer_and_reader();
        let mut envelope = Parameter::new(0.0.into(), 0.0);
        envelope.set(1.0.into(), fade(self.fade_in));
        let voice = BedVoice {
            bed: self.bed,
            stop: stop_reader,
            level_cmd: level_reader,
            rate_cmd: rate_reader,
            position: 0.0,
            envelope,
            level: Parameter::new(self.level.into(), self.level),
            rate: Parameter::new(1.0.into(), 1.0),
            stopping: false,
            finished: false,
        };
        Ok((Box::new(voice), BedHandle { stop, level, rate, stopping: false }))
    }
}

impl Sound for BedVoice {
    fn on_start_processing(&mut self) {
        if let Some(secs) = self.stop.read() {
            self.envelope.set(0.0.into(), fade(secs));
            self.stopping = true;
        }
        if let Some((level, secs)) = self.level_cmd.read() {
            self.level.set(level.into(), fade(secs));
        }
        if let Some((rate, secs)) = self.rate_cmd.read() {
            self.rate.set(rate.into(), fade(secs));
        }
    }

    fn process(&mut self, out: &mut [Frame], dt: f64, info: &Info) {
        if self.finished {
            out.fill(Frame::ZERO);
            return;
        }
        let count = out.len();
        let done = self.envelope.update(dt * count as f64, info);
        self.level.update(dt * count as f64, info);
        self.rate.update(dt * count as f64, info);
        let len = self.bed.pcm.len() as f64;
        for (i, frame) in out.iter_mut().enumerate() {
            let k = (i + 1) as f64 / count as f64;
            let gain = self.envelope.interpolated_value(k) * self.level.interpolated_value(k);
            *frame = self.bed.frame(self.position) * gain;
            // 设备采样率不同时按时间推进；音高变了，读得快慢跟着变
            self.position =
                (self.position + dt * f64::from(SAMPLE_RATE) * self.rate.interpolated_value(k)) % len;
        }
        if done && self.stopping {
            self.finished = true;
        }
    }

    fn finished(&self) -> bool {
        self.finished
    }
}

// ---- 合成

/// 一阶低通（y 往 x 靠）。
struct OnePole {
    a: f32,
    y: f32,
}

impl OnePole {
    fn new(freq: f32) -> Self {
        OnePole { a: 1.0 - (-TAU * freq / SR).exp(), y: 0.0 }
    }

    fn low(&mut self, x: f32) -> f32 {
        self.y += self.a * (x - self.y);
        self.y
    }
}

/// 状态变量带通（Chamberlin）；中心频率可以每个采样改。
#[derive(Default)]
struct Svf {
    low: f32,
    band: f32,
}

impl Svf {
    fn band(&mut self, x: f32, freq: f32, q: f32) -> f32 {
        let f = 2.0 * (PI * freq / SR).sin();
        self.low += f * self.band;
        let high = x - self.low - self.band / q;
        self.band += f * high;
        self.band
    }
}

fn rms(v: &[f32]) -> f32 {
    (v.iter().map(|x| x * x).sum::<f32>() / v.len().max(1) as f32).sqrt()
}

/// 风：两层一阶低通的噪声做底子，阵风一紧一松（起伏以循环长度为周期，正好接上）；
/// 阵风紧的时候上面多一道呜呜的哨音（带通噪声，中心频率跟着阵风从 420 Hz 走到 1100 Hz）。
/// calm 是风最松时底子剩几成；whistle 是哨音相对底子的响度；level 是底子的有效值。
fn add_wind(data: &mut [f32], seed: u32, cutoff: f32, calm: f32, whistle: f32, level: f32) {
    let period = BED_SECS - OVERLAP;
    // 起点挪到风最松的那一刻（约第 8.6 秒）：接缝处哨音最弱，接得上
    let gust = |t: f32| {
        let p = TAU * (t + 8.63) / period;
        (0.55 + 0.25 * (p + 0.7).sin() + 0.14 * (2.0 * p + 2.1).sin() + 0.06 * (5.0 * p + 0.4).sin())
            .clamp(0.1, 1.0)
    };
    let mut noise = Noise(seed);
    let (mut l1, mut l2) = (OnePole::new(cutoff), OnePole::new(cutoff));
    let mut svf = Svf::default();
    let (mut low, mut high) = (Vec::with_capacity(data.len()), Vec::with_capacity(data.len()));
    for i in 0..data.len() {
        let g = gust(i as f32 / SR);
        let x = noise.next();
        low.push(l2.low(l1.low(x)) * (calm + (1.0 - calm) * g));
        high.push(svf.band(x, 420.0 + 680.0 * g, 7.0) * g * g * g);
    }
    let (kl, kh) = (level / rms(&low).max(1e-6), whistle * level / rms(&high).max(1e-6));
    for ((d, l), h) in data.iter_mut().zip(&low).zip(&high) {
        *d += l * kl + h * kh;
    }
}

/// 末尾 OVERLAP 秒交叠进开头；循环边界两侧来自原采样的相邻位置。
fn loop_seam(data: &mut Vec<f32>) {
    let overlap = (OVERLAP * SR) as usize;
    let len = data.len() - overlap;
    for i in 0..overlap {
        let x = i as f32 / overlap as f32;
        data[i] = data[len + i] * (1.0 - x) + data[i] * x;
    }
    data.truncate(len);
}

fn render(scene: Scene) -> Bed {
    let mut b = Buf::new(BED_SECS);
    b.seed_noise(0x7213_31ab + scene as u32 * 179);
    match scene {
        // 灯驿：屋里，很低的底子，灯芯轻响，听感贴近人物；不使用显眼的节拍。
        Scene::Hub => {
            for at in [0.0, 3.2, 6.4, 9.6] {
                b.noise(
                    at,
                    4.5,
                    0.045,
                    NoiseOpts { kind: FilterKind::Low, freq: 220.0, attack: 1.8, ..Default::default() },
                );
            }
            for (i, at) in [0.7, 2.3, 5.1, 5.4, 8.7, 10.8].into_iter().enumerate() {
                b.noise(
                    at,
                    0.045,
                    0.013,
                    NoiseOpts { freq: 1100.0 + i as f32 * 130.0, ..Default::default() },
                );
            }
        }
        // 标题：山路上远远的风，松一些
        Scene::Title => add_wind(&mut b.data, 0x51ee_d001, 240.0, 0.45, 0.25, 0.022),
        Scene::Night => add_wind(&mut b.data, 0x51ee_d002, 280.0, 0.35, 0.35, 0.028),
        // 夜主：风紧，哨音更多，底下一层低频的闷响
        Scene::Boss => {
            add_wind(&mut b.data, 0x51ee_d003, 320.0, 0.55, 0.35, 0.024);
            b.noise(0.0, BED_SECS, 0.05, NoiseOpts { freq: 72.0, q: 1.5, attack: 4.0, ..Default::default() });
        }
    }
    loop_seam(&mut b.data);
    Bed::quantize(&b.data)
}

/// 虫鸣：四只蟋蟀（3.9–5.1 kHz，各自一串几声、节奏、远近不同，偶尔歇一会儿），
/// 底下一层很淡的远处虫声（6.5 kHz 一带的窄带噪声按 42 Hz 颤动，8 秒一起伏）。
/// 蟋蟀按圆周时间写进循环里（越过末尾的接到开头），本身就无缝；远处虫声靠交叠接上。
fn bugs() -> Bed {
    let len = (BUGS_SECS * SR) as usize;
    let mut bed = vec![0.0f32; len + (OVERLAP * SR) as usize];
    let mut noise = Noise(0x7a8b_9cad);
    let mut svf = Svf::default();
    for (i, d) in bed.iter_mut().enumerate() {
        let t = i as f32 / SR;
        let am = (0.5 + 0.5 * (TAU * 42.0 * t).sin()) * (0.6 + 0.4 * (TAU * t / 8.0).sin());
        *d = svf.band(noise.next(), 6500.0, 5.0) * am;
    }
    let k = 0.006 / rms(&bed).max(1e-6);
    bed.iter_mut().for_each(|d| *d *= k);
    loop_seam(&mut bed);

    let mut crickets = vec![0.0f32; len];
    let mut rng = Pcg32::new(0x00c1_c4e7, 3);
    // （音高 Hz，一串几声，一串的间隔秒，响度）
    let voices =
        [(4300.0, 3, 0.85, 1.0), (4720.0, 4, 1.15, 0.7), (5080.0, 3, 0.7, 0.45), (3920.0, 5, 1.35, 0.35)];
    const PULSE: f32 = 0.014;
    const GAP: f32 = 0.022;
    for (freq, pulses, every, loud) in voices {
        let mut t = rng.range_f32(0.0, every);
        while t < BUGS_SECS {
            // 偶尔歇一会儿
            if rng.chance(0.08) {
                t += rng.range_f32(1.5, 3.5);
                continue;
            }
            let amp = loud * rng.range_f32(0.75, 1.1);
            for p in 0..pulses {
                let t0 = t + p as f32 * (PULSE + GAP);
                let (s0, m) = ((t0 * SR) as usize, (PULSE * SR) as usize);
                for j in 0..m {
                    let u = j as f32 / m as f32;
                    let ph = TAU * freq * (t0 + j as f32 / SR);
                    crickets[(s0 + j) % len] +=
                        (ph.sin() + 0.15 * (3.0 * ph).sin()) * (PI * u).sin().powi(2) * amp;
                }
            }
            t += every * rng.range_f32(0.85, 1.2);
        }
    }
    let k = 0.1 / crickets.iter().fold(0.0_f32, |m, s| m.max(s.abs())).max(1e-6);
    let mix: Vec<f32> = bed.iter().zip(&crickets).map(|(b, c)| b + c * k).collect();
    Bed::quantize(&mix)
}

/// 单声道的一段，按时间顺序逐个采样调用 f（f 可以自己累积相位）。
fn mono(secs: f32, mut f: impl FnMut(f32) -> f32) -> StaticSoundData {
    let frames: Vec<Frame> =
        (0..(secs * SR) as usize).map(|i| Frame::from_mono(f(i as f32 / SR).clamp(-1.0, 1.0))).collect();
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default(),
        slice: None,
    }
}

/// 起音、收尾都圆滑的包络：t 在 [0, dur] 里，attack 秒起来，最后 release 秒落下。
fn soft(t: f32, dur: f32, attack: f32, release: f32) -> f32 {
    if t < 0.0 || t > dur {
        return 0.0;
    }
    let a = (t / attack).min(1.0);
    let r = ((dur - t) / release).min(1.0);
    (a * FRAC_PI_2).sin() * (r * FRAC_PI_2).sin()
}

/// 鸮：“呼——呼、呼——”，低沉的正弦微微往下滑。
fn owl() -> StaticSoundData {
    const HOOTS: [(f32, f32); 3] = [(0.0, 0.42), (0.72, 0.2), (1.0, 0.5)];
    let mut ph = [0.0f32; 3];
    mono(1.7, move |t| {
        let mut s = 0.0;
        for (k, (t0, dur)) in HOOTS.into_iter().enumerate() {
            let u = t - t0;
            if (0.0..=dur).contains(&u) {
                ph[k] = (ph[k] + (312.0 - 24.0 * u / dur) / SR).fract();
                let p = TAU * ph[k];
                s += (p.sin() + 0.12 * (2.0 * p).sin()) * soft(u, dur, 0.07, 0.16);
            }
        }
        s * 0.22
    })
}

/// 远处的狐：两声尖利的短鸣，先挑上去再落下来；高频收掉一些，像隔着林子。
fn fox() -> StaticSoundData {
    const YELPS: [(f32, f32, f32); 2] = [(0.0, 0.34, 1.0), (0.5, 0.42, 0.92)];
    let mut ph = [0.0f32; 2];
    let mut lp = OnePole::new(2200.0);
    mono(1.2, move |t| {
        let mut s = 0.0;
        for (i, (t0, dur, pitch)) in YELPS.into_iter().enumerate() {
            let u = t - t0;
            if (0.0..=dur).contains(&u) {
                let k = u / dur;
                // 700 → 1250 → 620 Hz
                let f =
                    pitch * if k < 0.3 { 700.0 + 550.0 * k / 0.3 } else { 1250.0 - 630.0 * (k - 0.3) / 0.7 };
                ph[i] = (ph[i] + f / SR).fract();
                let p = TAU * ph[i];
                let v: f32 = (1..=4).map(|h| (h as f32 * p).sin() / (h as f32).powf(1.5)).sum();
                s += v * soft(u, dur, 0.025, 0.12);
            }
        }
        lp.low(s * 0.16)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use kira::info::MockInfoBuilder;

    fn play(bed: Arc<Bed>, blocks: usize) -> (Box<dyn Sound>, BedHandle, Vec<Frame>) {
        let (mut sound, handle) = BedData { bed, fade_in: 0.0, level: 1.0 }.into_sound().unwrap();
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

    /// 虫鸣的接缝：末尾一个采样和开头一个采样差得不比平时相邻采样大。
    #[test]
    fn bugs_are_quiet_and_seamless() {
        let bed = bugs();
        let peak = bed.pcm.iter().map(|&s| f32::from(s).abs() * bed.gain).fold(0.0, f32::max);
        assert!((0.01..0.2).contains(&peak), "峰值 {peak}");
        let typical =
            (1..bed.pcm.len() as i64).map(|i| (bed.at(i) - bed.at(i - 1)).abs()).fold(0.0, f32::max);
        assert!((bed.at(0) - bed.at(-1)).abs() <= typical);
    }

    #[test]
    fn calls_are_audible_and_not_clipped() {
        for (name, s) in [("owl", owl()), ("fox", fox())] {
            let peak = s.frames.iter().map(|f| f.left.abs()).fold(0.0, f32::max);
            assert!(peak > 0.01 && peak < 0.9, "{name} 峰值 {peak}");
        }
    }

    #[test]
    fn level_and_rate_follow_the_handle() {
        let bed = Arc::new(render(Scene::Night));
        let info = MockInfoBuilder::new().build();
        let mut block = [Frame::ZERO; 256];
        let (mut sound, mut handle, _) = play(Arc::clone(&bed), 4);
        handle.set_level(0.0, 0.01);
        handle.set_rate(0.8, 0.01);
        for _ in 0..20 {
            sound.on_start_processing();
            sound.process(&mut block, 1.0 / f64::from(SAMPLE_RATE), &info);
        }
        assert!(block.iter().all(|f| f.left.abs() < 1e-6), "音量降到 0 就没声");
        assert!(!sound.finished(), "音量为 0 不等于停了");
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
