//! 灯驿长卷（docs/GAMEPLAY.md 第 11.6 节；格式见 docs/DESIGN.md 第 15 节“灯驿长卷”）。
//!
//! 美术的 `assets/atlas/screens/hub/hub.json` 给出底图和各层在 1920 × 1080 图里的位置。灯驿和它下面的
//! 四处一直铺着这幅长卷（按“铺满再居中裁边”缩放），代替标题画：
//! - 四个人物各有点击区和聚光，选中的那位身上亮一团暖光；
//! - 心灯 12 盏，节点等级 > 0 就亮（灯身、火苗、灯芯、光晕四层，光晕按“等级 ÷ 最大等级”）；
//! - 通关过的地区，远山上铺着晨光（P0 只有青丘：通关一更）。
//!
//! 长卷的节点只在进出灯驿时建、拆，选中项变了不重建，质感会话的 `hub_fx` 可以在上面播动画：
//! 它读 [`HubLamp`]、[`HubDawn`] 这些标记，只改透明度、缩放、颜色，不改布局。
//! 人物名牌、台词、标题和提示是界面面板（[`labels`]），跟着选中项重画。

use std::collections::BTreeMap;

use bevy::asset::{RenderAssetUsages, embedded_asset};
use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;
use bevy::render::render_resource::{
    AsBindGroup, BlendComponent, BlendFactor, BlendOperation, BlendState, Extent3d, RenderPipelineDescriptor,
    TextureDimension, TextureFormat,
};
use bevy::shader::ShaderRef;
use bevy::ui::widget::NodeImageMode;
use bevy::ui_render::ui_material::UiMaterialKey;
use serde::Deserialize;

use lantern_content::Content;
use lantern_platform::{HubNews, Profile, paths};
use lantern_sim::AppState;

use crate::cover::Cover;
use crate::title::{TitleMode, TitleUi};
use crate::{DIM, Fonts, PAPER, hub, text};

const DIR: &str = "atlas/screens/hub";

#[derive(Deserialize, Clone, Debug)]
struct Character {
    rect: [f32; 4],
    /// 名牌那块文字的上沿中点
    label: [f32; 2],
    /// 选中时的聚光：x、y、半径
    light: [f32; 3],
}

#[derive(Deserialize, Clone, Debug)]
struct Layer {
    file: String,
    rect: [f32; 4],
    /// 火苗的底（摇曳绕着它）
    #[serde(default)]
    base: Option<[f32; 2]>,
}

#[derive(Deserialize, Clone, Debug)]
struct Lamp {
    body: Layer,
    flame: Layer,
    core: Layer,
    glow: Layer,
}

#[derive(Deserialize, Clone, Debug)]
struct Dawn {
    file: String,
    rect: [f32; 4],
    mask: String,
    #[serde(default)]
    glow: Option<Layer>,
}

/// hub.json（不认识的字段忽略）。
#[derive(Deserialize, Clone, Debug)]
struct HubJson {
    size: [f32; 2],
    characters: Vec<Character>,
    lamps: BTreeMap<String, Lamp>,
    #[serde(default)]
    dawn: BTreeMap<String, Dawn>,
    /// 画面安静、可以放字的地方：左上角的标题和钱袋、底部的操作提示
    #[serde(default)]
    text_safe: Vec<[f32; 4]>,
}

/// 读好的长卷；没有 hub.json 时不插入，灯驿退回到卡片界面。
#[derive(Resource)]
pub(crate) struct HubScene {
    json: HubJson,
    /// 人物聚光用的径向渐变（程序生成）
    light: Handle<Image>,
}

impl HubScene {
    pub(crate) fn size(&self) -> Vec2 {
        Vec2::from(self.json.size)
    }
}

// ---- 给质感会话的动画用的标记 ----

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum LampPart {
    Body,
    Flame,
    Core,
    Glow,
}

/// 一盏心灯的一层。`level` 是建节点或上次刷新时这个节点的等级。
#[derive(Component, Clone, Debug)]
pub(crate) struct HubLamp {
    pub id: String,
    pub part: LampPart,
    pub level: u32,
}

