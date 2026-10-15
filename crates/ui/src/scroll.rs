//! 开场卷轴（docs/GAMEPLAY.md 第 2.5 节）：第一次进入某个地区时，一幅水墨长卷从左往右展开，
//! 左上角的空白天空里浮出三四句旁白；拿回那里的烛火以后再来，展开一次上了颜色的天明版。
//! 画是 `atlas/screens/scroll_<地区>.png`（2400 × 800），旁白在 `regions.ron`。确认、返回或点一下就接着出发。

use bevy::prelude::*;
use bevy::ui::widget::NodeImageMode;

use lantern_content::RegionDef;
use lantern_platform::UiCue;

use crate::{DIM, Fonts, INK, PAPER, text};

/// P0 只有青丘
pub(crate) const REGION: &str = "qingqiu";

/// 卷轴占屏幕宽度的比例（视口宽度的百分数）；画是 3:1
const WIDTH_VW: f32 = 94.0;
/// 展开用时、旁白开始浮出的时刻、每行间隔（秒）
const UNROLL: f32 = 1.8;
const WORDS_AT: f32 = 1.2;
const LINE_GAP: f32 = 0.7;

/// 卷轴的轴头（美术的 `screens/scroll_roller.png`，60 × 832，长夜版、天明版共用）：第 10 列对齐
/// 展开的那道边，上下各伸出 16 像素。下面换算成卷轴画（2400 × 800）的百分比。
const ROLLER_EDGE: f32 = 10.0 / 2400.0 * 100.0;
const ROLLER_W: f32 = 60.0 / 2400.0 * 100.0;
const ROLLER_TOP: f32 = 16.0 / 800.0 * 100.0;
const ROLLER_H: f32 = 832.0 / 800.0 * 100.0;

/// 轴头：跟着展开的那道边往右走。
#[derive(Component)]
pub(crate) struct Roller;

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
    /// 浮出时的那一声已经发过
    cued: bool,
}

/// 把卷轴画进 `root`（标题界面的面板，重画时一起清掉）。
pub(crate) fn spawn(
    commands: &mut Commands,
    root: Entity,
    assets: &AssetServer,
    fonts: &Fonts,
    region: &RegionDef,
    dawn: bool,
    window_width: f32,
) {
    let (file, words, color) = if dawn {
        (format!("atlas/screens/scroll_{}_dawn.png", region.id), region.dawn.as_deref().unwrap_or(""), INK)
    } else {
        (format!("atlas/screens/scroll_{}.png", region.id), region.scroll.as_str(), PAPER)
    };
    let image: Handle<Image> = assets.load(file);
    let roller: Handle<Image> = assets.load("atlas/screens/scroll_roller.png");
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
                            width: percent(0),
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
                // 轴头：压在画的右边缘，展开时跟着走，像手推开的卷轴
                frame.spawn((
                    Roller,
                    Node {
                        position_type: PositionType::Absolute,
                        left: percent(-ROLLER_EDGE),
                        top: percent(-ROLLER_TOP),
                        width: percent(ROLLER_W),
                        height: percent(ROLLER_H),
                        ..default()
                    },
                    ImageNode::new(roller).with_mode(NodeImageMode::Stretch),
                    ZIndex(2),
                ));
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
                                Line { k, color, cued: false },
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
    mut rollers: Query<&mut Node, (With<Roller>, Without<Unroll>)>,
    mut lines: Query<(&mut Line, &mut TextColor)>,
    mut cues: MessageWriter<UiCue>,
) {
    let dt = time.delta_secs().min(0.1);
    let mut t = None;
    for (mut u, mut node) in &mut clips {
        // 展开的第一帧：纸响
        if u.t == 0.0 {
            cues.write(UiCue::ScrollUnroll);
        }
        u.t += dt;
        // 先快后慢，像手推开的卷轴
        let k = (u.t / UNROLL).clamp(0.0, 1.0);
        let open = 100.0 * (1.0 - (1.0 - k) * (1.0 - k));
        node.width = percent(open);
        for mut r in &mut rollers {
            r.left = percent(open - ROLLER_EDGE);
        }
        t = Some(u.t);
    }
    let Some(t) = t else { return };
    for (mut line, mut color) in &mut lines {
        let a = ((t - WORDS_AT - line.k as f32 * LINE_GAP) / 0.8).clamp(0.0, 1.0);
        color.0 = line.color.with_alpha(a);
        // 一行开始浮出：一声很轻的高音，一行比一行高
        if a > 0.0 && !line.cued {
            line.cued = true;
            cues.write(UiCue::ScrollLine(line.k.min(255) as u8));
        }
    }
}
