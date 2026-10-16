//! 法器与法术的画面（参照网页版 render/weaponViews.ts）：飞剑、纸鹤、石印与预警、地裂、
//! 寒波与各种环、连锁爆炸、太极、护盾、拾取物、夜主弹幕、奇遇的道具，以及闪屏。
//!
//! 持续存在的东西直接读模拟的资源；一次性的效果（环、印痕、爆炸）收到模拟事件后在这里记下，自己计时淡出。
//! 纯装饰的随机数用画面层自己的，不影响模拟。

use std::f32::consts::TAU;

use bevy::prelude::*;

use lantern_content::{BlastKind, Element, EventKind, Stat, WeaponBehavior, WeaponIdentity, ZoneKind};
use lantern_core::Pcg32;
use lantern_sim::boss::{BossState, Foes};
use lantern_sim::charms::Trail;
use lantern_sim::combat::StrikeFx;
use lantern_sim::encounters::Encounters;
use lantern_sim::enemies::CHARGE_WINDUP;
use lantern_sim::gold::Coins;
use lantern_sim::lanterns::Lanterns;
use lantern_sim::pickups::{PickupKind, Pickups};
use lantern_sim::reactions::{Herbs, Zones};
use lantern_sim::reveal::Reveal;
use lantern_sim::weapons::drop::{Fissures, Seals};
use lantern_sim::weapons::volley::Shots;
use lantern_sim::{
    AppState, Arsenal, Director, GameContent, Player, Pos, PrevPos, RunState, SimEvent, SimOutbox, Stats,
};

use crate::actors::{ActorFrames, Draw, GlowRequests, Pools, sort_z};
use crate::atlas::{AtlasDb, FrameId};
use crate::feedback::{Category, Feedback, Priority, eviction};
use crate::{MainCamera, layer, to_screen};

/// 透视：地面上的圆画成扁圆
const FLAT: f32 = 0.62;

/// 燃灯各拍用现实秒：收束与即时冲击叠起，不能为视觉蓄力推迟伤害。
const ULT_CONTRACT: f32 = 0.08;
const ULT_WAVE: f32 = 0.32;
pub(crate) const ULT_FLASH: f32 = 0.12;
pub(crate) const ULT_END: f32 = 0.8;

/// 冲击帧即为光爆峰值，保持 20ms，400ms 内交给余烬。
pub(crate) fn ult_flare(t: f32) -> f32 {
    0.8 * (1.0 - ((t - 0.02) / 0.38).clamp(0.0, 1.0))
}

fn rgb(hex: u32) -> Color {
    Color::srgb_u8((hex >> 16) as u8, (hex >> 8) as u8, hex as u8)
}

#[derive(Resource)]
pub(crate) struct FxFrames {
    sword: FrameId,
    sword_evo: FrameId,
    trail: FrameId,
    crane: Vec<FrameId>,
    crane_evo: Vec<FrameId>,
    seal: FrameId,
    seal_evo: FrameId,
    seal_mark: FrameId,
    warn: FrameId,
    ring: FrameId,
    wave: FrameId,
    ring_ink: FrameId,
    crack: FrameId,
    slash: FrameId,
    streak: FrameId,
    taiji: FrameId,
    shield: FrameId,
    chest: FrameId,
    soulbell: FrameId,
    lotus: FrameId,
    glow: FrameId,
    spark: FrameId,
    spring: Option<FrameId>,
    rift: Option<FrameId>,
    rift_glow: Option<FrameId>,
    lamp: Option<(FrameId, Option<FrameId>)>,
    altar: Option<(FrameId, Option<FrameId>)>,
    stone: Option<(FrameId, Option<FrameId>)>,
    /// 熄灭的石灯笼（和点亮的同尺寸、同锚点，直接换帧）
    stone_dark: Option<FrameId>,
    /// 狐村的留灯：没点、点着、点着的自发光（同画布、同锚点，挂钩在锚点）
    eave_lamp: Option<(FrameId, FrameId, Option<FrameId>)>,
    merchant: Option<(FrameId, Option<FrameId>)>,
    gem: Option<FrameId>,
    /// 地上的铜钱（普通）和它的微光（叠加）
    coin: Option<(FrameId, Option<FrameId>)>,
    /// 冲锋预警：车道、箭头
    charge: Option<(FrameId, FrameId)>,
    /// 反应留下的区域：赤地（底图 + 叠加光）、淤泥、灵草（底图 + 叠加光）
    zone_lava: Option<(FrameId, Option<FrameId>)>,
    zone_mud: Option<FrameId>,
    zone_herb: Option<(FrameId, Option<FrameId>)>,
    /// 精英词缀的小图标（按 `affixes.ron` 的顺序）
    affix: Vec<Option<FrameId>>,
    /// 墨点（合围预警的墨雾）
    ink: Vec<FrameId>,
}

/// 区域、扇形贴图在缩放 1 时的有效半径（世界单位）；图集 meta 里有 radius_px 时以它为准，这里是没有时的后备值。
const ZONE_LAVA_R: f32 = 43.0;
const ZONE_MUD_R: f32 = 45.5;
const ZONE_HERB_R: f32 = 39.5;

pub(crate) fn build_fx_frames(mut commands: Commands, db: Res<AtlasDb>, content: Res<GameContent>) {
    let need = |name: &str| db.find(name).unwrap_or_else(|| panic!("图集里缺少帧 {name}"));
    let seq = |prefix: &str| (0..4).filter_map(|i| db.find(&format!("{prefix}_{i}"))).collect::<Vec<_>>();
    let prop = |asset: &str| {
        db.find(&format!("{asset}/idle_S_00")).map(|f| (f, db.find(&format!("{asset}/idle_S_00_emit"))))
    };
    commands.insert_resource(FxFrames {
        sword: need("weapons/sword"),
        sword_evo: need("weapons/sword_evo"),
        trail: need("weapons/sword_trail"),
        crane: seq("weapons/crane"),
        crane_evo: seq("weapons/crane_evo"),
        seal: need("weapons/seal"),
        seal_evo: need("weapons/seal_evo"),
        seal_mark: need("weapons/seal_mark"),
        warn: need("weapons/warn"),
        ring: need("weapons/ring"),
        wave: need("fx/wave"),
        ring_ink: need("weapons/ring_ink"),
        crack: need("weapons/crack"),
        slash: need("fx/slash"),
        streak: need("fx/streak"),
        taiji: need("weapons/taiji"),
        shield: need("weapons/shield"),
        chest: need("weapons/chest"),
        soulbell: need("weapons/soulbell"),
        lotus: need("weapons/lotus"),
        glow: need("vfx/glow"),
        spark: need("vfx/spark"),
        spring: db.find("ground/spring"),
        rift: db.find("ground/rift"),
        rift_glow: db.find("ground/rift_glow"),
        lamp: prop("ancient_lamp"),
        altar: prop("blood_altar"),
        stone: prop("stone_lantern"),
        stone_dark: db.find("stone_lantern_dark/idle_S_00"),
        eave_lamp: db
            .find("fox_eave_lamp/idle_S_00")
            .zip(prop("fox_eave_lamp_lit"))
            .map(|(u, (l, e))| (u, l, e)),
        merchant: prop("merchant"),
        gem: db.find("vfx/gem_0"),
        coin: db.find("vfx/coin").map(|f| (f, db.find("vfx/coin_emit"))),
        charge: db.find("weapons/charge_line").zip(db.find("weapons/charge_line_head")),
        ink: (0..3).filter_map(|k| db.find(&format!("vfx/ink_{k}"))).collect(),
        zone_lava: db.find("ground/zone_lava").map(|f| (f, db.find("ground/zone_lava_glow"))),
        zone_mud: db.find("ground/zone_mud"),
        zone_herb: db.find("ground/zone_herb").map(|f| (f, db.find("ground/zone_herb_glow"))),
        affix: content.0.affixes.iter().map(|a| db.find(&format!("ui/icon_affix_{}", a.id))).collect(),
    });
}

#[derive(Clone, Copy)]
enum OneShot {
    Ring { color: Color, ink: bool, light: bool, strong: bool },
    Mark { evolved: bool },
    Blast { color: Color, ice: bool },
    Pulse,
    Toll,
    Quake,
    Ult,
    Reaction { color: Color },
    HostileBlast { color: Color },
    Taiji,
    Residue(WeaponIdentity),
}

fn residue_life(identity: WeaponIdentity) -> f32 {
    match identity {
        WeaponIdentity::Lamp => 1.1,
        WeaponIdentity::Sword => 0.45,
        WeaponIdentity::Bell => 0.7,
        WeaponIdentity::Crane => 0.9,
        WeaponIdentity::Seal => 1.0,
    }
}

struct Live {
    priority: Priority,
    kind: OneShot,
    pos: Vec2,
    r: f32,
    t: f32,
    fresh: bool,
    life: f32,
    rot: f32,
}

impl Live {
    fn category(&self) -> Category {
        self.kind.category()
    }

    fn advance(&mut self, dt: f32, real_dt: f32) -> bool {
        if matches!(self.kind, OneShot::Ult) {
            // 燃灯先画事件帧的收束姿态与光爆峰值；随后穿过顿帧继续演出。
            if !self.fresh {
                self.t += real_dt;
            }
        } else {
            self.t += dt;
        }
        self.fresh = false;
        self.t < self.life
    }
}

impl OneShot {
    fn category(self) -> Category {
        match self {
            Self::HostileBlast { .. } => Category::Hostile,
            _ => Category::Decorative,
        }
    }
}

/// 一次性效果、闪屏。震屏在 `camera.rs`。
#[derive(Resource)]
pub(crate) struct FxState {
    rng: Pcg32,
    live: Vec<Live>,
    time: f32,
    residue_quiet: f32,
    /// 石灯笼点亮的时刻（按下标），光区从小慢慢铺开
    lamp_lit: Vec<(u8, f32)>,
    pub flash: Color,
    priority: Priority,
    flash_priority: Priority,
    flash_fresh: bool,
    flash_decay: f32,
    /// 合围预警的墨雾：已经起了多久、预警多长、合拢后散了多久
    mist: Option<(f32, f32, Option<f32>)>,
}

impl Default for FxState {
    fn default() -> Self {
        FxState {
            rng: Pcg32::new(0xf00d_2026, 3),
            live: Vec::new(),
            time: 0.0,
            residue_quiet: 0.0,
            lamp_lit: Vec::new(),
            flash: Color::NONE,
            priority: Priority::Normal,
            flash_priority: Priority::Ambient,
            flash_fresh: false,
            flash_decay: 3.0,
            mist: None,
        }
    }
}

const MAX_LIVE: usize = 64;
const LIVE_RESERVE: usize = 8;

