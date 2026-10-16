//! 角色层：主角、妖物、灯火、魂火、影子，以及它们的光源和自发光（docs/DESIGN.md 第 9 节）。
//!
//! 妖物和魂火在模拟的池子里，这里用固定的精灵池，每帧只画视野内的，不随妖物生死创建、销毁实体。
//! 前后关系按脚底 y 排序（z 越大越靠前）。光源和自发光帧先攒成 [`Glow`] 请求，由 [`apply_glow`]
//! 统一写进 Mesh2d 池（光源在光照相机的图层，自发光在暗层之上）。

use std::collections::BTreeMap;
use std::f32::consts::{FRAC_PI_4, TAU};

use bevy::camera::visibility::RenderLayers;
use bevy::prelude::*;
use bevy::sprite::Anchor;

use lantern_content::Stat;
use lantern_sim::bamboo::{Bamboo, ClumpState};
use lantern_sim::boss::BossState;
use lantern_sim::enemies::{
    CHARGE_DASH, CHARGE_RECOVER, CHARGE_WINDUP, EnemyHandle, SPAWN_GRACE, TAG_REVEALED,
};
use lantern_sim::{
    AppState, Arsenal, Enemies, GameContent, Gems, Player, Pos, PrevPos, RunState, SimEvent, SimOutbox, Stats,
};

use crate::atlas::{AnimMeta, AtlasDb, FrameId};
use crate::hero_feedback::HeroFeedback;
use crate::lighting::{AddMaterial, FrameMeshes, LIGHT_LAYER, SceneLights, SurfaceDraws, contact_shadow};
use crate::{MainCamera, layer, to_screen};

/// 8 个方向，顺序与图集一致：E SE S SW W NW N NE（y 向下，角度顺时针增加）。
const DIRS: [&str; 8] = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"];

/// 光源颜色与半径（docs/PORTING-NOTES.md 第 7 节）
pub(crate) const LANTERN_LIGHT: (Color, f32) = (crate::palette::LANTERN_LIGHT, 200.0);
/// 光池（平顶）比尖顶的光照得开，按同样的照明半径画会盖掉大半个画面，收到八成。
const POOL_RADIUS: f32 = 0.8;

/// 两种颜色按比例混合（t = 0 时是 a）。
fn mix(a: Color, b: Color, t: f32) -> Color {
    let (a, b) = (a.to_srgba(), b.to_srgba());
    Color::srgb(
        a.red + (b.red - a.red) * t,
        a.green + (b.green - a.green) * t,
        a.blue + (b.blue - a.blue) * t,
    )
}
const FLAME_LIGHT: (Color, f32) = (Color::srgba(1.0, 0.66, 0.376, 0.75), 64.0);
/// 冰火两重天的冰焰和它的光
const ICE_FLAME: Color = Color::srgb(0.35, 0.8, 1.0);
const ICE_FLAME_LIGHT: Color = Color::srgba(0.3, 0.7, 1.0, 0.75);
const GEM_LIGHT: Color = Color::srgba(0.75, 0.94, 1.0, 0.5);
const GEM_COLOR: Color = Color::srgb(0.75, 0.94, 1.0);
const FROZEN_TINT: Color = Color::srgb(0.62, 0.82, 1.0);
/// 五行印记的颜色，按 金、木、水、火、土
const MARK_TINT: [Color; 5] = [
    Color::srgb(1.0, 0.92, 0.6),
    Color::srgb(0.55, 1.0, 0.7),
    Color::srgb(0.55, 0.78, 1.0),
    Color::srgb(1.0, 0.6, 0.35),
    Color::srgb(0.9, 0.7, 0.45),
];
const BURN_TINT: Color = Color::srgb(1.0, 0.55, 0.35);
/// 同时画光的魂火上限
const GEM_LIGHT_CAP: usize = 200;

/// 按脚底 y 排序的 z：越靠下（越近）越大。
pub fn sort_z(base: f32, sim_y: f32) -> f32 {
    base + sim_y * 1e-4
}

// ---------------------------------------------------------------------------
// 帧缓存：每帧要查几千次，开局前按名字查好
// ---------------------------------------------------------------------------

struct HeroAnim {
    name: &'static str,
    /// [方向][帧]
    frames: Vec<Vec<FrameId>>,
    emit: Vec<Vec<FrameId>>,
    fps: f32,
    stride: Option<f32>,
}

#[derive(Resource)]
pub(crate) struct HeroFrames {
    idle: HeroAnim,
    walk: HeroAnim,
    dash: HeroAnim,
    hurt: HeroAnim,
    death: HeroAnim,
    shadow_scale: f32,
    /// 灯笼叠层（按 `lamps.ron` 的下标）：和主角同画布、同锚点的逐帧叠画（docs/DESIGN.md 第 15 节）
    lanterns: Vec<LanternLayer>,
}

/// 一盏灯的叠层：按动作名存 [方向][帧] 和自发光，加上光色。
struct LanternLayer {
    anims: Vec<(&'static str, Vec<Vec<FrameId>>, Vec<Vec<FrameId>>)>,
    light: Color,
}

impl LanternLayer {
    fn load(db: &AtlasDb, lamp: &str, color: &str) -> Self {
        let seq = |anim: &str, suffix: &str| -> Vec<Vec<FrameId>> {
            DIRS.iter()
                .map(|d| {
                    db.anim(&format!("lantern_{lamp}/{anim}_{d}{suffix}"))
                        .map(<[FrameId]>::to_vec)
                        .unwrap_or_default()
                })
                .collect()
        };
        let anims = ["idle", "walk", "dash", "hurt", "death"]
            .into_iter()
            .map(|a| (a, seq(a, ""), seq(a, "_emit")))
            .collect();
        LanternLayer { anims, light: crate::fx::hex(color) }
    }

    fn frame(&self, anim: &str, dir: usize, k: usize) -> (Option<FrameId>, Option<FrameId>) {
        let Some((_, frames, emit)) = self.anims.iter().find(|(a, ..)| *a == anim) else {
            return (None, None);
        };
        (frames[dir].get(k).copied(), emit[dir].get(k).copied())
    }
}

/// 妖物的一个动作：普通帧，闪白帧和自发光帧（和普通帧等长，否则为空）。
struct EnemyAnim {
    normal: Vec<FrameId>,
    flash: Vec<FrameId>,
    emit: Vec<FrameId>,
    fps: f32,
    /// 前几帧是蓄力
    windup: usize,
    /// 播完后从这一帧起循环（loop_from）
    loop_from: Option<usize>,
}

impl EnemyAnim {
    fn load(db: &AtlasDb, asset: &str, name: &str, meta: &AnimMeta) -> Self {
        let seq = |suffix: &str| {
            db.anim(&format!("{asset}/{name}_E{suffix}")).map(<[FrameId]>::to_vec).unwrap_or_default()
        };
        let normal = seq("");
        let same_len = |v: Vec<FrameId>| if v.len() == normal.len() { v } else { Vec::new() };
        EnemyAnim {
            flash: same_len(seq("_flash")),
            emit: same_len(seq("_emit")),
            normal,
            fps: meta.fps,
            windup: meta.windup_frames,
            loop_from: meta.loop_from,
        }
    }

    /// 蓄力了 t 秒：播蓄力帧，停在最后一个蓄力帧等预警结束。
    fn windup_frame(&self, t: f32) -> usize {
        windup_frame(self.windup, self.fps, t)
    }

