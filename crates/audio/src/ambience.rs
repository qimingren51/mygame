//! 夜里的环境声（docs/FEEL.md 第 6 节）：风一阵紧一阵松、草里的虫鸣，偶尔远处一声鸮啼；
//! 夜主快来时，远处的狐鸣一声比一声近。跟着局势变：
//! - 夜主登场，虫声一下子停了，风紧起来——万籁俱寂；夜主退去 20 秒后虫声慢慢回来；
//! - 妖潮来时虫声停一阵；
//! - 天明后虫声不再回来，风也小了（晨鸟由天明的音效接上）；
//! - 无尽夜每深一层，风声低一点、虫声弱一点；
//! - 升级选择、暂停时整体压低。
//!
//! 全部代码合成：风和虫鸣各是一段能无缝循环的立体声，循环播放；鸟兽的叫声是单发的。
//! 都走音效轨（音量跟音效设置，也一起送混响、一起静半拍）。用现实时间，不碰模拟。

use std::f32::consts::{FRAC_PI_2, PI, TAU};
use std::sync::Arc;
use std::time::Duration;

use bevy::prelude::*;
use kira::sound::static_sound::{StaticSoundData, StaticSoundHandle, StaticSoundSettings};
use kira::{Decibels, Frame, Panning, Tween};

use lantern_core::Pcg32;
use lantern_core::step::TICK_HZ;
use lantern_sim::{AppState, Director, RunState, SimEvent, SimOutbox, SimPhase, Tick};

use crate::Audio;
use crate::synth::{Noise, SAMPLE_RATE};

const SR: f32 = SAMPLE_RATE as f32;

/// 风和虫鸣在一局里的音量（分贝，相对音效轨；音效轨本身另提了 7 分贝）。
const WIND_DB: f32 = -14.0;
const BUGS_DB: f32 = -12.0;
/// 标题画面：远一些、轻一些
const TITLE_DB: f32 = -5.0;
/// 夜主在场时风紧一点
const BOSS_WIND: f32 = 4.0;
/// 天明后风小一些
const DAWN_WIND: f32 = -6.0;
/// 升级选择、暂停时压低
const MENU_DB: f32 = -8.0;
/// 无尽夜每深一层：风的音高 × (1 − 这么多)，虫声低这么多分贝
const DEEP_RATE: f32 = 0.05;
const DEEP_BUGS: f32 = 3.0;
/// 夜主退去、妖潮过后，虫声多久回来（秒）
const BUGS_BACK: f64 = 20.0;
const SURGE_HUSH: f64 = 18.0;
/// 狐鸣：几秒起开始有，到几秒最密（夜主 9:30 登场）
const FOX_FROM: f32 = 360.0;
const FOX_PEAK: f32 = 560.0;

pub(crate) struct Ambience {
    wind: StaticSoundData,
    bugs: StaticSoundData,
    owl: StaticSoundData,
    fox: StaticSoundData,
    wind_h: Option<StaticSoundHandle>,
    bugs_h: Option<StaticSoundHandle>,
    rng: Pcg32,
    title: bool,
    /// 天明以后
    dawn: bool,
    /// 虫声在这个时刻之前保持安静（妖潮、夜主刚退去）
    hush_until: f64,
    boss: bool,
    depth: u32,
    /// 下一声鸟兽叫的时刻
    next_call: f64,
    /// 上一次发给播放器的目标（变了才发，免得每帧发命令）
    sent: (f32, f32, f32),
}

impl Ambience {
    pub(crate) fn new() -> Self {
        Ambience {
            wind: wind(),
            bugs: bugs(),
            owl: owl(),
            fox: fox(),
            wind_h: None,
            bugs_h: None,
            rng: Pcg32::new(0x0a3b_1e57, 5),
            title: false,
            dawn: false,
            hush_until: 0.0,
            boss: false,
            depth: 0,
            next_call: 0.0,
            sent: (f32::NAN, f32::NAN, f32::NAN),
        }
    }
}

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Title), |time: Res<Time<Real>>, mut a: NonSendMut<Audio>| {
        start(&mut a, true, time.elapsed_secs_f64())
    })
    .add_systems(OnEnter(AppState::Run), |time: Res<Time<Real>>, mut a: NonSendMut<Audio>| {
        start(&mut a, false, time.elapsed_secs_f64())
    })
    .add_systems(OnExit(AppState::Title), |mut a: NonSendMut<Audio>| stop(&mut a, 0.8))
    .add_systems(OnExit(AppState::Run), |mut a: NonSendMut<Audio>| stop(&mut a, 2.0))
    .add_systems(
        Update,
        update.run_if(|s: Option<Res<State<AppState>>>| {
            s.is_some_and(|s| matches!(s.get(), AppState::Title | AppState::Run))
        }),
    );
}

