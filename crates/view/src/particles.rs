//! 粒子（docs/FEEL.md 第 3 节）：命中火星、击杀墨溅与化灰、精英爆墨、闪避残影与扬尘、
//! 灯火余烬、环境里的萤火和夜雾。
//!
//! 固定容量的 CPU 粒子池，不创建实体：每帧把活着的粒子攒成绘制请求，普通混合的进精灵池
//! （受光照影响，暗处看不见），叠加混合的进发光池（画在暗层之上，暗处也亮）。
//! 软点、火线、烟、灰、墨滴、雾、笔触几张贴图在启动时用代码画好，作为图集的一页。
//! 纯装饰，随机数是画面层自己的，不影响模拟。

use std::f32::consts::{FRAC_PI_2, PI, TAU};

use bevy::asset::RenderAssetUsages;
use bevy::math::URect;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};

use lantern_content::{BlastKind, Element, Rank, WeaponIdentity};
use lantern_core::Pcg32;
use lantern_sim::bamboo::{Bamboo, ClumpState};
use lantern_sim::combat::StrikeFx;
use lantern_sim::{Arsenal, Director, Enemies, GameContent, HitKind, Player, RunState, SimEvent, SimOutbox};

use crate::actors::{ActorFrames, Draw, GlowRequests, HeroView, Pools};
use crate::atlas::{AtlasDb, FrameId};
use crate::feedback::{Category, Feedback, Priority, eviction};
use crate::fx::{ULT_END, ULT_FLASH, hex};
use crate::{Feel, layer, to_screen};

/// 总量固定，其中 480 个位置留给暴击、燃灯和夜主死亡。
const CAP: usize = 1800;
const RESERVE: usize = 480;
// 保护类别单独计数，避免攻击耗尽其预算。
const FRAME_BUDGET: [u32; Priority::ALL.len()] = [32, 120, 180, 64, 128, 320, 180, 320];

/// 墨色（普通混合的粒子）
pub(crate) const INK: Color = crate::palette::INK;

// ---------------------------------------------------------------------------
// 程序生成的贴图
// ---------------------------------------------------------------------------

const PAGE: UVec2 = UVec2::new(512, 128);

/// 粒子贴图的帧。
#[derive(Clone, Copy)]
pub(crate) struct PFrames {
    /// 软点（命中亮心、光点）
    pub dot: FrameId,
    pub streak: FrameId,
    pub smoke: FrameId,
    pub ash: FrameId,
    pub ember: FrameId,
    pub drop: FrameId,
    pub wisp: FrameId,
    pub slash: FrameId,
    /// 美术的竹叶 `vfx/bamboo_leaf_0..3`；图集里没有时是灰片，拉长了当竹叶
    pub leaves: [FrameId; 4],
    pub real_leaves: bool,
    /// 美术的羽毛、纸屑 `vfx/feather_0..3`（纸鹤命中翻飞用）；没有时用灰片
    pub feathers: Option<[FrameId; 4]>,
}

/// 美术的逐帧特效（docs/FEEL.md 第 12 节），都是 24 帧 / 秒、播一次。
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub(crate) enum Fx {
    #[default]
    None,
    HitMetal,
    HitWood,
    HitWater,
    HitFire,
    HitEarth,
    Crit,
    Slash,
    KillInk,
    Shockwave,
    FireBurst,
    FireSmoke,
    IceShatter,
    Evolve,
    Pillar,
    CoinSlash,
    CoinWhirl,
    CoinSpark,
    CoinCross,
    TowerDust,
}

impl Fx {
    const ALL: [Fx; 20] = [
        Fx::None,
        Fx::HitMetal,
        Fx::HitWood,
        Fx::HitWater,
        Fx::HitFire,
        Fx::HitEarth,
        Fx::Crit,
        Fx::Slash,
        Fx::KillInk,
        Fx::Shockwave,
        Fx::FireBurst,
        Fx::FireSmoke,
        Fx::IceShatter,
        Fx::Evolve,
        Fx::Pillar,
        Fx::CoinSlash,
        Fx::CoinWhirl,
        Fx::CoinSpark,
        Fx::CoinCross,
        Fx::TowerDust,
    ];

    /// 图集里的帧名前缀（后面接 `_0`、`_1`……）
    fn name(self) -> &'static str {
        match self {
            Fx::None => "",
            Fx::HitMetal => "vfx/hit_metal",
            Fx::HitWood => "vfx/hit_wood",
            Fx::HitWater => "vfx/hit_water",
            Fx::HitFire => "vfx/hit_fire",
            Fx::HitEarth => "vfx/hit_earth",
            Fx::Crit => "vfx/crit",
            Fx::Slash => "vfx/slash",
            Fx::KillInk => "vfx/kill_ink",
            Fx::Shockwave => "vfx/shockwave",
            Fx::FireBurst => "vfx/fire_burst",
            Fx::FireSmoke => "vfx/fire_burst_smoke",
            Fx::IceShatter => "vfx/ice_shatter",
            Fx::Evolve => "vfx/evolve",
            Fx::Pillar => "vfx/evolve_pillar",
            Fx::CoinSlash => "weapons/coin_slash",
            Fx::CoinWhirl => "weapons/coin_whirl",
            Fx::CoinSpark => "weapons/coin_spark",
            Fx::CoinCross => "weapons/coin_cross",
            Fx::TowerDust => "weapons/tower_dust",
        }
    }

    /// 普通混合的帧（墨溅、墨烟）画在暗层之下，其余叠加、画在暗层之上
    fn glow(self) -> bool {
        !matches!(self, Fx::KillInk | Fx::FireSmoke | Fx::TowerDust)
    }

    fn hit(e: Option<Element>) -> Fx {
        match e {
            Some(Element::Metal) => Fx::HitMetal,
            Some(Element::Wood) => Fx::HitWood,
            Some(Element::Water) => Fx::HitWater,
            Some(Element::Fire) => Fx::HitFire,
            Some(Element::Earth) => Fx::HitEarth,
            None => Fx::None,
        }
    }
}

/// 逐帧特效的帧率（美术统一按 24 帧画）
const ANIM_FPS: f32 = 24.0;

/// 逐帧特效第 t 秒画哪一帧、淡到多少：按 24 帧换帧，淡入淡出画在图里；
/// 寿命比动画长的，停在最后一帧，在多出来的那段里淡掉。
fn anim_frame(frames: &[FrameId], t: f32, life: f32) -> (FrameId, f32) {
    let i = ((t * ANIM_FPS) as usize).min(frames.len() - 1);
    let len = frames.len() as f32 / ANIM_FPS;
    let hold = if t > len && life > len { (1.0 - (t - len) / (life - len)).max(0.0) } else { 1.0 };
    (frames[i], hold.sqrt())
}

/// 从图集里按名字收齐每段逐帧特效（`fx::sequence`：图集登记了动画就用动画，否则按 `_0`、`_1`……找）；
/// 缺的段是空的，调用处退回代码画的粒子。
fn load_anims(db: &AtlasDb) -> Vec<Vec<FrameId>> {
    Fx::ALL
        .iter()
        .map(|fx| match *fx {
            Fx::None => Vec::new(),
            fx => crate::fx::sequence(db, fx.name()),
        })
        .collect()
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
        ("fx/wave", r(352, 0, 96, 96)),
    ];
    let at = |name: &str| frames.iter().find(|f| f.0 == name).map(|f| f.1).unwrap_or_default();
    let radial = |u: f32, v: f32| ((u - 0.5) * 2.0).hypot((v - 0.5) * 2.0);
    // 软点：高斯
    paint(&mut px, at("fx/dot"), |u, v| {
        let d = radial(u, v);
        (-d * d * 4.5).exp() * smoothstep(1.0, 0.85, d)
    });
    // 空心波前：细边带少许飞白，中心完全透明，不把法术范围涂成色块。
    paint(&mut px, at("fx/wave"), |u, v| {
        let d = radial(u, v);
        let band = (-((d - 0.84) / 0.025).powi(2)).exp();
        band * (0.55 + 0.45 * fbm(u * 14.0, v * 14.0, 31))
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
        priority: Priority::Ambient,
        category: Category::Decorative,
        spawned: [0; Priority::ALL.len()],
        f: PFrames {
            streak: f("fx/streak"),
            smoke: f("fx/smoke"),
            ash: f("fx/ash"),
            ember: f("fx/ember"),
            drop: f("fx/drop"),
            wisp: f("fx/wisp"),
            slash: f("fx/slash"),
            dot: f("fx/dot"),
            leaves: [0, 1, 2, 3].map(|i| db.find(&format!("vfx/bamboo_leaf_{i}")).unwrap_or(f("fx/ash"))),
            real_leaves: db.find("vfx/bamboo_leaf_0").is_some(),
            feathers: [0, 1, 2, 3]
                .map(|i| db.find(&format!("vfx/feather_{i}")))
                .into_iter()
                .collect::<Option<Vec<_>>>()
                .and_then(|v| v.try_into().ok()),
        },
        anims: load_anims(&db),
    });
}

