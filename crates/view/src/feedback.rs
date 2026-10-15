//! 表现层仲裁：先给高光留位置，再限制同帧、同类、邻近的小效果。不改写模拟事件。

use bevy::prelude::*;
use lantern_content::{BlastKind, Rank};
use lantern_sim::combat::StrikeFx;
use lantern_sim::{HitKind, SimEvent, SimOutbox};

use crate::Feel;

/// 敌方出手单独归类，不改变镜头的冲击级别，也不参与玩家高光压暗。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Category {
    #[default]
    Decorative,
    Hostile,
}

impl Category {
    pub fn of(event: &SimEvent) -> Self {
        match event {
            SimEvent::SweepStrike { .. } | SimEvent::RainStrike { .. } | SimEvent::BossVolley { .. } => {
                Self::Hostile
            }
            _ => Self::Decorative,
        }
    }

    /// 两套压暗只取较小值，避免玩家效果重复变暗；敌方出手始终完整显示。
    pub fn visibility(self, feedback: &Feedback, priority: Priority, personal_gain: f32) -> f32 {
        if self == Self::Hostile || priority.protected() {
            1.0
        } else {
            feedback.visibility(priority).min(personal_gain)
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Priority {
    #[default]
    Ambient,
    Normal,
    Impact,
    Critical,
    Ultimate,
    Finale,
    /// 玩家危险反馈走保护通道，不参与攻击高光的压暗。
    Hurt,
    Death,
}

impl Priority {
    pub const ALL: [Self; 8] = [
        Self::Death,
        Self::Hurt,
        Self::Finale,
        Self::Ultimate,
        Self::Critical,
        Self::Impact,
        Self::Normal,
        Self::Ambient,
    ];

    pub fn protected(self) -> bool {
        matches!(self, Self::Hurt | Self::Death)
    }

    pub fn of(event: &SimEvent) -> Self {
        match event {
            SimEvent::PlayerDied => Self::Death,
            SimEvent::PlayerHurt { .. } => Self::Hurt,
            SimEvent::BossDefeated { .. } | SimEvent::Kill { rank: Rank::Boss, .. } => Self::Finale,
            SimEvent::Strike { fx: StrikeFx::Ult, .. }
            | SimEvent::LastStand { .. }
            | SimEvent::Revived { .. } => Self::Ultimate,
            SimEvent::Hit { crit: true, .. } => Self::Critical,
            SimEvent::Kill { rank: Rank::Elite, .. }
            | SimEvent::BossArrived { .. }
            | SimEvent::BossPhase { .. }
            | SimEvent::SweepStrike { .. }
            | SimEvent::RainStrike { .. }
            | SimEvent::Reaction { first: true, .. }
            | SimEvent::LevelUp { .. }
            | SimEvent::LanternLit { .. }
            // 夜主结界一次烧平一片竹丛，粒子多，给高一档的预算
            | SimEvent::BambooBurned { .. } => Self::Impact,
            _ => Self::Normal,
        }
    }
}

/// 只对装饰事件限流。危险预警及灯阵等持久状态仍消费完整队列。
fn family(event: &SimEvent) -> Option<(u16, Vec2, usize)> {
    if Category::of(event) == Category::Hostile {
        return None;
    }
    match *event {
        SimEvent::Hit { pos, kind: HitKind::Dot, .. } => Some((13, pos, 4)),
        SimEvent::Hit { pos, crit, .. } => Some((u16::from(crit), pos, if crit { 6 } else { 14 })),
        SimEvent::Kill { pos, rank, .. } => Some(match rank {
            Rank::Boss => (4, pos, 2),
            Rank::Elite => (3, pos, 4),
            _ => (2, pos, 12),
        }),
        SimEvent::Strike { pos, fx, .. } => {
            let id = match fx {
                StrikeFx::None => return None,
                StrikeFx::Pulse => 5,
                StrikeFx::Toll => 6,
                StrikeFx::Seal { .. } => 7,
                StrikeFx::Blast(BlastKind::Fire) => 8,
                StrikeFx::Blast(BlastKind::Ice) => 16,
                StrikeFx::Quake => 9,
                StrikeFx::Taiji => 10,
                StrikeFx::Ult => 11,
            };
            Some((id, pos, if fx == StrikeFx::Ult { 1 } else { 3 }))
        }
        SimEvent::Reaction { kind, pos, first: false, .. } => Some((32 + u16::from(kind), pos, 2)),
        SimEvent::IllusionDispelled { pos } => Some((12, pos, 3)),
        _ => None,
    }
}

fn strength(event: &SimEvent) -> f32 {
    match event {
        SimEvent::Hit { damage, .. } => *damage,
        SimEvent::Strike { radius, .. } => *radius,
        _ => 0.0,
    }
}

#[derive(Resource, Default)]
pub(crate) struct Feedback {
    /// 按重要性排列的原队列下标，各表现系统共用同一份取舍。
    pub selected: Vec<usize>,
    candidates: Vec<usize>,
    focus: Priority,
    hold: f32,
}

impl Feedback {
    fn prepare(&mut self, events: &[SimEvent], dt: f32, lite: bool) {
        self.hold = (self.hold - dt).max(0.0);
        if self.hold == 0.0 {
            self.focus = Priority::Ambient;
        }
        self.selected.clear();
        self.candidates.clear();
        for priority in Priority::ALL {
            for (index, event) in events.iter().enumerate() {
                if Priority::of(event) != priority {
                    continue;
                }
                if let Some((kind, pos, mut cap)) = family(event) {
                    if lite && priority < Priority::Ultimate {
                        cap = cap.div_ceil(2);
                    }
                    let mut count = 0;
                    let mut nearby = None;
                    let mut weakest = None;
                    for &slot in &self.candidates {
                        let other = self.selected[slot];
                        if let Some((other_kind, other_pos, _)) = family(&events[other])
                            && other_kind == kind
                        {
                            count += 1;
                            if pos.distance_squared(other_pos) < 48.0 * 48.0 {
                                nearby = Some(slot);
                            }
                            if weakest.is_none_or(|old| {
                                strength(&events[self.selected[old]]) > strength(&events[other])
                            }) {
                                weakest = Some(slot);
                            }
                        }
                    }
                    let replacement = if priority < Priority::Ultimate { nearby } else { None }
                        .or(if count >= cap { weakest } else { None });
                    if let Some(slot) = replacement {
                        if strength(event) > strength(&events[self.selected[slot]]) {
                            self.selected[slot] = index;
                        }
                        continue;
                    }
                    self.candidates.push(self.selected.len());
                }
                self.selected.push(index);
                // 只有燃灯、终幕这类高光才压暗别的；自己的暴击不该把夜主和危险的提示压下去
                if !priority.protected() && priority >= Priority::Ultimate && priority >= self.focus {
                    self.focus = priority;
                    self.hold = match priority {
                        Priority::Finale => 0.9,
                        Priority::Ultimate => 0.45,
                        _ => 0.14,
                    };
                }
            }
        }
    }

    /// 在高光期间压低已经在场的小特效；危险信息不经过这个系数。
    pub fn visibility(&self, priority: Priority) -> f32 {
        if priority.protected() || self.hold <= 0.0 || priority >= self.focus {
            1.0
        } else if priority >= Priority::Critical {
            0.65
        } else if priority == Priority::Impact {
            0.45
        } else {
            0.22
        }
    }
}

pub(crate) fn prepare_feedback(
    outbox: Res<SimOutbox>,
    real: Res<Time<Real>>,
    feel: Res<Feel>,
    mut feedback: ResMut<Feedback>,
) {
    feedback.prepare(&outbox.0, real.delta_secs(), feel.lite);
}

pub(crate) fn reset_feedback(mut feedback: ResMut<Feedback>) {
    *feedback = Feedback::default();
}

/// 满池时只替换较低级效果，优先清走最弱的；同级旧效果不被小事件驱逐。
pub(crate) fn eviction<T, K: Ord>(list: &[T], priority: K, get: impl Fn(&T) -> K) -> Option<usize> {
    list.iter()
        .enumerate()
        .filter(|(_, item)| get(item) < priority)
        .min_by_key(|(_, item)| get(item))
        .map(|(index, _)| index)
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::HitKind;

    fn hit(x: f32, crit: bool) -> SimEvent {
        SimEvent::Hit {
            pos: Vec2::new(x, 0.0),
            damage: 1200.0,
            crit,
            kind: HitKind::Normal,
            element: None,
            impact_pos: Vec2::new(x, 0.0),
            incoming_dir: Vec2::ZERO,
            weapon: None,
            source: lantern_sim::combat::Source::Ult,
            target: lantern_sim::enemies::EnemyHandle::from_raw(0),
        }
    }

    #[test]
    fn crowded_frame_keeps_highlights_and_limits_nearby_hits() {
        for lite in [false, true] {
            let mut events = vec![hit(0.0, false); 500];
            events.push(hit(0.0, true));
            events.push(SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult });
            events.push(SimEvent::Kill {
                pos: Vec2::ZERO,
                kind: 0,
                rank: Rank::Boss,
                incoming_dir: Vec2::ZERO,
                target: lantern_sim::enemies::EnemyHandle::from_raw(0),
                weapon: None,
            });
            let original = events.clone();
            let mut f = Feedback::default();
            f.prepare(&events, 0.016, lite);
            assert_eq!(f.selected.len(), 4);
            assert_eq!(f.selected[0], 502);
            assert!(f.selected.contains(&500) && f.selected.contains(&501));
            assert_eq!(events, original);
            assert!(f.visibility(Priority::Normal) < f.visibility(Priority::Finale));
            f.prepare(&[], 1.0, lite);
            assert_eq!(f.visibility(Priority::Normal), 1.0);
        }
    }

    #[test]
    fn distributed_hits_are_bounded_and_warnings_are_preserved() {
        let mut events: Vec<_> = (0..500).map(|n| hit(n as f32 * 60.0, false)).collect();
        events.push(SimEvent::SweepWarn { pos: Vec2::ZERO, dir: 0.0 });
        let mut f = Feedback::default();
        f.prepare(&events, 0.016, false);
        assert_eq!(f.selected.len(), 15);
        assert!(f.selected.contains(&500));
        f.prepare(&events, 0.016, true);
        assert_eq!(f.selected.len(), 8);
    }

    #[test]
    fn hostile_attacks_bypass_proximity_and_frame_caps_even_in_lite_mode() {
        let mut events = vec![SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult }];
        events.extend([SimEvent::RainStrike { pos: Vec2::ZERO }; 20]);
        events.extend([SimEvent::SweepStrike { pos: Vec2::ZERO, dir: 0.0 }; 5]);
        events.extend([SimEvent::BossVolley { pos: Vec2::ZERO, illusion: true }; 3]);
        for lite in [false, true] {
            let mut f = Feedback::default();
            f.prepare(&events, 0.016, lite);
            assert_eq!(f.selected.len(), events.len());
            for index in 0..events.len() {
                assert!(f.selected.contains(&index));
            }
            assert_eq!(f.focus, Priority::Ultimate);
            for event in &events[1..] {
                assert_eq!(Category::of(event), Category::Hostile);
                assert_eq!(Category::of(event).visibility(&f, Priority::of(event), 0.32), 1.0);
            }
            assert_eq!(Category::Decorative.visibility(&f, Priority::Impact, 0.32), 0.32);
            assert_eq!(Category::Decorative.visibility(&f, Priority::Normal, 0.32), 0.22);
            // 敌方出手不会延长玩家高光的压暗时间。
            f.prepare(&events[1..], 1.0, lite);
            assert_eq!(f.visibility(Priority::Normal), 1.0);
        }
    }

    #[test]
    fn stronger_crit_replaces_a_nearby_small_crit() {
        let mut weak = hit(0.0, true);
        if let SimEvent::Hit { damage, .. } = &mut weak {
            *damage = 10.0;
        }
        let strong = hit(1.0, true);
        let mut f = Feedback::default();
        f.prepare(&[weak, strong], 0.016, false);
        assert_eq!(f.selected, vec![1]);
        f.prepare(&[strong, weak], 0.016, false);
        assert_eq!(f.selected, vec![0]);
    }

    #[test]
    fn player_feedback_is_preserved_without_changing_attack_highlights() {
        let hurt = SimEvent::PlayerHurt { amount: 10.0, by: lantern_sim::HurtBy::Shot, from: Vec2::X };
        for lite in [false, true] {
            for highlight in [
                hit(0.0, true),
                SimEvent::Strike { pos: Vec2::ZERO, radius: 400.0, fx: StrikeFx::Ult },
                SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true },
            ] {
                let mut f = Feedback::default();
                f.prepare(&[highlight, hurt, SimEvent::PlayerDied], 0.016, lite);
                assert_eq!(f.selected, vec![2, 1, 0]);
                // 普通暴击不抢焦点，燃灯、终幕才抢
                let focus = Priority::of(&highlight);
                assert_eq!(f.focus, if focus >= Priority::Ultimate { focus } else { Priority::Ambient });
                f.prepare(&[hurt, SimEvent::PlayerDied], 0.016, lite);
                assert_eq!(f.selected, vec![1, 0]);
                assert_eq!(f.visibility(Priority::Normal) < 1.0, focus >= Priority::Ultimate);
                assert_eq!(f.visibility(Priority::Hurt), 1.0);
                assert_eq!(f.visibility(Priority::Death), 1.0);
                f.prepare(&[], 1.0, lite);
                assert_eq!(f.visibility(Priority::Normal), 1.0);
            }
        }
    }
}
