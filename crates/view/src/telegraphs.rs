//! 夜主预警：直接描摹模拟几何，在夜色、自发光之上保留稳定墨边与朱砂轮廓。
//! 外缘从起手到出手固定；沿边行进的浅金笔迹表示剩余蓄力，不用缩圈冒充伤害范围。

use std::f32::consts::{PI, TAU};

use bevy::asset::RenderAssetUsages;
use bevy::camera::visibility::NoFrustumCulling;
use bevy::mesh::PrimitiveTopology;
use bevy::prelude::*;
use bevy::sprite_render::AlphaMode2d;
use lantern_sim::boss::{BossState, DangerArea};
use lantern_sim::{AppState, GameContent, Player, Pos, PrevPos};

use crate::{layer, to_screen};

#[derive(Resource)]
pub(crate) struct Readability {
    /// 只压低玩家装饰特效；角色、敌弹、环境照明保留。
    pub gain: f32,
}

impl Default for Readability {
    fn default() -> Self {
        Self { gain: 1.0 }
    }
}

pub(crate) fn update_readability(
    time: Res<Time>,
    fixed: Res<Time<Fixed>>,
    content: Res<GameContent>,
    boss: Option<Res<BossState>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    mut readability: ResMut<Readability>,
) {
    let (pos, prev) = *player;
    let visible = prev.0.lerp(pos.0, fixed.overstep_fraction());
    let danger = boss.is_some_and(|b| {
        b.threatens(pos.0, content.0.player.radius) || b.threatens(visible, content.0.player.radius)
    });
    let target = if danger { 0.32 } else { 1.0 };
    let rate = if danger { 24.0 } else { 7.0 };
    readability.gain += (target - readability.gain) * (1.0 - (-time.delta_secs() * rate).exp());
}

#[derive(Component)]
pub(crate) struct TelegraphMesh;

pub(crate) fn spawn(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
    mut readability: ResMut<Readability>,
) {
    *readability = Readability::default();
    commands.spawn((
        TelegraphMesh,
        Mesh2d(meshes.add(InkMesh::default().finish())),
        MeshMaterial2d(materials.add(ColorMaterial { alpha_mode: AlphaMode2d::Blend, ..default() })),
        Transform::from_xyz(0.0, 0.0, layer::TELEGRAPH),
        NoFrustumCulling,
        DespawnOnExit(AppState::Run),
    ));
}

/// 所有点先在世界坐标生成，最后统一转屏幕坐标。禁止追加地面装饰用的 0.62 压扁。
fn boundary(area: DangerArea) -> Vec<Vec2> {
    let arc = |center: Vec2, radius: f32, start: f32, angle: f32, steps: usize| {
        (0..=steps).map(move |k| {
            let a = start + angle * k as f32 / steps as f32;
            center + Vec2::new(a.cos(), a.sin()) * radius
        })
    };
    match area {
        DangerArea::Circle { center, radius } => arc(center, radius, 0.0, TAU, 96).take(96).collect(),
        DangerArea::Sector { origin, dir, angle, radius } => {
            let steps = (96.0 * angle / TAU).ceil().max(8.0) as usize;
            std::iter::once(origin).chain(arc(origin, radius, dir - angle * 0.5, angle, steps)).collect()
        }
        DangerArea::Lane { start, end, radius } => {
            let d = end - start;
            let angle = d.y.atan2(d.x);
            arc(end, radius, angle - PI * 0.5, PI, 12)
                .chain(arc(start, radius, angle + PI * 0.5, PI, 12))
                .collect()
        }
    }
}

#[derive(Default)]
struct InkMesh {
    positions: Vec<[f32; 3]>,
    colors: Vec<[f32; 4]>,
}

impl InkMesh {
    fn triangle(&mut self, points: [Vec2; 3], z: f32, colors: [Color; 3]) {
        for (p, color) in points.into_iter().zip(colors) {
            self.positions.push(to_screen(p).extend(z).to_array());
            self.colors.push(color.to_linear().to_f32_array());
        }
    }

    fn line(&mut self, a: Vec2, b: Vec2, width: f32, z: f32, colors: [Color; 2]) {
        let n = (b - a).normalize_or_zero().perp();
        let [ca, cb] = colors;
        let inner = n * width * 0.5;
        self.triangle([a - inner, a + inner, b + inner], z, [ca, ca, cb]);
        self.triangle([a - inner, b + inner, b - inner], z, [ca, cb, cb]);
        // 半透明羽化只在描边外侧，不移动几何边界，避免缩放后硬锯齿。
        for side in [-1.0, 1.0] {
            let inside = inner * side;
            let outside = n * (width * 0.5 + 0.65) * side;
            self.triangle(
                [a + inside, a + outside, b + outside],
                z,
                [ca, ca.with_alpha(0.0), cb.with_alpha(0.0)],
            );
            self.triangle([a + inside, b + outside, b + inside], z, [ca, cb.with_alpha(0.0), cb]);
        }
    }

    fn charge(&mut self, origin: Vec2, progress: f32) {
        let points = boundary(DangerArea::Circle { center: origin, radius: 32.0 });
        let gold = Color::srgba(1.0, 0.74, 0.42, 0.8);
        let ink = Color::srgba(0.055, 0.025, 0.04, 0.7);
        for k in 0..points.len() {
            let (a, b) = (points[k], points[(k + 1) % points.len()]);
            self.line(a, b, 2.2, 0.3, [ink; 2]);
            let u = (progress * points.len() as f32 - k as f32).clamp(0.0, 1.0);
            if u > 0.0 {
                self.line(a, a.lerp(b, u), 0.9, 0.4, [gold; 2]);
            }
        }
    }

