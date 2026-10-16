//! 敌方预警：直接描摹模拟几何，在夜色、自发光之上保留稳定墨边与朱砂轮廓。
//! 外缘从起手到出手固定；沿边行进的浅金笔迹表示剩余蓄力，不用缩圈冒充伤害范围。

use std::f32::consts::{PI, TAU};

use bevy::asset::RenderAssetUsages;
use bevy::camera::visibility::NoFrustumCulling;
use bevy::mesh::PrimitiveTopology;
use bevy::prelude::*;
use bevy::sprite_render::AlphaMode2d;
use lantern_content::Content;
use lantern_sim::boss::{BossState, DangerArea};
use lantern_sim::{AppState, Director, Enemies, GameContent, Player, Pos, PrevPos, RunState};

use crate::boss_cues::{BossCues, Release, ReleaseShape};
use crate::{Feel, layer, to_screen};

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
    enemies: Option<Res<Enemies>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    mut readability: ResMut<Readability>,
) {
    let (pos, prev) = *player;
    let visible = prev.0.lerp(pos.0, fixed.overstep_fraction());
    // 狐火环的弹道太长，二阶段几乎总站在某条上；只在扫击、狐火雨的落点里压暗自己的特效
    let boss_danger = boss.is_some_and(|b| {
        b.in_strike_zone(pos.0, content.0.player.radius) || b.in_strike_zone(visible, content.0.player.radius)
    });
    let ranged_danger = enemies.is_some_and(|en| {
        (0..en.hi)
            .filter_map(|i| ranged_warning(&en, i, &content.0))
            .any(|(area, _)| area.contains(pos.0) || area.contains(visible))
    });
    // 预警本身够亮，自己的法器压一半就分得清（质感会话定的数）
    let danger = boss_danger || ranged_danger;
    let target = if danger { 0.5 } else { 1.0 };
    let rate = if danger { 24.0 } else { 7.0 };
    readability.gain += (target - readability.gain) * (1.0 - (-time.delta_secs() * rate).exp());
}

/// 竹刺的起点、方向在模拟蓄力时锁定；描边包含玩家半径，与实际碰撞安全距离一致。
fn ranged_warning(en: &Enemies, i: usize, content: &Content) -> Option<(DangerArea, f32)> {
    if !en.alive[i] || en.grace[i] > 0.0 || en.aim_t[i] <= 0.0 {
        return None;
    }
    let shot = content.enemies.get(en.kind[i] as usize)?.shot.as_ref()?;
    let start = Vec2::new(en.aim_x[i], en.aim_y[i]);
    let dir = Vec2::new(en.aim_dx[i], en.aim_dy[i]);
    let end = start + dir * shot.speed * shot.life;
    Some((
        DangerArea::Lane { start, end, radius: shot.radius + content.player.radius },
        (1.0 - en.aim_t[i] / shot.warn).clamp(0.0, 1.0),
    ))
}