impl FxState {
    fn push(&mut self, kind: OneShot, pos: Vec2, r: f32, life: f32) {
        // 死亡残留是最低的一级：挤不掉普通招式，普通招式可以挤掉它；高潮（暴击以上）能用预留的格子。
        let category = kind.category();
        let priority = if matches!(kind, OneShot::Residue(_)) { Priority::Ambient } else { self.priority };
        let limit = if category == Category::Decorative && priority < Priority::Critical {
            MAX_LIVE - LIVE_RESERVE
        } else {
            MAX_LIVE
        };
        if self.live.len() >= limit {
            // 敌方出手可回收任意装饰槽，后来的玩家高光不能反向挤掉落点。
            // 64 槽因此始终能容纳一轮五雨点加一扫击；全是敌方效果时才轮换最旧的。
            let Some(index) = eviction(&self.live, (category, priority), |l| (l.category(), l.priority))
                .or_else(|| {
                    (category == Category::Hostile)
                        .then(|| self.live.iter().position(|l| l.category() == Category::Hostile))
                        .flatten()
                })
            else {
                return;
            };
            self.live.remove(index);
        }
        let rot = self.rng.range_f32(0.0, TAU);
        self.live.push(Live { kind, pos, r, t: 0.0, fresh: true, life, rot, priority });
    }

    fn flash(&mut self, color: Color, a: f32) {
        self.flash_with_decay(color, a, 3.0);
    }

    fn flash_with_decay(&mut self, color: Color, a: f32, decay: f32) {
        let cap: f32 = match self.priority {
            Priority::Hurt | Priority::Death => 0.18,
            Priority::Finale => 0.3,
            Priority::Ultimate => 0.24,
            Priority::Critical => 0.18,
            Priority::Impact => 0.12,
            _ => 0.06,
        };
        let a = a.min(cap);
        if self.priority > self.flash_priority
            || (self.priority == self.flash_priority && a >= self.flash.alpha())
            || self.flash.alpha() <= 0.0
        {
            self.flash = color.with_alpha(a);
            self.flash_priority = self.priority;
            self.flash_fresh = true;
            self.flash_decay = decay;
        }
    }
}

pub(crate) fn reset_fx(mut fx: ResMut<FxState>) {
    let rng = fx.rng.clone();
    *fx = FxState { rng, ..default() };
}

/// 五行的颜色（和 `elements.ron` 一致）。
fn element_rgb(e: Element) -> Color {
    match e {
        Element::Metal => rgb(0xe9d9a6),
        Element::Wood => rgb(0x6fd6a0),
        Element::Water => rgb(0x6fb8ff),
        Element::Fire => rgb(0xff8a3d),
        Element::Earth => rgb(0xc9925a),
    }
}

/// 把模拟事件变成一次性效果和闪屏。
pub(crate) fn read_fx_events(
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    time: Res<Time>,
    feel: Res<crate::Feel>,
    feedback: Res<Feedback>,
    mut fx: ResMut<FxState>,
) {
    fx.residue_quiet = (fx.residue_quiet - time.delta_secs()).max(0.0);
    let climax = outbox.0.iter().any(|e| {
        matches!(
            e,
            SimEvent::BossDefeated { .. }
                | SimEvent::Strike { fx: StrikeFx::Ult | StrikeFx::Taiji | StrikeFx::Toll, .. }
        )
    });
    if climax {
        fx.residue_quiet = 0.5;
        fx.live.retain(|l| !matches!(l.kind, OneShot::Residue(_)));
    }
    let mut residues = 0;
    let cap = if feel.lite { 12 } else { 24 };
    let per_frame = if feel.lite { 4 } else { 8 };
    for &index in &feedback.selected {
        let ev = &outbox.0[index];
        fx.priority = Priority::of(ev);
        match *ev {
            SimEvent::Kill { pos, kind, weapon, incoming_dir, .. }
                if fx.residue_quiet == 0.0 && residues < per_frame =>
            {
                let Some(identity) = WeaponIdentity::resolve(&content.0, weapon) else { continue };
                let count = fx.live.iter().filter(|l| matches!(l.kind, OneShot::Residue(_))).count();
                if count >= cap || fx.live.len() >= MAX_LIVE - 8 {
                    continue;
                }
                residues += 1;
                let radius = content.0.enemies[kind as usize].radius.clamp(8.0, 22.0);
                let before = fx.live.len();
                fx.push(OneShot::Residue(identity), to_screen(pos), radius, residue_life(identity));
                if fx.live.len() > before {
                    let dir = to_screen(incoming_dir);
                    fx.live.last_mut().unwrap().rot = dir.y.atan2(dir.x);
                }
            }
            SimEvent::Reaction { kind, pos, first, .. } => {
                let r = &content.0.elements.reactions[kind as usize];
                let color = element_rgb(r.b);
                fx.push(
                    OneShot::Reaction { color },
                    to_screen(pos),
                    if first { 90.0 } else { 46.0 },
                    if first { 0.6 } else { 0.35 },
                );
                if first {
                    fx.flash(color, 0.12);
                }
            }
            SimEvent::Strike { pos, radius, fx: kind } => {
                let p = to_screen(pos);
                match kind {
                    StrikeFx::Pulse => fx.push(OneShot::Pulse, p, radius, 0.45),
                    StrikeFx::Toll => fx.push(OneShot::Toll, p, radius, 0.7),
                    StrikeFx::Seal { evolved } => {
                        fx.push(OneShot::Mark { evolved }, p, radius, if evolved { 2.4 } else { 1.8 });
                        fx.push(OneShot::Quake, p, radius * 1.2, 0.35);
                    }
                    StrikeFx::Bamboo | StrikeFx::SwordGrove => {
                        let color = if kind == StrikeFx::Bamboo { rgb(0x80b879) } else { rgb(0xc0d8ef) };
                        fx.push(
                            OneShot::Ring { color, ink: true, light: false, strong: false },
                            p,
                            radius,
                            0.35,
                        );
                    }
                    StrikeFx::Blast(kind) => {
                        let color = if kind == BlastKind::Ice { rgb(0x6fb8ff) } else { rgb(0xff8a3d) };
                        fx.push(OneShot::Blast { color, ice: kind == BlastKind::Ice }, p, radius, 0.3);
                    }
                    StrikeFx::Quake => fx.push(OneShot::Quake, p, radius, 0.5),
                    StrikeFx::Taiji => fx.push(OneShot::Taiji, p, radius, 1.0),
                    StrikeFx::Ult => {
                        fx.push(OneShot::Ult, p, radius, ULT_END);
                        fx.flash_with_decay(rgb(0xffd98a), 0.55, 0.24 / ULT_FLASH);
                    }
                    StrikeFx::None => {}
                }
            }
            SimEvent::SweepStrike { pos, dir } => {
                let tip = pos + Vec2::new(dir.cos(), dir.sin()) * 110.0;
                fx.push(OneShot::HostileBlast { color: rgb(0xff4a3a) }, to_screen(tip), 120.0, 0.35);
            }
            // 回光、九转金丹：金色的大环，震屏
            SimEvent::LastStand { pos } | SimEvent::Revived { pos } => {
                let r = if matches!(ev, SimEvent::Revived { .. }) { 420.0 } else { 180.0 };
                fx.push(
                    OneShot::Ring { color: rgb(0xffd98a), ink: false, light: true, strong: true },
                    to_screen(pos),
                    r,
                    0.9,
                );
                fx.flash(rgb(0xfff1c2), 0.45);
            }
            SimEvent::RainStrike { pos } => {
                fx.push(OneShot::HostileBlast { color: rgb(0xff6b5a) }, to_screen(pos), 44.0, 0.3);
            }
            SimEvent::IllusionDispelled { pos } => fx.push(
                OneShot::Ring { color: rgb(0xd8c8ff), ink: false, light: true, strong: false },
                to_screen(pos),
                60.0,
                0.5,
            ),
            SimEvent::LanternLit { index, .. } => {
                fx.flash(rgb(0xffd98a), 0.25);
                let now = fx.time;
                fx.lamp_lit.push((index, now));
            }
            SimEvent::BossPhase { .. } => fx.flash(rgb(0xff3b30), 0.2),
            // 五连宝箱金光一闪（三连淡一些）
            SimEvent::ChestOpened { count, .. } if count >= 3 => {
                fx.flash(rgb(0xffd98a), if count >= 5 { 0.3 } else { 0.15 })
            }
            SimEvent::EncircleWarn { warn } => {
                fx.flash(rgb(0x1a1020), 0.35);
                fx.mist = Some((0.0, warn.max(0.3), None));
            }
            SimEvent::Encircle { .. } => {
                if let Some(m) = &mut fx.mist {
                    m.2 = Some(0.0);
                }
            }
            SimEvent::PlayerHurt { .. } | SimEvent::PlayerDied => {
                fx.flash(rgb(0xff3b30), 0.18);
            }
            SimEvent::BossArrived { .. } => {
                fx.flash(rgb(0xff6b5a), 0.2);
            }
            SimEvent::BossDefeated { .. } => {
                fx.flash(rgb(0xfff1c2), 0.6);
            }
            SimEvent::Pickup { kind: PickupKind::Bell, .. } => fx.flash(rgb(0x5fd4c4), 0.15),
            SimEvent::CritterLooted { .. } => fx.flash(rgb(0xffd98a), 0.2),
            SimEvent::Sacrifice { .. } => fx.flash(rgb(0xff3b30), 0.25),
            SimEvent::Buff { .. } => fx.flash(rgb(0xffd98a), 0.2),
            _ => {}
        }
    }
}

