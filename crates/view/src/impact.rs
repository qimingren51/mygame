//! 目标句柄驱动的受击姿态与致死衔接；计时、偏移和形变都只在画面层。

use std::collections::BTreeMap;

use bevy::prelude::*;
use lantern_content::WeaponIdentity;
use lantern_sim::enemies::EnemyHandle;
use lantern_sim::{Enemies, GameContent, HitKind, SimEvent, SimOutbox};

use crate::actors::{ActorFrames, Draw, GlowRequests, Pools};
use crate::atlas::FrameId;
use crate::{layer, to_screen};

#[derive(Clone, Copy)]
pub(crate) struct Response {
    pub age: f32,
    pub dir: Vec2,
    pub identity: Option<WeaponIdentity>,
    pub crit: bool,
}

impl Response {
    fn duration(self) -> f32 {
        let base = if self.crit { 0.08 } else { 0.05 };
        base + match self.identity {
            Some(WeaponIdentity::Seal) => 0.01,
            Some(WeaponIdentity::Sword | WeaponIdentity::Bell) => -0.005,
            _ => 0.0,
        }
    }

    /// 受击闪白多久：GAMEPLAY 第 14 节的 0.08 秒，暴击 0.1 秒（形变回弹另按 `duration`）。
    fn flash_len(self) -> f32 {
        if self.crit { 0.1 } else { 0.08 }
    }

    pub fn flashing(self) -> bool {
        self.age < self.flash_len()
    }

    /// 闪白的强度：起手最亮，0.08 秒里淡完（画在暗层之上的那层白影用）。
    pub fn flash_strength(self) -> f32 {
        (1.0 - self.age / self.flash_len()).clamp(0.0, 1.0)
    }

    /// 沿入射轴压缩，垂直轴拉伸；不旋转妖物本来的朝向。
    pub fn sample(self) -> (Mat2, Vec2) {
        let hold = self.duration();
        let dir = self.dir.normalize_or(Vec2::Y);
        let side = dir.perp();
        let strength = match self.identity {
            Some(WeaponIdentity::Seal) => 1.2,
            Some(WeaponIdentity::Sword) => 0.9,
            _ => 1.0,
        };
        let (along, across, push) = if self.age < hold {
            let k =
                if self.identity == Some(WeaponIdentity::Bell) { 1.0 } else { 1.0 - 0.2 * self.age / hold };
            let power = strength * k * if self.crit { 2.0 } else { 1.0 };
            (1.0 - 0.08 * power, 1.0 + 0.10 * power, (1.5 * power).min(3.0))
        } else {
            let k = (1.0 - (self.age - hold) / 0.05).clamp(0.0, 1.0);
            (1.0 + 0.03 * k, 1.0 - 0.03 * k, -0.4 * k)
        };
        let axes = Mat2::from_cols(dir, side);
        let matrix = axes * Mat2::from_diagonal(Vec2::new(along, across)) * axes.transpose();
        let lateral =
            if self.identity == Some(WeaponIdentity::Crane) { side * push * 0.6 } else { Vec2::ZERO };
        (matrix, dir * push + lateral)
    }
}

#[derive(Clone, Copy)]
pub(crate) struct Pose {
    pub frame: FrameId,
    pub flash: FrameId,
    pub pos: Vec2,
    pub flip: bool,
}

struct Dying {
    pose: Pose,
    response: Option<Response>,
    age: f32,
    life: f32,
    priority: u8,
}

#[derive(Resource, Default)]
pub(crate) struct Impacts {
    pub hits: BTreeMap<EnemyHandle, Response>,
    pub poses: BTreeMap<EnemyHandle, Pose>,
    dying: Vec<Dying>,
}

pub(crate) fn reset(mut state: ResMut<Impacts>) {
    *state = Impacts::default();
}