// ---------------------------------------------------------------------------
// 粒子池
// ---------------------------------------------------------------------------

/// 一个粒子。坐标是画面坐标（y 向上）。
#[derive(Clone, Copy)]
pub(crate) struct P {
    pub frame: FrameId,
    priority: Priority,
    category: Category,
    pub pos: Vec2,
    pub vel: Vec2,
    /// 离地高度和竖直速度：墨滴抛起再落地
    pub h: f32,
    pub vh: f32,
    /// 每秒的阻力（速度乘 e^(-drag·dt)）、画面 y 方向的加速度
    pub drag: f32,
    pub accel: Vec2,
    pub t: f32,
    fresh: bool,
    core: bool,
    /// 燃灯用现实时间穿过顿帧；待发余烬也计入粒子预算，延迟期间不绘制、不运动。
    real_time: bool,
    delay: f32,
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
    /// 播一段逐帧特效（`Fx::None` 时画 `frame`）
    pub anim: Fx,
}

impl P {
    pub fn new(frame: FrameId, pos: Vec2, life: f32, z: f32) -> Self {
        P {
            frame,
            priority: Priority::Ambient,
            category: Category::Decorative,
            pos,
            vel: Vec2::ZERO,
            h: 0.0,
            vh: 0.0,
            drag: 0.0,
            accel: Vec2::ZERO,
            t: 0.0,
            fresh: true,
            core: false,
            real_time: false,
            delay: 0.0,
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
            anim: Fx::None,
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
    priority: Priority,
    category: Category,
    spawned: [u32; Priority::ALL.len()],
    /// 逐帧特效的帧，按 `Fx` 的顺序（`load_anims`）
    anims: Vec<Vec<FrameId>>,
}

impl Particles {
    fn begin_frame(&mut self, lite: bool) {
        self.lite = lite;
        self.spawned = [0; Priority::ALL.len()];
        self.priority = Priority::Ambient;
        self.category = Category::Decorative;
        let cap = if lite { CAP / 2 } else { CAP };
        if self.list.len() > cap {
            self.list.sort_by_key(|p| std::cmp::Reverse((p.category, p.priority)));
            self.list.truncate(cap);
        }
    }

    /// 放一个粒子；本帧预算用完、池满又挤不掉别的时丢掉，返回 false。
    pub fn spawn(&mut self, mut p: P) -> bool {
        let divisor = if self.lite { 2 } else { 1 };
        let priority = self.priority;
        let used = &mut self.spawned[priority as usize];
        // 核心（命中的接触核心、美术的逐帧图）不受每帧预算限制：它们的数量已经由仲裁按事件限住，
        // 丢了就只剩火星；照样计数，挤占后面装饰粒子的预算
        if self.category == Category::Decorative
            && !p.core
            && *used >= FRAME_BUDGET[priority as usize].div_ceil(divisor as u32)
        {
            return false;
        }
        let cap = CAP / divisor;
        let limit = if self.category == Category::Decorative && priority < Priority::Critical {
            cap - RESERVE / divisor
        } else {
            cap
        };
        p.priority = priority;
        p.category = self.category;
        if self.list.len() < limit {
            self.list.push(p);
        } else if let Some(index) =
            eviction(&self.list, (self.category, priority), |p| (p.category, p.priority))
        {
            self.list.swap_remove(index);
            self.list.push(p);
        } else if p.core
            && let Some(index) = self.list.iter().position(|q| !q.core && q.priority <= priority)
        {
            // 命中的接触核心可以替换同级的装饰粒子，短闪光至少显示一次
            self.list.swap_remove(index);
            self.list.push(p);
        } else {
            return false;
        }
        if self.category == Category::Decorative {
            *used += 1;
        }
        true
    }

    /// 一团粒子的个数：精简特效时减半（至少留一个）。
    fn n(&self, n: u32) -> u32 {
        if self.lite { n.div_ceil(2) } else { n }
    }

    pub fn clear(&mut self) {
        self.list.clear();
        self.spawned = [0; Priority::ALL.len()];
        self.priority = Priority::Ambient;
        self.category = Category::Decorative;
    }

    pub fn len(&self) -> usize {
        self.list.len()
    }

    fn dir(&mut self) -> Vec2 {
        Vec2::from_angle(self.rng.range_f32(0.0, TAU))
    }

    /// 火星：四散的细火线（叠加）。bias 不为零时偏向那个方向。
    pub fn sparks(&mut self, at: Vec2, color: Color, n: u32, speed: f32, bias: Vec2) {
        self.sparks_with_clock(at, color, n, speed, bias, false);
    }

    fn sparks_with_clock(&mut self, at: Vec2, color: Color, n: u32, speed: f32, bias: Vec2, real_time: bool) {
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
                real_time,
                ..P::new(self.f.streak, at, life, layer::EMISSIVE + 1.0)
            };
            self.spawn(p);
        }
    }