/// 法器、拾取物、弹幕、奇遇、一次性效果的绘制请求。
pub(crate) fn collect_fx(
    // 三种时间：虚拟（随顿帧）、现实（燃灯节拍）、定步长（插值）
    (time, real, fixed): (Res<Time>, Res<Time<Real>>, Res<Time<Fixed>>),
    run: Option<Res<State<RunState>>>,
    content: Res<GameContent>,
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    f: Res<FxFrames>,
    parts: Res<crate::particles::Particles>,
    feedback: Res<Feedback>,
    res: FxSources,
    player: Single<(&Pos, &PrevPos, &Player)>,
    cam: Single<(&Transform, &Projection), With<MainCamera>>,
    mut fx: ResMut<FxState>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
    mut foreground: ResMut<crate::foreground::Safety>,
) {
    foreground.clear();
    let dt = time.delta_secs();
    fx.time += dt;
    let now = fx.time;
    let a = fixed.overstep_fraction();
    let (ppos, pprev, pl) = *player;
    let hero = to_screen(pprev.0.lerp(ppos.0, a));
    let lerp = |prev: Vec2, cur: Vec2| to_screen(prev.lerp(cur, a));
    let px = |frame: FrameId, world: f32| world / db.frame(frame).size.x;

    // ---- 合围预警：屏幕四边起墨雾，预警期间往里压；合拢后 1.5 秒散去
    if let Some((t, warn, closing)) = &mut fx.mist {
        *t += dt;
        let a = match closing {
            Some(c) => {
                *c += dt;
                1.0 - *c / 1.5
            }
            None => (*t / *warn).min(1.0),
        };
        let (tf, proj) = *cam;
        if let (Projection::Orthographic(o), false) = (proj, f.ink.is_empty())
            && a > 0.0
        {
            let center = tf.translation.truncate();
            let half = o.area.half_size();
            let blob = half.y * 0.8;
            // 沿四边均匀放一圈墨团，随 a 往里压一点
            let (nx, ny) = (10, 6);
            let mut spots = Vec::with_capacity(2 * (nx + ny));
            for k in 0..nx {
                let x = -half.x + (k as f32 + 0.5) * 2.0 * half.x / nx as f32;
                spots.push(Vec2::new(x, half.y));
                spots.push(Vec2::new(-x, -half.y));
            }
            for k in 0..ny {
                let y = -half.y + (k as f32 + 0.5) * 2.0 * half.y / ny as f32;
                spots.push(Vec2::new(half.x, -y));
                spots.push(Vec2::new(-half.x, y));
            }
            let squeeze = 1.0 - 0.08 * a;
            for (k, spot) in spots.into_iter().enumerate() {
                let id = f.ink[k % f.ink.len()];
                let wobble = 1.0 + 0.15 * (k as f32 * 2.3 + now * 0.7).sin();
                let pos = center + spot * squeeze;
                let scale = Vec2::splat(blob * wobble / db.frame(id).size.x);
                let rot = k as f32 * 1.7 + now * 0.08;
                pools.fx.push(Draw {
                    scale,
                    rot,
                    color: rgb(0x0b0710).with_alpha(0.85 * a),
                    ..Draw::new(id, pos.extend(layer::NUMBERS - 10.0))
                });
                glow.add(
                    f.glow,
                    pos.extend(layer::EMISSIVE),
                    Vec2::splat(blob * 1.2 / db.frame(f.glow).size.x),
                    0.0,
                    rgb(0xff4a3a).with_alpha(0.12 * a),
                );
            }
        }
        if a <= 0.0 && closing.is_some() {
            fx.mist = None;
        }
    }

    let personal_start = (pools.fx.len(), glow.0.len());
    // ---- 照见圈：地上一圈淡淡的墨线；灯芯的灯焰带在圈边跳动
    if let Some(reveal) = &res.reveal
        && reveal.radius > 0.0
    {
        let k = px(f.ring_ink, reveal.radius * 2.0);
        pools.fx.push(Draw {
            scale: Vec2::new(k, k * FLAT),
            color: rgb(0x1d2433).with_alpha(0.22),
            ..Draw::new(f.ring_ink, hero.extend(layer::GROUND + 0.5))
        });
        if reveal.band_dps > 0.0 {
            let kr = px(f.wave, reveal.radius * 2.0 / 0.84);
            let flicker = 0.22 + 0.05 * (now * 9.0).sin();
            glow.add(
                f.wave,
                hero.extend(layer::EMISSIVE - 2.5),
                Vec2::new(kr, kr * FLAT),
                0.0,
                rgb(0xff9a4a).with_alpha(flicker),
            );
        }
    }

    // ---- 不夜城的内环火海
    if let (Some(arsenal), Some(stats)) = (&res.arsenal, &res.stats) {
        let c = &content.0;
        for slot in &arsenal.0 {
            if let WeaponBehavior::Pulse { permafrost: Some(_), .. } = slot.behavior(c) {
                let r = slot.stats(c).radius * stats.get(Stat::Area);
                let k = px(f.ring, r * 2.0);
                let pos = hero.extend(layer::GROUND + 0.9);
                pools.fx.push(Draw {
                    scale: Vec2::new(k, k * FLAT),
                    color: rgb(0x527d9a).with_alpha(0.45),
                    ..Draw::new(f.ring_ink, pos)
                });
                glow.add(
                    f.ring,
                    hero.extend(layer::EMISSIVE - 2.0),
                    Vec2::new(k, k * FLAT),
                    0.0,
                    rgb(0x8fd9ff).with_alpha(0.45),
                );
            }
            if let WeaponBehavior::Orbit { inner: Some(fire), .. } = slot.behavior(c) {
                let r = fire.radius * stats.get(Stat::Area);
                let kr = px(f.wave, r * 2.0 / 0.84);
                let flicker = 0.28 + 0.06 * (now * 11.0).sin();
                glow.add(
                    f.wave,
                    hero.extend(layer::EMISSIVE - 1.5),
                    Vec2::new(kr, kr * FLAT),
                    0.0,
                    rgb(0xff7a2a).with_alpha(flicker),
                );
                glow.light(&frames, &db, hero, (rgb(0xff8a3d).with_alpha(0.12), r * 1.6));
            }
        }
    }

    let visibility = Category::Decorative.visibility(&feedback, Priority::Normal, res.readability.gain);
    dim_personal(&mut pools, &mut glow, personal_start, visibility);

    // ---- 反应留下的区域：赤地（橙红的裂纹）、淤泥（暗褐的泥圈）
    if let Some(zones) = &res.zones {
        for z in &zones.0 {
            let p = to_screen(z.pos);
            let fade = (z.life / 0.5).min(1.0) * ((z.max_life - z.life) / 0.2).min(1.0);
            match (z.kind, f.zone_lava, f.zone_mud) {
                (ZoneKind::Lava, Some((base, glow_frame)), _) => {
                    let k = z.radius / db.frame(base).radius.unwrap_or(ZONE_LAVA_R);
                    pools.fx.push(Draw {
                        scale: Vec2::splat(k),
                        color: Color::WHITE.with_alpha(0.85 * fade),
                        ..Draw::new(base, p.extend(layer::GROUND + 0.88))
                    });
                    if let Some(g) = glow_frame {
                        let pulse = 0.75 + 0.25 * (now * 3.0 + z.pos.x * 0.05).sin();
                        glow.add(
                            g,
                            p.extend(layer::EMISSIVE - 3.0),
                            Vec2::splat(k),
                            0.0,
                            rgb(0xff7a2a).with_alpha(0.8 * fade * pulse),
                        );
                    }
                }
                (ZoneKind::Mud, _, Some(mud)) => {
                    pools.fx.push(Draw {
                        scale: Vec2::splat(z.radius / db.frame(mud).radius.unwrap_or(ZONE_MUD_R)),
                        color: Color::WHITE.with_alpha(0.85 * fade),
                        ..Draw::new(mud, p.extend(layer::GROUND + 0.87))
                    });
                }
                // 图集里没有区域贴图时的旧画法
                (ZoneKind::Lava, None, _) => {
                    let k = px(f.crack, z.radius * 2.0);
                    pools.fx.push(Draw {
                        scale: Vec2::new(k, k * 0.75),
                        color: rgb(0x5a1a08).with_alpha(0.6 * fade),
                        ..Draw::new(f.crack, p.extend(layer::GROUND + 0.88))
                    });
                    glow.add(
                        f.glow,
                        p.extend(layer::EMISSIVE - 3.0),
                        Vec2::new(z.radius / 40.0, z.radius / 40.0 * FLAT),
                        0.0,
                        rgb(0xff5a1f).with_alpha(0.5 * fade),
                    );
                }
                (ZoneKind::Mud, _, None) => {
                    let k = px(f.ring_ink, z.radius * 2.0);
                    pools.fx.push(Draw {
                        scale: Vec2::new(k, k * FLAT),
                        color: rgb(0x4a3a24).with_alpha(0.55 * fade),
                        ..Draw::new(f.ring_ink, p.extend(layer::GROUND + 0.87))
                    });
                }
            }
        }
    }

    // ---- 风火轮的火痕
    if let Some(trail) = &res.trail {
        for e in &trail.list {
            let p = to_screen(e.pos);
            let fade = (e.life / 0.5).min(1.0);
            let flicker = 0.75 + 0.25 * (now * 13.0 + e.pos.x * 0.1).sin();
            glow.add(
                f.glow,
                p.extend(layer::EMISSIVE - 3.0),
                Vec2::new(0.45, 0.45 * FLAT),
                0.0,
                rgb(0xff7a2a).with_alpha(0.6 * fade * flicker),
            );
        }
    }

    // ---- 灵草（滋生）
    if let Some(herbs) = &res.herbs {
        for h in &herbs.list {
            let p = to_screen(h.pos);
            let fade = (h.life / 0.6).min(1.0);
            let sway = (now * 2.4 + h.pos.x * 0.07).sin() * 0.08;
            if let Some((base, glow_frame)) = f.zone_herb {
                // 一小丛灵草，半径和拾取距离差不多
                let k = 24.0 / db.frame(base).radius.unwrap_or(ZONE_HERB_R);
                pools.fx.push(Draw {
                    scale: Vec2::splat(k),
                    color: Color::WHITE.with_alpha(fade),
                    ..Draw::new(base, p.extend(layer::GROUND + 0.89))
                });
                if let Some(g) = glow_frame {
                    glow.add(
                        g,
                        p.extend(layer::EMISSIVE - 3.0),
                        Vec2::splat(k),
                        0.0,
                        rgb(0x9cf0b8).with_alpha(fade),
                    );
                }
            } else {
                pools.fx.push(Draw {
                    scale: Vec2::splat(0.7),
                    rot: sway,
                    color: rgb(0x9cf0b8).with_alpha(fade),
                    ..Draw::new(f.lotus, p.extend(sort_z(layer::WEAPONS, h.pos.y)))
                });
            }
            glow.add(
                f.glow,
                (p + Vec2::new(0.0, 6.0)).extend(layer::EMISSIVE),
                Vec2::splat(0.35),
                0.0,
                rgb(0x6fd6a0).with_alpha(0.45 * fade),
            );
        }
    }

    // 狐村借用现有狐祠、石灯和狐狸帧；小狐无敌人实体、无红眼与血条。
    if let Some(v) = res.story.as_ref().and_then(|s| s.village.as_ref()) {
        use lantern_sim::story::{RADIUS, VillageStage};
        let p = to_screen(v.pos);
        if let Some(shrine) = db.find("fox_shrine/idle_S_00") {
            pools.fx.push(Draw {
                scale: Vec2::splat(1.15),
                ..Draw::new(shrine, (p + Vec2::new(0.0, 24.0)).extend(sort_z(layer::ACTORS, v.pos.y - 24.0)))
            });
        }
        // 青火仍在檐下；留下的是自己灯里分出的一缕暖光。
        glow.light(&frames, &db, p + Vec2::new(0.0, 30.0), (rgb(0x81cdb2).with_alpha(0.65), 100.0));
        // 火芯要看得见，不能只剩一片绿光；护住以后，摇动慢下来。
        let sway = (now * if v.stage == VillageStage::Guard { 5.0 } else { 1.8 }).sin();
        let fire = (p + Vec2::new(sway * 1.5, 30.0)).extend(layer::EMISSIVE);
        glow.add(f.spark, fire, Vec2::new(px(f.spark, 15.0), px(f.spark, 25.0)), sway * 0.08, rgb(0x8de4b9));
        glow.add(f.glow, fire, Vec2::splat(px(f.glow, 28.0)), 0.0, rgb(0x81cdb2).with_alpha(0.55));
        // 留灯挂在祠的左檐下（和石灯阵的石灯笼形制不同，不会被当成要点的灯）。
        if let Some((dark, lit_frame, emit)) = f.eave_lamp {
            let lit = v.stage == VillageStage::Lit;
            let hook = p + Vec2::new(-12.0, 24.0 + 18.0);
            let z = sort_z(layer::ACTORS, v.pos.y - 24.0) + 0.001;
            pools.fx.push(Draw {
                scale: Vec2::splat(0.8),
                ..Draw::new(if lit { lit_frame } else { dark }, hook.extend(z))
            });
            if lit {
                if let Some(emit) = emit {
                    glow.add(emit, hook.extend(layer::EMISSIVE), Vec2::splat(0.8), 0.0, Color::WHITE);
                }
                glow.light(&frames, &db, hook - Vec2::new(0.0, 7.0), (rgb(0xff9a4a).with_alpha(0.85), 70.0));
            }
        }
        if let Some(fox) = db.find("fox/move_E_00") {
            for i in 0..3 {
                let spread = if v.stage == VillageStage::Guard { 12.0 } else { 21.0 };
                let at = p + Vec2::new(-20.0 + i as f32 * spread, -8.0 - (i % 2) as f32 * 12.0);
                pools.fx.push(Draw {
                    scale: Vec2::new(if i == 2 { -0.42 } else { 0.42 }, 0.42),
                    color: rgb(0xc6b69b),
                    ..Draw::new(fox, at.extend(sort_z(layer::ACTORS, -at.y)))
                });
            }
        }
        if v.tending {
            let u = v.ticks as f32 / v.duration() as f32;
            let k = px(f.ring_ink, RADIUS * 2.0);
            pools.fx.push(Draw {
                scale: Vec2::new(k, k * FLAT),
                color: rgb(0x80af9b).with_alpha(0.12 + u * 0.22),
                ..Draw::new(f.ring_ink, p.extend(layer::GROUND + 0.55))
            });
        }
    }

    // ---- 石灯笼：没点亮的暗着，站在旁边时一圈进度；点亮后成为光区
    if let (Some(lanterns), Some((frame, emit))) = (&res.lanterns, f.stone) {
        let def = &content.0.run.lanterns;
        for (i, l) in lanterns.0.iter().enumerate() {
            let p = to_screen(l.pos);
            // 没点亮的用熄灭版；没有熄灭版时把点亮的压暗
            let (body, tint) = match (l.lit, f.stone_dark) {
                (true, _) => (frame, Color::WHITE),
                (false, Some(dark)) => (dark, Color::WHITE),
                (false, None) => (frame, Color::srgb(0.55, 0.55, 0.6)),
            };
            // 点亮后 1.5 秒里光区从小铺开（读档或回放跳转时没有记录，直接全开）
            let spread = fx.lamp_lit.iter().find(|&&(k, _)| k as usize == i).map_or(1.0, |&(_, t)| {
                let u = ((now - t) / 1.5).clamp(0.0, 1.0);
                1.0 - (1.0 - u) * (1.0 - u)
            });
            pools.fx.push(Draw {
                scale: Vec2::splat(1.25),
                color: tint,
                ..Draw::new(body, p.extend(sort_z(layer::ACTORS, l.pos.y)))
            });
            if l.lit {
                if let Some(emit) = emit {
                    glow.add(emit, p.extend(layer::EMISSIVE), Vec2::splat(1.25), 0.0, Color::WHITE);
                }
                glow.light(
                    &frames,
                    &db,
                    p + Vec2::new(0.0, 30.0),
                    (rgb(0xffc56b).with_alpha(0.9), def.zone_radius * (0.25 + 0.75 * spread)),
                );
                let k = px(f.ring_ink, def.zone_radius * 2.0 * spread);
                pools.fx.push(Draw {
                    scale: Vec2::new(k, k * FLAT),
                    color: rgb(0x8a5a1c).with_alpha(0.2),
                    ..Draw::new(f.ring_ink, p.extend(layer::GROUND + 0.55))
                });
            } else {
                let u = (l.progress / def.light_time).clamp(0.0, 1.0);
                let pulse = 0.35 + 0.2 * (now * 2.5).sin();
                let k = px(f.ring, def.light_radius * 2.0);
                glow.add(
                    f.ring,
                    p.extend(layer::EMISSIVE - 3.0),
                    Vec2::new(k, k * FLAT),
                    0.0,
                    rgb(0xffd98a).with_alpha(pulse + u * 0.5),
                );
                if u > 0.0 {
                    glow.light(
                        &frames,
                        &db,
                        p + Vec2::new(0.0, 30.0),
                        (rgb(0xffc56b).with_alpha(u * 0.8), 60.0 + u * 80.0),
                    );
                }
            }
        }
    }

    // ---- 铜钱：方孔铜钱，暗处有一点微光；被吸住时飞向主角
    if let (Some(coins), Some((coin, emit))) = (&res.coins, f.coin) {
        for c in &coins.0 {
            let p = lerp(c.prev, c.pos);
            let bob = (now * 4.0 + c.pos.x * 0.13).sin() * 1.5;
            let at = p + Vec2::new(0.0, bob);
            pools.fx.push(Draw::new(coin, at.extend(sort_z(layer::GEMS, c.pos.y))));
            if let Some(emit) = emit {
                glow.add(emit, at.extend(layer::EMISSIVE), Vec2::ONE, 0.0, Color::WHITE.with_alpha(0.7));
            }
        }
    } else if let (Some(coins), Some(gem)) = (&res.coins, f.gem) {
        for c in &coins.0 {
            let p = lerp(c.prev, c.pos);
            let bob = (now * 4.0 + c.pos.x * 0.13).sin() * 1.5;
            pools.fx.push(Draw {
                scale: Vec2::splat(0.75),
                color: rgb(0xffd24a),
                ..Draw::new(gem, (p + Vec2::new(0.0, bob)).extend(sort_z(layer::GEMS, c.pos.y)))
            });
            glow.add(
                f.glow,
                p.extend(layer::EMISSIVE),
                Vec2::splat(0.22),
                0.0,
                rgb(0xffd24a).with_alpha(0.6),
            );
        }
    }

    // ---- 夜主：结界、幻身；危险区统一交给 telegraphs.rs 描摹模拟几何
    if let Some(dir) = &res.director
        && let Some((c, r)) = dir.barrier
    {
        let p = to_screen(c);
        let k = px(f.ring, r * 2.0);
        let pulse = 0.45 + 0.15 * (now * 2.0).sin();
        glow.add(
            f.ring,
            p.extend(layer::EMISSIVE - 2.0),
            Vec2::new(k, k * FLAT),
            0.0,
            rgb(0xb07cf0).with_alpha(pulse),
        );
        let ki = px(f.ring_ink, r * 2.0);
        pools.fx.push(Draw {
            scale: Vec2::new(ki, ki * FLAT),
            color: rgb(0x2a1840).with_alpha(0.5),
            ..Draw::new(f.ring_ink, p.extend(layer::GROUND + 0.6))
        });
    }
    if let Some(bs) = &res.boss {
        let c = &content.0;
        let boss_kind = c.enemies.iter().position(|e| e.boss.is_some());
        if let Some(kind) = boss_kind {
            let ef = frames.enemy_frames(kind);
            if !ef.is_empty() {
                for (k, m) in bs.illusions.iter().enumerate() {
                    let p = lerp(m.prev, m.pos);
                    let frame = m
                        .volley
                        .as_ref()
                        .and_then(|v| frames.charge_frame(kind, v.t / v.warn))
                        .unwrap_or(ef[((now * 8.0) as usize + k * 3) % ef.len()]);
                    let flicker = 0.45 + 0.15 * (now * 6.0 + k as f32).sin();
                    pools.fx.push(Draw {
                        flip: m.pos.x > ppos.0.x,
                        color: Color::srgb(0.85, 0.75, 1.0).with_alpha(flicker),
                        ..Draw::new(frame, p.extend(sort_z(layer::ACTORS, m.pos.y)))
                    });
                }
            }
        }
        // 近景竹子避开扫击、狐火雨的落点（描边在 telegraphs.rs 画）
        for sw in &bs.sweeps {
            foreground.protect(to_screen(sw.origin), sw.radius);
        }
        for d in &bs.drops {
            foreground.protect(to_screen(d.pos), d.radius + 12.0);
        }
    }

    // ---- 冲锋的预警：蓄力时身上发亮、地上画出冲锋线（越接近出手越亮，锁定后最亮）
    if let Some(en) = &res.enemies {
        let c = &content.0;
        let red = rgb(0xff4a3a);
        for i in en.iter_alive() {
            if en.charge[i] != CHARGE_WINDUP {
                continue;
            }
            let Some(ch) = &c.enemies[en.kind[i] as usize].charge else { continue };
            let u = (1.0 - en.charge_t[i] / ch.windup).clamp(0.0, 1.0);
            let at = Vec2::new(en.x[i], en.y[i]);
            let dir = Vec2::new(en.charge_dx[i], en.charge_dy[i]);
            let len = ch.speed * ch.duration + en.r[i];
            let start = to_screen(at);
            let screen_dir = to_screen(at + dir * len) - start;
            foreground.protect(start + screen_dir * 0.5, len * 0.5 + en.r[i]);
            let rot = screen_dir.y.atan2(screen_dir.x);
            // 锁定以后线停下、变亮，给玩家躲的信号
            let locked = en.charge_t[i] <= ch.lock;
            let (line_a, glow_a) = if locked { (0.95, 0.75) } else { (0.2 + 0.35 * u, 0.12 + 0.25 * u) };
            if let Some((line, head)) = f.charge {
                // 车道锚点在起点、沿 X 拉伸，箭头接在末端不拉伸（DESIGN 第 15 节）；车道宽约为妖物直径的 0.8 倍
                let (lf, hf) = (db.frame(line), db.frame(head));
                let k = en.r[i] * 1.6 / lf.width.unwrap_or(lf.size.y);
                let head_len = hf.head_len.unwrap_or(hf.size.x) * k;
                let body = (screen_dir.length() - head_len).max(0.0);
                let tip = start + screen_dir.normalize_or_zero() * body;
                for (id, pos, scale) in
                    [(line, start, Vec2::new(body / lf.size.x, k)), (head, tip, Vec2::splat(k))]
                {
                    pools.fx.push(Draw {
                        scale,
                        rot,
                        color: red.with_alpha(line_a),
                        ..Draw::new(id, pos.extend(layer::DANGER))
                    });
                    glow.add(id, pos.extend(layer::DANGER + 0.01), scale, rot, red.with_alpha(glow_a));
                }
            } else {
                // 没有专用贴图时借剑光拖尾：锚点在右端，放在终点、朝冲锋方向
                let end = start + screen_dir;
                let w = db.frame(f.trail).size;
                let scale = Vec2::new(screen_dir.length() / w.x, en.r[i] * 1.2 / w.y);
                pools.fx.push(Draw {
                    scale,
                    rot,
                    color: red.with_alpha(line_a),
                    ..Draw::new(f.trail, end.extend(layer::DANGER))
                });
                glow.add(f.trail, end.extend(layer::DANGER + 0.01), scale, rot, red.with_alpha(glow_a));
            }
            let pulse = 0.6 + 0.4 * (now * 18.0).sin();
            glow.add(
                f.glow,
                lerp(Vec2::new(en.px[i], en.py[i]), at).extend(layer::EMISSIVE),
                Vec2::splat(en.r[i] / 30.0),
                0.0,
                red.with_alpha((0.3 + 0.5 * u) * pulse),
            );
        }
    }

    // ---- 精英词缀：头顶一排小图标。画在妖物这一层的最上面、夜色之下，暗处和妖物一起看不见；“隐”着的不画
    if let Some(en) = &res.enemies
        && f.affix.iter().any(Option::is_some)
    {
        const ICON: f32 = 0.7;
        const GAP: f32 = 12.0;
        for i in en.iter_alive() {
            let bits = en.affix[i];
            if bits == 0 || en.cloaked[i] {
                continue;
            }
            let p = lerp(Vec2::new(en.px[i], en.py[i]), Vec2::new(en.x[i], en.y[i]));
            let icons: Vec<FrameId> = f
                .affix
                .iter()
                .enumerate()
                .filter(|&(k, _)| bits & (1 << k) != 0)
                .filter_map(|(_, f)| *f)
                .collect();
            let x0 = -(icons.len() as f32 - 1.0) * GAP * 0.5;
            for (k, &icon) in icons.iter().enumerate() {
                let at = p + Vec2::new(x0 + k as f32 * GAP, en.r[i] * 2.0 + 14.0);
                pools.fx.push(Draw {
                    scale: Vec2::splat(ICON),
                    ..Draw::new(icon, at.extend(layer::ACTORS + 50.0))
                });
            }
        }
    }

    // ---- 地裂：地面上的墨痕；凤火、竹墙与剑林复用图集，以颜色和轮廓区分
    if let Some(fissures) = &res.fissures {
        for z in &fissures.0 {
            use lantern_content::GroundKind;
            let p = to_screen(z.pos);
            let k = px(f.crack, z.radius * 2.0);
            if z.kind == GroundKind::Fissure {
                let alpha = ((z.life / z.max_life) + 0.2).min(1.0) * 0.55;
                pools.fx.push(Draw {
                    scale: Vec2::new(k, k * 0.75),
                    color: Color::WHITE.with_alpha(alpha),
                    ..Draw::new(f.crack, p.extend(layer::GROUND + 0.9))
                });
                continue;
            }
            let alpha = ((z.life / z.max_life) + 0.2).min(1.0) * 0.65;
            let tint = match z.kind {
                GroundKind::Fire => rgb(0xff8138),
                GroundKind::Bamboo => rgb(0x80b879),
                _ => rgb(0xb4cbda),
            };
            pools.fx.push(Draw {
                scale: Vec2::new(k, k * FLAT),
                color: tint.with_alpha(alpha),
                ..Draw::new(f.crack, p.extend(layer::GROUND + 0.9))
            });
            match z.kind {
                GroundKind::Fire => {
                    glow.add(
                        f.glow,
                        p.extend(layer::EMISSIVE - 3.0),
                        Vec2::new(k, k * FLAT),
                        0.0,
                        tint.with_alpha(alpha * 0.5),
                    );
                    for i in 0..3 {
                        let offset =
                            Vec2::new((i as f32 - 1.0) * z.radius * 0.6, (now * 4.0 + i as f32).sin() * 3.0);
                        glow.add(
                            f.trail,
                            (p + offset).extend(layer::EMISSIVE - 1.0),
                            Vec2::new(0.4, 0.7),
                            std::f32::consts::FRAC_PI_2,
                            tint.with_alpha(alpha),
                        );
                    }
                }
                GroundKind::Bamboo | GroundKind::Sword => {
                    let frame = if z.kind == GroundKind::Bamboo {
                        db.find("bamboo_clump/idle_S_00").unwrap_or(f.sword_evo)
                    } else {
                        f.sword_evo
                    };
                    for i in 0..5 {
                        let x = (i as f32 - 2.0) * z.radius * 0.35;
                        let rise = if z.kind == GroundKind::Bamboo { 34.0 } else { 18.0 };
                        pools.fx.push(Draw {
                            scale: Vec2::new(0.65, 1.3),
                            rot: if z.kind == GroundKind::Bamboo {
                                0.0
                            } else {
                                -std::f32::consts::FRAC_PI_2
                            },
                            color: tint.with_alpha(alpha),
                            ..Draw::new(
                                frame,
                                (p + Vec2::new(x, rise)).extend(sort_z(layer::WEAPONS, z.pos.y)),
                            )
                        });
                    }
                }
                GroundKind::Fissure => {}
            }
        }
    }

    // ---- 一次性效果
    let fx = &mut *fx;
    let real_dt = if run.is_some_and(|s| *s.get() == RunState::Paused) { 0.0 } else { real.delta_secs() };
    fx.live.retain_mut(|l| l.advance(dt, real_dt));
    for l in &fx.live {
        let personal_start = (pools.fx.len(), glow.0.len());
        let u = l.t / l.life;
        match l.kind {
            OneShot::Residue(identity) => draw_residue(l, identity, &f, &parts.f, &db, &mut pools, &mut glow),
            OneShot::Ring { color, ink, light, strong } => {
                let rr = 12.0 + (l.r - 12.0) * (1.0 - (1.0 - u) * (1.0 - u));
                let k = px(f.ring, rr * 2.0);
                let alpha = (1.0 - u) * if strong { 1.0 } else { 0.85 };
                glow.add(
                    f.ring,
                    l.pos.extend(layer::EMISSIVE - 1.0),
                    Vec2::new(k, k * FLAT),
                    0.0,
                    color.with_alpha(alpha),
                );
                if ink {
                    let ki = px(f.ring_ink, rr * 1.9);
                    pools.fx.push(Draw {
                        scale: Vec2::new(ki, ki * FLAT),
                        rot: 0.0,
                        color: rgb(0x3e5a7e).with_alpha((1.0 - u) * 0.35),
                        ..Draw::new(f.ring_ink, l.pos.extend(layer::GROUND + 0.92))
                    });
                }
                if light {
                    glow.light(&frames, &db, l.pos, (color.with_alpha((1.0 - u) * 0.8), rr * 1.1));
                }
            }
            OneShot::Mark { evolved } => {
                // 山印落地：朱砂印痕，慢慢淡去；印痕是点睛的小印，不随范围无限放大
                let k = px(f.seal_mark, (l.r * 0.6).min(if evolved { 56.0 } else { 40.0 }));
                let fade = if u < 0.6 { 1.0 } else { 1.0 - (u - 0.6) / 0.4 };
                pools.fx.push(Draw {
                    scale: Vec2::new(k, k * FLAT),
                    rot: l.rot * 0.15 - 0.15,
                    color: Color::WHITE.with_alpha(fade * 0.7),
                    ..Draw::new(f.seal_mark, l.pos.extend(layer::GROUND + 0.93))
                });
            }
            OneShot::Pulse => {
                // 寒波：六道细长冰棱贴地外推，留出大片负空间。
                for i in 0..6 {
                    let angle = i as f32 * TAU / 6.0;
                    let d = Vec2::from_angle(angle);
                    let at = l.pos + d * Vec2::new(1.0, FLAT) * l.r * (0.18 + u * 0.78);
                    let k = px(f.streak, l.r * (0.5 - u * 0.25));
                    glow.add(
                        f.streak,
                        at.extend(layer::EMISSIVE),
                        Vec2::new(k, k * 0.22),
                        (d.y * FLAT).atan2(d.x),
                        rgb(0xa8d4ff).with_alpha((1.0 - u) * 0.75),
                    );
                }
            }
            OneShot::Toll => {
                // 钟鸣保留波纹身份：两道错拍的窄波前，没有整片填色。
                for delay in [0.0, 0.24] {
                    let wave = (u - delay) / (1.0 - delay);
                    if !(0.0..1.0).contains(&wave) {
                        continue;
                    }
                    let k = px(f.wave, l.r * 2.0 * (0.15 + 0.85 * wave));
                    glow.add(
                        f.wave,
                        l.pos.extend(layer::EMISSIVE - 1.0),
                        Vec2::new(k, k * FLAT),
                        0.0,
                        rgb(0xa8d4ff).with_alpha((1.0 - wave) * 0.55),
                    );
                }
            }
            OneShot::Quake => {
                // 震地 / 落印：裂纹从落点分叉，停在地上褪去。
                let reach = (u * 5.0).min(1.0);
                for i in 0..5 {
                    let angle = l.rot + i as f32 * TAU / 5.0;
                    let d = Vec2::from_angle(angle);
                    let k = px(f.crack, l.r * reach);
                    let at = l.pos + d * Vec2::new(1.0, FLAT) * l.r * reach * 0.38;
                    pools.fx.push(Draw {
                        scale: Vec2::new(k, k * 0.28),
                        rot: (d.y * FLAT).atan2(d.x),
                        color: rgb(0x4b342b).with_alpha((1.0 - u) * 0.85),
                        ..Draw::new(f.crack, at.extend(layer::GROUND + 0.96))
                    });
                }
            }
            OneShot::Ult => {
                // 灯焰收束：外圈墨边向内压，灯芯从宽柱收成细线；冲击无需等它播完。
                let contract = (l.t / ULT_CONTRACT).min(1.0);
                if contract < 1.0 {
                    let k = px(f.ring_ink, l.r * (1.15 - contract * 0.55));
                    pools.fx.push(Draw {
                        scale: Vec2::new(k, k * FLAT),
                        color: rgb(0x1b1720).with_alpha((1.0 - contract) * 0.45),
                        ..Draw::new(f.ring_ink, l.pos.extend(layer::WEAPONS))
                    });
                    let k = px(f.streak, l.r.min(240.0) * (0.85 - contract * 0.4));
                    glow.add(
                        f.streak,
                        (l.pos + Vec2::Y * l.r.min(240.0) * 0.22).extend(layer::EMISSIVE),
                        Vec2::new(k, k * (0.4 - contract * 0.32)),
                        TAU * 0.25,
                        rgb(0xfff1c2).with_alpha((1.0 - contract) * 0.8),
                    );
                }
                // 墨浪：首帧已有波前，20ms 后快速翻卷，320ms 内褪去。
                let wave = ((l.t - 0.02) / (ULT_WAVE - 0.02)).clamp(0.0, 1.0);
                let reach = 0.08 + 0.92 * (1.0 - (1.0 - wave).powi(3));
                let fade = 1.0 - ((l.t - ULT_CONTRACT) / (ULT_WAVE - ULT_CONTRACT)).clamp(0.0, 1.0);
                for i in 0..8 {
                    if fade <= 0.0 {
                        break;
                    }
                    let angle = i as f32 * TAU / 8.0 + wave * 0.3;
                    let d = Vec2::from_angle(angle);
                    let at = l.pos + d * Vec2::new(1.0, FLAT) * l.r * reach * 0.6;
                    let k = px(f.slash, l.r * (0.35 + reach * 0.45));
                    pools.fx.push(Draw {
                        scale: Vec2::new(k, k * 0.85),
                        rot: angle,
                        color: rgb(0x1b1720).with_alpha(fade * 0.8),
                        ..Draw::new(f.slash, at.extend(layer::WEAPONS + 1.0))
                    });
                    glow.add(
                        f.slash,
                        at.extend(layer::EMISSIVE + 1.0),
                        Vec2::new(k * 0.9, k * 0.42),
                        angle,
                        rgb(0xffd98a).with_alpha(fade * ult_flare(l.t) * 0.8),
                    );
                }
                // 局部光爆从第 0 帧取峰值；不因波前外扩而在后面补第二次爆闪。
                let flare = ult_flare(l.t);
                if flare > 0.0 {
                    glow.light(&frames, &db, l.pos, (rgb(0xffd98a).with_alpha(flare), l.r * 0.9));
                }
            }
            OneShot::Reaction { color } => {
                // 五行相遇用交错短笔锋，避免每次反应再铺一个大圈。
                let k = px(f.slash, l.r * (0.8 + u * 0.4));
                for angle in [l.rot, l.rot + TAU * 0.4] {
                    glow.add(
                        f.slash,
                        l.pos.extend(layer::EMISSIVE),
                        Vec2::new(k, k * 0.5),
                        angle,
                        color.with_alpha((1.0 - u) * 0.6),
                    );
                }
            }
            OneShot::Blast { color, .. } | OneShot::HostileBlast { color } => {
                if matches!(l.kind, OneShot::Blast { ice: true, .. }) {
                    // 冰爆是向外迸射的尖棱，火爆是向上卷的焰舌。
                    for i in 0..7 {
                        let angle = l.rot + i as f32 * TAU / 7.0;
                        let at = l.pos + Vec2::from_angle(angle) * l.r * u;
                        let k = px(f.streak, l.r * (0.9 - u * 0.5));
                        glow.add(
                            f.streak,
                            at.extend(layer::EMISSIVE),
                            Vec2::new(k, k * 0.3),
                            angle,
                            color.with_alpha((1.0 - u) * 0.8),
                        );
                    }
                } else {
                    for i in -1..=1 {
                        let at = l.pos + Vec2::new(i as f32 * l.r * 0.32, l.r * u * 0.65);
                        let k = px(f.slash, l.r * (0.8 + u * 0.4));
                        glow.add(
                            f.slash,
                            at.extend(layer::EMISSIVE),
                            Vec2::new(k, k * 0.7),
                            TAU * 0.25 + i as f32 * 0.3,
                            color.with_alpha((1.0 - u) * 0.65),
                        );
                    }
                }
            }
            OneShot::Taiji => {
                // 太极：在主角脚下转一圈后淡出
                let k = px(f.taiji, (u * 3.0).min(1.0) * l.r * 0.5);
                pools.fx.push(Draw {
                    scale: Vec2::new(k, k * 0.6),
                    rot: now * 2.5,
                    color: Color::WHITE.with_alpha((1.0 - u) * 0.85),
                    ..Draw::new(f.taiji, hero.extend(layer::GROUND + 0.95))
                });
                for angle in [u * TAU, u * TAU + TAU * 0.5] {
                    let d = Vec2::from_angle(angle);
                    let at = l.pos + d * Vec2::new(1.0, FLAT) * l.r * 0.55;
                    let k = px(f.slash, l.r * 0.75);
                    glow.add(
                        f.slash,
                        at.extend(layer::EMISSIVE),
                        Vec2::new(k, k * 0.6),
                        angle,
                        rgb(0xffd98a).with_alpha((1.0 - u) * 0.65),
                    );
                }
            }
        }
        let visibility = l.category().visibility(feedback.as_ref(), l.priority, res.readability.gain);
        dim_personal(&mut pools, &mut glow, personal_start, visibility);
    }

    let personal_start = (pools.fx.len(), glow.0.len());
    // ---- 石印：预警和下落
    if let Some(seals) = &res.seals {
        for s in &seals.0 {
            let pulse = 0.55 + 0.25 * (now * 18.0).sin();
            let show = if s.t > -0.05 { 1.0 } else { 0.4 };
            let p = to_screen(s.pos);
            let kr = px(f.wave, s.radius * 2.0 / 0.84);
            let earth = rgb(0xc9925a);
            glow.add(
                f.wave,
                p.extend(layer::EMISSIVE - 2.0),
                Vec2::new(kr, kr * FLAT),
                0.0,
                earth.with_alpha(pulse * show * 0.55),
            );
            glow.add(
                f.warn,
                p.extend(layer::EMISSIVE - 2.0),
                Vec2::new(0.8, 0.8 * FLAT),
                0.0,
                earth.with_alpha(pulse * show),
            );
            if s.t > 0.0 {
                let k = (s.t / s.delay).min(1.0);
                let bamboo = s.fissure.is_some_and(|f| f.kind == lantern_content::GroundKind::Bamboo);
                let drop = (1.0 - k) * (1.0 - k) * if bamboo { -70.0 } else { 150.0 };
                let kind = s.fissure.map(|v| v.kind);
                let frame = match kind {
                    Some(lantern_content::GroundKind::Sword) => f.sword_evo,
                    Some(lantern_content::GroundKind::Bamboo) => {
                        db.find("bamboo_clump/idle_S_00").unwrap_or(f.seal_evo)
                    }
                    _ => {
                        if s.evolved {
                            f.seal_evo
                        } else {
                            f.seal
                        }
                    }
                };
                let sk = (s.radius / if s.evolved { 70.0 } else { 45.0 }).max(1.0) * (0.8 + k * 0.2);
                pools.fx.push(Draw {
                    scale: Vec2::splat(sk),
                    color: Color::WHITE.with_alpha((k * 3.0).min(1.0)),
                    ..Draw::new(frame, Vec3::new(p.x, p.y + drop, sort_z(layer::WEAPONS, s.pos.y)))
                });
            }
        }
    }

    // ---- 飞剑
    if let Some(shots) = &res.shots {
        for s in &shots.0 {
            let p = lerp(s.prev, s.pos);
            // 屏幕 y 向上，角度取反
            let ang = -s.vel.y.atan2(s.vel.x);
            let trail = if s.effects.molten.is_some() {
                rgb(0xff603c)
            } else if s.effects.freeze > 0.0 {
                rgb(0x80dfff)
            } else if s.effects.execute > 0.0 {
                rgb(0xaabed4)
            } else if s.big {
                rgb(0xffd98a)
            } else if s.bonus {
                rgb(0xcfe3f5)
            } else {
                rgb(0xe9f1ff)
            };
            let (tk, tky) = if s.big { (1.4, 1.2) } else { (1.1, 0.9) };
            glow.add(f.trail, p.extend(layer::EMISSIVE), Vec2::new(tk, tky), ang, trail.with_alpha(0.75));
            let frame = if s.big { f.sword_evo } else { f.sword };
            // 赤霄、冰剑、铁羽的剑身跟拖尾同色，其余飞剑照旧
            let tinted = s.effects != lantern_sim::weapons::volley::ShotEffects::default();
            pools.fx.push(Draw {
                scale: Vec2::new(if s.big { 1.15 } else { 1.0 }, 1.0),
                rot: ang,
                color: if tinted { trail } else { Color::WHITE },
                ..Draw::new(frame, p.extend(sort_z(layer::WEAPONS, s.pos.y)))
            });
            glow.light(&frames, &db, p, (trail.with_alpha(0.5), if s.big { 40.0 } else { 28.0 }));
        }
    }

    // ---- 纸鹤
    if let Some(arsenal) = &res.arsenal {
        for slot in &arsenal.0 {
            let seq = if slot.transformed() { &f.crane_evo } else { &f.crane };
            if slot.cranes.is_empty() || seq.is_empty() {
                continue;
            }
            let phoenix = matches!(slot.behavior(&content.0), WeaponBehavior::Seeker { on_hit: Some(_), .. });
            let iron = matches!(slot.behavior(&content.0), WeaponBehavior::Seeker { count_cap: Some(_), .. });
            let tint = if phoenix {
                rgb(0xff9250)
            } else if iron {
                rgb(0x9baac7)
            } else {
                Color::WHITE
            };
            if phoenix && slot.count > 0 {
                let angle = slot.prev_angle + (slot.angle - slot.prev_angle) * a;
                let p = hero + to_screen(slot.orbit_offset(angle, 0));
                pools.fx.push(Draw {
                    scale: Vec2::splat(2.2),
                    color: tint,
                    rot: -angle,
                    ..Draw::new(seq[(now * 12.0) as usize % seq.len()], p.extend(layer::WEAPONS))
                });
                glow.light(&frames, &db, p, (tint.with_alpha(0.5), 65.0));
            }
            for (k, c) in slot.cranes.iter().enumerate() {
                let p = lerp(c.prev, c.pos) + Vec2::new(0.0, 6.0);
                let rest = match slot.behavior(&content.0) {
                    WeaponBehavior::Seeker { rest, .. } => *rest,
                    _ => 0.0,
                };
                let contact_age = rest - c.rest;
                let contacting = !c.striking && c.target.is_some() && (0.0..0.15).contains(&contact_age);
                let frame = if contacting && contact_age < 0.05 {
                    seq[0]
                } else {
                    seq[((now * 12.0 + k as f32 * 1.3) as usize) % seq.len()]
                };
                let contact = if contacting { (1.0 - contact_age / 0.15).max(0.0) } else { 0.0 };
                let ang = -c.angle + contact * 0.18;
                // 向左飞时上下翻转，保持鹤背朝上
                let flip_y = if c.angle.cos() < 0.0 { -1.0 } else { 1.0 };
                pools.fx.push(Draw {
                    scale: Vec2::new(
                        (if phoenix { 1.3 } else { 1.0 }) * (1.0 - contact * 0.18),
                        flip_y * (1.0 + contact * 0.12),
                    ),
                    color: tint,
                    rot: ang,
                    ..Draw::new(frame, p.extend(sort_z(layer::WEAPONS, c.pos.y)))
                });
                if slot.transformed() {
                    // 千鹤引照旧是金色微光；凤、铁鹤用自己的颜色
                    let lit = if phoenix || iron { tint } else { rgb(0xffd98a) };
                    glow.add(f.glow, p.extend(layer::EMISSIVE), Vec2::splat(0.3), 0.0, lit.with_alpha(0.35));
                }
            }
        }
    }

    // ---- 护盾
    if pl.shield > 0.0 {
        let k = px(f.shield, 11.0 * 3.2);
        let alpha = 0.35 + 0.15 * (now * 4.0).sin();
        glow.add(
            f.shield,
            (hero + Vec2::new(0.0, 14.0)).extend(layer::EMISSIVE),
            Vec2::splat(k),
            now * 0.6,
            rgb(0xc9925a).with_alpha(alpha),
        );
    }

    let visibility = Category::Decorative.visibility(&feedback, Priority::Normal, res.readability.gain);
    dim_personal(&mut pools, &mut glow, personal_start, visibility);

    // ---- 拾取物
    if let Some(pickups) = &res.pickups {
        for it in &pickups.0 {
            let bob = (now * 3.0 + it.pos.x * 0.1).sin() * 2.0;
            let p = to_screen(it.pos);
            let (frame, color, light) = match it.kind {
                PickupKind::Chest => (f.chest, rgb(0xffd98a), 60.0),
                PickupKind::BossChest => (f.chest, rgb(0xffe9a8), 90.0),
                PickupKind::Bell => (f.soulbell, rgb(0x5fd4c4), 36.0),
                PickupKind::Lotus => (f.lotus, rgb(0xffb0c0), 36.0),
            };
            pools
                .fx
                .push(Draw::new(frame, Vec3::new(p.x, p.y - bob + 2.0, sort_z(layer::WEAPONS, it.pos.y))));
            glow.add(
                f.glow,
                (p + Vec2::new(0.0, 8.0)).extend(layer::EMISSIVE),
                Vec2::splat(0.5),
                0.0,
                color.with_alpha(0.45),
            );
            glow.light(&frames, &db, p, (color.with_alpha(0.6), light));
        }
    }

    // ---- 夜主弹幕（狐火）
    if let Some(foes) = &res.foes {
        for fo in &foes.0 {
            let p = lerp(fo.prev, fo.pos);
            glow.add(
                f.glow,
                p.extend(layer::EMISSIVE),
                Vec2::splat(0.35),
                0.0,
                rgb(0xff6b5a).with_alpha(0.9),
            );
            glow.add(f.spark, p.extend(layer::EMISSIVE + 0.1), Vec2::splat(1.2), now * 3.0, rgb(0xffe0c0));
            glow.light(&frames, &db, p, (rgb(0xff6b5a).with_alpha(0.45), 30.0));
        }
    }

    // ---- 奇遇：灵泉、妖潮裂隙画在地上；古灯、血祭坛是道具
    if let Some(enc) = &res.encounters {
        let c = &content.0;
        for e in &enc.list {
            let def = &c.events.kinds[e.kind];
            let p = to_screen(e.pos);
            let fade = ((def.life - e.t) / 1.5).clamp(0.0, 1.0) * (e.t / 0.5).min(1.0);
            let color = hex(&def.color);
            match def.kind {
                EventKind::Spring { radius, .. } => {
                    if let Some(frame) = f.spring {
                        let k = px(frame, radius * 2.6);
                        pools.fx.push(Draw {
                            scale: Vec2::splat(k),
                            color: Color::WHITE.with_alpha(fade),
                            ..Draw::new(frame, p.extend(layer::GROUND + 0.8))
                        });
                    }
                    glow.light(&frames, &db, p, (color.with_alpha(0.7 * fade), radius * 2.2));
                }
                EventKind::Rift { .. } => {
                    if let Some(frame) = f.rift {
                        pools.fx.push(Draw {
                            color: Color::WHITE.with_alpha(fade),
                            ..Draw::new(frame, p.extend(layer::GROUND + 0.8))
                        });
                    }
                    if let Some(frame) = f.rift_glow {
                        let pulse = 0.6 + 0.3 * (now * 3.0).sin();
                        glow.add(
                            frame,
                            p.extend(layer::EMISSIVE - 3.0),
                            Vec2::ONE,
                            0.0,
                            color.with_alpha(pulse * fade),
                        );
                    }
                    glow.light(&frames, &db, p, (color.with_alpha(0.6 * fade), 120.0));
                }
                EventKind::Shrine { .. } | EventKind::Altar { .. } => {
                    let prop = if matches!(def.kind, EventKind::Shrine { .. }) { f.lamp } else { f.altar };
                    if let Some((frame, emit)) = prop {
                        pools.fx.push(Draw {
                            color: Color::WHITE.with_alpha(fade.max(0.2)),
                            ..Draw::new(frame, p.extend(sort_z(layer::ACTORS, e.pos.y)))
                        });
                        if let Some(emit) = emit {
                            glow.add(
                                emit,
                                p.extend(layer::EMISSIVE),
                                Vec2::ONE,
                                0.0,
                                Color::WHITE.with_alpha(fade),
                            );
                        }
                    }
                    // 一圈细环提示可以触碰
                    let pulse = 0.5 + 0.3 * (now * 4.0).sin();
                    let k = px(f.ring, 64.0);
                    glow.add(
                        f.ring,
                        p.extend(layer::EMISSIVE - 3.0),
                        Vec2::new(k, k * FLAT),
                        0.0,
                        color.with_alpha(pulse * fade),
                    );
                    glow.light(&frames, &db, p + Vec2::new(0.0, 24.0), (color.with_alpha(0.8 * fade), 110.0));
                }
                EventKind::Critter { .. } => {
                    // 金蟾是妖物，自己会画；这里只加一点金光
                    glow.light(&frames, &db, p, (color.with_alpha(0.7), 70.0));
                }
                EventKind::Merchant { radius, .. } => {
                    // 货郎担；图集里没有时用一只箱子顶着
                    match f.merchant {
                        Some((frame, emit)) => {
                            pools.fx.push(Draw {
                                color: Color::WHITE.with_alpha(fade.max(0.3)),
                                ..Draw::new(frame, p.extend(sort_z(layer::ACTORS, e.pos.y)))
                            });
                            if let Some(emit) = emit {
                                glow.add(
                                    emit,
                                    p.extend(layer::EMISSIVE),
                                    Vec2::ONE,
                                    0.0,
                                    Color::WHITE.with_alpha(fade),
                                );
                            }
                        }
                        None => pools.fx.push(Draw {
                            scale: Vec2::splat(1.2),
                            color: Color::WHITE.with_alpha(fade.max(0.3)),
                            ..Draw::new(f.chest, p.extend(sort_z(layer::ACTORS, e.pos.y)))
                        }),
                    }
                    let pulse = 0.5 + 0.3 * (now * 3.0).sin();
                    let k = px(f.ring, radius * 2.0);
                    glow.add(
                        f.ring,
                        p.extend(layer::EMISSIVE - 3.0),
                        Vec2::new(k, k * FLAT),
                        0.0,
                        color.with_alpha(pulse * fade),
                    );
                    glow.light(&frames, &db, p + Vec2::new(0.0, 20.0), (color.with_alpha(0.7 * fade), 100.0));
                }
            }
        }
    }
}

