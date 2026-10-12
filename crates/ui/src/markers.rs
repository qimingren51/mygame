//! 屏幕边缘的指示箭头（docs/GAMEPLAY.md 第 4.5 节）：屏幕外没点亮的石灯笼、奇遇、精英、夜主。

use bevy::prelude::*;

use lantern_content::Rank;
use lantern_sim::encounters::Encounters;
use lantern_sim::lanterns::Lanterns;
use lantern_sim::{AppState, Enemies, GameContent};
use lantern_view::{MainCamera, to_screen};

use crate::describe::hex;
use crate::skin::Skin;

/// 同时显示的箭头上限
const SLOTS: usize = 12;
/// 箭头离屏幕边缘多远（逻辑像素）
const MARGIN: f32 = 34.0;
const SIZE: f32 = 40.0;

#[derive(Component)]
pub(crate) struct Marker(usize);

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Run), spawn)
        .add_systems(Update, update.run_if(in_state(AppState::Run)));
}

fn spawn(mut commands: Commands, skin: Res<Skin>) {
    for k in 0..SLOTS {
        commands.spawn((
            Marker(k),
            DespawnOnExit(AppState::Run),
            GlobalZIndex(4),
            Visibility::Hidden,
            Node { position_type: PositionType::Absolute, width: px(SIZE), height: px(SIZE), ..default() },
            UiTransform::IDENTITY,
            skin.image("arrow_marker"),
        ));
    }
}

#[allow(clippy::type_complexity)]
fn update(
    content: Res<GameContent>,
    lanterns: Option<Res<Lanterns>>,
    encounters: Option<Res<Encounters>>,
    enemies: Option<Res<Enemies>>,
    camera: Single<(&Camera, &GlobalTransform), With<MainCamera>>,
    mut markers: Query<(&Marker, &mut Node, &mut UiTransform, &mut ImageNode, &mut Visibility)>,
    mut targets: Local<Vec<(Vec2, Color, f32)>>,
) {
    let c = &content.0;
    targets.clear();
    if let Some(l) = &lanterns {
        targets.extend(l.0.iter().filter(|l| !l.lit).map(|l| (l.pos, hex("#FFD98A"), 1.0)));
    }
    if let Some(e) = &encounters {
        targets.extend(e.list.iter().map(|e| (e.pos, hex(&c.events.kinds[e.kind].color), 0.9)));
    }
    if let Some(en) = &enemies {
        for i in en.iter_alive() {
            let rank = c.enemies[en.kind[i] as usize].rank;
            if matches!(rank, Rank::Elite | Rank::Boss) && !en.cloaked[i] {
                let size = if rank == Rank::Boss { 1.3 } else { 1.0 };
                targets.push((Vec2::new(en.x[i], en.y[i]), hex("#FF6B5A"), size));
                if targets.len() >= SLOTS {
                    break;
                }
            }
        }
    }
    let (cam, gt) = *camera;
    let Some(view) = cam.logical_viewport_size() else { return };
    let center = view * 0.5;
    let mut shown = 0;
    for &(world, color, size) in targets.iter() {
        if shown >= SLOTS {
            break;
        }
        let Ok(sp) = cam.world_to_viewport(gt, to_screen(world).extend(0.0)) else { continue };
        let inside = sp.x > 0.0 && sp.y > 0.0 && sp.x < view.x && sp.y < view.y;
        if inside {
            continue;
        }
        // 从屏幕中心朝目标的方向，贴到屏幕边缘
        let d = sp - center;
        let half = center - Vec2::splat(MARGIN);
        let k = (half.x / d.x.abs().max(1e-3)).min(half.y / d.y.abs().max(1e-3));
        let at = center + d * k;
        for (m, mut node, mut tf, mut img, mut vis) in &mut markers {
            if m.0 != shown {
                continue;
            }
            let s = SIZE * size;
            node.left = px(at.x - s * 0.5);
            node.top = px(at.y - s * 0.5);
            node.width = px(s);
            node.height = px(s);
            tf.rotation = Rot2::radians(d.y.atan2(d.x));
            img.color = color;
            vis.set_if_neq(Visibility::Inherited);
        }
        shown += 1;
    }
    for (m, _, _, _, mut vis) in &mut markers {
        if m.0 >= shown {
            vis.set_if_neq(Visibility::Hidden);
        }
    }
}
