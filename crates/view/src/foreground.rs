//! 近景墨竹：固定八束，沿屏幕上下边缘掠过；世界位移按 1.24 倍视差滚动。
//! 叶片是带透明裙边的网格笔触，不依赖新图集，也不采样/模糊整幅画面。

use crate::{Dawn, Feel, MainCamera, layer};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use bevy::sprite_render::AlphaMode2d;
use lantern_core::Pcg32;
use lantern_sim::{AppState, Player, RunSetup};

const COUNT: usize = 8;
const PARALLAX: f32 = 1.24;
const REACH: f32 = 120.0;

/// 由已有预警遍历顺手收集，不再为前景扫描妖物。超预算时整层退出，保证危险区留白。
#[derive(Resource, Default)]
pub(crate) struct Safety {
    zones: Vec<(Vec2, f32)>,
    overflow: bool,
}

impl Safety {
    pub(crate) fn clear(&mut self) {
        self.zones.clear();
        self.overflow = false;
    }

    pub(crate) fn protect(&mut self, center: Vec2, radius: f32) {
        if self.zones.len() < 32 {
            self.zones.push((center, radius));
        } else {
            self.overflow = true;
        }
    }

    fn fade(&self, branch: Vec2, reach: f32) -> f32 {
        if self.overflow {
            return 0.0;
        }
        self.zones
            .iter()
            .fold(1.0, |alpha, &(p, radius)| alpha.min(smooth((branch.distance(p) - radius - reach) / 40.0)))
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct Frond {
    phase: f32,
    depth: f32,
    scale: f32,
    flip: f32,
}

fn fronds(seed: u64) -> [Frond; COUNT] {
    let mut rng = Pcg32::new(seed ^ 0x6261_6d62_6f6f, 12);
    std::array::from_fn(|k| Frond {
        phase: k as f32 / 4.0 + rng.range_f32(-0.06, 0.06),
        depth: rng.range_f32(8.0, 30.0),
        scale: rng.range_f32(0.8, 1.0),
        flip: if rng.chance(0.5) { -1.0 } else { 1.0 },
    })
}

/// 周期接缝位于屏外，留出整束枝叶的宽度；边缘渐隐不会突然换一棵树。
fn frond_position(f: Frond, top: bool, camera: Vec2, half: Vec2) -> Vec2 {
    let width = half.x * 2.0 + REACH * 4.0;
    let x = (f.phase * width - camera.x * PARALLAX).rem_euclid(width) - width * 0.5;
    let height = half.y * 2.0 + REACH * 2.0;
    let y = if top { half.y + f.depth } else { -half.y - f.depth };
    let y = (y - camera.y * PARALLAX + height * 0.5).rem_euclid(height) - height * 0.5;
    Vec2::new(x, y)
}

fn smooth(v: f32) -> f32 {
    let v = v.clamp(0.0, 1.0);
    v * v * (3.0 - 2.0 * v)
}

/// 以整束包围圆避让玩家，窄屏、镜头偏移与闪避时仍留出至少 85 单位的清晰区。
fn player_fade(branch: Vec2, player: Vec2, reach: f32) -> f32 {
    smooth((branch.distance(player) - reach - 85.0) / 65.0)
}

/// 单片叶子按像素位置让出画面中部，上下仅外侧 22% 高度可见。
fn edge_fade(pos: Vec2, half: Vec2) -> f32 {
    smooth((pos.y.abs() / half.y.max(1.0) - 0.78) / 0.16)
        * (1.0 - smooth((pos.x.abs() - half.x - 15.0) / (REACH * 1.5)))
}

#[derive(Resource)]
pub(crate) struct Foreground {
    fronds: [Frond; COUNT],
    mesh: Handle<Mesh>,
    /// 叶片模板只构建一次；每帧只变换有上限的顶点。
    template: BrushMesh,
}

#[derive(Default)]
struct BrushMesh {
    positions: Vec<[f32; 3]>,
    colors: Vec<[f32; 4]>,
    indices: Vec<u32>,
}

impl BrushMesh {
    /// 一笔叶片：轴线微弯，中央积墨，边缘 1.2 单位的透明裙边形成微虚焦。
    fn leaf(&mut self, root: Vec2, tip: Vec2, width: f32) {
        let axis = tip - root;
        let normal = Vec2::new(-axis.y, axis.x).normalize_or_zero();
        let start = self.positions.len() as u32;
        for row in 0..=8 {
            let t = row as f32 / 8.0;
            let arc = (std::f32::consts::PI * t).sin();
            let center = root + axis * t + normal * arc * width * 0.6;
            let w = arc * width;
            for (off, alpha) in
                [(-w - 1.2, 0.0), (-w * 0.65, 0.72), (0.0, 0.9), (w * 0.65, 0.72), (w + 1.2, 0.0)]
            {
                let p = center + normal * off;
                self.positions.push([p.x, p.y, 0.0]);
                self.colors.push([0.007, 0.014, 0.021, alpha * smooth(arc * 5.0)]);
            }
        }
        for row in 0..8 {
            for col in 0..4 {
                let i = start + row * 5 + col;
                self.indices.extend([i, i + 6, i + 1, i, i + 5, i + 6]);
            }
        }
    }

    fn into_mesh(self) -> Mesh {
        let n = self.positions.len();
        Mesh::new(
            PrimitiveTopology::TriangleList,
            RenderAssetUsages::MAIN_WORLD | RenderAssetUsages::RENDER_WORLD,
        )
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, self.positions)
        .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, self.colors)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, vec![[0.0, 0.0, 1.0]; n])
        .with_inserted_attribute(Mesh::ATTRIBUTE_UV_0, vec![[0.0, 0.0]; n])
        .with_inserted_indices(Indices::U32(self.indices))
    }
}

