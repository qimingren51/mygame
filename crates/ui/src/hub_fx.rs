//! 灯驿长卷的动画（docs/FEEL.md 第 9 节）：心灯亮起、地区晨光铺开、平时灯火摇曳。
//! 布局由 `hub_scene.rs` 按美术的 hub.json 生成（节点挂 `HubLamp`、`HubDawn` 等标记）；这里只改
//! 透明度、缩放和颜色，不动布局。叠加层用 `hub_scene` 的 `UiAdd`；晨光要铺开时，把那一层的
//! `ImageNode` 换成 `DawnReveal`（按“先亮哪里”的灰度图铺开）。

use std::f32::consts::TAU;

use bevy::asset::{RenderAssetUsages, embedded_asset};
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, Extent3d, TextureDimension, TextureFormat};
use bevy::shader::ShaderRef;
use bevy::ui::Val2;

use lantern_platform::HubNews;
use lantern_sim::GameContent;

use crate::hub_scene::{
    DawnPart, HubDawn, HubDawnMask, HubFlameBase, HubImage, HubLamp, LampPart, UiAdd, glow_alpha,
};

/// 地区晨光：按“先亮哪里”的灰度图铺开（`dawn_reveal.wesl`）。
#[derive(AsBindGroup, Asset, TypePath, Debug, Clone)]
pub(crate) struct DawnReveal {
    /// x：进度 0..1；y：边的宽度（灰度单位）；z：水痕的深浅；w：整体不透明度
    #[uniform(0)]
    pub params: Vec4,
    #[texture(1)]
    #[sampler(2)]
    pub image: Handle<Image>,
    #[texture(3)]
    #[sampler(4)]
    pub mask: Handle<Image>,
}

impl UiMaterial for DawnReveal {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_ui/dawn_reveal.wesl".into()
    }
}

/// 点亮：第一盏在灯驿出现后 LIGHT_DELAY 秒开始，之后每盏隔 LIGHT_STAGGER；一盏用 LIGHT_LEN 秒。
const LIGHT_DELAY: f32 = 0.5;
const LIGHT_STAGGER: f32 = 0.35;
const LIGHT_LEN: f32 = 1.4;
/// 晨光：灯驿出现后 DAWN_DELAY 秒开始，DAWN_LEN 秒铺满。
const DAWN_DELAY: f32 = 0.8;
const DAWN_LEN: f32 = 3.2;
/// 余烬、光圈的颜色（和美术叠加层的 #FFD98A 一致）
const WARM: Vec3 = Vec3::new(1.0, 0.85, 0.54);

/// 正在播的点亮和晨光。
#[derive(Resource, Default)]
pub(crate) struct HubAnim {
    clock: f32,
    /// （灯的 id，开始的时刻）
    lighting: Vec<(String, f32)>,
    /// （地区，开始的时刻）
    dawn: Option<(String, f32)>,
    /// 已经放过余烬、光圈的（灯的 id，哪一层）
    sparked: Vec<(String, LampPart)>,
}

impl HubAnim {
    /// 这盏灯点亮了多久；没在点亮时为 None。
    fn lit_for(&self, id: &str) -> Option<f32> {
        self.lighting.iter().find(|(l, _)| l == id).map(|(_, at)| self.clock - at)
    }
}

/// 程序画的小贴图：余烬的软点、荡开的光圈。
#[derive(Resource)]
pub(crate) struct HubTex {
    dot: Handle<Image>,
    ring: Handle<Image>,
}

/// 点亮时飘起的余烬、荡开的光圈：挂在火苗、光晕节点下面，位置按父节点的百分比。
#[derive(Component)]
pub(crate) struct Spark {
    t: f32,
    life: f32,
    /// 起点和每秒的位移（父节点尺寸的百分比）
    from: Vec2,
    vel: Vec2,
    /// 光圈：从多大胀到多大；余烬：(1, 1)
    grow: (f32, f32),
    strength: f32,
}

pub(crate) fn register(app: &mut App) {
    embedded_asset!(app, "dawn_reveal.wesl");
    app.add_plugins(UiMaterialPlugin::<DawnReveal>::default())
        .init_resource::<HubAnim>()
        .add_systems(Startup, make_textures)
        .add_systems(Update, (start, animate_lamps, animate_dawn, animate_sparks).chain());
}