    fn warning(&mut self, area: DangerArea, progress: f32) {
        let points = boundary(area);
        let center = match area {
            DangerArea::Circle { center, .. } => center,
            DangerArea::Sector { origin, .. } => origin,
            DangerArea::Lane { start, end, .. } => (start + end) * 0.5,
        };
        let lane = matches!(area, DangerArea::Lane { .. });
        let fill = Color::srgba(
            0.8,
            0.12,
            0.07,
            if lane { 0.012 + progress * 0.012 } else { 0.045 + progress * 0.04 },
        );
        // 远端仍保留完整弹道，只降低墨迹强度；起手进度集中在原点，避免满屏金色长线。
        let fade = |p: Vec2, color: Color| match area {
            DangerArea::Lane { start, end, .. } => {
                let distance = p.distance(start) / start.distance(end).max(1.0);
                color.with_alpha(color.alpha() * (1.0 - 0.8 * distance.clamp(0.0, 1.0)))
            }
            _ => color,
        };
        let ink = Color::srgba(0.055, 0.025, 0.04, if lane { 0.55 } else { 0.85 });
        let edge = Color::srgba(1.0, 0.29, 0.17, if lane { 0.6 } else { 0.8 });
        let gold = Color::srgba(1.0, 0.74, 0.42, 0.8);
        let perimeter: f32 =
            (0..points.len()).map(|k| points[k].distance(points[(k + 1) % points.len()])).sum();
        let mut remaining = perimeter * progress.clamp(0.0, 1.0);
        for k in 0..points.len() {
            let (a, b) = (points[k], points[(k + 1) % points.len()]);
            self.triangle([center, a, b], 0.0, [fade(center, fill), fade(a, fill), fade(b, fill)]);
            self.line(a, b, if lane { 1.8 } else { 3.0 }, 0.1, [fade(a, ink), fade(b, ink)]);
            self.line(a, b, if lane { 0.7 } else { 1.1 }, 0.2, [fade(a, edge), fade(b, edge)]);
            let len = a.distance(b);
            if !lane && remaining > 0.0 && len > 0.0 {
                self.line(a, a.lerp(b, (remaining / len).min(1.0)), 1.15, 0.3, [gold; 2]);
            }
            remaining -= len;
        }
    }

    fn finish(self) -> Mesh {
        Mesh::new(
            PrimitiveTopology::TriangleList,
            RenderAssetUsages::MAIN_WORLD | RenderAssetUsages::RENDER_WORLD,
        )
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, self.positions)
        .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, self.colors)
    }
}

pub(crate) fn draw(
    boss: Option<Res<BossState>>,
    content: Res<GameContent>,
    q: Single<(&Mesh2d, &mut Visibility), With<TelegraphMesh>>,
    mut meshes: ResMut<Assets<Mesh>>,
) {
    let mut ink = InkMesh::default();
    if let Some(boss) = boss {
        let reach = content.0.player.radius;
        for v in boss.volleys() {
            for area in v.lanes(reach) {
                ink.warning(area, v.t / v.warn);
            }
            ink.charge(v.origin, v.t / v.warn);
        }
        for sw in &boss.sweeps {
            ink.warning(sw.danger(reach), sw.t / sw.warn);
        }
        for drop in &boss.drops {
            ink.warning(drop.danger(reach), drop.t / drop.warn);
        }
    }
    let (handle, mut visibility) = q.into_inner();
    if ink.positions.is_empty() {
        *visibility = Visibility::Hidden;
        return;
    }
    *visibility = Visibility::Visible;
    if let Some(mut mesh) = meshes.get_mut(&handle.0) {
        *mesh = ink.finish();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn projected_boundaries_match_hit_geometry_in_every_direction() {
        let origin = Vec2::new(70.0, -30.0);
        let radius = 231.0;
        for dir in [0.0, PI * 0.25, PI * 0.5, PI, -PI * 0.75] {
            let area = DangerArea::Sector { origin, dir, angle: PI * 2.0 / 3.0, radius };
            let points = boundary(area);
            for p in &points[2..points.len() - 1] {
                let screen = to_screen(*p);
                assert!((screen.distance(to_screen(origin)) - radius).abs() < 0.001);
                let d = to_screen(screen) - origin;
                assert!(area.contains(origin + d * 0.999));
                assert!(!area.contains(origin + d * 1.001));
            }
        }
        let circle = DangerArea::Circle { center: origin, radius: 51.0 };
        for p in boundary(circle) {
            let d = to_screen(to_screen(p)) - origin;
            assert!((d.length() - 51.0).abs() < 0.001);
            assert!(circle.contains(origin + d * 0.999));
            assert!(!circle.contains(origin + d * 1.001));
        }
    }

    #[test]
    fn projectile_corridor_keeps_safe_gaps_and_round_caps() {
        let lane = DangerArea::Lane { start: Vec2::ZERO, end: Vec2::new(300.0, 400.0), radius: 17.0 };
        let axis = Vec2::new(0.6, 0.8);
        assert!(lane.contains(axis * 250.0 + axis.perp() * 16.9));
        assert!(!lane.contains(axis * 250.0 + axis.perp() * 17.1));
        for p in boundary(lane) {
            assert!(lane.contains(p * 0.99999));
        }
    }
}