    /// 出手以后 t 秒（going：这一招还没结束）。
    fn strike_frame(&self, t: f32, going: bool) -> Option<usize> {
        strike_frame(self.normal.len(), self.windup, self.loop_from, self.fps, t, going)
    }
}

fn windup_frame(windup: usize, fps: f32, t: f32) -> usize {
    ((t.max(0.0) * fps) as usize).min(windup.saturating_sub(1))
}

/// 本体与幻身共用聚火段，后两帧只用于出手和恢复。
fn summon_windup_frame(progress: f32) -> usize {
    usize::from(progress >= 0.5)
}

/// 出手以后 t 秒的帧号：从蓄力帧之后接着播。播完时，有 loop_from 的从那一帧起循环；
/// 没有的，这一招还没结束就停在最后一帧，结束了回到平时的动作（None）。
fn strike_frame(
    n: usize,
    windup: usize,
    loop_from: Option<usize>,
    fps: f32,
    t: f32,
    going: bool,
) -> Option<usize> {
    let k = windup + (t.max(0.0) * fps) as usize;
    if k < n {
        return Some(k);
    }
    if !going || n == 0 {
        return None;
    }
    Some(match loop_from {
        Some(from) if from < n => from + (k - n) % (n - from),
        _ => n - 1,
    })
}

struct EnemyFrames {
    /// 平时的动作
    base: EnemyAnim,
    /// 冲锋（赤面狐 pounce、青面鬼 charge）
    charge: Option<EnemyAnim>,
    /// 九尾扫、召唤（召唤和狐火雨时播）
    sweep: Option<EnemyAnim>,
    summon: Option<EnemyAnim>,
    /// 竹魅射刺：瞄准时停在蓄力帧，射出后播完
    shoot: Option<EnemyAnim>,
    /// 讨封狐：现形那一下，和现形以后走路（没现形时播平时的 disguise）
    reveal: Option<EnemyAnim>,
    unmasked: Option<EnemyAnim>,
    floating: bool,
    shadow_scale: f32,
}

#[derive(Resource)]
pub(crate) struct ActorFrames {
    /// 按 `enemies.ron` 的下标
    enemies: Vec<EnemyFrames>,
    flames: Vec<FrameId>,
    gems: [FrameId; 3],
    pub(crate) shadow: FrameId,
    pub(crate) light: FrameId,
    /// 主角灯笼的光池（平顶），见 `GlowRequests::pool_light`
    light_pool: Option<FrameId>,
    /// 光环（升级时扩开）
    pub(crate) ring: FrameId,
    /// 竹丛：立着的、打碎的、影子缩放
    bamboo: Option<(FrameId, FrameId, f32)>,
}

impl ActorFrames {
    /// 某种妖物的动画帧（幻身等借用妖物的样子时用）。
    pub(crate) fn enemy_frames(&self, kind: usize) -> &[FrameId] {
        self.enemies.get(kind).map_or(&[], |f| f.base.normal.as_slice())
    }

    /// 幻身也保持尾尖聚火动作，进度与本体一样只读模拟蓄力。
    pub(crate) fn charge_frame(&self, kind: usize, progress: f32) -> Option<FrameId> {
        let a = self.enemies.get(kind)?.summon.as_ref()?;
        let k = summon_windup_frame(progress);
        a.normal.get(k).copied()
    }

    /// 妖物死时化墨用的剪影：白色剪影帧，没有时用普通帧。
    pub(crate) fn enemy_ghost(&self, kind: usize) -> Option<FrameId> {
        let f = self.enemies.get(kind)?;
        f.base.flash.first().or(f.base.normal.first()).copied()
    }

    /// 让 light 贴图（径向渐变）画出半径 r 的光所需的缩放。
    pub(crate) fn light_scale(&self, db: &AtlasDb, r: f32) -> f32 {
        r * 2.0 / db.frame(self.light).size.x
    }
}

fn hero_anim(db: &AtlasDb, name: &'static str) -> HeroAnim {
    let meta = db.assets.get("hero").and_then(|a| a.anims.get(name));
    let seq = |suffix: &str| -> Vec<Vec<FrameId>> {
        DIRS.iter()
            .map(|d| {
                db.anim(&format!("hero/{name}_{d}{suffix}")).map(<[FrameId]>::to_vec).unwrap_or_default()
            })
            .collect()
    };
    HeroAnim {
        name,
        frames: seq(""),
        emit: seq("_emit"),
        fps: meta.map_or(8.0, |m| m.fps),
        stride: meta.and_then(|m| m.stride_units),
    }
}

/// 影子贴图按素材的影子半径缩放
fn shadow_scale(db: &AtlasDb, asset: &str, shadow: FrameId) -> f32 {
    let r_px = db.assets.get(asset).map_or(24.0, |a| a.shadow_radius_px.max(8.0));
    let w = db.frame(shadow).size.x * db.px_per_unit;
    (r_px * 2.0) / w
}

pub(crate) fn build_frames(mut commands: Commands, db: Res<AtlasDb>, content: Res<GameContent>) {
    let need = |name: &str| db.find(name).unwrap_or_else(|| panic!("图集里缺少帧 {name}"));
    let shadow = need("vfx/shadow");
    commands.insert_resource(HeroFrames {
        idle: hero_anim(&db, "idle"),
        walk: hero_anim(&db, "walk"),
        dash: hero_anim(&db, "dash"),
        hurt: hero_anim(&db, "hurt"),
        death: hero_anim(&db, "death"),
        shadow_scale: shadow_scale(&db, "hero", shadow),
        lanterns: content.0.lamps.iter().map(|l| LanternLayer::load(&db, &l.id, &l.color)).collect(),
    });
    let fallback = "shade";
    let enemies = content
        .0
        .enemies
        .iter()
        .map(|e| {
            // 缺图时借用影妖（美术管线还没交付的素材）
            let asset = if db.assets.contains_key(&e.sprite) { e.sprite.as_str() } else { fallback };
            let meta = &db.assets[asset];
            let (anim, am) = meta.default_anim().expect("素材至少有一个动作");
            // 出手动作按名字找（DESIGN 第 15 节“妖物动作”）；没画的照旧播平时的动作
            let named = |names: &[&str]| {
                names.iter().find_map(|&n| {
                    let a = meta.anims.get(n)?;
                    Some(EnemyAnim::load(&db, asset, n, a)).filter(|a| !a.normal.is_empty())
                })
            };
            EnemyFrames {
                base: EnemyAnim::load(&db, asset, anim, am),
                charge: e.charge.as_ref().and_then(|_| named(&["pounce", "charge"])),
                sweep: e.boss.as_ref().and_then(|_| named(&["sweep"])),
                summon: e.boss.as_ref().and_then(|_| named(&["summon"])),
                shoot: e.shot.as_ref().and_then(|_| named(&["shoot"])),
                reveal: e.disguise.as_ref().and_then(|_| named(&["reveal"])),
                unmasked: e.disguise.as_ref().and_then(|_| named(&["move"])),
                floating: meta.floating,
                shadow_scale: shadow_scale(&db, asset, shadow),
            }
        })
        .collect();
    commands.insert_resource(ActorFrames {
        enemies,
        flames: (0..4).map(|i| need(&format!("vfx/flame_{i}"))).collect(),
        gems: [need("vfx/gem_0"), need("vfx/gem_1"), need("vfx/gem_2")],
        shadow,
        light: need("vfx/light"),
        light_pool: db.find("vfx/light_pool"),
        ring: need("weapons/ring"),
        bamboo: db
            .find("bamboo_clump/idle_S_00")
            .zip(db.find("bamboo_clump_broken/idle_S_00"))
            .map(|(a, b)| (a, b, shadow_scale(&db, "bamboo_clump", shadow))),
    });
}

// ---------------------------------------------------------------------------
// 发光请求：光源（画进光照图）和自发光帧（画在暗层之上），都是叠加混合
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
pub(crate) struct Glow {
    pub frame: FrameId,
    /// 颜色乘以贴图；alpha 是强度
    pub color: Color,
    pub pos: Vec3,
    pub scale: Vec2,
    pub rot: f32,
    pub flip: bool,
    /// true：光源；false：自发光
    pub light: bool,
}

/// 渐隐的效果每帧颜色都不同；强度量化到 1/32，叠加材质的种类有上限，也更容易合批。
fn quantize(c: Color) -> Color {
    let a = (c.alpha() * 32.0).round() / 32.0;
    c.with_alpha(a)
}

#[derive(Resource, Default)]
pub(crate) struct GlowRequests(pub Vec<Glow>);

impl GlowRequests {
    pub fn light(&mut self, frames: &ActorFrames, db: &AtlasDb, at: Vec2, (color, radius): (Color, f32)) {
        self.light_frame(frames.light, db, at, (color, radius));
    }

