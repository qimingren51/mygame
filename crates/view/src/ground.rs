//! 青丘地面：纸底上的青灰土色、林缘积叶与狐祠庭院。地表成片，通行带疏朗。
//!
//! 世界按 512 单位分块，每块的装饰由“本局种子 + 块坐标”决定，同一个种子每次看到的地面一样。
//! 这是纯画面的随机，不消耗模拟的随机流。只保留镜头附近的块。

use std::collections::HashMap;

use bevy::prelude::*;
use bevy::sprite::Anchor;

use lantern_core::Pcg32;
use lantern_sim::{AppState, Player, RunSetup};

use crate::actors::sort_z;
use crate::atlas::{AtlasDb, FrameId};
use crate::effects::PropLight;
use crate::{MainCamera, layer};

const CHUNK: f32 = 512.0;
/// 镜头周围保留几圈块
const KEEP: i32 = 2;

/// 宣纸平铺块的边长（世界单位）。宣纸图 1024 像素，按图集密度 1 纹素 = 0.25 世界单位
/// （docs/DESIGN.md 第 15 节）。
const PAPER_TILE: f32 = 256.0;

#[derive(Component)]
pub(crate) struct Paper;

pub(crate) fn spawn_paper(mut commands: Commands, assets: Res<crate::SceneAssets>, db: Res<AtlasDb>) {
    commands.spawn((
        Paper,
        DespawnOnExit(AppState::Run),
        Sprite {
            image: assets.paper.clone(),
            custom_size: Some(Vec2::splat(PAPER_TILE * 8.0)),
            image_mode: SpriteImageMode::Tiled {
                tile_x: true,
                tile_y: true,
                stretch_value: 1.0 / db.px_per_unit,
            },
            ..default()
        },
        Transform::from_xyz(0.0, 0.0, layer::PAPER),
    ));
}

/// 宣纸跟着镜头按整块平移，看起来是无限平铺。
pub(crate) fn scroll_paper(
    cam: Single<&Transform, (With<MainCamera>, Without<Paper>)>,
    mut paper: Single<&mut Transform, With<Paper>>,
) {
    let snap = |v: f32| (v / PAPER_TILE).round() * PAPER_TILE;
    paper.translation.x = snap(cam.translation.x);
    paper.translation.y = snap(cam.translation.y);
}

/// 装饰的种类：帧名前缀、每块平均几个、所在图层。
struct DecorKind {
    frames: Vec<FrameId>,
    per_chunk: f32,
    /// true：和角色一起按 y 排序（山石、灯笼）；false：平铺在地面
    upright: bool,
    /// 带光的道具（石灯笼）
    light: Option<PropLight>,
}

#[derive(Resource)]
pub(crate) struct Decor {
    kinds: Vec<DecorKind>,
    beds: Vec<FrameId>,
    chunks: HashMap<IVec2, Vec<Entity>>,
}

/// 道具的挂点（图集像素，相对脚底，y 向下）换算成世界坐标（y 向上）。
fn socket(db: &AtlasDb, asset: &str, name: &str) -> Option<Vec2> {
    let &[x, y] = db.assets.get(asset)?.sockets.get(name)?.get("idle")?.get("S")?.first()?;
    Some(Vec2::new(x, -y) / db.px_per_unit)
}

/// 自己会发光的道具（狐灯、狐仙祠）：光色、光半径写在素材 meta 里，光放在 glow 挂点。
fn glowing_prop(db: &AtlasDb, asset: &str, per_chunk: f32) -> Option<DecorKind> {
    let frame = db.find(&format!("{asset}/idle_S_00"))?;
    let meta = db.assets.get(asset)?;
    let color = crate::fx::hex(meta.light_color.as_deref()?);
    Some(DecorKind {
        frames: vec![frame],
        per_chunk,
        upright: true,
        light: Some(PropLight {
            offset: socket(db, asset, "glow").unwrap_or(Vec2::new(0.0, 20.0)),
            color: color.with_alpha(0.85),
            radius: meta.light_radius_units.unwrap_or(80.0),
            emit: db.find(&format!("{asset}/idle_S_00_emit")),
        }),
    })
}