/// 用到的模拟资源（开局前都不存在）。
#[derive(bevy::ecs::system::SystemParam)]
pub(crate) struct FxSources<'w> {
    readability: Res<'w, crate::telegraphs::Readability>,
    shots: Option<Res<'w, Shots>>,
    seals: Option<Res<'w, Seals>>,
    fissures: Option<Res<'w, Fissures>>,
    pickups: Option<Res<'w, Pickups>>,
    foes: Option<Res<'w, Foes>>,
    arsenal: Option<Res<'w, Arsenal>>,
    encounters: Option<Res<'w, Encounters>>,
    reveal: Option<Res<'w, Reveal>>,
    zones: Option<Res<'w, Zones>>,
    trail: Option<Res<'w, Trail>>,
    herbs: Option<Res<'w, Herbs>>,
    stats: Option<Res<'w, Stats>>,
    lanterns: Option<Res<'w, Lanterns>>,
    story: Option<Res<'w, lantern_sim::story::Story>>,
    coins: Option<Res<'w, Coins>>,
    boss: Option<Res<'w, BossState>>,
    director: Option<Res<'w, Director>>,
    enemies: Option<Res<'w, lantern_sim::Enemies>>,
}

pub(crate) fn hex(s: &str) -> Color {
    let v = u32::from_str_radix(s.trim_start_matches('#'), 16).unwrap_or(0xffffff);
    rgb(v)
}

