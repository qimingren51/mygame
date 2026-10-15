//! 光照：“灯照见画”（docs/DESIGN.md 第 9.2 节，参数见 docs/PORTING-NOTES.md 第 7 节）。
//!
//! - 光照相机把所有光源（径向渐变贴图，叠加混合）画进一张低分辨率的图，底色是夜色。
//! - 主画面上盖一张全屏四边形，以正片叠底乘上这张图：照到的地方显出原画，其余只剩夜色。
//! - 自发光层（主角灯笼窗、妖眼、魂火）画在暗层之上，暗处也看得见。
//!
//! Bevy 的精灵只有普通混合，这里用 `ExtendedMaterial2d<ColorMaterial, 混合扩展>`：着色器沿用
//! Bevy 自带的，扩展只改渲染管线的混合方式。每一帧图集做成一个带对应纹理坐标的四边形网格，
//! 同一页贴图、同一种颜色的共用一个材质，可以合批。

use std::collections::HashMap;

use bevy::asset::{RenderAssetUsages, embedded_asset};
use bevy::camera::visibility::RenderLayers;
use bevy::camera::{RenderTarget, ScalingMode};
use bevy::core_pipeline::tonemapping::Tonemapping;
use bevy::material::descriptor::RenderPipelineDescriptor;
use bevy::material::specialize::SpecializedMeshPipelineError;
use bevy::mesh::{Indices, MeshVertexBufferLayoutRef, PrimitiveTopology};
use bevy::prelude::*;
use bevy::render::render_resource::{
    AsBindGroup, BlendComponent, BlendFactor, BlendOperation, BlendState, ShaderType, TextureFormat,
};
use bevy::shader::ShaderRef;
use bevy::sprite_render::{
    AlphaMode2d, ExtendedMaterial2d, Material2d, Material2dKey, Material2dPipeline, Material2dPlugin,
    MaterialExtension2d,
};
use bevy::window::{PrimaryWindow, WindowResized};

use crate::atlas::{AtlasDb, FrameId};

/// 光照相机画的图层
pub const LIGHT_LAYER: usize = 1;

/// 光照图的分辨率相对窗口的比例
const LIGHTMAP_SCALE: f32 = 0.5;

/// 自发光的亮度倍数（主画面是 HDR）。超过 1 的部分由辉光晕开。
pub const EMIT_HDR: f32 = 1.5;

/// 夜色：没有光照到的地方乘以它
pub const NIGHT_AMBIENT: Color = Color::srgb(0.086, 0.106, 0.173);

// ---------------------------------------------------------------------------
// 混合方式扩展
// ---------------------------------------------------------------------------

fn set_blend(descriptor: &mut RenderPipelineDescriptor, blend: BlendState) {
    if let Some(fragment) = &mut descriptor.fragment {
        for target in fragment.targets.iter_mut().flatten() {
            target.blend = Some(blend);
        }
    }
}

/// 叠加：结果 = 底色 + 颜色 × alpha
#[derive(AsBindGroup, TypePath, Clone, Debug, Default)]
pub struct Additive {}

impl MaterialExtension2d for Additive {
    fn specialize(
        _pipeline: &Material2dPipeline,
        descriptor: &mut RenderPipelineDescriptor,
        _layout: &MeshVertexBufferLayoutRef,
        _key: Material2dKey<Self>,
    ) -> Result<(), SpecializedMeshPipelineError> {
        let add = BlendComponent {
            src_factor: BlendFactor::SrcAlpha,
            dst_factor: BlendFactor::One,
            operation: BlendOperation::Add,
        };
        let keep = BlendComponent {
            src_factor: BlendFactor::Zero,
            dst_factor: BlendFactor::One,
            operation: BlendOperation::Add,
        };
        set_blend(descriptor, BlendState { color: add, alpha: keep });
        Ok(())
    }
}

/// 正片叠底：结果 = 底色 × 颜色
#[derive(AsBindGroup, TypePath, Clone, Debug, Default)]
pub struct Multiply {}

