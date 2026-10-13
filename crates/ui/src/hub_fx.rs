//! 灯驿长卷的动画（docs/FEEL.md 第 9 节）：心灯亮起、地区晨光铺开、平时灯火摇曳。
//! 复用青丘纸卷，程序化墨树与灯盏。只读存档投影，亮灯确认交给平台命令。

use bevy::asset::RenderAssetUsages;
use bevy::asset::embedded_asset;
use bevy::picking::Pickable;
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, Extent3d, TextureDimension, TextureFormat};
use bevy::shader::ShaderRef;
use bevy::ui::widget::NodeImageMode;
use lantern_content::Content;
use lantern_platform::profile::HUB_RETURN_MILESTONES;
use lantern_platform::{Actions, Profile};

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

impl DawnReveal {
    pub(crate) fn new(image: Handle<Image>, mask: Handle<Image>) -> Self {
        DawnReveal { params: Vec4::new(0.0, 0.08, 0.25, 1.0), image, mask }
    }
}

impl UiMaterial for DawnReveal {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_ui/dawn_reveal.wesl".into()
    }
}

pub(crate) fn register(app: &mut App) {
    embedded_asset!(app, "dawn_reveal.wesl");
    embedded_asset!(app, "hub_lanterns.wesl");
    app.add_plugins((UiMaterialPlugin::<DawnReveal>::default(), UiMaterialPlugin::<HubLanterns>::default()))
        .add_systems(Startup, load)
        .add_systems(Update, animate);
}

#[derive(AsBindGroup, Asset, TypePath, Debug, Clone)]
pub(crate) struct HubLanterns {
    #[uniform(0)]
    params: Vec4,
    #[uniform(0)]
    lights: [Vec4; 64],
}

impl UiMaterial for HubLanterns {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_ui/hub_lanterns.wesl".into()
    }
}

#[derive(Resource)]
pub(crate) struct ScrollArt {
    night: Handle<Image>,
    dawn: Handle<Image>,
    mask: Handle<Image>,
}

fn load(mut commands: Commands, assets: Res<AssetServer>, mut images: ResMut<Assets<Image>>) {
    // 从左向右、带少量纸痕起伏的灰度阈值图。
    let mut mask = Image::new_fill(
        Extent3d { width: 256, height: 32, depth_or_array_layers: 1 },
        TextureDimension::D2,
        &[0, 0, 0, 255],
        TextureFormat::Rgba8Unorm,
        RenderAssetUsages::default(),
    );
    if let Some(data) = &mut mask.data {
        for (i, pixel) in data.as_chunks_mut::<4>().0.iter_mut().enumerate() {
            let x = (i % 256) as f32;
            let y = (i / 256) as f32;
            let v = (x + (y * 0.6 + x * 0.08).sin() * 4.0).clamp(0.0, 255.0) as u8;
            pixel.copy_from_slice(&[v, v, v, 255]);
        }
    }
    commands.insert_resource(ScrollArt {
        night: assets.load("atlas/screens/scroll_qingqiu.png"),
        dawn: assets.load("atlas/screens/scroll_qingqiu_dawn.png"),
        mask: images.add(mask),
    });
}

#[derive(Component)]
struct ScrollAnimation {
    t: f32,
    fresh: bool,
    lamps: Handle<HubLanterns>,
    dawn: Handle<DawnReveal>,
}

/// 位置固定在节点与等级上，不按购买先后重排。
fn slots(c: &Content) -> Vec<(String, Vec2)> {
    let mut out = Vec::new();
    for n in &c.meta.nodes {
        for lv in 1..=n.max_level {
            let i = out.len();
            let tree = i / 13;
            let local = i % 13;
            let row = local / 5;
            let col = local % 5;
            let x = 0.08 + tree as f32 * 0.30 + col as f32 * 0.045;
            let y = 0.28 + row as f32 * 0.20 + (2.0 - col as f32).abs() * -0.015;
            out.push((format!("meta/{}/{lv}", n.id), Vec2::new(x, y)));
        }
    }
    for (i, n) in HUB_RETURN_MILESTONES.iter().enumerate() {
        let x = 0.08 + i as f32 * 0.059;
        out.push((format!("return/{n}"), Vec2::new(x, 0.90 - (x * 6.0).sin() * 0.035)));
    }
    for t in 1..=c.difficulty.len() {
        out.push((format!("dawn/{t}"), Vec2::new(0.68 + t as f32 * 0.044, 0.28 - t as f32 * 0.021)));
    }
    out
}

fn sheet() -> Node {
    Node { position_type: PositionType::Absolute, width: percent(100), height: percent(100), ..default() }
}