/// 闪屏：一张盖住整个画面的半透明色块，跟着镜头。
#[derive(Component)]
pub(crate) struct ScreenFlash;

pub(crate) fn spawn_flash(mut commands: Commands) {
    commands.spawn((
        ScreenFlash,
        Sprite { color: Color::NONE, custom_size: Some(Vec2::splat(20_000.0)), ..default() },
        Transform::from_xyz(0.0, 0.0, layer::NUMBERS + 50.0),
        DespawnOnExit(AppState::Run),
    ));
}

/// 闪屏淡出，跟着镜头。
pub(crate) fn apply_flash(
    time: Res<Time<Real>>,
    feedback: Res<Feedback>,
    mut fx: ResMut<FxState>,
    cam: Single<&Transform, With<MainCamera>>,
    mut flash: Query<(&mut Sprite, &mut Transform), (With<ScreenFlash>, Without<MainCamera>)>,
) {
    if !fx.flash_fresh {
        let a = (fx.flash.alpha() - time.delta_secs() * fx.flash_decay).max(0.0);
        fx.flash.set_alpha(a);
    }
    fx.flash_fresh = false;
    for (mut sprite, mut tf) in &mut flash {
        sprite.color = fx.flash.with_alpha(fx.flash.alpha() * feedback.visibility(fx.flash_priority));
        tf.translation.x = cam.translation.x;
        tf.translation.y = cam.translation.y;
    }
}

