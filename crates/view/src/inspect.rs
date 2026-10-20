//! 物件检视（docs/PLAYTEST.md 第 11 项，规格见 DESIGN 第 15 节“检视模型”）：法器、灯坠、灯笼的 glTF 模型，
//! 用单独的三维相机画到一张贴图上，界面层把贴图放进检视面板。打开时才加载模型，关掉就连相机、灯、模型一起卸掉。
//!
//! 模型在 `assets/models/inspect/<id>.glb`：+Y 朝上、正面朝 +Z、原点在几何中心、包围球半径 1。
//! 名字以 `_outline` 结尾的网格（节点名或材质名）是水墨描边的反向外壳，换成不受光的纯黑；带 `idle` 动画的循环播放。
//! 转动用现实时间，暂停时也能转。

use std::f32::consts::TAU;

use bevy::animation::graph::{AnimationGraph, AnimationGraphHandle};
use bevy::asset::{LoadState, RenderAssetUsages};
use bevy::camera::Hdr;
use bevy::camera::RenderTarget;
use bevy::camera::visibility::RenderLayers;
use bevy::core_pipeline::tonemapping::Tonemapping;
use bevy::gltf::{Gltf, GltfAssetLabel, GltfMaterialName};
use bevy::post_process::bloom::Bloom;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use bevy::world_serialization::{WorldAssetRoot, WorldInstanceReady};

use crate::AssetRoot;

/// 检视用的渲染层：游戏画面在 0 层，光照图在 1 层
pub const INSPECT_LAYER: usize = 2;
/// 画面贴图的边长（像素）
const SIZE: u32 = 1024;
/// 相机的竖直视角和到原点的基础距离：半径 1 的球在视角里留一圈边
const FOV: f32 = 0.52;
const DISTANCE: f32 = 4.6;
/// 俯仰的上下限（±80°）、缩放的范围
const PITCH_MAX: f32 = 80.0 * std::f32::consts::PI / 180.0;
const ZOOM: (f32, f32) = (0.75, 2.6);
/// 松手后转速每秒衰减的比例、不动多久以后开始自己转、自己转的速度（弧度 / 秒）
const DAMPING: f32 = 3.5;
const IDLE_AFTER: f32 = 2.5;
const IDLE_SPIN: f32 = 0.35;
/// 拖动一像素转多少弧度
const DRAG_RATE: f32 = 0.008;

/// 模型文件的相对路径（相对资源根目录）。
pub fn model_path(id: &str) -> String {
    format!("models/inspect/{id}.glb")
}

