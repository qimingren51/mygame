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
mod feedback;
mod foreground;
mod fx;
mod ground;
mod hero_feedback;
mod impact;
pub mod lighting;
mod mist;
/// 统一色板（和美术 style.py 的 RUNTIME_COLORS 对齐，docs/STYLE_GUIDE.md）；质感会话接入后逐步替换各处写死的颜色
mod palette;
mod particles;
pub mod smoke;
mod stats;
mod telegraphs;

use atlas::AtlasDb;
pub use atmos::{DAWN_LEN, Dawn};
pub use camera::{Feel, NumberMode};
pub use stats::ViewStats;

/// 图层的 z 基数（从下到上）。同一图层内再按脚底 y 微调。
pub mod layer {
    pub const PAPER: f32 = 0.0;
    /// 地面装饰占 GROUND .. GROUND + 1
    pub const GROUND: f32 = 10.0;
    /// 接触阴影在地面笔触与危险填充之下，不能压暗预警。
    pub const SHADOW: f32 = 9.0;
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
    /// 近景墨竹盖过场景与薄雾，但在法术和危险描边之下。
    pub const FOREGROUND: f32 = 205.0;
    pub const DANGER: f32 = 240.0;
    pub const NUMBERS: f32 = 300.0;
}

/// 夜色，也是画面清屏色（和光照图的底色同值）。
pub const NIGHT: Color = palette::NIGHT_AMBIENT;

pub struct ViewPlugin {
    /// 资源根目录（图集 JSON 在 `<asset_root>/atlas/`）
    pub asset_root: PathBuf,
}

/// 启动时确定的绝对资源根目录，供图集和界面皮肤共用。
#[derive(Resource)]
pub struct AssetRoot(pub PathBuf);

/// 局内单独使用的贴图，在标题期间保留并预载。
#[derive(Resource)]
pub struct SceneAssets {
    pub paper: Handle<Image>,
}