/// 压低当前一段玩家特效请求；只动本帧颜色，不改模拟状态或永久材质。
fn dim_personal(pools: &mut Pools, glow: &mut GlowRequests, start: (usize, usize), gain: f32) {
    for draw in &mut pools.fx[start.0..] {
        draw.color = draw.color.with_alpha(draw.color.alpha() * gain);
    }
    for draw in &mut glow.0[start.1..] {
        draw.color = draw.color.with_alpha(draw.color.alpha() * gain);
    }
}

/// 残留只用已有图集，每组最多六次绘制；在普通特效与地面层之间保持克制。
fn draw_residue(
    l: &Live,
    identity: WeaponIdentity,
    f: &FxFrames,
    p: &crate::particles::PFrames,
    db: &AtlasDb,
    pools: &mut Pools,
    glow: &mut GlowRequests,
) {
    use WeaponIdentity::*;
    let u = l.t / l.life;
    let fade = (1.0 - u).powi(2);
    let axis = Vec2::from_angle(l.rot);
    let ground = layer::GROUND + 0.96;
    let color = match identity {
        Lamp => rgb(0xff6528),
        Sword => rgb(0xf5e6b4),
        Bell => rgb(0xc6eeff),
        Crane => rgb(0x92dcb4),
        Seal => rgb(0xb79a6b),
    };
    if identity == Sword {
        let size = Vec2::new(l.r * 3.0 / db.frame(p.slash).size.x, 0.06);
        pools.fx.push(Draw {
            rot: l.rot,
            scale: size * 1.15,
            color: crate::particles::INK.with_alpha(fade * 0.65),
            ..Draw::new(p.slash, l.pos.extend(ground))
        });
        glow.add(
            p.streak,
            l.pos.extend(layer::EMISSIVE - 1.0),
            Vec2::new(l.r * 2.4 / db.frame(p.streak).size.x, 0.07),
            l.rot,
            color.with_alpha(fade * 0.5),
        );
        return;
    }
    if matches!(identity, Bell | Seal) {
        let ring = if identity == Seal { f.ring_ink } else { f.ring };
        let k = l.r * (1.4 + 0.5 * u) / db.frame(ring).size.x;
        pools.fx.push(Draw {
            scale: Vec2::new(k, k * FLAT),
            color: color.with_alpha(fade * 0.45),
            ..Draw::new(ring, l.pos.extend(ground))
        });
        if identity == Seal {
            pools.fx.push(Draw {
                scale: Vec2::new(k * 0.8, k * 0.3),
                color: crate::particles::INK.with_alpha(fade * 0.35),
                ..Draw::new(p.drop, l.pos.extend(ground - 0.01))
            });
        }
    }
    for i in 0..4 {
        let n = i as f32;
        let dir = Vec2::from_angle(l.rot + n * 2.4);
        let off = dir * l.r * (0.18 + n * 0.13) + axis * (u * 2.0);
        let drift = match identity {
            Lamp => Vec2::Y * u * (5.0 + n),
            Crane => dir.perp() * (u * 8.0) + Vec2::Y * ((u * 7.0 + n).sin() * 2.0),
            _ => Vec2::ZERO,
        };
        let pos = l.pos + Vec2::new(off.x, off.y * FLAT) + drift;
        let frame = if identity == Lamp && i % 2 == 0 { p.ember } else { p.ash };
        let scale = match identity {
            Bell => Vec2::new(0.12, 0.35),
            Crane => Vec2::new(0.40, 0.21) * (0.8 + 0.2 * (u * 14.0 + n).cos().abs()),
            _ => Vec2::splat(0.22 + n * 0.035),
        };
        let rot = l.rot + n + if identity == Crane { u * 2.0 } else { 0.0 };
        if identity == Lamp && i % 2 == 0 {
            glow.add(frame, pos.extend(layer::EMISSIVE - 1.0), scale, rot, color.with_alpha(fade * 0.6));
        } else {
            pools.fx.push(Draw {
                scale,
                rot,
                color: if identity == Lamp {
                    crate::particles::INK.with_alpha(fade * 0.6)
                } else {
                    color.with_alpha(fade * 0.7)
                },
                ..Draw::new(frame, pos.extend(ground + 0.01))
            });
        }
    }
}