pub(crate) fn read_events(
    time: Res<Time>,
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    en: Option<Res<Enemies>>,
    frames: Res<ActorFrames>,
    mut state: ResMut<Impacts>,
) {
    let dt = time.delta_secs();
    state.hits.retain(|_, hit| {
        hit.age += dt;
        hit.age < hit.duration() + 0.05
    });
    state.dying.retain_mut(|d| {
        d.age += dt;
        d.age < d.life
    });
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { target, incoming_dir, weapon, crit, kind, .. }
                if !matches!(kind, HitKind::Dot | HitKind::Reaction) =>
            {
                let response = Response {
                    age: 0.0,
                    dir: to_screen(incoming_dir),
                    crit,
                    identity: WeaponIdentity::resolve(&content.0, weapon),
                };
                // 同帧普通命中不覆盖暴击的峰值。
                if !state.hits.get(&target).is_some_and(|h| h.crit && h.age == 0.0 && !crit) {
                    state.hits.insert(target, response);
                }
            }
            SimEvent::Kill { target, kind, pos, rank, .. } => {
                let response = state.hits.remove(&target);
                let pose = state.poses.remove(&target).or_else(|| {
                    frames.enemy_ghost(kind as usize).map(|f| Pose {
                        frame: f,
                        flash: f,
                        pos: to_screen(pos),
                        flip: false,
                    })
                });
                if let Some(pose) = pose {
                    let life = match rank {
                        lantern_content::Rank::Boss => 1.2,
                        lantern_content::Rank::Elite => 0.45,
                        _ => 0.23,
                    };
                    let priority = match rank {
                        lantern_content::Rank::Boss => 2,
                        lantern_content::Rank::Elite => 1,
                        _ => 0,
                    };
                    // 死亡姿态有独立上限，杂兵不挤掉夜主和精英。
                    if state.dying.len() == 64 {
                        let (i, old) =
                            state.dying.iter().enumerate().min_by_key(|(_, d)| d.priority).unwrap();
                        if old.priority > priority {
                            continue;
                        }
                        state.dying.remove(i);
                    }
                    state.dying.push(Dying { pose, response, age: 0.0, life, priority });
                }
            }
            _ => {}
        }
    }
    if let Some(en) = en {
        state.poses.retain(|h, _| en.resolve(*h).is_some());
        state.hits.retain(|h, _| en.resolve(*h).is_some());
    }
}

pub(crate) fn draw_deaths(state: Res<Impacts>, mut pools: ResMut<Pools>, mut glow: ResMut<GlowRequests>) {
    for d in &state.dying {
        // 倒下那一下的亮：叠加的白影画在暗层之上，月夜的暗处也亮得起来、发得了光（试玩第 1 轮）
        if d.age < 0.08 {
            let k = 1.0 - d.age / 0.08;
            glow.add_flipped(
                d.pose.flash,
                (d.pose.pos + Vec2::Y * (d.age * 8.0)).extend(layer::EMISSIVE - 0.2),
                Vec2::splat(1.0 + 0.12 * (1.0 - k)),
                0.0,
                Color::srgb(1.25, 1.15, 1.0).with_alpha(0.42 * k * k),
                d.pose.flip,
            );
        }
        let confirm = d.age < 0.03;
        let fade = (1.0 - (d.age - 0.03).max(0.0) / (d.life - 0.03)).clamp(0.0, 1.0);
        let (deform, offset) = d
            .response
            .map_or((Mat2::IDENTITY, Vec2::ZERO), |r| Response { age: r.age + d.age, ..r }.sample());
        let color = if confirm {
            Color::srgb(1.0, 0.97, 0.87)
        } else {
            crate::particles::INK.with_alpha(fade * 0.75)
        };
        pools.fx.push(Draw {
            flip: d.pose.flip,
            color,
            deform,
            scale: Vec2::splat(1.0 + 0.08 * (1.0 - fade)),
            ..Draw::new(
                if confirm { d.pose.flash } else { d.pose.frame },
                (d.pose.pos + offset + Vec2::Y * (d.age * 8.0)).extend(layer::ACTORS + 1.1),
            )
        });
    }
}

