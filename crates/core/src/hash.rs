//! 状态哈希：FNV-1a 64 位。算法固定，跨平台、跨版本结果一致，用于回放校验和黄金测试。

#[derive(Clone, Debug)]
pub struct StateHasher(u64);

impl Default for StateHasher {
    fn default() -> Self {
        StateHasher(0xcbf2_9ce4_8422_2325)
    }
}

impl StateHasher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn write_bytes(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 ^= u64::from(b);
            self.0 = self.0.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }

    pub fn write_u32(&mut self, v: u32) {
        self.write_bytes(&v.to_le_bytes());
    }

    pub fn write_u64(&mut self, v: u64) {
        self.write_bytes(&v.to_le_bytes());
    }

    /// 按位写入，-0.0 和 0.0 视为不同；模拟里出现差异就说明真的不一致。
    pub fn write_f32(&mut self, v: f32) {
        self.write_u32(v.to_bits());
    }

    pub fn finish(&self) -> u64 {
        self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnv1a_known_value() {
        let mut h = StateHasher::new();
        h.write_bytes(b"a");
        assert_eq!(h.finish(), 0xaf63dc4c8601ec8c);
    }
}
