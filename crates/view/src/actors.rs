//! 角色层：主角、妖物、灯火、魂火、影子（docs/DESIGN.md 第 9 节）。
//!
//! 妖物和魂火在模拟的池子里，这里用固定的精灵池，每帧只画视野内的，不随妖物生死创建、销毁实体。
//! 前后关系按脚底 y 排序（z 越大越靠前）。

use std::f32::consts::{FRAC_PI_4, TAU};

use bevy::prelude::*;
use bevy::sprite::Anchor;

use lantern_sim::{AppState, Arsenal, Enemies, GameContent, Gems, Player, Pos, PrevPos, RunState};

use crate::atlas::{AtlasDb, FrameId};
use crate::{MainCamera, layer, to_screen};

/// 8 个方向，顺序与图集一致：E SE S SW W NW N NE（y 向下，角度顺时针增加）。
const DIRS: [&str; 8] = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"];

/// 按脚底 y 排序的 z：越靠下（越近）越大。
pub fn sort_z(base: f32, sim_y: f32) -> f32 {
    base + sim_y * 1e-4
}

// ---------------------------------------------------------------------------
// 帧缓存：每帧要查几千次，开局前按名字查好
// ---------------------------------------------------------------------------

struct HeroAnim {
    /// [方向][帧]
    frames: Vec<Vec<FrameId>>,
    fps: f32,
    stride: Option<f32>,
}

#[derive(Resource)]
pub(crate) struct HeroFrames {
    idle: HeroAnim,
    walk: HeroAnim,
    dash: HeroAnim,
    death: HeroAnim,
    shadow_scale: f32,
}

struct EnemyFrames {
    normal: Vec<FrameId>,
    flash: Vec<FrameId>,
    fps: f32,
    floating: bool,
    shadow_scale: f32,
}

#[derive(Resource)]
pub(crate) struct ActorFrames {
    /// 按 `enemies.ron` 的下标
    enemies: Vec<EnemyFrames>,
    flames: Vec<FrameId>,
    gems: [FrameId; 3],
    shadow: FrameId,
}

fn hero_anim(db: &AtlasDb, anim: &str) -> HeroAnim {
    let meta = db.assets.get("hero").and_then(|a| a.anims.get(anim));
    let frames = DIRS
        .iter()
        .map(|d| db.anim(&format!("hero/{anim}_{d}")).map(<[FrameId]>::to_vec).unwrap_or_default())
        .collect();
    HeroAnim { frames, fps: meta.map_or(8.0, |m| m.fps), stride: meta.and_then(|m| m.stride_units) }
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
        death: hero_anim(&db, "death"),
        shadow_scale: shadow_scale(&db, "hero", shadow),
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
            let (anim, am) = meta.anims.iter().min_by_key(|(k, _)| k.as_str()).expect("素材至少有一个动作");
            let seq = |suffix: &str| {
                db.anim(&format!("{asset}/{anim}_E{suffix}")).map(<[FrameId]>::to_vec).unwrap_or_default()
            };
            let normal = seq("");
            let flash = seq("_flash");
            EnemyFrames {
                flash: if flash.len() == normal.len() { flash } else { normal.clone() },
                normal,
                fps: am.fps,
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
    });
}

// ---------------------------------------------------------------------------
// 主角
// ---------------------------------------------------------------------------

/// 主角的画面状态。
#[derive(Component, Default)]
pub(crate) struct HeroView {
    dir: usize,
    /// 待机、闪避、倒地动画的计时
    clock: f32,
    /// 走路动画按移动距离推进
    stride: f32,
    last_pos: Vec2,
    dying: bool,
}

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
        HeroView { dir: 2, ..default() },
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

pub(crate) fn animate_hero(
    time: Res<Time>,
    hero: Res<HeroFrames>,
    db: Res<AtlasDb>,
    run: Option<Res<State<RunState>>>,
    mut q: Query<(&Player, &Transform, &mut HeroView, &mut Sprite, &mut Anchor)>,
    mut shadow: Query<&mut Transform, (With<HeroShadow>, Without<Player>)>,
) {
    let over = run.is_some_and(|s| *s.get() == RunState::Over);
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
        view.clock += dt;
        let (anim, frame) = if view.dying {
            let n = hero.death.frames[view.dir].len().max(1);
            (&hero.death, ((view.clock * hero.death.fps) as usize).min(n - 1))
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
        if let Some(&id) = seq.get(frame % seq.len().max(1)) {
            db.set(id, &mut sprite, &mut anchor);
        }
        for mut s in &mut shadow {
            s.translation = Vec3::new(pos.x, pos.y, layer::SHADOW);
        }
    }
}

// ---------------------------------------------------------------------------
// 精灵池：妖物、妖物影子、灯火、魂火
// ---------------------------------------------------------------------------

#[derive(Component, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Pooled {
    Enemy,
    EnemyShadow,
    Flame,
    Gem,
}

/// 每类精灵本帧要显示的内容，攒好后一次写进池子。
#[derive(Default)]
pub(crate) struct Draw {
    frame: Option<FrameId>,
    pos: Vec3,
    flip: bool,
    size_scale: f32,
    color: Color,
}

#[derive(Resource, Default)]
pub(crate) struct Pools {
    enemy: Vec<Draw>,
    enemy_shadow: Vec<Draw>,
    flame: Vec<Draw>,
    gem: Vec<Draw>,
    /// 每类已经生成的精灵数
    spawned: [usize; 4],
}

