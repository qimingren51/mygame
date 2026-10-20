//! 物件检视的面板（docs/PLAYTEST.md 第 11 项）：左边是三维模型的画面（画面层 `lantern_view::inspect`
//! 画到贴图上），右边写名字、短句和背景故事。拖动转、滚轮或双指缩放，方向键、右摇杆转、扳机缩放，返回键合上。
//! 模型读不出来时，画面退回这件东西的卡面插画。

use std::collections::BTreeSet;

use bevy::input::gamepad::{Gamepad, GamepadButton};
use bevy::input::mouse::MouseScrollUnit;
use bevy::input::touch::Touches;
use bevy::picking::events::{PointerClick, PointerDrag, PointerDragEnd, PointerScroll};
use bevy::prelude::*;
use lantern_platform::Actions;
use lantern_view::AssetRoot;
use lantern_view::atlas::AtlasDb;
use lantern_view::inspect::{Inspect, InspectStatus, has_model};

use crate::{Fonts, INK, INK_DIM, PAPER, on_paper, skin::Skin, text};

/// 有检视模型的物件（`assets/models/inspect/<id>.glb` 在不在）；图鉴据此决定给不给“检视”。
#[derive(Resource, Default)]
pub(crate) struct InspectModels(pub BTreeSet<String>);

impl InspectModels {
    pub(crate) fn scan(root: &AssetRoot, ids: impl IntoIterator<Item = String>) -> Self {
        Self(ids.into_iter().filter(|id| has_model(root, id)).collect())
    }

    pub(crate) fn has(&self, id: &str) -> bool {
        self.0.contains(id)
    }
}

/// 检视面板上写的字和退回用的卡面插画；打开检视时一起给。
#[derive(Resource, Default, Clone)]
pub(crate) struct InspectCard {
    pub name: String,
    /// 一行小字：“法器 · 进化”“灯坠”之类
    pub kind: String,
    pub short: String,
    pub flavor: String,
    pub color: Color,
    /// 卡面插画的帧名（`ui/card_<id>`）
    pub art: String,
}

/// 打开检视：记下要写的字，交给画面层去加载模型。
pub(crate) fn open(inspect: &mut Inspect, card: &mut InspectCard, id: &str, info: InspectCard) {
    *card = info;
    inspect.open(id);
}

#[derive(Component)]
struct Panel;

/// 放三维画面的那块
#[derive(Component)]
struct View;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<InspectCard>()
        .add_systems(Startup, scan_models)
        // 排在标题界面的输入之后：合上检视的那一下返回键，不再让图鉴也跟着合上
        .add_systems(Update, (input, redraw, show_view).chain().after(crate::title::input));
}

/// 全部可检视物件的 id：法器本体、进化、异化，合璧，灯坠，灯笼（DESIGN 第 15 节“检视模型”）。
pub(crate) fn inspect_ids(c: &lantern_content::Content) -> Vec<String> {
    let mut ids = Vec::new();
    for w in &c.weapons {
        ids.push(w.id.clone());
        if w.evolution.is_some() {
            ids.push(format!("{}_evo", w.id));
        }
        if w.mutation.is_some() {
            ids.push(format!("{}_mut", w.id));
        }
    }
    ids.extend(c.fusions.iter().map(|f| f.id.clone()));
    ids.extend(c.charms.iter().map(|ch| ch.id.clone()));
    ids.extend(c.lamps.iter().map(|l| format!("lantern_{}", l.id)));
    ids
}

fn scan_models(mut commands: Commands, root: Res<AssetRoot>, content: Res<lantern_sim::GameContent>) {
    commands.insert_resource(InspectModels::scan(&root, inspect_ids(&content.0)));
}