/// 火苗的底在这一层里的位置（hub.json 的像素，层的左上角为原点，y 向下）。
#[derive(Component, Clone, Copy, Debug)]
#[expect(dead_code, reason = "给 hub_fx 的摇曳动画读，那边接上以前没人读")]
pub(crate) struct HubFlameBase(pub Vec2);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum DawnPart {
    Image,
    Glow,
}

/// 一个地区的晨光。Image 那层默认是普通的 `ImageNode`，要铺开时由 `hub_fx` 换成 `DawnReveal` 材质。
#[derive(Component, Clone, Debug)]
#[expect(dead_code, reason = "给 hub_fx 的晨光动画读，那边接上以前没人读")]
pub(crate) struct HubDawn {
    pub region: String,
    pub part: DawnPart,
}

/// 晨光铺开用的灰度图（assets 路径）。
#[derive(Component, Clone, Debug)]
#[expect(dead_code, reason = "给 hub_fx 的晨光动画读，那边接上以前没人读")]
pub(crate) struct HubDawnMask(pub String);

/// 这一层贴图的 assets 路径（`hub_fx` 换材质、重设贴图时用）。
#[derive(Component, Clone, Debug)]
#[expect(dead_code, reason = "给 hub_fx 读，那边接上以前没人读")]
pub(crate) struct HubImage(pub String);

/// 人物的聚光（第几个人物）。
#[derive(Component, Clone, Copy, Debug)]
pub(crate) struct HubLight(pub usize);

#[derive(Component)]
pub(crate) struct SceneRoot;

// ---- 叠加材质 ----

/// 界面上的叠加层：画面 += 贴图 RGB × alpha × 颜色（`ui_add.wesl`）。
#[derive(AsBindGroup, Asset, TypePath, Debug, Clone)]
pub(crate) struct UiAdd {
    #[uniform(0)]
    pub color: Vec4,
    #[texture(1)]
    #[sampler(2)]
    pub image: Handle<Image>,
}

impl UiMaterial for UiAdd {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_ui/ui_add.wesl".into()
    }

    fn specialize(descriptor: &mut RenderPipelineDescriptor, _key: UiMaterialKey<Self>) {
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
        if let Some(target) =
            descriptor.fragment.as_mut().and_then(|f| f.targets.first_mut()).and_then(|t| t.as_mut())
        {
            target.blend = Some(BlendState { color: add, alpha: keep });
        }
    }
}

pub(crate) fn register(app: &mut App) {
    embedded_asset!(app, "ui_add.wesl");
    // 建、刷长卷的系统排在标题界面的系统链里（title::register）
    app.add_plugins(UiMaterialPlugin::<UiAdd>::default()).add_systems(Startup, load);
}

/// 径向渐变：中心亮、边上全透明（白色，用时乘颜色）。
fn radial(size: u32) -> Image {
    let mut data = Vec::with_capacity((size * size * 4) as usize);
    let c = (size as f32 - 1.0) / 2.0;
    for y in 0..size {
        for x in 0..size {
            let d = (((x as f32 - c).powi(2) + (y as f32 - c).powi(2)).sqrt() / c).min(1.0);
            let a = (1.0 - d * d) * (1.0 - d * d);
            data.extend_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
        }
    }
    Image::new(
        Extent3d { width: size, height: size, depth_or_array_layers: 1 },
        TextureDimension::D2,
        data,
        TextureFormat::Rgba8UnormSrgb,
        RenderAssetUsages::RENDER_WORLD,
    )
}

fn load(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let path = paths::asset_dir().join(DIR).join("hub.json");
    let json = match std::fs::read_to_string(&path).map(|t| serde_json::from_str::<HubJson>(&t)) {
        Ok(Ok(j)) => j,
        Err(_) => return,
        Ok(Err(e)) => {
            warn!("灯驿长卷 {} 读取失败：{e}，灯驿改用卡片界面", path.display());
            return;
        }
    };
    commands.insert_resource(HubScene { json, light: images.add(radial(128)) });
}

/// 灯驿和它下面四处铺长卷。
fn in_hub(mode: &TitleMode) -> bool {
    matches!(
        mode,
        TitleMode::Hub | TitleMode::Meta | TitleMode::Shop | TitleMode::Achievements | TitleMode::Codex
    )
}

