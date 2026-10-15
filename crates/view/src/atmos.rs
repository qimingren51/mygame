//! 氛围（docs/FEEL.md 第 4 节）：萤火与夜雾、暗角、受伤与濒死、夜主登场压暗、天明。
//!
//! - 萤火和夜雾都叠加在暗层之上：萤火是暗处的小光点，夜雾是暗处泛起的一层冷蓝薄雾。
//! - 暗角用 Bevy 自带的 `Vignette`，平时很淡；受伤时一跳，生命低于三成时随心跳收紧、泛红。
//! - 天明：击败夜主后，光照图的底色在 3 秒内从夜色变成晨光，剩下的妖物化成墨烟
//!   （docs/GAMEPLAY.md 第 4.2、14 节）。只改画面，模拟照常结束。

use std::f32::consts::TAU;

use bevy::post_process::bloom::Bloom;
use bevy::post_process::effect_stack::{ChromaticAberration, Vignette};
use bevy::prelude::*;

use lantern_core::Pcg32;
use lantern_sim::combat::StrikeFx;
use lantern_sim::{Health, Player, Pos, SimEvent, SimOutbox};

use crate::actors::{GlowRequests, Pools};
use crate::lighting::{LightCamera, NIGHT_AMBIENT};
use crate::particles::{INK, Particles};
use crate::{Feel, MainCamera, layer};

/// 无尽夜：夜主每退去一次夜色暗多少、最多几层
const DEPTH_STEP: f32 = 0.06;
const MAX_DEPTH: u32 = 4;
/// 辉光平时的强度（`lib.rs` 的 `bloom()` 也用它）
pub(crate) const BLOOM_BASE: f32 = 0.16;
/// 天明用多久（现实秒），从夜主倒下后 DAWN_DELAY 秒开始
pub const DAWN_LEN: f32 = 3.0;
const DAWN_DELAY: f32 = 0.8;
/// 萤火、夜雾的数量
const MOTES: usize = 40;
const WISPS: usize = 9;

/// 天明的进度。界面层读它决定结算什么时候浮现。
#[derive(Resource, Default)]
pub struct Dawn {
    /// 夜主倒下后过了多久（现实秒）；None：还是夜里
    pub t: Option<f32>,
}

impl Dawn {
    /// 0..1：夜色褪去的程度
    pub fn progress(&self) -> f32 {
        self.t.map_or(0.0, |t| ((t - DAWN_DELAY) / DAWN_LEN).clamp(0.0, 1.0))
    }
}

struct Mote {
    /// 相对镜头的位置
    off: Vec2,
    phase: f32,
    speed: f32,
    warm: bool,
}

struct Wisp {
    off: Vec2,
    vel: f32,
    scale: f32,
    flip: bool,
}

#[derive(Resource)]
pub(crate) struct Atmos {
    rng: Pcg32,
    motes: Vec<Mote>,
    wisps: Vec<Wisp>,
    /// 受伤后的闪红（1 → 0）
    hurt: f32,
    /// 辉光炸亮（燃灯、夜主倒下……），1 → 0
    flare: f32,
    /// 夜主登场的压暗（1 → 0）
    gloom: f32,
    /// 无尽夜：夜主每退去一次，夜就深一层（目标层数和当前过渡到的深度）
    deeper: u32,
    depth: f32,
    /// 上一下挨打来自哪边（模拟坐标里的单位向量，y 向下，和屏幕 UV 一致）；来源就在脚下时为零
    hurt_dir: Vec2,
    heart: f32,
}