/// 键盘、手柄、滚轮、双指：转和缩放；返回键合上。拖动在画面上的观察者里处理。
pub(crate) fn input(
    time: Res<Time<Real>>,
    actions: Res<Actions>,
    keys: Res<ButtonInput<KeyCode>>,
    gamepads: Query<&Gamepad>,
    touches: Res<Touches>,
    mut pinch: Local<Option<f32>>,
    mut inspect: ResMut<Inspect>,
) {
    if !inspect.is_open() {
        *pinch = None;
        return;
    }
    if actions.back {
        inspect.close();
        return;
    }
    let dt = time.delta_secs().min(0.1);
    let key = |k: KeyCode| if keys.pressed(k) { 1.0 } else { 0.0 };
    let mut rate = Vec2::new(
        key(KeyCode::ArrowRight) - key(KeyCode::ArrowLeft),
        key(KeyCode::ArrowDown) - key(KeyCode::ArrowUp),
    );
    let mut zoom = 0.0;
    for pad in &gamepads {
        let stick = pad.right_stick();
        if stick.length() > 0.15 {
            rate += Vec2::new(stick.x, -stick.y);
        }
        let trigger = |b: GamepadButton| pad.get(b).unwrap_or(0.0);
        zoom += (trigger(GamepadButton::RightTrigger2) - trigger(GamepadButton::LeftTrigger2)) * 4.0 * dt;
    }
    inspect.turn(rate.clamp_length_max(1.0), dt);
    // 双指捏合：两指距离变大是拉近
    let fingers: Vec<Vec2> = touches.iter().map(|t| t.position()).take(2).collect();
    if let [a, b] = fingers[..] {
        let d = a.distance(b);
        if let Some(last) = *pinch
            && last > 1.0
        {
            zoom += (d / last).ln() / 1.12f32.ln();
        }
        *pinch = Some(d);
    } else {
        *pinch = None;
    }
    if zoom != 0.0 {
        inspect.zoom(zoom);
    }
}

/// 开着就有面板，关了就收起
fn redraw(
    mut commands: Commands,
    inspect: Res<Inspect>,
    card: Res<InspectCard>,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    panels: Query<Entity, With<Panel>>,
) {
    if !inspect.is_changed() && !card.is_changed() {
        return;
    }
    let open = inspect.is_open();
    if open == !panels.is_empty() && !card.is_changed() {
        return;
    }
    for e in &panels {
        commands.entity(e).despawn();
    }
    if open {
        spawn_panel(&mut commands, &card, &fonts, &skin);
    }
}

/// 面板：深色衬底，左边画面，右边文字，下面一行操作提示。画布固定 1280 × 720，小窗口等比缩小。
fn spawn_panel(commands: &mut Commands, card: &InspectCard, fonts: &Fonts, skin: &Skin) {
    commands
        .spawn((
            Panel,
            GlobalZIndex(60),
            crate::responsive::FitViewport::Fixed(Vec2::new(1280.0, 720.0)),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                row_gap: px(14),
                ..default()
            },
            // 不透明：界面在线性空间混色，哪怕 0.98，后面图鉴的字也还看得见，和右边的字叠在一起
            BackgroundColor(Color::srgb(0.02, 0.025, 0.03)),
        ))
        .with_children(|root| {
            root.spawn(Node { column_gap: px(36), align_items: AlignItems::Center, ..default() })
                .with_children(|row| {
                    // 画面：宣纸框里放三维画面，可拖动、可滚轮缩放
                    row.spawn((
                        Node { width: px(600), height: px(600), padding: UiRect::all(px(14)), ..default() },
                        skin.image("panel"),
                    ))
                    .with_children(|frame| {
                        frame
                            .spawn((
                                View,
                                Node { width: percent(100), height: percent(100), ..default() },
                                ImageNode::default(),
                            ))
                            .observe(
                                |drag: On<PointerDrag>,
                                 time: Res<Time<Real>>,
                                 mut inspect: ResMut<Inspect>| {
                                    inspect.drag(drag.delta, time.delta_secs());
                                },
                            )
                            .observe(|_: On<PointerDragEnd>, mut inspect: ResMut<Inspect>| inspect.release())
                            .observe(|scroll: On<PointerScroll>, mut inspect: ResMut<Inspect>| {
                                let steps = match scroll.unit {
                                    MouseScrollUnit::Line => scroll.y,
                                    MouseScrollUnit::Pixel => scroll.y / 40.0,
                                };
                                inspect.zoom(steps);
                            });
                    });
                    row.spawn(Node {
                        width: px(520),
                        flex_direction: FlexDirection::Column,
                        row_gap: px(14),
                        ..default()
                    })
                    .with_children(|col| {
                        col.spawn(text(&fonts.body, 18.0, INK_DIM.mix(&PAPER, 0.6), &card.kind));
                        col.spawn(text(
                            &fonts.title,
                            48.0,
                            on_paper(card.color).mix(&PAPER, 0.35),
                            &card.name,
                        ));
                        col.spawn((
                            Node { max_width: px(520), ..default() },
                            text(&fonts.body, 22.0, PAPER, &card.short),
                        ));
                        if !card.flavor.is_empty() {
                            col.spawn((
                                Node { max_width: px(520), ..default() },
                                text(&fonts.body, 19.0, PAPER.mix(&INK_DIM, 0.35), &card.flavor),
                            ));
                        }
                    });
                });
            root.spawn(Node { column_gap: px(36), align_items: AlignItems::Center, ..default() })
                .with_children(|row| {
                    row.spawn(crate::prompts::hint(
                        &fonts.body,
                        18.0,
                        PAPER.mix(&INK, 0.3),
                        "拖动转　滚轮缩放　{back} 合上",
                    ));
                    row.spawn((
                        Node { padding: UiRect::axes(px(18), px(8)), ..default() },
                        text(&fonts.body, 20.0, PAPER, "合上"),
                    ))
                    .observe(|_: On<PointerClick>, mut inspect: ResMut<Inspect>| inspect.close());
                });
        });
}

