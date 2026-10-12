//! 画面层（docs/DESIGN.md 第 9 节）。只读模拟状态，不改变模拟。
//!
//! M0 只有镜头、宣纸背景和主角占位图形，用来打通“输入 → 模拟 → 插值 → 画面”的整条链路。
//! 图集、光照图、特效在 M1 加入。

use bevy::camera::ScalingMode;
use bevy::prelude::*;

use lantern_sim::{AppState, GameContent, Player, Pos, PrevPos};

/// 图层的 z 基数（从下到上）。同一图层内再按脚底 y 微调。
pub mod layer {
    pub const PAPER: f32 = 0.0;
    pub const ACTORS: f32 = 100.0;
    pub const GLOW: f32 = 300.0;
}

/// 夜色，也是画面清屏色。
pub const NIGHT: Color = Color::srgb(0.086, 0.106, 0.173);
const INK: Color = Color::srgb(0.11, 0.11, 0.13);
const LANTERN: Color = Color::srgba(1.0, 0.72, 0.36, 0.28);

/// 宣纸平铺块的边长（世界单位）。宣纸图 512 像素，1 纹素 = 0.5 世界单位（docs/PORTING-NOTES.md 8.2）。
const PAPER_TILE: f32 = 256.0;
const PAPER_TEXELS_PER_UNIT: f32 = 2.0;

pub struct ViewPlugin;

impl Plugin for ViewPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(ClearColor(NIGHT))
            .add_systems(Startup, setup_camera)
            .add_systems(OnEnter(AppState::Run), spawn_paper)
            .add_observer(dress_player)
            .add_systems(
                Update,
                (interpolate, follow_camera, scroll_paper).chain().run_if(in_state(AppState::Run)),
            );
    }
}

#[derive(Component)]
pub struct MainCamera;

#[derive(Component)]
struct Paper;

fn setup_camera(mut commands: Commands, content: Res<GameContent>) {
    commands.spawn((
        Camera2d,
        MainCamera,
        Projection::Orthographic(OrthographicProjection {
            scaling_mode: ScalingMode::FixedVertical { viewport_height: content.0.run.view_height },
            ..OrthographicProjection::default_2d()
        }),
    ));
}

fn spawn_paper(mut commands: Commands, assets: Res<AssetServer>) {
    commands.spawn((
        Paper,
        DespawnOnExit(AppState::Run),
        Sprite {
            image: assets.load("atlas/paper.png"),
            custom_size: Some(Vec2::splat(PAPER_TILE * 6.0)),
            image_mode: SpriteImageMode::Tiled {
                tile_x: true,
                tile_y: true,
                stretch_value: 1.0 / PAPER_TEXELS_PER_UNIT,
            },
            ..default()
        },
        Transform::from_xyz(0.0, 0.0, layer::PAPER),
    ));
}

/// 模拟里出现主角时，挂上画面组件。M1 换成图集里的 8 方向角色。
fn dress_player(
    add: On<Add<Player>>,
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
    content: Res<GameContent>,
) {
    let r = content.0.player.radius;
    let glow = commands
        .spawn((
            Mesh2d(meshes.add(Circle::new(r * 6.0))),
            MeshMaterial2d(materials.add(LANTERN)),
            // M0 没有光照图，光晕先垫在主角下面；M1 改为画进光照图。
            Transform::from_xyz(0.0, 0.0, -1.0),
        ))
        .id();
    commands
        .entity(add.event().entity)
        .insert((
            Mesh2d(meshes.add(Circle::new(r))),
            MeshMaterial2d(materials.add(INK)),
            Transform::from_xyz(0.0, 0.0, layer::ACTORS),
            Visibility::default(),
        ))
        .add_child(glow);
}

/// 模拟坐标 y 向下，画面 y 向上。
fn to_screen(p: Vec2) -> Vec2 {
    Vec2::new(p.x, -p.y)
}

/// 在上一步和这一步之间插值。
fn interpolate(fixed: Res<Time<Fixed>>, mut q: Query<(&Pos, &PrevPos, &mut Transform)>) {
    let a = fixed.overstep_fraction();
    for (pos, prev, mut tf) in &mut q {
        let p = to_screen(prev.0.lerp(pos.0, a));
        // 按脚底 y 排序：越靠下（越近）越晚画。
        tf.translation = p.extend(layer::ACTORS - p.y * 1e-4);
    }
}

fn follow_camera(
    player: Single<&Transform, (With<Player>, Without<MainCamera>)>,
    mut cam: Single<&mut Transform, With<MainCamera>>,
) {
    cam.translation.x = player.translation.x;
    cam.translation.y = player.translation.y;
}

/// 宣纸跟着镜头按整块平移，看起来是无限平铺。
fn scroll_paper(
    cam: Single<&Transform, (With<MainCamera>, Without<Paper>)>,
    mut paper: Single<&mut Transform, With<Paper>>,
) {
    let snap = |v: f32| (v / PAPER_TILE).round() * PAPER_TILE;
    paper.translation.x = snap(cam.translation.x);
    paper.translation.y = snap(cam.translation.y);
}