fn make_textures(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let paint = |n: u32, f: &dyn Fn(f32) -> f32| {
        let mut px = vec![0u8; (n * n * 4) as usize];
        for y in 0..n {
            for x in 0..n {
                let c = (n as f32 - 1.0) * 0.5;
                let d = Vec2::new(x as f32 - c, y as f32 - c).length() / c;
                let a = f(d).clamp(0.0, 1.0);
                let i = ((y * n + x) * 4) as usize;
                px[i..i + 4].copy_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
            }
        }
        Image::new(
            Extent3d { width: n, height: n, depth_or_array_layers: 1 },
            TextureDimension::D2,
            px,
            TextureFormat::Rgba8UnormSrgb,
            RenderAssetUsages::RENDER_WORLD,
        )
    };
    let dot = paint(32, &|d| (-d * d * 5.0).exp() * (1.0 - d).max(0.0) * 1.2);
    let ring = paint(128, &|d| (-((d - 0.82) * 9.0).powi(2)).exp() * (1.0 - d).max(0.0) * 6.0);
    commands.insert_resource(HubTex { dot: images.add(dot), ring: images.add(ring) });
}

/// 灯驿出现以后，把这次点亮的心灯、第一次天明的地区排上队（播完不再播）。
fn start(
    mut commands: Commands,
    time: Res<Time<Real>>,
    assets: Res<AssetServer>,
    mut anim: ResMut<HubAnim>,
    news: Option<ResMut<HubNews>>,
    lamps: Query<(), With<HubLamp>>,
    dawns: Query<(Entity, &HubDawn, &HubImage, &HubDawnMask)>,
    mut reveals: ResMut<Assets<DawnReveal>>,
) {
    anim.clock += time.delta_secs().min(0.1);
    let clock = anim.clock;
    anim.lighting.retain(|(_, at)| clock - at < LIGHT_LEN + 1.0);
    let HubAnim { lighting, sparked, .. } = &mut *anim;
    sparked.retain(|(id, _)| lighting.iter().any(|(l, _)| l == id));
    if anim.dawn.as_ref().is_some_and(|(_, at)| clock - at > DAWN_LEN + 1.0) {
        anim.dawn = None;
    }
    let Some(mut news) = news else { return };
    if lamps.is_empty() {
        return;
    }
    if !news.lit.is_empty() {
        let lit = std::mem::take(&mut news.lit);
        for (k, id) in lit.into_iter().enumerate() {
            anim.lighting.push((id, clock + LIGHT_DELAY + k as f32 * LIGHT_STAGGER));
        }
    }
    if let Some(region) = news.dawn.take() {
        // 那一层从普通的图换成按灰度图铺开的材质（铺完就停在整幅，不再换回去）
        for (e, d, image, mask) in &dawns {
            if d.region == region && d.part == DawnPart::Image {
                let m = DawnReveal {
                    params: Vec4::new(0.0, 0.08, 0.25, 1.0),
                    image: assets.load(&image.0),
                    mask: assets.load(&mask.0),
                };
                commands.entity(e).remove::<ImageNode>().insert(MaterialNode(reveals.add(m)));
            }
        }
        anim.dawn = Some((region, clock + DAWN_DELAY));
    }
}

/// 每盏灯一个相位，摇曳的节拍错开。
fn phase(id: &str) -> f32 {
    let h = id.bytes().fold(2166136261u32, |h, b| (h ^ u32::from(b)).wrapping_mul(16777619));
    (h % 1000) as f32 / 1000.0
}

fn smooth(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}

