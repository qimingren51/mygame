//! 镜头与时间的手感（docs/FEEL.md）：跟随主角、移动方向上的前瞻、创伤式震屏、方向冲击、
//! 缩放冲击，以及顿帧和慢镜。
//!
//! 全部只在画面层。震屏和缩放不改变模拟的视野（模拟按 21:9 计算，docs/DESIGN.md 第 6.1 节），
//! 缩放只往里推，不会露出视野外刚刷出来的妖物。顿帧和慢镜只调 `Time<Virtual>` 的速度：模拟照样
//! 一步一步走，只是现实时间里走得慢，结果和回放都不受影响。

use bevy::prelude::*;
use bevy::window::PrimaryWindow;

use lantern_content::Rank;
use lantern_core::Pcg32;
use lantern_sim::combat::StrikeFx;
use lantern_sim::{GameContent, Player, Pos, PrevPos, RunState, SimEvent, SimOutbox};

use crate::lighting::{Darkness, LightCamera};
use crate::{MainCamera, layer, to_screen};

/// 震屏最大位移（世界单位）和最大侧倾（弧度），创伤为 1 时取到
const SHAKE_MAX: f32 = 14.0;
const ROLL_MAX: f32 = 0.022;
/// 创伤每秒衰减
const TRAUMA_DECAY: f32 = 1.5;
/// 移动方向上的前瞻距离（世界单位）和跟上的速度
const LEAD: f32 = 16.0;
const LEAD_RATE: f32 = 2.2;
/// 方向冲击弹簧的角频率（越大回弹越快）
const KICK_OMEGA: f32 = 15.0;
/// 同一类顿帧至少隔这么久（现实秒），免得连续暴击把画面卡成幻灯片
const STOP_GAP: f32 = 0.18;

/// 画面手感的开关，由界面层按设置同步（画面层不依赖平台层）。
#[derive(Resource, Clone, Copy, Debug, PartialEq)]
pub struct Feel {
    /// 震屏与缩放冲击的强度，0 为关
    pub shake: f32,
    /// 顿帧与慢镜
    pub hitstop: bool,
    /// 辉光
    pub bloom: bool,
    /// 精简特效：粒子减半，不画环境萤火、夜雾和色散
    pub lite: bool,
}

impl Default for Feel {
    fn default() -> Self {
        Feel { shake: 1.0, hitstop: true, bloom: true, lite: false }
    }
}

/// 镜头的状态。各处特效通过它的方法申请震屏、冲击、缩放和顿帧。
#[derive(Resource)]
pub(crate) struct Rig {
    rng: Pcg32,
    /// 噪声相位
    phase: [f32; 3],
    clock: f32,
    trauma: f32,
    /// 方向冲击：弹簧的位移和速度（屏幕坐标）
    kick: Vec2,
    kick_v: Vec2,
    lead: Vec2,
    /// 缩放冲击：当前推进量（0.08 即放大 8%）、目标、保持时间
    zoom: f32,
    zoom_to: f32,
    zoom_hold: f32,
    /// 顿帧剩余（现实秒）、慢镜剩余与倍率
    stop: f32,
    stop_ready: f32,
    slow: f32,
    slow_len: f32,
    slow_scale: f32,
    /// 镜头的落点（主角 + 前瞻），震屏前
    pub(crate) focus: Vec2,
}

impl Default for Rig {
    fn default() -> Self {
        let mut rng = Pcg32::new(0x5ca1_ab1e, 11);
        let phase = [rng.range_f32(0.0, 100.0), rng.range_f32(0.0, 100.0), rng.range_f32(0.0, 100.0)];
        Rig {
            rng,
            phase,
            clock: 0.0,
            trauma: 0.0,
            kick: Vec2::ZERO,
            kick_v: Vec2::ZERO,
            lead: Vec2::ZERO,
            zoom: 0.0,
            zoom_to: 0.0,
            zoom_hold: 0.0,
            stop: 0.0,
            stop_ready: 0.0,
            slow: 0.0,
            slow_len: 0.0,
            slow_scale: 1.0,
            focus: Vec2::ZERO,
        }
    }
}

impl Rig {
    /// 震屏：创伤叠加，封顶 1（总量预算，大事件同时发生也不会晕）。
    pub fn trauma(&mut self, amount: f32) {
        self.trauma = (self.trauma + amount).min(1.0);
    }

