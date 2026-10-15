//! 地面：宣纸平铺和散落的装饰（草、墨晕、落叶、石子、芦苇、竹、山石、石灯笼，青丘的竹叶、苔点、狐灯……）。
//!
//! 世界按 512 单位分块，每块的装饰由“本局种子 + 块坐标”决定，同一个种子每次看到的地面一样。
//! 这是纯画面的随机，不消耗模拟的随机流。只保留镜头附近的块。

use std::collections::HashMap;

use bevy::prelude::*;

use lantern_core::Pcg32;
use lantern_sim::{AppState, RunSetup};

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
        flat(&["ground/wash_0", "ground/wash_1", "ground/wash_2"], 0.8),
        flat(&["ground/qq_wash_0", "ground/qq_wash_1"], 1.0),
        flat(&["ground/leaves_0", "ground/leaves_1", "ground/pebbles_0", "ground/pebbles_1"], 1.5),
        flat(&["ground/qq_bamboo_leaves_0", "ground/qq_bamboo_leaves_1", "ground/qq_bamboo_leaves_2"], 4.0),
        flat(&["ground/qq_moss_0", "ground/qq_moss_1"], 2.0),
        flat(&["ground/qq_fox_tracks"], 0.4),
        upright(&["ground/reed_0", "ground/reed_1", "ground/reed_2"], 0.6),
        upright(&["ground/bamboo_0", "ground/bamboo_1"], 1.2),
        upright(&["ground/qq_shoots_0", "ground/qq_shoots_1"], 1.0),
        upright(&["stone_fox/idle_S_00"], 0.2),
    ];
    kinds.extend(glowing_prop(&db, "fox_shrine", 0.1));
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
        chunks: HashMap::new(),
    });
}

fn chunk_rng(seed: u64, c: IVec2) -> Pcg32 {
    let key = (c.x as u32 as u64) << 32 | c.y as u32 as u64;
    Pcg32::new(seed ^ key.wrapping_mul(0x9E37_79B9_7F4A_7C15), 0x006c_616e_7465_726e)
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
            for kind in &decor.kinds {
                let n = (kind.per_chunk + rng.next_f32()) as u32;
                for _ in 0..n {
                    // 模拟坐标（y 向下）
                    let x = (cx as f32 + rng.next_f32()) * CHUNK;
                    let y = (cy as f32 + rng.next_f32()) * CHUNK;
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
                    let mut e = commands.spawn((sprite, anchor, Transform::from_xyz(x, -y, z)));
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