pub(crate) fn build_decor(mut commands: Commands, db: Res<AtlasDb>) {
    let frames = |names: &[&str]| names.iter().filter_map(|n| db.find(n)).collect::<Vec<_>>();
    let flat = |names: &[&str], per_chunk: f32| DecorKind {
        frames: frames(names),
        per_chunk,
        upright: false,
        light: None,
    };
    let upright = |names: &[&str], per_chunk: f32| DecorKind {
        frames: frames(names),
        per_chunk,
        upright: true,
        light: None,
    };
    // P0 只有青丘（竹海、狐村，docs/LORE.md 6.1）：通用的草、墨晕之外，铺青丘的落竹叶、苔点、
    // 青绿晕染、狐爪印、竹笋，偶尔有石狐、狐仙祠和狐灯。加地区时按地区挑
    let mut kinds = vec![
        flat(&["ground/grass_0", "ground/grass_1", "ground/grass_2", "ground/grass_3"], 10.0),
        flat(&["ground/leaves_0", "ground/leaves_1", "ground/pebbles_0", "ground/pebbles_1"], 1.5),
        flat(&["ground/qq_bamboo_leaves_0", "ground/qq_bamboo_leaves_1", "ground/qq_bamboo_leaves_2"], 9.0),
        flat(&["ground/qq_moss_0", "ground/qq_moss_1"], 5.0),
        flat(&["ground/qq_fox_tracks"], 0.4),
        upright(&["ground/reed_0", "ground/reed_1", "ground/reed_2"], 0.6),
        upright(&["ground/bamboo_0", "ground/bamboo_1"], 1.2),
        upright(&["ground/qq_shoots_0", "ground/qq_shoots_1"], 1.0),
        upright(&["stone_fox/idle_S_00"], 0.2),
    ];
    // 狐祠由庭院构图单独生成，散点里不再出现第二座。
    kinds.extend(glowing_prop(&db, "fox_lanterns", 0.12));
    kinds.extend([
        upright(&["rock_a/idle_S_00", "rock_b/idle_S_00", "rock_c/idle_S_00"], 0.8),
        // 地上装饰的石灯笼默认熄灭（长夜里的石灯笼都熄了，要守灯人去点，docs/LORE.md 11.5）；
        // 图集里没有熄灭版时用点亮的那张，带光
        match db.find("stone_lantern_dark/idle_S_00") {
            Some(dark) => DecorKind { frames: vec![dark], per_chunk: 0.25, upright: true, light: None },
            None => DecorKind {
                frames: frames(&["stone_lantern/idle_S_00"]),
                per_chunk: 0.25,
                upright: true,
                light: Some(PropLight {
                    offset: socket(&db, "stone_lantern", "flame").unwrap_or(Vec2::new(0.0, 20.0)),
                    color: Color::srgba(1.0, 0.784, 0.565, 0.9),
                    radius: 120.0,
                    emit: db.find("stone_lantern/idle_S_00_emit"),
                }),
            },
        },
    ]);
    commands.insert_resource(Decor {
        kinds: kinds.into_iter().filter(|k| !k.frames.is_empty()).collect(),
        beds: frames(&["ground/qq_wash_0", "ground/qq_wash_1", "ground/wash_0", "ground/wash_2"]),
        chunks: HashMap::new(),
    });
}

fn chunk_rng(seed: u64, c: IVec2) -> Pcg32 {
    let key = (c.x as u32 as u64) << 32 | c.y as u32 as u64;
    Pcg32::new(seed ^ key.wrapping_mul(0x9E37_79B9_7F4A_7C15), 0x006c_616e_7465_726e)
}