    /// 主角灯笼那盏大光：平顶的光池（美术的 `vfx/light_pool`，半径四成以内一样亮，再往外半个余弦收掉），
    /// 灯下一圈都看得清，没有旧光那几道色带。平顶照得开，半径收到八成，灯外还留得住月夜；
    /// 没有这帧时照旧用尖顶的 `vfx/light`。别的光源都用尖顶的，小光画成平顶会像圆饼。
    pub fn pool_light(
        &mut self,
        frames: &ActorFrames,
        db: &AtlasDb,
        at: Vec2,
        (color, radius): (Color, f32),
    ) {
        match frames.light_pool {
            Some(pool) => self.light_frame(pool, db, at, (color, radius * POOL_RADIUS)),
            None => self.light_frame(frames.light, db, at, (color, radius)),
        }
    }

    fn light_frame(&mut self, frame: FrameId, db: &AtlasDb, at: Vec2, (color, radius): (Color, f32)) {
        if color.alpha() <= 0.01 {
            return;
        }
        self.0.push(Glow {
            frame,
            color: quantize(color),
            pos: at.extend(0.0),
            scale: Vec2::splat(radius * 2.0 / db.frame(frame).size.x),
            rot: 0.0,
            flip: false,
            light: true,
        });
    }

    pub fn emit(&mut self, frame: FrameId, pos: Vec2, flip: bool, color: Color) {
        if color.alpha() <= 0.01 {
            return;
        }
        self.0.push(Glow {
            frame,
            color: quantize(color),
            pos: pos.extend(layer::EMISSIVE),
            scale: Vec2::ONE,
            rot: 0.0,
            flip,
            light: false,
        });
    }

    /// 自发光（叠加），可以缩放、旋转；z 决定前后。
    pub fn add(&mut self, frame: FrameId, pos: Vec3, scale: Vec2, rot: f32, color: Color) {
        self.add_flipped(frame, pos, scale, rot, color, false);
    }

