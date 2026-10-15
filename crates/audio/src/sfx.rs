//! 音效（移植自网页版 audio/sfx.ts）。启动时全部渲染好；每种音效有最短间隔，
//! 一帧几十次命中也不会叠成噪音。

use kira::sound::static_sound::StaticSoundData;

use crate::synth::{Buf, FilterKind, NoiseOpts, Wave, pent, render};

/// 渲染好的全部音效。
pub struct Sfx {
    pub hit: StaticSoundData,
    pub crit: StaticSoundData,
    pub kill: StaticSoundData,
    /// 拾取魂火：基准音 pent(10)，播放时按连拾次数升调
    pub gem: StaticSoundData,
    pub level_up: StaticSoundData,
    pub select: StaticSoundData,
    /// 宝箱 1 / 3 / 5 连
    pub chest: [StaticSoundData; 3],
    pub evolution: StaticSoundData,
    pub resonance: StaticSoundData,
    pub ult: StaticSoundData,
    pub ult_ready: StaticSoundData,
    pub dash: StaticSoundData,
    pub hurt: StaticSoundData,
    pub sword: StaticSoundData,
    pub crane: StaticSoundData,
    pub bell_pulse: StaticSoundData,
    pub big_bell: StaticSoundData,
    pub seal: StaticSoundData,
    pub blast: StaticSoundData,
    pub quake: StaticSoundData,
    pub warn: StaticSoundData,
    pub warn_big: StaticSoundData,
    pub soul_bell: StaticSoundData,
    pub heal: StaticSoundData,
    pub combo: StaticSoundData,
    pub event: StaticSoundData,
    pub coins: StaticSoundData,
    pub shield: StaticSoundData,
    pub victory: StaticSoundData,
    pub defeat: StaticSoundData,
    /// 盖章：朱砂印落下的闷响（共鸣跨阶、反应初见）
    pub stamp: StaticSoundData,
    /// 濒死的心跳（“咚、咚”）
    pub heart: StaticSoundData,
    /// 夜主倒下：低锣、太鼓、长长的余响
    pub boss_down: StaticSoundData,
    /// 天明：编钟和晨鸟
    pub dawn: StaticSoundData,
    /// 精英倒下：一声沉的
    pub elite_down: StaticSoundData,
    /// 无尽夜夜深一层：低处一声锣，一个音慢慢往下沉
    pub deeper: StaticSoundData,
    /// 竹丛打碎：一声脆的“咔嚓”，后面跟几下竹片的噼啪
    pub bamboo: StaticSoundData,
    /// 狐火烧平竹丛：呼地一下着起来，噼里啪啦
    pub burn: StaticSoundData,
    // 下面四个是界面上的事（卷轴、灯驿），界面发 UiCue 来播
    /// 开场卷轴展开：一声低的拨弦，纸沙沙地推开，推到头轴头一磕
    pub scroll_unroll: StaticSoundData,
    /// 卷轴旁白浮出一行：很轻的一声高音（按行升调播放）
    pub scroll_line: StaticSoundData,
    /// 灯驿里点亮一盏心灯：呼地着起来，一个暖的和音
    pub lamp_lit: StaticSoundData,
    /// 灯驿远山晨光铺开：一串往上走的拨弦，末尾几声鸟叫
    pub dawn_spread: StaticSoundData,
}

/// 一声鸟叫：两三个快速上滑的短音。
fn chirp(b: &mut Buf, t: f32, base: f32, vol: f32) {
    for k in 0..3 {
        let t = t + k as f32 * 0.075;
        let f = base * (1.0 + k as f32 * 0.06);
        b.osc(Wave::Sine, f, t, 0.055, vol, Some((f * 1.45, 0.045)), 0.004);
    }
}

fn noise(kind: FilterKind, freq: f32) -> NoiseOpts {
    NoiseOpts { kind, freq, ..Default::default() }
}

