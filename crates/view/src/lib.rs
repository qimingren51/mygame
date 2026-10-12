//! 画面层（docs/DESIGN.md 第 9 节）。只读模拟状态，不改变模拟。
//!
//! M1-3：图集、主角与妖物精灵、影子、灯火、魂火、地面装饰。光照图、自发光层、伤害数字在 M1-4 加入。

use std::path::PathBuf;

use bevy::camera::ScalingMode;
use bevy::prelude::*;

use lantern_sim::{AppState, GameContent, Player, Pos, PrevPos};

mod actors;
pub mod atlas;
mod ground;

use atlas::AtlasDb;

/// 图层的 z 基数（从下到上）。同一图层内再按脚底 y 微调。
pub mod layer {
    pub const PAPER: f32 = 0.0;
    /// 地面装饰占 GROUND .. GROUND + 1
    pub const GROUND: f32 = 10.0;
    pub const SHADOW: f32 = 50.0;
    pub const GEMS: f32 = 60.0;
    /// 角色按脚底 y 排序，占 ACTORS ± 1
    pub const ACTORS: f32 = 100.0;
}

/// 夜色，也是画面清屏色。
pub const NIGHT: Color = Color::srgb(0.086, 0.106, 0.173);

pub struct ViewPlugin {
    /// 资源根目录（图集 JSON 在 `<asset_root>/atlas/`）
    pub asset_root: PathBuf,
}

#[derive(Resource)]
struct AssetRoot(PathBuf);

impl Plugin for ViewPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(ClearColor(NIGHT))
            .insert_resource(AssetRoot(self.asset_root.clone()))
            .init_resource::<actors::Pools>()
            .add_systems(
                Startup,
                (setup_camera, load_atlas, (actors::build_frames, ground::build_decor)).chain(),
            )
            .add_systems(OnEnter(AppState::Run), ground::spawn_paper)
            .add_systems(OnExit(AppState::Run), (actors::reset_pools, ground::clear_decor))
            .add_observer(actors::dress_player)
            .add_systems(
                Update,
                (
                    interpolate,
                    actors::animate_hero,
                    follow_camera,
                    actors::collect_draws,
                    actors::apply_pools,
                    ground::scroll_paper,
                    ground::update_decor,
                )
                    .chain()
                    .run_if(in_state(AppState::Run)),
            );
    }
}

#[derive(Component)]
pub struct MainCamera;

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

/// 读图集。失败时没法画任何东西，直接报错退出。
fn load_atlas(
    mut commands: Commands,
    root: Res<AssetRoot>,
    assets: Res<AssetServer>,
    mut layouts: ResMut<Assets<TextureAtlasLayout>>,
    mut exit: MessageWriter<AppExit>,
) {
    match AtlasDb::load(&root.0, &assets, &mut layouts) {
        Ok(db) => commands.insert_resource(db),
        Err(e) => {
            error!("图集加载失败：{e}");
            exit.write(AppExit::error());
        }
    }
}

/// 模拟坐标 y 向下，画面 y 向上。
pub(crate) fn to_screen(p: Vec2) -> Vec2 {
    Vec2::new(p.x, -p.y)
}

/// 主角在上一步和这一步之间插值。
fn interpolate(fixed: Res<Time<Fixed>>, mut q: Query<(&Pos, &PrevPos, &mut Transform), With<Player>>) {
    let a = fixed.overstep_fraction();
    for (pos, prev, mut tf) in &mut q {
        let p = prev.0.lerp(pos.0, a);
        let s = to_screen(p);
        tf.translation = Vec3::new(s.x, s.y, actors::sort_z(layer::ACTORS, p.y));
    }
}

fn follow_camera(
    player: Single<&Transform, (With<Player>, Without<MainCamera>)>,
    mut cam: Single<&mut Transform, With<MainCamera>>,
) {
    cam.translation.x = player.translation.x;
    cam.translation.y = player.translation.y;
}
