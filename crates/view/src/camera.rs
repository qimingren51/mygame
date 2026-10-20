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

use crate::feedback::{Feedback, Priority};
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
/// 攻击顿帧至少隔这么久（现实秒）；受伤和死亡不走这个冷却。
const STOP_GAP: f32 = 0.18;
/// 短于这个的是轻顿帧（暴击、打中精英），单独冷却：连着暴击也不会一卡一卡，也不挡住更重的顿帧。
const LIGHT_STOP: f32 = 0.03;
const LIGHT_GAP: f32 = 0.7;

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
    /// 伤害数字显示多少
    pub numbers: NumberMode,
}

/// 伤害数字：全部、只看暴击、关。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum NumberMode {
    #[default]
    All,
    Crit,
    Off,
}

impl Default for Feel {
    fn default() -> Self {
        Feel { shake: 1.0, hitstop: true, bloom: true, lite: false, numbers: NumberMode::All }
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
    /// 保护玩家反馈直到震屏、缩放保持和顿帧结束，期间不接收低级镜头冲击。
    protected_priority: Priority,
    protected_left: f32,
    /// 方向冲击：弹簧的位移和速度（屏幕坐标）
    kick: Vec2,
    kick_v: Vec2,
    lead: Vec2,
    /// 缩放冲击：当前推进量（0.08 即放大 8%）、目标、保持时间
    zoom: f32,
    zoom_to: f32,
    zoom_hold: f32,
    /// 顿帧剩余（现实秒）；只有攻击请求记录冷却与等级。
    stop: f32,
    stop_ready: f32,
    stop_priority: Priority,
    stop_fresh: bool,
    light_ready: f32,
    slow_priority: Priority,
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
            protected_priority: Priority::Ambient,
            protected_left: 0.0,
            kick: Vec2::ZERO,
            kick_v: Vec2::ZERO,
            lead: Vec2::ZERO,
            zoom: 0.0,
            zoom_to: 0.0,
            zoom_hold: 0.0,
            stop: 0.0,
            stop_ready: 0.0,
            stop_priority: Priority::Ambient,
            stop_fresh: false,
            light_ready: 0.0,
            slow_priority: Priority::Ambient,
            slow: 0.0,
            slow_len: 0.0,
            slow_scale: 1.0,
            focus: Vec2::ZERO,
        }
    }
}

impl Rig {
    /// 同帧和连续小事件只补到该级强度，不能靠堆数量超过大事件。
    pub fn trauma(&mut self, amount: f32) {
        self.trauma = self.trauma.max(amount.min(1.0));
    }

    /// 方向冲击：镜头朝 dir（屏幕坐标）猛地一顿再弹回。
    pub fn kick(&mut self, dir: Vec2, amount: f32) {
        let velocity = dir.normalize_or_zero() * amount * 60.0;
        if velocity.length_squared() >= self.kick_v.length_squared() {
            self.kick_v = velocity;
        }
    }

    /// 随机方向的小冲击。
    pub fn jolt(&mut self, amount: f32) {
        let a = self.rng.range_f32(0.0, std::f32::consts::TAU);
        self.kick(Vec2::from_angle(a), amount);
    }

    /// 缩放冲击：推进 amount（0.06 即放大 6%），保持 hold 秒后弹回。
    pub fn punch(&mut self, amount: f32, hold: f32) {
        if amount > 0.0 && amount >= self.zoom_to {
            self.zoom_to = amount;
            self.zoom_hold = hold;
        }
    }

    /// 顿帧：画面和模拟一起停 secs 现实秒。
    pub fn hitstop(&mut self, secs: f32, priority: Priority) {
        let light = secs < LIGHT_STOP && !priority.protected();
        if secs <= 0.0
            || (light && self.light_ready > 0.0)
            || (!priority.protected()
                && !self.stop_fresh
                && self.stop_ready > 0.0
                && priority <= self.stop_priority)
        {
            return;
        }
        if light {
            self.light_ready = LIGHT_GAP;
        } else if !priority.protected() {
            self.stop_priority =
                if self.stop_ready > 0.0 { self.stop_priority.max(priority) } else { priority };
            self.stop_ready = self.stop_ready.max(STOP_GAP + secs);
        }
        self.stop_fresh = true;
        self.stop = self.stop.max(secs);
    }

    /// 慢镜：secs 现实秒内以 scale 倍速运行，最后一段平滑回到正常速度。
    pub fn slowmo(&mut self, secs: f32, scale: f32, priority: Priority) {
        if self.slow > 0.0 && priority < self.slow_priority {
            return;
        }
        self.slow_priority = priority;
        self.slow = secs;
        self.slow_len = secs;
        self.slow_scale = scale;
    }

