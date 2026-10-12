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

use bevy::asset::RenderAssetUsages;
use bevy::camera::visibility::RenderLayers;
use bevy::camera::{RenderTarget, ScalingMode};
use bevy::core_pipeline::tonemapping::Tonemapping;
use bevy::material::descriptor::RenderPipelineDescriptor;
use bevy::material::specialize::SpecializedMeshPipelineError;
use bevy::mesh::{Indices, MeshVertexBufferLayoutRef, PrimitiveTopology};
use bevy::prelude::*;
use bevy::render::render_resource::{
    AsBindGroup, BlendComponent, BlendFactor, BlendOperation, BlendState, TextureFormat,
};
use bevy::sprite_render::{
    AlphaMode2d, ExtendedMaterial2d, Material2dKey, Material2dPipeline, Material2dPlugin, MaterialExtension2d,
};
use bevy::window::{PrimaryWindow, WindowResized};

use crate::atlas::{AtlasDb, FrameId};

/// 光照相机画的图层
pub const LIGHT_LAYER: usize = 1;

/// 光照图的分辨率相对窗口的比例
const LIGHTMAP_SCALE: f32 = 0.5;

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
    materials: HashMap<(usize, [u8; 4]), Handle<AddMaterial>>,
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

    /// 叠加材质：同一页贴图、同一种颜色（含强度）共用一个。
    pub fn additive(
        &mut self,
        db: &AtlasDb,
        materials: &mut Assets<AddMaterial>,
        id: FrameId,
        color: Color,
    ) -> Handle<AddMaterial> {
        let key = (db.page_of(id), color.to_srgba().to_u8_array());
        self.materials
            .entry(key)
            .or_insert_with(|| {
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
        app.add_plugins((
            Material2dPlugin::<AddMaterial>::default(),
            Material2dPlugin::<MulMaterial>::default(),
        ))
        .init_resource::<FrameMeshes>();
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

/// 光照相机和暗层跟着主镜头走；暗层铺满镜头看到的范围。
pub(crate) fn follow_main_camera(
    main: Single<
        (&Transform, &Projection),
        (With<crate::MainCamera>, Without<LightCamera>, Without<Darkness>),
    >,
    mut light_cam: Single<&mut Transform, (With<LightCamera>, Without<Darkness>)>,
    mut darkness: Single<(&mut Transform, &mut Visibility), With<Darkness>>,
) {
    let (main_tf, proj) = *main;
    light_cam.translation = main_tf.translation;
    let half = match proj {
        Projection::Orthographic(o) => o.area.half_size(),
        _ => Vec2::splat(500.0),
    };
    let (dark_tf, dark_vis) = &mut *darkness;
    dark_tf.translation = Vec3::new(main_tf.translation.x, main_tf.translation.y, crate::layer::DARKNESS);
    dark_tf.scale = (half * 2.0).extend(1.0);
    **dark_vis = Visibility::Inherited;
}

pub(crate) fn hide_darkness(mut darkness: Single<&mut Visibility, With<Darkness>>) {
    **darkness = Visibility::Hidden;
}
