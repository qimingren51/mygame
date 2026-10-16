//! 可复现的随机数。
//!
//! 每局一个种子，经 SplitMix64 派生出各用途独立的 PCG32 流。某个系统多抽或少抽一次，
//! 不会影响其他系统的结果，调平衡时改动更局部，回放也更稳定。

/// PCG32（XSH RR 64/32），与参考实现 pcg32_random_r 逐位一致。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Pcg32 {
    state: u64,
    inc: u64,
}

const PCG_MULT: u64 = 6_364_136_223_846_793_005;

impl Pcg32 {
    /// 等同参考实现的 `pcg32_srandom_r(seed, seq)`。
    pub fn new(seed: u64, seq: u64) -> Self {
        let mut rng = Pcg32 { state: 0, inc: (seq << 1) | 1 };
        rng.next_u32();
        rng.state = rng.state.wrapping_add(seed);
        rng.next_u32();
        rng
    }

    pub fn next_u32(&mut self) -> u32 {
        let old = self.state;
        self.state = old.wrapping_mul(PCG_MULT).wrapping_add(self.inc);
        let xorshifted = (((old >> 18) ^ old) >> 27) as u32;
        let rot = (old >> 59) as u32;
        xorshifted.rotate_right(rot)
    }

    /// [0, 1) 上的均匀分布，24 位精度。
    pub fn next_f32(&mut self) -> f32 {
        (self.next_u32() >> 8) as f32 * (1.0 / (1u32 << 24) as f32)
    }

    /// [lo, hi) 上的均匀分布。
    pub fn range_f32(&mut self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.next_f32()
    }

    /// [0, n) 上的均匀整数，无偏（Lemire 方法）。`n` 为 0 时返回 0。
    pub fn below(&mut self, n: u32) -> u32 {
        if n == 0 {
            return 0;
        }
        let threshold = n.wrapping_neg() % n;
        loop {
            let m = u64::from(self.next_u32()) * u64::from(n);
            if (m as u32) >= threshold {
                return (m >> 32) as u32;
            }
        }
    }

    /// 以概率 `p` 返回 true。
    pub fn chance(&mut self, p: f32) -> bool {
        self.next_f32() < p
    }

    /// 内部状态，用于状态哈希和存档。
    pub fn raw_state(&self) -> (u64, u64) {
        (self.state, self.inc)
    }
}

/// SplitMix64，只用来从一个种子派生出多个互不相关的种子。
fn splitmix64(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// 随机流的用途。新增用途只能加在末尾，否则旧种子的结果会变。
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Stream {
    /// 夜签抽取
    Omen,
    /// 开局布置
    Start,
    /// 刷怪
    Spawn,
    /// 战斗（暴击、触发概率）
    Combat,
    /// 掉落
    Drop,
    /// 奇遇
    Event,
    /// 升级选项
    Choice,
    /// 宝箱
    Chest,
    /// 叙事（手记掉落）。只在叙事启用时使用，状态也只在那时写进哈希。
    Story,
}

impl Stream {
    pub const ALL: [Stream; 9] = [
        Stream::Omen,
        Stream::Start,
        Stream::Spawn,
        Stream::Combat,
        Stream::Drop,
        Stream::Event,
        Stream::Choice,
        Stream::Chest,
        Stream::Story,
    ];
    /// 总是写进状态哈希的流。后加的、按需启用的流（叙事）不在这里，由使用方启用时自己写，
    /// 这样不用它的局哈希不变。
    pub const HASHED: [Stream; 8] = [
        Stream::Omen,
        Stream::Start,
        Stream::Spawn,
        Stream::Combat,
        Stream::Drop,
        Stream::Event,
        Stream::Choice,
        Stream::Chest,
    ];
}

/// 一局的全部随机流。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Streams {
    seed: u64,
    rngs: [Pcg32; Stream::ALL.len()],
}

impl Streams {
    pub fn new(seed: u64) -> Self {
        let mut sm = seed;
        let rngs = Stream::ALL.map(|s| {
            let a = splitmix64(&mut sm);
            Pcg32::new(a, s as u64)
        });
        Streams { seed, rngs }
    }

    pub fn seed(&self) -> u64 {
        self.seed
    }