/// 一片地表的浓淡和尺度独立于散物数量。稀疏墨晕承担大形，叶片只补近看的细节。
/// 这是贴地的土色，不引入水域、台阶或不可通行的林墙。
#[derive(Clone, Copy)]
struct GroundPatch {
    pos: Vec2,
    scale: Vec2,
    opacity: f32,
    flip: bool,
    variant: u32,
}

fn ground_patches(seed: u64, c: IVec2) -> [GroundPatch; 3] {
    let mut rng = chunk_rng(seed ^ 0x6772_6f75_6e64_6265, c);
    std::array::from_fn(|_| GroundPatch {
        pos: c.as_vec2() * CHUNK + Vec2::new(rng.range_f32(38.0, 474.0), rng.range_f32(38.0, 474.0)),
        scale: Vec2::new(rng.range_f32(1.8, 2.9), rng.range_f32(1.45, 2.1)),
        opacity: rng.range_f32(0.6, 0.9),
        flip: rng.chance(0.5),
        variant: rng.next_u32(),
    })
}

/// 旧路只由少积叶、少草的连续留白暗示；它仍是和旁边完全相同的可走地面。
/// 横穿出生处，不按块重置，镜头移动后也不会变成互不相干的小空地。
fn trail_density(at: Vec2, seed: u64) -> f32 {
    let phase = (seed % 1024) as f32 * 0.006;
    let bend = ((at.x / 340.0 + phase).sin() - phase.sin()) * 52.0 + at.x * 0.16;
    let distance = (at.y - bend).abs();
    let t = ((distance - 42.0) / 90.0).clamp(0.0, 1.0);
    0.12 + 0.88 * t * t * (3.0 - 2.0 * t)
}

fn spawn_ground_beds(
    commands: &mut Commands,
    db: &AtlasDb,
    beds: &[FrameId],
    patches: &[GroundPatch; 3],
    seed: u64,
    entities: &mut Vec<Entity>,
) {
    if beds.is_empty() {
        return;
    }
    for (k, patch) in patches.iter().enumerate() {
        let frame = beds[patch.variant as usize % beds.len()];
        let (mut sprite, anchor) = db.sprite(frame);
        sprite.flip_x = patch.flip;
        // 庭院也需要土色落地；只减弱密度，不把它挖成一块与周围断开的白纸。
        let alpha = patch.opacity
            * (0.45 + 0.55 * decor_density(patch.pos, seed))
            * (0.6 + 0.4 * trail_density(patch.pos, seed));
        sprite.color = Color::WHITE.with_alpha(alpha);
        entities.push(
            commands
                .spawn((
                    sprite,
                    anchor,
                    Transform::from_xyz(patch.pos.x, -patch.pos.y, layer::GROUND - 2.0 + k as f32 * 0.01)
                        .with_scale(patch.scale.extend(1.0)),
                ))
                .id(),
        );
    }
}