impl MaterialExtension2d for Multiply {
    fn specialize(
        _pipeline: &Material2dPipeline,
        descriptor: &mut RenderPipelineDescriptor,
        _layout: &MeshVertexBufferLayoutRef,
        _key: Material2dKey<Self>,
    ) -> Result<(), SpecializedMeshPipelineError> {
        let mul = BlendComponent {
            src_factor: BlendFactor::Dst,
            dst_factor: BlendFactor::Zero,
            operation: BlendOperation::Add,
        };
        let keep = BlendComponent {
            src_factor: BlendFactor::Zero,
            dst_factor: BlendFactor::One,
            operation: BlendOperation::Add,
        };
        set_blend(descriptor, BlendState { color: mul, alpha: keep });
        Ok(())
    }
}

pub type AddMaterial = ExtendedMaterial2d<ColorMaterial, Additive>;
pub type MulMaterial = ExtendedMaterial2d<ColorMaterial, Multiply>;

// ---------------------------------------------------------------------------
// 每帧一个网格、每种颜色一个材质的缓存
// ---------------------------------------------------------------------------

/// 图集帧做成的四边形网格（锚点在原点），以及叠加材质。
#[derive(Resource, Default)]
pub struct FrameMeshes {
    meshes: HashMap<(FrameId, bool), Handle<Mesh>>,
    materials: HashMap<(usize, [u8; 4], bool), Handle<AddMaterial>>,
}

fn quad_mesh(db: &AtlasDb, id: FrameId, flip: bool) -> Mesh {
    let f = db.frame(id);
    let (w, h) = (f.size.x, f.size.y);
    let a = f.anchor.0;
    let (x0, x1) = ((-0.5 - a.x) * w, (0.5 - a.x) * w);
    let (y0, y1) = ((-0.5 - a.y) * h, (0.5 - a.y) * h);
    let (mut u0, mut u1) = (f.uv.min.x, f.uv.max.x);
    if flip {
        std::mem::swap(&mut u0, &mut u1);
    }
    let (v0, v1) = (f.uv.min.y, f.uv.max.y);
    Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::RENDER_WORLD)
        .with_inserted_attribute(
            Mesh::ATTRIBUTE_POSITION,
            vec![[x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0]],
        )
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, vec![[0.0, 0.0, 1.0]; 4])
        .with_inserted_attribute(Mesh::ATTRIBUTE_UV_0, vec![[u0, v1], [u1, v1], [u1, v0], [u0, v0]])
        .with_inserted_indices(Indices::U32(vec![0, 1, 2, 0, 2, 3]))
}

impl FrameMeshes {
    pub fn mesh(&mut self, db: &AtlasDb, meshes: &mut Assets<Mesh>, id: FrameId, flip: bool) -> Handle<Mesh> {
        self.meshes.entry((id, flip)).or_insert_with(|| meshes.add(quad_mesh(db, id, flip))).clone()
    }

    /// 叠加材质：同一页贴图、同一种颜色（含强度）共用一个。hdr：画在主画面上的自发光，
    /// 亮度乘 [`EMIT_HDR`]，叠起来能超过 1，辉光才晕得开；画进光照图的光源不乘。
    pub fn additive(
        &mut self,
        db: &AtlasDb,
        materials: &mut Assets<AddMaterial>,
        id: FrameId,
        color: Color,
        hdr: bool,
    ) -> Handle<AddMaterial> {
        let key = (db.page_of(id), color.to_srgba().to_u8_array(), hdr);
        self.materials
            .entry(key)
            .or_insert_with(|| {
                let color = if hdr {
                    let l = color.to_linear();
                    Color::linear_rgba(l.red * EMIT_HDR, l.green * EMIT_HDR, l.blue * EMIT_HDR, l.alpha)
                } else {
                    color
                };
                materials.add(AddMaterial {
                    base: ColorMaterial {
                        color,
                        alpha_mode: AlphaMode2d::Blend,
                        texture: Some(db.image(id)),
                        ..default()
                    },
                    extension: Additive {},
                })
            })
            .clone()
    }
}

// ---------------------------------------------------------------------------
// 光照图、光照相机、暗层
// ---------------------------------------------------------------------------

#[derive(Resource)]
pub struct Lightmap {
    pub image: Handle<Image>,
}

#[derive(Component)]
pub struct LightCamera;

#[derive(Component)]
pub(crate) struct Darkness;

pub struct LightingPlugin;