    /// 方向冲击：镜头朝 dir（屏幕坐标）猛地一顿再弹回。
    pub fn kick(&mut self, dir: Vec2, amount: f32) {
        self.kick_v += dir.normalize_or_zero() * amount * 60.0;
    }

    /// 随机方向的小冲击。
    pub fn jolt(&mut self, amount: f32) {
        let a = self.rng.range_f32(0.0, std::f32::consts::TAU);
        self.kick(Vec2::from_angle(a), amount);
    }

    /// 缩放冲击：推进 amount（0.06 即放大 6%），保持 hold 秒后弹回。
    pub fn punch(&mut self, amount: f32, hold: f32) {
        if amount >= self.zoom_to {
            self.zoom_to = amount;
            self.zoom_hold = hold;
        }
    }

    /// 顿帧：画面和模拟一起停 secs 现实秒。
    pub fn hitstop(&mut self, secs: f32) {
        if self.stop_ready > 0.0 {
            return;
        }
        self.stop = self.stop.max(secs);
        self.stop_ready = STOP_GAP + secs;
    }

    /// 慢镜：secs 现实秒内以 scale 倍速运行，最后一段平滑回到正常速度。
    pub fn slowmo(&mut self, secs: f32, scale: f32) {
        self.slow = secs;
        self.slow_len = secs;
        self.slow_scale = scale;
    }

    /// 当前的时间倍率。
    fn time_scale(&self) -> f32 {
        if self.stop > 0.0 {
            return 0.0;
        }
        if self.slow > 0.0 {
            // 后 40% 的时间里缓缓回到 1
            let u = self.slow / self.slow_len.max(1e-3);
            let k = (u / 0.4).min(1.0);
            return self.slow_scale + (1.0 - self.slow_scale) * (1.0 - k * k);
        }
        1.0
    }

    /// 方向冲击：临界阻尼的弹簧，用解析解推进，帧长再大也不会发散。
    fn step_kick(&mut self, dt: f32) {
        let w = KICK_OMEGA;
        let decay = (-w * dt).exp();
        let tmp = self.kick_v + self.kick * w;
        self.kick = (self.kick + tmp * dt) * decay;
        self.kick_v = (self.kick_v - tmp * w * dt) * decay;
    }

    /// 平滑的噪声：几个不成整数比的正弦相加，-1..1。
    fn noise(&self, i: usize) -> f32 {
        let t = self.clock + self.phase[i];
        (t * 31.0).sin() * 0.5 + (t * 47.3).sin() * 0.3 + (t * 73.1).sin() * 0.2
    }
}