pub(crate) fn update_decor(
    mut commands: Commands,
    db: Res<AtlasDb>,
    setup: Res<RunSetup>,
    cam: Single<&Transform, With<MainCamera>>,
    mut decor: ResMut<Decor>,
) {
    let center =
        IVec2::new((cam.translation.x / CHUNK).floor() as i32, (-cam.translation.y / CHUNK).floor() as i32);
    let decor = &mut *decor;
    // 移除离开范围的块
    decor.chunks.retain(|c, entities| {
        let keep = (c.x - center.x).abs() <= KEEP && (c.y - center.y).abs() <= KEEP;
        if !keep {
            for &e in entities.iter() {
                commands.entity(e).despawn();
            }
        }
        keep
    });
    for cy in center.y - KEEP..=center.y + KEEP {
        for cx in center.x - KEEP..=center.x + KEEP {
            let c = IVec2::new(cx, cy);
            if decor.chunks.contains_key(&c) {
                continue;
            }
            let mut rng = chunk_rng(setup.seed, c);
            let mut entities = Vec::new();
            let patches = ground_patches(setup.seed, c);
            spawn_ground_beds(&mut commands, &db, &decor.beds, &patches, setup.seed, &mut entities);
            for kind in &decor.kinds {
                let n = (kind.per_chunk + rng.next_f32()) as u32;
                for _ in 0..n {
                    // 模拟坐标（y 向下）
                    let at = if !kind.upright && rng.chance(0.82) {
                        let patch = patches[rng.below(patches.len() as u32) as usize];
                        // 同一片地表共用落点范围，避免草、苔、竹叶各自均匀撒满纸面。
                        patch.pos
                            + Vec2::new(rng.range_f32(-45.0, 45.0), rng.range_f32(-30.0, 30.0)) * patch.scale
                    } else {
                        Vec2::new((cx as f32 + rng.next_f32()) * CHUNK, (cy as f32 + rng.next_f32()) * CHUNK)
                    };
                    let Vec2 { x, y } = at;
                    if rng.next_f32() >= decor_density(at, setup.seed) * trail_density(at, setup.seed) {
                        continue;
                    }
                    // 主角出生点附近不放山石，免得开局挡住
                    if kind.upright && x * x + y * y < 120.0 * 120.0 {
                        continue;
                    }
                    let frame = kind.frames[rng.below(kind.frames.len() as u32) as usize];
                    let (mut sprite, anchor) = db.sprite(frame);
                    sprite.flip_x = rng.chance(0.5);
                    if !kind.upright {
                        sprite.color = Color::srgba(1.0, 1.0, 1.0, rng.range_f32(0.55, 0.9));
                    }
                    let z =
                        if kind.upright { sort_z(layer::ACTORS, y) } else { layer::GROUND + rng.next_f32() };
                    let scale = if kind.upright { 1.0 } else { rng.range_f32(0.8, 1.22) };
                    let angle = if kind.upright { 0.0 } else { rng.range_f32(-0.28, 0.28) };
                    let mut e = commands.spawn((
                        sprite,
                        anchor,
                        Transform::from_xyz(x, -y, z)
                            .with_scale(Vec3::new(scale, scale, 1.0))
                            .with_rotation(Quat::from_rotation_z(angle)),
                    ));
                    if kind.upright {
                        e.insert(GroundFoot(foot_radius(&db, frame)));
                    }
                    if let Some(light) = kind.light {
                        e.insert(light);
                    }
                    entities.push(e.id());
                }
            }
            decor.chunks.insert(c, entities);
        }
    }
}

/// 一局结束时清掉所有块。
pub(crate) fn clear_decor(mut commands: Commands, mut decor: ResMut<Decor>) {
    for (_, entities) in decor.chunks.drain() {
        for e in entities {
            commands.entity(e).despawn();
        }
    }
}

/// 青丘只有一处狐祠庭院。位置独立派生，不随载入块的顺序或窗口尺寸改变。
fn shrine_center(seed: u64) -> Vec2 {
    let mut rng = Pcg32::new(seed ^ 0x7169_6e67_7169_7500, 12);
    let side = if rng.chance(0.5) { -1.0 } else { 1.0 };
    Vec2::new(side * rng.range_f32(210.0, 235.0), rng.range_f32(-105.0, -75.0))
}

/// 庭院正殿；檐下挂留灯（docs/DESIGN.md 第 15 节“挂着的道具”）。
const SHRINE: &str = "fox_shrine_grand/idle_S_00";
const EAVE_LAMP: [&str; 2] = ["fox_eave_lamp", "fox_eave_lamp_lit"];

/// 正殿檐下的留灯。主角在狐村留过灯（存档或本局）就点着。
#[derive(Component)]
pub(crate) struct EaveLamp {
    lit: bool,
}

#[derive(Debug, PartialEq)]
struct ShrinePiece {
    asset: &'static str,
    pos: Vec2,
    scale: f32,
    flip: bool,
    upright: bool,
    angle: f32,
    opacity: f32,
}