impl Plugin for ViewPlugin {
    fn build(&self, app: &mut App) {
        app.add_plugins((lighting::LightingPlugin, hero_feedback::HeroFeedbackPlugin))
            .insert_resource(ClearColor(NIGHT))
            .insert_resource(AssetRoot(self.asset_root.clone()))
            .init_resource::<actors::Pools>()
            .init_resource::<impact::Impacts>()
            .init_resource::<actors::GlowPool>()
            .init_resource::<actors::GlowRequests>()
            .init_resource::<fx::FxState>()
            .init_resource::<telegraphs::Readability>()
            .init_resource::<camera::Rig>()
            .init_resource::<feedback::Feedback>()
            .init_resource::<actors::LanternFlare>()
            .init_resource::<atmos::Atmos>()
            .init_resource::<Dawn>()
            .init_resource::<particles::ParticleClock>()
            .init_resource::<Feel>()
            .init_resource::<ViewStats>()
            .init_resource::<foreground::Safety>()
            .init_resource::<mist::MistReady>()
            .add_systems(
                Startup,
                (
                    setup_camera,
                    load_atlas,
                    particles::setup_particles.run_if(resource_exists::<AtlasDb>),
                    (
                        actors::build_frames,
                        fx::build_fx_frames,
                        ground::build_decor,
                        effects::setup_effects,
                        lighting::setup_lighting,
                    )
                        .run_if(resource_exists::<AtlasDb>),
                )
                    .chain(),
            )
            .add_systems(
                OnEnter(AppState::Run),
                (
                    ground::spawn_paper,
                    ground::spawn_shrine,
                    foreground::spawn_foreground,
                    effects::spawn_number_pool,
                    fx::spawn_flash,
                    fx::reset_fx,
                    impact::reset,
                    telegraphs::spawn,
                    feedback::reset_feedback,
                    camera::reset_rig,
                    particles::reset_particles,
                    atmos::reset_atmos,
                    atmos::spawn_hurt_arc,
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
                    lighting::reset_scene_lights,
                ),
            )
            .add_systems(
                PostUpdate,
                impact::apply_deform
                    .after(bevy::transform::TransformSystems::Propagate)
                    .before(bevy::camera::visibility::VisibilitySystems::CheckVisibility),
            )
            .add_observer(actors::dress_player)
            .add_systems(Update, (lighting::resize_lightmap, apply_bloom, mist::setup_mist))
            .add_systems(
                Update,
                (
                    // 镜头先定下来，后面的绘制都按这一帧的镜头算
                    (
                        stats::begin,
                        feedback::prepare_feedback,
                        interpolate,
                        actors::animate_hero,
                        camera::advance_rig_time,
                        lighting::update_scene_lights,
                        actors::update_hero_shadow,
                        camera::camera_events,
                        camera::update_rig,
                        camera::follow_main_camera,
                    )
                        .chain(),
                    (
                        impact::read_events,
                        telegraphs::update_readability,
                        actors::collect_draws,
                        impact::draw_deaths,
                        fx::read_fx_events,
                        fx::apply_flash,
                        fx::collect_fx,
                        actors::hero_glow,
                        hero_feedback::draw,
                        effects::read_events,
                        effects::update_effects,
                    )
                        .chain(),
                    (
                        particles::particle_events,
                        (atmos::atmos_events, atmos::draw_hurt_arc, atmos::update_atmos).chain(),
                        mist::update_mist,
                        particles::update_particles,
                        telegraphs::draw,
                        (
                            ground::scroll_paper,
                            ground::update_decor,
                            ground::update_eave_lamp,
                            ground::ground_shadows,
                            foreground::update_foreground,
                            actors::apply_pools,
                            actors::apply_glow,
                            lighting::apply_surface_lights,
                            stats::end,
                        )
                            .chain(),
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

/// 读图集。失败时交给主程序的 panic hook 记录日志并提示玩家，停止后续初始化。
fn load_atlas(
    mut commands: Commands,
    root: Res<AssetRoot>,
    assets: Res<AssetServer>,
    mut layouts: ResMut<Assets<TextureAtlasLayout>>,
) {
    commands.insert_resource(SceneAssets { paper: assets.load("atlas/paper.png") });
    match AtlasDb::load(&root.0, &assets, &mut layouts) {
        Ok(db) => commands.insert_resource(db),
        Err(e) => {
            // AppExit 要到帧末才生效，继续运行会让依赖图集的系统因缺少资源而再次出错。
            panic!("图集加载失败（{}）：{e}", root.0.display());
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn atlas_failure_stops_startup_with_the_path() {
        #[derive(Resource, Default)]
        struct AfterAtlas(bool);

        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("提灯 图集测试-{}-{now}", std::process::id()));
        std::fs::create_dir_all(root.join("atlas")).unwrap();

        // 缺清单、坏清单、缺页、坏页都必须提供原始错误并停止初始化链。
        for (index, page, expected) in [
            (None, None, "读取 atlas/index.json 失败"),
            (Some("{"), None, "atlas/index.json 格式错误"),
            (Some(r#"{"pages":{"actors":["actors.json"]}}"#), None, "读取 atlas/actors.json 失败"),
            (Some(r#"{"pages":{"actors":["actors.json"]}}"#), Some("{"), "atlas/actors.json 格式错误"),
        ] {
            if let Some(index) = index {
                std::fs::write(root.join("atlas/index.json"), index).unwrap();
            }
            if let Some(page) = page {
                std::fs::write(root.join("atlas/actors.json"), page).unwrap();
            }
            let mut app = App::new();
            app.add_plugins((MinimalPlugins, AssetPlugin::default()))
                .init_asset::<Image>()
                .init_resource::<Assets<TextureAtlasLayout>>()
                .init_resource::<AfterAtlas>()
                .insert_resource(AssetRoot(root.clone()))
                .add_systems(
                    Startup,
                    (
                        load_atlas,
                        (|_: Res<AtlasDb>, mut after: ResMut<AfterAtlas>| after.0 = true)
                            .run_if(resource_exists::<AtlasDb>),
                    )
                        .chain(),
                );
            let panic = catch_unwind(AssertUnwindSafe(|| app.update())).unwrap_err();
            let message = panic.downcast::<String>().unwrap();
            assert!(!app.world().contains_resource::<AtlasDb>());
            assert!(!app.world().resource::<AfterAtlas>().0);
            assert!(message.contains(expected), "{message}");
            assert!(message.contains(root.to_str().unwrap()));
        }
        std::fs::remove_dir_all(root).unwrap();
    }
}