const GEM_COLOR: Color = Color::srgb(0.75, 0.94, 1.0);

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
    frames: Res<ActorFrames>,
    en: Option<Res<Enemies>>,
    gems: Option<Res<Gems>>,
    arsenal: Option<Res<Arsenal>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    camera: Single<(&Transform, &Projection), With<MainCamera>>,
    mut pools: ResMut<Pools>,
) {
    let (Some(en), Some(gems), Some(arsenal)) = (en, gems, arsenal) else { return };
    let a = fixed.overstep_fraction();
    let t = time.elapsed_secs();
    let rect = view_rect(camera.0, camera.1);
    let (ppos, pprev) = *player;
    let player_now = pprev.0.lerp(ppos.0, a);
    let pools = &mut *pools;
    pools.enemy.clear();
    pools.enemy_shadow.clear();
    pools.flame.clear();
    pools.gem.clear();

    for i in en.iter_alive() {
        let p = Vec2::new(en.px[i], en.py[i]).lerp(Vec2::new(en.x[i], en.y[i]), a);
        let s = to_screen(p);
        if !rect.contains(s) {
            continue;
        }
        let kind = en.kind[i] as usize;
        let f = &frames.enemies[kind];
        let n = f.normal.len().max(1);
        let phase = en.wob[i] / TAU * n as f32;
        let k = ((t * f.fps + phase) as usize) % n;
        let seq = if en.flash[i] > 0.0 { &f.flash } else { &f.normal };
        let bob = if f.floating { (t * 2.0 + en.wob[i]).sin() * 1.5 + 4.0 } else { 0.0 };
        pools.enemy.push(Draw {
            frame: seq.get(k).copied(),
            pos: Vec3::new(s.x, s.y + bob, sort_z(layer::ACTORS, p.y)),
            flip: player_now.x < p.x,
            size_scale: 1.0,
            color: Color::WHITE,
        });
        pools.enemy_shadow.push(Draw {
            frame: Some(frames.shadow),
            pos: Vec3::new(s.x, s.y, layer::SHADOW),
            flip: false,
            size_scale: f.shadow_scale,
            color: Color::srgba(1.0, 1.0, 1.0, 0.7),
        });
    }

    // 灯火：按插值后的角度绕着主角
    for slot in &arsenal.0 {
        let angle = slot.prev_angle + (slot.angle - slot.prev_angle) * a;
        for k in 0..slot.count {
            let p = player_now + slot.orbit_offset(angle, k);
            let s = to_screen(p);
            let fk = ((t * 10.0) as usize + k as usize) % frames.flames.len();
            pools.flame.push(Draw {
                frame: Some(frames.flames[fk]),
                pos: Vec3::new(s.x, s.y, sort_z(layer::ACTORS, p.y)),
                flip: false,
                size_scale: slot.size / 10.0,
                color: Color::WHITE,
            });
        }
    }

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
        pools.gem.push(Draw {
            frame: Some(frames.gems[size]),
            pos: Vec3::new(s.x, s.y + 3.0 + (t * 3.0 + i as f32).sin() * 1.5, layer::GEMS),
            flip: false,
            size_scale: 1.0,
            color: GEM_COLOR,
        });
    }
}

/// 把攒好的绘制内容写进精灵池；不够就补生成（下一帧可见），多余的隐藏。
pub(crate) fn apply_pools(
    mut commands: Commands,
    db: Res<AtlasDb>,
    mut pools: ResMut<Pools>,
    mut q: Query<(&Pooled, &mut Sprite, &mut Anchor, &mut Transform, &mut Visibility)>,
) {
    let pools = &mut *pools;
    let mut used = [0usize; 4];
    for (kind, mut sprite, mut anchor, mut tf, mut vis) in &mut q {
        let (list, k) = match kind {
            Pooled::Enemy => (&pools.enemy, 0),
            Pooled::EnemyShadow => (&pools.enemy_shadow, 1),
            Pooled::Flame => (&pools.flame, 2),
            Pooled::Gem => (&pools.gem, 3),
        };
        let Some(d) = list.get(used[k]) else {
            if *vis != Visibility::Hidden {
                *vis = Visibility::Hidden;
            }
            continue;
        };
        used[k] += 1;
        let Some(frame) = d.frame else { continue };
        db.set(frame, &mut sprite, &mut anchor);
        if d.size_scale != 1.0 {
            sprite.custom_size = Some(db.frame(frame).size * d.size_scale);
        }
        sprite.flip_x = d.flip;
        sprite.color = d.color;
        tf.translation = d.pos;
        if *vis != Visibility::Inherited {
            *vis = Visibility::Inherited;
        }
    }
    // 不够的补上
    let kinds = [Pooled::Enemy, Pooled::EnemyShadow, Pooled::Flame, Pooled::Gem];
    let lens = [pools.enemy.len(), pools.enemy_shadow.len(), pools.flame.len(), pools.gem.len()];
    for k in 0..4 {
        let have = pools.spawned[k];
        if lens[k] > have {
            let first = pools_first_frame(&db);
            let batch: Vec<_> = (have..lens[k])
                .map(|_| {
                    let (sprite, anchor) = db.sprite(first);
                    (
                        kinds[k],
                        sprite,
                        anchor,
                        Transform::default(),
                        Visibility::Hidden,
                        DespawnOnExit(AppState::Run),
                    )
                })
                .collect();
            commands.spawn_batch(batch);
            pools.spawned[k] = lens[k];
        }
    }
}

fn pools_first_frame(db: &AtlasDb) -> FrameId {
    db.find("vfx/shadow").unwrap_or(FrameId(0))
}

/// 一局结束时精灵池跟着清掉，计数归零。
pub(crate) fn reset_pools(mut pools: ResMut<Pools>) {
    *pools = Pools::default();
}