fn tween(secs: f32) -> Tween {
    Tween { duration: Duration::from_secs_f32(secs), ..Default::default() }
}

fn start(audio: &mut Audio, title: bool, now: f64) {
    stop(audio, 0.5);
    let Audio { ambience: a, sfx_track, .. } = audio;
    let Some(track) = sfx_track else { return };
    a.title = title;
    a.dawn = false;
    a.boss = false;
    a.depth = 0;
    a.hush_until = 0.0;
    a.next_call = now + f64::from(a.rng.range_f32(8.0, 20.0));
    a.sent = (f32::NAN, f32::NAN, f32::NAN);
    a.wind_h = track.play(a.wind.volume(Decibels::SILENCE)).ok();
    a.bugs_h = track.play(a.bugs.volume(Decibels::SILENCE)).ok();
}

fn stop(audio: &mut Audio, secs: f32) {
    let a = &mut audio.ambience;
    for mut h in [a.wind_h.take(), a.bugs_h.take()].into_iter().flatten() {
        h.stop(tween(secs));
    }
}

fn update(
    time: Res<Time<Real>>,
    outbox: Option<Res<SimOutbox>>,
    tick: Option<Res<Tick>>,
    director: Option<Res<Director>>,
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    mut audio: NonSendMut<Audio>,
) {
    let now = time.elapsed_secs_f64();
    let Audio { ambience: a, sfx_track, .. } = &mut *audio;
    if !a.title {
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
    let menu = !a.title
        && (phase.as_deref().is_some_and(|p| *p != SimPhase::Play)
            || run.is_some_and(|r| *r.get() != RunState::Playing));

    // ---- 目标音量
    let base = if a.title { TITLE_DB } else { 0.0 } + if menu { MENU_DB } else { 0.0 };
    let wind_db =
        WIND_DB + base + if a.boss { BOSS_WIND } else { 0.0 } + if a.dawn { DAWN_WIND } else { 0.0 };
    let quiet = a.boss || a.dawn || now < a.hush_until;
    let bugs_db = if quiet { f32::NEG_INFINITY } else { BUGS_DB + base - DEEP_BUGS * a.depth as f32 };
    let rate = 1.0 - DEEP_RATE * a.depth as f32;
    let target = (wind_db, bugs_db, rate);
    if target != a.sent {
        // 刚开始：慢慢淡入
        let first = a.sent.0.is_nan();
        let was_quiet = a.sent.1 == f32::NEG_INFINITY;
        a.sent = target;
        if let Some(h) = &mut a.wind_h {
            h.set_volume(wind_db, tween(if a.boss && !first { 1.0 } else { 3.0 }));
            h.set_playback_rate(f64::from(rate), tween(3.0));
        }
        if let Some(h) = &mut a.bugs_h {
            // 停要停得干脆（夜主登场那一下），回来要慢
            let (vol, secs) = if quiet {
                (Decibels::SILENCE, if a.boss { 0.8 } else { 1.5 })
            } else {
                (
                    Decibels(bugs_db),
                    if was_quiet {
                        6.0
                    } else if first {
                        4.0
                    } else {
                        1.5
                    },
                )
            };
            h.set_volume(vol, tween(secs));
        }
    }

    // ---- 远处偶尔一声：平时是鸮，夜主快来时换成狐，越来越密；夜主在场、天明以后不叫
    if now < a.next_call {
        return;
    }
    let secs = tick.map_or(0.0, |t| t.0 as f32 / TICK_HZ as f32);
    let fox_k = if a.title { 0.0 } else { ((secs - FOX_FROM) / (FOX_PEAK - FOX_FROM)).clamp(0.0, 1.0) };
    let gap = if fox_k > 0.0 { 30.0 - 16.0 * fox_k } else { 34.0 };
    a.next_call = now + f64::from(gap * a.rng.range_f32(0.7, 1.4));
    if menu || a.boss || a.dawn {
        return;
    }
    let Some(track) = sfx_track else { return };
    let fox = fox_k > 0.0 && a.rng.chance(0.35 + 0.6 * fox_k);
    let (data, vol) = if fox {
        // 越近越响
        (&a.fox, -16.0 + 7.0 * fox_k)
    } else {
        (&a.owl, if a.title { -20.0 } else { -17.0 })
    };
    let pan = a.rng.range_f32(-0.7, 0.7);
    let rate = f64::from(a.rng.range_f32(0.94, 1.06));
    let _ = track.play(data.playback_rate(rate).volume(Decibels(vol)).panning(Panning(pan)));
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

/// 立体声缓冲做成能无缝循环的一段：多渲染 xf 秒，把尾巴等功率交叉淡入到开头。
fn seamless(l: &[f32], r: &[f32], len: usize, xf: usize) -> StaticSoundData {
    let frames: Vec<Frame> = (0..len)
        .map(|i| {
            let (mut fl, mut fr) = (l[i], r[i]);
            if i < xf {
                let k = i as f32 / xf as f32 * FRAC_PI_2;
                fl = fl * k.sin() + l[len + i] * k.cos();
                fr = fr * k.sin() + r[len + i] * k.cos();
            }
            Frame { left: fl.clamp(-1.0, 1.0), right: fr.clamp(-1.0, 1.0) }
        })
        .collect();
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(frames),
        settings: StaticSoundSettings::default().loop_region(..),
        slice: None,
    }
}

/// 风：低处一层呼呼的底子，阵风时上面多一道呜呜的哨音。阵风的起伏以 20 秒为周期，正好接上。
fn wind() -> StaticSoundData {
    const LEN: f32 = 20.0;
    const XF: f32 = 2.0;
    let (len, xf) = ((LEN * SR) as usize, (XF * SR) as usize);
    let n = len + xf;
    let gust = |t: f32| {
        let p = TAU * t / LEN;
        (0.55 + 0.25 * (p + 0.7).sin() + 0.14 * (3.0 * p + 2.1).sin() + 0.06 * (7.0 * p + 0.4).sin())
            .clamp(0.1, 1.0)
    };
    let (mut nl, mut nr) = (Noise(0x1d2c_3b4a), Noise(0x5e6f_7081));
    let (mut l1, mut l2, mut r1, mut r2) =
        (OnePole::new(260.0), OnePole::new(260.0), OnePole::new(260.0), OnePole::new(260.0));
    let (mut wl, mut wr) = (Svf::default(), Svf::default());
    let (mut low_l, mut low_r, mut hi_l, mut hi_r) =
        (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
    for i in 0..n {
        let t = i as f32 / SR;
        let g = gust(t);
        let (a, b) = (nl.next(), nr.next());
        // 两边的噪声大半独立、带一点相关，听起来宽而不散
        let (xl, xr) = (a, 0.75 * b + 0.25 * a);
        low_l.push(l2.low(l1.low(xl)) * (0.35 + 0.65 * g));
        low_r.push(r2.low(r1.low(xr)) * (0.35 + 0.65 * g));
        let f = 420.0 + 680.0 * g;
        let w = g * g * g;
        hi_l.push(wl.band(xl, f, 7.0) * w);
        hi_r.push(wr.band(xr, f * 1.04, 7.0) * w);
    }
    let (kl, kh) = (0.07 / rms(&low_l).max(1e-6), 0.022 / rms(&hi_l).max(1e-6));
    let l: Vec<f32> = low_l.iter().zip(&hi_l).map(|(a, b)| a * kl + b * kh).collect();
    let r: Vec<f32> = low_r.iter().zip(&hi_r).map(|(a, b)| a * kl + b * kh).collect();
    seamless(&l, &r, len, xf)
}

/// 虫鸣：几只蟋蟀（各自的音高、节奏、远近、左右），一串一串地叫，偶尔歇一会儿；
/// 底下一层很淡的远处虫声（6.5 kHz 一带的窄带噪声按 42 Hz 颤动）。16 秒一循环。
fn bugs() -> StaticSoundData {
    const LEN: f32 = 16.0;
    const XF: f32 = 1.5;
    let (len, xf) = ((LEN * SR) as usize, (XF * SR) as usize);
    let n = len + xf;
    let (mut l, mut r) = (vec![0.0f32; n], vec![0.0f32; n]);
    let mut rng = Pcg32::new(0x00c1_c4e7, 3);
    // （音高 Hz，一串几声，一串的间隔秒，响度，左右）
    let voices = [
        (4300.0, 3, 0.85, 1.0, -0.55),
        (4720.0, 4, 1.15, 0.7, 0.45),
        (5080.0, 3, 0.7, 0.45, 0.8),
        (3920.0, 5, 1.35, 0.35, -0.15),
    ];
    const PULSE: f32 = 0.014;
    const GAP: f32 = 0.022;
    for (freq, pulses, every, loud, pan) in voices {
        let (gl, gr) = {
            let p = (pan + 1.0) * PI / 4.0;
            (p.cos(), p.sin())
        };
        let mut t = rng.range_f32(0.0, every);
        let train = pulses as f32 * (PULSE + GAP);
        while t + train < LEN {
            // 偶尔歇一会儿
            if rng.chance(0.08) {
                t += rng.range_f32(1.5, 3.5);
                continue;
            }
            let amp = loud * rng.range_f32(0.75, 1.1);
            for p in 0..pulses {
                let t0 = t + p as f32 * (PULSE + GAP);
                let (s0, m) = ((t0 * SR) as usize, (PULSE * SR) as usize);
                for k in 0..m {
                    let u = k as f32 / m as f32;
                    let e = (PI * u).sin().powi(2) * amp;
                    let ph = TAU * freq * (t0 + k as f32 / SR);
                    let s = (ph.sin() + 0.15 * (3.0 * ph).sin()) * e;
                    l[s0 + k] += s * gl;
                    r[s0 + k] += s * gr;
                }
            }
            t += every * rng.range_f32(0.85, 1.2);
        }
    }
    let k = 0.05 / rms(&l).max(rms(&r)).max(1e-6);
    // 远处的虫声：6.5 kHz 一带的窄带噪声（不是满频带的沙沙声），42 Hz 颤动，8 秒一起伏（两个周期正好一循环）
    let (mut na, mut nb) = (Noise(0x7a8b_9cad), Noise(0x3141_5926));
    let (mut fa, mut fb) = (Svf::default(), Svf::default());
    let mut bed_l = Vec::with_capacity(n);
    let mut bed_r = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f32 / SR;
        let am = (0.5 + 0.5 * (TAU * 42.0 * t).sin()) * (0.6 + 0.4 * (TAU * t / 8.0).sin());
        bed_l.push(fa.band(na.next(), 6500.0, 5.0) * am);
        bed_r.push(fb.band(nb.next(), 6300.0, 5.0) * am);
    }
    let kb = 0.008 / rms(&bed_l).max(1e-6);
    for i in 0..n {
        l[i] = l[i] * k + bed_l[i] * kb;
        r[i] = r[i] * k + bed_r[i] * kb;
    }
    seamless(&l, &r, len, xf)
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
    let raw = mono(1.2, move |t| {
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
        s * 0.16
    });
    // 隔着林子：一阶低通 2.2 kHz
    let mut lp = OnePole::new(2200.0);
    let frames: Vec<Frame> = raw.frames.iter().map(|f| Frame::from_mono(lp.low(f.left))).collect();
    StaticSoundData { frames: Arc::from(frames), ..raw }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn peak(s: &StaticSoundData) -> f32 {
        s.frames.iter().map(|f| f.left.abs().max(f.right.abs())).fold(0.0, f32::max)
    }

    #[test]
    fn ambience_is_audible_and_not_clipped() {
        for (name, s) in [("wind", wind()), ("bugs", bugs()), ("owl", owl()), ("fox", fox())] {
            let p = peak(&s);
            assert!(p > 0.01 && p < 0.9, "{name} 峰值 {p}");
        }
    }

    /// 循环的接缝处不能有跳变：末尾一个采样和开头一个采样差得不比平时相邻采样大多少。
    #[test]
    fn loops_are_seamless() {
        for (name, s) in [("wind", wind()), ("bugs", bugs())] {
            let f = &s.frames;
            let step = |a: &Frame, b: &Frame| (a.left - b.left).abs().max((a.right - b.right).abs());
            let typical = f.windows(2).map(|w| step(&w[0], &w[1])).fold(0.0, f32::max);
            let seam = step(&f[f.len() - 1], &f[0]);
            assert!(seam <= typical, "{name} 接缝 {seam}，平时最大 {typical}");
        }
    }
}