/// 近景竹子最深的不透明度：上下两条边要能看见进来的妖物、弹幕和拾取物
const MAX_ALPHA: f32 = 0.6;

/// 近景竹子那一个网格。
#[derive(Component)]
pub(crate) struct ForegroundMesh;

pub(crate) fn spawn_foreground(
    mut commands: Commands,
    setup: Res<RunSetup>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
) {
    let mut template = BrushMesh::default();
    template.leaf(Vec2::ZERO, Vec2::new(72.0, -48.0), 1.6);
    for k in 0..6 {
        let root = Vec2::new(10.0 + 10.0 * k as f32, -8.0 - 6.0 * k as f32);
        template.leaf(root, root + Vec2::new(-14.0, -28.0 - (k % 3) as f32 * 3.0), 3.4);
        template.leaf(root, root + Vec2::new(22.0, 5.0 + (k % 2) as f32 * 9.0), 3.0);
    }
    let mesh = meshes.add(BrushMesh::default().into_mesh());
    commands.spawn((
        Mesh2d(mesh.clone()),
        MeshMaterial2d(materials.add(ColorMaterial {
            color: Color::WHITE,
            alpha_mode: AlphaMode2d::Blend,
            ..default()
        })),
        Transform::from_xyz(0.0, 0.0, layer::FOREGROUND),
        // 还没有顶点：先藏起来，免得空网格每帧报警告
        Visibility::Hidden,
        ForegroundMesh,
        DespawnOnExit(AppState::Run),
    ));
    commands.insert_resource(Foreground { fronds: fronds(setup.seed), mesh, template });
}