/// 把画面层的贴图放进面板；模型读不出来时换成卡面插画
fn show_view(
    inspect: Res<Inspect>,
    card: Res<InspectCard>,
    db: Option<Res<AtlasDb>>,
    mut views: Query<&mut ImageNode, With<View>>,
) {
    for mut node in &mut views {
        let want = match (inspect.status(), inspect.image(), db.as_deref()) {
            (InspectStatus::Failed, _, Some(db)) => match db.find(&card.art) {
                Some(f) => {
                    let ui = db.ui_image(f);
                    if node.image != ui.image || node.texture_atlas.is_none() {
                        *node = ui;
                    }
                    continue;
                }
                None => continue,
            },
            (_, Some(image), _) => image.clone(),
            _ => continue,
        };
        if node.image != want {
            *node = ImageNode::new(want);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn content() -> lantern_content::Content {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
        lantern_content::Content::load(&root).unwrap()
    }

    /// 用户定的 39 件：法器本体和进化 20、异化 5、合璧 3、灯坠 8、灯笼 3；名字和卡面插画一套。
    #[test]
    fn inspect_ids_are_the_39_items_the_user_picked() {
        let ids = inspect_ids(&content());
        assert_eq!(ids.len(), 39, "{ids:?}");
        for id in ["sword", "sword_evo", "sword_mut", "phoenix", "wind_wheel", "lantern_red", "lantern_frost"]
        {
            assert!(ids.iter().any(|i| i == id), "少了 {id}");
        }
        let unique: BTreeSet<_> = ids.iter().collect();
        assert_eq!(unique.len(), ids.len(), "有重名");
    }

    /// models/inspect 里的每个 glb 都对得上一件东西，名字写错了这里会提醒
    #[test]
    fn every_inspect_model_is_named_after_an_item() {
        let ids: BTreeSet<String> = inspect_ids(&content()).into_iter().collect();
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/models/inspect");
        let Ok(files) = std::fs::read_dir(&dir) else { return };
        for f in files.flatten() {
            let name = f.file_name().to_string_lossy().into_owned();
            let id = name.strip_suffix(".glb").unwrap_or_else(|| panic!("{name} 不是 .glb"));
            assert!(ids.contains(id), "{name} 对不上任何法器、灯坠或灯笼");
        }
    }
}