/// 正殿（大狐仙祠，按原尺寸画，不放大）坐北，石牌坊立在中轴前方，成对石狐守住入口，
/// 林下土色连接建筑与庭院，风吹积叶聚在两侧；中轴保留清晰的可走空地。
fn shrine_layout(seed: u64) -> Vec<ShrinePiece> {
    let center = shrine_center(seed);
    let mut pieces = Vec::new();
    let mut put = |asset, x, y, scale, flip, upright| {
        pieces.push(ShrinePiece {
            asset,
            pos: center + Vec2::new(x, y),
            scale,
            flip,
            upright,
            angle: 0.0,
            opacity: 1.0,
        })
    };
    put(SHRINE, 0.0, 0.0, 1.0, false, true);
    put("fox_gate/idle_S_00", 0.0, 95.0, 1.0, false, true);
    put("stone_fox/idle_S_00", -65.0, 40.0, 1.25, false, true);
    put("stone_fox/idle_S_00", 65.0, 40.0, 1.25, true, true);
    put("fox_lanterns/idle_S_00", -103.0, 5.0, 1.25, false, true);
    put("rock_b/idle_S_00", 112.0, -20.0, 1.5, true, true);
    put("ground/bamboo_0", -123.0, -32.0, 1.6, false, true);
    put("ground/bamboo_1", 133.0, -42.0, 1.8, true, true);
    // 宽而淡的积墨把正殿、石狐与小径接到同一块土地上；不围闭、不画假台阶。
    for (asset, x, y, scale, opacity) in [
        ("ground/qq_wash_0", -72.0, 13.0, 1.65, 0.85),
        ("ground/wash_2", 80.0, 24.0, 1.7, 0.62),
        ("ground/qq_wash_1", -72.0, 126.0, 1.55, 0.72),
        ("ground/qq_wash_0", 66.0, 186.0, 1.8, 0.65),
    ] {
        pieces.push(ShrinePiece {
            asset,
            pos: center + Vec2::new(x, y),
            scale,
            flip: x > 0.0,
            upright: false,
            angle: 0.0,
            opacity,
        });
    }
    let mut rng = Pcg32::new(seed ^ 0x666f_7873_6872_696e, 12);
    // 一侧浓、一侧疏的积叶代替等距双排石子。苔点依附石狐与灯架，中央不堆装饰。
    for (x, y, count) in [(-72.0, 48.0, 3), (70.0, 78.0, 2), (-62.0, 132.0, 3), (66.0, 186.0, 2)] {
        for asset in ["ground/qq_bamboo_leaves_0", "ground/qq_bamboo_leaves_2", "ground/qq_moss_0"]
            .into_iter()
            .take(count)
        {
            pieces.push(ShrinePiece {
                asset,
                pos: center + Vec2::new(x + rng.range_f32(-18.0, 18.0), y + rng.range_f32(-17.0, 17.0)),
                scale: rng.range_f32(0.8, 1.25),
                flip: rng.chance(0.5),
                upright: false,
                angle: rng.range_f32(-0.35, 0.35),
                opacity: rng.range_f32(0.48, 0.72),
            });
        }
    }
    for (x, y, angle) in [(12.0, 151.0, 1.15), (-7.0, 82.0, 1.45)] {
        pieces.push(ShrinePiece {
            asset: "ground/qq_fox_tracks",
            pos: center + Vec2::new(x, y),
            scale: 0.8,
            flip: false,
            upright: false,
            angle,
            opacity: 0.46,
        });
    }
    pieces
}

/// 清出整个庭院及引导小径，边缘再慢慢恢复散点，避免块边界留下密度接缝。
fn decor_density(at: Vec2, seed: u64) -> f32 {
    let p = at - (shrine_center(seed) + Vec2::new(0.0, 60.0));
    let d = (p / Vec2::new(195.0, 250.0)).length();
    ((d - 1.0) / 0.35).clamp(0.0, 1.0)
}

/// 仅大型正殿和牌坊需要退让；记录实际画面中的实心部位，不把门洞当作遮挡。
#[derive(Component)]
pub(crate) struct PropOcclusion {
    parts: Vec<Rect>,
    alpha: f32,
}

