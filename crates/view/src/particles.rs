//! 粒子（docs/FEEL.md 第 3 节）：命中火星、击杀墨溅与化灰、精英爆墨、闪避残影与扬尘、
//! 灯火余烬、环境里的萤火和夜雾。
//!
//! 固定容量的 CPU 粒子池，不创建实体：每帧把活着的粒子攒成绘制请求，普通混合的进精灵池
//! （受光照影响，暗处看不见），叠加混合的进发光池（画在暗层之上，暗处也亮）。
//! 软点、火线、烟、灰、墨滴、雾、笔触几张贴图在启动时用代码画好，作为图集的一页。
//! 纯装饰，随机数是画面层自己的，不影响模拟。

use std::f32::consts::{PI, TAU};

use bevy::asset::RenderAssetUsages;
use bevy::math::URect;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};

use lantern_content::{BlastKind, Element, Rank};
use lantern_core::Pcg32;
use lantern_sim::bamboo::{Bamboo, ClumpState};
use lantern_sim::combat::StrikeFx;
use lantern_sim::{Arsenal, GameContent, HitKind, Player, SimEvent, SimOutbox};

use crate::actors::{ActorFrames, Draw, GlowRequests, HeroView, Pools};
use crate::atlas::{AtlasDb, FrameId};
use crate::fx::hex;
use crate::{Feel, layer, to_screen};

/// 同时存在的粒子上限；满了就不再生成（先来的先演完）
const CAP: usize = 1800;

/// 墨色（普通混合的粒子）
pub(crate) const INK: Color = Color::srgb(0.07, 0.075, 0.1);

// ---------------------------------------------------------------------------
// 程序生成的贴图
// ---------------------------------------------------------------------------

const PAGE: UVec2 = UVec2::new(512, 128);

/// 粒子贴图的帧。
#[derive(Clone, Copy)]
pub(crate) struct PFrames {
    pub streak: FrameId,
    pub smoke: FrameId,
    pub ash: FrameId,
    pub ember: FrameId,
    pub drop: FrameId,
    pub wisp: FrameId,
    pub slash: FrameId,
}

fn hash(x: i32, y: i32, seed: u32) -> f32 {
    let mut h = (x as u32).wrapping_mul(0x8da6_b343)
        ^ (y as u32).wrapping_mul(0xd816_3841)
        ^ seed.wrapping_mul(0xcb1a_b31f);
    h ^= h >> 13;
    h = h.wrapping_mul(0x5bd1_e995);
    h ^= h >> 15;
    (h & 0xffff) as f32 / 65535.0
}

/// 值噪声，0..1。
fn value_noise(x: f32, y: f32, seed: u32) -> f32 {
    let (xi, yi) = (x.floor() as i32, y.floor() as i32);
    let (fx, fy) = (x - xi as f32, y - yi as f32);
    let s = |t: f32| t * t * (3.0 - 2.0 * t);
    let (u, v) = (s(fx), s(fy));
    let a = hash(xi, yi, seed);
    let b = hash(xi + 1, yi, seed);
    let c = hash(xi, yi + 1, seed);
    let d = hash(xi + 1, yi + 1, seed);
    a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v
}

fn fbm(x: f32, y: f32, seed: u32) -> f32 {
    let mut sum = 0.0;
    let mut amp = 0.5;
    let mut f = 1.0;
    for o in 0..4 {
        sum += value_noise(x * f, y * f, seed + o) * amp;
        f *= 2.0;
        amp *= 0.5;
    }
    sum / 0.9375
}