#[cfg(test)]
mod identity_tests {
    use super::*;

    #[test]
    fn residues_yield_to_moves_and_cannot_evict_them() {
        let mut fx = FxState::default();
        for _ in 0..MAX_LIVE - LIVE_RESERVE {
            fx.push(OneShot::Residue(WeaponIdentity::Lamp), Vec2::ZERO, 10.0, 1.0);
        }
        // 普通招式能挤掉残留
        for _ in 0..MAX_LIVE {
            fx.push(OneShot::Taiji, Vec2::ZERO, 10.0, 1.0);
        }
        assert_eq!(fx.live.len(), MAX_LIVE - LIVE_RESERVE);
        assert!(fx.live.iter().all(|l| !matches!(l.kind, OneShot::Residue(_))));
        // 残留挤不掉任何东西
        fx.push(OneShot::Residue(WeaponIdentity::Seal), Vec2::ZERO, 10.0, 1.0);
        assert!(fx.live.iter().all(|l| !matches!(l.kind, OneShot::Residue(_))));
        for identity in WeaponIdentity::ALL {
            assert!((0.4..=1.2).contains(&residue_life(identity)));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ult_keeps_impact_pose_then_advances_on_real_time_through_hitstop() {
        for frame_dt in [1.0 / 60.0, 1.0 / 30.0, 0.2, 1.0] {
            let mut fx = FxState::default();
            fx.push(OneShot::Ult, Vec2::ZERO, 400.0, ULT_END);
            let live = &mut fx.live[0];
            assert!(live.advance(frame_dt, frame_dt));
            assert_eq!(live.t, 0.0);
            assert_eq!(ult_flare(live.t), 0.8);
            assert!(live.advance(0.0, ULT_CONTRACT));
            assert_eq!(live.t, ULT_CONTRACT);
            assert!(ult_flare(live.t) < 0.8);
            assert!(live.advance(0.0, 0.32));
            assert!(ult_flare(live.t) < 1e-6);
            assert!(!live.advance(0.0, 0.5));
        }
    }

    #[test]
    fn crowded_frame_keeps_all_five_rain_impacts_and_sweep_in_both_modes() {
        let content = lantern_content::Content::load(
            &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"),
        )
        .unwrap();
        for lite in [false, true] {
            let mut app = App::new();
            app.insert_resource(GameContent(content.clone().into()))
                .insert_resource(crate::Feel { lite, ..default() })
                .init_resource::<Time>()
                .init_resource::<Time<Real>>()
                .init_resource::<Feedback>()
                .init_resource::<SimOutbox>()
                .init_resource::<FxState>()
                .add_systems(Update, (crate::feedback::prepare_feedback, read_fx_events).chain());
            {
                let mut fx = app.world_mut().resource_mut::<FxState>();
                fx.priority = Priority::Finale;
                for _ in 0..MAX_LIVE {
                    fx.push(OneShot::Ult, Vec2::ZERO, 400.0, 1.0);
                }
            }
            {
                let mut events = app.world_mut().resource_mut::<SimOutbox>();
                events.0.push(SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult });
                for x in 0..5 {
                    events.0.push(SimEvent::RainStrike { pos: Vec2::new(x as f32, 0.0) });
                }
                events.0.push(SimEvent::SweepStrike { pos: Vec2::ZERO, dir: 0.0 });
            }
            app.update();
            let feedback = app.world().resource::<Feedback>();
            let fx = app.world().resource::<FxState>();
            let hostile: Vec<_> = fx.live.iter().filter(|l| l.category() == Category::Hostile).collect();
            assert_eq!(fx.live.len(), MAX_LIVE);
            assert_eq!(hostile.len(), 6);
            for x in 0..5 {
                assert!(hostile.iter().any(|l| l.pos == Vec2::new(x as f32, 0.0) && l.r == 44.0));
            }
            assert!(hostile.iter().any(|l| l.pos == Vec2::new(110.0, 0.0) && l.r == 120.0));
            for l in hostile {
                assert!(matches!(l.kind, OneShot::HostileBlast { .. }));
                assert_eq!(l.category().visibility(feedback, l.priority, 0.32), 1.0);
            }
            let mut fx = app.world_mut().resource_mut::<FxState>();
            fx.priority = Priority::Finale;
            for _ in 0..MAX_LIVE {
                fx.push(OneShot::Ult, Vec2::ZERO, 400.0, 1.0);
            }
            assert_eq!(fx.live.iter().filter(|l| l.category() == Category::Hostile).count(), 6);
        }
    }

    #[test]
    fn full_transient_pool_reserves_and_then_evicts_for_ultimate() {
        let mut fx = FxState::default();
        for _ in 0..200 {
            fx.push(OneShot::Pulse, Vec2::ZERO, 100.0, 0.5);
        }
        assert_eq!(fx.live.len(), MAX_LIVE - LIVE_RESERVE);
        fx.priority = Priority::Critical;
        for _ in 0..LIVE_RESERVE {
            fx.push(OneShot::Toll, Vec2::ZERO, 100.0, 0.5);
        }
        fx.priority = Priority::Ultimate;
        fx.push(OneShot::Ult, Vec2::ZERO, 400.0, 1.0);
        assert_eq!(fx.live.len(), MAX_LIVE);
        assert!(fx.live.iter().any(|l| matches!(l.kind, OneShot::Ult)));
        fx.priority = Priority::Normal;
        fx.push(OneShot::Pulse, Vec2::ZERO, 100.0, 0.5);
        assert!(fx.live.iter().any(|l| matches!(l.kind, OneShot::Ult)));
    }

    #[test]
    fn weaker_flash_cannot_recolor_a_climax() {
        let mut fx = FxState { priority: Priority::Finale, ..default() };
        let gold = rgb(0xfff1c2);
        fx.flash(gold, 0.6);
        fx.priority = Priority::Normal;
        fx.flash(Color::BLACK, 1.0);
        assert_eq!(fx.flash, gold.with_alpha(0.3));
        fx.flash.set_alpha(0.0);
        fx.flash(Color::BLACK, 1.0);
        assert_eq!(fx.flash.alpha(), 0.06);
    }

    #[test]
    fn protected_flash_overrides_attacks_and_only_death_can_replace_hurt() {
        let red = rgb(0xff3b30);
        for priority in [Priority::Hurt, Priority::Death] {
            let mut fx = FxState { priority: Priority::Finale, ..default() };
            fx.flash(Color::WHITE, 0.6);
            fx.priority = priority;
            fx.flash(red, 0.18);
            assert_eq!(fx.flash, red.with_alpha(0.18));
            for attack in Priority::ALL.into_iter().filter(|p| !p.protected()) {
                fx.priority = attack;
                fx.flash(Color::WHITE, 1.0);
                assert_eq!(fx.flash, red.with_alpha(0.18));
            }
            fx.priority = Priority::Hurt;
            fx.flash(Color::BLACK, 0.18);
            if priority == Priority::Death {
                assert_eq!(fx.flash, red.with_alpha(0.18));
            }
            fx.priority = Priority::Death;
            fx.flash(Color::WHITE, 0.18);
            assert_eq!(fx.flash, Color::WHITE.with_alpha(0.18));
        }
    }
}
