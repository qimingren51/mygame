//! 提灯夜行的最底层：定步长常量、按用途分流的随机数、状态哈希。
//!
//! 这里不依赖引擎，模拟层、命令行工具和测试都用它。所有算法都自己实现，
//! 不随依赖升级而变化，旧回放才能一直重放（docs/DESIGN.md 第 7 节）。

pub mod hash;
pub mod rng;
pub mod step;

pub use hash::StateHasher;
pub use rng::{Pcg32, Stream, Streams};