/// Sprite 的局部轴不能表达斜向挤压，在传播之后只修改渲染用的仿射矩阵。
#[derive(Component)]
pub(crate) struct SpriteDeform(pub Mat2);

pub(crate) fn apply_deform(mut sprites: Query<(&SpriteDeform, &Transform, &mut GlobalTransform)>) {
    for (d, tf, mut global) in &mut sprites {
        let m = Mat4::from_cols(
            d.0.x_axis.extend(0.0).extend(0.0),
            d.0.y_axis.extend(0.0).extend(0.0),
            Vec4::Z,
            Vec4::W,
        );
        *global = GlobalTransform::from(tf.to_matrix() * m);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn squeeze_and_rebound_follow_the_incoming_axis() {
        let dir = Vec2::new(1.0, 1.0).normalize();
        let base = Response { age: 0.0, dir, identity: None, crit: false };
        let (m, offset) = base.sample();
        assert!((m * dir - dir * 0.92).length() < 1e-5);
        assert!((m * dir.perp() - dir.perp() * 1.10).length() < 1e-5);
        assert!(offset.dot(dir) > 1.0);
        let (m, _) = Response { crit: true, ..base }.sample();
        assert!(((m * dir).length() - 0.84).abs() < 1e-5);
        let (m, _) = Response { age: 0.05, ..base }.sample();
        assert!(((m * dir).length() - 1.03).abs() < 1e-5);
        assert!(((m * dir.perp()).length() - 0.97).abs() < 1e-5);
        let (m, p) = Response { age: 0.11, ..base }.sample();
        assert!((m * dir - dir).length() < 1e-5);
        assert_eq!(p, Vec2::ZERO);
        assert!(Response { dir: Vec2::ZERO, ..base }.sample().0.is_finite());
    }

    #[test]
    fn held_pose_does_not_accumulate_and_recovers_on_pool_reuse() {
        let mut app = App::new();
        app.add_systems(Update, apply_deform);
        let response =
            Response { age: 0.0, dir: Vec2::new(1.0, 2.0), identity: Some(WeaponIdentity::Seal), crit: true };
        let transform = Transform::from_xyz(10.0, 20.0, 100.0);
        let entity = app.world_mut().spawn((transform, SpriteDeform(response.sample().0))).id();
        app.update();
        let first = *app.world().get::<GlobalTransform>(entity).unwrap();
        for _ in 0..5 {
            app.update();
        }
        assert_eq!(app.world().get::<GlobalTransform>(entity).unwrap().to_matrix(), first.to_matrix());
        app.world_mut().get_mut::<SpriteDeform>(entity).unwrap().0 = Mat2::IDENTITY;
        app.update();
        assert_eq!(app.world().get::<GlobalTransform>(entity).unwrap().to_matrix(), transform.to_matrix());
    }

    #[test]
    fn material_pose_timings_and_offsets_remain_bounded() {
        let base = Response { age: 0.0, dir: Vec2::X, identity: None, crit: false };
        for identity in WeaponIdentity::ALL {
            for crit in [false, true] {
                let r = Response { identity: Some(identity), crit, ..base };
                let range = if crit { 0.074..=0.091 } else { 0.044..=0.061 };
                assert!(range.contains(&r.duration()));
                let (m, offset) = r.sample();
                assert!(offset.length() < 3.6 && offset.dot(Vec2::X) >= 1.0);
                assert!((m * Vec2::X).length() < 1.0);
            }
        }
        let bell = Response { identity: Some(WeaponIdentity::Bell), ..base };
        assert_eq!(bell.sample(), Response { age: 0.03, ..bell }.sample());
        assert!(Response { age: 0.07, ..bell }.flashing());
        assert!(!Response { age: 0.08, ..bell }.flashing());
        assert!(Response { age: 0.09, crit: true, ..bell }.flashing());
    }
}