/// 这件东西有没有模型：没有就不给检视入口。
pub fn has_model(root: &AssetRoot, id: &str) -> bool {
    root.0.join(model_path(id)).is_file()
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum InspectStatus {
    #[default]
    Closed,
    Loading,
    Ready,
    /// 模型读不出来：界面退回显示卡面插画
    Failed,
}

/// 检视的状态。界面层用 [`Inspect::open`] / [`Inspect::close`] 开关，用 `drag`、`turn`、`zoom` 转动。
#[derive(Resource, Default)]
pub struct Inspect {
    id: Option<String>,
    shown: Option<String>,
    image: Option<Handle<Image>>,
    status: InspectStatus,
    yaw: f32,
    pitch: f32,
    zoom: f32,
    /// 松手时的转速（弧度 / 秒，x 是绕竖轴，y 是俯仰）
    spin: Vec2,
    /// 多久没碰了（秒）；拖动时为 0
    idle: f32,
    dragging: bool,
    /// 模型出来以后过了几秒：入场时墨晕化开、物件转进来
    intro: f32,
}

impl Inspect {
    pub fn open(&mut self, id: impl Into<String>) {
        self.id = Some(id.into());
    }

    pub fn close(&mut self) {
        self.id = None;
    }

    pub fn is_open(&self) -> bool {
        self.id.is_some()
    }

    pub fn id(&self) -> Option<&str> {
        self.id.as_deref()
    }

    /// 画面贴图；打开后、相机建好才有
    pub fn image(&self) -> Option<&Handle<Image>> {
        self.image.as_ref()
    }

    pub fn status(&self) -> InspectStatus {
        self.status
    }

    /// 鼠标或手指拖了 `delta` 像素（这一帧，`dt` 秒）：跟手转，松手后按最后的速度带惯性
    pub fn drag(&mut self, delta: Vec2, dt: f32) {
        let turn = delta * DRAG_RATE;
        self.rotate(turn);
        if dt > 0.0 {
            self.spin = self.spin.lerp(turn / dt, 0.5);
        }
        self.dragging = true;
        self.idle = 0.0;
    }

    /// 松手
    pub fn release(&mut self) {
        self.dragging = false;
    }

    /// 方向键、摇杆：按住时匀速转（`rate` 是 -1..1，`dt` 秒）
    pub fn turn(&mut self, rate: Vec2, dt: f32) {
        if rate == Vec2::ZERO {
            return;
        }
        self.rotate(rate * 2.2 * dt);
        self.spin = Vec2::ZERO;
        self.idle = 0.0;
    }

    /// 滚轮、扳机、双指：正数拉近
    pub fn zoom(&mut self, steps: f32) {
        self.zoom = (self.zoom * 1.12f32.powf(steps)).clamp(ZOOM.0, ZOOM.1);
        self.idle = 0.0;
    }

    fn rotate(&mut self, turn: Vec2) {
        self.yaw = (self.yaw + turn.x).rem_euclid(TAU);
        self.pitch = (self.pitch + turn.y).clamp(-PITCH_MAX, PITCH_MAX);
    }

    /// 一帧：惯性衰减，不碰久了自己慢慢转
    fn advance(&mut self, dt: f32) {
        if self.dragging {
            return;
        }
        self.idle += dt;
        self.rotate(self.spin * dt);
        self.spin *= (-DAMPING * dt).exp();
        if self.idle > IDLE_AFTER {
            let ease = ((self.idle - IDLE_AFTER) / 1.5).min(1.0);
            self.rotate(Vec2::new(IDLE_SPIN * ease * dt, 0.0));
            // 自己转时慢慢回正俯仰
            self.pitch *= (-0.8 * ease * dt).exp();
        }
    }

    /// 物件的朝向：先绕竖轴转，再朝镜头俯仰；入场时多带一段没转完的角度
    fn rotation(&self) -> Quat {
        let late = INTRO_TURN * (1.0 - ease_out(self.intro / INTRO_SECS));
        Quat::from_rotation_x(self.pitch) * Quat::from_rotation_y(self.yaw - late)
    }
}

/// 检视时建出来的东西（相机、灯、模型），关掉时一起卸掉
#[derive(Component)]
struct InspectPart;

/// 转动的支点（模型挂在它下面）
#[derive(Component)]
struct Pivot;

#[derive(Component)]
struct InspectCamera;

/// 物件背后的墨（一张烤好的底图：宣纸、一团淡墨晕、一道干笔横扫的笔触）
#[derive(Component)]
struct Backdrop;

/// 入场：墨从中间往外晕开，物件从侧面转进来并稍稍放大到原大，用时（秒）和多转的角度（弧度）
const INTRO_SECS: f32 = 0.8;
const INTRO_TURN: f32 = 1.1;
/// 模型出来以后先停一下再入场：头一帧要编着色器，卡一下的那几帧不算进入场
const INTRO_DELAY: f32 = 0.25;
/// 底图离原点多远（在物件后面）、多大。底图边上就是宣纸色，和底色一样，放大缩小都看不出边
const BACKDROP_Z: f32 = -2.0;
const BACKDROP_SIZE: f32 = 4.2;
/// 笔触斜一点
const STROKE_TILT: f32 = 0.1;

fn ease_out(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    1.0 - (1.0 - t).powi(3)
}

/// 模型的整个 glTF（取 idle 动画用）
#[derive(Component)]
struct ModelGltf(Handle<Gltf>);

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Inspect>().add_systems(Update, (sync, watch_load, advance).chain());
}

