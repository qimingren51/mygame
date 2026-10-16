//! 青丘迷雾（docs/FEEL.md 第 4 节）：美术的 `vfx/mist_0`（大团）、`mist_1`（碎团）是无缝平铺的贴图，
//! 一张盖 128 个世界单位，白色可染。图集里不能重复采样，一格格铺开会在格子边上露出接缝，
//! 所以等图集加载好，把这两帧拷成单独的、重复采样的贴图，每层一个盖住镜头的大四边形，
//! UV 跟着世界坐标走、各自漂移。叠在暗层之上、普通混合：夜里像月光下的雾，天明时淡一半，成了晨雾。
//! 夜签“浓雾”（灯光范围 −30%）的夜里雾浓得多、飘得慢，让减掉的灯光看得见。

use bevy::asset::RenderAssetUsages;
use bevy::image::{ImageAddressMode, ImageSampler, ImageSamplerDescriptor};
use bevy::math::Affine2;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension};
use bevy::sprite_render::AlphaMode2d;

use lantern_sim::RunSetup;

use crate::atlas::AtlasDb;
use crate::palette::TIDE_DECOR_GAIN;
use crate::{Dawn, Feel, MainCamera, layer};

/// （帧名，不透明度，漂移速度：世界单位 / 秒）。HDR 镜头在线性空间里混合，亮雾盖在暗处
/// 比美术预览（sRGB 里混合）亮得多，所以不透明度比美术建议的 0.2、0.15 低很多。
const LAYERS: [(&str, f32, Vec2); 2] =
    [("vfx/mist_0", 0.05, Vec2::new(7.0, -2.0)), ("vfx/mist_1", 0.035, Vec2::new(-12.0, 3.5))];
const TILE: f32 = 128.0;
/// #DDD9CF
const TINT: Color = Color::srgb(0.867, 0.851, 0.812);
/// 夜签“浓雾”：不透明度乘这么多，漂移乘 FOG_DRIFT
const FOG_THICK: f32 = 2.6;
const FOG_DRIFT: f32 = 0.6;

#[derive(Component)]
pub(crate) struct MistLayer(usize);

/// 贴图拷好、四边形生成以后（或者图集里没有迷雾）为 true。
#[derive(Resource, Default)]
pub(crate) struct MistReady(bool);

/// 等图集那一页加载好，拷出迷雾贴图，生成两层四边形。只做一次。
pub(crate) fn setup_mist(
    mut commands: Commands,
    mut ready: ResMut<MistReady>,
    db: Res<AtlasDb>,
    mut images: ResMut<Assets<Image>>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
) {
    if ready.0 {
        return;
    }
    let Some(first) = db.find(LAYERS[0].0) else {
        ready.0 = true;
        return;
    };
    let Some(page) = images.get(&db.image(first)) else { return };
    let (Some(data), size, format) = (page.data.as_ref(), page.size(), page.texture_descriptor.format) else {
        ready.0 = true;
        return;
    };
    // 先把像素拷出来，放开对整页的借用再加新贴图
    let mut tiles = Vec::new();
    for (k, &(name, ..)) in LAYERS.iter().enumerate() {
        let Some(f) = db.find(name) else { continue };
        let uv = db.frame(f).uv;
        let x0 = (uv.min.x * size.x as f32).round() as u32;
        let y0 = (uv.min.y * size.y as f32).round() as u32;
        let w = ((uv.max.x - uv.min.x) * size.x as f32).round() as u32;
        let h = ((uv.max.y - uv.min.y) * size.y as f32).round() as u32;
        let mut px = Vec::with_capacity((w * h * 4) as usize);
        for y in y0..y0 + h {
            let row = ((y * size.x + x0) * 4) as usize;
            px.extend_from_slice(&data[row..row + (w * 4) as usize]);
        }
        tiles.push((k, w, h, px));
    }
    let mesh = meshes.add(Rectangle::new(1.0, 1.0));
    for (k, w, h, px) in tiles {
        let mut image = Image::new(
            Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            TextureDimension::D2,
            px,
            format,
            RenderAssetUsages::RENDER_WORLD,
        );
        image.sampler = ImageSampler::Descriptor(ImageSamplerDescriptor {
            address_mode_u: ImageAddressMode::Repeat,
            address_mode_v: ImageAddressMode::Repeat,
            ..ImageSamplerDescriptor::linear()
        });
        let material = materials.add(ColorMaterial {
            color: TINT.with_alpha(0.0),
            texture: Some(images.add(image)),
            alpha_mode: AlphaMode2d::Blend,
            ..default()
        });
        commands.spawn((
            MistLayer(k),
            Mesh2d(mesh.clone()),
            MeshMaterial2d(material),
            Transform::from_xyz(0.0, 0.0, layer::DARKNESS + 2.0 + k as f32),
        ));
    }
    ready.0 = true;
}

/// 每层盖住镜头看到的范围，UV 按世界坐标对齐再加上漂移；精简特效只留大团的那层。
pub(crate) fn update_mist(
    time: Res<Time>,
    dawn: Res<Dawn>,
    atmos: Res<crate::atmos::Atmos>,
    feel: Res<Feel>,
    setup: Option<Res<RunSetup>>,
    cam: Single<(&Transform, &Projection), With<MainCamera>>,
    mut q: Query<
        (&MistLayer, &mut Transform, &MeshMaterial2d<ColorMaterial>, &mut Visibility),
        Without<MainCamera>,
    >,
    mut materials: ResMut<Assets<ColorMaterial>>,
) {
    let (cam_tf, proj) = *cam;
    // 留一点边：镜头晃动时会轻微转动
    let half = match proj {
        Projection::Orthographic(o) => o.area.half_size(),
        _ => Vec2::new(500.0, 300.0),
    } + Vec2::splat(24.0);
    let center = cam_tf.translation.truncate();
    let t = time.elapsed_secs();
    // 天明时淡一半；妖潮、合围时也压低（和萤火、夜雾一起，危险色留在最前面）
    let fade = (1.0 - 0.5 * dawn.progress()) * (1.0 - (1.0 - TIDE_DECOR_GAIN) * atmos.tide);
    let fog = setup.is_some_and(|s| s.omen.as_ref().is_some_and(|o| o.id == "fog"));
    let (thick, slow) = if fog { (FOG_THICK, FOG_DRIFT) } else { (1.0, 1.0) };
    for (m, mut tf, mat, mut vis) in &mut q {
        let (_, alpha, drift) = LAYERS[m.0];
        vis.set_if_neq(if feel.lite && m.0 > 0 { Visibility::Hidden } else { Visibility::Inherited });
        tf.translation = center.extend(tf.translation.z);
        tf.scale = (half * 2.0).extend(1.0);
        let Some(mut material) = materials.get_mut(&mat.0) else { continue };
        // 四边形左上角在世界里的位置（贴图 v 向下，世界 y 向上）；贴图本身往 drift 方向漂
        let corner = Vec2::new(center.x - half.x, center.y + half.y) - drift * slow * t;
        let offset = Vec2::new(corner.x, -corner.y) / TILE;
        material.uv_transform =
            Affine2::from_scale_angle_translation(half * 2.0 / TILE, 0.0, offset.rem_euclid(Vec2::ONE));
        material.color = TINT.with_alpha(alpha * thick * fade);
    }
}

/// 离开一局时把四边形留着（下一局接着用），只是先藏起来：标题、结算画面不画雾。
pub(crate) fn hide_mist(mut q: Query<&mut Visibility, With<MistLayer>>) {
    for mut v in &mut q {
        *v = Visibility::Hidden;
    }
}
