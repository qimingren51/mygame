//! 画面层（docs/DESIGN.md 第 9 节）。只读模拟状态，不改变模拟。
//!
//! 图集、主角与妖物精灵、影子、灯火、魂火、地面装饰、光照图与自发光、伤害数字与墨点。

use std::path::PathBuf;

use bevy::camera::{Hdr, ScalingMode};
use bevy::post_process::bloom::{Bloom, BloomCompositeMode, BloomPrefilter};
use bevy::prelude::*;

use lantern_sim::{AppState, GameContent, Player, Pos, PrevPos};

mod actors;
pub mod atlas;
mod atmos;
mod camera;
mod effects;
mod fx;
mod ground;
pub mod lighting;
mod mist;
mod particles;
mod stats;
mod telegraphs;

use atlas::AtlasDb;
pub use atmos::{DAWN_LEN, Dawn};
pub use camera::Feel;
pub use stats::ViewStats;

/// 图层的 z 基数（从下到上）。同一图层内再按脚底 y 微调。
pub mod layer {
    pub const PAPER: f32 = 0.0;
    /// 地面装饰占 GROUND .. GROUND + 1
    pub const GROUND: f32 = 10.0;
    pub const SHADOW: f32 = 50.0;
    pub const GEMS: f32 = 60.0;
    /// 角色按脚底 y 排序，占 ACTORS ± 1
    pub const ACTORS: f32 = 100.0;
    /// 暗层：以正片叠底盖上光照图
    pub const DARKNESS: f32 = 200.0;
    /// 法器本体（灯火火焰），在暗层之上
    pub const WEAPONS: f32 = 210.0;
    /// 自发光（叠加）：灯笼窗、妖眼、魂火
    pub const EMISSIVE: f32 = 220.0;
    /// 危险轮廓在自发光、战斗粒子之上，伤害数字之下。
    pub const TELEGRAPH: f32 = 260.0;
    pub const NUMBERS: f32 = 300.0;
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
        app.add_plugins(lighting::LightingPlugin)
            .insert_resource(ClearColor(NIGHT))
            .insert_resource(AssetRoot(self.asset_root.clone()))
            .init_resource::<actors::Pools>()
            .init_resource::<actors::GlowPool>()
            .init_resource::<actors::GlowRequests>()
            .init_resource::<fx::FxState>()
            .init_resource::<telegraphs::Readability>()
            .init_resource::<camera::Rig>()
            .init_resource::<actors::LanternFlare>()
            .init_resource::<atmos::Atmos>()
            .init_resource::<Dawn>()
            .init_resource::<particles::ParticleClock>()
            .init_resource::<Feel>()
            .init_resource::<ViewStats>()
            .init_resource::<mist::MistReady>()
            .add_systems(
                Startup,
                (
                    setup_camera,
                    load_atlas,
                    particles::setup_particles,
                    (
                        actors::build_frames,
                        fx::build_fx_frames,
                        ground::build_decor,
                        effects::setup_effects,
                        lighting::setup_lighting,
                    ),
                )
                    .chain(),
            )
            .add_systems(
                OnEnter(AppState::Run),
                (
                    ground::spawn_paper,
                    effects::spawn_number_pool,
                    fx::spawn_flash,
                    fx::reset_fx,
                    telegraphs::spawn,
                    camera::reset_rig,
                    particles::reset_particles,
                    atmos::reset_atmos,
                ),
            )
            .add_systems(
                OnExit(AppState::Run),
                (
                    actors::reset_pools,
                    ground::clear_decor,
                    lighting::hide_darkness,
                    camera::reset_rig,
                    mist::hide_mist,
                ),
            )
            .add_observer(actors::dress_player)
            .add_systems(Update, (lighting::resize_lightmap, apply_bloom, mist::setup_mist))
            .add_systems(
                Update,
                (
                    // 镜头先定下来，后面的绘制都按这一帧的镜头算
                    (
                        stats::begin,
                        interpolate,
                        actors::animate_hero,
                        camera::camera_events,
                        camera::update_rig,
                        camera::follow_main_camera,
                        fx::apply_flash,
                    )
                        .chain(),
                    (
                        telegraphs::update_readability,
                        actors::collect_draws,
                        fx::read_fx_events,
                        fx::collect_fx,
                        actors::hero_glow,
                        effects::read_events,
                        effects::update_effects,
                        particles::particle_events,
                        atmos::atmos_events,
                        atmos::update_atmos,
                        mist::update_mist,
                        particles::update_particles,
                        telegraphs::draw,
                        actors::apply_pools,
                        actors::apply_glow,
                        ground::scroll_paper,
                        ground::update_decor,
                        stats::end,
                    )
                        .chain(),
                )
                    .chain()
                    .run_if(in_state(AppState::Run)),
            );
    }
}

#[derive(Component)]
pub struct MainCamera;

/// 辉光：只让比较亮的东西（灯火、法术、自发光）往外晕开，纸面和墨色不受影响。
fn bloom() -> Bloom {
    Bloom {
        intensity: atmos::BLOOM_BASE,
        low_frequency_boost: 0.5,
        low_frequency_boost_curvature: 0.9,
        high_pass_frequency: 1.0,
        prefilter: BloomPrefilter { threshold: 1.0, threshold_softness: 0.25 },
        composite_mode: BloomCompositeMode::Additive,
        ..Bloom::NATURAL
    }
}

/// 设置里的辉光开关。
fn apply_bloom(mut commands: Commands, feel: Res<Feel>, cam: Single<(Entity, Has<Bloom>), With<MainCamera>>) {
    let (e, has) = *cam;
    if feel.bloom && !has {
        commands.entity(e).insert(bloom());
    } else if !feel.bloom && has {
        commands.entity(e).remove::<Bloom>();
    }
}

fn setup_camera(mut commands: Commands, content: Res<GameContent>) {
    commands.spawn((
        Camera2d,
        MainCamera,
        Hdr,
        atmos::base_vignette(),
        bevy::post_process::effect_stack::ChromaticAberration { intensity: 0.0, ..default() },
        IsDefaultUiCamera,
        bevy::core_pipeline::tonemapping::Tonemapping::None,
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
pub fn to_screen(p: Vec2) -> Vec2 {
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