/// hub.json 里的矩形换成长卷里的百分比位置。
fn place(scene: &HubScene, [x, y, w, h]: [f32; 4]) -> Node {
    let [sw, sh] = scene.json.size;
    Node {
        position_type: PositionType::Absolute,
        left: percent(x / sw * 100.0),
        top: percent(y / sh * 100.0),
        width: percent(w / sw * 100.0),
        height: percent(h / sh * 100.0),
        ..default()
    }
}

fn file(name: &str) -> String {
    format!("{DIR}/{name}")
}

/// P0 只有青丘：通关过一更就算这里天明过（以后按地区记通关）。
fn dawned(profile: &Profile, region: &str, content: &Content) -> bool {
    profile.cleared >= 1 && content.regions.first().is_some_and(|r| r.id == region)
}

fn shown(on: bool) -> Visibility {
    if on { Visibility::Inherited } else { Visibility::Hidden }
}

/// 进出灯驿时建、拆长卷，标题画跟着藏起、露出。
#[allow(clippy::too_many_arguments)]
pub(crate) fn sync_scene(
    mut commands: Commands,
    scene: Option<Res<HubScene>>,
    mode: Res<TitleMode>,
    content: Res<lantern_sim::GameContent>,
    profile: Res<Profile>,
    assets: Res<AssetServer>,
    mut adds: ResMut<Assets<UiAdd>>,
    roots: Query<Entity, With<SceneRoot>>,
    mut title_bg: Query<&mut Visibility, (With<crate::title_fx::TitleBg>, Without<SceneRoot>)>,
) {
    let Some(scene) = scene else { return };
    let want = in_hub(&mode);
    let have = !roots.is_empty();
    for mut v in &mut title_bg {
        v.set_if_neq(shown(!want));
    }
    if want == have {
        return;
    }
    if !want {
        for e in &roots {
            commands.entity(e).despawn();
        }
        return;
    }
    let c = &content.0;
    let mut add = |image: Handle<Image>, color: Vec4| MaterialNode(adds.add(UiAdd { color, image }));
    let j = &scene.json;
    commands
        .spawn((
            SceneRoot,
            DespawnOnExit(AppState::Title),
            GlobalZIndex(-1),
            Node { position_type: PositionType::Absolute, overflow: Overflow::clip(), ..default() },
            Cover(scene.size()),
        ))
        .with_children(|root| {
            root.spawn((
                Node { width: percent(100), height: percent(100), ..default() },
                ImageNode::new(assets.load(file("hub.png"))).with_mode(NodeImageMode::Stretch),
            ));
            // 远山的晨光
            for (region, d) in &j.dawn {
                let on = shown(dawned(&profile, region, c));
                root.spawn((
                    place(&scene, d.rect),
                    ImageNode::new(assets.load(file(&d.file))).with_mode(NodeImageMode::Stretch),
                    HubDawn { region: region.clone(), part: DawnPart::Image },
                    HubImage(file(&d.file)),
                    HubDawnMask(file(&d.mask)),
                    on,
                ));
                if let Some(g) = &d.glow {
                    root.spawn((
                        place(&scene, g.rect),
                        add(assets.load(file(&g.file)), Vec4::ONE),
                        HubDawn { region: region.clone(), part: DawnPart::Glow },
                        HubImage(file(&g.file)),
                        on,
                    ));
                }
            }
            // 心灯：按 meta.ron 的顺序
            for node in &c.meta.nodes {
                let Some(l) = j.lamps.get(&node.id) else { continue };
                let level = profile.meta.get(&node.id).copied().unwrap_or(0);
                let on = shown(level > 0);
                let mark = |part| HubLamp { id: node.id.clone(), part, level };
                for (layer, part) in [(&l.body, LampPart::Body), (&l.flame, LampPart::Flame)] {
                    let mut e = root.spawn((
                        place(&scene, layer.rect),
                        ImageNode::new(assets.load(file(&layer.file))).with_mode(NodeImageMode::Stretch),
                        mark(part),
                        HubImage(file(&layer.file)),
                        on,
                    ));
                    if let Some([bx, by]) = layer.base {
                        e.insert(HubFlameBase(Vec2::new(bx - layer.rect[0], by - layer.rect[1])));
                    }
                }
                root.spawn((
                    place(&scene, l.core.rect),
                    add(assets.load(file(&l.core.file)), Vec4::ONE),
                    mark(LampPart::Core),
                    HubImage(file(&l.core.file)),
                    on,
                ));
                let glow = glow_alpha(level, node.max_level);
                root.spawn((
                    place(&scene, l.glow.rect),
                    add(assets.load(file(&l.glow.file)), Vec4::new(1.0, 1.0, 1.0, glow)),
                    mark(LampPart::Glow),
                    HubImage(file(&l.glow.file)),
                    on,
                ));
            }
            // 人物：聚光（选中时亮）和点击区
            for (i, ch) in j.characters.iter().enumerate() {
                let [x, y, r] = ch.light;
                root.spawn((
                    place(&scene, [x - r, y - r, r * 2.0, r * 2.0]),
                    add(scene.light.clone(), Vec4::new(1.0, 0.78, 0.5, 0.55)),
                    HubLight(i),
                    Visibility::Hidden,
                ));
                let mut hit = root.spawn(place(&scene, ch.rect));
                hit.observe(move |_: On<PointerClick>, mode: Res<TitleMode>, mut ui: ResMut<TitleUi>| {
                    if *mode == TitleMode::Hub {
                        ui.clicked = Some(i);
                    }
                });
                hit.observe(move |_: On<PointerOver>, mode: Res<TitleMode>, mut ui: ResMut<TitleUi>| {
                    if *mode == TitleMode::Hub {
                        ui.hovered = Some(i);
                    }
                });
            }
        });
}

