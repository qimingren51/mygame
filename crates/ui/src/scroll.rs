//! 开场卷轴（docs/GAMEPLAY.md 第 2.5 节）：第一次进入某个地区时，一幅水墨长卷从左往右展开，
//! 左上角的空白天空里浮出三四句旁白；拿回那里的烛火以后再来，展开一次上了颜色的天明版。
//! 画是 `atlas/screens/scroll_<地区>.png`（2400 × 800），旁白在 `regions.ron`。确认、返回或点一下就接着出发。

use bevy::prelude::*;
use bevy::ui::widget::NodeImageMode;

use lantern_content::RegionDef;

use crate::{DIM, Fonts, INK, PAPER, text};

/// P0 只有青丘
pub(crate) const REGION: &str = "qingqiu";

#[derive(Resource)]
pub(crate) struct ScrollArt {
    pub night: Handle<Image>,
    pub dawn: Handle<Image>,
}

pub(crate) fn preload(mut commands: Commands, assets: Res<AssetServer>) {
    commands.insert_resource(ScrollArt {
        night: assets.load(format!("atlas/screens/scroll_{REGION}.png")),
        dawn: assets.load(format!("atlas/screens/scroll_{REGION}_dawn.png")),
    });
}

/// 卷轴占屏幕宽度的比例（视口宽度的百分数）；画是 3:1
const WIDTH_VW: f32 = 94.0;
/// 展开用时、旁白开始浮出的时刻、每行间隔（秒）
const UNROLL: f32 = 1.8;
const WORDS_AT: f32 = 1.2;
const LINE_GAP: f32 = 0.7;

/// 卷轴展开的进度：裁剪框的宽度从 0 拉到整幅。
#[derive(Component, Default)]
pub(crate) struct Unroll {
    t: f32,
}

/// 旁白的第 k 行，按顺序浮出。
#[derive(Component)]
pub(crate) struct Line {
    k: usize,
    color: Color,
}

/// 把卷轴画进 `root`（标题界面的面板，重画时一起清掉）。
pub(crate) fn spawn(
    commands: &mut Commands,
    root: Entity,
    art: &ScrollArt,
    fonts: &Fonts,
    region: &RegionDef,
    dawn: bool,
    window_width: f32,
) {
    let (image, words, color) = if dawn {
        (art.dawn.clone(), region.dawn.as_deref().unwrap_or(""), INK)
    } else {
        (art.night.clone(), region.scroll.as_str(), PAPER)
    };
    // 字号跟着卷轴的实际宽度走：留白的天空约占画宽的 40%，一行放二十五个字左右
    let size = (window_width * WIDTH_VW / 100.0 * 0.0155).clamp(16.0, 44.0);
    commands.entity(root).insert(BackgroundColor(Color::srgb(0.03, 0.035, 0.05))).with_children(|p| {
        p.spawn(Node { width: Val::Vw(WIDTH_VW), height: Val::Vw(WIDTH_VW / 3.0), ..default() })
            .with_children(|frame| {
                frame
                    .spawn((
                        Unroll::default(),
                        Node {
                            position_type: PositionType::Absolute,
                            left: px(0),
                            top: px(0),
                            width: percent(12),
                            height: percent(100),
                            overflow: Overflow::clip(),
                            ..default()
                        },
                    ))
                    .with_children(|clip| {
                        clip.spawn((
                            Node {
                                position_type: PositionType::Absolute,
                                left: px(0),
                                top: px(0),
                                width: Val::Vw(WIDTH_VW),
                                height: Val::Vw(WIDTH_VW / 3.0),
                                ..default()
                            },
                            ImageNode::new(image).with_mode(NodeImageMode::Stretch),
                        ));
                    });
                // 画上留给旁白的天空：约 x 60–950、y 40–390（2400 × 800 的画）
                frame
                    .spawn(Node {
                        position_type: PositionType::Absolute,
                        left: percent(3.5),
                        top: percent(8),
                        width: percent(39),
                        flex_direction: FlexDirection::Column,
                        row_gap: Val::Px(size * 0.5),
                        ..default()
                    })
                    .with_children(|sky| {
                        for (k, line) in words.lines().filter(|l| !l.trim().is_empty()).enumerate() {
                            sky.spawn((
                                Line { k, color },
                                text(&fonts.body, size, color.with_alpha(0.0), line.trim()),
                            ));
                        }
                    });
            });
        p.spawn(text(&fonts.body, 16.0, DIM, "Enter / 手柄 A　继续"));
    });
}

/// 展开卷轴，旁白一行行浮出。
pub(crate) fn animate(
    time: Res<Time<Real>>,
    mut clips: Query<(&mut Unroll, &mut Node)>,
    mut lines: Query<(&Line, &mut TextColor)>,
) {
    let dt = time.delta_secs().min(0.1);
    let mut t = None;
    for (mut u, mut node) in &mut clips {
        u.t += dt;
        // 先快后慢，像手推开的卷轴
        let k = (u.t / UNROLL).clamp(0.0, 1.0);
        // 首帧已有画幅，避免墨幕揭开后又等一段近乎全黑的展开。
        node.width = percent(12.0 + 88.0 * (1.0 - (1.0 - k) * (1.0 - k)));
        t = Some(u.t);
    }
    let Some(t) = t else { return };
    for (line, mut color) in &mut lines {
        let a = ((t - WORDS_AT - line.k as f32 * LINE_GAP) / 0.8).clamp(0.0, 1.0);
        color.0 = line.color.with_alpha(a);
    }
}