impl Default for Atmos {
    fn default() -> Self {
        let mut rng = Pcg32::new(0x0a75_0f1e, 9);
        let motes = (0..MOTES)
            .map(|_| Mote {
                off: Vec2::new(rng.range_f32(-420.0, 420.0), rng.range_f32(-240.0, 240.0)),
                phase: rng.range_f32(0.0, TAU),
                speed: rng.range_f32(0.4, 1.0),
                warm: rng.chance(0.6),
            })
            .collect();
        let wisps = (0..WISPS)
            .map(|_| Wisp {
                off: Vec2::new(rng.range_f32(-500.0, 500.0), rng.range_f32(-260.0, 260.0)),
                vel: rng.range_f32(4.0, 10.0),
                scale: rng.range_f32(1.6, 2.8),
                flip: rng.chance(0.5),
            })
            .collect();
        Atmos {
            rng,
            motes,
            wisps,
            hurt: 0.0,
            flare: 0.0,
            gloom: 0.0,
            deeper: 0,
            depth: 0.0,
            heart: 0.0,
            hurt_dir: Vec2::ZERO,
        }
    }
}

pub(crate) fn reset_atmos(mut atmos: ResMut<Atmos>, mut dawn: ResMut<Dawn>) {
    atmos.hurt = 0.0;
    atmos.hurt_dir = Vec2::ZERO;
    atmos.flare = 0.0;
    atmos.gloom = 0.0;
    atmos.deeper = 0;
    atmos.depth = 0.0;
    dawn.t = None;
}

/// 平时一层很淡的暗角。
pub(crate) fn base_vignette() -> Vignette {
    Vignette {
        intensity: 0.28,
        radius: 0.95,
        smoothness: 3.0,
        color: Color::srgb(0.02, 0.025, 0.05),
        ..default()
    }
}

/// 挨打时暗角的中心：往来源的反方向挪，挨打的那一边收得更近。
/// dir 是模拟坐标里的单位向量（y 向下，和屏幕 UV 一致）。
fn vignette_center(dir: Vec2, hurt: f32) -> Vec2 {
    Vec2::splat(0.5) - dir * 0.16 * hurt
}

pub(crate) fn atmos_events(
    outbox: Res<SimOutbox>,
    mut atmos: ResMut<Atmos>,
    mut dawn: ResMut<Dawn>,
    hero: Query<&Pos, With<Player>>,
) {
    for ev in &outbox.0 {
        match ev {
            // 伤害从哪儿来：妖物、弹幕、扇形的顶点、狐火雨的落点（模拟坐标）
            SimEvent::PlayerHurt { from, .. } => {
                atmos.hurt = 1.0;
                atmos.hurt_dir = hero.single().map_or(Vec2::ZERO, |p| (*from - p.0).normalize_or_zero());
            }
            SimEvent::Sacrifice { .. } => {
                atmos.hurt = 1.0;
                atmos.hurt_dir = Vec2::ZERO;
            }
            SimEvent::BossArrived { .. } => atmos.gloom = 1.0,
            SimEvent::BossDefeated { dawn: true, .. } => {
                dawn.t = Some(0.0);
                atmos.flare = 1.0;
            }
            // 无尽夜：夜主倒下也不天明，辉光一亮就过去
            SimEvent::BossDefeated { dawn: false, .. } => atmos.flare = 0.8,
            // 夜深一层（无尽夜 10 分钟以后每 5 分钟）：夜色先猛地压一下，再停在更暗的一层（docs/LORE.md 第 8 节）
            SimEvent::NightDeeper { layer } => {
                atmos.deeper = (*layer).min(MAX_DEPTH);
                atmos.gloom = 1.0;
            }
            // 大事件时辉光猛地一亮再回落
            SimEvent::Strike { fx: StrikeFx::Ult, .. } => atmos.flare = atmos.flare.max(0.8),
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => atmos.flare = atmos.flare.max(0.7),
            SimEvent::Evolve { .. } => atmos.flare = atmos.flare.max(0.5),
            SimEvent::LanternLit { all: true, .. } => atmos.flare = atmos.flare.max(0.6),
            SimEvent::Reaction { first: true, .. } => atmos.flare = atmos.flare.max(0.3),
            _ => {}
        }
    }
}

