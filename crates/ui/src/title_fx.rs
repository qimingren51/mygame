//! 标题画面的动静（docs/FEEL.md 第 5 节）：背景极慢地推近又拉回，山路上飘起几点魂火，
//! 进入标题时 logo 淡入。只是装饰，不影响菜单的操作。

use bevy::prelude::*;

use lantern_core::Pcg32;
use lantern_sim::AppState;
use lantern_view::atlas::AtlasDb;

/// 标题背景图（title.rs 生成时挂上）。
#[derive(Component)]
pub(crate) struct TitleBg;

/// 标题 logo（主菜单重画时也挂上；淡入按进入标题后的时间算，重画不会重播）。
#[derive(Component)]
pub(crate) struct TitleLogo;

#[derive(Component)]
struct Mote {
    /// 位置（屏幕百分比）
    x: f32,
    y: f32,
    rise: f32,
    sway: f32,
    t: f32,
    life: f32,
}

#[derive(Resource)]
struct TitleFx {
    clock: f32,
    rng: Pcg32,
}

const MOTES: usize = 9;

pub(crate) fn register(app: &mut App) {
    app.insert_resource(TitleFx { clock: 0.0, rng: Pcg32::new(0x7171_e000, 3) })
        .add_systems(OnEnter(AppState::Title), spawn_motes)
        .add_systems(Update, animate.run_if(in_state(AppState::Title)));
}

/// 山路一带随机一点（屏幕百分比）。
fn spawn_point(rng: &mut Pcg32) -> (f32, f32) {
    (rng.range_f32(28.0, 96.0), rng.range_f32(62.0, 96.0))
}

fn spawn_motes(mut commands: Commands, db: Res<AtlasDb>, mut fx: ResMut<TitleFx>) {
    fx.clock = 0.0;
    let Some(frame) = db.find("vfx/gem_0") else { return };
    for k in 0..MOTES {
        let (x, y) = spawn_point(&mut fx.rng);
        let life = fx.rng.range_f32(5.0, 9.0);
        commands.spawn((
            Mote {
                x,
                y,
                rise: fx.rng.range_f32(3.0, 6.0),
                sway: fx.rng.range_f32(0.0, std::f32::consts::TAU),
                // 错开出场，不要一起亮起来
                t: -(k as f32) * 0.7,
                life,
            },
            DespawnOnExit(AppState::Title),
            Node { position_type: PositionType::Absolute, width: px(13), height: px(18), ..default() },
            db.ui_image(frame).with_color(Color::srgba(0.8, 0.95, 1.0, 0.0)),
        ));
    }
}

fn animate(
    time: Res<Time<Real>>,
    mut fx: ResMut<TitleFx>,
    mut bg: Query<&mut UiTransform, (With<TitleBg>, Without<TitleLogo>)>,
    mut logo: Query<(&mut ImageNode, &mut UiTransform), (With<TitleLogo>, Without<Mote>)>,
    mut motes: Query<(&mut Mote, &mut Node, &mut ImageNode), Without<TitleLogo>>,
) {
    let dt = time.delta_secs().min(0.1);
    fx.clock += dt;
    let t = fx.clock;
    // 背景：40 秒一个来回，最多推近 3%
    for mut tf in &mut bg {
        let k = 0.5 - 0.5 * (t * std::f32::consts::TAU / 40.0).cos();
        tf.scale = Vec2::splat(1.0 + 0.03 * k);
    }
    // logo：1.2 秒淡入，从略大落定
    let k = (t / 1.2).clamp(0.0, 1.0);
    let ease = 1.0 - (1.0 - k).powi(3);
    for (mut img, mut tf) in &mut logo {
        img.color.set_alpha(ease);
        tf.scale = Vec2::splat(1.04 - 0.04 * ease);
    }
    // 魂火：慢慢升起、左右摆，亮一会儿再淡去，换个地方重来
    let fx = &mut *fx;
    for (mut m, mut node, mut img) in &mut motes {
        m.t += dt;
        if m.t >= m.life {
            let (x, y) = spawn_point(&mut fx.rng);
            *m = Mote { x, y, t: 0.0, life: fx.rng.range_f32(5.0, 9.0), ..*m };
        }
        if m.t < 0.0 {
            continue;
        }
        let u = m.t / m.life;
        let y = m.y - m.rise * m.t;
        let x = m.x + (m.t * 0.9 + m.sway).sin() * 0.8;
        node.left = percent(x);
        node.top = percent(y);
        let a = (u / 0.2).min(1.0) * ((1.0 - u) / 0.35).min(1.0);
        img.color.set_alpha(0.75 * a);
    }
}