    /// 同 [`Self::add`]，可以左右镜像。
    pub fn add_flipped(
        &mut self,
        frame: FrameId,
        pos: Vec3,
        scale: Vec2,
        rot: f32,
        color: Color,
        flip: bool,
    ) {
        if color.alpha() <= 0.01 {
            return;
        }
        self.0.push(Glow { frame, color: quantize(color), pos, scale, rot, flip, light: false });
    }
}

// ---------------------------------------------------------------------------
// 主角
// ---------------------------------------------------------------------------

/// 主角的画面状态。
#[derive(Component, Default)]
pub(crate) struct HeroView {
    pub(crate) feedback: HeroFeedback,
    dir: usize,
    /// 待机、闪避、倒地动画的计时
    clock: f32,
    /// 走路动画按移动距离推进
    stride: f32,
    last_pos: Vec2,
    dying: bool,
    /// 本帧画的动作、帧号（灯笼挂点、自发光用）
    anim: &'static str,
    frame: usize,
    emit: Option<FrameId>,
    /// 本帧画的图集帧（闪避残影用）
    pub(crate) frame_id: Option<FrameId>,
    /// 本帧灯笼叠层的帧（闪避残影要连灯笼一起画）
    pub(crate) lantern_id: Option<FrameId>,
    /// 这一局的灯的光色（没有灯笼叠层时用默认的暖光）
    light: Option<Color>,
}

impl HeroView {
    /// 受光、影子和光照图共用同一个逐帧挂点。
    pub(crate) fn lamp(&self, db: &AtlasDb) -> (Vec2, Color) {
        let socket = db
            .assets
            .get("hero")
            .and_then(|a| a.sockets.get("lantern"))
            .and_then(|s| s.get(self.anim))
            .and_then(|s| s.get(DIRS[self.dir]))
            .and_then(|s| s.get(self.frame))
            .map_or(Vec2::new(8.0, 14.0), |&[x, y]| Vec2::new(x, -y) / db.px_per_unit);
        // 换上的灯笼的灯色只混进两成半：灯光底色已经偏橙，混多了整片灯下发橙（试玩第 1 轮，原来 0.45）
        (socket, self.light.map_or(LANTERN_LIGHT.0, |c| mix(LANTERN_LIGHT.0, c, 0.25)))
    }
}

/// 叠在主角身上的灯笼（逐帧跟着主角的动作和朝向）。
#[derive(Component)]
pub(crate) struct HeroLantern;

#[derive(Component)]
pub(crate) struct HeroShadow;

/// 模拟里出现主角时，挂上精灵和影子。
pub(crate) fn dress_player(
    add: On<Add<Player>>,
    mut commands: Commands,
    db: Res<AtlasDb>,
    hero: Res<HeroFrames>,
    frames: Res<ActorFrames>,
) {
    let first = hero.idle.frames[2].first().copied().unwrap_or(frames.shadow);
    let (sprite, anchor) = db.sprite(first);
    let (mut shadow, shadow_anchor) = db.sprite(frames.shadow);
    shadow.custom_size = Some(db.frame(frames.shadow).size * hero.shadow_scale);
    shadow.color = Color::srgba(1.0, 1.0, 1.0, 0.8);
    commands.entity(add.event().entity).insert((
        sprite,
        anchor,
        HeroView { dir: 2, anim: "idle", ..default() },
        Transform::from_xyz(0.0, 0.0, layer::ACTORS),
        Visibility::default(),
    ));
    commands.spawn((
        HeroShadow,
        shadow,
        shadow_anchor,
        Transform::from_xyz(0.0, 0.0, layer::SHADOW),
        DespawnOnExit(AppState::Run),
    ));
    let (lantern, lantern_anchor) = db.sprite(first);
    commands.spawn((
        HeroLantern,
        lantern,
        lantern_anchor,
        Transform::from_xyz(0.0, 0.0, layer::ACTORS),
        Visibility::Hidden,
        DespawnOnExit(AppState::Run),
    ));
}

/// 朝向带滞后：偏离当前扇区中心超过 22.5° + 0.12 弧度才切换，避免在两个方向之间来回抖。
fn pick_dir(current: usize, facing: Vec2) -> usize {
    if facing.length_squared() < 1e-6 {
        return current;
    }
    let a = facing.y.atan2(facing.x);
    let center = current as f32 * FRAC_PI_4;
    let mut diff = (a - center).rem_euclid(TAU);
    if diff > std::f32::consts::PI {
        diff -= TAU;
    }
    if diff.abs() <= FRAC_PI_4 / 2.0 + 0.12 {
        return current;
    }
    ((a / FRAC_PI_4).round() as i32).rem_euclid(8) as usize
}

#[allow(clippy::type_complexity)]
pub(crate) fn animate_hero(
    time: Res<Time>,
    real: Res<Time<Real>>,
    outbox: Res<SimOutbox>,
    hero: Res<HeroFrames>,
    db: Res<AtlasDb>,
    content: Res<GameContent>,
    setup: Option<Res<lantern_sim::RunSetup>>,
    run: Option<Res<State<RunState>>>,
    mut q: Query<(&Player, &Transform, &mut HeroView, &mut Sprite, &mut Anchor)>,
    mut shadow: Query<&mut Transform, (With<HeroShadow>, Without<Player>)>,
    mut lantern: Query<
        (&mut Transform, &mut Sprite, &mut Anchor, &mut Visibility),
        (With<HeroLantern>, Without<Player>, Without<HeroShadow>),
    >,
) {
    // 这一局的灯；无灯不画，也不退回红纸灯（docs/DESIGN.md 第 15 节）
    let layer = setup.and_then(|s| hero.lanterns.get(s.lamp_index(&content.0)));
    let over = run.as_ref().is_some_and(|s| *s.get() == RunState::Over);
    let paused = run.as_ref().is_some_and(|s| !matches!(s.get(), RunState::Playing | RunState::Over));
    let dt = time.delta_secs();
    for (player, tf, mut view, mut sprite, mut anchor) in &mut q {
        let pos = tf.translation.truncate();
        let moved = pos.distance(view.last_pos);
        view.last_pos = pos;
        view.dir = pick_dir(view.dir, player.facing);
        if over && !view.dying {
            view.dying = true;
            view.clock = 0.0;
        }
        let dying = view.dying || outbox.0.iter().any(|e| matches!(e, SimEvent::PlayerDied));
        view.feedback.update(
            &outbox.0,
            if paused { std::time::Duration::ZERO } else { real.delta() },
            player.iframe,
            dying,
        );
        let alpha = if dying { 1.0 } else { view.feedback.alpha(player.iframe) };
        sprite.color.set_alpha(alpha);
        view.clock += dt;
        let (anim, frame) = if view.dying {
            let n = hero.death.frames[view.dir].len().max(1);
            (&hero.death, ((view.clock * hero.death.fps) as usize).min(n - 1))
        } else if let Some(frame) = view.feedback.hurt_frame(hero.hurt.fps) {
            (&hero.hurt, frame)
        } else if player.dash_t > 0.0 {
            (&hero.dash, (view.clock * hero.dash.fps) as usize)
        } else if player.moved > 0.01 {
            let stride = hero.walk.stride.unwrap_or(80.0);
            view.stride = (view.stride + moved) % stride;
            let n = hero.walk.frames[view.dir].len().max(1);
            (&hero.walk, (view.stride / stride * n as f32) as usize)
        } else {
            view.stride = 0.0;
            (&hero.idle, (view.clock * hero.idle.fps) as usize)
        };
        let seq = &anim.frames[view.dir];
        let k = frame % seq.len().max(1);
        view.anim = anim.name;
        view.frame = k;
        view.emit = anim.emit[view.dir].get(k).copied();
        view.frame_id = seq.get(k).copied();
        if let Some(&id) = seq.get(k) {
            db.set(id, &mut sprite, &mut anchor);
        }
        for mut s in &mut shadow {
            s.translation = Vec3::new(pos.x, pos.y, layer::SHADOW);
        }
        // 灯笼叠层：同一动作、同一朝向、同一帧号，画在主角上面一点
        let (lantern_frame, lantern_emit) = layer.map_or((None, None), |l| l.frame(anim.name, view.dir, k));
        view.light = layer.filter(|_| lantern_frame.is_some()).map(|l| l.light);
        view.lantern_id = lantern_frame;
        if lantern_frame.is_some() {
            view.emit = lantern_emit;
        }
        for (mut t, mut s, mut a, mut vis) in &mut lantern {
            match lantern_frame {
                Some(id) => {
                    db.set(id, &mut s, &mut a);
                    s.color.set_alpha(alpha);
                    t.translation = tf.translation + Vec3::new(0.0, 0.0, 1e-5);
                    vis.set_if_neq(Visibility::Inherited);
                }
                None => {
                    vis.set_if_neq(Visibility::Hidden);
                }
            }
        }
    }
}

/// 灯焰一跳：拾到魂火时灯笼的光猛地一涨再落回（docs/GAMEPLAY.md 第 14 节）。
#[derive(Resource, Default)]
pub(crate) struct LanternFlare {
    flare: f32,
    /// 开局后过了多久（现实秒）：灯笼从一点火光亮起来，光圈慢慢铺开
    intro: f32,
}

/// 主角的灯笼光（在灯笼挂点上）和自发光帧（灯笼窗）。灯光半径 = 200 × √范围 × 灯光倍率。
/// 灯焰带一点不规则的摇曳，拾魂火时一跳。
pub(crate) fn hero_glow(
    time: Res<Time>,
    real: Res<Time<Real>>,
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    stats: Option<Res<Stats>>,
    outbox: Res<lantern_sim::SimOutbox>,
    q: Query<(&Transform, &HeroView, &Sprite, Option<&lantern_sim::Health>)>,
    mut flare: ResMut<LanternFlare>,
    mut glow: ResMut<GlowRequests>,
    readability: Res<crate::telegraphs::Readability>,
    mut surfaces: ResMut<SurfaceDraws>,
) {
    let picked = outbox.0.iter().filter(|e| matches!(e, lantern_sim::SimEvent::GemPicked { .. })).count();
    flare.flare = (flare.flare + picked as f32 * 0.12).min(1.0);
    flare.flare *= (-time.delta_secs() * 5.0).exp();
    flare.intro += real.delta_secs().min(0.1);
    // 开局点灯：1.4 秒里光圈从一点铺到全亮，起头那一下火光最亮
    let ignite = {
        let k = (flare.intro / 1.4).clamp(0.0, 1.0);
        0.12 + 0.88 * (1.0 - (1.0 - k).powi(3))
    };
    let spark = (1.0 - flare.intro / 0.8).clamp(0.0, 1.0);
    let t = time.elapsed_secs();
    // 生命低于三成时灯焰摇曳：光圈忽大忽小（docs/GAMEPLAY.md 第 4.4、14 节）
    let low = q
        .iter()
        .next()
        .and_then(|(_, _, _, h)| h)
        .map_or(0.0, |h| ((0.3 - h.hp / h.max.max(1.0)) / 0.2).clamp(0.0, 1.0));
    let gutter = low * (0.08 * (t * 11.0).sin() + 0.06 * (t * 23.7).sin() - 0.1).min(0.0);
    let flicker = 1.0 + 0.025 * (t * 7.3).sin() + 0.015 * (t * 17.9).sin() + 0.12 * flare.flare + gutter;
    let (_, base) = LANTERN_LIGHT;
    let radius =
        stats.map_or(base, |s| base * s.get(Stat::Area).sqrt() * s.get(Stat::Light)) * flicker * ignite;
    for (tf, view, sprite, _) in &q {
        // 灯的光色淡淡地染进暖光里，纸面不至于整片变色
        let (socket, color) = view.lamp(&db);
        let pos = tf.translation.truncate();
        if let Some(frame) = view.frame_id {
            surfaces.0.push(Draw::new(frame, tf.translation));
        }
        glow.pool_light(&frames, &db, pos + socket, (color, radius));
        if let Some(emit) = view.emit {
            glow.emit(emit, pos, false, Color::WHITE.with_alpha(sprite.color.alpha()));
        }
        // 灯笼周围一团暖光晕，拾魂火时更亮
        glow.add(
            frames.light,
            (pos + socket).extend(layer::EMISSIVE + 0.2),
            Vec2::splat(frames.light_scale(&db, 14.0 + 10.0 * flare.flare + 22.0 * spark)),
            0.0,
            Color::srgb(1.0, 0.78, 0.45)
                .with_alpha((0.22 + 0.5 * flare.flare + 0.7 * spark).min(1.0) * readability.gain),
        );
    }
}

// ---------------------------------------------------------------------------
// 精灵池：妖物、妖物影子、灯火
// ---------------------------------------------------------------------------

#[derive(Component, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Pooled {
    Enemy,
    EnemyShadow,
    /// 其他普通混合的精灵：灯火、法器、拾取物、地面印痕……（层次由 z 决定）
    Fx,
}