fn prop_occlusion(db: &AtlasDb, frame: FrameId, asset: &str) -> Option<PropOcclusion> {
    let parts = match asset {
        SHRINE => vec![Rect::new(0.04, 0.03, 0.96, 0.58), Rect::new(0.08, 0.58, 0.92, 0.94)],
        "fox_gate/idle_S_00" => vec![
            Rect::new(0.05, 0.7, 0.95, 0.94),
            Rect::new(0.02, 0.02, 0.2, 0.74),
            Rect::new(0.8, 0.02, 0.98, 0.74),
        ],
        _ => return None,
    };
    let frame = db.frame(frame);
    let origin = (-Vec2::splat(0.5) - frame.anchor.0) * frame.size;
    Some(PropOcclusion {
        parts: parts
            .into_iter()
            .map(|p| Rect::from_corners(origin + p.min * frame.size, origin + p.max * frame.size))
            .collect(),
        alpha: 1.0,
    })
}

fn occlusion_alpha(body: Rect, hero_z: f32, prop: &PropOcclusion, tf: &Transform) -> f32 {
    // 人在景物前面时已有正确的脚底排序，不能因为靠近建筑就让它变淡。
    if tf.translation.z <= hero_z {
        return 1.0;
    }
    let mut cover = 0.0_f32;
    for part in &prop.parts {
        let bounds = Rect::from_corners(
            tf.transform_point(part.min.extend(0.0)).truncate(),
            tf.transform_point(part.max.extend(0.0)).truncate(),
        );
        let overlap = body.max.min(bounds.max) - body.min.max(bounds.min);
        if overlap.min_element() > 0.0 {
            cover = cover.max((overlap.x / 10.0).min(overlap.y / 16.0).clamp(0.0, 1.0));
        }
    }
    // 进入轮廓时逐渐让出上身；仍保留浅淡屋形，避免建筑凭空消失。
    1.0 - 0.84 * cover * cover * (3.0 - 2.0 * cover)
}

pub(crate) fn update_prop_occlusion(
    time: Res<Time>,
    hero: Single<(&Transform, &Sprite, &Anchor), With<Player>>,
    mut props: Query<(&Transform, &mut Sprite, &mut PropOcclusion), Without<Player>>,
) {
    let (tf, sprite, anchor) = *hero;
    let size = sprite.custom_size.unwrap_or(Vec2::new(32.0, 54.0));
    let origin = (-Vec2::splat(0.5) - anchor.0) * size;
    // 保护当前动画的躯干与头部，裁掉武器伸出的边缘和脚底；闪避动画也使用这一帧尺寸。
    let body = Rect::from_corners(
        tf.transform_point((origin + size * Vec2::new(0.23, 0.18)).extend(0.0)).truncate(),
        tf.transform_point((origin + size * Vec2::new(0.77, 0.96)).extend(0.0)).truncate(),
    );
    for (prop_tf, mut sprite, mut prop) in &mut props {
        let target = occlusion_alpha(body, tf.translation.z, &prop, prop_tf);
        let speed = if target < prop.alpha { 24.0 } else { 7.0 };
        prop.alpha += (target - prop.alpha) * (1.0 - (-speed * time.delta_secs()).exp());
        sprite.color.set_alpha(prop.alpha);
    }
}

#[derive(Component)]
pub(crate) struct GroundFoot(f32);

fn foot_radius(db: &AtlasDb, frame: FrameId) -> f32 {
    (db.frame(frame).size.x * 0.3).clamp(5.0, 24.0)
}