/// 卷中灯树、归途与远山；所有装饰忽略拾取，不遮挡人物与跳过按钮。
pub(crate) fn spawn(
    parent: &mut ChildSpawnerCommands,
    c: &Content,
    p: &Profile,
    art: &ScrollArt,
    lanterns: &mut Assets<HubLanterns>,
    dawns: &mut Assets<DawnReveal>,
) {
    let lit = p.hub_lights(c);
    let new_count = lit.difference(&p.hub_lights_seen).count();
    let positions = slots(c);
    let mut lights = [Vec4::ZERO; 64];
    let mut new_index = 0;
    for (i, (id, pos)) in positions.iter().take(64).enumerate() {
        let on = lit.contains(id);
        let delay = if on && !p.hub_lights_seen.contains(id) {
            let delay = new_index as f32 * (1.2 / new_count.max(1) as f32);
            new_index += 1;
            delay
        } else {
            -1.0
        };
        lights[i] = Vec4::new(pos.x, pos.y, if on { 1.0 } else { 0.0 }, delay);
    }
    let strength = 1.0 + p.meta_levels(c) as f32 * 0.012 + p.wins.min(10) as f32 * 0.015;
    let lamps = lanterns
        .add(HubLanterns { params: Vec4::new(0.0, 0.0, positions.len().min(64) as f32, strength), lights });
    let seen = lit.intersection(&p.hub_lights_seen).count();
    let opacity = |n: usize| (n as f32 * 0.009).min(0.42);
    let old = opacity(seen);
    let mut reveal = DawnReveal::new(art.dawn.clone(), art.mask.clone());
    reveal.params.w = (opacity(lit.len()) - old) / (1.0 - old);
    let dawn = dawns.add(reveal);
    parent
        .spawn((
            Node {
                width: percent(100),
                aspect_ratio: Some(3.4),
                flex_shrink: 0.0,
                overflow: Overflow::clip(),
                ..default()
            },
            ScrollAnimation { t: 0.0, fresh: new_count > 0, lamps: lamps.clone(), dawn: dawn.clone() },
            Pickable::IGNORE,
        ))
        .with_children(|scene| {
            scene.spawn((
                sheet(),
                ImageNode::new(art.night.clone())
                    .with_mode(NodeImageMode::Stretch)
                    .with_color(Color::srgb(0.46, 0.51, 0.53)),
                Pickable::IGNORE,
            ));
            scene.spawn((
                sheet(),
                ImageNode::new(art.dawn.clone())
                    .with_mode(NodeImageMode::Stretch)
                    .with_color(Color::WHITE.with_alpha(old)),
                Pickable::IGNORE,
            ));
            scene.spawn((sheet(), MaterialNode(dawn), Pickable::IGNORE));
            scene.spawn((sheet(), MaterialNode(lamps), Pickable::IGNORE));
        });
}

fn animate(
    time: Res<Time<Real>>,
    actions: Res<Actions>,
    mut scenes: Query<&mut ScrollAnimation>,
    mut lanterns: ResMut<Assets<HubLanterns>>,
    mut dawns: ResMut<Assets<DawnReveal>>,
) {
    for mut scene in &mut scenes {
        // X / 手柄西键直接落到常亮；其余操作照常交给人物导航，不被演出吞掉。
        if actions.skip && scene.t > 0.0 {
            scene.t = 6.0;
        }
        scene.t += time.delta_secs().min(0.1);
        if let Some(mut m) = lanterns.get_mut(&scene.lamps) {
            m.params.x = if scene.fresh { scene.t } else { 6.0 };
            m.params.y = time.elapsed_secs_wrapped();
        }
        if let Some(mut m) = dawns.get_mut(&scene.dawn) {
            m.params.x = ((scene.t - 0.8) / 3.0).clamp(0.0, 1.0);
        }
    }
}

/// 鼠标跳过不参与人物索引，避免改变当前焦点。
pub(crate) fn skip_on_click(button: &mut EntityCommands) {
    button.observe(|_: On<bevy::picking::events::PointerClick>, mut scenes: Query<&mut ScrollAnimation>| {
        for mut scene in &mut scenes {
            scene.t = 6.0;
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_saved_light_has_one_stable_slot() {
        let c = Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
            .unwrap();
        let mut p = Profile::default();
        p.runs = 100;
        p.cleared = c.difficulty.len() as u8;
        p.meta = c.meta.nodes.iter().map(|n| (n.id.clone(), n.max_level)).collect();
        let slots = slots(&c);
        assert!(slots.len() <= 64);
        let ids: std::collections::BTreeSet<_> = slots.iter().map(|(id, _)| id.clone()).collect();
        assert_eq!(ids.len(), slots.len());
        assert_eq!(ids, p.hub_lights(&c));
        assert!(slots.iter().all(|(_, xy)| xy.x > 0.0 && xy.x < 1.0 && xy.y > 0.0 && xy.y < 1.0));
    }
}