/// 每类精灵本帧要显示的内容，攒好后一次写进池子。
pub(crate) struct Draw {
    pub deform: Mat2,
    pub frame: FrameId,
    pub pos: Vec3,
    pub flip: bool,
    /// 相对图集帧原始大小的缩放
    pub scale: Vec2,
    pub rot: f32,
    pub color: Color,
}

impl Draw {
    pub fn new(frame: FrameId, pos: Vec3) -> Self {
        Draw {
            deform: Mat2::IDENTITY,
            frame,
            pos,
            flip: false,
            scale: Vec2::ONE,
            rot: 0.0,
            color: Color::WHITE,
        }
    }
}

impl Pools {
    /// 本帧要画的精灵数（妖物、影子、其他）。
    pub(crate) fn sprite_count(&self) -> usize {
        self.enemy.len() + self.enemy_shadow.len() + self.fx.len()
    }
}

#[derive(Resource, Default)]
pub(crate) struct Pools {
    enemy: Vec<Draw>,
    enemy_shadow: Vec<Draw>,
    pub fx: Vec<Draw>,
    /// 每类已经生成的精灵数
    spawned: [usize; 3],
    /// 本帧画出来的妖物（画面坐标，天明化烟用）
    pub visible_enemies: Vec<Vec2>,
    /// 天明时妖物淡去的程度（0：照常）
    pub dissolve: f32,
}

/// 决定哪些妖物看得见的模拟资源（开局前不存在）。
#[derive(bevy::ecs::system::SystemParam)]
pub(crate) struct Sight<'w> {
    stats: Option<Res<'w, lantern_sim::Stats>>,
    reveal: Option<Res<'w, lantern_sim::reveal::Reveal>>,
}

/// 九尾最近一次扫击落下、召唤（或狐火雨）的时刻（画面时间）。
#[derive(Default)]
pub(crate) struct BossClock {
    /// （时刻，扫击方向）
    strike: Option<(f32, f32)>,
    summon: Option<f32>,
}

impl BossClock {
    fn update(&mut self, events: &[SimEvent], now: f32) {
        for ev in events {
            match *ev {
                SimEvent::SweepStrike { dir, .. } => self.strike = Some((now, dir)),
                SimEvent::BossSummon { .. }
                | SimEvent::RainStrike { .. }
                | SimEvent::BossVolley { illusion: false, .. } => self.summon = Some(now),
                _ => {}
            }
        }
    }

    fn summon_frame(&self, boss: Option<&BossState>, now: f32) -> Option<usize> {
        // 出手当帧切到第 2 帧，保持 150ms，再以第 3 帧恢复 150ms。
        // 同时有另一招蓄力时，先完整交代这次发射。
        if let Some(at) = self.summon {
            let elapsed = (now - at).max(0.0);
            if elapsed < 0.3 {
                return Some(if elapsed < 0.15 { 2 } else { 3 });
            }
        }
        let boss = boss?;
        let progress = boss
            .volley
            .as_ref()
            .map(|v| v.t / v.warn)
            .or_else(|| boss.drops.first().map(|r| r.t / r.warn))?;
        // 聚火只用 0–1 帧，按模拟预警进度覆盖完整 800ms；暂停不会提前播完。
        Some(summon_windup_frame(progress))
    }
}

/// 每只小妖的出手时刻（画面自己记，模拟里只有状态）：竹魅射出那一刻、讨封狐现形那一刻。
#[derive(Clone, Copy, Default)]
struct Track {
    aiming: bool,
    shot_at: Option<f32>,
    revealed_at: Option<f32>,
}

/// 挑妖物的出手动作要读的模拟状态（DESIGN 第 15 节“妖物动作”）。
#[derive(bevy::ecs::system::SystemParam)]
pub(crate) struct Moves<'w, 's> {
    content: Res<'w, GameContent>,
    boss: Option<Res<'w, BossState>>,
    outbox: Res<'w, SimOutbox>,
    clock: Local<'s, BossClock>,
    tracks: Local<'s, BTreeMap<EnemyHandle, Track>>,
}

impl Moves<'_, '_> {
    fn update(&mut self, now: f32, en: &Enemies) {
        self.clock.update(&self.outbox.0, now);
        // 死了的、槽位被复用的不再记
        self.tracks.retain(|h, _| en.resolve(*h).is_some());
    }

    /// 竹魅、讨封狐的动作；其余的走 [`Self::pick`]。
    fn pick_minion<'f>(
        &mut self,
        f: &'f EnemyFrames,
        en: &Enemies,
        i: usize,
        now: f32,
    ) -> Option<(&'f EnemyAnim, usize, Option<bool>)> {
        let def = &self.content.0.enemies[en.kind[i] as usize];
        if let (Some(a), Some(sh)) = (&f.shoot, &def.shot) {
            let track = self.tracks.entry(en.handle(i)).or_default();
            if en.aim_t[i] > 0.0 {
                track.aiming = true;
                return Some((a, a.windup_frame(sh.warn - en.aim_t[i]), None));
            }
            // 瞄完了：冷却记满的是射出去了，记一半的是被打断
            if std::mem::take(&mut track.aiming) && en.atk_t[i] > sh.every * 0.75 {
                track.shot_at = Some(now);
            }
            let k = track.shot_at.and_then(|at| a.strike_frame(now - at, false));
            return k.map(|k| (a, k, None));
        }
        if def.disguise.is_some() && en.tags[i] & TAG_REVEALED != 0 {
            let track = self.tracks.entry(en.handle(i)).or_default();
            let at = *track.revealed_at.get_or_insert(now);
            if let Some(a) = &f.reveal
                && let Some(k) = a.strike_frame(now - at, false)
            {
                return Some((a, k, None));
            }
            let a = f.unmasked.as_ref()?;
            let n = a.normal.len();
            let phase = en.wob[i] / TAU * n as f32;
            return Some((a, ((now * a.fps + phase) as usize) % n, None));
        }
        None
    }

    /// 正在出招的妖物：播哪个动作的第几帧，朝不朝左（None：照常朝着主角）。
    fn pick<'f>(
        &self,
        f: &'f EnemyFrames,
        en: &Enemies,
        i: usize,
        now: f32,
    ) -> Option<(&'f EnemyAnim, usize, Option<bool>)> {
        // 冲锋：蓄力时停在最后一个蓄力帧，冲出去接着播，停下来以后播完剩下的
        if let Some(a) = &f.charge
            && let Some(ch) = &self.content.0.enemies[en.kind[i] as usize].charge
        {
            let k = match en.charge[i] {
                CHARGE_WINDUP => Some(a.windup_frame(ch.windup - en.charge_t[i])),
                CHARGE_DASH => a.strike_frame(ch.duration - en.charge_t[i], true),
                CHARGE_RECOVER => a.strike_frame(ch.duration + ch.recover - en.charge_t[i], false),
                _ => None,
            };
            return k.map(|k| (a, k, Some(en.charge_dx[i] < 0.0)));
        }
        let left = |dir: f32| Some(dir.cos() < 0.0);
        // 九尾扫：预警时蓄力，落下时扫过去
        if let Some(a) = &f.sweep {
            if let Some(sw) = self.boss.as_ref().and_then(|b| b.sweeps.first()) {
                return Some((a, a.windup_frame(sw.t), left(sw.dir)));
            }
            if let Some((at, dir)) = self.clock.strike
                && let Some(k) = a.strike_frame(now - at, false)
            {
                return Some((a, k, left(dir)));
            }
        }
        let a = f.summon.as_ref()?;
        let k = self.clock.summon_frame(self.boss.as_deref(), now)?;
        Some((a, k, None))
    }
}