impl Plugin for LightingPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "surface_light.wesl");
        app.add_plugins((
            Material2dPlugin::<AddMaterial>::default(),
            Material2dPlugin::<MulMaterial>::default(),
            Material2dPlugin::<SurfaceMaterial>::default(),
        ))
        .init_resource::<FrameMeshes>()
        .init_resource::<SceneLights>()
        .init_resource::<SurfaceDraws>();
    }
}

fn lightmap_size(window: &Window) -> UVec2 {
    let size = window.physical_size().as_vec2() * LIGHTMAP_SCALE;
    size.max(Vec2::splat(8.0)).as_uvec2()
}

pub(crate) fn setup_lighting(
    mut commands: Commands,
    window: Single<&Window, With<PrimaryWindow>>,
    content: Res<lantern_sim::GameContent>,
    mut images: ResMut<Assets<Image>>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut mul_materials: ResMut<Assets<MulMaterial>>,
) {
    let size = lightmap_size(&window);
    let image = images.add(Image::new_target_texture(size.x, size.y, TextureFormat::Rgba8UnormSrgb, None));
    commands.spawn((
        Camera2d,
        LightCamera,
        Camera { order: -1, clear_color: ClearColorConfig::Custom(NIGHT_AMBIENT), ..default() },
        RenderTarget::from(image.clone()),
        Tonemapping::None,
        Projection::Orthographic(OrthographicProjection {
            scaling_mode: ScalingMode::FixedVertical { viewport_height: content.0.run.view_height },
            ..OrthographicProjection::default_2d()
        }),
        RenderLayers::layer(LIGHT_LAYER),
    ));
    commands.spawn((
        Darkness,
        Mesh2d(meshes.add(Rectangle::new(1.0, 1.0))),
        MeshMaterial2d(mul_materials.add(MulMaterial {
            base: ColorMaterial {
                color: Color::WHITE,
                alpha_mode: AlphaMode2d::Blend,
                texture: Some(image.clone()),
                ..default()
            },
            extension: Multiply {},
        })),
        Transform::from_xyz(0.0, 0.0, crate::layer::DARKNESS),
        Visibility::Hidden,
    ));
    commands.insert_resource(Lightmap { image });
}

/// 窗口改变大小时，光照图跟着改。
pub(crate) fn resize_lightmap(
    mut resized: MessageReader<WindowResized>,
    window: Single<&Window, With<PrimaryWindow>>,
    lightmap: Res<Lightmap>,
    mut images: ResMut<Assets<Image>>,
) {
    if resized.read().last().is_none() {
        return;
    }
    let size = lightmap_size(&window);
    if let Some(mut image) = images.get_mut(&lightmap.image) {
        image.resize(bevy::render::render_resource::Extent3d {
            width: size.x,
            height: size.y,
            depth_or_array_layers: 1,
        });
    }
}

pub(crate) fn hide_darkness(mut darkness: Single<&mut Visibility, With<Darkness>>) {
    **darkness = Visibility::Hidden;
}

// ---------------------------------------------------------------------------
// 近场受光与接触阴影：只读画面坐标，不向模拟写数据
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
pub(crate) struct LocalLight {
    pub pos: Vec2,
    pub radius: f32,
    pub strength: f32,
    pub color: Vec3,
}

impl LocalLight {
    fn weight(self, at: Vec2) -> f32 {
        let falloff = (1.0 - at.distance_squared(self.pos) / self.radius.max(1.0).powi(2)).max(0.0);
        falloff * falloff * self.strength
    }
}

/// 固定三个主光：手灯、燃灯爆光、最近一团夜主狐火。杂兵只取手灯，避免逐妖遍历光源。
#[derive(Resource, Default)]
pub(crate) struct SceneLights {
    pub sources: [LocalLight; 3],
    burst: f32,
    burst_pos: Vec2,
    burst_radius: f32,
}

impl SceneLights {
    /// 主角、地标和夜主取当前位置最强的主光；普通妖物仍只算手灯。
    pub(crate) fn dominant(&self, at: Vec2) -> LocalLight {
        self.sources.into_iter().max_by(|a, b| a.weight(at).total_cmp(&b.weight(at))).unwrap_or_default()
    }
}