/// 模拟事件 → 震屏、冲击、缩放、顿帧、慢镜（docs/FEEL.md 第 2 节的手感表）。
pub(crate) fn camera_events(outbox: Res<SimOutbox>, mut rig: ResMut<Rig>, player: Single<&Player>) {
    for ev in &outbox.0 {
        match *ev {
            // 大暴击停 2 帧（docs/GAMEPLAY.md 第 14 节）
            SimEvent::Hit { damage, crit: true, .. } if damage >= 1000.0 => {
                rig.hitstop(0.035);
                rig.trauma(0.1);
            }
            SimEvent::Kill { rank: Rank::Elite, .. } => {
                rig.trauma(0.3);
                rig.hitstop(0.06);
            }
            SimEvent::PlayerHurt { .. } => {
                rig.trauma(0.32);
                rig.jolt(0.6);
                rig.hitstop(0.045);
            }
            SimEvent::Dash { .. } => rig.kick(-to_screen(player.facing), 0.3),
            SimEvent::Strike { fx, .. } => match fx {
                StrikeFx::Seal { evolved } => {
                    rig.trauma(if evolved { 0.3 } else { 0.15 });
                    rig.kick(Vec2::NEG_Y, if evolved { 0.9 } else { 0.45 });
                }
                StrikeFx::Bamboo => {
                    rig.trauma(0.18);
                    rig.kick(Vec2::Y, 0.55);
                }
                StrikeFx::SwordGrove => {
                    rig.trauma(0.2);
                    rig.kick(Vec2::NEG_Y, 0.6);
                }
                StrikeFx::Quake => rig.trauma(0.42),
                StrikeFx::Toll => {
                    rig.trauma(0.28);
                    rig.punch(0.03, 0.08);
                }
                StrikeFx::Blast(_) => rig.trauma(0.05),
                StrikeFx::Taiji => {
                    rig.trauma(0.25);
                    rig.punch(0.04, 0.15);
                }
                StrikeFx::Ult => {
                    rig.trauma(0.75);
                    rig.punch(0.09, 0.25);
                    rig.hitstop(0.09);
                }
                StrikeFx::Pulse | StrikeFx::None => {}
            },
            SimEvent::SweepStrike { dir, .. } => {
                rig.trauma(0.38);
                rig.kick(to_screen(Vec2::from_angle(dir)), 0.8);
            }
            SimEvent::RainStrike { .. } => rig.trauma(0.08),
            SimEvent::Reaction { first: true, .. } => rig.trauma(0.2),
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                rig.trauma(0.7);
                rig.punch(0.1, 0.4);
                rig.slowmo(0.9, 0.3);
            }
            SimEvent::LanternLit { all, .. } => rig.punch(if all { 0.05 } else { 0.025 }, 0.2),
            SimEvent::Surge => rig.trauma(0.3),
            SimEvent::Encircle { .. } => rig.trauma(0.2),
            SimEvent::BossArrived { .. } => {
                rig.trauma(0.6);
                rig.punch(0.06, 0.6);
            }
            SimEvent::BossPhase { .. } => {
                rig.trauma(0.45);
                rig.hitstop(0.12);
            }
            SimEvent::BossEnraged => rig.trauma(0.3),
            // 夜主倒下：慢镜 1 秒多（docs/GAMEPLAY.md 第 14 节）
            SimEvent::BossDefeated { .. } => {
                rig.trauma(0.9);
                rig.punch(0.12, 0.8);
                rig.hitstop(0.12);
                rig.slowmo(1.6, 0.2);
            }
            SimEvent::PlayerDied => {
                rig.trauma(0.5);
                rig.punch(0.08, 1.2);
            }
            _ => {}
        }
    }
}

pub(crate) fn reset_rig(mut rig: ResMut<Rig>, mut time: ResMut<Time<Virtual>>) {
    let rng = rig.rng.clone();
    *rig = Rig { rng, ..default() };
    time.set_relative_speed(1.0);
}

/// 主角插值位置 + 前瞻 + 冲击 + 震屏；缩放冲击改投影；顿帧与慢镜改虚拟时间的速度。
pub(crate) fn update_rig(
    real: Res<Time<Real>>,
    fixed: Res<Time<Fixed>>,
    feel: Res<Feel>,
    run: Option<Res<State<RunState>>>,
    mut rig: ResMut<Rig>,
    mut time: ResMut<Time<Virtual>>,
    player: Single<(&Pos, &PrevPos, &Player)>,
    mut cam: Single<(&mut Transform, &mut Projection), With<MainCamera>>,
) {
    let dt = real.delta_secs().min(0.1);
    let paused = run.is_some_and(|s| *s.get() == RunState::Paused);
    let rig = &mut *rig;
    rig.clock += dt;

    // ---- 时间：暂停时顿帧、慢镜不倒数（结算时照常倒数，免得一直慢着）
    if !paused {
        rig.stop = (rig.stop - dt).max(0.0);
        rig.slow = (rig.slow - dt).max(0.0);
    }
    rig.stop_ready = (rig.stop_ready - dt).max(0.0);
    let scale = if feel.hitstop { rig.time_scale() } else { 1.0 };
    if (time.relative_speed() - scale).abs() > 1e-4 {
        time.set_relative_speed(scale);
    }

    // ---- 前瞻：移动时朝前看一点，停下后慢慢回中
    let (pos, prev, pl) = *player;
    let hero = to_screen(prev.0.lerp(pos.0, fixed.overstep_fraction()));
    let want = if pl.moved > 0.01 { to_screen(pl.facing).normalize_or_zero() * LEAD } else { Vec2::ZERO };
    rig.lead += (want - rig.lead) * (1.0 - (-dt * LEAD_RATE).exp());
    rig.focus = hero + rig.lead;

    rig.step_kick(dt);

    // ---- 震屏
    rig.trauma = (rig.trauma - dt * TRAUMA_DECAY).max(0.0);
    let s = rig.trauma * rig.trauma * feel.shake;
    let shake = Vec2::new(rig.noise(0), rig.noise(1)) * SHAKE_MAX * s;
    let roll = rig.noise(2) * ROLL_MAX * s;

    // ---- 缩放冲击：很快推进，保持，再弹回
    if rig.zoom_hold > 0.0 {
        rig.zoom_hold -= dt;
        rig.zoom += (rig.zoom_to - rig.zoom) * (1.0 - (-dt * 18.0).exp());
    } else {
        rig.zoom_to = 0.0;
        rig.zoom += (0.0 - rig.zoom) * (1.0 - (-dt * 3.5).exp());
    }
    let zoom = 1.0 / (1.0 + rig.zoom * feel.shake.min(1.0));

    let (tf, proj) = &mut *cam;
    let p = rig.focus + rig.kick * feel.shake.min(1.0) + shake;
    tf.translation.x = p.x;
    tf.translation.y = p.y;
    tf.rotation = if roll == 0.0 { Quat::IDENTITY } else { Quat::from_rotation_z(roll) };
    if let Projection::Orthographic(o) = &mut **proj
        && (o.scale - zoom).abs() > 1e-5
    {
        o.scale = zoom;
    }
}