/// 摄像机看得到的范围（世界坐标，留一点边）。
fn view_rect(cam: &Transform, proj: &Projection) -> Rect {
    let half = match proj {
        Projection::Orthographic(o) => o.area.half_size(),
        _ => Vec2::splat(1000.0),
    };
    Rect::from_center_half_size(cam.translation.truncate(), half + Vec2::splat(80.0))
}

pub(crate) fn collect_draws(
    time: Res<Time>,
    fixed: Res<Time<Fixed>>,
    db: Res<AtlasDb>,
    frames: Res<ActorFrames>,
    en: Option<Res<Enemies>>,
    gems: Option<Res<Gems>>,
    arsenal: Option<Res<Arsenal>>,
    sight: Sight,
    mut moves: Moves,
    mut impacts: ResMut<crate::impact::Impacts>,
    bamboo: Option<Res<Bamboo>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    camera: Single<(&Transform, &Projection), With<MainCamera>>,
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowRequests>,
    // 危险区压暗、场景光源、伪法线受光（参数超过 16 个，并成一组）
    (readability, lights, mut surfaces): (
        Res<crate::telegraphs::Readability>,
        Res<SceneLights>,
        ResMut<SurfaceDraws>,
    ),
) {
    glow.0.clear();
    let pools = &mut *pools;
    pools.enemy.clear();
    pools.enemy_shadow.clear();
    pools.fx.clear();
    pools.visible_enemies.clear();
    let fade = 1.0 - pools.dissolve;
    let (Some(en), Some(gems), Some(arsenal)) = (en, gems, arsenal) else { return };
    let a = fixed.overstep_fraction();
    let t = time.elapsed_secs();
    let rect = view_rect(camera.0, camera.1);
    let (ppos, pprev) = *player;
    let player_now = pprev.0.lerp(ppos.0, a);
    moves.update(t, &en);

    // 夜签“无月”：照见圈外完全看不见；“隐”的精英在照见圈外也看不见
    let no_moon = sight.stats.as_ref().is_some_and(|s| s.rule(lantern_content::Rule::NoMoon));
    for i in en.iter_alive() {
        let p = Vec2::new(en.px[i], en.py[i]).lerp(Vec2::new(en.x[i], en.y[i]), a);
        let s = to_screen(p);
        // “隐”着的看不见；伪装的讨封狐照样画（画成路人）
        let disguised = moves.content.0.enemies[en.kind[i] as usize].disguise.is_some();
        if !rect.contains(s) || (en.cloaked[i] && !disguised) {
            continue;
        }
        if no_moon
            && let Some(reveal) = &sight.reveal
            && !reveal.covers(Vec2::new(en.x[i], en.y[i]))
        {
            continue;
        }
        let f = &frames.enemies[en.kind[i] as usize];
        let n = f.base.normal.len();
        if n == 0 {
            continue;
        }
        let (anim, k, face) =
            moves.pick_minion(f, &en, i, t).or_else(|| moves.pick(f, &en, i, t)).unwrap_or_else(|| {
                let phase = en.wob[i] / TAU * n as f32;
                (&f.base, ((t * f.base.fps + phase) as usize) % n, None)
            });
        let response = impacts.hits.get(&en.handle(i)).copied();
        let flashing = response.is_some_and(|h| h.flashing()) && !anim.flash.is_empty();
        let frame = if flashing { anim.flash[k] } else { anim.normal[k] };
        let bob = if f.floating { (t * 2.0 + en.wob[i]).sin() * 1.5 + 4.0 } else { 0.0 };
        let flip = face.unwrap_or(player_now.x < p.x);
        let (deform, offset) = response.map_or((Mat2::IDENTITY, Vec2::ZERO), |h| h.sample());
        let body = Vec2::new(s.x, s.y + bob) + offset;
        impacts.poses.insert(
            en.handle(i),
            crate::impact::Pose {
                frame: anim.normal[k],
                flash: anim.flash.get(k).copied().unwrap_or(anim.normal[k]),
                pos: Vec2::new(s.x, s.y + bob),
                flip,
            },
        );
        // 冰冻发蓝，灼烧发红
        let color = if flashing {
            Color::WHITE
        } else if en.frozen[i] > 0.0 {
            FROZEN_TINT
        } else if en.burn_t[i] > 0.0 {
            let k = 0.5 + 0.5 * (t * 14.0 + en.wob[i]).sin();
            Color::WHITE.mix(&BURN_TINT, k * 0.6)
        } else if en.mark_t[i] > 0.0 && en.mark[i] > 0 {
            // 五行印记：淡淡染上那一系的颜色
            Color::WHITE.mix(&MARK_TINT[en.mark[i] as usize - 1], 0.45)
        } else {
            Color::WHITE
        };
        if pools.visible_enemies.len() < 400 {
            pools.visible_enemies.push(body);
        }
        if fade <= 0.01 {
            continue;
        }
        let def = &moves.content.0.enemies[en.kind[i] as usize];
        // 分裂出来的小号按实际碰撞半径画小；刚刷出来的从墨里浮现（这段时间不伤人）
        let size = Vec2::splat(en.r[i] / def.radius);
        let born = 1.0 - (en.grace[i] / SPAWN_GRACE).clamp(0.0, 1.0);
        let color = color.with_alpha(fade * (0.2 + 0.8 * born));
        // 夜主用伪法线受光（lighting::apply_surface_lights 叠在身上）
        if def.boss.is_some() && !flashing {
            surfaces.0.push(Draw {
                flip,
                color,
                deform,
                scale: size,
                ..Draw::new(frame, body.extend(sort_z(layer::ACTORS, p.y)))
            });
        }
        pools.enemy.push(Draw {
            flip,
            color,
            deform,
            scale: size,
            ..Draw::new(frame, body.extend(sort_z(layer::ACTORS, p.y)))
        });
        let radius = db.frame(frames.shadow).size.x * f.shadow_scale * 0.5;
        let source = if def.boss.is_some() { lights.dominant(s) } else { lights.sources[0] };
        let (offset, stretch) = contact_shadow(s, source, radius);
        pools.enemy_shadow.push(Draw {
            scale: stretch * f.shadow_scale * size,
            color: Color::srgba(1.0, 1.0, 1.0, if f.floating { 0.42 } else { 0.62 } * fade),
            ..Draw::new(frames.shadow, (s + offset).extend(layer::SHADOW))
        });
        if !flashing && let Some(&emit) = anim.emit.get(k) {
            let before = glow.0.len();
            glow.emit(emit, body, flip, Color::WHITE.with_alpha(fade * born));
            if glow.0.len() > before
                && let Some(g) = glow.0.last_mut()
            {
                g.scale = size;
            }
        }
    }

    // 竹丛：和角色一起按脚底排序；打碎的换图，烧平的焦黑，挨打时晃一下
    if let (Some(b), Some((standing, broken, shadow_k))) = (&bamboo, frames.bamboo) {
        for c in b.near() {
            let s = to_screen(c.pos);
            if !rect.contains(s) {
                continue;
            }
            let (frame, color, shake) = match c.state {
                ClumpState::Standing => (standing, Color::WHITE, c.cd.max(0.0) * 8.0),
                ClumpState::Broken(_) => (broken, Color::WHITE, 0.0),
                ClumpState::Burned => (broken, Color::srgb(0.32, 0.27, 0.25), 0.0),
                ClumpState::Cleared => continue,
            };
            let x = s.x + (t * 55.0 + c.pos.x).sin() * shake;
            pools.fx.push(Draw {
                color,
                flip: c.pos.x.rem_euclid(2.0) < 1.0,
                ..Draw::new(frame, Vec3::new(x, s.y, sort_z(layer::ACTORS, c.pos.y)))
            });
            pools.enemy_shadow.push(Draw {
                scale: Vec2::splat(shadow_k),
                color: Color::srgba(1.0, 1.0, 1.0, 0.6),
                ..Draw::new(frames.shadow, Vec3::new(s.x, s.y, layer::SHADOW))
            });
        }
    }

    // 灯火：按插值后的角度绕着主角；火焰画在暗层之上（网页版的画法），同时是光源
    for slot in &arsenal.0 {
        if slot.count == 0 || slot.size <= 0.0 {
            continue;
        }
        // 巨凤由特效层复用鹤的帧绘制；这里只画灯火
        if !matches!(slot.behavior(&moves.content.0), lantern_content::WeaponBehavior::Orbit { .. }) {
            continue;
        }
        // 冰火两重天：偶数盏是冰焰
        let ice = matches!(
            slot.behavior(&moves.content.0),
            lantern_content::WeaponBehavior::Orbit { ice_fire: Some(_), .. }
        );
        let angle = slot.prev_angle + (slot.angle - slot.prev_angle) * a;
        for k in 0..slot.count {
            let p = player_now + slot.orbit_offset(angle, k);
            let s = to_screen(p);
            let fk = ((t * 10.0) as usize + k as usize) % frames.flames.len();
            pools.fx.push(Draw {
                scale: Vec2::splat(slot.size / 10.0),
                color: (if ice && k % 2 == 0 { ICE_FLAME } else { Color::WHITE })
                    .with_alpha(readability.gain),
                ..Draw::new(frames.flames[fk], s.extend(sort_z(layer::WEAPONS, p.y)))
            });
            let light = if ice && k % 2 == 0 { ICE_FLAME_LIGHT } else { FLAME_LIGHT.0 };
            glow.light(&frames, &db, s, (light.with_alpha(light.alpha() * readability.gain), FLAME_LIGHT.1));
        }
    }

    // 魂火：自发光，靠近的同时是光源。满地魂火时每颗的光弱一些，免得画面糊成一片光斑
    let mut lights = 0;
    let crowd = (60.0 / gems.n.max(1) as f32).clamp(0.3, 1.0);
    let gem_light = GEM_LIGHT.with_alpha(GEM_LIGHT.alpha() * crowd);
    for i in 0..gems.n {
        let p = Vec2::new(gems.px[i], gems.py[i]).lerp(Vec2::new(gems.x[i], gems.y[i]), a);
        let s = to_screen(p);
        if !rect.contains(s) {
            continue;
        }
        let v = gems.value[i];
        let size = if v < 2.0 {
            0
        } else if v < 6.0 {
            1
        } else {
            2
        };
        let pos = Vec2::new(s.x, s.y + 3.0 + (t * 3.0 + i as f32).sin() * 1.5);
        glow.emit(frames.gems[size], pos, false, GEM_COLOR);
        if lights < GEM_LIGHT_CAP {
            lights += 1;
            glow.light(&frames, &db, pos, (gem_light, 24.0 + 6.0 * size as f32));
        }
    }
}

