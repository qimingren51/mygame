//! 音效（移植自网页版 audio/sfx.ts）。启动时全部渲染好；每种音效有最短间隔，
//! 一帧几十次命中也不会叠成噪音。

use kira::sound::static_sound::StaticSoundData;
use lantern_content::WeaponIdentity;

use crate::impact::VARIANTS;
use crate::synth::{Buf, FilterKind, NoiseOpts, Wave, jiao, render, render_seeded};

/// 渲染好的全部音效。
pub struct Sfx {
    /// 没有法器的命中（燃灯、爆炸、冲撞）用的通用命中声
    pub hit: StaticSoundData,
    /// 法器 × 普通/暴击 × 三种材质纹理（洗牌轮换见 [`crate::impact`]）
    pub impacts: [[[StaticSoundData; VARIANTS]; 2]; 5],
    pub crit: StaticSoundData,
    /// 菜单：换一项、确认、返回（走界面总线）
    pub ui_move: StaticSoundData,
    pub ui_confirm: StaticSoundData,
    pub ui_back: StaticSoundData,
    pub kill: StaticSoundData,
    /// 拾取魂火：基准音 jiao(10)（E5），播放时按连拾次数升调
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
    pub bell_pulse: StaticSoundData,
    pub big_bell: StaticSoundData,
    pub seal: StaticSoundData,
    pub blast: StaticSoundData,
    pub quake: StaticSoundData,
    pub warn: StaticSoundData,
    /// 夜主起手：聚火、扫尾、落雨各有固定音色，短起音穿过战斗声。
    pub volley_warn: StaticSoundData,
    pub sweep_warn: StaticSoundData,
    pub rain_warn: StaticSoundData,
    pub warn_big: StaticSoundData,
    pub soul_bell: StaticSoundData,
    pub heal: StaticSoundData,
    pub combo: StaticSoundData,
    pub event: StaticSoundData,
    pub coins: StaticSoundData,
    pub shield: StaticSoundData,
    pub defeat: StaticSoundData,
    /// 盖章：朱砂印落下的闷响（共鸣跨阶、反应初见）
    pub stamp: StaticSoundData,
    /// 濒死的心跳（“咚、咚”）
    pub heart: StaticSoundData,
    /// 夜主换阶段：太鼓一击、低锣，一声狐啸（往上挑再拖着落下来）
    pub boss_phase: StaticSoundData,
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
            b.bell(jiao(12 + i as i32 * 2), 0.35 + i as f32 * 0.28, 0.14, 1.4);
        }
        // 五连：五声之后一记金光，A 和 E 的空五度从低往高扫上去，落在主音 E 上（界面上整卷泛金光）
        if gold {
            let t = 0.35 + n as f32 * 0.28;
            for (j, d) in [12, 15, 17, 20].into_iter().enumerate() {
                b.bell(jiao(d), t + j as f32 * 0.04, 0.09, 2.4);
            }
            b.sine(jiao(20), t + 0.12, 0.9, 0.025);
        }
    })
}

/// 节流键和合成槽位按法器区分，暴击有自己的起音空间。
pub(crate) fn impact_group(identity: WeaponIdentity, crit: bool) -> (usize, &'static str, f64) {
    use WeaponIdentity::*;
    let (index, keys, gap) = match identity {
        Lamp => (0, ["lamp_hit", "lamp_crit"], 0.08),
        Sword => (1, ["sword_hit", "sword_crit"], 0.04),
        Bell => (2, ["bell_hit", "bell_crit"], 0.075),
        Crane => (3, ["crane_hit", "crane_crit"], 0.06),
        Seal => (4, ["seal_hit", "seal_crit"], 0.10),
    };
    (index, keys[usize::from(crit)], gap)
}

