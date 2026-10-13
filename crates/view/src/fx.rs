//! 法器与法术的画面（参照网页版 render/weaponViews.ts）：飞剑、纸鹤、石印与预警、地裂、
//! 寒波与各种环、连锁爆炸、太极、护盾、拾取物、夜主弹幕、奇遇的道具，以及闪屏。
//!
//! 持续存在的东西直接读模拟的资源；一次性的效果（环、印痕、爆炸）收到模拟事件后在这里记下，自己计时淡出。
//! 纯装饰的随机数用画面层自己的，不影响模拟。

use std::f32::consts::TAU;

use bevy::prelude::*;

use lantern_content::{BlastKind, Element, EventKind, Stat, WeaponBehavior, ZoneKind};
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
    AppState, Arsenal, Director, GameContent, Player, Pos, PrevPos, SimEvent, SimOutbox, Stats,
};

use crate::actors::{ActorFrames, Draw, GlowRequests, Pools, sort_z};
use crate::atlas::{AtlasDb, FrameId};
use crate::{MainCamera, layer, to_screen};

/// 透视：地面上的圆画成扁圆
const FLAT: f32 = 0.62;

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
    ring_ink: FrameId,
    crack: FrameId,
    blast: FrameId,
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
    gem: Option<FrameId>,
    /// 地上的铜钱（普通）和它的微光（叠加）
    coin: Option<(FrameId, Option<FrameId>)>,
    /// 九尾扫的扇形预警：轮廓、蓄力填充
    sector: Option<(FrameId, FrameId)>,
    /// 反应留下的区域：赤地（底图 + 叠加光）、淤泥、灵草（底图 + 叠加光）
    zone_lava: Option<(FrameId, Option<FrameId>)>,
    zone_mud: Option<FrameId>,
    zone_herb: Option<(FrameId, Option<FrameId>)>,
    /// 精英词缀的小图标（按 `affixes.ron` 的顺序）
    affix: Vec<Option<FrameId>>,
}

/// 区域、扇形贴图在缩放 1 时的有效半径（世界单位）；图集 meta 里有 radius_px 时以它为准，这里是没有时的后备值。
const ZONE_LAVA_R: f32 = 43.0;
const ZONE_MUD_R: f32 = 45.5;
const ZONE_HERB_R: f32 = 39.5;
const SECTOR_R: f32 = 32.0;

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
        ring_ink: need("weapons/ring_ink"),
        crack: need("weapons/crack"),
        blast: need("weapons/blast"),
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
        gem: db.find("vfx/gem_0"),
        coin: db.find("vfx/coin").map(|f| (f, db.find("vfx/coin_emit"))),
        sector: db.find("weapons/sector").zip(db.find("weapons/sector_fill")),
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
    Blast { color: Color },
    Taiji,
}

struct Live {
    kind: OneShot,
    pos: Vec2,
    r: f32,
    t: f32,
    life: f32,
    rot: f32,
}

/// 一次性效果、闪屏。震屏在 `camera.rs`。
#[derive(Resource)]
pub(crate) struct FxState {
    rng: Pcg32,
    live: Vec<Live>,
    time: f32,
    pub flash: Color,
}

impl Default for FxState {
    fn default() -> Self {
        FxState { rng: Pcg32::new(0xf00d_2026, 3), live: Vec::new(), time: 0.0, flash: Color::NONE }
    }
}

const MAX_LIVE: usize = 160;

impl FxState {
    fn push(&mut self, kind: OneShot, pos: Vec2, r: f32, life: f32) {
        if self.live.len() >= MAX_LIVE {
            self.live.remove(0);
        }
        let rot = self.rng.range_f32(0.0, TAU);
        self.live.push(Live { kind, pos, r, t: 0.0, life, rot });
    }