/// 主角的影子独立于身体动画：原地翻身或闪避不会把贴地椭圆一起抬起。
pub(crate) fn update_hero_shadow(
    lights: Res<SceneLights>,
    hero: Res<HeroFrames>,
    frames: Res<ActorFrames>,
    db: Res<AtlasDb>,
    player: Single<&Transform, With<Player>>,
    mut q: Query<(&mut Transform, &mut Sprite), (With<HeroShadow>, Without<Player>)>,
) {
    let pos = player.translation.truncate();
    let size = db.frame(frames.shadow).size * hero.shadow_scale;
    let (offset, stretch) = contact_shadow(pos, lights.dominant(pos), size.x * 0.5);
    for (mut tf, mut sprite) in &mut q {
        tf.translation = (pos + offset).extend(layer::SHADOW);
        sprite.custom_size = Some(size * stretch);
    }
}

/// 把攒好的绘制内容写进精灵池；不够就按本帧姿态补生成，多余的隐藏。
pub(crate) fn apply_pools(
    mut commands: Commands,
    db: Res<AtlasDb>,
    mut pools: ResMut<Pools>,
    mut q: Query<(
        &Pooled,
        &mut Sprite,
        &mut Anchor,
        &mut Transform,
        &mut Visibility,
        &mut crate::impact::SpriteDeform,
    )>,
) {
    let pools = &mut *pools;
    let mut used = [0usize; 3];
    for (kind, mut sprite, mut anchor, mut tf, mut vis, mut deform) in &mut q {
        let (list, k) = match kind {
            Pooled::Enemy => (&pools.enemy, 0),
            Pooled::EnemyShadow => (&pools.enemy_shadow, 1),
            Pooled::Fx => (&pools.fx, 2),
        };
        let Some(d) = list.get(used[k]) else {
            vis.set_if_neq(Visibility::Hidden);
            continue;
        };
        used[k] += 1;
        db.set(d.frame, &mut sprite, &mut anchor);
        if d.scale != Vec2::ONE {
            sprite.custom_size = Some(db.frame(d.frame).size * d.scale);
        }
        deform.0 = d.deform;
        sprite.flip_x = d.flip;
        sprite.color = d.color;
        tf.translation = d.pos;
        tf.rotation = if d.rot == 0.0 { Quat::IDENTITY } else { Quat::from_rotation_z(d.rot) };
        vis.set_if_neq(Visibility::Inherited);
    }
    // 不够的补上
    let kinds = [Pooled::Enemy, Pooled::EnemyShadow, Pooled::Fx];
    let lens = [pools.enemy.len(), pools.enemy_shadow.len(), pools.fx.len()];
    for k in 0..kinds.len() {
        if lens[k] > pools.spawned[k] {
            let batch: Vec<_> = (pools.spawned[k]..lens[k])
                .map(|i| {
                    let d = match kinds[k] {
                        Pooled::Enemy => &pools.enemy[i],
                        Pooled::EnemyShadow => &pools.enemy_shadow[i],
                        Pooled::Fx => &pools.fx[i],
                    };
                    let (mut sprite, anchor) = db.sprite(d.frame);
                    sprite.custom_size = Some(db.frame(d.frame).size * d.scale);
                    sprite.color = d.color;
                    sprite.flip_x = d.flip;
                    (
                        kinds[k],
                        crate::impact::SpriteDeform(d.deform),
                        sprite,
                        anchor,
                        Transform::from_translation(d.pos).with_rotation(Quat::from_rotation_z(d.rot)),
                        Visibility::Inherited,
                        DespawnOnExit(AppState::Run),
                    )
                })
                .collect();
            commands.spawn_batch(batch);
            pools.spawned[k] = lens[k];
        }
    }
}

/// 发光池里的一个 Mesh2d。
#[derive(Component)]
pub(crate) struct GlowSlot {
    light: bool,
}

#[derive(Resource, Default)]
pub(crate) struct GlowPool {
    /// 已生成的光源、自发光数量
    spawned: [usize; 2],
}