fn impact_sound(identity: WeaponIdentity, crit: bool, variant: usize) -> StaticSoundData {
    use WeaponIdentity::*;
    let v = variant as f32;
    let gain = if crit { 1.35 } else { 1.0 };
    let (index, _, _) = impact_group(identity, crit);
    let life = match identity {
        Lamp => 0.12,
        Sword => 0.10,
        Bell => 0.24,
        Crane => 0.13,
        Seal => 0.22,
    };
    render_seeded(life, 0x92a4_017b_u32.wrapping_add((index * 37 + variant * 101) as u32), |b| {
        match identity {
            Lamp => {
                b.noise(
                    0.0,
                    0.07 + v * 0.009,
                    0.13 * gain,
                    NoiseOpts {
                        attack: 0.001,
                        slide: Some(450.0),
                        ..noise(FilterKind::Low, 1800.0 + v * 180.0)
                    },
                );
                b.osc(Wave::Sine, 160.0, 0.0, 0.07, 0.045 * gain, Some((65.0, 0.06)), 0.002);
                for i in 0..3 {
                    b.noise(
                        0.014 + i as f32 * (0.017 + v * 0.002),
                        0.006,
                        0.045 * gain,
                        noise(FilterKind::High, 3500.0),
                    );
                }
            }
            Sword => {
                b.noise(
                    0.0,
                    0.045 + v * 0.008,
                    0.07 * gain,
                    NoiseOpts {
                        attack: 0.001,
                        slide: Some(6800.0),
                        ..noise(FilterKind::High, 2600.0 + v * 250.0)
                    },
                );
                for (i, ratio) in [1.0, 1.48, 2.17].into_iter().enumerate() {
                    b.sine(
                        (2450.0 + v * 55.0) * ratio,
                        0.0,
                        0.065 - i as f32 * 0.014,
                        0.035 * gain / (i + 1) as f32,
                    );
                }
            }
            Bell => {
                b.noise(0.0, 0.023 + v * 0.004, 0.07 * gain, noise(FilterKind::High, 5500.0 + v * 200.0));
                b.bell(jiao(20), 0.0, 0.045 * gain, 0.17 + v * 0.015);
                b.sine(7040.0, 0.003, 0.05, 0.014 * gain);
            }
            Crane => {
                b.noise(
                    0.0,
                    0.045,
                    0.08 * gain,
                    NoiseOpts { q: 0.7, slide: Some(4200.0), ..noise(FilterKind::Band, 1500.0 + v * 160.0) },
                );
                b.noise(0.018 + v * 0.004, 0.065, 0.075 * gain, noise(FilterKind::High, 2300.0));
                b.noise(0.055, 0.03, 0.05 * gain, noise(FilterKind::Low, 750.0 + v * 80.0));
            }
            Seal => {
                b.drum(0.0, 0.18 * gain, 92.0 + v * 3.0);
                b.sine(70.0, 0.0, 0.16, 0.065 * gain);
                b.noise(0.0, 0.10 + v * 0.015, 0.13 * gain, noise(FilterKind::Low, 1100.0 + v * 180.0));
                b.noise(0.015, 0.04, 0.035 * gain, noise(FilterKind::Band, 2200.0));
            }
        }
        // 暴击仍保留材质，只增加短促起音与低处的分量。
        if crit {
            b.noise(0.0, 0.012, 0.04, noise(FilterKind::High, 6000.0));
            b.sine(if identity == Seal { 68.0 } else { 155.0 }, 0.0, 0.055, 0.045);
        }
    })
}

impl Sfx {
    #[cfg(test)]
    pub(crate) fn pcm_bytes(&self) -> usize {
        [
            &self.hit,
            &self.crit,
            &self.kill,
            &self.gem,
            &self.level_up,
            &self.select,
            &self.evolution,
            &self.resonance,
            &self.ult,
            &self.ult_ready,
            &self.dash,
            &self.hurt,
            &self.sword,
            &self.bell_pulse,
            &self.big_bell,
            &self.seal,
            &self.blast,
            &self.quake,
            &self.warn,
            &self.volley_warn,
            &self.sweep_warn,
            &self.rain_warn,
            &self.warn_big,
            &self.soul_bell,
            &self.heal,
            &self.combo,
            &self.event,
            &self.coins,
            &self.shield,
            &self.defeat,
            &self.stamp,
            &self.heart,
            &self.boss_phase,
            &self.boss_down,
            &self.dawn,
            &self.elite_down,
            &self.deeper,
            &self.bamboo,
            &self.burn,
            &self.scroll_unroll,
            &self.scroll_line,
            &self.lamp_lit,
            &self.dawn_spread,
            &self.ui_move,
            &self.ui_confirm,
            &self.ui_back,
        ]
        .into_iter()
        .chain(self.chest.iter())
        .chain(self.impacts.iter().flatten().flatten())
        .map(|s| s.frames.len() * size_of::<kira::Frame>())
        .sum()
    }

