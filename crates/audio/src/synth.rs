//! 离线合成（参照网页版 audio/engine.ts 的乐器）：启动时把乐器和音效一次性渲染成采样，
//! 运行时只播放。音色：古筝拨弦、编钟、太鼓、木鱼、锣，以及各种噪声做的风声、爆裂声。

use std::f32::consts::TAU;
use std::sync::Arc;

use kira::Frame;
use kira::sound::static_sound::{StaticSoundData, StaticSoundSettings};

pub const SAMPLE_RATE: u32 = 48_000;
const SR: f32 = SAMPLE_RATE as f32;

/// D 羽调五声音阶（D F G A C），pent(0) 是 D3。
pub fn pent(i: i32) -> f32 {
    const STEPS: [f32; 5] = [0.0, 3.0, 5.0, 7.0, 10.0];
    const ROOT: f32 = 146.83;
    let o = i.div_euclid(5);
    let s = STEPS[i.rem_euclid(5) as usize];
    ROOT * 2f32.powf(o as f32 + s / 12.0)
}

#[derive(Clone, Copy)]
pub enum Wave {
    Sine,
    Triangle,
}

#[derive(Clone, Copy)]
pub enum FilterKind {
    Low,
    High,
    Band,
}

#[derive(Clone, Copy)]
pub struct NoiseOpts {
    pub kind: FilterKind,
    pub freq: f32,
    pub slide: Option<f32>,
    pub q: f32,
    pub attack: f32,
}

impl Default for NoiseOpts {
    fn default() -> Self {
        NoiseOpts { kind: FilterKind::Band, freq: 1200.0, slide: None, q: 1.0, attack: 0.003 }
    }
}

/// 简单的 xorshift 噪声；固定种子，每次启动合成的音色一样。
pub struct Noise(pub u32);

impl Noise {
    pub fn next(&mut self) -> f32 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 17;
        self.0 ^= self.0 << 5;
        self.0 as f32 / u32::MAX as f32 * 2.0 - 1.0
    }
}

/// RBJ 双二阶滤波器。
struct Biquad {
    b0: f32,
    b1: f32,
    b2: f32,
    a1: f32,
    a2: f32,
    x1: f32,
    x2: f32,
    y1: f32,
    y2: f32,
}

impl Biquad {
    fn new() -> Self {
        Biquad { b0: 1.0, b1: 0.0, b2: 0.0, a1: 0.0, a2: 0.0, x1: 0.0, x2: 0.0, y1: 0.0, y2: 0.0 }
    }

    fn set(&mut self, kind: FilterKind, freq: f32, q: f32) {
        let w = TAU * freq.clamp(10.0, SR * 0.45) / SR;
        let (s, c) = w.sin_cos();
        let alpha = s / (2.0 * q.max(0.05));
        let (b0, b1, b2) = match kind {
            FilterKind::Low => ((1.0 - c) / 2.0, 1.0 - c, (1.0 - c) / 2.0),
            FilterKind::High => ((1.0 + c) / 2.0, -(1.0 + c), (1.0 + c) / 2.0),
            FilterKind::Band => (alpha, 0.0, -alpha),
        };
        let a0 = 1.0 + alpha;
        self.b0 = b0 / a0;
        self.b1 = b1 / a0;
        self.b2 = b2 / a0;
        self.a1 = -2.0 * c / a0;
        self.a2 = (1.0 - alpha) / a0;
    }

    fn run(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2;
        self.x2 = self.x1;
        self.x1 = x;
        self.y2 = self.y1;
        self.y1 = y;
        y
    }
}

/// 网页版的包络：指数起音到 vol，再指数衰减到几乎为零。
fn env(t: f32, vol: f32, attack: f32, dur: f32) -> f32 {
    const FLOOR: f32 = 0.0001;
    let vol = vol.max(0.0002);
    if t < 0.0 || t > dur {
        0.0
    } else if t < attack {
        FLOOR * (vol / FLOOR).powf(t / attack)
    } else {
        vol * (FLOOR / vol).powf((t - attack) / (dur - attack).max(1e-4))
    }
}

/// 一段单声道采样，往里面叠加各种声音。
pub struct Buf {
    pub data: Vec<f32>,
    noise: Noise,
}

impl Buf {
    pub fn new(secs: f32) -> Self {
        Buf { data: vec![0.0; (secs * SR) as usize], noise: Noise(0x2545_f491) }
    }

    /// 振荡器；slide 是 (目标频率, 用时)，指数滑音。
    pub fn osc(
        &mut self,
        wave: Wave,
        freq: f32,
        t0: f32,
        dur: f32,
        vol: f32,
        slide: Option<(f32, f32)>,
        attack: f32,
    ) {
        let start = (t0 * SR) as usize;
        let n = ((dur + 0.05) * SR) as usize;
        let mut phase = 0.0f32;
        for k in 0..n {
            let i = start + k;
            if i >= self.data.len() {
                break;
            }
            let t = k as f32 / SR;
            let f = match slide {
                Some((to, time)) => freq * (to / freq).powf((t / time).min(1.0)),
                None => freq,
            };
            phase = (phase + f / SR).fract();
            let s = match wave {
                Wave::Sine => (phase * TAU).sin(),
                Wave::Triangle => 1.0 - 4.0 * (phase - 0.5).abs(),
            };
            self.data[i] += s * env(t, vol, attack, dur);
        }
    }

    pub fn sine(&mut self, freq: f32, t0: f32, dur: f32, vol: f32) {
        self.osc(Wave::Sine, freq, t0, dur, vol, None, 0.004);
    }