    fn flash(&mut self, color: Color, a: f32) {
        if a >= self.flash.alpha() {
            self.flash = color.with_alpha(a);
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
pub(crate) fn read_fx_events(content: Res<GameContent>, outbox: Res<SimOutbox>, mut fx: ResMut<FxState>) {
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Reaction { kind, pos, first, .. } => {
                let r = &content.0.elements.reactions[kind as usize];
                let color = element_rgb(r.b);
                fx.push(
                    OneShot::Ring { color, ink: false, light: first, strong: first },
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
                    StrikeFx::Pulse => fx.push(
                        OneShot::Ring { color: rgb(0x6fb8ff), ink: true, light: false, strong: false },
                        p,
                        radius,
                        0.45,
                    ),
                    StrikeFx::Toll => {
                        fx.push(
                            OneShot::Ring { color: rgb(0xa8d4ff), ink: true, light: true, strong: true },
                            p,
                            radius,
                            0.7,
                        );
                        fx.flash(rgb(0x6fb8ff), 0.18);
                    }
                    StrikeFx::Seal { evolved } => {
                        fx.push(OneShot::Mark { evolved }, p, radius, if evolved { 2.4 } else { 1.8 });
                        fx.push(
                            OneShot::Ring { color: rgb(0xc9925a), ink: false, light: false, strong: false },
                            p,
                            radius * 1.2,
                            0.35,
                        );
                    }
                    StrikeFx::Blast(kind) => {
                        let color = if kind == BlastKind::Ice { rgb(0x6fb8ff) } else { rgb(0xff8a3d) };
                        fx.push(OneShot::Blast { color }, p, radius, 0.3);
                    }
                    StrikeFx::Quake => {
                        fx.push(
                            OneShot::Ring { color: rgb(0xc9925a), ink: false, light: false, strong: false },
                            p,
                            radius,
                            0.5,
                        );
                    }
                    StrikeFx::Taiji => fx.push(OneShot::Taiji, p, radius, 1.0),
                    StrikeFx::Ult => {
                        fx.push(
                            OneShot::Ring { color: rgb(0xffd98a), ink: false, light: true, strong: true },
                            p,
                            radius * 1.1,
                            1.0,
                        );
                        fx.flash(rgb(0xffd98a), 0.55);
                    }
                    StrikeFx::None => {}
                }
            }
            SimEvent::SweepStrike { pos, dir } => {
                let tip = pos + Vec2::new(dir.cos(), dir.sin()) * 110.0;
                fx.push(OneShot::Blast { color: rgb(0xff4a3a) }, to_screen(tip), 120.0, 0.35);
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
                fx.push(OneShot::Blast { color: rgb(0xff6b5a) }, to_screen(pos), 44.0, 0.3);
            }
            SimEvent::IllusionDispelled { pos } => fx.push(
                OneShot::Ring { color: rgb(0xd8c8ff), ink: false, light: true, strong: false },
                to_screen(pos),
                60.0,
                0.5,
            ),
            SimEvent::LanternLit { .. } => fx.flash(rgb(0xffd98a), 0.25),
            SimEvent::EncircleWarn { .. } => fx.flash(rgb(0x1a1020), 0.35),
            SimEvent::PlayerHurt { .. } => {
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
    time: Res<Time>,
    fixed: Res<Time<Fixed>>,
    content: Res<GameContent>,
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    f: Res<FxFrames>,
    res: FxSources,
    player: Single<(&Pos, &PrevPos, &Player)>,
    mut fx: ResMut<FxState>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
) {
    let dt = time.delta_secs();
    fx.time += dt;
    let now = fx.time;
    let a = fixed.overstep_fraction();
    let (ppos, pprev, pl) = *player;
    let hero = to_screen(pprev.0.lerp(ppos.0, a));
    let lerp = |prev: Vec2, cur: Vec2| to_screen(prev.lerp(cur, a));
    let px = |frame: FrameId, world: f32| world / db.frame(frame).size.x;

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
            let kr = px(f.ring, reveal.radius * 2.0);
            let flicker = 0.45 + 0.15 * (now * 9.0).sin() + 0.08 * (now * 23.0).sin();
            glow.add(
                f.ring,
                hero.extend(layer::EMISSIVE - 2.5),
                Vec2::new(kr, kr * FLAT),
                now * 0.3,
                rgb(0xff9a4a).with_alpha(flicker),
            );
        }
    }

    // ---- 不夜城的内环火海
    if let (Some(arsenal), Some(stats)) = (&res.arsenal, &res.stats) {
        let c = &content.0;
        for slot in &arsenal.0 {
            if let WeaponBehavior::Orbit { inner: Some(fire), .. } = slot.behavior(c) {
                let r = fire.radius * stats.get(Stat::Area);
                let kr = px(f.ring, r * 2.0);
                let flicker = 0.55 + 0.2 * (now * 11.0).sin();
                glow.add(
                    f.ring,
                    hero.extend(layer::EMISSIVE - 1.5),
                    Vec2::new(kr, kr * FLAT),
                    -now * 1.5,
                    rgb(0xff7a2a).with_alpha(flicker),
                );
                glow.light(&frames, &db, hero, (rgb(0xff8a3d).with_alpha(0.35), r * 1.6));
            }
        }
    }

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

    // ---- 石灯笼：没点亮的暗着，站在旁边时一圈进度；点亮后成为光区
    if let (Some(lanterns), Some((frame, emit))) = (&res.lanterns, f.stone) {
        let def = &content.0.run.lanterns;
        for l in &lanterns.0 {
            let p = to_screen(l.pos);
            pools.fx.push(Draw {
                scale: Vec2::splat(1.25),
                color: if l.lit { Color::WHITE } else { Color::srgb(0.55, 0.55, 0.6) },
                ..Draw::new(frame, p.extend(sort_z(layer::ACTORS, l.pos.y)))
            });
            if l.lit {
                if let Some(emit) = emit {
                    glow.add(emit, p.extend(layer::EMISSIVE), Vec2::splat(1.25), 0.0, Color::WHITE);
                }
                glow.light(
                    &frames,
                    &db,
                    p + Vec2::new(0.0, 30.0),
                    (rgb(0xffc56b).with_alpha(0.9), def.zone_radius),
                );
                let k = px(f.ring_ink, def.zone_radius * 2.0);
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

    // ---- 夜主：结界、幻身、九尾扫与狐火雨的预警
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
                    let frame = ef[((now * 8.0) as usize + k * 3) % ef.len()];
                    let flicker = 0.45 + 0.15 * (now * 6.0 + k as f32).sin();
                    pools.fx.push(Draw {
                        flip: m.pos.x > ppos.0.x,
                        color: Color::srgb(0.85, 0.75, 1.0).with_alpha(flicker),
                        ..Draw::new(frame, p.extend(sort_z(layer::ACTORS, m.pos.y)))
                    });
                }
            }
        }
        let red = rgb(0xff4a3a);
        for sw in bs.sweeps.iter().filter(|_| f.sector.is_some()) {
            // 扇形预警：轮廓按扇形朝向旋转、地面压扁；填充层从顶点往外放大，填满时落下
            let Some((outline, fill)) = f.sector else { break };
            let u = (sw.t / sw.warn).clamp(0.0, 1.0);
            let o = to_screen(sw.origin);
            let d = Vec2::new(sw.dir.cos(), sw.dir.sin());
            let radial = to_screen(sw.origin + d * sw.radius) - o;
            let radial = Vec2::new(radial.x, radial.y * FLAT);
            let side = to_screen(sw.origin + d.perp() * sw.radius) - o;
            let side = Vec2::new(side.x, side.y * FLAT);
            let rot = radial.y.atan2(radial.x);
            let across = (radial.normalize_or_zero().perp_dot(side)).abs();
            // 贴图的扇形张角是 120°；九尾扫的张角写在数据里，横向按比例缩放
            let open = (sw.angle * 0.5).tan() / (std::f32::consts::FRAC_PI_3).tan();
            let scale =
                Vec2::new(radial.length(), across * open) / db.frame(outline).radius.unwrap_or(SECTOR_R);
            pools.fx.push(Draw {
                scale,
                rot,
                color: red.with_alpha(0.35 + 0.3 * u),
                ..Draw::new(outline, o.extend(layer::GROUND + 0.95))
            });
            pools.fx.push(Draw {
                scale: scale * u,
                rot,
                color: red.with_alpha(0.25 + 0.25 * u),
                ..Draw::new(fill, o.extend(layer::GROUND + 0.96))
            });
            glow.add(outline, o.extend(layer::EMISSIVE - 2.0), scale, rot, red.with_alpha(0.15 + 0.35 * u));
        }
        for sw in bs.sweeps.iter().filter(|_| f.sector.is_none()) {
            // 没有扇形贴图时：沿扇形铺几排光点，越接近落下越亮
            let u = (sw.t / sw.warn).clamp(0.0, 1.0);
            for ring in 1..=4 {
                let rr = sw.radius * ring as f32 / 4.0;
                let steps = 3 + ring * 2;
                for j in 0..=steps {
                    let a = sw.dir - sw.angle * 0.5 + sw.angle * j as f32 / steps as f32;
                    let w = sw.origin + Vec2::new(a.cos(), a.sin()) * rr;
                    glow.add(
                        f.glow,
                        to_screen(w).extend(layer::EMISSIVE - 2.0),
                        Vec2::splat(0.35),
                        0.0,
                        red.with_alpha(0.25 + 0.5 * u),
                    );
                }
            }
        }
        for d in &bs.drops {
            let u = (d.t / d.warn).clamp(0.0, 1.0);
            let k = px(f.ring, d.radius * 2.0);
            glow.add(
                f.ring,
                to_screen(d.pos).extend(layer::EMISSIVE - 2.0),
                Vec2::new(k, k * FLAT) * (1.2 - 0.2 * u),
                0.0,
                red.with_alpha(0.3 + 0.6 * u),
            );
        }
    }

    // ---- 冲锋的预警：蓄力时身上发亮、地上画出冲锋线（越接近出手越亮）
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
            // 线从妖物脚下画到冲锋的终点（贴图的锚点在右端，放在终点、朝冲锋方向）
            let len = ch.speed * ch.duration + en.r[i];
            let end = to_screen(at + dir * len);
            let screen_dir = end - to_screen(at);
            let rot = screen_dir.y.atan2(screen_dir.x);
            let w = db.frame(f.trail).size;
            let scale = Vec2::new(screen_dir.length() / w.x, en.r[i] * 1.2 / w.y);
            pools.fx.push(Draw {
                scale,
                rot,
                color: red.with_alpha(0.25 + 0.45 * u),
                ..Draw::new(f.trail, end.extend(layer::GROUND + 0.97))
            });
            glow.add(f.trail, end.extend(layer::EMISSIVE - 2.0), scale, rot, red.with_alpha(0.15 + 0.35 * u));
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

    // ---- 地裂：地面上的墨痕
    if let Some(fissures) = &res.fissures {
        for z in &fissures.0 {
            let k = px(f.crack, z.radius * 2.0);
            let alpha = ((z.life / z.max_life) + 0.2).min(1.0) * 0.55;
            pools.fx.push(Draw {
                scale: Vec2::new(k, k * 0.75),
                color: Color::WHITE.with_alpha(alpha),
                ..Draw::new(f.crack, to_screen(z.pos).extend(layer::GROUND + 0.9))
            });
        }
    }

    // ---- 一次性效果
    let fx = &mut *fx;
    fx.live.retain_mut(|l| {
        l.t += dt;
        l.t < l.life
    });
    for l in &fx.live {
        let u = l.t / l.life;
        match l.kind {
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
            OneShot::Blast { color } => {
                let k = px(f.blast, l.r * 2.0 * (0.5 + u * 0.7));
                glow.add(
                    f.blast,
                    l.pos.extend(layer::EMISSIVE),
                    Vec2::splat(k),
                    0.0,
                    color.with_alpha(1.0 - u),
                );
                glow.light(&frames, &db, l.pos, (color.with_alpha((1.0 - u) * 0.8), l.r * 1.6));
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
                let kr = px(f.ring, l.r * 2.0 * u);
                glow.add(
                    f.ring,
                    hero.extend(layer::EMISSIVE),
                    Vec2::new(kr, kr * 0.6),
                    0.0,
                    rgb(0xffd98a).with_alpha(1.0 - u),
                );
            }
        }
    }

    // ---- 石印：预警和下落
    if let Some(seals) = &res.seals {
        for s in &seals.0 {
            let pulse = 0.55 + 0.25 * (now * 18.0).sin();
            let show = if s.t > -0.05 { 1.0 } else { 0.4 };
            let p = to_screen(s.pos);
            let kr = px(f.ring, s.radius * 2.0);
            let earth = rgb(0xc9925a);
            glow.add(
                f.ring,
                p.extend(layer::EMISSIVE - 2.0),
                Vec2::new(kr, kr * FLAT),
                0.0,
                earth.with_alpha(pulse * show * 0.8),
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
                let drop = (1.0 - k) * (1.0 - k) * 150.0;
                let frame = if s.evolved { f.seal_evo } else { f.seal };
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
            let trail = if s.big {
                rgb(0xffd98a)
            } else if s.bonus {
                rgb(0xcfe3f5)
            } else {
                rgb(0xe9f1ff)
            };
            let (tk, tky) = if s.big { (1.4, 1.2) } else { (1.1, 0.9) };
            glow.add(f.trail, p.extend(layer::EMISSIVE), Vec2::new(tk, tky), ang, trail.with_alpha(0.75));
            let frame = if s.big { f.sword_evo } else { f.sword };
            pools.fx.push(Draw {
                scale: Vec2::new(if s.big { 1.15 } else { 1.0 }, 1.0),
                rot: ang,
                ..Draw::new(frame, p.extend(sort_z(layer::WEAPONS, s.pos.y)))
            });
            glow.light(&frames, &db, p, (trail.with_alpha(0.5), if s.big { 40.0 } else { 28.0 }));
        }
    }

    // ---- 纸鹤
    if let Some(arsenal) = &res.arsenal {
        for slot in &arsenal.0 {
            let seq = if slot.evolved { &f.crane_evo } else { &f.crane };
            if slot.cranes.is_empty() || seq.is_empty() {
                continue;
            }
            for (k, c) in slot.cranes.iter().enumerate() {
                let p = lerp(c.prev, c.pos) + Vec2::new(0.0, 6.0);
                let frame = seq[((now * 12.0 + k as f32 * 1.3) as usize) % seq.len()];
                let ang = -c.angle;
                // 向左飞时上下翻转，保持鹤背朝上
                let flip_y = if c.angle.cos() < 0.0 { -1.0 } else { 1.0 };
                pools.fx.push(Draw {
                    scale: Vec2::new(1.0, flip_y),
                    rot: ang,
                    ..Draw::new(frame, p.extend(sort_z(layer::WEAPONS, c.pos.y)))
                });
                if slot.evolved {
                    glow.add(
                        f.glow,
                        p.extend(layer::EMISSIVE),
                        Vec2::splat(0.3),
                        0.0,
                        rgb(0xffd98a).with_alpha(0.35),
                    );
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
                    // 货郎还没有专门的美术：先用一只金边的箱子和一圈金环
                    pools.fx.push(Draw {
                        scale: Vec2::splat(1.2),
                        color: Color::WHITE.with_alpha(fade.max(0.3)),
                        ..Draw::new(f.chest, p.extend(sort_z(layer::ACTORS, e.pos.y)))
                    });
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
    mut fx: ResMut<FxState>,
    cam: Single<&Transform, With<MainCamera>>,
    mut flash: Query<(&mut Sprite, &mut Transform), (With<ScreenFlash>, Without<MainCamera>)>,
) {
    let a = (fx.flash.alpha() - time.delta_secs() * 3.0).max(0.0);
    fx.flash.set_alpha(a);
    for (mut sprite, mut tf) in &mut flash {
        sprite.color = fx.flash;
        tf.translation.x = cam.translation.x;
        tf.translation.y = cam.translation.y;
    }
}