    /// 由种子和键派生一个独立的随机数（地图分块用）：只取决于种子和键，和各条流抽了多少次无关，
    /// 同一个种子每次生成的地图一样。
    pub fn derive(&self, key: u64) -> Pcg32 {
        let mut sm = self.seed ^ key.wrapping_mul(0xD6E8_FEB8_6659_FD93);
        let a = splitmix64(&mut sm);
        Pcg32::new(a, key)
    }

    pub fn get(&mut self, stream: Stream) -> &mut Pcg32 {
        &mut self.rngs[stream as usize]
    }

    /// 同时借出两个不同的流。
    pub fn pair(&mut self, a: Stream, b: Stream) -> (&mut Pcg32, &mut Pcg32) {
        assert_ne!(a, b, "不能同时借出同一个随机流");
        let (ia, ib) = (a as usize, b as usize);
        if ia < ib {
            let (lo, hi) = self.rngs.split_at_mut(ib);
            (&mut lo[ia], &mut hi[0])
        } else {
            let (lo, hi) = self.rngs.split_at_mut(ia);
            (&mut hi[0], &mut lo[ib])
        }
    }

    /// 按固定顺序把 [`Stream::HASHED`] 各流的状态写进哈希。
    pub fn hash_into(&self, h: &mut crate::StateHasher) {
        for s in Stream::HASHED {
            self.hash_stream(s, h);
        }
    }

    /// 把一条流的状态写进哈希（按需启用的流由使用方调用）。
    pub fn hash_stream(&self, stream: Stream, h: &mut crate::StateHasher) {
        let (state, inc) = self.rngs[stream as usize].raw_state();
        h.write_u64(state);
        h.write_u64(inc);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 派生的随机数只取决于种子和键。
    #[test]
    fn derived_rngs_ignore_stream_use() {
        let mut a = Streams::new(7);
        let b = Streams::new(7);
        a.get(Stream::Spawn).next_u32();
        assert_eq!(a.derive(42).next_u32(), b.derive(42).next_u32());
        assert_ne!(a.derive(42).next_u32(), a.derive(43).next_u32());
        assert_ne!(Streams::new(8).derive(42).next_u32(), b.derive(42).next_u32());
    }

    /// 参考实现 pcg32-demo 用 srandom(42, 54) 的前六个输出。
    #[test]
    fn pcg32_matches_reference() {
        let mut rng = Pcg32::new(42, 54);
        let got: Vec<u32> = (0..6).map(|_| rng.next_u32()).collect();
        assert_eq!(got, [0xa15c02b7, 0x7b47f409, 0xba1d3330, 0x83d2f293, 0xbfa4784b, 0xcbed606e]);
    }

    #[test]
    fn streams_are_reproducible_and_independent() {
        let mut a = Streams::new(123);
        let mut b = Streams::new(123);
        // 在 b 里多抽几次刷怪流，战斗流不受影响。
        for _ in 0..10 {
            b.get(Stream::Spawn).next_u32();
        }
        let ca: Vec<u32> = (0..5).map(|_| a.get(Stream::Combat).next_u32()).collect();
        let cb: Vec<u32> = (0..5).map(|_| b.get(Stream::Combat).next_u32()).collect();
        assert_eq!(ca, cb);
        assert_ne!(a.get(Stream::Spawn).next_u32(), a.get(Stream::Combat).next_u32());
    }

    /// 叙事流加在末尾：前面各流的派生不变；不启用叙事时它不进状态哈希。
    #[test]
    fn story_stream_is_appended_and_hashed_only_on_request() {
        let a = Streams::new(9);
        let mut b = Streams::new(9);
        for s in Stream::HASHED {
            assert_eq!(a.rngs[s as usize], b.rngs[s as usize]);
        }
        assert_eq!(*Stream::ALL.last().unwrap(), Stream::Story);
        b.get(Stream::Story).next_u32();
        let hash = |s: &Streams, story: bool| {
            let mut h = crate::StateHasher::new();
            s.hash_into(&mut h);
            if story {
                s.hash_stream(Stream::Story, &mut h);
            }
            h.finish()
        };
        assert_eq!(hash(&a, false), hash(&b, false));
        assert_ne!(hash(&a, true), hash(&b, true));
    }

    #[test]
    fn below_and_f32_ranges() {
        let mut rng = Pcg32::new(7, 0);
        for _ in 0..10_000 {
            assert!(rng.below(5) < 5);
            let f = rng.next_f32();
            assert!((0.0..1.0).contains(&f));
        }
        assert_eq!(rng.below(0), 0);
    }
}