/// 暗角、色差、光照图底色（夜主登场压暗、天明）、萤火与夜雾、天明时妖物化烟。
pub(crate) fn update_atmos(
    real: Res<Time<Real>>,
    time: Res<Time>,
    mut atmos: ResMut<Atmos>,
    mut dawn: ResMut<Dawn>,
    mut parts: ResMut<Particles>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
    hero: Single<&Health, With<Player>>,
    mut cam: Single<
        (&Transform, Option<&mut Vignette>, Option<&mut ChromaticAberration>, Option<&mut Bloom>),
        With<MainCamera>,
    >,
    mut light: Single<&mut Camera, With<LightCamera>>,
    feel: Res<Feel>,
) {
    let rdt = real.delta_secs().min(0.1);
    let dt = time.delta_secs();
    let t = time.elapsed_secs();
    let atmos = &mut *atmos;
    atmos.hurt = (atmos.hurt - rdt * 2.5).max(0.0);
    atmos.flare = (atmos.flare - rdt * 1.6).max(0.0);
    atmos.gloom = (atmos.gloom - rdt / 3.0).max(0.0);
    // 夜沉下去要慢，3 秒左右过渡完
    atmos.depth += (atmos.deeper as f32 - atmos.depth) * (1.0 - (-rdt * 1.2).exp());
    if let Some(dt_dawn) = &mut dawn.t {
        *dt_dawn += rdt;
    }
    let day = dawn.progress();

    // ---- 暗角：受伤一跳；生命低于三成时随心跳收紧、泛红
    let hp = hero.hp / hero.max.max(1.0);
    let low = ((0.3 - hp) / 0.2).clamp(0.0, 1.0);
    let beat_rate = 1.1 + low * 0.6;
    atmos.heart = (atmos.heart + rdt * beat_rate).fract();
    // 心跳是“咚、咚”两下
    let beat = {
        let h = atmos.heart;
        let a = (-((h - 0.05) * 18.0).powi(2)).exp();
        let b = (-((h - 0.28) * 18.0).powi(2)).exp() * 0.7;
        a + b
    };
    let (cam_tf, vignette, chroma, bloom) = &mut *cam;
    if let Some(b) = bloom {
        // 快起慢落：平方让尾巴拖长一点
        b.intensity = BLOOM_BASE + 0.45 * atmos.flare * atmos.flare.sqrt();
    }
    if let Some(v) = vignette {
        let base = base_vignette();
        v.intensity = (base.intensity + atmos.hurt * 0.35 + low * (0.3 + 0.2 * beat)) * (1.0 - day * 0.7);
        v.radius = base.radius - low * (0.25 + 0.06 * beat) - atmos.hurt * 0.12;
        // 挨打那一边的暗角收得更近：中心往反方向挪
        v.center = vignette_center(atmos.hurt_dir, atmos.hurt);
        let red = (atmos.hurt * 0.8 + low * 0.7).min(1.0);
        v.color = base.color.mix(&Color::srgb(0.35, 0.02, 0.03), red);
    }
    if let Some(c) = chroma {
        c.intensity = if feel.lite { 0.0 } else { atmos.hurt * 0.012 + low * beat * 0.006 };
    }

    // ---- 光照图底色：夜色 → 夜主登场时更暗 → 天明时变成晨光
    let night = NIGHT_AMBIENT.to_linear();
    // 夜主登场：0.4 秒压暗，停一会儿，最后 1.5 秒慢慢回来
    let gloom = if atmos.gloom > 0.0 {
        let (elapsed, left) = ((1.0 - atmos.gloom) * 3.0, atmos.gloom * 3.0);
        1.0 - 0.45 * smooth(elapsed / 0.4) * smooth(left / 1.5)
    } else {
        1.0
    };
    let dawn_col = if day < 0.5 {
        LinearRgba::from(Color::srgb(1.0, 0.82, 0.66)) * (day / 0.5)
            + LinearRgba::from(NIGHT_AMBIENT) * (1.0 - day / 0.5)
    } else {
        let k = (day - 0.5) / 0.5;
        LinearRgba::from(Color::srgb(1.0, 0.98, 0.94)) * k
            + LinearRgba::from(Color::srgb(1.0, 0.82, 0.66)) * (1.0 - k)
    };
    let ambient = if day > 0.0 {
        dawn_col
    } else {
        let deep = gloom * (1.0 - DEPTH_STEP * atmos.depth);
        LinearRgba::rgb(night.red * deep, night.green * deep, night.blue * deep)
    };
    light.clear_color = ClearColorConfig::Custom(Color::LinearRgba(ambient.with_alpha(1.0)));

    // ---- 天明时妖物化烟
    if day > 0.05 && day < 0.85 && !pools.visible_enemies.is_empty() {
        let n = pools.visible_enemies.len();
        for _ in 0..4 {
            let at = pools.visible_enemies[atmos.rng.below(n as u32) as usize];
            parts.smoke(at + Vec2::new(0.0, 10.0), 0.7, INK.with_alpha(0.35), 1);
            parts.ash(at + Vec2::new(0.0, 8.0), 8.0, 2, INK.with_alpha(0.6));
        }
    }
    pools.dissolve = smooth((day - 0.15) / 0.6);

    // ---- 萤火：绕着镜头飘，忽明忽暗；天亮了就散
    let center = cam_tf.translation.truncate();
    let night_k = 1.0 - day;
    // 精简特效：萤火和夜雾都不画
    if feel.lite {
        return;
    }
    if night_k > 0.01 {
        for m in &mut atmos.motes {
            let wander =
                Vec2::new((t * 0.3 * m.speed + m.phase).sin(), (t * 0.23 * m.speed + m.phase * 1.7).cos());
            m.off += wander * 9.0 * dt * m.speed + Vec2::new(0.0, 3.0 * dt);
            // 出了范围就绕到另一边
            if m.off.x.abs() > 440.0 {
                m.off.x = -m.off.x.signum() * 430.0;
            }
            if m.off.y.abs() > 250.0 {
                m.off.y = -m.off.y.signum() * 240.0;
            }
            let blink = (0.5 + 0.5 * (t * 1.7 * m.speed + m.phase * 3.0).sin()).powi(3);
            let color = if m.warm { Color::srgb(1.0, 0.78, 0.4) } else { Color::srgb(0.65, 1.0, 0.7) };
            glow.add(
                parts.f.ember,
                (center + m.off).extend(layer::EMISSIVE - 1.0),
                Vec2::splat(0.45),
                0.0,
                color.with_alpha(0.15 + 0.6 * blink * night_k),
            );
        }
    }

    // ---- 夜雾：大片冷蓝的薄雾慢慢横移，叠加在暗层之上，暗处泛起一层月色，亮处几乎看不出
    for w in &mut atmos.wisps {
        w.off.x += w.vel * dt;
        if w.off.x > 560.0 {
            w.off.x = -560.0;
            w.off.y = atmos.rng.range_f32(-260.0, 260.0);
        }
        let edge = 1.0 - (w.off.x.abs() / 560.0).powi(4);
        glow.add_flipped(
            parts.f.wisp,
            (center + w.off).extend(layer::EMISSIVE - 4.0),
            Vec2::new(w.scale * 1.6, w.scale * 0.8),
            0.0,
            Color::srgb(0.5, 0.6, 0.82).with_alpha(0.07 * edge * (1.0 - day)),
            w.flip,
        );
    }
}

fn smooth(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vignette_leans_toward_the_hit() {
        // 从右边挨打：中心往左挪，右边收得更近
        assert!(vignette_center(Vec2::X, 1.0).x < 0.5);
        // 从下面挨打（模拟坐标 y 向下）：中心往上挪（UV 的 y 也向下）
        assert!(vignette_center(Vec2::Y, 1.0).y < 0.5);
        // 受伤的一跳退完就回到正中
        assert_eq!(vignette_center(Vec2::X, 0.0), Vec2::splat(0.5));
    }
}