/// 平时：火苗每秒抖六七下、幅度很小，内圈光跟着火苗，外圈光晕约 3 秒一次慢慢呼吸。
/// 点亮：火苗从底部长出来，内圈闪一下，外圈胀开再落定，灯身跟着淡入，飘几颗余烬，纸上荡开一圈光。
#[expect(clippy::type_complexity)]
fn animate_lamps(
    mut commands: Commands,
    content: Res<GameContent>,
    mut anim: ResMut<HubAnim>,
    tex: Option<Res<HubTex>>,
    images: Res<Assets<Image>>,
    mut adds: ResMut<Assets<UiAdd>>,
    mut q: Query<(
        Entity,
        &HubLamp,
        &ComputedNode,
        &mut UiTransform,
        Option<&mut ImageNode>,
        Option<&MaterialNode<UiAdd>>,
        Option<&HubFlameBase>,
    )>,
) {
    let t = anim.clock;
    for (e, lamp, node, mut tf, img, mat, base) in &mut q {
        let ph = phase(&lamp.id);
        let flick =
            0.5 * (t * 13.7 + ph * 20.0).sin() + 0.3 * (t * 23.1 + ph * 7.0).sin() + 0.2 * (t * 7.3).sin();
        let breath = (t * TAU / 3.2 + ph * TAU).sin();
        // 点亮了多久：还没轮到它时整盏不亮，播完以后照平时
        let lit = anim.lit_for(&lamp.id).map(|u| if u > LIGHT_LEN { f32::INFINITY } else { u });
        let u = lit.unwrap_or(f32::INFINITY);
        let (alpha, scale) = match lamp.part {
            LampPart::Body => (smooth((u - 0.05) / 0.3), Vec2::ONE),
            LampPart::Flame => {
                // 从底部长出来：0 → 1.15 → 1（0.25 秒），之后照平时抖
                let grow = if u < 0.25 {
                    let k = u.max(0.0) / 0.25;
                    1.15 * smooth(k * 1.4)
                } else {
                    1.0 + 0.15 * (-(u - 0.25) * 9.0).exp()
                };
                let s = Vec2::new(1.0 + 0.04 * flick, 1.0 + 0.07 * flick) * grow;
                ((u / 0.06).clamp(0.0, 1.0), s)
            }
            LampPart::Core => {
                let flash =
                    if u < 0.12 { u.max(0.0) / 0.12 * 1.4 } else { 1.0 + 0.4 * (-(u - 0.12) * 5.0).exp() };
                (flash * (0.92 + 0.08 * flick), Vec2::splat(0.6 + 0.4 * smooth(u / 0.15)))
            }
            LampPart::Glow => {
                // 0.8 秒里从 0.6 胀到 1.1 再回到 1
                let swell = if u < 0.5 {
                    0.6 + 0.5 * smooth(u / 0.5)
                } else {
                    1.0 + 0.1 * (1.0 - smooth((u - 0.5) / 0.3))
                };
                let a = smooth(u / 0.35) * (1.0 + 0.2 * (1.0 - smooth((u - 0.4) / 0.6)));
                (a * (0.95 + 0.05 * breath), Vec2::splat(swell * (1.0 + 0.015 * breath)))
            }
        };
        tf.scale = scale;
        // 火苗绕底部那一点缩放：节点按中心缩放，挪回去
        if let (Some(base), Some(img)) = (base, &img)
            && let Some(size) = images.get(&img.image).map(|i| i.size().as_vec2())
        {
            let logical = node.size() * node.inverse_scale_factor();
            let d = (base.0 / size - Vec2::splat(0.5)) * logical;
            tf.translation = Val2::px(d.x * (1.0 - scale.x), d.y * (1.0 - scale.y));
        }
        if let Some(mut img) = img {
            img.color.set_alpha(alpha.clamp(0.0, 1.0));
        }
        if let Some(mat) = mat
            && let Some(mut m) = adds.get_mut(&mat.0)
        {
            // 光晕的底子按“等级 ÷ 最大等级”（hub_scene 定的），点亮和呼吸乘在上面
            let base = if lamp.part == LampPart::Glow {
                let max = content.0.meta.nodes.iter().find(|n| n.id == lamp.id).map_or(1, |n| n.max_level);
                glow_alpha(lamp.level.max(1), max)
            } else {
                1.0
            };
            m.color.w = alpha.max(0.0) * base;
        }
        // 点亮的那一下：火苗上飘余烬，光晕下荡开一圈光（每盏只放一次）
        let Some(tex) = &tex else { continue };
        let Some(u) = lit else { continue };
        let key = (lamp.id.clone(), lamp.part);
        if u < 0.1 || anim.sparked.contains(&key) {
            continue;
        }
        anim.sparked.push(key);
        match lamp.part {
            LampPart::Flame => {
                for k in 0..7 {
                    let a = ph * TAU + k as f32 * 0.9;
                    let from = Vec2::new(50.0 + 20.0 * a.cos(), 30.0);
                    let vel = Vec2::new(60.0 * a.sin(), -260.0 - 50.0 * (k % 3) as f32);
                    spawn_spark(
                        &mut commands,
                        &mut adds,
                        e,
                        tex.dot.clone(),
                        from,
                        vel,
                        0.9 + 0.12 * k as f32,
                        (0.3, 0.15),
                        1.3,
                    );
                }
            }
            LampPart::Glow => {
                spawn_spark(
                    &mut commands,
                    &mut adds,
                    e,
                    tex.ring.clone(),
                    Vec2::splat(50.0),
                    Vec2::ZERO,
                    1.0,
                    (0.15, 1.1),
                    0.4,
                );
            }
            _ => {}
        }
    }
}