    /// 滤波噪声。
    pub fn noise(&mut self, t0: f32, dur: f32, vol: f32, o: NoiseOpts) {
        let start = (t0 * SR) as usize;
        let n = ((dur + 0.05) * SR) as usize;
        let mut f = Biquad::new();
        for k in 0..n {
            let i = start + k;
            if i >= self.data.len() {
                break;
            }
            let t = k as f32 / SR;
            if k % 32 == 0 {
                let freq = match o.slide {
                    Some(to) => o.freq * (to / o.freq).powf((t / dur).min(1.0)),
                    None => o.freq,
                };
                f.set(o.kind, freq, o.q);
            }
            let x = self.noise.next();
            self.data[i] += f.run(x) * env(t, vol, o.attack, dur);
        }
    }

    pub fn to_sound(&self) -> StaticSoundData {
        let frames: Vec<Frame> = self.data.iter().map(|&s| Frame::from_mono(s.clamp(-1.0, 1.0))).collect();
        StaticSoundData {
            sample_rate: SAMPLE_RATE,
            frames: Arc::from(frames),
            settings: StaticSoundSettings::default(),
            slice: None,
        }
    }

    // ---- 乐器（与网页版 engine.ts 同名函数一致）----

    /// 古筝式拨弦：起音略高后回落，带泛音。
    pub fn pluck(&mut self, freq: f32, t: f32, vol: f32, decay: f32) {
        self.osc(Wave::Triangle, freq * 1.012, t, decay, vol, Some((freq, 0.06)), 0.003);
        self.sine(freq * 2.0, t, decay * 0.5, vol * 0.35);
        self.sine(freq * 3.0, t, decay * 0.25, vol * 0.12);
        let opts = NoiseOpts { freq: (freq * 4.0).min(8000.0), q: 2.0, ..Default::default() };
        self.noise(t, 0.03, vol * 0.25, opts);
    }

    /// 编钟：非整数倍泛音。
    pub fn bell(&mut self, freq: f32, t: f32, vol: f32, decay: f32) {
        self.sine(freq, t, decay, vol);
        self.sine(freq * 2.76, t, decay * 0.5, vol * 0.4);
        self.sine(freq * 5.4, t, decay * 0.25, vol * 0.18);
    }

    /// 太鼓。
    pub fn drum(&mut self, t: f32, vol: f32, pitch: f32) {
        self.osc(Wave::Sine, pitch, t, 0.45, vol, Some((pitch * 0.42, 0.3)), 0.004);
        self.noise(
            t,
            0.12,
            vol * 0.45,
            NoiseOpts { kind: FilterKind::Low, freq: 420.0, ..Default::default() },
        );
    }

    /// 木鱼。
    pub fn wood(&mut self, t: f32, vol: f32, pitch: f32) {
        self.sine(pitch, t, 0.08, vol);
        self.noise(t, 0.03, vol * 0.6, NoiseOpts { freq: pitch * 2.0, q: 6.0, ..Default::default() });
    }

    /// 锣。
    pub fn gong(&mut self, freq: f32, t: f32, vol: f32) {
        for (i, m) in [1.0, 1.48, 2.02, 2.74, 3.9].into_iter().enumerate() {
            let detune = 2f32.powf(self.noise.next() * 7.0 / 1200.0);
            self.osc(
                Wave::Sine,
                freq * m * detune,
                t,
                3.4 - i as f32 * 0.5,
                vol / (i + 1) as f32,
                None,
                0.01,
            );
        }
        self.noise(
            t,
            0.4,
            vol * 0.35,
            NoiseOpts { kind: FilterKind::Low, freq: 700.0, ..Default::default() },
        );
    }

    /// 末尾 2 毫秒淡出，避免截断时的爆音。
    pub fn finish(mut self) -> Self {
        let n = (SR * 0.002) as usize;
        let len = self.data.len();
        for k in 0..n.min(len) {
            self.data[len - 1 - k] *= k as f32 / n as f32;
        }
        self
    }
}

/// 只渲染一段：在 secs 长的缓冲里调用 f。
pub fn render(secs: f32, f: impl FnOnce(&mut Buf)) -> StaticSoundData {
    let mut b = Buf::new(secs);
    f(&mut b);
    b.finish().to_sound()
}

/// 独立噪声种子的材质变体，不改变其他音效的合成结果。
pub fn render_seeded(secs: f32, seed: u32, f: impl FnOnce(&mut Buf)) -> StaticSoundData {
    let mut b = Buf::new(secs);
    b.noise = Noise(seed.max(1));
    f(&mut b);
    b.finish().to_sound()
}

/// 可以无缝循环的低音持续音：两个三角波（频率取 0.25 Hz 的整数倍，4 秒正好整周期）经过低通。
pub fn drone(a: f32, b: f32) -> StaticSoundData {
    let q = |f: f32| (f * 4.0).round() / 4.0;
    let (a, b) = (q(a), q(b));
    let len = (4.0 * SR) as usize;
    let mut f = Biquad::new();
    f.set(FilterKind::Low, 500.0, 0.7);
    let tri = |p: f32| 1.0 - 4.0 * (p.fract() - 0.5).abs();
    // 先跑一个周期让滤波器稳定，再录下一周期
    let mut out = Vec::with_capacity(len);
    for i in 0..len * 2 {
        let t = (i % len) as f32 / SR;
        let x = (tri(a * t) + tri(b * t)) * 0.5;
        let y = f.run(x);
        if i >= len {
            out.push(Frame::from_mono(y * 0.9));
        }
    }
    StaticSoundData {
        sample_rate: SAMPLE_RATE,
        frames: Arc::from(out),
        settings: StaticSoundSettings::default().loop_region(..),
        slice: None,
    }
}
