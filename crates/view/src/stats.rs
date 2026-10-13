//! 画面层的诊断数字（F3 性能面板显示）：每帧画面系统的耗时、精灵和发光的数量、粒子数。
//! 只是诊断，不影响画面。

use std::time::Instant;

use bevy::prelude::*;

use crate::actors::{GlowRequests, Pools};
use crate::particles::Particles;

/// 画面层的耗时与数量。耗时只算画面系统本身（不含渲染）。
#[derive(Resource, Default)]
pub struct ViewStats {
    start: Option<Instant>,
    /// 累计耗时（毫秒）和帧数，面板按区间求平均
    pub total_ms: f64,
    pub frames: u64,
    /// 本帧的精灵（妖物 + 其他）、发光、粒子数
    pub sprites: usize,
    pub glows: usize,
    pub particles: usize,
}

pub(crate) fn begin(mut s: ResMut<ViewStats>) {
    s.start = Some(Instant::now());
}

pub(crate) fn end(
    mut s: ResMut<ViewStats>,
    pools: Res<Pools>,
    glow: Res<GlowRequests>,
    parts: Option<Res<Particles>>,
) {
    if let Some(t) = s.start.take() {
        s.total_ms += t.elapsed().as_secs_f64() * 1e3;
        s.frames += 1;
    }
    s.sprites = pools.sprite_count();
    s.glows = glow.0.len();
    s.particles = parts.map_or(0, |p| p.len());
}
