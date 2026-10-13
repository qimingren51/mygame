//! 照见圈、易伤区与灯焰带（docs/GAMEPLAY.md 第 4.2 节，docs/BALANCE.md 第 3.1、7.3 节）。
//!
//! 照见圈是规则半径，和画面的灯光半径分开：照见圈里的妖物受到伤害 +10%（灯芯、照夜珠再加）；
//! 点亮的石灯笼是永久光区，区里的妖物也算被照见。灯芯 1 级起，照见圈最外面一圈燃起灯焰带。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_content::Stat;

use crate::combat::{HIT_DOT, HIT_NOCRIT, Hit, HitQueue, Source};
use crate::enemies::Enemies;
use crate::lanterns::Lanterns;
use crate::run::Progress;
use crate::spatial::Grid;
use crate::stats::Stats;
use crate::{GameContent, Player, Pos, Tick};

/// 灯焰带、赤地等持续区域每隔这么多步结算一次（0.5 秒）
pub const ZONE_TICK: u64 = 30;

#[derive(Resource, Clone, Debug, Default)]
pub struct Reveal {
    pub center: Vec2,
    pub radius: f32,
    /// 照见的易伤
    pub vuln: f32,
    /// 灯焰带每秒伤害（0 表示没有）与宽度
    pub band_dps: f32,
    pub band_width: f32,
    /// 点亮的石灯笼：(位置, 半径)
    pub zones: Vec<(Vec2, f32)>,
    /// 光区里的易伤（取它和照见易伤中较高的）
    pub zone_vuln: f32,
}

impl Reveal {
    /// 这一点在照见圈或光区里。
    pub fn covers(&self, p: Vec2) -> bool {
        p.distance_squared(self.center) <= self.radius * self.radius
            || self.zones.iter().any(|&(c, r)| p.distance_squared(c) <= r * r)
    }
}

/// 每步更新照见圈：跟着主角，半径随等级和属性变化。
pub(crate) fn update_reveal(
    content: Res<GameContent>,
    stats: Res<Stats>,
    progress: Res<Progress>,
    lanterns: Res<Lanterns>,
    player: Single<&Pos, With<Player>>,
    mut reveal: ResMut<Reveal>,
) {
    let r = &content.0.player.reveal;
    let lz = &content.0.run.lanterns;
    reveal.zones.clear();
    reveal.zones.extend(lanterns.0.iter().filter(|l| l.lit).map(|l| (l.pos, lz.zone_radius)));
    reveal.zone_vuln = lz.zone_vuln;
    reveal.center = player.0;
    reveal.radius = stats.get(Stat::Reveal);
    reveal.vuln = stats.get(Stat::RevealVuln);
    let rank = stats.get(Stat::FlameBand);
    reveal.band_width = r.band_width;
    reveal.band_dps = if rank >= 1.0 {
        r.band_dps.at(progress.level as f32)
            * (1.0 + r.band_per_rank * (rank - 1.0))
            * stats.get(Stat::FlameBandMult)
    } else {
        0.0
    };
}

/// 易伤区：照见（或光区）、熔金、冰冻相加，上限 cap。
pub(crate) struct Vuln<'a> {
    reveal: &'a Reveal,
    r2: f32,
    frozen: f32,
    cap: f32,
}

impl<'a> Vuln<'a> {
    pub fn new(reveal: &'a Reveal, stats: &Stats, cap: f32) -> Self {
        Vuln { reveal, r2: reveal.radius * reveal.radius, frozen: stats.get(Stat::FrozenVuln), cap }
    }

    /// 妖物 i 的易伤区倍率。
    pub fn of(&self, en: &Enemies, i: usize) -> f32 {
        let p = Vec2::new(en.x[i], en.y[i]);
        let mut v = 0.0;
        if p.distance_squared(self.reveal.center) <= self.r2 {
            v += self.reveal.vuln;
        } else if self.reveal.zones.iter().any(|&(c, r)| p.distance_squared(c) <= r * r) {
            v += self.reveal.vuln.max(self.reveal.zone_vuln);
        }
        if en.melt_t[i] > 0.0 {
            v += en.melt[i];
        }
        if en.frozen[i] > 0.0 {
            v += self.frozen;
        }
        1.0 + v.min(self.cap)
    }
}

/// 灯焰带：每 0.5 秒对照见圈最外面一圈里的妖物造成伤害（吃加成区和易伤，不暴击、不打印记）。
pub(crate) fn flame_band(
    tick: Res<Tick>,
    reveal: Res<Reveal>,
    grid: Res<Grid>,
    en: Res<Enemies>,
    mut hits: ResMut<HitQueue>,
    mut found: Local<Vec<u32>>,
) {
    if reveal.band_dps <= 0.0 || !tick.0.is_multiple_of(ZONE_TICK) {
        return;
    }
    let c = reveal.center;
    found.clear();
    grid.query_circle(&en, c.x, c.y, reveal.radius, &mut found);
    let inner = (reveal.radius - reveal.band_width).max(0.0);
    let dmg = reveal.band_dps * ZONE_TICK as f32 * lantern_core::step::DT;
    for &i in found.iter() {
        let i = i as usize;
        let d2 = Vec2::new(en.x[i], en.y[i]).distance_squared(c);
        if d2 >= inner * inner {
            hits.0.push(Hit::new(en.handle(i), dmg, Source::Band).flags(HIT_DOT | HIT_NOCRIT));
        }
    }
}