/// 打开、换物件、关掉：重建或卸掉相机、灯和模型。
fn sync(
    mut commands: Commands,
    mut inspect: ResMut<Inspect>,
    mut images: ResMut<Assets<Image>>,
    (mut meshes, mut materials): (ResMut<Assets<Mesh>>, ResMut<Assets<StandardMaterial>>),
    mut backdrop: Local<Option<Handle<Image>>>,
    assets: Res<AssetServer>,
    parts: Query<Entity, With<InspectPart>>,
) {
    if inspect.id == inspect.shown {
        return;
    }
    for e in &parts {
        commands.entity(e).despawn();
    }
    if let Some(old) = inspect.image.take() {
        images.remove(&old);
    }
    inspect.shown = inspect.id.clone();
    let Some(id) = inspect.id.clone() else {
        inspect.status = InspectStatus::Closed;
        return;
    };
    *inspect = Inspect {
        id: Some(id.clone()),
        shown: Some(id.clone()),
        zoom: 1.0,
        pitch: -0.18,
        intro: -INTRO_DELAY,
        ..default()
    };
    let image = images.add(Image::new_target_texture(SIZE, SIZE, TextureFormat::Rgba8UnormSrgb, None));
    inspect.image = Some(image.clone());
    inspect.status = InspectStatus::Loading;
    let layer = RenderLayers::layer(INSPECT_LAYER);

    commands.spawn((
        InspectPart,
        InspectCamera,
        Camera3d::default(),
        // 在游戏画面和界面之前画好；底色是宣纸（先反算色调映射，画出来才是宣纸色，不发灰）
        Camera { order: -2, clear_color: ClearColorConfig::Custom(before_aces(PAPER)), ..default() },
        RenderTarget::from(image),
        Hdr,
        Bloom { intensity: 0.22, ..Bloom::NATURAL },
        Tonemapping::AcesFitted,
        Projection::Perspective(PerspectiveProjection { fov: FOV, ..default() }),
        // 环境光压低、偏冷，物件才有明暗
        AmbientLight { color: Color::srgb(0.9, 0.93, 1.0), brightness: 320.0, ..default() },
        Transform::from_xyz(0.0, 0.0, DISTANCE).looking_at(Vec3::ZERO, Vec3::Y),
        layer.clone(),
    ));
    // 三盏灯跟镜头不动，物件转：左上前方一盏暖的主光（像灯笼），右侧一盏冷的补光（像月光），
    // 背后偏上一道亮的边缘光，金属的刃口、器物的轮廓转到侧面时会亮起一线（docs/FEEL.md 第 14 节）
    for (illuminance, color, from) in [
        (11000.0, Color::srgb(1.0, 0.9, 0.74), Vec3::new(-2.5, 2.5, 3.5)),
        (2400.0, Color::srgb(0.74, 0.84, 1.0), Vec3::new(3.5, 0.3, 1.5)),
        (22000.0, Color::srgb(1.0, 0.96, 0.88), Vec3::new(0.8, 2.2, -3.5)),
    ] {
        commands.spawn((
            InspectPart,
            DirectionalLight { illuminance, color, shadow_maps_enabled: false, ..default() },
            Transform::from_translation(from).looking_at(Vec3::ZERO, Vec3::Y),
            layer.clone(),
        ));
    }
    // 物件背后烤好的一张底图：宣纸上一团淡墨晕、一道干笔横扫的笔触。三维画面在色调映射之前混色，
    // 纸色那时比白还亮，半透明的墨怎么叠都是褐色；所以每个像素直接存“映射前该是多少”，不混色。
    // 第一次打开时画，之后一直用
    let backdrop = backdrop.get_or_insert_with(|| images.add(ink_backdrop())).clone();
    commands.spawn((
        InspectPart,
        Backdrop,
        Mesh3d(meshes.add(Rectangle::new(BACKDROP_SIZE, BACKDROP_SIZE))),
        MeshMaterial3d(materials.add(StandardMaterial {
            base_color_texture: Some(backdrop),
            unlit: true,
            ..default()
        })),
        Transform::from_xyz(0.0, 0.0, BACKDROP_Z).with_scale(Vec3::splat(0.3)),
        layer.clone(),
    ));
    let path = model_path(&id);
    commands
        .spawn((InspectPart, Pivot, Transform::default(), Visibility::default(), layer.clone()))
        .with_children(|pivot| {
            pivot
                .spawn((
                    WorldAssetRoot(assets.load(GltfAssetLabel::Scene(0).from_asset(path.clone()))),
                    ModelGltf(assets.load(path)),
                    layer,
                ))
                .observe(on_ready);
        });
}

