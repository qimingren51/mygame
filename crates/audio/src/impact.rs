//! 材质分层的命中采样库。每种材质四个独立采样，洗牌轮换，再轻微改变音高与力度。
//! 合成和轮换只用音频私有随机流，不借用 SimRng，也不以帧时间取小数伪装随机。

use kira::sound::static_sound::StaticSoundData;
use lantern_content::Element;
use lantern_core::Pcg32;

use crate::synth::{Buf, FilterKind, NoiseOpts, Wave};

const VARIANTS: usize = 4;
const MATERIALS: usize = 6;

pub(crate) struct ImpactBank {
    samples: [[[StaticSoundData; VARIANTS]; 2]; MATERIALS],
}

impl ImpactBank {
    pub fn new() -> Self {
        Self {
            samples: std::array::from_fn(|material| {
                std::array::from_fn(|crit| {
                    std::array::from_fn(|variant| sample(material, crit != 0, variant))
                })
            }),
        }
    }

    pub fn sound(&self, pick: Impact) -> StaticSoundData {
        self.samples[pick.material][usize::from(pick.crit)][pick.variant].clone()
    }
}

fn sample(material: usize, crit: bool, variant: usize) -> StaticSoundData {
    let mut b = Buf::new(0.42);
    b.seed_noise(0x519a_721d ^ (material as u32 * 113 + variant as u32 * 7919 + u32::from(crit)));
    let v = variant as f32;
    let body = 125.0 + v * 17.0;
    // 接触的低频实体、表面颗粒、材质余振分开塑形，避免一声高频噪声包办所有命中。
    b.osc(Wave::Sine, body, 0.0, 0.09 + v * 0.009, 0.10, Some((body * 0.55, 0.07)), 0.0015);
    let (freq, decay, grain) = match material {
        0 => (1850.0 + v * 145.0, 0.18, 4300.0), // 金：短促金石余振
        1 => (520.0 + v * 73.0, 0.09, 1500.0),   // 木：纤维断裂、木腔
        2 => (820.0 + v * 91.0, 0.12, 2300.0),   // 水：水滴与散开的水膜
        3 => (310.0 + v * 42.0, 0.08, 3100.0),   // 火：炭裂与火星
        4 => (240.0 + v * 38.0, 0.13, 1000.0),   // 土：石粒与沉闷的实体
        _ => (390.0 + v * 57.0, 0.07, 1750.0),   // 无五行：近身钝击
    };
    b.noise(
        0.0,
        0.032 + v * 0.004,
        0.095,
        NoiseOpts { freq: grain, q: 0.8, attack: 0.001, ..Default::default() },
    );
    match material {
        0 => b.bell(freq, 0.002, 0.046, decay),
        1 => {
            b.wood(0.002, 0.072, freq);
            b.wood(0.010 + v * 0.002, 0.018, freq * 1.7);
        }
        2 => b.osc(Wave::Sine, freq * 1.8, 0.004, decay, 0.055, Some((freq, 0.06)), 0.002),
        3 => {
            for i in 0..3 {
                b.noise(
                    0.005 + i as f32 * 0.013,
                    0.018,
                    0.05 / (i + 1) as f32,
                    NoiseOpts { kind: FilterKind::High, freq: grain, ..Default::default() },
                );
            }
        }
        _ => {
            b.sine(freq, 0.002, decay, 0.055);
            b.noise(
                0.009,
                0.06,
                0.065,
                NoiseOpts { kind: FilterKind::Low, freq: grain, ..Default::default() },
            );
        }
    }
    if crit {
        b.bell(freq * 1.6, 0.001, 0.065, 0.27);
        b.sine(body * 0.75, 0.002, 0.13, 0.075);
    }
    b.finish().to_sound()
}

#[derive(Clone, Copy)]
struct Bag {
    order: [usize; VARIANTS],
    next: usize,
    last: Option<usize>,
}

impl Default for Bag {
    fn default() -> Self {
        Self { order: [0, 1, 2, 3], next: VARIANTS, last: None }
    }
}

impl Bag {
    fn draw(&mut self, rng: &mut Pcg32) -> usize {
        if self.next == VARIANTS {
            for i in (1..VARIANTS).rev() {
                self.order.swap(i, rng.below((i + 1) as u32) as usize);
            }
            if self.last == Some(self.order[0]) {
                self.order.swap(0, 1 + rng.below((VARIANTS - 1) as u32) as usize);
            }
            self.next = 0;
        }
        let value = self.order[self.next];
        self.next += 1;
        self.last = Some(value);
        value
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Impact {
    material: usize,
    crit: bool,
    variant: usize,
    pub rate: f64,
    pub volume: f32,
}

pub(crate) struct ImpactPicker {
    rng: Pcg32,
    bags: [[Bag; 2]; MATERIALS],
}

impl ImpactPicker {
    pub fn new(seed: u64) -> Self {
        Self { rng: Pcg32::new(seed, 0x4155_4449), bags: [[Bag::default(); 2]; MATERIALS] }
    }

    pub fn next(&mut self, element: Option<Element>, crit: bool) -> Impact {
        let material = element.map_or(5, Element::index);
        let variant = self.bags[material][usize::from(crit)].draw(&mut self.rng);
        Impact {
            material,
            crit,
            variant,
            rate: 2.0_f64.powf(f64::from(self.rng.range_f32(-0.7, 0.7)) / 12.0),
            volume: self.rng.range_f32(-1.5, 0.5),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shuffled_samples_do_not_repeat_even_across_bags() {
        let mut a = ImpactPicker::new(42);
        let mut b = ImpactPicker::new(42);
        for element in Element::ALL.map(Some).into_iter().chain([None]) {
            for crit in [false, true] {
                let mut last = None;
                for _ in 0..24 {
                    let mut seen = [false; VARIANTS];
                    for _ in 0..VARIANTS {
                        let p = a.next(element, crit);
                        assert_eq!(p, b.next(element, crit));
                        assert_ne!(last, Some(p.variant));
                        assert!(!seen[p.variant]);
                        assert!((0.96..1.042).contains(&p.rate));
                        assert!((-1.5..0.5).contains(&p.volume));
                        last = Some(p.variant);
                        seen[p.variant] = true;
                    }
                }
            }
        }
    }

    #[test]
    fn material_samples_are_distinct_audible_and_have_headroom() {
        let bank = ImpactBank::new();
        let all: Vec<_> = bank.samples.iter().flatten().flatten().collect();
        for (i, sound) in all.iter().enumerate() {
            let peak = sound.frames.iter().map(|f| f.left.abs()).fold(0.0, f32::max);
            assert!((0.04..0.8).contains(&peak), "采样 {i} 峰值 {peak}");
            assert!(sound.frames.iter().all(|f| f.left.is_finite()));
            for other in &all[..i] {
                assert_ne!(sound.frames, other.frames);
            }
        }
    }
}