fn chest(n: usize) -> StaticSoundData {
    let gold = n >= 5;
    render(0.6 + n as f32 * 0.3 + if gold { 2.6 } else { 1.5 }, |b| {
        for i in 0..6 {
            let i = i as f32;
            b.wood(i * 0.045 * (1.0 - i * 0.08), 0.1, 700.0 + i * 60.0);
        }
        for i in 0..n {
            b.bell(pent(12 + i as i32 * 2), 0.35 + i as f32 * 0.28, 0.14, 1.4);
        }
        // 五连：五声之后一记金光，D 和 A 的空五度从低往高扫上去，落定（界面上整卷泛金光）
        if gold {
            let t = 0.35 + n as f32 * 0.28;
            for (j, d) in [10, 13, 15, 18].into_iter().enumerate() {
                b.bell(pent(d), t + j as f32 * 0.04, 0.09, 2.4);
            }
            b.sine(pent(20), t + 0.12, 0.9, 0.025);
        }
    })
}

impl Sfx {
    pub fn new() -> Self {
        Sfx {
            hit: render(0.1, |b| b.noise(0.0, 0.035, 0.07, noise(FilterKind::High, 3300.0))),
            // 暴击：清脆的金属声（docs/GAMEPLAY.md 第 14 节）
            crit: render(0.5, |b| {
                b.noise(0.0, 0.03, 0.09, noise(FilterKind::High, 5200.0));
                b.bell(2350.0, 0.0, 0.05, 0.35);
                b.sine(4980.0, 0.0, 0.12, 0.025);
                b.wood(0.0, 0.05, 1500.0);
            }),
            kill: render(0.2, |b| b.osc(Wave::Sine, 285.0, 0.0, 0.12, 0.1, Some((85.0, 0.12)), 0.004)),
            gem: render(0.25, |b| {
                let f = pent(10);
                b.sine(f, 0.0, 0.18, 0.06);
                b.osc(Wave::Triangle, f * 2.0, 0.0, 0.08, 0.025, None, 0.004);
            }),
            level_up: render(2.2, |b| {
                for (i, d) in [10, 12, 13, 15, 17].into_iter().enumerate() {
                    b.pluck(pent(d), i as f32 * 0.06, 0.16, 0.9);
                }
                b.bell(pent(20), 0.32, 0.08, 1.6);
            }),
            select: render(1.0, |b| {
                b.pluck(pent(12), 0.0, 0.18, 0.8);
                b.pluck(pent(15), 0.05, 0.14, 0.8);
            }),
            chest: [chest(1), chest(3), chest(5)],
            evolution: render(4.0, |b| {
                b.gong(73.4, 0.0, 0.32);
                b.drum(0.0, 0.6, 90.0);
                for (i, d) in [5, 7, 10, 12, 15, 17, 20].into_iter().enumerate() {
                    b.pluck(pent(d), 0.1 + i as f32 * 0.07, 0.15, 1.0);
                }
                b.bell(pent(22), 0.7, 0.12, 2.5);
            }),
            resonance: render(2.0, |b| {
                for (i, d) in [12, 15, 17].into_iter().enumerate() {
                    b.pluck(pent(d), i as f32 * 0.08, 0.13, 1.0);
                }
                b.bell(pent(19), 0.24, 0.07, 1.5);
            }),
            ult: render(4.0, |b| {
                b.noise(
                    0.0,
                    0.4,
                    0.25,
                    NoiseOpts {
                        kind: FilterKind::High,
                        freq: 400.0,
                        slide: Some(5000.0),
                        q: 1.0,
                        attack: 0.3,
                    },
                );
                b.drum(0.33, 0.9, 70.0);
                b.noise(
                    0.33,
                    0.9,
                    0.3,
                    NoiseOpts {
                        kind: FilterKind::Low,
                        freq: 900.0,
                        slide: Some(120.0),
                        ..Default::default()
                    },
                );
                b.gong(55.0, 0.33, 0.22);
            }),
            ult_ready: render(1.6, |b| {
                b.bell(pent(15), 0.0, 0.08, 1.2);
                b.bell(pent(20), 0.1, 0.07, 1.4);
            }),
            dash: render(0.3, |b| {
                b.noise(
                    0.0,
                    0.18,
                    0.14,
                    NoiseOpts { freq: 700.0, slide: Some(3200.0), q: 1.4, ..Default::default() },
                )
            }),
            hurt: render(0.4, |b| {
                b.osc(Wave::Sine, 190.0, 0.0, 0.25, 0.28, Some((60.0, 0.25)), 0.004);
                b.noise(0.0, 0.12, 0.15, noise(FilterKind::Low, 600.0));
            }),
            sword: render(0.15, |b| {
                b.noise(
                    0.0,
                    0.07,
                    0.045,
                    NoiseOpts {
                        kind: FilterKind::High,
                        freq: 4500.0,
                        slide: Some(7000.0),
                        ..Default::default()
                    },
                )
            }),
            crane: render(0.15, |b| {
                b.noise(
                    0.0,
                    0.06,
                    0.04,
                    NoiseOpts { freq: 1800.0, slide: Some(900.0), q: 2.0, ..Default::default() },
                )
            }),
            bell_pulse: render(1.4, |b| b.bell(pent(15), 0.0, 0.06, 1.1)),
            big_bell: render(3.2, |b| {
                b.bell(pent(5), 0.0, 0.22, 3.0);
                b.bell(pent(10), 0.02, 0.12, 2.5);
            }),
            seal: render(0.6, |b| b.drum(0.0, 0.22, 95.0)),
            blast: render(0.3, |b| {
                b.osc(Wave::Sine, 130.0, 0.0, 0.2, 0.1, Some((50.0, 0.2)), 0.004);
                b.noise(0.0, 0.15, 0.07, noise(FilterKind::Low, 900.0));
            }),
            quake: render(1.0, |b| {
                b.drum(0.0, 0.5, 70.0);
                b.noise(
                    0.0,
                    0.5,
                    0.2,
                    NoiseOpts { kind: FilterKind::Low, freq: 500.0, slide: Some(80.0), ..Default::default() },
                );
            }),
            warn: render(1.1, |b| {
                for i in 0..2 {
                    b.drum(i as f32 * 0.24, 0.55, 95.0);
                }
            }),
            warn_big: render(4.2, |b| {
                for i in 0..3 {
                    b.drum(i as f32 * 0.24, 0.55, 75.0);
                }
                b.gong(49.0, 0.72, 0.28);
            }),
            soul_bell: render(1.4, |b| {
                for i in 0..8 {
                    b.bell(pent(12 + i), i as f32 * 0.045, 0.06, 0.9);
                }
            }),
            heal: render(1.4, |b| {
                b.bell(pent(14), 0.0, 0.1, 1.2);
                b.bell(pent(17), 0.08, 0.08, 1.2);
            }),
            // 连斩：鼓点 + 钟
            combo: render(1.8, |b| {
                b.drum(0.0, 0.5, 92.0);
                b.drum(0.14, 0.42, 92.0);
                b.drum(0.3, 0.65, 70.0);
                b.bell(pent(17), 0.3, 0.1, 1.0);
                b.bell(pent(20), 0.36, 0.08, 1.2);
            }),
            event: render(2.2, |b| {
                b.bell(pent(13), 0.0, 0.12, 1.6);
                b.bell(pent(16), 0.18, 0.1, 1.8);
            }),
            coins: render(0.6, |b| {
                for i in 0..10 {
                    b.sine(pent(15 + (i % 5)) * 2.0, i as f32 * 0.035, 0.12, 0.05);
                }
            }),
            shield: render(0.8, |b| {
                b.bell(pent(8), 0.0, 0.06, 0.6);
                b.noise(0.0, 0.2, 0.05, noise(FilterKind::Band, 1500.0));
            }),
            victory: render(4.8, |b| {
                let notes = [
                    (10, 0.0),
                    (12, 0.25),
                    (14, 0.5),
                    (17, 0.75),
                    (15, 1.1),
                    (14, 1.35),
                    (12, 1.6),
                    (15, 1.85),
                    (20, 2.3),
                ];
                for (d, at) in notes {
                    b.pluck(pent(d), 0.1 + at, 0.18, 1.4);
                }
                b.gong(73.4, 2.4, 0.2);
            }),
            stamp: render(0.9, |b| {
                b.drum(0.0, 0.5, 62.0);
                b.wood(0.0, 0.14, 330.0);
                b.noise(0.0, 0.07, 0.22, noise(FilterKind::Low, 380.0));
            }),
            heart: render(0.6, |b| {
                b.osc(Wave::Sine, 64.0, 0.0, 0.13, 0.55, Some((42.0, 0.12)), 0.004);
                b.osc(Wave::Sine, 60.0, 0.2, 0.11, 0.38, Some((40.0, 0.1)), 0.004);
                b.noise(0.0, 0.05, 0.06, noise(FilterKind::Low, 180.0));
            }),
            bamboo: render(0.5, |b| {
                b.noise(0.0, 0.035, 0.22, noise(FilterKind::High, 2600.0));
                b.wood(0.0, 0.14, 1250.0);
                b.wood(0.018, 0.1, 1650.0);
                b.wood(0.045, 0.08, 900.0);
                b.wood(0.0, 0.07, 320.0);
                for (k, t) in [0.08, 0.12, 0.17, 0.23].into_iter().enumerate() {
                    b.noise(t, 0.012, 0.09 - k as f32 * 0.018, noise(FilterKind::High, 3800.0));
                }
            }),
            scroll_unroll: render(3.4, |b| {
                b.pluck(pent(5), 0.0, 0.11, 2.6);
                b.pluck(pent(10), 0.02, 0.05, 2.2);
                // 纸响：一串短的带通噪声颗粒，越推越轻
                for k in 0..18 {
                    let t = 0.05 + k as f32 * 0.095 + (k * 53 % 7) as f32 * 0.008;
                    let f = 2200.0 + (k * 211 % 9) as f32 * 220.0;
                    let vol = 0.05 * (1.0 - k as f32 / 22.0);
                    b.noise(
                        t,
                        0.07 + (k % 3) as f32 * 0.02,
                        vol,
                        NoiseOpts { freq: f, q: 1.6, ..Default::default() },
                    );
                }
                b.wood(1.8, 0.09, 380.0);
                b.wood(1.84, 0.05, 520.0);
            }),
            scroll_line: render(1.6, |b| {
                b.bell(pent(15), 0.0, 0.035, 1.4);
                b.sine(pent(20), 0.02, 0.35, 0.008);
            }),
            lamp_lit: render(2.6, |b| {
                b.noise(
                    0.0,
                    0.35,
                    0.12,
                    NoiseOpts {
                        kind: FilterKind::Low,
                        freq: 200.0,
                        slide: Some(1600.0),
                        attack: 0.05,
                        ..Default::default()
                    },
                );
                for (i, d) in [10, 14, 17].into_iter().enumerate() {
                    b.bell(pent(d), 0.12 + i as f32 * 0.05, 0.06, 2.2);
                }
                for k in 0..4 {
                    b.noise(0.2 + k as f32 * 0.13, 0.01, 0.03, noise(FilterKind::High, 3400.0));
                }
            }),
            dawn_spread: render(4.5, |b| {
                for (i, d) in [10, 12, 13, 15, 17, 18, 20].into_iter().enumerate() {
                    b.pluck(pent(d), i as f32 * 0.32, 0.07, 2.4);
                }
                for (t, f) in [(2.4, 3600.0), (2.75, 4100.0), (3.3, 3800.0)] {
                    chirp(b, t, f, 0.035);
                }
            }),
            burn: render(2.2, |b| {
                b.noise(
                    0.0,
                    1.1,
                    0.2,
                    NoiseOpts {
                        kind: FilterKind::Low,
                        freq: 300.0,
                        slide: Some(2400.0),
                        attack: 0.25,
                        ..Default::default()
                    },
                );
                for k in 0..14 {
                    let t = 0.15 + k as f32 * 0.11 + (k * 37 % 7) as f32 * 0.013;
                    b.noise(t, 0.01, 0.06, noise(FilterKind::High, 3000.0 + (k * 131 % 5) as f32 * 400.0));
                }
            }),
            deeper: render(5.0, |b| {
                b.gong(36.7, 0.0, 0.2);
                b.bell(pent(0), 0.0, 0.05, 3.5);
                // 从 D4 沉到 D3
                b.osc(Wave::Sine, pent(5), 0.05, 3.0, 0.07, Some((pent(0), 2.6)), 0.08);
                b.noise(
                    0.0,
                    2.4,
                    0.08,
                    NoiseOpts { kind: FilterKind::Low, freq: 400.0, slide: Some(80.0), ..Default::default() },
                );
            }),
            boss_down: render(6.0, |b| {
                b.gong(41.2, 0.0, 0.3);
                b.drum(0.0, 0.5, 52.0);
                b.drum(0.35, 0.32, 48.0);
                b.noise(
                    0.0,
                    1.6,
                    0.18,
                    NoiseOpts { kind: FilterKind::Low, freq: 600.0, slide: Some(60.0), ..Default::default() },
                );
            }),
            dawn: render(6.0, |b| {
                for (i, d) in [15, 19, 22].into_iter().enumerate() {
                    b.bell(pent(d), i as f32 * 0.45, 0.17 - i as f32 * 0.025, 3.2);
                }
                let birds = [
                    (1.1, 3400.0),
                    (1.6, 3900.0),
                    (1.85, 3600.0),
                    (2.5, 4200.0),
                    (3.1, 3500.0),
                    (3.4, 4000.0),
                ];
                for (t, f) in birds {
                    chirp(b, t, f, 0.045);
                }
            }),
            elite_down: render(1.2, |b| {
                b.drum(0.0, 0.55, 75.0);
                b.osc(Wave::Sine, 220.0, 0.0, 0.3, 0.12, Some((70.0, 0.3)), 0.004);
                b.noise(0.0, 0.25, 0.12, noise(FilterKind::Low, 700.0));
            }),
            defeat: render(4.0, |b| {
                let notes = [(14, 0.0), (12, 0.45), (11, 0.9), (9, 1.35), (5, 1.9)];
                for (d, at) in notes {
                    b.pluck(pent(d), 0.1 + at, 0.16, 1.8);
                }
                b.drum(2.0, 0.3, 70.0);
            }),
        }
    }
}