pub(crate) fn spawn_shrine(mut commands: Commands, setup: Res<RunSetup>, db: Res<AtlasDb>) {
    for p in shrine_layout(setup.seed) {
        let Some(frame) = db.find(p.asset) else { continue };
        if p.asset == SHRINE {
            spawn_eave_lamp(&mut commands, &db, &p);
        }
        let (mut sprite, anchor) = db.sprite(frame);
        sprite.flip_x = p.flip;
        sprite.color = Color::WHITE.with_alpha(p.opacity);
        let z = if p.upright {
            sort_z(layer::ACTORS, p.pos.y)
        } else if p.asset.contains("wash_") {
            layer::GROUND - 1.5
        } else {
            layer::GROUND + 0.1
        };
        let mut e = commands.spawn((
            sprite,
            anchor,
            Transform::from_xyz(p.pos.x, -p.pos.y, z)
                .with_scale(Vec3::new(p.scale, p.scale, 1.0))
                .with_rotation(Quat::from_rotation_z(p.angle)),
            DespawnOnExit(AppState::Run),
        ));
        if let Some(occlusion) = prop_occlusion(&db, frame, p.asset) {
            e.insert(occlusion);
        }
        // 牌坊是两根柱子，中间是过道，不在中点压一团影子。
        if p.upright && !p.asset.starts_with("fox_gate/") {
            e.insert(GroundFoot(foot_radius(&db, frame) * p.scale));
        }
        if let Some(asset) = p.asset.split('/').next()
            && let Some(kind) = glowing_prop(&db, asset, 0.0)
            && let Some(light) = kind.light
        {
            e.insert(light);
        }
    }
}

/// 留灯挂在宿主的 eave_lamp 挂点：同一排序深度、画在宿主之上、缩放跟宿主一致，不落地、没有影子。
fn spawn_eave_lamp(commands: &mut Commands, db: &AtlasDb, host: &ShrinePiece) {
    let (Some(hook), Some(frame)) =
        (socket(db, "fox_shrine_grand", "eave_lamp"), db.find(&format!("{}/idle_S_00", EAVE_LAMP[0])))
    else {
        return;
    };
    let (sprite, anchor) = db.sprite(frame);
    let at = Vec2::new(host.pos.x, -host.pos.y) + hook * host.scale;
    commands.spawn((
        EaveLamp { lit: false },
        sprite,
        anchor,
        Transform::from_xyz(at.x, at.y, sort_z(layer::ACTORS, host.pos.y) + 0.001)
            .with_scale(Vec3::new(host.scale, host.scale, 1.0)),
        DespawnOnExit(AppState::Run),
    ));
}

/// 灯火放在点着那张的 flame 挂点，光色、光半径取 meta。
fn eave_lamp_light(db: &AtlasDb) -> Option<PropLight> {
    let asset = EAVE_LAMP[1];
    let meta = db.assets.get(asset)?;
    Some(PropLight {
        offset: socket(db, asset, "flame").unwrap_or(Vec2::new(0.0, -8.0)),
        color: crate::fx::hex(meta.light_color.as_deref()?).with_alpha(0.85),
        radius: meta.light_radius_units.unwrap_or(50.0),
        emit: db.find(&format!("{asset}/idle_S_00_emit")),
    })
}

/// 留过灯就换成点着的那张（同画布、同锚点，直接换图）。
pub(crate) fn update_eave_lamp(
    mut commands: Commands,
    db: Res<AtlasDb>,
    story: Option<Res<lantern_sim::story::Story>>,
    mut q: Query<(Entity, &mut EaveLamp, &mut Sprite)>,
) {
    let lit = story.is_some_and(|s| s.has(lantern_content::StoryBeat::LeftLantern));
    for (e, mut lamp, mut sprite) in &mut q {
        if lamp.lit == lit {
            continue;
        }
        let Some(frame) = db.find(&format!("{}/idle_S_00", EAVE_LAMP[usize::from(lit)])) else { continue };
        lamp.lit = lit;
        let flip = sprite.flip_x;
        *sprite = db.sprite(frame).0;
        sprite.flip_x = flip;
        match eave_lamp_light(&db).filter(|_| lit) {
            Some(light) => commands.entity(e).insert(light),
            None => commands.entity(e).remove::<PropLight>(),
        };
    }
}

