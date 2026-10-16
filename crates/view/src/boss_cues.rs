//! 九尾出手的短暂余迹：只消费真实出手事件，不把取消的预警当作命中。
//! 蓄力几何由模拟提供；余迹跟随模拟步数，暂停、顿帧与回放跳转不会补播旧招。

use bevy::prelude::*;
use lantern_content::BossDef;
use lantern_core::step::DT;
use lantern_sim::boss::{BossState, DangerArea};
use lantern_sim::{Director, Enemies, GameContent, SimEvent, SimOutbox, Tick};

const MAX_RELEASES: usize = 12;
/// 一次普通渲染帧不应跨过整秒；更大的步数差视为回放跳转，不留下旧余迹。
const SEEK_TICKS: u64 = 60;

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum ReleaseShape {
    Sweep(DangerArea),
    Rain(DangerArea),
    Volley { origin: Vec2, illusion: bool },
}

impl ReleaseShape {
    fn life(self) -> f32 {
        match self {
            Self::Sweep(_) => 0.20,
            Self::Rain(_) => 0.24,
            Self::Volley { .. } => 0.18,
        }
    }

    fn priority(self) -> u8 {
        match self {
            Self::Sweep(_) => 2,
            Self::Rain(_) => 1,
            Self::Volley { .. } => 0,
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) struct Release {
    pub shape: ReleaseShape,
    age: f32,
}

impl Release {
    pub fn progress(&self) -> f32 {
        (self.age / self.shape.life()).clamp(0.0, 1.0)
    }
}

/// 某一帧没见到预警时，从当前这只夜主的内容还原几何，不猜通用圆或固定扇角。
#[derive(Clone, Copy, Default)]
struct Pattern {
    sweep: Option<(f32, f32)>,
    rain: Option<f32>,
}

impl Pattern {
    fn from_def(def: &BossDef, reach: f32) -> Self {
        Self {
            sweep: def.sweep.map(|s| (s.angle, s.radius + reach)),
            rain: def.rain.map(|r| r.radius + reach),
        }
    }
}

#[derive(Resource, Default)]
pub(crate) struct BossCues {
    releases: Vec<Release>,
    sweeps: Vec<DangerArea>,
    drops: Vec<DangerArea>,
    tick: Option<u64>,
}

impl BossCues {
    pub fn releases(&self) -> impl Iterator<Item = &Release> {
        self.releases.iter()
    }

    fn remember(&mut self, boss: &BossState, reach: f32) {
        self.sweeps.clear();
        self.sweeps.extend(boss.sweeps.iter().map(|s| s.danger(reach)));
        self.drops.clear();
        self.drops.extend(boss.drops.iter().map(|r| r.danger(reach)));
    }

    fn push(&mut self, shape: ReleaseShape) {
        if self.releases.len() == MAX_RELEASES {
            let (oldest, old) = self
                .releases
                .iter()
                .enumerate()
                .min_by_key(|(_, release)| release.shape.priority())
                .expect("余迹池已满");
            if old.shape.priority() > shape.priority() {
                return;
            }
            self.releases.remove(oldest);
        }
        self.releases.push(Release { shape, age: 0.0 });
    }

    fn step(&mut self, tick: u64, boss: &BossState, events: &[SimEvent], pattern: Pattern, reach: f32) {
        let previous = self.tick.replace(tick);
        let jumped = previous.is_some_and(|old| tick < old || tick - old > SEEK_TICKS);
        let ended =
            events.iter().any(|event| matches!(event, SimEvent::BossDefeated { .. } | SimEvent::PlayerDied));
        if jumped || ended {
            self.releases.clear();
            self.remember(boss, reach);
            return;
        }
        // 同一个模拟步可能渲好几帧；暂停时既不前进，也不重复消费尚在队列里的出手。
        if previous == Some(tick) {
            return;
        }
        let dt = previous.map_or(0.0, |old| (tick - old) as f32 * DT);
        self.releases.retain_mut(|release| {
            release.age += dt;
            release.age < release.shape.life()
        });
        for event in events {
            let shape = match *event {
                SimEvent::SweepStrike { pos, dir } => {
                    let area = self
                        .sweeps
                        .iter()
                        .copied()
                        .find(|area| {
                            matches!(area, DangerArea::Sector { origin, dir: angle, .. }
                                if *origin == pos && *angle == dir)
                        })
                        .or_else(|| {
                            pattern.sweep.map(|(angle, radius)| DangerArea::Sector {
                                origin: pos,
                                dir,
                                angle,
                                radius,
                            })
                        });
                    area.map(ReleaseShape::Sweep)
                }
                SimEvent::RainStrike { pos } => {
                    let area = self
                        .drops
                        .iter()
                        .copied()
                        .find(|area| matches!(area, DangerArea::Circle { center, .. } if *center == pos))
                        .or_else(|| pattern.rain.map(|radius| DangerArea::Circle { center: pos, radius }));
                    area.map(ReleaseShape::Rain)
                }
                SimEvent::BossVolley { pos, illusion } => {
                    Some(ReleaseShape::Volley { origin: pos, illusion })
                }
                _ => None,
            };
            if let Some(shape) = shape {
                // 新出手不消耗上一帧的时间，短促接触边缘至少呈现一帧。
                self.push(shape);
            }
        }
        self.remember(boss, reach);
    }
}

pub(crate) fn reset(mut cues: ResMut<BossCues>) {
    *cues = BossCues::default();
}

pub(crate) fn update(
    tick: Option<Res<Tick>>,
    boss: Option<Res<BossState>>,
    director: Option<Res<Director>>,
    enemies: Option<Res<Enemies>>,
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    mut cues: ResMut<BossCues>,
) {
    let (Some(tick), Some(boss)) = (tick, boss) else {
        *cues = BossCues::default();
        return;
    };
    let reach = content.0.player.radius;
    let pattern = director
        .and_then(|d| d.boss)
        .and_then(|handle| enemies.as_ref().and_then(|en| en.resolve(handle).map(|i| en.kind[i])))
        .and_then(|kind| content.0.enemies[kind as usize].boss.as_ref())
        .map_or_else(Pattern::default, |def| Pattern::from_def(def, reach));
    cues.step(tick.0, &boss, &outbox.0, pattern, reach);
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::boss::{RainDrop, Sweep};

    fn warning() -> BossState {
        BossState {
            sweeps: vec![Sweep {
                origin: Vec2::new(10.0, 20.0),
                dir: 0.7,
                angle: 1.4,
                radius: 120.0,
                damage: 10.0,
                t: 0.7,
                warn: 0.8,
            }],
            drops: vec![RainDrop {
                pos: Vec2::new(60.0, 80.0),
                radius: 40.0,
                damage: 10.0,
                t: 0.7,
                warn: 0.8,
            }],
            ..default()
        }
    }

    #[test]
    fn only_real_strikes_commit_the_cached_warning_geometry() {
        let mut cues = BossCues::default();
        let warning = warning();
        let empty = BossState::default();
        let reach = 11.0;
        cues.step(10, &warning, &[], Pattern::default(), reach);
        cues.step(11, &empty, &[], Pattern::default(), reach);
        assert!(cues.releases.is_empty(), "取消预警不能伪造一次出手");
        cues.step(12, &warning, &[], Pattern::default(), reach);
        cues.step(
            13,
            &empty,
            &[
                SimEvent::SweepStrike { pos: warning.sweeps[0].origin, dir: warning.sweeps[0].dir },
                SimEvent::RainStrike { pos: warning.drops[0].pos },
            ],
            Pattern { sweep: Some((2.0, 999.0)), rain: Some(999.0) },
            reach,
        );
        assert_eq!(cues.releases[0].shape, ReleaseShape::Sweep(warning.sweeps[0].danger(reach)));
        assert_eq!(cues.releases[1].shape, ReleaseShape::Rain(warning.drops[0].danger(reach)));
        assert!(cues.releases.iter().all(|release| release.progress() == 0.0), "出手帧不先扣寿命");
    }

    #[test]
    fn unseen_warnings_use_the_current_boss_pattern_instead_of_a_generic_circle() {
        let mut cues = BossCues::default();
        cues.step(
            100,
            &BossState::default(),
            &[SimEvent::SweepStrike { pos: Vec2::Y, dir: -0.6 }, SimEvent::RainStrike { pos: Vec2::X }],
            Pattern { sweep: Some((1.7, 231.0)), rain: Some(63.0) },
            11.0,
        );
        assert_eq!(
            cues.releases[0].shape,
            ReleaseShape::Sweep(DangerArea::Sector { origin: Vec2::Y, dir: -0.6, angle: 1.7, radius: 231.0 })
        );
        assert_eq!(
            cues.releases[1].shape,
            ReleaseShape::Rain(DangerArea::Circle { center: Vec2::X, radius: 63.0 })
        );
    }

    #[test]
    fn release_lifetime_follows_simulation_and_clears_on_seek_or_defeat() {
        let mut cues = BossCues::default();
        let boss = BossState::default();
        let event = [SimEvent::BossVolley { pos: Vec2::ZERO, illusion: false }];
        cues.step(5, &boss, &event, Pattern::default(), 11.0);
        cues.step(5, &boss, &event, Pattern::default(), 11.0);
        assert_eq!(cues.releases.len(), 1, "暂停或高帧率不重复消费同一出手");
        assert_eq!(cues.releases[0].progress(), 0.0);
        cues.step(9, &boss, &[], Pattern::default(), 11.0);
        assert!(cues.releases[0].progress() > 0.0);
        cues.step(40, &boss, &[], Pattern::default(), 11.0);
        assert!(cues.releases.is_empty());
        cues.step(41, &boss, &event, Pattern::default(), 11.0);
        cues.step(1, &boss, &event, Pattern::default(), 11.0);
        assert!(cues.releases.is_empty(), "向后跳播不能保留旧余迹");
        cues.step(2, &boss, &event, Pattern::default(), 11.0);
        cues.step(1000, &boss, &event, Pattern::default(), 11.0);
        assert!(cues.releases.is_empty(), "向前跳播也不重放跳过的出手");
        cues.step(1001, &boss, &event, Pattern::default(), 11.0);
        cues.step(
            1002,
            &boss,
            &[SimEvent::BossDefeated { pos: Vec2::ZERO, dawn: true }],
            Pattern::default(),
            11.0,
        );
        assert!(cues.releases.is_empty());
    }

    #[test]
    fn local_releases_are_bounded_and_volleys_do_not_evict_a_sweep() {
        let mut cues = BossCues::default();
        let mut events = vec![SimEvent::SweepStrike { pos: Vec2::ZERO, dir: 0.0 }];
        events
            .extend((0..20).map(|i| SimEvent::BossVolley { pos: Vec2::new(i as f32, 0.0), illusion: true }));
        cues.step(
            10,
            &BossState::default(),
            &events,
            Pattern { sweep: Some((1.7, 231.0)), rain: None },
            11.0,
        );
        assert_eq!(cues.releases.len(), MAX_RELEASES);
        assert!(matches!(cues.releases[0].shape, ReleaseShape::Sweep(_)));
    }
}
