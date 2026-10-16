//! 命中声的轮换：每件法器、普通和暴击各三种材质纹理（[`crate::sfx::Sfx::impacts`]），洗牌轮换，
//! 再轻微改变音高与力度。没有法器的命中只用通用命中声，不叠第二套采样。
//! 只用音频私有的随机流，不借用 SimRng，也不拿帧时间取小数冒充随机。

use lantern_core::Pcg32;

/// 每组命中的纹理数。
pub(crate) const VARIANTS: usize = 3;
const WEAPONS: usize = lantern_content::WeaponIdentity::ALL.len();

#[derive(Clone, Copy)]
struct Bag {
    order: [usize; VARIANTS],
    next: usize,
    last: Option<usize>,
}

impl Default for Bag {
    fn default() -> Self {
        Self { order: std::array::from_fn(|i| i), next: VARIANTS, last: None }
    }
}

impl Bag {
    /// 一轮里每种纹理各出一次；跨轮时也不连着重复同一个。
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
    pub variant: usize,
    pub rate: f64,
    pub volume: f32,
}

pub(crate) struct ImpactPicker {
    rng: Pcg32,
    bags: [[Bag; 2]; WEAPONS],
}

impl ImpactPicker {
    pub fn new(seed: u64) -> Self {
        Self { rng: Pcg32::new(seed, 0x4155_4449), bags: [[Bag::default(); 2]; WEAPONS] }
    }

    /// 上下 semitones 个半音内随机改音高，力度 −1.5 到 +0.5 分贝。
    fn jitter(&mut self, variant: usize, semitones: f32) -> Impact {
        Impact {
            variant,
            rate: 2.0_f64.powf(f64::from(self.rng.range_f32(-semitones, semitones)) / 12.0),
            volume: self.rng.range_f32(-1.5, 0.5),
        }
    }

    /// 法器命中：`group` 是 [`crate::sfx::impact_group`] 给的法器槽位。
    pub fn weapon(&mut self, group: usize, crit: bool) -> Impact {
        let variant = self.bags[group][usize::from(crit)].draw(&mut self.rng);
        self.jitter(variant, 0.7)
    }

    /// 没有法器的命中只有一个采样，音高放宽一些；暴击的金属声收窄，免得走调。
    pub fn generic(&mut self, crit: bool) -> Impact {
        self.jitter(0, if crit { 1.0 } else { 4.0 })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shuffled_variants_do_not_repeat_even_across_bags() {
        let mut a = ImpactPicker::new(42);
        let mut b = ImpactPicker::new(42);
        for group in 0..WEAPONS {
            for crit in [false, true] {
                let mut last = None;
                for _ in 0..24 {
                    let mut seen = [false; VARIANTS];
                    for _ in 0..VARIANTS {
                        let p = a.weapon(group, crit);
                        assert_eq!(p, b.weapon(group, crit));
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
    fn generic_hits_vary_pitch_within_range() {
        let mut p = ImpactPicker::new(7);
        let rates: Vec<_> = (0..64).map(|_| p.generic(false).rate).collect();
        assert!(rates.iter().all(|r| (0.79..1.27).contains(r)));
        assert!(rates.iter().any(|&r| r < 0.95) && rates.iter().any(|&r| r > 1.05));
        assert!((0..64).all(|_| (0.94..1.06).contains(&p.generic(true).rate)));
    }
}