pub(crate) fn update_scene_lights(
    time: Res<Time>,
    fixed: Res<Time<Fixed>>,
    db: Res<AtlasDb>,
    hero: Single<(&Transform, &crate::actors::HeroView), With<lantern_sim::Player>>,
    foes: Option<Res<lantern_sim::boss::Foes>>,
    stats: Option<Res<lantern_sim::Stats>>,
    outbox: Res<lantern_sim::SimOutbox>,
    mut lights: ResMut<SceneLights>,
    mut draws: ResMut<SurfaceDraws>,
) {
    draws.0.clear();
    lights.burst = (lights.burst - time.delta_secs() / 0.55).max(0.0);
    for ev in &outbox.0 {
        if let lantern_sim::SimEvent::Strike { pos, radius, fx: lantern_sim::combat::StrikeFx::Ult } = ev {
            lights.burst = 1.0;
            lights.burst_pos = crate::to_screen(*pos);
            lights.burst_radius = *radius;
        }
    }
    let (tf, view) = *hero;
    let pos = tf.translation.truncate();
    let (socket, color) = view.lamp(&db);
    let col = color.to_linear();
    lights.sources[0] = LocalLight {
        pos: pos + socket,
        radius: stats.map_or(200.0, |s| {
            200.0 * s.get(lantern_content::Stat::Area).sqrt() * s.get(lantern_content::Stat::Light)
        }),
        strength: 0.85,
        color: Vec3::new(col.red, col.green, col.blue),
    };
    lights.sources[1] = LocalLight {
        pos: lights.burst_pos,
        radius: lights.burst_radius.max(240.0),
        strength: lights.burst * 1.4,
        color: Vec3::new(1.0, 0.69, 0.32),
    };
    // 位置和弹幕精灵一样插值；没有狐火时完全熄灭，不凭空补一团光。
    lights.sources[2] = foes
        .as_ref()
        .and_then(|f| {
            f.0.iter().min_by(|a, b| {
                a.pos
                    .distance_squared(crate::to_screen(pos))
                    .total_cmp(&b.pos.distance_squared(crate::to_screen(pos)))
            })
        })
        .map_or(LocalLight::default(), |f| LocalLight {
            pos: crate::to_screen(f.prev.lerp(f.pos, fixed.overstep_fraction())),
            radius: 155.0,
            strength: 0.8,
            color: Vec3::new(1.0, 0.25, 0.16),
        });
}

/// 椭圆仍紧贴脚底：离光越远稍长，偏移封顶为脚底半径的 22%，不能变成悬浮的投影。
pub(crate) fn contact_shadow(at: Vec2, light: LocalLight, radius: f32) -> (Vec2, Vec2) {
    let delta = at - light.pos;
    let weight = light.weight(at).min(1.0);
    if weight <= 0.001 {
        return (Vec2::ZERO, Vec2::ONE);
    }
    let direction = delta / (delta.length_squared() + 24.0 * 24.0).sqrt();
    let offset = direction * radius * 0.22 * weight;
    let stretch = Vec2::ONE + direction.abs() * (0.28 * weight);
    (offset, stretch)
}

/// 主角/夜主少量叠画；材质和实体按槽复用，不为杂兵增加一次绘制。
#[derive(Resource, Default)]
pub(crate) struct SurfaceDraws(pub Vec<crate::actors::Draw>);

#[derive(Clone, Copy, ShaderType, Debug)]
pub(crate) struct SurfaceUniform {
    uv_rect: Vec4,
    tint: Vec4,
    // xyz：位置与半径；w：强度
    lights: [Vec4; 3],
    colors: [Vec4; 3],
    // x：水平镜像符号；其余保留
    shape: Vec4,
}

#[derive(Asset, TypePath, AsBindGroup, Clone, Debug)]
pub(crate) struct SurfaceMaterial {
    #[uniform(0)]
    params: SurfaceUniform,
    #[texture(1)]
    #[sampler(2)]
    image: Handle<Image>,
}