/// 地标与散景共用角色的影子纹理和精灵池；离屏时不提交绘制请求。
pub(crate) fn ground_shadows(
    db: Res<AtlasDb>,
    frames: Res<crate::actors::ActorFrames>,
    lights: Res<crate::lighting::SceneLights>,
    camera: Single<(&Transform, &Projection), With<MainCamera>>,
    q: Query<(&GroundFoot, &Transform)>,
    mut pools: ResMut<crate::actors::Pools>,
) {
    let (cam, proj) = *camera;
    let half = match proj {
        Projection::Orthographic(o) => o.area.half_size(),
        _ => Vec2::splat(500.0),
    } + Vec2::splat(100.0);
    for (foot, tf) in &q {
        let at = tf.translation.truncate();
        if (at - cam.translation.truncate()).abs().cmpgt(half).any() {
            continue;
        }
        let (offset, stretch) = crate::lighting::contact_shadow(at, lights.dominant(at), foot.0);
        pools.fx.push(crate::actors::Draw {
            scale: stretch * (foot.0 * 2.0 / db.frame(frames.shadow).size.x),
            color: Color::WHITE.with_alpha(0.55),
            ..crate::actors::Draw::new(frames.shadow, (at + offset).extend(layer::SHADOW))
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shrine_is_unique_reproducible_and_clear_of_spawn() {
        for seed in [0, 1, 3, u64::MAX] {
            let a = shrine_layout(seed);
            assert_eq!(a, shrine_layout(seed));
            assert_eq!(a.iter().filter(|p| p.asset.starts_with("fox_shrine")).count(), 1);
            assert_eq!(a.iter().filter(|p| p.asset == SHRINE).count(), 1);
            assert!(a.iter().filter(|p| p.upright).all(|p| p.pos.length() > 100.0));
            let center = shrine_center(seed);
            assert_eq!(decor_density(center, seed), 0.0);
            assert_eq!(decor_density(center + Vec2::new(0.0, 190.0), seed), 0.0);
            assert_eq!(decor_density(center + Vec2::splat(600.0), seed), 1.0);
        }
        assert_ne!(shrine_layout(1), shrine_layout(2));
    }

    #[test]
    fn props_only_yield_when_they_occlude_the_hero() {
        let prop = PropOcclusion { parts: vec![Rect::new(-40.0, 0.0, 40.0, 90.0)], alpha: 1.0 };
        let tf = Transform::from_xyz(0.0, 0.0, 100.0);
        let body = Rect::new(-8.0, 18.0, 8.0, 54.0);
        assert!(occlusion_alpha(body, 99.0, &prop, &tf) < 0.2);
        assert_eq!(occlusion_alpha(body, 101.0, &prop, &tf), 1.0);
        assert_eq!(occlusion_alpha(Rect::new(55.0, 18.0, 71.0, 54.0), 99.0, &prop, &tf), 1.0);
    }

    #[test]
    fn gate_opening_does_not_trigger_a_fade() {
        let prop = PropOcclusion {
            parts: vec![
                Rect::new(-40.0, 56.0, 40.0, 74.0),
                Rect::new(-40.0, 0.0, -27.0, 56.0),
                Rect::new(27.0, 0.0, 40.0, 56.0),
            ],
            alpha: 1.0,
        };
        let tf = Transform::from_xyz(0.0, 0.0, 100.0);
        assert_eq!(occlusion_alpha(Rect::new(-8.0, 12.0, 8.0, 50.0), 99.0, &prop, &tf), 1.0);
        assert!(occlusion_alpha(Rect::new(-8.0, 48.0, 8.0, 85.0), 99.0, &prop, &tf) < 0.2);
    }

    #[test]
    fn chunk_random_is_independent_of_visit_order() {
        let sample = |c| {
            let mut rng = chunk_rng(3, c);
            [rng.next_f32(), rng.next_f32()]
        };
        let a = IVec2::new(-1, 2);
        let first = sample(a);
        let _ = sample(IVec2::new(7, -5));
        assert_eq!(first, sample(a));
    }
}