/// 光照相机和暗层跟着主镜头走（位置、侧倾、缩放）。暗层要和光照图逐像素对齐，所以大小
/// 必须正好等于镜头看到的范围；这里按窗口比例当场算，不用上一帧的 `area`，缩放时不会漏边。
pub(crate) fn follow_main_camera(
    content: Res<GameContent>,
    window: Single<&Window, With<PrimaryWindow>>,
    main: Single<(&Transform, &Projection), (With<MainCamera>, Without<LightCamera>, Without<Darkness>)>,
    mut light_cam: Single<(&mut Transform, &mut Projection), (With<LightCamera>, Without<Darkness>)>,
    mut darkness: Single<(&mut Transform, &mut Visibility), With<Darkness>>,
) {
    let (main_tf, main_proj) = *main;
    let scale = match main_proj {
        Projection::Orthographic(o) => o.scale,
        _ => 1.0,
    };
    let (light_tf, light_proj) = &mut *light_cam;
    light_tf.translation = main_tf.translation;
    light_tf.rotation = main_tf.rotation;
    if let Projection::Orthographic(o) = &mut **light_proj
        && o.scale != scale
    {
        o.scale = scale;
    }
    let size = window.size();
    let aspect = if size.y > 0.0 { size.x / size.y } else { 16.0 / 9.0 };
    let h = content.0.run.view_height * scale;
    let (dark_tf, dark_vis) = &mut *darkness;
    dark_tf.translation = Vec3::new(main_tf.translation.x, main_tf.translation.y, layer::DARKNESS);
    dark_tf.rotation = main_tf.rotation;
    dark_tf.scale = Vec2::new(h * aspect, h).extend(1.0);
    **dark_vis = Visibility::Inherited;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trauma_is_capped() {
        let mut rig = Rig::default();
        for _ in 0..10 {
            rig.trauma(0.4);
        }
        assert_eq!(rig.trauma, 1.0);
    }

    #[test]
    fn hitstop_freezes_then_respects_gap() {
        let mut rig = Rig::default();
        rig.hitstop(0.05);
        assert_eq!(rig.time_scale(), 0.0);
        // 顿帧结束后，间隔内再来一次不生效
        rig.stop = 0.0;
        rig.hitstop(0.05);
        assert_eq!(rig.time_scale(), 1.0);
    }

    #[test]
    fn slowmo_eases_back_to_full_speed() {
        let mut rig = Rig::default();
        rig.slowmo(1.0, 0.2);
        assert!((rig.time_scale() - 0.2).abs() < 1e-5);
        rig.slow = 0.2;
        let mid = rig.time_scale();
        assert!(mid > 0.2 && mid < 1.0, "{mid}");
        rig.slow = 1e-4;
        assert!(rig.time_scale() > 0.99);
    }

    #[test]
    fn kick_spring_is_stable_with_long_frames() {
        let mut rig = Rig::default();
        rig.kick(Vec2::X, 1.0);
        // 读大回放时一帧可能卡几十秒
        for dt in [0.1, 30.0, 0.016, 5.0] {
            rig.step_kick(dt);
            assert!(rig.kick.is_finite() && rig.kick_v.is_finite());
        }
        assert!(rig.kick.length() < 1e-3);
    }
}
