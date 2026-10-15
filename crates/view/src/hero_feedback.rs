//! 主角受伤与无敌提示：只读事件和模拟剩余时间，不延长或缩短保护。

use std::f32::consts::TAU;
use std::time::Duration;

use bevy::asset::embedded_asset;
use bevy::prelude::*;
use bevy::render::render_resource::AsBindGroup;
use bevy::shader::ShaderRef;
use bevy::sprite_render::{AlphaMode2d, Material2d, Material2dPlugin};
use lantern_sim::{AppState, Player, SimEvent};

use crate::actors::HeroView;
use crate::atlas::AtlasDb;
use crate::layer;

/// 用剩余模拟时间定相位，暂停、顿帧时保持原样，归零立即恢复不透明。
pub(crate) fn iframe_alpha(remaining: f32) -> f32 {
    if remaining <= 0.0 {
        return 1.0;
    }
    (0.775 + 0.225 * (TAU * (remaining % 0.1) / 0.1).cos()).clamp(0.55, 1.0)
}

#[derive(Default)]
pub(crate) struct HeroFeedback {
    hurt_age: Option<Duration>,
    rescued: bool,
    /// 这段无敌是挨打或救命给的（闪避也给无敌，但闪避不闪烁）
    blinking: bool,
}

impl HeroFeedback {
    pub fn update(&mut self, events: &[SimEvent], dt: Duration, iframe: f32, dying: bool) {
        self.hurt_age = self.hurt_age.map(|age| age + dt).filter(|age| *age < Duration::from_millis(200));
        for event in events {
            match event {
                SimEvent::PlayerHurt { .. } => {
                    self.hurt_age = Some(Duration::ZERO);
                    self.rescued = false;
                    self.blinking = true;
                }
                SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                    self.rescued = true;
                    self.blinking = true;
                }
                _ => {}
            }
        }
        // 同帧受伤、救命按模拟事件顺序处理；新的受伤也能清掉漏过归零帧的旧金边。
        self.rescued &= iframe > 0.0 && !dying;
        self.blinking &= iframe > 0.0 && !dying;
        if dying {
            self.hurt_age = None;
        }
    }

    /// 主角的不透明度：挨打、救命给的无敌里闪烁，闪避的无敌不闪。
    pub fn alpha(&self, iframe: f32) -> f32 {
        if self.blinking { iframe_alpha(iframe) } else { 1.0 }
    }

    pub fn hurt_frame(&self, fps: f32) -> Option<usize> {
        self.hurt_age.map(|age| (age.as_secs_f64() * f64::from(fps)) as usize)
    }

    fn outline(&self, iframe: f32) -> (Color, bool) {
        let flash = self.hurt_age.is_some_and(|age| age < Duration::from_millis(60));
        if self.rescued && iframe > 0.0 {
            (Color::srgba(1.0, 0.72, 0.18, (iframe / 0.2).clamp(0.0, 1.0)), flash)
        } else if flash {
            (Color::WHITE, true)
        } else {
            (Color::NONE, false)
        }
    }
}

pub(crate) struct HeroFeedbackPlugin;

impl Plugin for HeroFeedbackPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "hero_feedback.wesl");
        app.add_plugins(Material2dPlugin::<OutlineMaterial>::default())
            .add_systems(OnEnter(AppState::Run), spawn);
    }
}

/// 只采样图集 alpha；不需要新增闪白素材，也不会把相邻图集帧带进轮廓。
#[derive(Asset, TypePath, AsBindGroup, Debug, Clone)]
pub(crate) struct OutlineMaterial {
    #[uniform(0)]
    color: LinearRgba,
    #[uniform(0)]
    uv_rect: Vec4,
    /// xy：一世界单位对应的 UV；z：是否填充闪白。
    #[uniform(0)]
    step_fill: Vec4,
    #[texture(1)]
    #[sampler(2)]
    texture: Handle<Image>,
}

impl Material2d for OutlineMaterial {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_view/hero_feedback.wesl".into()
    }

    fn alpha_mode(&self) -> AlphaMode2d {
        AlphaMode2d::Blend
    }
}

#[derive(Component)]
pub(crate) struct HeroOutline {
    lantern: bool,
}

fn spawn(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<OutlineMaterial>>,
) {
    let quad = meshes.add(Rectangle::new(1.0, 1.0));
    for lantern in [false, true] {
        commands.spawn((
            HeroOutline { lantern },
            Mesh2d(quad.clone()),
            MeshMaterial2d(materials.add(OutlineMaterial {
                color: LinearRgba::NONE,
                uv_rect: Vec4::ZERO,
                step_fill: Vec4::ZERO,
                texture: Handle::default(),
            })),
            Transform::default(),
            Visibility::Hidden,
            DespawnOnExit(AppState::Run),
        ));
    }
}