/// 音乐用的乐器样本：按基准音高渲染，播放时变速换调。
pub struct Instruments {
    /// 拨弦（基准 pent(0) = D3），三种余音长短
    pub pluck: [StaticSoundData; 3],
    pub pluck_decays: [f32; 3],
    /// 木鱼（基准 900 Hz）
    pub wood: StaticSoundData,
    /// 太鼓（基准 100 Hz）
    pub drum: StaticSoundData,
    /// 锣（基准 49 Hz）
    pub gong: StaticSoundData,
}

impl Instruments {
    pub fn new() -> Self {
        let decays = [1.1, 1.6, 1.8];
        let pluck = decays.map(|d| render(d + 0.1, |b: &mut Buf| b.pluck(pent(0), 0.0, 1.0, d)));
        Instruments {
            pluck,
            pluck_decays: decays,
            wood: render(0.15, |b| b.wood(0.0, 1.0, 900.0)),
            drum: render(0.6, |b| b.drum(0.0, 1.0, 100.0)),
            gong: render(3.6, |b| b.gong(49.0, 0.0, 1.0)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 每个音效都要有声音，而且基本不削波（合成时已经夹在 ±1，碰到边就是削波了）。
    #[test]
    fn sounds_are_audible_and_not_clipped() {
        let s = Sfx::new();
        let all: [(&str, &StaticSoundData); 22] = [
            ("chest5", &s.chest[2]),
            ("deeper", &s.deeper),
            ("bamboo", &s.bamboo),
            ("burn", &s.burn),
            ("scroll_unroll", &s.scroll_unroll),
            ("scroll_line", &s.scroll_line),
            ("lamp_lit", &s.lamp_lit),
            ("dawn_spread", &s.dawn_spread),
            ("crit", &s.crit),
            ("combo", &s.combo),
            ("stamp", &s.stamp),
            ("heart", &s.heart),
            ("boss_down", &s.boss_down),
            ("dawn", &s.dawn),
            ("elite_down", &s.elite_down),
            ("hit", &s.hit),
            ("kill", &s.kill),
            ("ult", &s.ult),
            ("evolution", &s.evolution),
            ("victory", &s.victory),
            ("warn_big", &s.warn_big),
            ("hurt", &s.hurt),
        ];
        for (name, sound) in all {
            let peak = sound.frames.iter().map(|f| f.left.abs()).fold(0.0, f32::max);
            let clipped = sound.frames.iter().filter(|f| f.left.abs() >= 0.999).count();
            assert!(peak > 0.01, "{name} 没有声音（峰值 {peak}）");
            assert!(clipped <= 2, "{name} 削波 {clipped} 个采样（峰值 {peak}）");
        }
    }
}
