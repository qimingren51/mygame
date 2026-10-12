//! 模拟的时间步长。模拟只认这里的常量，从不读取真实时间。

/// 每秒模拟步数。
pub const TICK_HZ: u32 = 60;

/// 每一步的时长（秒）。
pub const DT: f32 = 1.0 / TICK_HZ as f32;

/// 一帧最多补几步。卡顿时宁可让游戏变慢，也不让模拟连续追赶。
pub const MAX_CATCHUP_TICKS: u32 = 4;

/// 每隔多少步记录一次状态哈希（每秒一次）。
pub const HASH_INTERVAL: u64 = TICK_HZ as u64;

/// 秒数换算成步数（向下取整）。
pub fn secs_to_ticks(secs: f32) -> u64 {
    (secs * TICK_HZ as f32) as u64
}