/// 宣纸底色
const PAPER: Color = Color::srgb(0.86, 0.82, 0.74);

/// 值噪声（0–1），画墨晕的毛边用。
fn noise(x: f32, y: f32) -> f32 {
    let hash = |i: i32, j: i32| {
        let mut h = (i as u32).wrapping_mul(0x8da6_b343) ^ (j as u32).wrapping_mul(0xd816_3841);
        h ^= h >> 13;
        h = h.wrapping_mul(0x5bd1_e995);
        h ^= h >> 15;
        (h & 0xffff) as f32 / 65535.0
    };
    let (xi, yi) = (x.floor() as i32, y.floor() as i32);
    let (fx, fy) = (x - xi as f32, y - yi as f32);
    let s = |t: f32| t * t * (3.0 - 2.0 * t);
    let (u, v) = (s(fx), s(fy));
    let (a, b, c, d) = (hash(xi, yi), hash(xi + 1, yi), hash(xi, yi + 1), hash(xi + 1, yi + 1));
    a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v
}

fn fbm(x: f32, y: f32) -> f32 {
    (noise(x, y) * 0.55 + noise(x * 2.1, y * 2.1) * 0.3 + noise(x * 4.3, y * 4.3) * 0.15).clamp(0.0, 1.0)
}

fn smooth(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// 干笔横扫的笔触有多浓（0–1）：u 沿着笔走（0 起笔，1 收笔），v 横着（-1..1）。
/// 起笔圆、笔肚饱满、收笔尖，越往后越干、拉出飞白的细丝。
fn stroke(u: f32, v: f32) -> f32 {
    if !(0.0..=1.0).contains(&u) {
        return 0.0;
    }
    // 起笔是钝圆的一团（笔一按下去就铺开），笔肚饱满，收笔尖
    let start = (1.0 - (1.0 - (u / 0.06).min(1.0)).powi(2)).sqrt();
    let half = 0.7 * (0.55 + 0.45 * smooth(0.0, 0.12, u)) * start * (1.0 - 0.9 * smooth(0.6, 1.0, u)) + 0.02;
    let wobble = (fbm(u * 2.4, 1.3) - 0.5) * 0.3;
    let rough = (fbm(u * 18.0, v * 2.0 + 5.0) - 0.5) * 0.3;
    let d = ((v - wobble).abs() + rough * half) / half;
    let body = 1.0 - smooth(0.88, 1.0, d);
    let dry = smooth(0.3, 1.0, u);
    let hair = fbm(u * 1.5 + 9.0, v * 46.0);
    let white = 1.0 - dry * (1.0 - smooth(0.42 - 0.12 * dry, 0.56, hair));
    (body * white * (0.8 + 0.2 * fbm(u * 24.0, v * 12.0))).clamp(0.0, 1.0)
}

/// 检视的底图：宣纸色上一团淡墨晕、一道略斜的干笔横扫。存的是色调映射之前的值（半精度浮点），
/// 画出来正好是想要的纸色和墨色。
fn ink_backdrop() -> Image {
    const N: u32 = 640;
    const INK: Color = Color::srgb(0.09, 0.08, 0.06);
    let (sin, cos) = STROKE_TILT.sin_cos();
    let mut px = Vec::with_capacity((N * N * 8) as usize);
    for y in 0..N {
        for x in 0..N {
            // 贴图的 y 往下，画面的 y 往上
            let p =
                Vec2::new((x as f32 + 0.5) / N as f32 * 2.0 - 1.0, 1.0 - (y as f32 + 0.5) / N as f32 * 2.0);
            // 淡墨晕：中间浓、往外化开，边上毛
            let d = p.length() * (0.75 + 0.5 * fbm(p.x * 2.6 + 7.1, p.y * 2.6 - 2.3)) / 0.62;
            let halo = (1.0 - smooth(0.3, 0.95, d)) * (0.7 + 0.3 * fbm(p.x * 9.0 + 1.7, p.y * 9.0 + 3.1));
            // 笔触：转正以后沿 x 走，占中间一段
            let q = Vec2::new(p.x * cos + p.y * sin, -p.x * sin + p.y * cos);
            let brush = stroke((q.x + 0.66) / 1.32, (q.y + 0.02) / 0.3);
            let ink = 1.0 - (1.0 - 0.2 * halo) * (1.0 - 0.94 * brush);
            let c = before_aces(PAPER.mix(&INK, ink)).to_linear();
            for v in [c.red, c.green, c.blue, 1.0] {
                px.extend_from_slice(&f16_bits(v).to_le_bytes());
            }
        }
    }
    Image::new(
        Extent3d { width: N, height: N, depth_or_array_layers: 1 },
        TextureDimension::D2,
        px,
        TextureFormat::Rgba16Float,
        RenderAssetUsages::RENDER_WORLD,
    )
}

/// 正数 f32 转半精度浮点的位（底图的值都在 0 到几十之间，太小的当 0）。
fn f16_bits(x: f32) -> u16 {
    let b = x.max(0.0).to_bits();
    let exp = ((b >> 23) & 0xff) as i32 - 127 + 15;
    if exp <= 0 {
        0
    } else if exp >= 31 {
        0x7c00
    } else {
        ((exp as u16) << 10) | ((b & 0x7f_ffff) >> 13) as u16
    }
}

/// Bevy 的 AcesFitted 用的两个矩阵（tonemapping.wesl 里是行向量乘，这里转置成列向量乘）
fn aces_matrices() -> (Mat3, Mat3) {
    let rgb_to_rrt = Mat3::from_cols(
        Vec3::new(0.59719, 0.35458, 0.04823),
        Vec3::new(0.07600, 0.90834, 0.01566),
        Vec3::new(0.02840, 0.13383, 0.83777),
    )
    .transpose();
    let odt_to_rgb = Mat3::from_cols(
        Vec3::new(1.60475, -0.53108, -0.07367),
        Vec3::new(-0.10208, 1.10813, -0.00605),
        Vec3::new(-0.00327, -0.07276, 1.07602),
    )
    .transpose();
    (rgb_to_rrt, odt_to_rgb)
}

/// 色调映射之前该是什么颜色，映射出来才正好是 `c`（AcesFitted 反过来算）。
fn before_aces(c: Color) -> Color {
    let (rgb_to_rrt, odt_to_rgb) = aces_matrices();
    let y = odt_to_rgb.inverse() * Vec3::from_array(c.to_linear().to_f32_array_no_alpha());
    // RRTAndODTFit：y = (x² + 0.0245786x − 0.000090537) / (0.983729x² + 0.432951x + 0.238081)，解 x 取正根
    let fit = |y: f32| {
        let a = 1.0 - 0.983729 * y;
        let b = 0.0245786 - 0.432951 * y;
        let k = -(0.000090537 + 0.238081 * y);
        (-b + (b * b - 4.0 * a * k).sqrt()) / (2.0 * a)
    };
    let x = rgb_to_rrt.inverse() * Vec3::new(fit(y.x), fit(y.y), fit(y.z));
    Color::linear_rgb(x.x, x.y, x.z)
}

/// 模型生成好了：整棵挪到检视层，描边换成纯黑，带 idle 动画的播起来。
#[allow(clippy::too_many_arguments)]
fn on_ready(
    ready: On<WorldInstanceReady>,
    mut commands: Commands,
    mut inspect: ResMut<Inspect>,
    children: Query<&Children>,
    names: Query<(Option<&Name>, Option<&GltfMaterialName>)>,
    players: Query<Entity, With<AnimationPlayer>>,
    gltfs: Query<&ModelGltf>,
    gltf_assets: Res<Assets<Gltf>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut graphs: ResMut<Assets<AnimationGraph>>,
) {
    let root = ready.entity;
    let layer = RenderLayers::layer(INSPECT_LAYER);
    let outline = materials.add(StandardMaterial { base_color: Color::BLACK, unlit: true, ..default() });
    let idle = gltfs
        .get(root)
        .ok()
        .and_then(|g| gltf_assets.get(&g.0))
        .and_then(|g| g.named_animations.get("idle").cloned());
    for e in children.iter_descendants(root) {
        commands.entity(e).insert(layer.clone());
        if let Ok((name, material)) = names.get(e)
            && (name.is_some_and(|n| n.as_str().ends_with("_outline"))
                || material.is_some_and(|m| m.0.ends_with("_outline")))
        {
            commands.entity(e).insert(MeshMaterial3d(outline.clone()));
        }
        if let (Some(clip), Ok(player)) = (idle.clone(), players.get(e)) {
            let (graph, node) = AnimationGraph::from_clip(clip);
            let mut p = AnimationPlayer::default();
            p.play(node).repeat();
            commands.entity(player).insert((p, AnimationGraphHandle(graphs.add(graph))));
        }
    }
    inspect.status = InspectStatus::Ready;
}

/// 模型读失败（文件坏了、格式不对）：标出来，界面退回卡面插画
fn watch_load(
    mut inspect: ResMut<Inspect>,
    assets: Res<AssetServer>,
    roots: Query<&WorldAssetRoot, With<ModelGltf>>,
) {
    if inspect.status != InspectStatus::Loading {
        return;
    }
    for root in &roots {
        if let LoadState::Failed(e) = assets.load_state(root.0.id()) {
            warn!("检视模型读取失败：{e}");
            inspect.status = InspectStatus::Failed;
        }
    }
}

/// 每帧：惯性、自转，把转角和缩放套到支点和相机上。用现实时间，暂停时也能转。
fn advance(
    time: Res<Time<Real>>,
    mut inspect: ResMut<Inspect>,
    mut pivots: Query<&mut Transform, (With<Pivot>, Without<InspectCamera>, Without<Backdrop>)>,
    mut cameras: Query<&mut Transform, (With<InspectCamera>, Without<Pivot>, Without<Backdrop>)>,
    mut washes: Query<&mut Transform, (With<Backdrop>, Without<Pivot>, Without<InspectCamera>)>,
) {
    if !inspect.is_open() {
        return;
    }
    let dt = time.delta_secs().min(0.1);
    inspect.advance(dt);
    // 入场从模型出来那一刻算：墨晕化开，物件转进来、放大到原大
    let fresh = inspect.intro < INTRO_SECS;
    if inspect.status == InspectStatus::Ready {
        inspect.intro += dt;
    }
    let k = ease_out(inspect.intro / INTRO_SECS);
    for mut tf in &mut pivots {
        tf.rotation = inspect.rotation();
        tf.scale = Vec3::splat(0.9 + 0.1 * k);
    }
    if fresh {
        // 墨从中间往外晕开：底图边上是纸色，放大时只看得见墨在长
        for mut tf in &mut washes {
            tf.scale = Vec3::splat(0.3 + 0.7 * k);
        }
    }
    for mut tf in &mut cameras {
        tf.translation = Vec3::Z * DISTANCE / inspect.zoom;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drag_turns_with_inertia_and_pitch_is_clamped() {
        let mut v = Inspect { zoom: 1.0, ..default() };
        v.drag(Vec2::new(100.0, 0.0), 1.0 / 60.0);
        assert!((v.yaw - 0.8).abs() < 1e-5);
        v.release();
        let before = v.yaw;
        v.advance(0.1);
        assert!(v.yaw > before, "松手后带惯性接着转");
        let fast = v.spin.x;
        v.advance(0.5);
        assert!(v.spin.x < fast * 0.3, "惯性衰减");
        v.drag(Vec2::new(0.0, 10_000.0), 1.0 / 60.0);
        assert!((v.pitch - PITCH_MAX).abs() < 1e-5, "俯仰限在 80°");
    }

    #[test]
    fn idle_spins_slowly_after_a_while_and_zoom_is_clamped() {
        let mut v = Inspect { zoom: 1.0, ..default() };
        for _ in 0..60 {
            v.advance(1.0 / 60.0);
        }
        assert_eq!(v.yaw, 0.0, "刚放手不自己转");
        for _ in 0..(60 * 4) {
            v.advance(1.0 / 60.0);
        }
        assert!(v.yaw > 0.1, "不碰两秒半以后自己慢慢转");
        v.zoom(100.0);
        assert_eq!(v.zoom, ZOOM.1);
        v.zoom(-100.0);
        assert_eq!(v.zoom, ZOOM.0);
    }

    /// 底色反算以后再走一遍 AcesFitted，回到宣纸色
    #[test]
    fn backdrop_comes_out_of_tonemapping_as_paper() {
        let (rgb_to_rrt, odt_to_rgb) = aces_matrices();
        let fit = |v: f32| (v * (v + 0.0245786) - 0.000090537) / (v * (0.983729 * v + 0.432951) + 0.238081);
        let x = Vec3::from_array(before_aces(PAPER).to_linear().to_f32_array_no_alpha());
        let m = rgb_to_rrt * x;
        let y = (odt_to_rgb * Vec3::new(fit(m.x), fit(m.y), fit(m.z))).clamp(Vec3::ZERO, Vec3::ONE);
        let want = Vec3::from_array(PAPER.to_linear().to_f32_array_no_alpha());
        assert!((y - want).abs().max_element() < 1e-3, "{y} vs {want}");
        assert!(x.max_element() > want.max_element(), "映射前要更亮");
    }

    /// 底图存的半精度浮点：常见的值换得对，负数和太小的当 0
    #[test]
    fn half_floats_for_the_backdrop() {
        assert_eq!(f16_bits(1.0), 0x3c00);
        assert_eq!(f16_bits(2.0), 0x4000);
        assert_eq!(f16_bits(0.5), 0x3800);
        assert_eq!(f16_bits(-1.0), 0);
        assert_eq!(f16_bits(1e-9), 0);
    }

    /// 笔触：起笔是钝的一团（不是尖），笔肚浓，收笔前干、有飞白的空隙，笔外没有墨
    #[test]
    fn brush_stroke_starts_blunt_and_dries_out() {
        assert!(stroke(0.02, 0.0) > 0.5, "起笔钝圆");
        assert!(stroke(0.3, 0.0) > 0.7, "笔肚浓");
        let tail: Vec<f32> = (0..200).map(|i| stroke(0.85, -0.2 + i as f32 * 0.002)).collect();
        assert!(tail.iter().any(|&a| a < 0.2) && tail.iter().any(|&a| a > 0.5), "收笔有飞白");
        assert_eq!(stroke(-0.1, 0.0), 0.0);
        assert_eq!(stroke(0.3, 0.99), 0.0, "笔外没有墨");
    }

    /// 入场：模型出来先停一下，再转进来；停的时候是起始姿势
    #[test]
    fn intro_waits_then_turns_in() {
        let mut v = Inspect { zoom: 1.0, intro: -INTRO_DELAY, ..default() };
        let start = v.rotation();
        v.intro = 0.0;
        assert!(v.rotation().angle_between(start) < 1e-5, "停的时候不动");
        v.intro = INTRO_SECS;
        assert!(v.rotation().angle_between(Quat::IDENTITY) < 1e-5, "入场完正对");
    }

    #[test]
    fn model_paths_follow_the_card_art_naming() {
        assert_eq!(model_path("sword_evo"), "models/inspect/sword_evo.glb");
    }
}