pub(crate) fn update_foreground(
    fg: Res<Foreground>,
    feel: Res<Feel>,
    dawn: Res<Dawn>,
    safety: Res<Safety>,
    camera: Single<(&Transform, &Projection), With<MainCamera>>,
    player: Single<&Transform, With<Player>>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut shown: Single<&mut Visibility, With<ForegroundMesh>>,
) {
    // 精简特效时不画近景
    if feel.lite {
        **shown = Visibility::Hidden;
        return;
    }
    let (cam, proj) = *camera;
    let Projection::Orthographic(proj) = proj else { return };
    let half = proj.area.half_size();
    let center = cam.translation.truncate();
    let hero = (cam.rotation.inverse() * (player.translation - cam.translation)).truncate();
    let mut batch = BrushMesh::default();
    for (k, f) in fg.fronds.iter().enumerate() {
        let top = k < 4;
        let p = frond_position(*f, top, center, half);
        let branch_world = center + (cam.rotation * p.extend(0.0)).truncate();
        let alpha = player_fade(p, hero, REACH * f.scale)
            * safety.fade(branch_world, REACH * f.scale)
            * (1.0 - dawn.progress() * 0.35)
            * MAX_ALPHA;
        if alpha <= 0.001 {
            continue;
        }
        let start = batch.positions.len() as u32;
        for (&v, &c) in fg.template.positions.iter().zip(&fg.template.colors) {
            let local = p + Vec2::new(v[0] * f.flip, v[1] * if top { 1.0 } else { -1.0 }) * f.scale;
            let world = center + (cam.rotation * local.extend(0.0)).truncate();
            batch.positions.push([world.x, world.y, 0.0]);
            batch.colors.push([c[0], c[1], c[2], c[3] * alpha * edge_fade(local, half)]);
        }
        // 镜像会反转绕序；材质默认背面剔除，镜像时同步反转三角形。
        let mirrored = f.flip * if top { 1.0 } else { -1.0 } < 0.0;
        for tri in fg.template.indices.as_chunks::<3>().0 {
            let [a, b, c] = [tri[0] + start, tri[1] + start, tri[2] + start];
            batch.indices.extend(if mirrored { [a, c, b] } else { [a, b, c] });
        }
    }
    // 全都淡掉了：藏起来，不写空网格（Bevy 会每帧警告）
    if batch.indices.is_empty() {
        **shown = Visibility::Hidden;
        return;
    }
    **shown = Visibility::Inherited;
    if let Some(mut mesh) = meshes.get_mut(&fg.mesh) {
        *mesh = batch.into_mesh();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn foreground_is_deterministic_and_scrolls_faster_than_ground() {
        assert_eq!(fronds(77), fronds(77));
        assert_ne!(fronds(77), fronds(78));
        let f = fronds(77)[1];
        let half = Vec2::new(373.0, 210.0);
        let a = frond_position(f, true, Vec2::ZERO, half);
        let b = frond_position(f, true, Vec2::X * 10.0, half);
        assert!((a.x - b.x - 12.4).abs() < 0.001);
        let c = frond_position(f, true, Vec2::Y * 10.0, half);
        assert!((a.y - c.y - 12.4).abs() < 0.001);
    }

    #[test]
    fn whole_branch_fades_near_player_and_center_is_clear() {
        let branch = Vec2::new(35.0, 80.0);
        assert_eq!(player_fade(branch, Vec2::ZERO, REACH), 0.0);
        assert_eq!(player_fade(branch, branch, REACH), 0.0);
        assert_eq!(player_fade(branch, Vec2::splat(-400.0), REACH), 1.0);
        for half in [Vec2::new(140.0, 210.0), Vec2::new(490.0, 210.0)] {
            assert_eq!(edge_fade(Vec2::ZERO, half), 0.0);
            assert_eq!(edge_fade(half * 0.7, half), 0.0);
            assert!(edge_fade(Vec2::new(0.0, half.y), half) > 0.99);
        }
    }

    #[test]
    fn hazards_clear_foreground_including_budget_overflow() {
        let mut safety = Safety::default();
        safety.protect(Vec2::new(300.0, 190.0), 35.0);
        assert_eq!(safety.fade(Vec2::new(310.0, 210.0), REACH), 0.0);
        assert_eq!(safety.fade(Vec2::new(-300.0, 210.0), REACH), 1.0);
        for _ in 0..32 {
            safety.protect(Vec2::splat(3000.0), 10.0);
        }
        assert_eq!(safety.fade(Vec2::ZERO, REACH), 0.0);
        safety.clear();
        assert_eq!(safety.fade(Vec2::ZERO, REACH), 1.0);
    }
}