    pub fn new() -> Self {
        Sfx {
            impacts: std::array::from_fn(|i| {
                std::array::from_fn(|crit| {
                    std::array::from_fn(|variant| impact_sound(WeaponIdentity::ALL[i], crit != 0, variant))
                })
            }),
            hit: render(0.1, |b| b.noise(0.0, 0.035, 0.07, noise(FilterKind::High, 3300.0))),
            // 暴击：清脆的金属声（docs/GAMEPLAY.md 第 14 节）
            crit: render(0.5, |b| {
                b.noise(0.0, 0.03, 0.09, noise(FilterKind::High, 5200.0));
                b.bell(2350.0, 0.0, 0.05, 0.35);
                b.sine(4980.0, 0.0, 0.12, 0.025);
                b.wood(0.0, 0.05, 1500.0);
            }),
            ui_move: render(0.12, |b| b.wood(0.0, 0.055, 760.0)),
            ui_confirm: render(0.32, |b| b.pluck(jiao(12), 0.0, 0.10, 0.28)),
            ui_back: render(0.22, |b| b.pluck(jiao(8), 0.0, 0.075, 0.18)),
            kill: render(0.2, |b| b.osc(Wave::Sine, 285.0, 0.0, 0.12, 0.1, Some((85.0, 0.12)), 0.004)),
            gem: render(0.25, |b| {
                let f = jiao(10);
                b.sine(f, 0.0, 0.18, 0.06);
                b.osc(Wave::Triangle, f * 2.0, 0.0, 0.08, 0.025, None, 0.004);
            }),
            level_up: render(2.2, |b| {
                for (i, d) in [10, 12, 13, 15, 17].into_iter().enumerate() {
                    b.pluck(jiao(d), i as f32 * 0.06, 0.16, 0.9);
                }
                b.bell(jiao(20), 0.32, 0.08, 1.6);
            }),
            select: render(1.0, |b| {
                b.pluck(jiao(12), 0.0, 0.18, 0.8);
                b.pluck(jiao(15), 0.05, 0.14, 0.8);
            }),
            chest: [chest(1), chest(3), chest(5)],
            evolution: render(4.0, |b| {
                b.gong(73.4, 0.0, 0.32);
                b.drum(0.0, 0.6, 90.0);
                for (i, d) in [5, 7, 10, 12, 15, 17, 20].into_iter().enumerate() {
                    b.pluck(jiao(d), 0.1 + i as f32 * 0.07, 0.15, 1.0);
                }
                b.bell(jiao(22), 0.7, 0.12, 2.5);
            }),
            resonance: render(2.0, |b| {
                for (i, d) in [12, 15, 17].into_iter().enumerate() {
                    b.pluck(jiao(d), i as f32 * 0.08, 0.13, 1.0);
                }
                b.bell(jiao(19), 0.24, 0.07, 1.5);
            }),
            ult: render(4.0, |b| {
                // 燃灯结算时立刻出重音，噪声起音和鼓、锣、低频对齐。
                b.noise(
                    0.0,
                    0.4,
                    0.25,
                    NoiseOpts {
                        kind: FilterKind::High,
                        freq: 400.0,
                        slide: Some(5000.0),
                        q: 1.0,
                        attack: 0.008,
                    },
                );
                b.drum(0.0, 0.9, 70.0);
                b.noise(
                    0.0,
                    0.9,
                    0.3,
                    NoiseOpts {
                        kind: FilterKind::Low,
                        freq: 900.0,
                        slide: Some(120.0),
                        ..Default::default()
                    },
                );
                b.gong(55.0, 0.0, 0.22);
                // 次级尾声在 120ms 接上，不推迟主重音。
                b.noise(
                    0.12,
                    0.4,
                    0.06,
                    NoiseOpts {
                        kind: FilterKind::High,
                        freq: 400.0,
                        slide: Some(5000.0),
                        q: 1.0,
                        attack: 0.008,
                    },
                );
                // 主重音同起会叠峰，整段统一留出余量，保留各层音量比例。
                let peak = b.data.iter().map(|s| s.abs()).fold(0.95, f32::max);
                for sample in &mut b.data {
                    *sample *= 0.95 / peak;
                }
            }),
            ult_ready: render(1.6, |b| {
                b.bell(jiao(15), 0.0, 0.08, 1.2);
                b.bell(jiao(20), 0.1, 0.07, 1.4);
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
            bell_pulse: render(1.4, |b| b.bell(jiao(15), 0.0, 0.06, 1.1)),
            big_bell: render(3.2, |b| {
                b.bell(jiao(5), 0.0, 0.22, 3.0);
                b.bell(jiao(10), 0.02, 0.12, 2.5);
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
            volley_warn: render(0.7, |b| {
                b.wood(0.0, 0.22, 620.0);
                b.bell(880.0, 0.02, 0.12, 0.6);
                b.osc(Wave::Sine, 180.0, 0.0, 0.65, 0.14, Some((350.0, 0.6)), 0.025);
            }),
            sweep_warn: render(0.7, |b| {
                b.drum(0.0, 0.45, 85.0);
                b.wood(0.16, 0.2, 440.0);
                b.noise(
                    0.0,
                    0.65,
                    0.1,
                    NoiseOpts {
                        kind: FilterKind::Band,
                        freq: 400.0,
                        slide: Some(1600.0),
                        ..Default::default()
                    },
                );
            }),
            rain_warn: render(0.7, |b| {
                for (i, f) in [1320.0, 1100.0, 880.0].into_iter().enumerate() {
                    b.bell(f, i as f32 * 0.12, 0.12, 0.4);
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
                    b.bell(jiao(12 + i), i as f32 * 0.045, 0.06, 0.9);
                }
            }),
            heal: render(1.4, |b| {
                b.bell(jiao(14), 0.0, 0.1, 1.2);
                b.bell(jiao(17), 0.08, 0.08, 1.2);
            }),
            // 连斩：鼓点 + 钟
            combo: render(1.8, |b| {
                b.drum(0.0, 0.5, 92.0);
                b.drum(0.14, 0.42, 92.0);
                b.drum(0.3, 0.65, 70.0);
                b.bell(jiao(17), 0.3, 0.1, 1.0);
                b.bell(jiao(20), 0.36, 0.08, 1.2);
            }),
            event: render(2.2, |b| {
                b.bell(jiao(13), 0.0, 0.12, 1.6);
                b.bell(jiao(16), 0.18, 0.1, 1.8);
            }),
            coins: render(0.6, |b| {
                for i in 0..10 {
                    b.sine(jiao(15 + (i % 5)) * 2.0, i as f32 * 0.035, 0.12, 0.05);
                }
            }),
            shield: render(0.8, |b| {
                b.bell(jiao(8), 0.0, 0.06, 0.6);
                b.noise(0.0, 0.2, 0.05, noise(FilterKind::Band, 1500.0));
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
                b.pluck(jiao(5), 0.0, 0.11, 2.6);
                b.pluck(jiao(10), 0.02, 0.05, 2.2);
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
                b.bell(jiao(15), 0.0, 0.035, 1.4);
                b.sine(jiao(20), 0.02, 0.35, 0.008);
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
                    b.bell(jiao(d), 0.12 + i as f32 * 0.05, 0.06, 2.2);
                }
                for k in 0..4 {
                    b.noise(0.2 + k as f32 * 0.13, 0.01, 0.03, noise(FilterKind::High, 3400.0));
                }
            }),
            dawn_spread: render(4.5, |b| {
                for (i, d) in [10, 12, 13, 15, 17, 18, 20].into_iter().enumerate() {
                    b.pluck(jiao(d), i as f32 * 0.32, 0.07, 2.4);
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
                b.gong(41.2, 0.0, 0.2);
                b.bell(jiao(0), 0.0, 0.05, 3.5);
                // 从 E4 沉到 E3（配乐的主音）
                b.osc(Wave::Sine, jiao(5), 0.05, 3.0, 0.07, Some((jiao(0), 2.6)), 0.08);
                b.noise(
                    0.0,
                    2.4,
                    0.08,
                    NoiseOpts { kind: FilterKind::Low, freq: 400.0, slide: Some(80.0), ..Default::default() },
                );
            }),
            boss_phase: render(3.5, |b| {
                b.drum(0.0, 0.5, 50.0);
                b.gong(55.0, 0.05, 0.2);
                // 狐啸：先往上挑，再拖着落下来；底下垫低八度的正弦撑住
                b.osc(Wave::Triangle, 520.0, 0.08, 0.34, 0.05, Some((1100.0, 0.3)), 0.06);
                b.osc(Wave::Triangle, 1100.0, 0.4, 0.9, 0.045, Some((380.0, 0.85)), 0.02);
                b.osc(Wave::Sine, 550.0, 0.4, 0.9, 0.04, Some((190.0, 0.85)), 0.02);
                b.noise(
                    0.08,
                    1.1,
                    0.05,
                    NoiseOpts {
                        kind: FilterKind::Band,
                        freq: 1800.0,
                        slide: Some(700.0),
                        q: 3.0,
                        attack: 0.05,
                    },
                );
                b.noise(
                    0.0,
                    1.4,
                    0.12,
                    NoiseOpts { kind: FilterKind::Low, freq: 500.0, slide: Some(60.0), ..Default::default() },
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
                for (i, d) in [10, 12, 15].into_iter().enumerate() {
                    b.bell(jiao(d), i as f32 * 0.45, 0.17 - i as f32 * 0.025, 3.2);
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
                    b.pluck(jiao(d), 0.1 + at, 0.16, 1.8);
                }
                b.drum(2.0, 0.3, 70.0);
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ult_main_accent_starts_within_one_frame() {
        let sound = Sfx::new().ult;
        let peak = sound.frames.iter().map(|f| f.left.abs()).fold(0.0, f32::max);
        // 测半峰值重音，不能让很轻的前导噪声冒充起音。
        assert!(peak > 0.5);
        let onset = sound.frames.iter().position(|f| f.left.abs() >= peak * 0.5).unwrap();
        let onset_secs = onset as f32 / sound.sample_rate as f32;
        assert!(onset_secs <= 0.0167, "燃灯主重音在 {onset_secs:.4}s 才起音");
    }

    /// 每个音效都要有声音，而且基本不削波（合成时已经夹在 ±1，碰到边就是削波了）。
    #[test]
    fn sounds_are_audible_and_not_clipped() {
        let s = Sfx::new();
        let all = [
            ("volley_warn", &s.volley_warn),
            ("sweep_warn", &s.sweep_warn),
            ("rain_warn", &s.rain_warn),
            ("boss_phase", &s.boss_phase),
            ("chest5", &s.chest[2]),
            ("deeper", &s.deeper),
            ("bamboo", &s.bamboo),
            ("burn", &s.burn),
            ("scroll_unroll", &s.scroll_unroll),
            ("scroll_line", &s.scroll_line),
            ("lamp_lit", &s.lamp_lit),
            ("dawn_spread", &s.dawn_spread),
            ("ui_move", &s.ui_move),
            ("ui_confirm", &s.ui_confirm),
            ("ui_back", &s.ui_back),
            ("crit", &s.crit),
            ("combo", &s.combo),
            ("stamp", &s.stamp),
            ("heart", &s.heart),
            ("boss_down", &s.boss_down),
            ("dawn", &s.dawn),
            ("elite_down", &s.elite_down),
            ("kill", &s.kill),
            ("ult", &s.ult),
            ("evolution", &s.evolution),
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

#[cfg(test)]
mod impact_tests {
    use super::*;

    #[test]
    fn material_variants_are_distinct_prompt_and_not_clipped() {
        let s = Sfx::new();
        let mut keys = Vec::new();
        for (i, identity) in WeaponIdentity::ALL.into_iter().enumerate() {
            for crit in [false, true] {
                let (index, key, gap) = impact_group(identity, crit);
                assert_eq!(index, i);
                assert!(!keys.contains(&key));
                keys.push(key);
                assert!((0.04..=0.1).contains(&gap));
                let bank = &s.impacts[i][usize::from(crit)];
                for (v, sound) in bank.iter().enumerate() {
                    let peak = sound.frames.iter().map(|f| f.left.abs()).fold(0.0, f32::max);
                    assert!(peak > 0.02 && peak < 0.98, "{identity:?}/{crit}/{v}: {peak}");
                    assert!(sound.frames.iter().take(220).any(|f| f.left.abs() > 0.002));
                    if v > 0 {
                        assert!(
                            sound
                                .frames
                                .iter()
                                .zip(bank[0].frames.iter())
                                .any(|(a, b)| (a.left - b.left).abs() > 0.001)
                        );
                    }
                }
                assert!(
                    s.impacts[i][0][0].frames.iter().zip(s.impacts[i][1][0].frames.iter()).any(|(a, b)| (a
                        .left
                        - b.left)
                        .abs()
                        > 0.001)
                );
            }
        }
    }
}