/// 光晕亮度：按“等级 ÷ 最大等级”，最暗也有六成。
fn glow_alpha(level: u32, max: u32) -> f32 {
    if level == 0 { 0.0 } else { 0.6 + 0.4 * level as f32 / max.max(1) as f32 }
}

/// 心灯等级变了就亮起、调光晕；选中的人物身上亮聚光，换了人就重画名牌和台词。
#[allow(clippy::too_many_arguments)]
pub(crate) fn refresh_scene(
    content: Res<lantern_sim::GameContent>,
    profile: Res<Profile>,
    mode: Res<TitleMode>,
    mut ui: ResMut<TitleUi>,
    window: Single<&Window, With<bevy::window::PrimaryWindow>>,
    mut last: Local<Option<(usize, UVec2)>>,
    mut adds: ResMut<Assets<UiAdd>>,
    mut lamps: Query<(&mut HubLamp, &mut Visibility, Option<&MaterialNode<UiAdd>>), Without<HubLight>>,
    mut lights: Query<(&HubLight, &mut Visibility), Without<HubLamp>>,
) {
    for (mut lamp, mut vis, mat) in &mut lamps {
        let level = profile.meta.get(&lamp.id).copied().unwrap_or(0);
        if level == lamp.level {
            continue;
        }
        lamp.level = level;
        vis.set_if_neq(shown(level > 0));
        if lamp.part == LampPart::Glow
            && let Some(mut m) = mat.and_then(|m| adds.get_mut(&m.0))
        {
            let max = content.0.meta.nodes.iter().find(|n| n.id == lamp.id).map_or(1, |n| n.max_level);
            m.color.w = glow_alpha(level, max);
        }
    }
    for (light, mut vis) in &mut lights {
        vis.set_if_neq(shown(*mode == TitleMode::Hub && ui.selected == light.0));
    }
    let size = UVec2::new(window.width() as u32, window.height() as u32);
    let now = (*mode == TitleMode::Hub).then_some((ui.selected, size));
    if now != *last {
        *last = now;
        if now.is_some() {
            ui.dirty = true;
        }
    }
}