fn smoothstep(e0: f32, e1: f32, x: f32) -> f32 {
    let t = ((x - e0) / (e1 - e0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// 在 rect 范围里逐像素算 alpha（白色），uv 是 0..1 的局部坐标。
fn paint(px: &mut [u8], rect: URect, f: impl Fn(f32, f32) -> f32) {
    let (w, h) = (rect.width() as f32, rect.height() as f32);
    for y in rect.min.y..rect.max.y {
        for x in rect.min.x..rect.max.x {
            let u = (x - rect.min.x) as f32 / w + 0.5 / w;
            let v = (y - rect.min.y) as f32 / h + 0.5 / h;
            let a = f(u, v).clamp(0.0, 1.0);
            let i = ((y * PAGE.x + x) * 4) as usize;
            px[i..i + 4].copy_from_slice(&[255, 255, 255, (a * 255.0).round() as u8]);
        }
    }
}

fn build_page() -> (Vec<u8>, Vec<(&'static str, URect)>) {
    let mut px = vec![0u8; (PAGE.x * PAGE.y * 4) as usize];
    let r = |x: u32, y: u32, w: u32, h: u32| URect::new(x, y, x + w, y + h);
    let frames = vec![
        ("fx/dot", r(0, 0, 32, 32)),
        ("fx/streak", r(32, 0, 64, 16)),
        ("fx/smoke", r(96, 0, 64, 64)),
        ("fx/ash", r(160, 0, 16, 16)),
        ("fx/ember", r(176, 0, 16, 16)),
        ("fx/drop", r(192, 0, 24, 24)),
        ("fx/wisp", r(224, 0, 128, 64)),
        ("fx/slash", r(0, 64, 256, 64)),
    ];
    let at = |name: &str| frames.iter().find(|f| f.0 == name).map(|f| f.1).unwrap_or_default();
    let radial = |u: f32, v: f32| ((u - 0.5) * 2.0).hypot((v - 0.5) * 2.0);
    // 软点：高斯
    paint(&mut px, at("fx/dot"), |u, v| {
        let d = radial(u, v);
        (-d * d * 4.5).exp() * smoothstep(1.0, 0.85, d)
    });
    // 火线：头亮尾淡的细长条，沿 +X 飞
    paint(&mut px, at("fx/streak"), |u, v| {
        let across = ((v - 0.5) * 2.0).abs();
        let body = (-across * across * 5.0).exp() * smoothstep(1.0, 0.7, across);
        let along = u.powf(1.6) * smoothstep(1.0, 0.88, u);
        body * along
    });
    // 烟：边缘被噪声啃过的软团
    paint(&mut px, at("fx/smoke"), |u, v| {
        let d = radial(u, v);
        let n = fbm(u * 4.0, v * 4.0, 7);
        smoothstep(1.0, 0.25, d + (n - 0.5) * 0.7) * (0.55 + 0.45 * n)
    });
    // 灰：不规则的小片
    paint(&mut px, at("fx/ash"), |u, v| {
        let (x, y) = ((u - 0.5) * 2.0, (v - 0.5) * 2.0);
        let a = y.atan2(x);
        let edge = 0.62 + 0.25 * (a * 3.0 + 1.3).sin() + 0.12 * (a * 5.0).cos();
        smoothstep(edge, edge - 0.18, x.hypot(y))
    });
    // 余烬：小而亮的芯
    paint(&mut px, at("fx/ember"), |u, v| {
        let d = radial(u, v);
        (-d * d * 9.0).exp() + 0.25 * (-d * d * 2.5).exp() * smoothstep(1.0, 0.8, d)
    });
    // 墨滴：边缘略抖的实心圆
    paint(&mut px, at("fx/drop"), |u, v| {
        let (x, y) = ((u - 0.5) * 2.0, (v - 0.5) * 2.0);
        let a = y.atan2(x);
        let edge = 0.78 + 0.08 * (a * 4.0 + 0.7).sin() + 0.05 * (a * 7.0).sin();
        smoothstep(edge, edge - 0.12, x.hypot(y))
    });
    // 雾：横向拉长的噪声团
    paint(&mut px, at("fx/wisp"), |u, v| {
        let d = ((u - 0.5) * 2.0).hypot((v - 0.5) * 2.0 * 1.15);
        let n = fbm(u * 5.0, v * 2.5, 21);
        smoothstep(1.0, 0.1, d + (n - 0.5) * 0.9) * n
    });
    // 笔触：一道月牙形的刷痕，带飞白
    paint(&mut px, at("fx/slash"), |u, v| {
        let (x, y) = ((u - 0.5) * 4.0, v * 2.0 - 1.2);
        // 两个错开的圆夹出月牙
        let outer = x.hypot(y + 1.6) - 2.0;
        let inner = x.hypot(y + 2.05) - 2.0;
        let band = smoothstep(0.04, -0.04, outer) * smoothstep(-0.04, 0.04, inner);
        // 沿着笔画方向的飞白
        let a = x.atan2(y + 1.6);
        let r = (outer - inner).abs().max(1e-3);
        let across = (x.hypot(y + 1.6) - 2.0 + r) / r;
        let dry = smoothstep(0.32, 0.55, value_noise(across * 9.0, a * 2.0, 5));
        let taper = smoothstep(1.05, 0.55, (a / 1.1).abs());
        band * (0.35 + 0.65 * dry) * taper
    });
    (px, frames)
}

/// 启动时画好粒子贴图，加进图集。
pub(crate) fn setup_particles(
    mut commands: Commands,
    mut db: ResMut<AtlasDb>,
    mut images: ResMut<Assets<Image>>,
    mut layouts: ResMut<Assets<TextureAtlasLayout>>,
) {
    let (px, frames) = build_page();
    let image = Image::new(
        Extent3d { width: PAGE.x, height: PAGE.y, depth_or_array_layers: 1 },
        TextureDimension::D2,
        px,
        TextureFormat::Rgba8UnormSrgb,
        RenderAssetUsages::RENDER_WORLD,
    );
    db.add_page(images.add(image), PAGE, &frames, &mut layouts);
    let f = |name: &str| db.find(name).expect("粒子贴图");
    commands.insert_resource(Particles {
        list: Vec::with_capacity(CAP),
        rng: Pcg32::new(0x0b1a_5e20, 5),
        lite: false,
        f: PFrames {
            streak: f("fx/streak"),
            smoke: f("fx/smoke"),
            ash: f("fx/ash"),
            ember: f("fx/ember"),
            drop: f("fx/drop"),
            wisp: f("fx/wisp"),
            slash: f("fx/slash"),
        },
    });
}

// ---------------------------------------------------------------------------
// 粒子池
// ---------------------------------------------------------------------------

/// 一个粒子。坐标是画面坐标（y 向上）。
#[derive(Clone, Copy)]
pub(crate) struct P {
    pub frame: FrameId,
    pub pos: Vec2,
    pub vel: Vec2,
    /// 离地高度和竖直速度：墨滴抛起再落地
    pub h: f32,
    pub vh: f32,
    /// 每秒的阻力（速度乘 e^(-drag·dt)）、画面 y 方向的加速度
    pub drag: f32,
    pub accel: Vec2,
    pub t: f32,
    pub life: f32,
    /// 起止大小（相对贴图原始尺寸）
    pub size: (f32, f32),
    /// 横向拉伸（火线按速度拉长）
    pub stretch: f32,
    pub color: Color,
    /// 淡入占寿命的比例
    pub fade_in: f32,
    pub rot: f32,
    pub spin: f32,
    /// true：叠加（发光）；false：普通混合
    pub glow: bool,
    pub z: f32,
    pub flip: bool,
    /// 朝速度方向转（火线）
    pub align: bool,
    /// 落地后留下墨点
    pub splat: bool,
}

impl P {
    pub fn new(frame: FrameId, pos: Vec2, life: f32, z: f32) -> Self {
        P {
            frame,
            pos,
            vel: Vec2::ZERO,
            h: 0.0,
            vh: 0.0,
            drag: 0.0,
            accel: Vec2::ZERO,
            t: 0.0,
            life,
            size: (1.0, 1.0),
            stretch: 1.0,
            color: Color::WHITE,
            fade_in: 0.0,
            rot: 0.0,
            spin: 0.0,
            glow: false,
            z,
            flip: false,
            align: false,
            splat: false,
        }
    }
}

#[derive(Resource)]
pub(crate) struct Particles {
    list: Vec<P>,
    pub rng: Pcg32,
    pub f: PFrames,
    /// 精简特效：成团的粒子减半，上限减半
    pub lite: bool,
}

impl Particles {
    pub fn spawn(&mut self, p: P) {
        let cap = if self.lite { CAP / 2 } else { CAP };
        if self.list.len() < cap {
            self.list.push(p);
        }
    }

    /// 一团粒子的个数：精简特效时减半（至少留一个）。
    fn n(&self, n: u32) -> u32 {
        if self.lite { n.div_ceil(2) } else { n }
    }

    pub fn clear(&mut self) {
        self.list.clear();
    }

    pub fn len(&self) -> usize {
        self.list.len()
    }

    fn dir(&mut self) -> Vec2 {
        Vec2::from_angle(self.rng.range_f32(0.0, TAU))
    }

    /// 火星：四散的细火线（叠加）。bias 不为零时偏向那个方向。
    pub fn sparks(&mut self, at: Vec2, color: Color, n: u32, speed: f32, bias: Vec2) {
        for _ in 0..self.n(n) {
            let d = (self.dir() + bias).normalize_or(Vec2::X);
            let v = d * speed * self.rng.range_f32(0.5, 1.2);
            let life = self.rng.range_f32(0.14, 0.3);
            let p = P {
                vel: v,
                drag: 7.0,
                size: (self.rng.range_f32(0.35, 0.55), 0.1),
                stretch: 1.6,
                color,
                glow: true,
                align: true,
                ..P::new(self.f.streak, at, life, layer::EMISSIVE + 1.0)
            };
            self.spawn(p);
        }
    }

    /// 余烬：慢慢上飘、忽明忽暗的小火点（叠加）。
    pub fn embers(&mut self, at: Vec2, spread: f32, color: Color, n: u32) {
        for _ in 0..self.n(n) {
            let off = self.dir() * self.rng.range_f32(0.0, spread);
            let p = P {
                vel: Vec2::new(self.rng.range_f32(-12.0, 12.0), self.rng.range_f32(14.0, 42.0)),
                accel: Vec2::new(0.0, 10.0),
                drag: 1.2,
                size: (self.rng.range_f32(0.5, 0.9), 0.15),
                color,
                fade_in: 0.1,
                glow: true,
                ..P::new(self.f.ember, at + off, self.rng.range_f32(0.6, 1.3), layer::EMISSIVE + 0.8)
            };
            self.spawn(p);
        }
    }

    /// 墨溅：墨滴抛起、落地留点。
    pub fn ink(&mut self, at: Vec2, n: u32, power: f32) {
        for _ in 0..self.n(n) {
            let v = self.dir() * self.rng.range_f32(30.0, 110.0) * power;
            let s = self.rng.range_f32(0.18, 0.42) * power.sqrt();
            let p = P {
                vel: v,
                h: self.rng.range_f32(4.0, 14.0),
                vh: self.rng.range_f32(40.0, 120.0) * power.sqrt(),
                drag: 1.5,
                size: (s, s * 0.8),
                color: INK.with_alpha(0.9),
                // 一半的墨滴落地留点，满地墨点太多既脏又费
                splat: self.rng.chance(0.5),
                ..P::new(self.f.drop, at, 2.0, layer::ACTORS + 1.2)
            };
            self.spawn(p);
        }
    }

    /// 化灰：灰片向上飘散（普通混合）。
    pub fn ash(&mut self, at: Vec2, spread: f32, n: u32, color: Color) {
        for _ in 0..self.n(n) {
            let off = Vec2::new(self.rng.range_f32(-spread, spread), self.rng.range_f32(0.0, spread * 1.4));
            let p = P {
                vel: Vec2::new(self.rng.range_f32(-16.0, 16.0), self.rng.range_f32(12.0, 40.0)),
                accel: Vec2::new(self.rng.range_f32(-6.0, 6.0), 6.0),
                drag: 0.8,
                size: (self.rng.range_f32(0.5, 1.0), 0.2),
                color,
                fade_in: 0.05,
                rot: self.rng.range_f32(0.0, TAU),
                spin: self.rng.range_f32(-6.0, 6.0),
                ..P::new(self.f.ash, at + off, self.rng.range_f32(0.6, 1.2), layer::ACTORS + 1.5)
            };
            self.spawn(p);
        }
    }

    /// 烟团：慢慢胀开、上升、淡去（普通混合）。
    pub fn smoke(&mut self, at: Vec2, size: f32, color: Color, n: u32) {
        for _ in 0..self.n(n) {
            let off = self.dir() * self.rng.range_f32(0.0, size * 6.0);
            let p = P {
                vel: self.dir() * self.rng.range_f32(4.0, 16.0) + Vec2::new(0.0, 10.0),
                drag: 1.5,
                size: (size * self.rng.range_f32(0.6, 0.9), size * self.rng.range_f32(1.3, 1.8)),
                color,
                fade_in: 0.15,
                rot: self.rng.range_f32(0.0, TAU),
                spin: self.rng.range_f32(-0.8, 0.8),
                ..P::new(self.f.smoke, at + off, self.rng.range_f32(0.6, 1.1), layer::ACTORS + 1.6)
            };
            self.spawn(p);
        }
    }

    /// 竹叶：从竹梢弹出去，打着转慢慢飘落（普通混合，在暗层之下）。
    pub fn leaves(&mut self, at: Vec2, n: u32) {
        for _ in 0..self.n(n) {
            let d = self.dir();
            let green = BAMBOO_LEAF.mix(&INK, self.rng.range_f32(0.0, 0.45));
            let p = P {
                vel: Vec2::new(d.x * self.rng.range_f32(40.0, 110.0), self.rng.range_f32(20.0, 90.0)),
                accel: Vec2::new(0.0, -70.0),
                drag: 2.6,
                // 灰片拉长就是一片竹叶
                size: (self.rng.range_f32(1.5, 2.2), 0.9),
                stretch: 2.4,
                color: green.with_alpha(0.95),
                fade_in: 0.02,
                rot: self.rng.range_f32(0.0, TAU),
                spin: self.rng.range_f32(-9.0, 9.0),
                ..P::new(
                    self.f.ash,
                    at + d * self.rng.range_f32(0.0, 14.0),
                    self.rng.range_f32(0.9, 1.7),
                    layer::ACTORS + 1.5,
                )
            };
            self.spawn(p);
        }
    }

    /// 竹片：断口崩出去的细条，快而短（普通混合）。
    pub fn splinters(&mut self, at: Vec2, n: u32) {
        for _ in 0..self.n(n) {
            let d = self.dir();
            let p = P {
                vel: Vec2::new(d.x, d.y.abs() * 0.8 + 0.2) * self.rng.range_f32(120.0, 220.0),
                accel: Vec2::new(0.0, -260.0),
                drag: 3.5,
                size: (self.rng.range_f32(0.55, 0.8), 0.35),
                stretch: 1.3,
                color: BAMBOO_SPLINTER,
                align: true,
                ..P::new(self.f.streak, at, self.rng.range_f32(0.25, 0.45), layer::ACTORS + 1.5)
            };
            self.spawn(p);
        }
    }

    /// 地上扬起的尘（闪避、落印）。
    pub fn dust(&mut self, at: Vec2, n: u32, power: f32, color: Color) {
        for _ in 0..self.n(n) {
            let d = self.dir();
            let p = P {
                vel: Vec2::new(d.x, d.y * 0.62) * self.rng.range_f32(20.0, 60.0) * power,
                drag: 4.0,
                size: (0.25 * power.sqrt(), self.rng.range_f32(0.5, 0.8) * power.sqrt()),
                color,
                fade_in: 0.1,
                rot: self.rng.range_f32(0.0, TAU),
                ..P::new(self.f.smoke, at, self.rng.range_f32(0.35, 0.6), layer::GROUND + 0.97)
            };
            self.spawn(p);
        }
    }

    /// 一个精灵的残影：化墨（普通混合，墨色）或者灵光（叠加）。
    pub fn ghost(
        &mut self,
        frame: FrameId,
        at: Vec2,
        flip: bool,
        color: Color,
        life: f32,
        glow: bool,
        z: f32,
    ) {
        let p = P {
            vel: Vec2::new(0.0, if glow { 0.0 } else { 14.0 }),
            size: (1.0, if glow { 1.0 } else { 1.12 }),
            color,
            // 灵光残影晚一点才亮起来，不盖住还在原地的本体
            fade_in: if glow { 0.4 } else { 0.0 },
            flip,
            glow,
            ..P::new(frame, at, life, z)
        };
        self.spawn(p);
    }

    /// 一道笔触（暴击、九尾扫）：快速出现，慢慢淡去。
    pub fn slash(&mut self, at: Vec2, angle: f32, size: f32, color: Color, glow: bool) {
        let p = P {
            size: (size * 0.85, size),
            stretch: 1.0,
            color,
            fade_in: 0.08,
            rot: angle,
            glow,
            ..P::new(self.f.slash, at, 0.32, if glow { layer::EMISSIVE + 1.2 } else { layer::ACTORS + 1.4 })
        };
        self.spawn(p);
    }

    /// 地上一圈扩开的光（升级、点灯）。
    pub fn halo(&mut self, frame: FrameId, at: Vec2, from: f32, to: f32, life: f32, color: Color) {
        let p = P { size: (from, to), color, glow: true, ..P::new(frame, at, life, layer::EMISSIVE - 0.5) };
        self.spawn(p);
    }
}

/// 推进粒子，攒成绘制请求。用虚拟时间：顿帧和慢镜时粒子一起停、一起慢。
pub(crate) fn update_particles(
    time: Res<Time>,
    feel: Res<Feel>,
    mut parts: ResMut<Particles>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
) {
    let dt = time.delta_secs();
    let parts = &mut *parts;
    parts.lite = feel.lite;
    let drop = parts.f.drop;
    let mut landed: Vec<Vec2> = Vec::new();
    parts.list.retain_mut(|p| {
        p.t += dt;
        if p.t >= p.life {
            return false;
        }
        p.vel += p.accel * dt;
        if p.drag > 0.0 {
            p.vel *= (-p.drag * dt).exp();
        }
        p.pos += p.vel * dt;
        p.rot += p.spin * dt;
        if p.vh != 0.0 || p.h > 0.0 {
            p.vh -= 420.0 * dt;
            p.h += p.vh * dt;
            if p.h <= 0.0 {
                if p.splat {
                    landed.push(p.pos);
                }
                return false;
            }
        }
        true
    });
    for at in landed {
        // 落地的墨点：扁的，慢慢淡去
        let s = parts.rng.range_f32(0.2, 0.45);
        let p = P {
            size: (s, s * 1.15),
            color: INK.with_alpha(0.6),
            rot: parts.rng.range_f32(0.0, TAU),
            ..P::new(drop, at, parts.rng.range_f32(1.4, 2.4), layer::GROUND + 0.94)
        };
        parts.spawn(p);
    }
    for p in &parts.list {
        let u = p.t / p.life;
        let size = p.size.0 + (p.size.1 - p.size.0) * u;
        let fade_in = if p.fade_in > 0.0 { (u / p.fade_in).min(1.0) } else { 1.0 };
        let fade_out = if u > 0.5 { 1.0 - (u - 0.5) / 0.5 } else { 1.0 };
        let alpha = p.color.alpha() * fade_in * fade_out * fade_out.sqrt();
        if alpha <= 0.01 {
            continue;
        }
        let color = p.color.with_alpha(alpha);
        let (rot, scale) = if p.align {
            let speed = p.vel.length();
            (p.vel.y.atan2(p.vel.x), Vec2::new(size * p.stretch * (0.4 + speed / 160.0).min(2.2), size))
        } else {
            (p.rot, Vec2::splat(size) * Vec2::new(p.stretch, 1.0))
        };
        let pos = (p.pos + Vec2::new(0.0, p.h)).extend(p.z);
        // 地上的墨点画成扁的
        let scale = if p.z < layer::SHADOW { Vec2::new(scale.x, scale.y * 0.62) } else { scale };
        if p.glow {
            glow.add_flipped(p.frame, pos, scale, rot, color, p.flip);
        } else {
            pools.fx.push(Draw { scale, rot, color, flip: p.flip, ..Draw::new(p.frame, pos) });
        }
    }
}

pub(crate) fn reset_particles(mut parts: ResMut<Particles>) {
    parts.clear();
}

// ---------------------------------------------------------------------------
// 模拟事件 → 粒子
// ---------------------------------------------------------------------------

/// 五行的光色（火星、余烬）。
pub(crate) fn element_glow(e: Option<Element>) -> Color {
    match e {
        Some(Element::Metal) => Color::srgb(1.0, 0.93, 0.7),
        Some(Element::Wood) => Color::srgb(0.5, 1.0, 0.7),
        Some(Element::Water) => Color::srgb(0.5, 0.78, 1.0),
        Some(Element::Fire) => Color::srgb(1.0, 0.6, 0.25),
        Some(Element::Earth) => Color::srgb(0.95, 0.72, 0.42),
        None => Color::srgb(1.0, 0.9, 0.72),
    }
}

const GOLD: Color = Color::srgb(1.0, 0.82, 0.42);
/// 一帧里最多为多少次命中、击杀放粒子（其余照样有伤害数字和墨点）
const HIT_BUDGET: u32 = 28;
const KILL_BUDGET: u32 = 32;

/// 本帧的计数和暴击笔触的冷却。
#[derive(Resource, Default)]
pub(crate) struct ParticleClock {
    slash_cd: f32,
    trail_cd: f32,
    /// 主角走过的路，每一步扬一点尘
    stride: f32,
    last_hero: Option<Vec2>,
}

pub(crate) fn particle_events(
    time: Res<Time>,
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    frames: Res<ActorFrames>,
    hero: Single<(&Transform, &Player, &HeroView)>,
    arsenal: Option<Res<Arsenal>>,
    lanterns: Option<Res<lantern_sim::lanterns::Lanterns>>,
    bamboo: Option<Res<Bamboo>>,
    fixed: Res<Time<Fixed>>,
    mut clock: ResMut<ParticleClock>,
    mut parts: ResMut<Particles>,
) {
    let dt = time.delta_secs();
    clock.slash_cd -= dt;
    clock.trail_cd -= dt;
    let (htf, pl, view) = *hero;
    let hero_at = htf.translation.truncate();
    let mut bamboo_bursts = 0;
    let kills = outbox.0.iter().filter(|e| matches!(e, SimEvent::Kill { .. })).count() as u32;
    // 击杀很多时每只少放一些，总量不超过预算
    let per_kill = if kills == 0 { 0.0 } else { (KILL_BUDGET as f32 / kills as f32).min(1.0) };
    let mut hits = 0;
    let mut kill_k = 0.0;
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { pos, damage, crit, kind, element } => {
                if kind == HitKind::Dot || hits >= HIT_BUDGET {
                    continue;
                }
                hits += 1;
                let at = to_screen(pos) + Vec2::new(0.0, -6.0);
                let away = (at - hero_at).normalize_or_zero() * 0.7;
                if crit {
                    parts.sparks(at, GOLD, 7, 230.0, away);
                    if clock.slash_cd <= 0.0 {
                        clock.slash_cd = 0.06;
                        let a = parts.rng.range_f32(-0.9, 0.9) + if parts.rng.chance(0.5) { 0.0 } else { PI };
                        let s = (0.22 + damage.max(1.0).log10() * 0.05).min(0.5);
                        parts.slash(at, a, s, INK.with_alpha(0.85), false);
                        parts.slash(at, a, s * 1.05, GOLD.with_alpha(0.7), true);
                    }
                } else {
                    let n = if damage >= 50.0 { 3 } else { 2 };
                    parts.sparks(at, element_glow(element), n, 160.0, away);
                }
            }
            SimEvent::Kill { pos, kind, rank } => {
                let def = &content.0.enemies[kind as usize];
                let at = to_screen(pos);
                let body = at + Vec2::new(0.0, def.radius.max(8.0));
                let eye = hex(&def.eye);
                match rank {
                    Rank::Elite => {
                        if let Some(f) = frames.enemy_ghost(kind as usize) {
                            parts.ghost(
                                f,
                                at,
                                hero_at.x < at.x,
                                INK.with_alpha(0.9),
                                0.55,
                                false,
                                layer::ACTORS + 1.1,
                            );
                        }
                        parts.ink(body, 16, 1.6);
                        parts.ash(body, def.radius, 14, INK.with_alpha(0.8));
                        parts.smoke(body, 1.2, INK.with_alpha(0.45), 5);
                        parts.sparks(body, eye, 12, 260.0, Vec2::ZERO);
                        parts.embers(body, def.radius, eye, 10);
                    }
                    // 夜主倒下：化成一大团墨，墨点四溅，灰烬冲天
                    Rank::Boss => {
                        if let Some(f) = frames.enemy_ghost(kind as usize) {
                            parts.ghost(
                                f,
                                at,
                                hero_at.x < at.x,
                                INK.with_alpha(0.95),
                                1.6,
                                false,
                                layer::ACTORS + 1.1,
                            );
                        }
                        let r = def.radius;
                        parts.ink(body, 60, 2.6);
                        parts.ash(body, r, 70, INK.with_alpha(0.85));
                        parts.smoke(body, 2.6, INK.with_alpha(0.55), 16);
                        parts.sparks(body, eye, 40, 420.0, Vec2::ZERO);
                        parts.embers(body, r * 1.5, eye, 40);
                        parts.embers(body, r, GOLD, 30);
                        parts.halo(frames.ring, at, 0.2, 6.0, 1.4, GOLD.with_alpha(0.9));
                    }
                    _ => {
                        kill_k += per_kill;
                        if kill_k < 1.0 {
                            continue;
                        }
                        kill_k -= 1.0;
                        if let Some(f) = frames.enemy_ghost(kind as usize) {
                            parts.ghost(
                                f,
                                at,
                                hero_at.x < at.x,
                                INK.with_alpha(0.5),
                                0.22,
                                false,
                                layer::ACTORS + 1.1,
                            );
                        }
                        parts.ink(body, 3, 1.0);
                        parts.ash(body, def.radius * 0.6, 2, INK.with_alpha(0.7));
                        parts.embers(body, 4.0, eye, 1);
                    }
                }
            }
            SimEvent::Strike { pos, radius, fx } => {
                let at = to_screen(pos);
                match fx {
                    StrikeFx::Seal { evolved } => {
                        let k = if evolved { 1.6 } else { 1.0 };
                        parts.dust(at, (10.0 * k) as u32, radius / 40.0 * k, DUST);
                        parts.ink(at, (6.0 * k) as u32, 1.3 * k);
                    }
                    StrikeFx::Blast(b) => {
                        let c = if b == BlastKind::Ice { element_glow(Some(Element::Water)) } else { FIRE };
                        parts.sparks(at, c, 8, 200.0, Vec2::ZERO);
                        parts.embers(at, radius * 0.4, c, 4);
                    }
                    StrikeFx::Quake => parts.dust(at, 18, radius / 40.0, DUST),
                    StrikeFx::Ult => {
                        for _ in 0..60 {
                            let d = Vec2::from_angle(parts.rng.range_f32(0.0, TAU));
                            let r = parts.rng.range_f32(0.2, 1.0) * radius;
                            parts.embers(at + Vec2::new(d.x * r, d.y * r * 0.62), 6.0, GOLD, 1);
                        }
                        parts.sparks(at, GOLD, 30, 420.0, Vec2::ZERO);
                    }
                    _ => {}
                }
            }
            SimEvent::SweepStrike { pos, dir } => {
                let at = to_screen(pos);
                let d = to_screen(Vec2::from_angle(dir));
                parts.slash(
                    at + d * 80.0,
                    d.y.atan2(d.x) - PI * 0.5,
                    1.4,
                    Color::srgb(1.0, 0.3, 0.22).with_alpha(0.8),
                    true,
                );
                parts.dust(at + d * 90.0, 16, 2.0, DUST);
            }
            SimEvent::Dash { .. } => {
                parts.dust(hero_at, 6, 0.8, DUST);
                clock.trail_cd = 0.0;
            }
            SimEvent::LevelUp { .. } => {
                parts.halo(frames.ring, hero_at, 0.1, 2.2, 0.9, GOLD.with_alpha(0.9));
                parts.embers(hero_at + Vec2::new(0.0, 20.0), 30.0, GOLD, 24);
            }
            // 竹丛打碎：竹梢的叶子四散飘落，断口崩出几根竹片，脚下起一小团尘（一刀砍倒一片时限量）
            SimEvent::BambooBroken { pos } if bamboo_bursts < BAMBOO_BUDGET => {
                bamboo_bursts += 1;
                let at = to_screen(pos);
                parts.leaves(at + Vec2::new(0.0, 46.0), 12);
                parts.splinters(at + Vec2::new(0.0, 14.0), 5);
                parts.dust(at, 4, 0.8, DUST);
            }
            // 夜主登场，狐火把结界里的竹丛烧平：每丛起一股狐火和焦烟，结界边上烧起一圈
            SimEvent::BambooBurned { pos, radius } => {
                if let Some(b) = &bamboo {
                    let mut n = 0;
                    for c in b.near() {
                        if c.state != ClumpState::Burned || c.pos.distance(pos) > radius + 10.0 || n >= 24 {
                            continue;
                        }
                        n += 1;
                        let at = to_screen(c.pos);
                        parts.sparks(at + Vec2::new(0.0, 16.0), FOXFIRE, 8, 170.0, Vec2::new(0.0, 0.8));
                        parts.halo(
                            frames.ring,
                            at + Vec2::new(0.0, 8.0),
                            0.15,
                            0.9,
                            0.45,
                            FOXFIRE.with_alpha(0.55),
                        );
                        parts.embers(at + Vec2::new(0.0, 28.0), 22.0, FOXFIRE, 14);
                        parts.smoke(at + Vec2::new(0.0, 24.0), 1.6, INK.with_alpha(0.55), 3);
                        parts.ash(at + Vec2::new(0.0, 18.0), 16.0, 6, INK.with_alpha(0.75));
                    }
                }
                let center = to_screen(pos);
                for k in 0..36 {
                    let a = k as f32 / 36.0 * TAU;
                    parts.embers(center + Vec2::from_angle(a) * radius, 6.0, FOXFIRE, 1);
                }
            }
            // 石灯笼点亮：灯窗里冒出一股金色火星，地上一圈光
            SimEvent::LanternLit { index, .. } => {
                if let Some(l) = lanterns.as_ref().and_then(|ls| ls.0.get(index as usize)) {
                    let at = to_screen(l.pos);
                    parts.embers(at + Vec2::new(0.0, 30.0), 10.0, GOLD, 26);
                    parts.halo(frames.ring, at, 0.2, 3.0, 1.2, GOLD.with_alpha(0.8));
                }
            }
            _ => {}
        }
    }
    // 走路扬尘：每走一段，脚边起一小团尘
    let moved = clock.last_hero.map_or(0.0, |p| p.distance(hero_at));
    clock.last_hero = Some(hero_at);
    if moved < 40.0 && pl.moved > 0.01 && pl.dash_t <= 0.0 && !parts.lite {
        clock.stride += moved;
        if clock.stride > 26.0 {
            clock.stride = 0.0;
            parts.dust(hero_at + Vec2::new(0.0, 2.0), 2, 0.45, DUST.with_alpha(0.3));
        }
    }
    // 灯火飘火星
    if let Some(arsenal) = arsenal.as_ref().filter(|_| !parts.lite) {
        let a = fixed.overstep_fraction();
        for slot in &arsenal.0 {
            if slot.count == 0 || slot.size <= 0.0 {
                continue;
            }
            let angle = slot.prev_angle + (slot.angle - slot.prev_angle) * a;
            for k in 0..slot.count {
                if parts.rng.chance(dt * 3.0) {
                    let p =
                        to_screen(slot.orbit_offset(angle, k)) + hero_at + Vec2::new(0.0, slot.size * 0.6);
                    parts.embers(p, 3.0, FIRE, 1);
                }
            }
        }
    }
    // 闪避残影：沿路留下几道淡蓝的灵光
    if pl.dash_t > 0.0
        && clock.trail_cd <= 0.0
        && let Some(f) = view.frame_id
    {
        clock.trail_cd = 0.028;
        let tint = Color::srgb(0.55, 0.78, 1.0).with_alpha(0.4);
        // 主角和灯笼叠层是同画布、同锚点的两帧，残影两张一起画
        for frame in std::iter::once(f).chain(view.lantern_id) {
            parts.ghost(frame, hero_at, false, tint, 0.3, true, layer::EMISSIVE - 0.3);
        }
    }
}

const DUST: Color = Color::srgba(0.42, 0.38, 0.32, 0.4);
/// 竹叶（再往墨色里随机调一点）、竹片、狐火
const BAMBOO_LEAF: Color = Color::srgb(0.38, 0.55, 0.34);
const BAMBOO_SPLINTER: Color = Color::srgb(0.82, 0.78, 0.58);
const FOXFIRE: Color = Color::srgb(1.0, 0.42, 0.35);
/// 一帧最多放几丛竹子的碎叶（一刀砍倒一片竹林时）
const BAMBOO_BUDGET: u32 = 6;
const FIRE: Color = Color::srgb(1.0, 0.55, 0.22);