    /// 一个接触核心加材质碎片；核心在粒子池满时可替换装饰粒子。
    fn impact(
        &mut self,
        at: Vec2,
        dir: Vec2,
        fallback: Vec2,
        identity: Option<WeaponIdentity>,
        color: Color,
        crit: bool,
    ) {
        use WeaponIdentity::*;
        let angle = dir.y.atan2(dir.x);
        let (frame, life, size, stretch) = match identity {
            Some(Sword) => (self.f.streak, 0.10, 0.18, 4.5),
            Some(Bell) => (self.f.ember, 0.04, 1.0, 1.0),
            Some(Crane) => (self.f.ash, 0.05, 0.65, 1.5),
            Some(Seal) => (self.f.drop, 0.06, 0.5, 1.7),
            _ => (self.f.ember, 0.06, 1.0, 1.0),
        };
        let core_color = if crit {
            Color::srgb(1.0, 0.97, 0.83)
        } else {
            match identity {
                Some(Sword) => Color::srgb(1.0, 0.95, 0.78),
                Some(Bell) => Color::srgb(0.88, 0.97, 1.0),
                _ => color,
            }
        };
        // 接触核心加大一倍多（试玩第 1 轮：原来 3–4 像素的亮点在乱战里看不见）
        self.spawn(P {
            color: core_color,
            size: (size * if crit { 2.9 } else { 2.2 }, size * 0.9),
            stretch,
            rot: angle,
            glow: true,
            core: true,
            ..P::new(frame, at, life, layer::EMISSIVE + 1.2)
        });
        // 一团一闪而过的亮心，亮度过辉光阈值，晕开一圈；暴击再加一道横竖交叉的星芒
        let hot = |c: Color, k: f32| {
            let l = c.to_linear();
            Color::linear_rgba(l.red * k, l.green * k, l.blue * k, 1.0)
        };
        self.spawn(P {
            color: hot(core_color.mix(&Color::WHITE, 0.5), if crit { 2.6 } else { 1.8 }),
            size: (if crit { 1.6 } else { 1.1 }, 0.2),
            glow: true,
            core: true,
            ..P::new(self.f.dot, at, if crit { 0.09 } else { 0.07 }, layer::EMISSIVE + 1.3)
        });
        if crit {
            for k in 0..2 {
                self.spawn(P {
                    color: hot(Color::srgb(1.0, 0.92, 0.7), 2.2),
                    size: (0.9, 0.3),
                    stretch: 6.0,
                    rot: angle + std::f32::consts::FRAC_PI_4 + k as f32 * std::f32::consts::FRAC_PI_2,
                    glow: true,
                    ..P::new(self.f.streak, at, 0.1, layer::EMISSIVE + 1.3)
                });
            }
        }
        let n = self.n(if crit { 6 } else { 4 });
        for k in 0..n {
            let d = emission_dir(dir, fallback, self.rng.next_f32(), self.rng.next_f32());
            let mut p = P {
                vel: d * self.rng.range_f32(100.0, if crit { 220.0 } else { 160.0 }),
                drag: 7.0,
                size: (0.35, 0.12),
                color,
                glow: true,
                rot: angle,
                ..P::new(self.f.ember, at, 0.22, layer::EMISSIVE + 1.0)
            };
            match identity {
                Some(Lamp) => {
                    p.accel = Vec2::Y * 190.0;
                    p.life = 0.34;
                    p.color = Color::srgb(1.0, 0.31 + 0.07 * k as f32, 0.10);
                }
                Some(Sword) | None => {
                    p.frame = self.f.streak;
                    p.align = true;
                    p.stretch = 1.5;
                    p.life = 0.16;
                    p.size = (0.22, 0.04);
                }
                Some(Bell) => {
                    p.frame = self.f.ash;
                    p.stretch = 0.45;
                    p.spin = 9.0;
                    p.life = 0.18;
                    p.accel = Vec2::NEG_Y * 150.0;
                }
                Some(Crane) => {
                    // 美术的羽毛、纸屑四种随机挑；没有时用灰片
                    p.frame = self.f.feathers.map_or(self.f.ash, |f| f[self.rng.below(4) as usize]);
                    if self.f.feathers.is_some() {
                        // 32×16 像素的羽毛：画到 7 个世界单位上下，染成青绿的纸色
                        p.size = (0.9, 0.6);
                        p.color = color.mix(&Color::srgb(0.93, 0.9, 0.84), 0.45);
                    }
                    p.glow = false;
                    p.z = layer::ACTORS + 1.5;
                    p.accel = d.perp() * 180.0 + Vec2::NEG_Y * 55.0;
                    p.spin = if k % 2 == 0 { 18.0 } else { -16.0 };
                    p.stretch = if self.f.feathers.is_some() { 1.0 } else { 1.8 };
                    p.drag = 4.0;
                }
                Some(Seal) => {
                    p.frame = if k == n - 1 { self.f.smoke } else { self.f.ash };
                    p.glow = false;
                    p.z = layer::ACTORS + 1.5;
                    p.accel = Vec2::NEG_Y * 420.0;
                    p.spin = 7.0;
                    p.drag = 3.0;
                    p.life = 0.28;
                    p.size = if k == n - 1 { (0.18, 0.42) } else { (0.4, 0.3) };
                }
            }
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

    fn ult(&mut self, at: Vec2, radius: f32) {
        // 火线保留即时冲击，余烬从闪屏结束时接棒，越往后越稀疏。
        let count = self.n(60);
        for i in 0..count {
            let u = i as f32 / (count - 1) as f32;
            let delay = ULT_FLASH + 0.38 * u * u;
            let d = self.dir();
            let r = self.rng.range_f32(0.2, 1.0) * radius;
            let life = self.rng.range_f32(0.28, 0.5).min(ULT_END - delay);
            let p = P {
                vel: Vec2::new(self.rng.range_f32(-16.0, 16.0), self.rng.range_f32(35.0, 70.0)),
                accel: Vec2::Y * 18.0,
                drag: 1.2,
                size: (self.rng.range_f32(0.5, 0.9) * (1.0 - u * 0.35), 0.08),
                color: GOLD.with_alpha(0.9 - u * 0.3),
                fade_in: 0.015 / life,
                glow: true,
                real_time: true,
                delay,
                ..P::new(self.f.ember, at + d * Vec2::new(r, r * 0.62), life, layer::EMISSIVE + 0.8)
            };
            self.spawn(p);
        }
        // 只给这次火线使用现实时间，不改变普通命中的粒子时钟。
        self.sparks_with_clock(at, GOLD, 30, 420.0, Vec2::ZERO, true);
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
            let frame = self.f.leaves[self.rng.below(4) as usize];
            // 美术的竹叶按原样；灰片拉长才像叶子
            let (size, stretch) = if self.f.real_leaves {
                ((self.rng.range_f32(1.3, 1.8), 0.9), 1.0)
            } else {
                ((self.rng.range_f32(1.5, 2.2), 0.9), 2.4)
            };
            let p = P {
                vel: Vec2::new(d.x * self.rng.range_f32(40.0, 110.0), self.rng.range_f32(20.0, 90.0)),
                accel: Vec2::new(0.0, -70.0),
                drag: 2.6,
                size,
                stretch,
                color: green.with_alpha(0.95),
                fade_in: 0.02,
                rot: self.rng.range_f32(0.0, TAU),
                spin: self.rng.range_f32(-9.0, 9.0),
                ..P::new(
                    frame,
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

    /// 铜钱剑挥一下（`SimEvent::Sweep`）：三道月牙笔锋依次扫过扇形，墨色垫底、金色和白热的两层发光，
    /// 像一刀挥过去留下的残影；弧上几点金火星往外迸，两头各闪一枚铜钱的光。`dir` 是画面方向的单位向量。
    /// 天罡（`full`）是绕身一整圈：六道笔锋接连转一圈，地上荡开一圈金光。
    pub fn sweep(&mut self, at: Vec2, dir: Vec2, arc: f32, radius: f32, full: bool, ring: FrameId) {
        let metal = Color::srgb(0.91, 0.85, 0.65);
        // 笔锋用偏暖的金：金系的淡金推亮以后发白，看不出是铜钱的颜色
        let gold = Color::srgb(1.0, 0.8, 0.45);
        let hot = |c: Color, k: f32| {
            let l = c.to_linear();
            Color::linear_rgba(l.red * k, l.green * k, l.blue * k, l.alpha)
        };
        // 月牙贴图是 64 × 16 个世界单位的一道“∪”（弧心在贴图上边外面）。扇形的弦长 2r·sin(arc/2)
        // 对上贴图宽度的九成；转到弧心朝主角、往外鼓，笔画中段离贴图中心 4.8 × 大小，摆到 0.75r 上
        let size = |half: f32| (2.0 * radius * half.min(FRAC_PI_2 * 0.7).sin() / (64.0 * 0.9)).max(0.25);
        let base = dir.y.atan2(dir.x);
        let (strokes, span, half) = if full { (6, TAU, PI / 6.0) } else { (3, arc * 0.5, arc * 0.5) };
        // 左右挥随机，连着挥不会一个方向
        let side = if self.rng.chance(0.5) { 1.0 } else { -1.0 };
        for k in 0..strokes {
            let u = if strokes > 1 { k as f32 / (strokes - 1) as f32 } else { 0.5 };
            let a = if full { base + side * u * span } else { base + side * (u - 0.5) * span };
            let d = Vec2::from_angle(a);
            let s = size(half);
            let at = at + d * (radius * 0.75 - 4.8 * s);
            let rot = a + FRAC_PI_2;
            let delay = k as f32 * if full { 0.022 } else { 0.03 };
            let fade = if full { 1.0 } else { 0.55 + 0.45 * u };
            for (color, scale, glow, z) in [
                (INK.with_alpha(0.55 * fade), 1.08, false, layer::ACTORS + 1.4),
                (hot(gold, 1.4).with_alpha(0.85 * fade), 1.0, true, layer::EMISSIVE + 1.2),
                (
                    hot(Color::srgb(1.0, 0.95, 0.82), 1.6).with_alpha(0.6 * fade),
                    0.6,
                    true,
                    layer::EMISSIVE + 1.25,
                ),
            ] {
                self.spawn(P {
                    size: (s * scale * 0.9, s * scale * 1.05),
                    color,
                    fade_in: 0.05,
                    rot,
                    glow,
                    delay,
                    ..P::new(self.f.slash, at, 0.2, z)
                });
            }
        }
        // 弧上迸出的金火星，顺着挥的方向带一点
        let n = if full { 10 } else { 5 };
        for _ in 0..self.n(n) {
            let a =
                if full { self.rng.range_f32(0.0, TAU) } else { base + self.rng.range_f32(-0.5, 0.5) * arc };
            let d = Vec2::from_angle(a);
            let tangent = Vec2::new(-d.y, d.x) * side;
            let (speed, size, reach, life) = (
                self.rng.range_f32(160.0, 280.0),
                self.rng.range_f32(0.35, 0.5),
                self.rng.range_f32(0.5, 0.85),
                self.rng.range_f32(0.12, 0.22),
            );
            let p = P {
                vel: (d * 0.7 + tangent * 0.5) * speed,
                drag: 8.0,
                size: (size, 0.1),
                stretch: 1.8,
                color: hot(metal, 1.6),
                glow: true,
                align: true,
                ..P::new(self.f.streak, at + d * radius * reach, life, layer::EMISSIVE + 1.0)
            };
            self.spawn(p);
        }
        // 两头各闪一下铜钱的光（天罡在一圈上闪四下）
        let glints = if full { 4 } else { 2 };
        for k in 0..glints {
            let a = if full {
                base + k as f32 * TAU / 4.0
            } else {
                base + if k == 0 { -0.5 } else { 0.5 } * arc * 0.9
            };
            self.spawn(P {
                color: hot(Color::srgb(1.0, 0.86, 0.5), 2.2),
                size: (2.4, 0.6),
                glow: true,
                delay: if full { k as f32 * 0.03 } else { 0.03 + k as f32 * 0.04 },
                ..P::new(self.f.ember, at + Vec2::from_angle(a) * radius * 0.85, 0.12, layer::EMISSIVE + 1.3)
            });
        }
        if full {
            // 光环贴图 64 个世界单位宽
            self.halo(ring, at, 0.15, radius * 2.0 / 64.0, 0.35, hot(metal, 1.3).with_alpha(0.6));
        }
    }

    /// 一团一闪而过的亮心（孔明灯爆燃的火球）：软点放大，0.1–0.2 秒里涨大、淡掉。
    pub fn flash(&mut self, at: Vec2, size: f32, color: Color, life: f32) {
        self.spawn(P {
            size: (size, size * 1.6),
            color,
            glow: true,
            ..P::new(self.f.ember, at, life, layer::EMISSIVE + 1.3)
        });
    }

    /// 水花：沿 `dir`（画面方向）前方 ±spread 弧度溅出去的细流，往下落（沧浪起浪）。
    pub fn spray(&mut self, at: Vec2, dir: Vec2, spread: f32, color: Color, n: u32) {
        let base = dir.y.atan2(dir.x);
        for _ in 0..self.n(n) {
            let a = base + self.rng.range_f32(-spread, spread);
            let (speed, life, size) = (
                self.rng.range_f32(160.0, 340.0),
                self.rng.range_f32(0.25, 0.45),
                self.rng.range_f32(0.7, 1.1),
            );
            let p = P {
                vel: Vec2::from_angle(a) * speed,
                drag: 4.5,
                accel: Vec2::new(0.0, -220.0),
                size: (size, 0.15),
                stretch: 1.6,
                color,
                glow: true,
                align: true,
                ..P::new(self.f.streak, at, life, layer::EMISSIVE + 1.0)
            };
            self.spawn(p);
        }
    }

    /// 一串光点从 `from` 流回 `to`（青藤吸血：绿光顺着藤回到主角），0.3 秒左右到。
    pub fn drain(&mut self, from: Vec2, to: Vec2, color: Color, n: u32) {
        let d = to - from;
        let side = Vec2::new(-d.y, d.x).normalize_or_zero();
        for k in 0..self.n(n) {
            let (life, wobble, size) = (
                self.rng.range_f32(0.26, 0.34),
                self.rng.range_f32(-14.0, 14.0),
                self.rng.range_f32(0.8, 1.1),
            );
            // 拉长的光条顺着流的方向，比圆点在灯下看得清
            let p = P {
                vel: d / life + side * wobble,
                size: (size, size * 0.5),
                stretch: 2.2,
                color,
                fade_in: 0.15,
                glow: true,
                align: true,
                delay: k as f32 * 0.05,
                ..P::new(self.f.streak, from, life, layer::EMISSIVE + 1.1)
            };
            self.spawn(p);
        }
    }

    /// 播一段美术的逐帧特效：`scale` 相对美术原尺寸，`hold` 是播完以后停在最后一帧、慢慢淡掉的秒数，
    /// `delay` 秒后才开始。图集里没有这段、或者这一帧的预算用完了，返回 false，调用处画代码的粒子。
    #[allow(clippy::too_many_arguments)]
    pub fn anim(
        &mut self,
        fx: Fx,
        at: Vec2,
        scale: f32,
        rot: f32,
        color: Color,
        z: f32,
        hold: f32,
        delay: f32,
    ) -> bool {
        let Some(&first) = self.anims.get(fx as usize).and_then(|v| v.first()) else { return false };
        let len = self.anims[fx as usize].len() as f32 / ANIM_FPS;
        // 地上的墨溅随机左右镜像，一片片不重样
        let flip = fx == Fx::KillInk && self.rng.chance(0.5);
        // 算作核心：池满时可以挤掉同级的装饰粒子；预算用完被丢掉时返回 false，调用处退回代码画的
        self.spawn(P {
            size: (scale, scale),
            color,
            rot,
            glow: fx.glow(),
            anim: fx,
            delay,
            flip,
            core: true,
            ..P::new(first, at, len + hold, z)
        })
    }

    /// 地上一圈扩开的光（升级、点灯）。
    pub fn halo(&mut self, frame: FrameId, at: Vec2, from: f32, to: f32, life: f32, color: Color) {
        let p = P { size: (from, to), color, glow: true, ..P::new(frame, at, life, layer::EMISSIVE - 0.5) };
        self.spawn(p);
    }
}

/// 推进粒子，攒成绘制请求。普通粒子跟虚拟时间，燃灯按现实时间走完三拍。
pub(crate) fn update_particles(
    time: Res<Time>,
    real: Res<Time<Real>>,
    run: Option<Res<State<RunState>>>,
    feedback: Res<Feedback>,
    mut parts: ResMut<Particles>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
) {
    let dt = time.delta_secs();
    let real_dt = if run.is_some_and(|s| *s.get() == RunState::Paused) { 0.0 } else { real.delta_secs() };
    let parts = &mut *parts;
    let drop = parts.f.drop;
    let mut landed: Vec<Vec2> = Vec::new();
    parts.list.retain_mut(|p| {
        // 接触帧必须画到，即使本帧跨过了整个短闪光寿命。
        if p.fresh {
            p.fresh = false;
            return true;
        }
        let dt = if p.real_time { real_dt } else { dt };
        let active_dt = (dt - p.delay).max(0.0);
        p.delay = (p.delay - dt).max(0.0);
        let dt = active_dt;
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
    let anims = &parts.anims;
    for p in &mut parts.list {
        // 落地墨点在本轮推进后生成，也从第一次绘制后开始计时。
        p.fresh = false;
        if p.delay > 0.0 {
            continue;
        }
        let u = p.t / p.life;
        let size = p.size.0 + (p.size.1 - p.size.0) * u;
        let fade_in = if p.fade_in > 0.0 { (u / p.fade_in).min(1.0) } else { 1.0 };
        let fade_out = if u > 0.5 { 1.0 - (u - 0.5) / 0.5 } else { 1.0 };
        // 逐帧特效：按 24 帧换帧，淡入淡出画在图里；播完停在最后一帧的，停的这段里淡掉
        let (frame, fade_out) = match anims.get(p.anim as usize).filter(|_| p.anim != Fx::None) {
            Some(frames) if !frames.is_empty() => anim_frame(frames, p.t, p.life),
            _ => (p.frame, fade_out),
        };
        let alpha = p.color.alpha()
            * fade_in
            * fade_out
            * fade_out.sqrt()
            * p.category.visibility(&feedback, p.priority, 1.0);
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
        // 地上的墨点画成扁的（逐帧特效的地面帧美术已经压扁了）
        let scale = if p.z < layer::SHADOW && p.anim == Fx::None {
            Vec2::new(scale.x, scale.y * 0.62)
        } else {
            scale
        };
        if p.glow {
            glow.add_flipped(frame, pos, scale, rot, color, p.flip);
        } else {
            pools.fx.push(Draw { scale, rot, color, flip: p.flip, ..Draw::new(frame, pos) });
        }
    }
}

pub(crate) fn reset_particles(mut parts: ResMut<Particles>, mut clock: ResMut<ParticleClock>) {
    parts.clear();
    *clock = ParticleClock::default();
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
/// 本帧的计数和暴击笔触的冷却。
#[derive(Resource, Default)]
pub(crate) struct ParticleClock {
    trail_cd: f32,
    /// 主角走过的路，每一步扬一点尘
    stride: f32,
    last_hero: Option<Vec2>,
}

pub(crate) fn particle_events(
    time: Res<Time>,
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    feedback: Res<Feedback>,
    feel: Res<Feel>,
    frames: Res<ActorFrames>,
    hero: Single<(&Transform, &Player, &HeroView)>,
    arsenal: Option<Res<Arsenal>>,
    lanterns: Option<Res<lantern_sim::lanterns::Lanterns>>,
    bamboo: Option<Res<Bamboo>>,
    director: Option<Res<Director>>,
    enemies: Option<Res<Enemies>>,
    fixed: Res<Time<Fixed>>,
    mut clock: ResMut<ParticleClock>,
    mut parts: ResMut<Particles>,
    (phase, mut evolving): (Option<Res<lantern_sim::SimPhase>>, Local<Option<u16>>),
) {
    let dt = time.delta_secs();
    clock.trail_cd -= dt;
    let (htf, pl, view) = *hero;
    let hero_at = htf.translation.truncate();
    let mut bamboo_bursts = 0;
    let mut pulses = 0;
    parts.begin_frame(feel.lite);
    // 进化：卡片收起、回到战斗的那一刻，在主角身上炸开（试玩第 1 轮：原来只有辉光一闪和界面卡片）；
    // 共约 114 个，在高光那一档的每帧预算（128）里
    for ev in &outbox.0 {
        if let SimEvent::Evolve { weapon, .. } = *ev {
            *evolving = Some(weapon);
        }
    }
    if let Some(weapon) = *evolving
        && phase.as_deref() == Some(&lantern_sim::SimPhase::Play)
    {
        *evolving = None;
        let color = element_glow(content.0.weapons.get(usize::from(weapon)).map(|w| w.element));
        parts.priority = Priority::Ultimate;
        parts.category = Category::Decorative;
        let bright = |c: Color, k: f32| {
            let l = c.to_linear();
            Color::linear_rgba(l.red * k, l.green * k, l.blue * k, 1.0)
        };
        // 美术的进化爆发（一朵放射的光，512 像素 = 128 个世界单位）和脚下升起的光柱（锚点在底边），先占预算
        parts.anim(
            Fx::Evolve,
            hero_at + Vec2::Y * 16.0,
            1.4,
            0.0,
            hdr(Color::WHITE, 1.3),
            layer::EMISSIVE + 1.3,
            0.0,
            0.0,
        );
        parts.anim(Fx::Pillar, hero_at, 1.2, 0.0, hdr(Color::WHITE, 1.2), layer::EMISSIVE + 1.25, 0.0, 0.0);
        parts.halo(frames.ring, hero_at, 0.2, 8.0, 0.9, bright(GOLD, 1.8).with_alpha(0.95));
        parts.halo(frames.ring, hero_at, 0.1, 5.0, 0.7, bright(color, 1.6).with_alpha(0.9));
        parts.sparks(hero_at + Vec2::Y * 14.0, bright(color, 1.5), 36, 520.0, Vec2::ZERO);
        parts.sparks(hero_at + Vec2::Y * 14.0, bright(GOLD, 1.5), 18, 380.0, Vec2::new(0.0, 0.6));
        parts.embers(hero_at, 40.0, GOLD, 30);
        parts.ink(hero_at + Vec2::Y * 6.0, 20, 2.2);
        parts.dust(hero_at, 8, 1.6, INK.with_alpha(0.5));
    }
    for &index in &feedback.selected {
        let Some(ev) = outbox.0.get(index) else { continue };
        parts.priority = Priority::of(ev);
        parts.category = Category::of(ev);
        match *ev {
            SimEvent::Hit {
                impact_pos, incoming_dir, crit, kind, element, weapon, source, damage, ..
            } => {
                let at = to_screen(impact_pos);
                let identity = WeaponIdentity::resolve(&content.0, weapon);
                let element = element
                    .or_else(|| weapon.and_then(|i| content.0.weapons.get(i as usize).map(|w| w.element)))
                    .or_else(|| match source {
                        lantern_sim::combat::Source::Burn => Some(Element::Fire),
                        lantern_sim::combat::Source::Reaction(i) => {
                            content.0.elements.reactions.get(i as usize).map(|r| r.b)
                        }
                        _ => None,
                    });
                let color = element_glow(element);
                if matches!(kind, HitKind::Dot | HitKind::Reaction) {
                    if pulses < 12 {
                        pulses += 1;
                        let f = parts.f.ember;
                        parts.spawn(P {
                            color: color.with_alpha(0.5),
                            size: (0.65, 0.3),
                            glow: true,
                            ..P::new(f, at, 0.03, layer::EMISSIVE)
                        });
                    }
                    continue;
                }
                let fallback = (at - hero_at).normalize_or_zero() * 0.7;
                parts.impact(at, to_screen(incoming_dir), fallback, identity, color, crit);
                // 美术的命中爆点：五行各一种，按五行色染、推过辉光阈值；暴击换成白金的大闪，
                // 符剑的暴击再沿来势划一道刀光（弧心在命中点后面，弧的中段正好扫过妖物）
                let d = to_screen(incoming_dir).normalize_or(if fallback == Vec2::ZERO {
                    Vec2::X
                } else {
                    fallback
                });
                let rot = d.y.atan2(d.x);
                // 铜钱剑：命中飞出铜钱影子 weapons/coin_spark（颜色画在图里），暴击一个铜钱十字 coin_cross
                let coin = weapon
                    .and_then(|i| content.0.weapons.get(i as usize))
                    .is_some_and(|w| w.id == "coin_sword");
                let coin_art = coin
                    && if crit {
                        parts.anim(
                            Fx::CoinCross,
                            at,
                            1.0,
                            rot,
                            hdr(COIN, 1.4),
                            layer::EMISSIVE + 1.3,
                            0.0,
                            0.0,
                        )
                    } else {
                        parts.anim(
                            Fx::CoinSpark,
                            at,
                            1.0,
                            rot,
                            hdr(Color::WHITE, 1.2),
                            layer::EMISSIVE + 1.2,
                            0.0,
                            0.0,
                        )
                    };
                if coin_art {
                    // 铜钱剑用自己的命中图
                } else if crit {
                    let big = damage >= 1000.0;
                    parts.anim(
                        Fx::Crit,
                        at,
                        if big { 1.3 } else { 1.0 },
                        rot,
                        hdr(Color::WHITE, 1.2),
                        layer::EMISSIVE + 1.3,
                        0.0,
                        0.0,
                    );
                    if identity == Some(WeaponIdentity::Sword) {
                        // vfx/slash：弧心在锚点、弧半径 50 个世界单位（radius_px 200 ÷ 4），这里画成 26
                        let k = 26.0 / 50.0;
                        parts.anim(
                            Fx::Slash,
                            at - d * 26.0,
                            k,
                            rot,
                            hdr(color, 1.4),
                            layer::EMISSIVE + 1.25,
                            0.0,
                            0.0,
                        );
                    }
                } else {
                    parts.anim(
                        Fx::hit(element),
                        at,
                        1.0,
                        rot,
                        hdr(color, 1.3),
                        layer::EMISSIVE + 1.2,
                        0.0,
                        0.0,
                    );
                }
            }
            SimEvent::Kill { pos, kind, rank, .. } => {
                let def = &content.0.enemies[kind as usize];
                let at = to_screen(pos);
                let body = at + Vec2::new(0.0, def.radius.max(8.0));
                let eye = hex(&def.eye);
                // 美术的击杀墨溅：一滴墨砸在地上开花，停在最后一帧慢慢淡掉（地上那一层，暗处看不见，灯下才看得见）
                let (ink, hold) = match rank {
                    Rank::Boss => (2.6, 2.0),
                    Rank::Elite => (1.3, 1.2),
                    _ => ((def.radius / 20.0).clamp(0.5, 0.9), 0.6),
                };
                parts.anim(
                    Fx::KillInk,
                    at,
                    ink,
                    0.0,
                    Color::WHITE.with_alpha(0.9),
                    layer::GROUND + 0.95,
                    hold,
                    0.0,
                );
                // 精英、夜主倒下：地上一圈冲击波荡开
                if rank != Rank::Normal {
                    let k = if rank == Rank::Boss { 4.5 } else { 1.4 };
                    parts.anim(Fx::Shockwave, at, k, 0.0, hdr(SHOCK, 1.3), layer::EMISSIVE - 0.4, 0.0, 0.0);
                }
                match rank {
                    Rank::Elite => {
                        parts.ink(body, 16, 1.6);
                        parts.ash(body, def.radius, 14, INK.with_alpha(0.8));
                        parts.smoke(body, 1.2, INK.with_alpha(0.45), 5);
                        parts.sparks(body, eye, 12, 260.0, Vec2::ZERO);
                        parts.embers(body, def.radius, eye, 10);
                    }
                    // 夜主倒下：化成一大团墨，墨点四溅，灰烬冲天
                    Rank::Boss => {
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
                        // 落印的冲击波按落印半径（美术的环 radius_px 220 = 55 个世界单位），染土色
                        let earth = element_glow(Some(Element::Earth));
                        parts.anim(
                            Fx::Shockwave,
                            at,
                            radius / 55.0,
                            0.0,
                            hdr(earth, 1.3),
                            layer::EMISSIVE - 0.4,
                            0.0,
                            0.0,
                        );
                    }
                    StrikeFx::Bamboo => {
                        parts.dust(at, 12, radius / 40.0, DUST);
                        parts.sparks(at, element_glow(Some(Element::Wood)), 8, 140.0, Vec2::Y);
                    }
                    StrikeFx::SwordGrove => {
                        parts.sparks(at, element_glow(Some(Element::Metal)), 12, 220.0, Vec2::NEG_Y);
                        parts.ink(at, 5, 1.0);
                    }
                    StrikeFx::Blast(b) => {
                        let c = if b == BlastKind::Ice { element_glow(Some(Element::Water)) } else { FIRE };
                        // 美术的火爆（radius_px 144 = 36 个世界单位，颜色画在图里），第 5 帧起墨烟跟上、留一会儿；
                        // 冰爆是冰碎（192 像素 = 48 个世界单位，染冰蓝）
                        if b == BlastKind::Ice {
                            let ice = Color::srgb(0.8, 0.92, 1.0);
                            parts.anim(
                                Fx::IceShatter,
                                at,
                                radius / 24.0,
                                0.0,
                                hdr(ice, 1.3),
                                layer::EMISSIVE + 1.1,
                                0.0,
                                0.0,
                            );
                        } else if parts.anim(
                            Fx::FireBurst,
                            at,
                            radius / 36.0,
                            0.0,
                            hdr(Color::WHITE, 1.2),
                            layer::EMISSIVE + 1.1,
                            0.0,
                            0.0,
                        ) {
                            parts.anim(
                                Fx::FireSmoke,
                                at,
                                radius / 36.0,
                                0.0,
                                Color::WHITE.with_alpha(0.8),
                                layer::ACTORS + 1.45,
                                0.5,
                                5.0 / ANIM_FPS,
                            );
                        }
                        // 逐帧图先占本帧的预算，火星、余烬在后
                        parts.sparks(at, c, 8, 200.0, Vec2::ZERO);
                        parts.embers(at, radius * 0.4, c, 4);
                    }
                    StrikeFx::Quake => {
                        parts.dust(at, 18, radius / 40.0, DUST);
                        parts.anim(
                            Fx::Shockwave,
                            at,
                            (radius / 55.0).min(6.0),
                            0.0,
                            hdr(SHOCK, 1.1),
                            layer::EMISSIVE - 0.4,
                            0.0,
                            0.0,
                        );
                    }
                    StrikeFx::Ult => {
                        parts.ult(at, radius);
                        parts.anim(
                            Fx::Shockwave,
                            at,
                            (radius / 55.0).min(8.0),
                            0.0,
                            hdr(GOLD, 1.5),
                            layer::EMISSIVE - 0.4,
                            0.0,
                            0.0,
                        );
                    }
                    _ => {}
                }
            }
            // 孔明灯落地爆燃：火星往上溅、余烬飘起，烧焦的红纸片落下来，一圈火光荡开、一点焦烟
            SimEvent::LanternBurst { pos, radius, evolved } => {
                let at = to_screen(pos);
                let k = if evolved { 1.3 } else { 1.0 };
                // 美术的火爆（接在灯坠下的最后一帧后面，按爆燃半径缩放）和第 5 帧起的墨烟；
                // 没有这段时，先一团过辉光阈值的火球、一圈火光。火星、余烬、烧焦的纸片照旧
                if parts.anim(
                    Fx::FireBurst,
                    at,
                    radius / 36.0,
                    0.0,
                    hdr(Color::WHITE, 1.2),
                    layer::EMISSIVE + 1.1,
                    0.0,
                    0.0,
                ) {
                    parts.anim(
                        Fx::FireSmoke,
                        at,
                        radius / 36.0,
                        0.0,
                        Color::WHITE.with_alpha(0.8),
                        layer::ACTORS + 1.45,
                        0.5,
                        5.0 / ANIM_FPS,
                    );
                } else {
                    parts.flash(
                        at + Vec2::Y * 6.0,
                        radius / 5.0,
                        hdr(Color::srgb(1.0, 0.72, 0.38), 2.6),
                        0.16,
                    );
                    parts.smoke(at, 1.6, INK.with_alpha(0.45), 5);
                    parts.halo(
                        frames.ring,
                        at,
                        0.2,
                        radius * 2.0 / 64.0,
                        0.45,
                        hdr(FIRE, 1.4).with_alpha(0.85),
                    );
                }
                parts.sparks(at, hdr(FIRE, 1.5), (22.0 * k) as u32, 320.0, Vec2::Y * 0.4);
                parts.embers(at, radius * 0.5, FIRE, (12.0 * k) as u32);
                parts.ash(at, radius * 0.4, 6, LANTERN_PAPER);
            }
            // 沧浪推浪：主角身前顺着浪的方向溅起一片水花、一团水汽；北冥潮四面八方都溅，一圈寒光荡开
            SimEvent::Wave { pos, dir, radius, ring, .. } => {
                let at = to_screen(pos) + Vec2::Y * 6.0;
                let water = element_glow(Some(Element::Water));
                if ring {
                    for k in 0..8 {
                        let d = Vec2::from_angle(k as f32 * TAU / 8.0);
                        parts.spray(at + d * 18.0, d, 0.35, water.with_alpha(0.7), 3);
                    }
                    parts.halo(frames.ring, at, 0.3, radius * 2.0 / 64.0, 0.6, water.with_alpha(0.6));
                } else {
                    let d = (to_screen(pos + dir) - to_screen(pos)).normalize_or(Vec2::X);
                    // 浪起的那一下：一道水色的月牙笔锋往前鼓（宽按浪的半宽），溅一片水花、一点白沫
                    let size = radius * 2.0 / (64.0 * 0.9);
                    let a = d.y.atan2(d.x);
                    parts.slash(
                        at + d * (40.0 - 4.8 * size),
                        a + FRAC_PI_2,
                        size,
                        hdr(water, 1.4).with_alpha(0.7),
                        true,
                    );
                    parts.spray(at + d * 24.0, d, 0.5, water.with_alpha(0.8), 20);
                    parts.smoke(at + d * 34.0, 1.4, Color::srgba(0.88, 0.94, 1.0, 0.45), 3);
                }
            }
            // 青藤吸血：两颗绿光从被连着的妖物顺着藤流回主角；万木春缠住时那只身上冒几片叶子、一小圈绿光
            SimEvent::VineDrain { pos, bind, .. } => {
                let at = to_screen(pos) + Vec2::Y * 10.0;
                let wood = element_glow(Some(Element::Wood));
                parts.drain(at, hero_at + Vec2::Y * 14.0, hdr(wood, 1.8).with_alpha(0.9), 3);
                if bind {
                    parts.leaves(at, 3);
                    parts.halo(frames.ring, to_screen(pos), 0.1, 0.7, 0.35, wood.with_alpha(0.6));
                }
            }
            // 镇妖塔落地：一圈尘浪、墨点四溅、碎石，地上一圈土黄的光扩到吸妖的范围（2.2 倍半径）
            SimEvent::TowerLand { pos, radius, evolved } => {
                let at = to_screen(pos);
                let k = if evolved { 1.4 } else { 1.0 };
                // 美术的落地尘土（自带土墨色、已经压扁，radius_px 160 = 40 个世界单位，按落地半径缩放，
                // 塔砸下那一刻起播）；没有时用代码的尘浪
                if !parts.anim(
                    Fx::TowerDust,
                    at,
                    radius / 40.0 * k,
                    0.0,
                    Color::WHITE,
                    layer::ACTORS + 1.45,
                    0.3,
                    0.0,
                ) {
                    parts.dust(at, (16.0 * k) as u32, radius / 30.0 * k, DUST);
                }
                parts.ink(at, (10.0 * k) as u32, 1.6 * k);
                parts.ash(at, radius * 0.5, 6, TOWER_STONE);
                let earth = element_glow(Some(Element::Earth));
                parts.halo(frames.ring, at, 0.3, radius * 2.2 * 2.0 / 64.0, 0.5, earth.with_alpha(0.5));
            }
            // 玲珑塔到时间炸开：金色火线四射、余烬、大团尘浪和墨，一圈大的金光
            SimEvent::TowerBurst { pos, radius } => {
                parts.priority = Priority::Impact;
                let at = to_screen(pos);
                // 美术的冲击波染金，按炸开的半径缩放（radius_px 220 = 55 个世界单位），先占预算；没有时一圈金光
                if !parts.anim(
                    Fx::Shockwave,
                    at,
                    radius / 55.0,
                    0.0,
                    hdr(SHOCK, 1.4),
                    layer::EMISSIVE - 0.4,
                    0.0,
                    0.0,
                ) {
                    parts.halo(frames.ring, at, 0.3, radius * 2.4 / 64.0, 0.6, GOLD.with_alpha(0.8));
                }
                parts.sparks(at, GOLD, 28, 320.0, Vec2::ZERO);
                parts.embers(at, radius * 0.6, GOLD, 16);
                parts.dust(at, 22, radius / 25.0, DUST);
                parts.ink(at, 16, 2.0);
            }
            // 铜钱剑：刀光从主角腰间挥出去（判定在地面，画面抬到腰的高度）
            SimEvent::Sweep { pos, dir, arc, radius, evolved, .. } => {
                let d = (to_screen(pos + dir) - to_screen(pos)).normalize_or(Vec2::X);
                let at = to_screen(pos) + Vec2::Y * 12.0;
                // 美术的铜钱剑刀光：锚点在弧心（主角腰间），radius_px 440 = 110 个世界单位；
                // 天罡的旋风 radius_px 464 = 116，冷却短、一圈很大，整体压到七成（美术的建议）。
                // 图集里没有时照旧用笔触拼
                let art = if evolved {
                    let spin = parts.rng.range_f32(0.0, TAU);
                    parts.anim(
                        Fx::CoinWhirl,
                        at,
                        radius / 116.0,
                        spin,
                        hdr(COIN, 1.2).with_alpha(0.7),
                        layer::EMISSIVE + 1.2,
                        0.0,
                        0.0,
                    )
                } else {
                    parts.anim(
                        Fx::CoinSlash,
                        at,
                        radius / 110.0,
                        d.y.atan2(d.x),
                        hdr(COIN, 1.3),
                        layer::EMISSIVE + 1.2,
                        0.0,
                        0.0,
                    )
                };
                if !art {
                    parts.sweep(at, d, arc, radius, evolved, frames.ring);
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
            // 讨封狐现形：“噗”地一团淡烟，顶在头上的那片叶子飘下来，妖眼色的火星迸开，一圈淡光荡开
            SimEvent::Unmasked { pos, kind } => {
                let def = content.0.enemies.get(usize::from(kind));
                let eye = def.map_or(Color::srgb(1.0, 0.82, 0.48), |d| hex(&d.eye));
                let at = to_screen(pos);
                let body = at + Vec2::new(0.0, def.map_or(12.0, |d| d.radius));
                parts.smoke(body, 1.1, Color::srgba(0.86, 0.88, 0.84, 0.55), 6);
                parts.leaves(body + Vec2::new(0.0, 12.0), 3);
                parts.sparks(body, eye, 8, 160.0, Vec2::ZERO);
                parts.halo(frames.ring, at, 0.15, 1.4, 0.45, eye.with_alpha(0.6));
            }
            // 竹魅射出竹刺：出手处崩出两三根竹片
            SimEvent::EnemyShot { pos, .. } => parts.splinters(to_screen(pos) + Vec2::new(0.0, 12.0), 3),
            // 夜主登场，狐火把结界里的竹丛烧平：每丛起一股狐火和焦烟，结界边上烧起一圈
            // 夜主换阶段：身上炸开一团墨，妖眼色的火线四射，一圈妖光荡开；三阶更猛
            SimEvent::BossPhase { phase } => {
                let Some((i, en)) = director
                    .as_ref()
                    .and_then(|d| d.boss)
                    .zip(enemies.as_ref())
                    .and_then(|(h, en)| Some((en.resolve(h)?, en)))
                else {
                    continue;
                };
                let def = &content.0.enemies[en.kind[i] as usize];
                let at = to_screen(Vec2::new(en.x[i], en.y[i]));
                let body = at + Vec2::new(0.0, def.radius.max(8.0));
                let eye = hex(&def.eye);
                let k = if phase >= 3 { 1.5 } else { 1.0 };
                parts.ink(body, (28.0 * k) as u32, 2.0 * k);
                parts.smoke(body, 1.8 * k, INK.with_alpha(0.5), (6.0 * k) as u32);
                parts.sparks(body, eye, (22.0 * k) as u32, 360.0, Vec2::ZERO);
                parts.embers(body, def.radius * k, eye, (18.0 * k) as u32);
                parts.halo(frames.ring, at, 0.2, 4.0 * k, 0.9, eye.with_alpha(0.85));
            }
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
    parts.priority = Priority::Ambient;
    parts.category = Category::Decorative;
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
                    let ice = k % 2 == 0
                        && matches!(
                            slot.behavior(&content.0),
                            lantern_content::WeaponBehavior::Orbit { ice_fire: Some(_), .. }
                        );
                    parts.embers(p, 3.0, if ice { Color::srgb(0.4, 0.8, 1.0) } else { FIRE }, 1);
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
/// 冲击波环的颜色（美术建议的染色）
const SHOCK: Color = Color::srgb(1.0, 0.886, 0.659);
/// 铜钱剑的铜金（美术建议的染色 #F2C46A）
const COIN: Color = Color::srgb(0.949, 0.769, 0.416);

/// 在线性空间里推亮（超过 1 的部分过辉光阈值、晕开）。
fn hdr(c: Color, k: f32) -> Color {
    let l = c.to_linear();
    Color::linear_rgba(l.red * k, l.green * k, l.blue * k, l.alpha)
}

/// 孔明灯烧焦的红纸片、镇妖塔崩出的碎石
const LANTERN_PAPER: Color = Color::srgb(0.62, 0.2, 0.12);
const TOWER_STONE: Color = Color::srgb(0.45, 0.38, 0.3);

/// 七成样本落在入射方向 ±30°，其余完整散射；无方向沿用旧偏置。
fn emission_dir(dir: Vec2, fallback: Vec2, choose: f32, spread: f32) -> Vec2 {
    if dir == Vec2::ZERO {
        return (Vec2::from_angle(spread * TAU) + fallback).normalize_or(Vec2::X);
    }
    let angle =
        if choose < 0.7 { dir.y.atan2(dir.x) + (spread * 2.0 - 1.0) * PI / 6.0 } else { spread * TAU };
    Vec2::from_angle(angle)
}

#[cfg(test)]
mod identity_tests {
    use super::*;

    #[test]
    fn seventy_percent_is_directed_and_zero_uses_old_scatter() {
        let d = Vec2::from_angle(1.2);
        let mut inside = 0;
        for i in 0..100 {
            for j in 0..100 {
                let choose = (i as f32 + 0.5) / 100.0;
                let spread = (j as f32 + 0.5) / 100.0;
                let v = emission_dir(d, Vec2::ZERO, choose, spread);
                let in_cone = v.dot(d) >= (PI / 6.0).cos() - 1e-6;
                if choose < 0.7 {
                    assert!(in_cone);
                }
                inside += usize::from(in_cone);
            }
        }
        assert!((7000..=7600).contains(&inside));
        let fallback = Vec2::X * 0.7;
        assert_eq!(
            emission_dir(Vec2::ZERO, fallback, 0.2, 0.25),
            (Vec2::from_angle(TAU * 0.25) + fallback).normalize()
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newborn_particles_keep_initial_age_and_pose_then_follow_virtual_time() {
        for dt in [1.0 / 60.0, 1.0 / 30.0, 0.8] {
            let mut app = App::new();
            let mut parts = pool();
            let p = P {
                vel: Vec2::new(100.0, 20.0),
                accel: Vec2::Y * 10.0,
                drag: 2.0,
                h: 5.0,
                vh: 40.0,
                rot: 0.3,
                spin: 3.0,
                ..P::new(FrameId(0), Vec2::new(10.0, 20.0), 0.3, layer::ACTORS)
            };
            parts.spawn(p);
            app.insert_resource(parts)
                .init_resource::<Time>()
                .init_resource::<Time<Real>>()
                .init_resource::<Feedback>()
                .init_resource::<Pools>()
                .init_resource::<GlowRequests>()
                .add_systems(Update, update_particles);
            app.world_mut().resource_mut::<Time>().advance_by(std::time::Duration::from_secs_f32(dt));
            app.update();
            let first = app.world().resource::<Particles>().list[0];
            assert_eq!(first.t, 0.0);
            assert_eq!(first.pos, p.pos);
            assert_eq!(first.vel, p.vel);
            assert_eq!((first.h, first.vh, first.rot), (p.h, p.vh, p.rot));
            let draws = &app.world().resource::<Pools>().fx;
            assert_eq!(draws.len(), 1);
            assert_eq!(draws[0].pos, (p.pos + Vec2::Y * p.h).extend(p.z));
            assert_eq!(draws[0].color.alpha(), 1.0);

            app.world_mut().resource_mut::<Time>().advance_by(std::time::Duration::ZERO);
            app.update();
            assert_eq!(app.world().resource::<Particles>().list[0].t, 0.0);
            app.world_mut().resource_mut::<Time>().advance_by(std::time::Duration::from_millis(20));
            app.update();
            let next = app.world().resource::<Particles>().list[0];
            assert!((next.t - 0.02).abs() < 1e-6);
            assert_ne!(next.pos, p.pos);
            assert_ne!(next.h, p.h);
            assert_ne!(next.rot, p.rot);
            app.world_mut().resource_mut::<Time>().advance_by(std::time::Duration::from_secs(1));
            app.update();
            assert_eq!(app.world().resource::<Particles>().len(), 0);
        }
    }

    #[test]
    fn splats_created_during_update_start_aging_after_their_first_draw() {
        let mut app = App::new();
        let mut parts = pool();
        parts.spawn(P {
            fresh: false,
            splat: true,
            h: 0.1,
            vh: -20.0,
            ..P::new(FrameId(0), Vec2::ZERO, 1.0, layer::ACTORS)
        });
        app.insert_resource(parts)
            .init_resource::<Time>()
            .init_resource::<Time<Real>>()
            .init_resource::<Feedback>()
            .init_resource::<Pools>()
            .init_resource::<GlowRequests>()
            .add_systems(Update, update_particles);
        app.world_mut().resource_mut::<Time>().advance_by(std::time::Duration::from_millis(20));
        app.update();
        let parts = app.world().resource::<Particles>();
        assert_eq!(parts.len(), 1);
        assert_eq!(parts.list[0].t, 0.0);
        // 落在地面那一层（#17 起影子在地面之下）
        assert!((layer::GROUND..layer::GROUND + 1.0).contains(&parts.list[0].z));
        app.update();
        assert!((app.world().resource::<Particles>().list[0].t - 0.02).abs() < 1e-6);
    }

    fn pool() -> Particles {
        let frame = FrameId(0);
        Particles {
            list: Vec::new(),
            rng: Pcg32::new(1, 2),
            lite: false,
            priority: Priority::Ambient,
            category: Category::Decorative,
            spawned: [0; Priority::ALL.len()],
            f: PFrames {
                dot: frame,
                streak: frame,
                smoke: frame,
                ash: frame,
                ember: frame,
                drop: frame,
                wisp: frame,
                slash: frame,
                leaves: [frame; 4],
                real_leaves: false,
                feathers: None,
            },
            anims: Vec::new(),
        }
    }

    /// 每帧预算用完以后，装饰粒子放不进去，核心（命中核心、逐帧图）照样放得进去。
    #[test]
    fn cores_are_not_dropped_by_the_frame_budget() {
        let mut parts = pool();
        parts.begin_frame(false);
        parts.priority = Priority::Normal;
        let budget = FRAME_BUDGET[Priority::Normal as usize];
        for _ in 0..budget {
            assert!(parts.spawn(P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0)));
        }
        assert!(!parts.spawn(P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0)));
        assert!(parts.spawn(P { core: true, ..P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0) }));
    }

    /// `load_anims` 按 `fx as usize` 取帧：`Fx::ALL` 必须和枚举的声明顺序一致。
    #[test]
    fn fx_table_follows_the_enum_order() {
        assert!(Fx::ALL.iter().enumerate().all(|(i, f)| *f as usize == i));
    }

    /// 逐帧特效 24 帧换一帧，播完停在最后一帧；停的那段里淡掉，没有停的不淡。
    #[test]
    fn anim_frames_advance_at_24_fps_and_hold_the_last_one() {
        let frames: Vec<FrameId> = (10..16).map(FrameId).collect();
        let len = 6.0 / ANIM_FPS;
        assert_eq!(anim_frame(&frames, 0.0, len), (FrameId(10), 1.0));
        assert_eq!(anim_frame(&frames, 2.5 / ANIM_FPS, len).0, FrameId(12));
        assert_eq!(anim_frame(&frames, len * 0.99, len), (FrameId(15), 1.0));
        // 墨溅：多停 0.6 秒，停到一半时还剩根号 0.5
        let (frame, a) = anim_frame(&frames, len + 0.3, len + 0.6);
        assert_eq!(frame, FrameId(15));
        assert!((a - 0.5f32.sqrt()).abs() < 1e-4);
    }

    #[test]
    fn ult_embers_follow_the_real_beat_during_hitstop_in_both_quality_modes() {
        for lite in [false, true] {
            let mut app = App::new();
            let mut parts = pool();
            // 区分火线和余烬，直接检查绘制请求，不把已预约的粒子当成已经出现。
            parts.f.ember = FrameId(1);
            parts.begin_frame(lite);
            parts.priority = Priority::Ultimate;
            parts.ult(Vec2::ZERO, 400.0);
            let count = if lite { 30 } else { 60 };
            assert_eq!(parts.len(), count + count / 2);
            app.insert_resource(parts)
                .init_resource::<Time>()
                .init_resource::<Time<Real>>()
                .init_resource::<Feedback>()
                .init_resource::<Pools>()
                .init_resource::<GlowRequests>()
                .add_systems(Update, update_particles);
            // 即使事件帧很慢，也要先完整呈现冲击，余烬仍未出场。
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_secs(1));
            app.update();
            assert_eq!(app.world().resource::<GlowRequests>().0.len(), count / 2);
            assert!(app.world().resource::<Particles>().list.iter().all(|p| p.t == 0.0));

            let mut visible = Vec::new();
            // 虚拟时间始终为零：关闭/开启顿帧不改变这套演出的节拍。
            for ms in [100, 60, 100, 240, 400] {
                app.world_mut().resource_mut::<GlowRequests>().0.clear();
                app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(ms));
                app.update();
                let draws = &app.world().resource::<GlowRequests>().0;
                visible.push(draws.iter().filter(|p| p.frame == FrameId(1)).count());
            }
            assert_eq!(visible[0], 0);
            assert!(visible[1] > 0 && visible[1] < count);
            assert!(visible[2] > visible[1]);
            assert!(visible[3] > 0);
            assert_eq!(visible[4], 0);
            assert_eq!(app.world().resource::<Particles>().len(), 0);
        }
    }

    #[test]
    fn paused_ult_keeps_pending_embers_and_reset_clears_them() {
        let mut app = App::new();
        let mut parts = pool();
        parts.priority = Priority::Ultimate;
        parts.ult(Vec2::ZERO, 400.0);
        app.insert_resource(parts)
            .insert_resource(State::new(RunState::Paused))
            .init_resource::<Time>()
            .init_resource::<Time<Real>>()
            .init_resource::<Feedback>()
            .init_resource::<Pools>()
            .init_resource::<GlowRequests>()
            .init_resource::<ParticleClock>()
            .add_systems(Update, update_particles);
        app.update();
        app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_secs(2));
        app.update();
        let parts = app.world().resource::<Particles>();
        assert_eq!(parts.len(), 90);
        assert!(parts.list.iter().all(|p| p.t == 0.0));
        assert_eq!(parts.list.iter().filter(|p| p.delay > 0.0).count(), 60);
        app.add_systems(Last, reset_particles);
        app.update();
        assert_eq!(app.world().resource::<Particles>().len(), 0);
    }

    #[test]
    fn hostile_particles_bypass_frame_budget_and_survive_attack_highlights() {
        for lite in [false, true] {
            let mut parts = pool();
            parts.begin_frame(lite);
            let cap = if lite { CAP / 2 } else { CAP };
            let p = P { priority: Priority::Finale, ..P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0) };
            parts.list.resize(cap, p);
            parts.category = Category::Hostile;
            parts.priority = Priority::Impact;
            let count = FRAME_BUDGET[Priority::Impact as usize] as usize + 1;
            for _ in 0..count {
                parts.spawn(P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0));
            }
            assert_eq!(parts.len(), cap);
            assert_eq!(parts.list.iter().filter(|p| p.category == Category::Hostile).count(), count);
            assert_eq!(parts.spawned[Priority::Impact as usize], 0);
            parts.begin_frame(lite);
            parts.priority = Priority::Finale;
            for _ in 0..cap {
                parts.spawn(P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0));
            }
            assert_eq!(parts.list.iter().filter(|p| p.category == Category::Hostile).count(), count);
        }
    }

    #[test]
    fn small_particles_leave_room_for_crit_ult_and_boss_in_both_quality_modes() {
        for lite in [false, true] {
            let divisor = if lite { 2 } else { 1 };
            let mut parts = pool();
            let p = P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0);
            for _ in 0..40 {
                parts.begin_frame(lite);
                parts.priority = Priority::Normal;
                for _ in 0..200 {
                    parts.spawn(p);
                }
            }
            assert_eq!(parts.len(), (CAP - RESERVE) / divisor);
            parts.begin_frame(lite);
            for (priority, count) in
                [(Priority::Finale, 258), (Priority::Ultimate, 90), (Priority::Critical, 44)]
            {
                parts.priority = priority;
                for _ in 0..count / divisor {
                    parts.spawn(p);
                }
                assert_eq!(parts.list.iter().filter(|p| p.priority == priority).count(), count / divisor);
            }
            assert!(parts.len() <= CAP / divisor);
        }
    }

    #[test]
    fn full_pool_evicts_lower_priority_and_lite_switch_preserves_finale() {
        let mut parts = pool();
        let p = P { priority: Priority::Normal, ..P::new(FrameId(0), Vec2::ZERO, 1.0, 0.0) };
        parts.list = vec![p; CAP];
        parts.priority = Priority::Finale;
        parts.spawn(p);
        assert_eq!(parts.len(), CAP);
        assert_eq!(parts.list.iter().filter(|p| p.priority == Priority::Finale).count(), 1);
        parts.begin_frame(true);
        assert_eq!(parts.len(), CAP / 2);
        assert_eq!(parts.list[0].priority, Priority::Finale);
    }

    #[test]
    fn per_frame_particle_budget_is_shared_by_all_small_emitters() {
        let mut parts = pool();
        parts.priority = Priority::Normal;
        for _ in 0..500 {
            parts.sparks(Vec2::ZERO, GOLD, 8, 200.0, Vec2::ZERO);
            parts.embers(Vec2::ZERO, 20.0, GOLD, 4);
        }
        assert_eq!(parts.len(), FRAME_BUDGET[Priority::Normal as usize] as usize);
    }
}
