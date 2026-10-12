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
}

fn noise(kind: FilterKind, freq: f32) -> NoiseOpts {
    NoiseOpts { kind, freq, ..Default::default() }
}

fn chest(n: usize) -> StaticSoundData {
    render(0.6 + n as f32 * 0.3 + 1.5, |b| {
        for i in 0..6 {
            let i = i as f32;
            b.wood(i * 0.045 * (1.0 - i * 0.08), 0.1, 700.0 + i * 60.0);
        }
        for i in 0..n {
            b.bell(pent(12 + i as i32 * 2), 0.35 + i as f32 * 0.28, 0.14, 1.4);
        }
    })
}

impl Sfx {
    pub fn new() -> Self {
        Sfx {
            hit: render(0.1, |b| b.noise(0.0, 0.035, 0.07, noise(FilterKind::High, 3300.0))),
            crit: render(0.15, |b| {
                b.noise(0.0, 0.035, 0.08, noise(FilterKind::High, 4200.0));
                b.wood(0.0, 0.05, 1400.0);
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
            combo: render(1.4, |b| {
                b.bell(pent(17), 0.0, 0.1, 1.0);
                b.bell(pent(20), 0.06, 0.08, 1.2);
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
