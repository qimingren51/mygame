//! 高光闪避包络。各级独立计时后取最深的衰减，弱事件不会延长强事件的静默。

use lantern_sim::SimEvent;

#[derive(Clone, Copy, Debug)]
pub(crate) enum Focus {
    Impact,
    Reveal,
    BossDeath,
}

impl Focus {
    fn envelope(self) -> (f64, f64, [f32; 3]) {
        // 保持、释放；普通战斗、音乐、环境的衰减。预警、高光和界面不闪避自身。
        match self {
            Self::Impact => (0.18, 0.55, [-10.0, -2.5, -4.0]),
            Self::Reveal => (0.65, 1.0, [-16.0, -5.0, -8.0]),
            Self::BossDeath => (0.55, 1.1, [-60.0, -60.0, -60.0]),
        }
    }

    pub fn for_event(event: &SimEvent) -> Option<Self> {
        match event {
            SimEvent::BossDefeated { .. } => Some(Self::BossDeath),
            SimEvent::Ult
            | SimEvent::Evolve { .. }
            | SimEvent::BossArrived { .. }
            | SimEvent::BossPhase { .. }
            | SimEvent::BossEnraged
            | SimEvent::RunOver { .. } => Some(Self::Reveal),
            SimEvent::Resonance { .. }
            | SimEvent::LastStand { .. }
            | SimEvent::Revived { .. }
            | SimEvent::ChestOpened { .. }
            | SimEvent::EncircleWarn { .. }
            | SimEvent::SweepWarn { .. }
            | SimEvent::RainWarn { .. } => Some(Self::Impact),
            _ => None,
        }
    }
}

#[derive(Default)]
pub(crate) struct Ducking {
    started: [Option<f64>; 3],
}

impl Ducking {
    pub fn trigger(&mut self, focus: Focus, now: f64) {
        self.started[focus as usize] = Some(now);
    }

    pub fn gains(&mut self, now: f64) -> [f32; 3] {
        let mut result = [0.0_f32; 3];
        for (i, focus) in [Focus::Impact, Focus::Reveal, Focus::BossDeath].into_iter().enumerate() {
            let Some(start) = self.started[i] else { continue };
            let (hold, release, gains) = focus.envelope();
            let t = ((now - start - hold) / release).clamp(0.0, 1.0) as f32;
            if t >= 1.0 {
                self.started[i] = None;
            }
            let envelope = 1.0 - t * t * (3.0 - 2.0 * t);
            for (out, gain) in result.iter_mut().zip(gains) {
                *out = out.min(gain * envelope);
            }
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strongest_wins_regardless_of_event_order_and_releases() {
        let mut a = Ducking::default();
        let mut b = Ducking::default();
        for f in [Focus::Impact, Focus::BossDeath, Focus::Reveal] {
            a.trigger(f, 10.0);
        }
        for f in [Focus::Reveal, Focus::BossDeath, Focus::Impact] {
            b.trigger(f, 10.0);
        }
        assert_eq!(a.gains(10.0), [-60.0; 3]);
        for t in [10.2, 10.55, 10.9, 11.5, 12.0] {
            assert_eq!(a.gains(t), b.gains(t));
        }
        assert_eq!(a.gains(12.0), [0.0; 3]);
    }

    #[test]
    fn weaker_event_cannot_extend_death_silence() {
        let mut d = Ducking::default();
        d.trigger(Focus::BossDeath, 0.0);
        d.trigger(Focus::Impact, 0.5);
        assert!(d.gains(0.8)[0] > -60.0);
        assert_eq!(d.gains(1.7), [0.0; 3]);
        d.trigger(Focus::Reveal, 2.0);
        d.trigger(Focus::Reveal, 2.5);
        assert_eq!(d.gains(2.8)[0], -16.0);
        assert_eq!(d.gains(10.0), [0.0; 3]);
    }
}