/// 只按当前模拟脚点判断近身危险；插值只用于绘制位置，越界当帧即撤下提示。
fn strike_progress(boss: &BossState, player: Vec2, reach: f32) -> Option<f32> {
    boss.sweeps
        .iter()
        .filter(|s| s.danger(reach).contains(player))
        .map(|s| (s.t / s.warn.max(f32::EPSILON)).clamp(0.0, 1.0))
        .chain(
            boss.drops
                .iter()
                .filter(|r| r.danger(reach).contains(player))
                .map(|r| (r.t / r.warn.max(f32::EPSILON)).clamp(0.0, 1.0)),
        )
        .max_by(f32::total_cmp)
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
        let edge = Color::srgba(1.0, 0.29, 0.17, if lane { 0.6 } else { 0.95 });
        let gold = Color::srgba(1.0, 0.74, 0.42, 0.8);
        let perimeter: f32 =
            (0..points.len()).map(|k| points[k].distance(points[(k + 1) % points.len()])).sum();
        let mut remaining = perimeter * progress.clamp(0.0, 1.0);
        for k in 0..points.len() {
            let (a, b) = (points[k], points[(k + 1) % points.len()]);
            self.triangle([center, a, b], 0.0, [fade(center, fill), fade(a, fill), fade(b, fill)]);
            // 近身落点描边高于长弹道，重叠时仍能辨认扇扫和狐火雨的完整边界。
            self.line(
                a,
                b,
                if lane { 1.8 } else { 4.5 },
                if lane { 0.1 } else { 0.5 },
                [fade(a, ink), fade(b, ink)],
            );
            self.line(
                a,
                b,
                if lane { 0.7 } else { 1.8 },
                if lane { 0.2 } else { 0.6 },
                [fade(a, edge), fade(b, edge)],
            );
            let len = a.distance(b);
            if !lane && remaining > 0.0 && len > 0.0 {
                self.line(a, a.lerp(b, (remaining / len).min(1.0)), 2.0, 0.7, [gold; 2]);
            }
            remaining -= len;
        }
    }

    fn release(&mut self, release: &Release, lite: bool) {
        let u = release.progress();
        let fade = (1.0 - u).powi(2);
        let (area, confirm, gain) = match release.shape {
            ReleaseShape::Sweep(area) | ReleaseShape::Rain(area) => (area, u < 0.16, 1.0),
            ReleaseShape::Volley { origin, illusion } => (
                DangerArea::Circle { center: origin, radius: 32.0 * (1.0 - u * 0.28) },
                false,
                if illusion { 0.65 } else { 1.0 },
            ),
        };
        let points = boundary(area);
        // 已结算的余迹不再用朱砂填色：接触帧浅金确认，随后断为淡墨短笔。
        // 近身危险边界仍在 0.5–0.7 层，比这份装饰余迹更靠前。
        let dark = Color::srgba(0.09, 0.065, 0.05, fade * gain * 0.55);
        let light = Color::srgba(1.0, 0.88, 0.64, fade * gain * if confirm { 0.9 } else { 0.6 });
        let spacing = if lite { 8 } else { 4 };
        for k in 0..points.len() {
            if !confirm && k % spacing != 0 {
                continue;
            }
            let (a, b) = (points[k], points[(k + 1) % points.len()]);
            self.line(a, b, if confirm { 3.6 } else { 2.4 }, 0.25, [dark; 2]);
            self.line(a, b, if confirm { 1.8 } else { 0.9 }, 0.35, [light; 2]);
        }
    }

    fn player_warning(&mut self, at: Vec2, reach: f32, progress: f32) {
        let radius = (reach + 4.0).clamp(12.0, 22.0);
        let urgent = ((progress - 0.7) / 0.3).clamp(0.0, 1.0);
        let dark = Color::srgba(0.055, 0.025, 0.04, 0.9);
        let red = Color::srgba(1.0, 0.29, 0.17, 0.85 + urgent * 0.1);
        // 四个短括角留出整个脚点中心，不铺圆盘，也不靠闪烁和震屏催促。
        for (x, y) in [(-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)] {
            let corner = at + Vec2::new(x, y) * radius;
            for end in [corner - Vec2::new(x * 5.0, 0.0), corner - Vec2::new(0.0, y * 5.0)] {
                self.line(corner, end, 3.8, 0.8, [dark; 2]);
                self.line(corner, end, 1.2 + urgent * 0.6, 0.9, [red; 2]);
            }
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
    director: Option<Res<Director>>,
    run: Option<Res<State<RunState>>>,
    enemies: Option<Res<Enemies>>,
    content: Res<GameContent>,
    cues: Res<BossCues>,
    feel: Res<Feel>,
    fixed: Res<Time<Fixed>>,
    player: Single<(&Pos, &PrevPos), With<Player>>,
    q: Single<(&Mesh2d, &mut Visibility), With<TelegraphMesh>>,
    mut meshes: ResMut<Assets<Mesh>>,
) {
    let mut ink = InkMesh::default();
    for release in cues.releases() {
        ink.release(release, feel.lite);
    }
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
        let (pos, previous) = *player;
        if director.is_some_and(|d| d.boss.is_some())
            && run.is_none_or(|state| *state.get() != RunState::Over)
            && let Some(progress) = strike_progress(&boss, pos.0, reach)
        {
            let visible = previous.0.lerp(pos.0, fixed.overstep_fraction());
            ink.player_warning(visible, reach, progress);
        }
    }
    if let Some(en) = enemies {
        for (area, progress) in (0..en.hi).filter_map(|i| ranged_warning(&en, i, &content.0)) {
            ink.warning(area, progress);
            if let DangerArea::Lane { start, .. } = area {
                ink.charge(start, progress);
            }
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
    fn foot_warning_is_only_for_current_strike_zones_and_leaves_the_center_clear() {
        use lantern_sim::boss::{RainDrop, Sweep, Volley};
        let mut boss = BossState {
            sweeps: vec![Sweep {
                origin: Vec2::ZERO,
                dir: 0.0,
                angle: PI * 0.5,
                radius: 100.0,
                damage: 1.0,
                t: 0.4,
                warn: 0.8,
            }],
            drops: vec![RainDrop { pos: Vec2::new(80.0, 0.0), radius: 20.0, damage: 1.0, t: 0.7, warn: 0.8 }],
            ..default()
        };
        assert_eq!(strike_progress(&boss, Vec2::new(80.0, 0.0), 11.0), Some(0.7 / 0.8));
        assert_eq!(strike_progress(&boss, Vec2::new(-80.0, 0.0), 11.0), None);
        assert_eq!(strike_progress(&boss, Vec2::new(112.0, 0.0), 11.0), None, "离开真实外缘立即退下");
        boss.sweeps.clear();
        boss.drops.clear();
        boss.volley = Some(Volley {
            origin: Vec2::ZERO,
            offset: 0.0,
            count: 14,
            speed: 115.0,
            radius: 6.0,
            damage: 1.0,
            life: 6.0,
            t: 0.7,
            warn: 0.8,
        });
        assert_eq!(strike_progress(&boss, Vec2::new(80.0, 0.0), 11.0), None, "长弹道不能让脚边常亮");
        let mut ink = InkMesh::default();
        ink.player_warning(Vec2::ZERO, 11.0, 1.0);
        assert!(!ink.positions.is_empty());
        assert!(ink.positions.iter().all(|p| Vec2::new(p[0], p[1]).length() > 11.0), "脚点中心留空");
    }

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

    #[test]
    fn bamboo_warning_uses_locked_origin_and_disappears_when_cancelled() {
        let content =
            Content::load(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let kind = content.enemies.iter().position(|e| e.id == "bamboo_wraith").unwrap();
        let shot = content.enemies[kind].shot.as_ref().unwrap();
        let mut en = Enemies::default();
        en.hi = 1;
        en.alive[0] = true;
        en.kind[0] = kind as u16;
        en.x[0] = 900.0;
        en.y[0] = 700.0;
        en.aim_x[0] = 40.0;
        en.aim_y[0] = 60.0;
        en.aim_dx[0] = 0.6;
        en.aim_dy[0] = 0.8;
        en.aim_t[0] = shot.warn * 0.5;
        let (area, progress) = ranged_warning(&en, 0, &content).unwrap();
        assert!((progress - 0.5).abs() < 1e-5);
        let origin = Vec2::new(40.0, 60.0);
        let axis = Vec2::new(0.6, 0.8);
        let end = origin + axis * shot.speed * shot.life;
        let radius = shot.radius + content.player.radius;
        assert!(area.contains(end + axis.perp() * (radius - 0.01)));
        assert!(!area.contains(end + axis.perp() * (radius + 0.01)));
        en.aim_t[0] = 0.0;
        assert!(ranged_warning(&en, 0, &content).is_none());
        en.aim_t[0] = shot.warn;
        en.alive[0] = false;
        assert!(ranged_warning(&en, 0, &content).is_none());
        en.alive[0] = true;
        en.grace[0] = 0.2;
        assert!(ranged_warning(&en, 0, &content).is_none());
    }
}