/// 灯驿首页的字：左上角“灯驿”和钱袋，每个人物的名牌（选中的那位多一句台词），底部操作提示。
/// 位置按长卷当前的缩放换算成屏幕像素。
#[allow(clippy::too_many_arguments)]
pub(crate) fn labels(
    commands: &mut Commands,
    scene: &HubScene,
    c: &Content,
    fonts: &Fonts,
    profile: &Profile,
    news: &HubNews,
    selected: usize,
    window: Vec2,
) {
    let (s, at) = Cover(scene.size()).fit(window);
    let to = |x: f32, y: f32| at + Vec2::new(x, y) * s;
    // 窗口比长卷窄很多时（接近 4:3），两边裁掉的比安全区还多：放字的矩形夹回窗口里
    let margin = 16.0;
    let clamp = |o: Vec2, w: f32| {
        let w = w.min(window.x - 2.0 * margin);
        (Vec2::new(o.x.clamp(margin, window.x - margin - w), o.y), w)
    };
    let size = |px_at_1920: f32, min: f32| (px_at_1920 * s).max(min);
    let j = &scene.json;
    commands
        .spawn((
            crate::title::TitlePanel,
            DespawnOnExit(AppState::Title),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                ..default()
            },
        ))
        .with_children(|p| {
            // 左上角：标题和钱袋
            if let Some(&[x, y, w, _]) = j.text_safe.first() {
                let (o, w) = clamp(to(x, y), w * s);
                p.spawn(Node {
                    position_type: PositionType::Absolute,
                    left: px(o.x),
                    top: px(o.y),
                    width: px(w),
                    align_items: AlignItems::Baseline,
                    column_gap: px(size(24.0, 10.0)),
                    ..default()
                })
                .with_children(|t| {
                    t.spawn(text(&fonts.title, size(56.0, 28.0), PAPER, "灯驿"));
                    t.spawn(text(&fonts.body, size(24.0, 14.0), hex_gold(), &hub::purses(profile)));
                });
            }
            // 名牌：名字、行当
            for (i, ch) in j.characters.iter().enumerate() {
                let (who, what, _) = hub::HUB[i.min(hub::HUB.len() - 1)];
                let o = to(ch.label[0], ch.label[1]);
                let w = 420.0 * s;
                let sel = i == selected;
                p.spawn(Node {
                    position_type: PositionType::Absolute,
                    left: px(o.x - w / 2.0),
                    top: px(o.y),
                    width: px(w),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    row_gap: px(size(4.0, 2.0)),
                    ..default()
                })
                .with_children(|l| {
                    let name = if sel { PAPER } else { PAPER.with_alpha(0.75) };
                    l.spawn(text(&fonts.title, size(39.0, 20.0), name, who));
                    l.spawn(text(&fonts.body, size(21.0, 12.0), DIM, &format!("{what}　{}", i + 1)));
                });
            }
            // 底部那条：选中的人物说的一句在正中，操作提示靠右
            if let Some(&[x, y, w, h]) = j.text_safe.get(1) {
                let (o, w) = clamp(to(x, y), w * s);
                let band = |justify| Node {
                    position_type: PositionType::Absolute,
                    left: px(o.x),
                    top: px(o.y),
                    width: px(w),
                    height: px(h * s),
                    justify_content: justify,
                    align_items: AlignItems::Center,
                    ..default()
                };
                if let Some(line) = profile.hub_line(c, selected, news) {
                    let who = hub::HUB[selected.min(hub::HUB.len() - 1)].0;
                    p.spawn(band(JustifyContent::Center)).with_children(|t| {
                        t.spawn(text(&fonts.body, size(26.0, 14.0), PAPER, &format!("{who}：“{line}”")));
                    });
                }
                p.spawn(band(JustifyContent::End)).with_children(|t| {
                    t.spawn(text(&fonts.body, size(20.0, 12.0), DIM, "← →　Enter 进去　Esc 返回"));
                });
            }
        });
}

fn hex_gold() -> Color {
    crate::describe::hex("#FFD98A")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 美术给的 hub.json 能读，四个人物、每个心灯节点都有位置（草稿还没合入 master 时跳过）。
    #[test]
    fn hub_json_covers_people_and_lamps() {
        let path =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets").join(DIR).join("hub.json");
        let Ok(text) = std::fs::read_to_string(&path) else { return };
        let j: HubJson = serde_json::from_str(&text).unwrap();
        assert_eq!(j.characters.len(), hub::HUB.len());
        let c = Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
            .unwrap();
        for n in &c.meta.nodes {
            assert!(j.lamps.contains_key(&n.id), "长卷上没有心灯 {}", n.id);
        }
        assert!(j.dawn.contains_key("qingqiu"));
    }
}