    fn advance_time(&mut self, dt: f32) {
        self.stop_fresh = false;
        let after_stop = (dt - self.stop).max(0.0);
        self.stop = (self.stop - dt).max(0.0);
        self.slow = (self.slow - after_stop).max(0.0);
        self.stop_ready = (self.stop_ready - dt).max(0.0);
        self.light_ready = (self.light_ready - dt).max(0.0);
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

/// 收新事件前推进旧顿帧、慢镜和冷却；计时用完整现实帧长，不受镜头积分上限影响。
pub(crate) fn advance_rig_time(
    real: Res<Time<Real>>,
    run: Option<Res<State<RunState>>>,
    mut rig: ResMut<Rig>,
) {
    // 暂停时不倒数；结算时照常倒数，免得一直慢着。
    let paused = run.is_some_and(|s| *s.get() == RunState::Paused);
    rig.advance_time(if paused { 0.0 } else { real.delta_secs() });
}

/// 模拟事件 → 震屏、冲击、缩放、顿帧、慢镜（docs/FEEL.md 第 2 节的手感表）。
pub(crate) fn camera_events(
    outbox: Res<SimOutbox>,
    feedback: Res<Feedback>,
    mut rig: ResMut<Rig>,
    player: Single<(&Player, &Pos)>,
    (content, enemies): (Res<lantern_sim::GameContent>, Option<Res<lantern_sim::Enemies>>),
    (phase, mut evolving): (Option<Res<lantern_sim::SimPhase>>, Local<bool>),
) {
    let (player, pos) = *player;
    let mut impulse = camera_impulse(&outbox.0, player.facing, pos.0);
    // 进化：卡片收起、回到战斗的那一刻，镜头一推一震（和粒子的进化爆发同一刻）
    *evolving |= outbox.0.iter().any(|e| matches!(e, SimEvent::Evolve { .. }));
    if *evolving && phase.as_deref() == Some(&lantern_sim::SimPhase::Play) {
        *evolving = false;
        if impulse.priority <= Priority::Ultimate {
            impulse.priority = Priority::Ultimate;
            impulse.trauma = impulse.trauma.max(0.5);
            impulse.zoom = impulse.zoom.max(0.08);
            impulse.hold = impulse.hold.max(0.3);
        }
    }
    // 精英、夜主挨了直接一击：一下很轻的顿帧（没有更重的顿帧时）
    if impulse.stop == 0.0
        && let Some(en) = &enemies
        && outbox.0.iter().any(|e| match e {
            SimEvent::Hit { target, kind, .. } if *kind != lantern_sim::HitKind::Dot => en
                .resolve(*target)
                .and_then(|i| content.0.enemies.get(usize::from(en.kind[i])))
                .is_some_and(|d| matches!(d.rank, Rank::Elite | Rank::Boss)),
            _ => false,
        })
    {
        impulse.stop = 0.015;
        impulse.priority = impulse.priority.max(Priority::Normal);
    }
    apply_impulse(&mut rig, &feedback, impulse);
}

fn apply_impulse(rig: &mut Rig, feedback: &Feedback, impulse: Impulse) {
    // 受伤的保护期里丢掉普通冲击，但夜主倒下（终幕）照常
    if rig.protected_left > 0.0
        && impulse.priority < rig.protected_priority
        && impulse.priority != Priority::Finale
    {
        return;
    }
    if impulse.priority.protected() {
        // 清掉先前攻击留下的速度与强度，受伤不会被更大的攻击残量盖住。
        rig.trauma = 0.0;
        rig.kick = Vec2::ZERO;
        rig.kick_v = Vec2::ZERO;
        rig.zoom_to = 0.0;
        rig.zoom_hold = 0.0;
        rig.protected_priority = impulse.priority;
        rig.protected_left = (impulse.trauma / TRAUMA_DECAY).max(impulse.hold).max(impulse.stop);
    }
    let weight = feedback.visibility(impulse.priority);
    rig.trauma(impulse.trauma * weight);
    if impulse.jolt > 0.0 {
        rig.jolt(impulse.jolt * weight);
    }
    rig.kick(impulse.kick, impulse.kick.length() * weight);
    rig.punch(impulse.zoom * weight, impulse.hold);
    if impulse.stop > 0.0 && weight == 1.0 {
        rig.hitstop(impulse.stop, impulse.priority);
    }
    if impulse.slow > 0.0 && weight == 1.0 {
        rig.slowmo(impulse.slow, impulse.scale, impulse.priority);
    }
}

/// 每帧只保留最高级的冲击；顿帧独立取最长，同级其余通道取最大值。
#[derive(Default, Debug, PartialEq)]
struct Impulse {
    priority: Priority,
    trauma: f32,
    kick: Vec2,
    jolt: f32,
    zoom: f32,
    hold: f32,
    stop: f32,
    slow: f32,
    scale: f32,
}

fn camera_impulse(events: &[SimEvent], facing: Vec2, hero: Vec2) -> Impulse {
    let mut best = Impulse::default();
    let mut stop: f32 = 0.0;
    // 救命（回光、九转金丹）和终幕的慢镜、推镜：同一帧还挨了打也要留着
    let mut keep = Impulse::default();
    for event in events {
        let mut cue = Impulse { priority: Priority::of(event), ..default() };
        match *event {
            // 暴击都有一下轻顿帧，大暴击停 2 帧（跟着设置里的顿帧开关，0.18 秒内不连顿）
            SimEvent::Hit { damage, crit: true, .. } => {
                cue.stop = if damage >= 1000.0 { 0.035 } else { 0.02 };
                cue.trauma = 0.16;
            }
            SimEvent::Kill { rank: Rank::Elite, .. } => {
                cue.trauma = 0.3;
                cue.stop = 0.06;
            }
            SimEvent::PlayerHurt { from, .. } => {
                cue.trauma = 0.32;
                cue.kick = -to_screen(crate::atmos::hurt_from(hero, from)) * 0.6;
                cue.stop = 0.045;
            }
            SimEvent::Dash { .. } => cue.kick = -to_screen(facing).normalize_or_zero() * 0.3,
            // 新法器（试玩第 1 轮）：孔明灯落地轻轻一震；镇妖塔砸下来往下一顿（比落印重一点），
            // 玲珑塔炸开一震一推；北冥潮一圈涌出去轻轻一震。普通的浪和青藤不动镜头
            SimEvent::LanternBurst { evolved, .. } => cue.trauma = if evolved { 0.1 } else { 0.07 },
            SimEvent::TowerLand { evolved, .. } => {
                cue.trauma = if evolved { 0.26 } else { 0.18 };
                cue.kick = Vec2::NEG_Y * if evolved { 0.75 } else { 0.55 };
            }
            SimEvent::TowerBurst { .. } => {
                cue.priority = cue.priority.max(Priority::Impact);
                cue.trauma = 0.35;
                cue.zoom = 0.03;
                cue.hold = 0.15;
            }
            SimEvent::Wave { ring: true, .. } => cue.trauma = 0.12,
            SimEvent::Strike { fx, .. } => match fx {
                StrikeFx::Seal { evolved } => {
                    cue.trauma = if evolved { 0.3 } else { 0.15 };
                    cue.kick = Vec2::NEG_Y * if evolved { 0.9 } else { 0.45 };
                }
                // 竹印：巨竹从地下往上顶；万剑冢：群剑往下落
                StrikeFx::Bamboo => {
                    cue.trauma = 0.18;
                    cue.kick = Vec2::Y * 0.55;
                }
                StrikeFx::SwordGrove => {
                    cue.trauma = 0.2;
                    cue.kick = Vec2::NEG_Y * 0.6;
                }
                StrikeFx::Quake => cue.trauma = 0.42,
                StrikeFx::Toll => {
                    cue.trauma = 0.28;
                    cue.zoom = 0.03;
                    cue.hold = 0.08;
                }
                StrikeFx::Blast(_) => cue.trauma = 0.05,
                StrikeFx::Taiji => {
                    cue.trauma = 0.25;
                    cue.zoom = 0.04;
                    cue.hold = 0.15;
                }
                StrikeFx::Ult => {
                    cue.trauma = 0.75;
                    cue.zoom = 0.09;
                    cue.hold = 0.25;
                    cue.stop = 0.09;
                }
                StrikeFx::Pulse | StrikeFx::None => continue,
            },
            SimEvent::SweepStrike { dir, .. } => {
                cue.trauma = 0.38;
                cue.kick = to_screen(Vec2::from_angle(dir)) * 0.8;
            }
            SimEvent::RainStrike { .. } => cue.trauma = 0.08,
            SimEvent::Reaction { first: true, .. } => cue.trauma = 0.2,
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                cue.trauma = 0.7;
                cue.zoom = 0.1;
                cue.hold = 0.4;
                cue.slow = 0.9;
                cue.scale = 0.3;
            }
            SimEvent::LanternLit { all, .. } => {
                cue.zoom = if all { 0.05 } else { 0.025 };
                cue.hold = 0.2;
            }
            SimEvent::Surge => cue.trauma = 0.3,
            SimEvent::Encircle { .. } => cue.trauma = 0.2,
            SimEvent::BossArrived { .. } => {
                cue.trauma = 0.6;
                cue.zoom = 0.06;
                cue.hold = 0.6;
            }
            SimEvent::BossPhase { .. } => {
                cue.trauma = 0.45;
                cue.stop = 0.12;
            }
            SimEvent::BossEnraged => cue.trauma = 0.3,
            SimEvent::BossDefeated { .. } => {
                cue.trauma = 0.9;
                cue.zoom = 0.12;
                cue.hold = 0.8;
                cue.stop = 0.12;
                cue.slow = 1.6;
                cue.scale = 0.2;
            }
            SimEvent::PlayerDied => {
                cue.trauma = 0.5;
                cue.zoom = 0.08;
                cue.hold = 1.2;
            }
            _ => continue,
        }
        stop = stop.max(cue.stop);
        if matches!(
            event,
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } | SimEvent::BossDefeated { .. }
        ) && cue.slow > keep.slow
        {
            keep = Impulse { slow: cue.slow, scale: cue.scale, zoom: cue.zoom, hold: cue.hold, ..default() };
        }
        if cue.priority > best.priority {
            best = cue;
        } else if cue.priority == best.priority {
            best.trauma = best.trauma.max(cue.trauma);
            best.jolt = best.jolt.max(cue.jolt);
            if cue.kick.length_squared() > best.kick.length_squared() {
                best.kick = cue.kick;
            }
            if cue.zoom > best.zoom || (cue.zoom == best.zoom && cue.hold > best.hold) {
                best.zoom = cue.zoom;
                best.hold = cue.hold;
            }
            if cue.slow > best.slow {
                best.slow = cue.slow;
                best.scale = cue.scale;
            }
        }
    }
    best.stop = stop;
    // 倒下的那一刻只演倒下
    if best.priority == Priority::Death {
        return best;
    }
    if keep.slow > best.slow {
        best.slow = keep.slow;
        best.scale = keep.scale;
    }
    if keep.zoom > best.zoom {
        best.zoom = keep.zoom;
        best.hold = best.hold.max(keep.hold);
    }
    best
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
    mut rig: ResMut<Rig>,
    mut time: ResMut<Time<Virtual>>,
    player: Single<(&Pos, &PrevPos, &Player)>,
    mut cam: Single<(&mut Transform, &mut Projection), With<MainCamera>>,
    speed: Option<Res<crate::SimSpeed>>,
) {
    let dt = real.delta_secs().min(0.1);
    let rig = &mut *rig;
    rig.clock += dt;
    rig.protected_left = (rig.protected_left - dt).max(0.0);

    // ---- 时间：旧计时已在收事件前推进，新请求完整保留到下一帧。
    // 开发者选项的流速是基础倍率，顿帧、慢镜在它上面再乘
    let base = speed.map_or(1.0, |s| s.0);
    let scale = (if feel.hitstop { rig.time_scale() } else { 1.0 }) * base;
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
    // 小冲击也要抖得出来（试玩第 1 轮：暴击 0.1 按平方只抖 0.14 单位，等于没抖）：
    // 线性和平方各占一部分，创伤为 1 时还是满幅，0.1 时约 4 倍于原来
    let s = (0.35 * rig.trauma + 0.65 * rig.trauma * rig.trauma) * feel.shake;
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
    use crate::feedback::prepare_feedback;
    use crate::fx::{FxState, ScreenFlash, apply_flash, hex, read_fx_events};
    use bevy::ecs::system::RunSystemOnce;
    use lantern_sim::{HitKind, HurtBy};

    fn hurt() -> SimEvent {
        SimEvent::PlayerHurt { amount: 10.0, by: HurtBy::Shot, from: Vec2::X }
    }

    fn crit(damage: f32) -> SimEvent {
        SimEvent::Hit {
            pos: Vec2::ZERO,
            damage,
            crit: true,
            kind: HitKind::Normal,
            element: None,
            impact_pos: Vec2::ZERO,
            incoming_dir: Vec2::ZERO,
            weapon: None,
            source: lantern_sim::combat::Source::Ult,
            target: lantern_sim::enemies::EnemyHandle::from_raw(0),
        }
    }

    #[test]
    fn hurt_kicks_away_from_the_source_and_overlap_has_no_direction() {
        let hero = Vec2::new(60.0, -90.0);
        for offset in [Vec2::X, Vec2::Y, Vec2::NEG_X, Vec2::NEG_Y, Vec2::ONE, Vec2::ZERO] {
            let event = SimEvent::PlayerHurt { amount: 10.0, by: HurtBy::Rain, from: hero + offset };
            let impulse = camera_impulse(&[event], Vec2::X, hero);
            assert_eq!(impulse.jolt, 0.0);
            assert!(impulse.kick.distance(-to_screen(offset).normalize_or_zero() * 0.6) < 1e-5);
            assert_eq!(impulse.priority, Priority::Hurt);
            assert_eq!(impulse.trauma, 0.32);
            assert_eq!(impulse.stop, 0.045);
        }
    }

    /// 走实际的事件筛选、镜头申请和闪屏绘制链，不需要窗口或渲染插件。
    fn feedback_app(lite: bool) -> (App, Entity) {
        let content = lantern_content::Content::load(
            &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"),
        )
        .unwrap();
        let mut app = App::new();
        app.insert_resource(GameContent(std::sync::Arc::new(content)))
            .insert_resource(Feel { lite, ..default() })
            .init_resource::<Time>()
            .init_resource::<Time<Real>>()
            .init_resource::<Time<Fixed>>()
            .init_resource::<Time<Virtual>>()
            .init_resource::<SimOutbox>()
            .init_resource::<Feedback>()
            .init_resource::<Rig>()
            .init_resource::<FxState>()
            .add_systems(
                Update,
                (prepare_feedback, advance_rig_time, camera_events, read_fx_events, apply_flash).chain(),
            );
        app.world_mut().spawn((Player::default(), Pos::default(), PrevPos::default()));
        app.world_mut().spawn((
            MainCamera,
            Transform::default(),
            Projection::Orthographic(OrthographicProjection::default_2d()),
        ));
        let flash = app.world_mut().spawn((ScreenFlash, Sprite::default(), Transform::default())).id();
        (app, flash)
    }

    fn assert_hurt_feedback(app: &App, flash: Entity, stop: f32) {
        let rig = app.world().resource::<Rig>();
        assert_eq!(rig.trauma, 0.32);
        assert!((rig.kick_v.length() - 0.6 * 60.0).abs() < 1e-5);
        assert_eq!(rig.stop, stop);
        assert_eq!(rig.time_scale(), 0.0);
        assert_eq!(app.world().get::<Sprite>(flash).unwrap().color, hex("ff3b30").with_alpha(0.18));
        assert_eq!(app.world().resource::<Feedback>().visibility(Priority::Hurt), 1.0);
    }

    #[test]
    fn hurt_keeps_every_channel_against_same_frame_attacks_in_either_order() {
        for lite in [false, true] {
            for attack in [
                crit(50.0),
                crit(1000.0),
                SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult },
                SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true },
            ] {
                for events in [[attack, hurt()], [hurt(), attack]] {
                    let (mut app, flash) = feedback_app(lite);
                    app.world_mut().resource_mut::<SimOutbox>().0 = events.to_vec();
                    app.update();
                    let stop = camera_impulse(&[attack], Vec2::X, Vec2::ZERO).stop.max(0.045);
                    assert_hurt_feedback(&app, flash, stop);
                }
            }
        }
    }

    #[test]
    fn hurt_bypasses_active_highlights_and_attack_cooldowns() {
        for attack in [
            crit(1000.0),
            SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult },
            SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true },
        ] {
            let (mut app, flash) = feedback_app(false);
            app.world_mut().resource_mut::<SimOutbox>().0 = vec![attack];
            app.update();
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_secs_f32(0.12));
            app.world_mut().resource_mut::<SimOutbox>().0 = vec![hurt()];
            app.update();
            assert_hurt_feedback(&app, flash, 0.045);

            // 受伤仍在呈现时，下一帧的大招也不能改写冲击或红闪。
            let kick = app.world().resource::<Rig>().kick_v;
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::ZERO);
            app.world_mut().resource_mut::<SimOutbox>().0 =
                vec![SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult }];
            app.update();
            assert_hurt_feedback(&app, flash, 0.045);
            assert_eq!(app.world().resource::<Rig>().kick_v, kick);

            // 保护期随现有镜头效果结束，之后正常接受攻击冲击。
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(100));
            for _ in 0..3 {
                app.world_mut().run_system_once(update_rig).unwrap();
            }
            assert_eq!(app.world().resource::<Rig>().protected_left, 0.0);
            app.update();
            let weight = app.world().resource::<Feedback>().visibility(Priority::Ultimate);
            assert_eq!(app.world().resource::<Rig>().trauma, 0.75 * weight);
        }
    }

    /// 回光和挨打在同一帧（模拟里总是这样）：受伤的保护通道赢，但回光的慢镜和推镜留着。
    #[test]
    fn rescue_keeps_its_slow_motion_when_hurt_wins_the_frame() {
        let rescue = SimEvent::LastStand { pos: Vec2::ZERO };
        for events in [vec![hurt(), rescue], vec![rescue, hurt()]] {
            let cue = camera_impulse(&events, Vec2::X, Vec2::ZERO);
            assert_eq!(cue.priority, Priority::Hurt);
            assert_eq!((cue.slow, cue.scale), (0.9, 0.3));
            assert_eq!((cue.zoom, cue.hold), (0.1, 0.4));
        }
    }

    #[test]
    fn death_wins_over_hurt_and_attacks_without_losing_the_longest_stop() {
        let climax = SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true };
        for events in [
            vec![crit(1000.0), hurt(), SimEvent::PlayerDied, climax],
            vec![climax, SimEvent::PlayerDied, hurt(), crit(1000.0)],
        ] {
            let (mut app, flash) = feedback_app(false);
            app.world_mut().resource_mut::<SimOutbox>().0 = events;
            app.update();
            let rig = app.world().resource::<Rig>();
            assert_eq!(rig.trauma, 0.5);
            assert_eq!(rig.zoom_to, 0.08);
            assert_eq!(rig.zoom_hold, 1.2);
            assert_eq!(rig.stop, 0.12);
            assert_eq!(rig.protected_priority, Priority::Death);
            assert_eq!(app.world().get::<Sprite>(flash).unwrap().color, hex("ff3b30").with_alpha(0.18));

            app.world_mut().resource_mut::<SimOutbox>().0 = vec![hurt(), climax];
            app.update();
            let rig = app.world().resource::<Rig>();
            assert_eq!(rig.trauma, 0.5);
            assert_eq!(rig.zoom_to, 0.08);
            assert_eq!(rig.zoom_hold, 1.2);
        }
        let fatal = camera_impulse(&[hurt(), SimEvent::PlayerDied], Vec2::X, Vec2::ZERO);
        assert_eq!(fatal.priority, Priority::Death);
        assert_eq!(fatal.stop, 0.045);
    }

    /// 暴击都有一下轻顿帧，过 1000 的停 2 帧（试玩第 1 轮：小暴击原来不顿，打起来发飘）。
    #[test]
    fn crits_request_light_hitstop_and_large_crits_two_frames() {
        for (damage, stop) in [(1.0, 0.02), (999.0, 0.02), (1000.0, 0.035), (2000.0, 0.035)] {
            let mut rig = Rig::default();
            apply_impulse(
                &mut rig,
                &Feedback::default(),
                camera_impulse(&[crit(damage)], Vec2::X, Vec2::ZERO),
            );
            assert_eq!(rig.stop, stop);
            assert_eq!(rig.time_scale(), 0.0);
            assert_eq!(rig.trauma, 0.16);
        }
    }

    /// 轻顿帧 0.7 秒内只顿一次，但不挡更重的顿帧。
    #[test]
    fn light_hitstops_are_rate_limited_without_blocking_heavy_ones() {
        let mut rig = Rig::default();
        let feedback = Feedback::default();
        apply_impulse(&mut rig, &feedback, camera_impulse(&[crit(10.0)], Vec2::X, Vec2::ZERO));
        assert_eq!(rig.stop, 0.02);
        rig.advance_time(0.3);
        apply_impulse(&mut rig, &feedback, camera_impulse(&[crit(10.0)], Vec2::X, Vec2::ZERO));
        assert_eq!(rig.stop, 0.0, "0.3 秒后的小暴击不再顿");
        apply_impulse(&mut rig, &feedback, camera_impulse(&[crit(2000.0)], Vec2::X, Vec2::ZERO));
        assert_eq!(rig.stop, 0.035, "大暴击照样顿");
        rig.advance_time(0.5);
        apply_impulse(&mut rig, &feedback, camera_impulse(&[crit(10.0)], Vec2::X, Vec2::ZERO));
        assert_eq!(rig.stop, 0.02);
    }

    #[test]
    fn small_shakes_cannot_accumulate_into_a_climax() {
        let mut rig = Rig::default();
        for _ in 0..10 {
            rig.trauma(0.4);
        }
        assert_eq!(rig.trauma, 0.4);
    }

    #[test]
    fn hitstop_freezes_then_respects_gap() {
        let mut rig = Rig::default();
        rig.hitstop(0.05, Priority::Impact);
        assert_eq!(rig.time_scale(), 0.0);
        // 顿帧结束后，间隔内再来一次不生效
        rig.advance_time(0.0);
        rig.stop = 0.0;
        rig.hitstop(0.05, Priority::Impact);
        assert_eq!(rig.time_scale(), 1.0);
    }

    #[test]
    fn climax_upgrades_active_stop_and_cooldown_without_being_downgraded() {
        for active in [true, false] {
            let mut rig = Rig::default();
            rig.hitstop(0.035, Priority::Critical);
            if !active {
                rig.stop = 0.0;
            }
            rig.hitstop(0.09, Priority::Ultimate);
            assert_eq!(rig.stop, 0.09);
            rig.hitstop(0.12, Priority::Finale);
            assert_eq!(rig.stop, 0.12);
            rig.advance_time(0.0);
            rig.hitstop(0.25, Priority::Impact);
            assert_eq!(rig.stop, 0.12);
        }
    }

    #[test]
    fn same_frame_stops_take_the_longest_and_hurt_never_waits_for_cooldown() {
        for requests in [
            [(0.035, Priority::Critical), (0.12, Priority::Impact), (0.045, Priority::Hurt)],
            [(0.045, Priority::Hurt), (0.12, Priority::Impact), (0.035, Priority::Critical)],
        ] {
            let mut rig = Rig::default();
            for (secs, priority) in requests {
                rig.hitstop(secs, priority);
            }
            assert_eq!(rig.stop, 0.12);
            rig.advance_time(0.0);
            rig.advance_time(0.12);
            assert!(rig.stop_ready > 0.0);
            rig.hitstop(0.045, Priority::Hurt);
            assert_eq!(rig.stop, 0.045);
        }
        let mut rig = Rig::default();
        rig.hitstop(0.045, Priority::Hurt);
        assert_eq!(rig.stop_ready, 0.0);
        rig.advance_time(0.0);
        rig.advance_time(0.045);
        rig.hitstop(0.045, Priority::Hurt);
        assert_eq!(rig.stop, 0.045);
    }

    #[test]
    fn slow_frame_does_not_consume_a_new_stop_or_the_following_slowmo() {
        let mut rig = Rig::default();
        rig.advance_time(0.2);
        rig.hitstop(0.12, Priority::Finale);
        rig.slowmo(1.6, 0.2, Priority::Finale);
        assert_eq!(rig.stop, 0.12);
        assert_eq!(rig.time_scale(), 0.0);
        rig.advance_time(0.12);
        assert_eq!(rig.slow, 1.6);
        assert_eq!(rig.time_scale(), 0.2);
        rig.slowmo(0.9, 0.3, Priority::Ultimate);
        assert_eq!(rig.slow, 1.6);
    }

    #[test]
    fn new_stop_keeps_its_full_duration_then_uses_unclamped_real_time() {
        for dt in [1.0 / 60.0, 1.0 / 30.0, 0.2] {
            let (mut app, _) = feedback_app(false);
            app.add_systems(Update, update_rig.after(camera_events));
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_secs_f32(dt));
            app.world_mut().resource_mut::<SimOutbox>().0 = vec![crit(1000.0)];
            app.update();
            let rig = app.world().resource::<Rig>();
            assert_eq!(rig.stop, 0.035);
            assert_eq!(rig.stop_ready, STOP_GAP + 0.035);
            assert_eq!(app.world().resource::<Time<Virtual>>().relative_speed(), 0.0);

            app.world_mut().resource_mut::<SimOutbox>().0.clear();
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(10));
            app.update();
            assert!((app.world().resource::<Rig>().stop - 0.025).abs() < 1e-6);

            // 长帧用完整现实时间扣除，不能被镜头的 100ms 积分上限拖长。
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(250));
            app.update();
            let rig = app.world().resource::<Rig>();
            assert_eq!(rig.stop, 0.0);
            assert_eq!(rig.stop_ready, 0.0);
            assert_eq!(app.world().resource::<Time<Virtual>>().relative_speed(), 1.0);
        }
    }

    #[test]
    fn old_timers_advance_before_new_requests_and_cooldown_can_expire_this_frame() {
        let (mut app, _) = feedback_app(false);
        {
            let mut rig = app.world_mut().resource_mut::<Rig>();
            rig.hitstop(0.035, Priority::Critical);
            rig.slowmo(1.6, 0.2, Priority::Finale);
        }
        app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(250));
        app.world_mut().resource_mut::<SimOutbox>().0 = vec![crit(1000.0)];
        app.update();
        let rig = app.world().resource::<Rig>();
        assert_eq!(rig.stop, 0.035);
        assert_eq!(rig.stop_ready, STOP_GAP + 0.035);
        assert!((rig.slow - (1.6 - (0.25 - 0.035))).abs() < 1e-6);
    }

    #[test]
    fn pause_preserves_hitstop_and_slowmo_timers() {
        let (mut app, _) = feedback_app(false);
        app.insert_resource(State::new(RunState::Paused));
        {
            let mut rig = app.world_mut().resource_mut::<Rig>();
            rig.hitstop(0.12, Priority::Finale);
            rig.slowmo(1.6, 0.2, Priority::Finale);
        }
        app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_secs(1));
        app.update();
        let rig = app.world().resource::<Rig>();
        assert_eq!(rig.stop, 0.12);
        assert_eq!(rig.slow, 1.6);
        assert_eq!(rig.stop_ready, STOP_GAP + 0.12);
    }

    #[test]
    fn crit_and_elite_kill_keep_longest_stop_in_either_order() {
        let kill = SimEvent::Kill {
            pos: Vec2::ZERO,
            kind: 0,
            rank: Rank::Elite,
            incoming_dir: Vec2::ZERO,
            target: lantern_sim::enemies::EnemyHandle::from_raw(0),
            weapon: None,
            frozen: false,
        };
        for events in [[crit(1000.0), kill], [kill, crit(1000.0)]] {
            let (mut app, _) = feedback_app(false);
            app.world_mut().resource_mut::<Time<Real>>().advance_by(std::time::Duration::from_millis(33));
            app.world_mut().resource_mut::<SimOutbox>().0 = events.to_vec();
            app.update();
            assert_eq!(app.world().resource::<Rig>().stop, 0.06);
        }
    }

    #[test]
    fn flash_shows_peak_on_event_frame_then_decays_even_at_low_fps() {
        for dt in [1.0 / 60.0, 1.0 / 30.0, 1.0 / 15.0, 0.2] {
            for (event, peak) in [
                (hurt(), 0.18),
                (SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult }, 0.24),
                (SimEvent::LastStand { pos: Vec2::ZERO }, 0.24),
                (SimEvent::Revived { pos: Vec2::ZERO }, 0.24),
            ] {
                let (mut app, flash) = feedback_app(false);
                let ult = matches!(event, SimEvent::Strike { fx: StrikeFx::Ult, .. });
                app.world_mut()
                    .resource_mut::<Time<Real>>()
                    .advance_by(std::time::Duration::from_secs_f32(dt));
                app.world_mut().resource_mut::<SimOutbox>().0 = vec![event];
                app.update();
                assert_eq!(app.world().get::<Sprite>(flash).unwrap().color.alpha(), peak);
                if ult {
                    let rig = app.world().resource::<Rig>();
                    assert_eq!(rig.stop, 0.09);
                    assert_eq!(rig.zoom_to, 0.09);
                    assert_eq!(rig.zoom_hold, 0.25);
                }
                app.world_mut().resource_mut::<SimOutbox>().0.clear();
                app.update();
                let alpha = app.world().get::<Sprite>(flash).unwrap().color.alpha();
                let decay = if ult { 0.24 / crate::fx::ULT_FLASH } else { 3.0 };
                assert!((alpha - (peak - dt * decay).max(0.0)).abs() < 1e-6);
            }
        }
    }

    #[test]
    fn frame_arbitration_ignores_event_order_and_small_event_count() {
        let small = SimEvent::Strike { pos: Vec2::ZERO, radius: 50.0, fx: StrikeFx::Seal { evolved: true } };
        let climax = SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true };
        let mut events = vec![small; 500];
        events.push(SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult });
        events.push(climax);
        let expected = camera_impulse(&[climax], Vec2::X, Vec2::ZERO);
        assert_eq!(camera_impulse(&events, Vec2::X, Vec2::ZERO), expected);
        events.reverse();
        assert_eq!(camera_impulse(&events, Vec2::X, Vec2::ZERO), expected);
        assert_eq!(
            camera_impulse(&vec![small; 500], Vec2::X, Vec2::ZERO),
            camera_impulse(&[small], Vec2::X, Vec2::ZERO)
        );
    }

    #[test]
    fn slowmo_eases_back_to_full_speed() {
        let mut rig = Rig::default();
        rig.slowmo(1.0, 0.2, Priority::Ultimate);
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