/// 把发光请求写进 Mesh2d 池：光源在光照相机的图层，自发光在主画面暗层之上。
pub(crate) fn apply_glow(
    mut commands: Commands,
    db: Res<AtlasDb>,
    glow: Res<GlowRequests>,
    mut cache: ResMut<FrameMeshes>,
    mut pool: ResMut<GlowPool>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<AddMaterial>>,
    mut q: Query<(&GlowSlot, &mut Mesh2d, &mut MeshMaterial2d<AddMaterial>, &mut Transform, &mut Visibility)>,
) {
    let (mut lights, mut emits): (Vec<&Glow>, Vec<&Glow>) = (Vec::new(), Vec::new());
    for g in &glow.0 {
        if g.light { lights.push(g) } else { emits.push(g) }
    }
    let mut used = [0usize; 2];
    for (slot, mut mesh, mut material, mut tf, mut vis) in &mut q {
        let (list, k) = if slot.light { (&lights, 0) } else { (&emits, 1) };
        let Some(g) = list.get(used[k]) else {
            vis.set_if_neq(Visibility::Hidden);
            continue;
        };
        used[k] += 1;
        let m = cache.mesh(&db, &mut meshes, g.frame, g.flip);
        if mesh.0 != m {
            mesh.0 = m;
        }
        let mat = cache.additive(&db, &mut materials, g.frame, g.color, !g.light);
        if material.0 != mat {
            material.0 = mat;
        }
        tf.translation = g.pos;
        tf.scale = g.scale.extend(1.0);
        tf.rotation = if g.rot == 0.0 { Quat::IDENTITY } else { Quat::from_rotation_z(g.rot) };
        vis.set_if_neq(Visibility::Inherited);
    }
    for (k, list) in [lights, emits].iter().enumerate() {
        let light = k == 0;
        while pool.spawned[k] < list.len() {
            let g = list[pool.spawned[k]];
            pool.spawned[k] += 1;
            let mesh = cache.mesh(&db, &mut meshes, g.frame, g.flip);
            let mat = cache.additive(&db, &mut materials, g.frame, g.color, !light);
            let mut e = commands.spawn((
                GlowSlot { light },
                Mesh2d(mesh),
                MeshMaterial2d(mat),
                Transform::from_translation(g.pos)
                    .with_scale(g.scale.extend(1.0))
                    .with_rotation(Quat::from_rotation_z(g.rot)),
                Visibility::Inherited,
                DespawnOnExit(AppState::Run),
            ));
            if light {
                e.insert(RenderLayers::layer(LIGHT_LAYER));
            }
        }
    }
}

/// 一局结束时精灵池跟着清掉，计数归零。
pub(crate) fn reset_pools(
    mut pools: ResMut<Pools>,
    mut glow: ResMut<GlowPool>,
    mut flare: ResMut<LanternFlare>,
) {
    *pools = Pools::default();
    *glow = GlowPool::default();
    *flare = LanternFlare::default();
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 出手动作（DESIGN 第 15 节）：蓄力帧停在最后一个，出手后接着播；
    /// 只播一遍的停在最后一帧，招式结束回到平时；loop_from 的从那一帧循环。
    #[test]
    fn attack_frames_follow_windup_and_loop() {
        // 赤面狐 pounce：6 帧、12 帧每秒、2 帧蓄力
        assert_eq!(windup_frame(2, 12.0, 0.0), 0);
        assert_eq!(windup_frame(2, 12.0, 0.09), 1);
        assert_eq!(windup_frame(2, 12.0, 0.5), 1, "停在最后一个蓄力帧等预警结束");
        assert_eq!(strike_frame(6, 2, None, 12.0, 0.0, true), Some(2));
        assert_eq!(strike_frame(6, 2, None, 12.0, 0.4, true), Some(5), "播完停在最后一帧");
        assert_eq!(strike_frame(6, 2, None, 12.0, 0.4, false), None, "招式结束回到平时的动作");
        assert_eq!(strike_frame(6, 2, None, 12.0, 0.2, false), Some(4), "停下时没播完的接着播");
        // 青面鬼 charge：6 帧、10 帧每秒、从第 2 帧循环
        assert_eq!(strike_frame(6, 2, Some(2), 10.0, 0.4, true), Some(2));
        assert_eq!(strike_frame(6, 2, Some(2), 10.0, 0.55, true), Some(3));
        assert_eq!(strike_frame(6, 2, Some(2), 10.0, 0.7, false), None);
    }

    fn charging_boss(rain: bool) -> BossState {
        use lantern_sim::boss::{RainDrop, Volley};
        let mut boss = BossState::default();
        if rain {
            boss.drops.push(RainDrop { pos: Vec2::ZERO, radius: 40.0, damage: 16.0, t: 0.0, warn: 0.8 });
        } else {
            boss.volley = Some(Volley {
                origin: Vec2::ZERO,
                offset: 0.0,
                count: 12,
                speed: 115.0,
                radius: 6.0,
                damage: 16.0,
                life: 6.0,
                t: 0.0,
                warn: 0.8,
            });
        }
        boss
    }

    #[test]
    fn summon_charge_release_and_recovery_never_rewind_at_30_or_60_fps() {
        for fps in [30, 60] {
            for rain in [false, true] {
                let mut boss = charging_boss(rain);
                let mut clock = BossClock::default();
                for frame in 0..fps * 4 / 5 {
                    let t = frame as f32 / fps as f32;
                    if rain {
                        boss.drops[0].t = t;
                    } else {
                        boss.volley.as_mut().unwrap().t = t;
                    }
                    let want = Some(usize::from(t >= 0.4));
                    assert_eq!(clock.summon_frame(Some(&boss), t), want);
                    // 模拟暂停或顿帧时，画面时间再长也不能进入发射帧。
                    assert_eq!(clock.summon_frame(Some(&boss), t + 10.0), want);
                }
                let event = if rain {
                    SimEvent::RainStrike { pos: Vec2::ZERO }
                } else {
                    SimEvent::BossVolley { pos: Vec2::ZERO, illusion: false }
                };
                clock.update(&[event], 0.0);
                assert_eq!(clock.summon_frame(Some(&boss), 0.0), Some(2));
                for frame in 0..=fps * 2 / 5 {
                    let t = frame as f32 / fps as f32;
                    let want = if t < 0.15 {
                        Some(2)
                    } else if t < 0.3 {
                        Some(3)
                    } else {
                        None
                    };
                    assert_eq!(clock.summon_frame(None, t), want);
                }
            }
        }
    }

    #[test]
    fn simultaneous_illusions_do_not_start_or_restart_the_body_animation() {
        let illusions = [SimEvent::BossVolley { pos: Vec2::ZERO, illusion: true }; 2];
        let mut clock = BossClock::default();
        clock.update(&illusions, 0.0);
        assert_eq!(clock.summon_frame(None, 0.0), None);
        let boss = charging_boss(false);
        assert_eq!(clock.summon_frame(Some(&boss), 0.0), Some(0));
        clock.update(&[SimEvent::BossVolley { pos: Vec2::ZERO, illusion: false }], 0.0);
        clock.update(&illusions, 0.2);
        assert_eq!(clock.summon_frame(None, 0.2), Some(3));
        assert_eq!(clock.summon_frame(None, 0.31), None);
        // 雨的起手只读模拟预警，实际落下才接发射与恢复。
        clock.update(&[SimEvent::RainWarn { count: 5 }], 1.0);
        assert_eq!(clock.summon_frame(None, 1.0), None);
        for event in [SimEvent::RainStrike { pos: Vec2::ZERO }, SimEvent::BossSummon { pos: Vec2::ZERO }] {
            clock.update(&[event], 2.0);
            assert_eq!(clock.summon_frame(None, 2.0), Some(2));
        }
    }
}