pub(crate) fn draw(
    db: Res<AtlasDb>,
    hero: Single<(&Player, &HeroView, &Transform)>,
    mut outlines: Query<
        (&HeroOutline, &MeshMaterial2d<OutlineMaterial>, &mut Transform, &mut Visibility),
        Without<Player>,
    >,
    mut materials: ResMut<Assets<OutlineMaterial>>,
) {
    let (player, view, hero_tf) = *hero;
    let (color, fill) = view.feedback.outline(player.iframe);
    for (outline, material, mut tf, mut visibility) in &mut outlines {
        let id = if outline.lantern { view.lantern_id } else { view.frame_id };
        let Some(id) = id.filter(|_| color.alpha() > 0.0) else {
            *visibility = Visibility::Hidden;
            continue;
        };
        *visibility = Visibility::Visible;
        let frame = db.frame(id);
        // 裁边图集的锚点仍对齐脚底，外扩一世界单位容纳描边。
        let center = hero_tf.translation.truncate() - frame.anchor.0 * frame.size;
        tf.translation = center.extend(layer::EMISSIVE + 0.5 + f32::from(outline.lantern) * 0.01);
        tf.scale = (frame.size + Vec2::splat(2.0)).extend(1.0);
        if let Some(mut material) = materials.get_mut(&material.0) {
            let step = frame.uv.size() / frame.size;
            material.color = color.to_linear();
            material.uv_rect = Vec4::new(frame.uv.min.x, frame.uv.min.y, frame.uv.max.x, frame.uv.max.y);
            material.step_fill = Vec4::new(step.x, step.y, f32::from(fill), 0.0);
            material.texture = db.image(id);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::HurtBy;

    #[test]
    fn dash_invincibility_does_not_blink_but_hurt_does() {
        let mut f = HeroFeedback::default();
        // 闪避：有无敌，没有受伤事件
        f.update(&[], Duration::from_millis(16), 0.45, false);
        assert_eq!(f.alpha(0.45), 1.0);
        let hurt = SimEvent::PlayerHurt { amount: 5.0, by: lantern_sim::HurtBy::Shot, from: Vec2::X };
        f.update(&[hurt], Duration::from_millis(16), 0.45, false);
        assert!(f.alpha(0.45) < 1.0);
        // 无敌结束就停
        f.update(&[], Duration::from_millis(16), 0.0, false);
        f.update(&[], Duration::from_millis(16), 0.45, false);
        assert_eq!(f.alpha(0.45), 1.0);
    }

    #[test]
    fn iframe_alpha_has_a_100ms_period_and_stays_in_range() {
        for remaining in [0.025, 0.05, 0.075, 0.1, 0.237, 0.5, 2.0] {
            let alpha = iframe_alpha(remaining);
            assert!((0.55..=1.0).contains(&alpha));
            assert!((alpha - iframe_alpha(remaining + 0.1)).abs() < 1e-5);
        }
        assert!((iframe_alpha(0.5) - 1.0).abs() < 1e-5);
        assert!((iframe_alpha(0.45) - 0.55).abs() < 1e-5);
        assert!((iframe_alpha(0.475) - 0.775).abs() < 1e-5);
        assert_eq!(iframe_alpha(0.0), 1.0);
        assert_eq!(iframe_alpha(-0.1), 1.0);
    }

    #[test]
    fn hurt_starts_at_frame_zero_and_rescue_tracks_simulated_protection() {
        let hurt = SimEvent::PlayerHurt { amount: 10.0, by: HurtBy::Shot, from: Vec2::X };
        let mut view = HeroFeedback::default();
        view.update(&[hurt], Duration::from_millis(200), 0.5, false);
        assert_eq!(view.hurt_frame(10.0), Some(0));
        assert_eq!(view.outline(0.5), (Color::WHITE, true));
        view.update(&[], Duration::from_millis(60), 0.44, false);
        assert_eq!(view.outline(0.44), (Color::NONE, false));
        view.update(&[], Duration::from_millis(40), 0.4, false);
        assert_eq!(view.hurt_frame(10.0), Some(1));
        view.update(&[], Duration::from_millis(100), 0.3, false);
        assert_eq!(view.hurt_frame(10.0), None);
        for rescue in [SimEvent::Revived { pos: Vec2::ZERO }, SimEvent::LastStand { pos: Vec2::ZERO }] {
            view.update(&[hurt, rescue], Duration::from_millis(0), 2.0, false);
            view.update(&[], Duration::from_millis(10000), 2.0, false);
            assert_eq!(view.outline(2.0), (Color::srgb(1.0, 0.72, 0.18), false));
            assert_eq!(view.outline(0.1).0.alpha(), 0.5);
            view.update(&[], Duration::from_millis(0), 0.0, false);
            assert_eq!(view.outline(0.0).0.alpha(), 0.0);
        }
        view.update(&[hurt, SimEvent::Revived { pos: Vec2::ZERO }], Duration::from_millis(0), 2.0, false);
        view.update(&[hurt], Duration::from_millis(0), 0.5, false);
        assert_eq!(view.outline(0.5), (Color::WHITE, true));
        view.update(&[], Duration::from_millis(0), 0.5, true);
        assert_eq!(view.outline(0.5), (Color::NONE, false));
    }
}