#[expect(clippy::too_many_arguments)]
fn spawn_spark(
    commands: &mut Commands,
    adds: &mut Assets<UiAdd>,
    parent: Entity,
    image: Handle<Image>,
    from: Vec2,
    vel: Vec2,
    life: f32,
    grow: (f32, f32),
    strength: f32,
) {
    let material = adds.add(UiAdd { color: WARM.extend(0.0), image });
    // 余烬是火苗宽度的 30%，光圈和光晕一样大
    let size = if grow.1 > 0.5 { 100.0 } else { 30.0 };
    commands.entity(parent).with_child((
        Spark { t: 0.0, life, from, vel, grow, strength },
        Node {
            position_type: PositionType::Absolute,
            left: percent(from.x - size * 0.5),
            top: percent(from.y - size * 0.5),
            width: percent(size),
            height: percent(size),
            ..default()
        },
        MaterialNode(material),
        UiTransform::from_scale(Vec2::splat(grow.0)),
    ));
}

fn animate_sparks(
    mut commands: Commands,
    time: Res<Time<Real>>,
    mut adds: ResMut<Assets<UiAdd>>,
    mut q: Query<(Entity, &mut Spark, &mut UiTransform, &MaterialNode<UiAdd>)>,
) {
    let dt = time.delta_secs().min(0.1);
    for (e, mut s, mut tf, mat) in &mut q {
        s.t += dt;
        if s.t >= s.life {
            commands.entity(e).despawn();
            continue;
        }
        let k = s.t / s.life;
        let off = s.vel * s.t;
        tf.translation = Val2::percent(off.x, off.y);
        let ring = s.grow.1 > 0.5;
        let grow = s.grow.0 + (s.grow.1 - s.grow.0) * (1.0 - (1.0 - k).powi(2));
        tf.scale = Vec2::splat(if ring { grow } else { s.grow.0 * (1.0 - 0.6 * k) });
        if let Some(mut m) = adds.get_mut(&mat.0) {
            // 余烬忽明忽暗地淡去；光圈越胀越淡
            let flicker = if ring { 1.0 } else { 0.75 + 0.25 * (s.t * 31.0 + s.from.x).sin() };
            m.color.w = s.strength * (1.0 - k) * flicker * (s.t / 0.08).min(1.0);
        }
    }
}

/// 晨光：平时整幅显示（山脊金光微微起伏）；第一次天明回来时按灰度图铺开，铺到七八成时金光亮一下。
fn animate_dawn(
    anim: Res<HubAnim>,
    mut reveals: ResMut<Assets<DawnReveal>>,
    mut adds: ResMut<Assets<UiAdd>>,
    q: Query<(&HubDawn, Option<&MaterialNode<DawnReveal>>, Option<&MaterialNode<UiAdd>>)>,
) {
    let t = anim.clock;
    for (dawn, reveal, add) in &q {
        let p = match &anim.dawn {
            Some((region, at)) if *region == dawn.region => smooth((t - at) / DAWN_LEN),
            _ => 1.0,
        };
        if let Some(r) = reveal
            && let Some(mut m) = reveals.get_mut(&r.0)
        {
            m.params.x = p;
        }
        if let Some(a) = add
            && let Some(mut m) = adds.get_mut(&a.0)
        {
            let bump = |x: f32| (-((x - 0.85) * 9.0).powi(2)).exp();
            let flare = 1.0 + 0.6 * (bump(p) - bump(1.0)).max(0.0);
            let shimmer = 0.94 + 0.06 * (t * TAU / 4.5 + phase(&dawn.region) * TAU).sin();
            m.color.w = smooth((p - 0.45) / 0.4) * flare * shimmer;
        }
    }
}