impl Material2d for SurfaceMaterial {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_view/surface_light.wesl".into()
    }

    fn alpha_mode(&self) -> AlphaMode2d {
        AlphaMode2d::Blend
    }

    fn specialize(
        _pipeline: &Material2dPipeline,
        descriptor: &mut RenderPipelineDescriptor,
        _layout: &MeshVertexBufferLayoutRef,
        _key: Material2dKey<Self>,
    ) -> Result<(), SpecializedMeshPipelineError> {
        set_blend(
            descriptor,
            BlendState {
                color: BlendComponent {
                    src_factor: BlendFactor::SrcAlpha,
                    dst_factor: BlendFactor::One,
                    operation: BlendOperation::Add,
                },
                alpha: BlendComponent {
                    src_factor: BlendFactor::Zero,
                    dst_factor: BlendFactor::One,
                    operation: BlendOperation::Add,
                },
            },
        );
        Ok(())
    }
}

#[derive(Component)]
pub(crate) struct SurfaceSlot;

pub(crate) fn apply_surface_lights(
    mut commands: Commands,
    db: Res<AtlasDb>,
    lights: Res<SceneLights>,
    requests: Res<SurfaceDraws>,
    mut cache: ResMut<FrameMeshes>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<SurfaceMaterial>>,
    mut q: Query<
        (&mut Mesh2d, &MeshMaterial2d<SurfaceMaterial>, &mut Transform, &mut Visibility),
        With<SurfaceSlot>,
    >,
) {
    let mut iter = requests.0.iter();
    for (mut mesh, mat, mut tf, mut vis) in &mut q {
        let Some(d) = iter.next() else {
            *vis = Visibility::Hidden;
            continue;
        };
        mesh.0 = cache.mesh(&db, &mut meshes, d.frame, d.flip);
        if let Some(mut material) = materials.get_mut(&mat.0) {
            *material = surface_material(&db, &lights, d);
        }
        *tf = surface_transform(d);
        *vis = Visibility::Inherited;
    }
    for d in iter {
        commands.spawn((
            SurfaceSlot,
            Mesh2d(cache.mesh(&db, &mut meshes, d.frame, d.flip)),
            MeshMaterial2d(materials.add(surface_material(&db, &lights, d))),
            surface_transform(d),
            DespawnOnExit(lantern_sim::AppState::Run),
        ));
    }
}

fn surface_transform(d: &crate::actors::Draw) -> Transform {
    Transform::from_translation(d.pos + Vec3::Z * 0.00002).with_scale(d.scale.extend(1.0))
}

fn surface_material(db: &AtlasDb, lights: &SceneLights, d: &crate::actors::Draw) -> SurfaceMaterial {
    let f = db.frame(d.frame);
    let c = d.color.to_linear();
    SurfaceMaterial {
        params: SurfaceUniform {
            uv_rect: Vec4::new(f.uv.min.x, f.uv.min.y, f.uv.max.x, f.uv.max.y),
            tint: Vec4::new(c.red, c.green, c.blue, c.alpha),
            lights: lights.sources.map(|l| Vec4::new(l.pos.x, l.pos.y, l.radius, l.strength)),
            colors: lights.sources.map(|l| l.color.extend(1.0)),
            shape: Vec4::new(if d.flip { -1.0 } else { 1.0 }, 0.0, 0.0, 0.0),
        },
        image: db.image(d.frame),
    }
}

pub(crate) fn reset_scene_lights(mut lights: ResMut<SceneLights>, mut draws: ResMut<SurfaceDraws>) {
    *lights = SceneLights::default();
    draws.0.clear();
}

#[cfg(test)]
mod depth_tests {
    use super::*;

    #[test]
    fn contact_shadow_follows_light_and_stays_at_feet() {
        for dir in [Vec2::X, Vec2::NEG_X, Vec2::Y, Vec2::NEG_Y] {
            let light = LocalLight { pos: dir * 40.0, radius: 200.0, strength: 1.0, ..default() };
            let (offset, stretch) = contact_shadow(Vec2::ZERO, light, 12.0);
            assert!(offset.dot(dir) < 0.0);
            assert!(offset.length() <= 12.0 * 0.22);
            assert!(stretch.min_element() >= 1.0 && stretch.max_element() <= 1.28);
        }
        let light = LocalLight { radius: 200.0, strength: 1.0, ..default() };
        assert_eq!(contact_shadow(Vec2::ZERO, light, 12.0), (Vec2::ZERO, Vec2::ONE));
        assert_eq!(contact_shadow(Vec2::splat(500.0), light, 12.0), (Vec2::ZERO, Vec2::ONE));
    }
}
