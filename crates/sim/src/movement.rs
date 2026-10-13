//! 妖物移动（移植自网页版 sim/step.ts 的 updateEnemies）。互相推开见 crowd 模块。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{ChargeDef, Movement, Rank, Stat};
use lantern_core::Stream;
use lantern_core::step::DT;

use crate::charms::Survival;
use crate::combat::{ActionQueue, Hard, HurtCtx, apply_hard, hurt_player};
use crate::enemies::{CHARGE_DASH, CHARGE_IDLE, CHARGE_RECOVER, CHARGE_WINDUP, Enemies};
use crate::reveal::Reveal;
use crate::run::{Director, RunPlan, SimView};
use crate::spatial::Grid;
use crate::stats::{Effects, Stats};
use crate::{GameContent, Health, HurtBy, Player, Pos, SimOutbox, SimRng, Tick};

/// 以玩家为中心重建空间网格。
pub(crate) fn build_grid(
    view: Res<SimView>,
    player: Single<&Pos, With<Player>>,
    en: Res<Enemies>,
    mut grid: ResMut<Grid>,
) {
    let r = view.radius * 1.8;
    grid.build(&en, player.0.x, player.0.y, r, r);
}

/// 追击（或逃跑）、击退衰减、离得太远的普通妖物绕到玩家前方、接触伤害。
pub(crate) fn update_enemies(
    content: Res<GameContent>,
    plan: Res<RunPlan>,
    view: Res<SimView>,
    tick: Res<Tick>,
    stats: Res<Stats>,
    effects: Res<Effects>,
    reveal: Res<Reveal>,
    director: Res<Director>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut survival: ResMut<Survival>,
    player: Single<(&Pos, &mut Player, &mut Health)>,
) {
    let content = &content.0;
    let (pos, mut player, mut health) = player.into_inner();
    // 照夜珠：照见圈外的妖物更快；霜瓷灯：受击时冻住攻击者
    let dark_speed = stats.get(Stat::DarkSpeed);
    let thorn = stats.get(Stat::ThornFreeze);
    let thorn_time = content.player.charms.thorn_freeze * stats.get(Stat::FreezeTime);
    let (px, py) = (pos.0.x, pos.0.y);
    // 夜深（无尽夜 10 分钟以后）：妖物更快（冲锋也是），越来越不吃冻住、击晕、定身、减速和击退
    let deep = crate::spawn::depth(content, director.endless.is_some(), tick.secs() / 60.0);
    let dd = &content.run.endless.depth;
    let deep_speed = 1.0 + dd.speed * deep;
    let resist = (dd.control * deep).min(dd.control_max);
    let held_tick = DT * (1.0 + 4.0 * resist);
    let pr = content.player.radius;
    let t = tick.secs();
    let decay = ops::exp(-8.0 * DT);
    let relocate_dist = view.radius * content.run.spawn.relocate;
    let spread = content.run.spawn.relocate_spread;
    let face_angle = ops::atan2(player.facing.y, player.facing.x);
    let en = &mut *en;
    let release2 = director.rush_release * director.rush_release;
    let zone_slow = content.run.lanterns.zone_slow;
    // “隐”的词缀位
    let cloak_bit = content
        .affixes
        .iter()
        .position(|a| matches!(a.kind, lantern_content::AffixKind::Cloak))
        .map_or(0u16, |k| 1 << k);
    let (relocate_rng, combat_rng) = rng.0.pair(Stream::Spawn, Stream::Combat);
    let mut ctx = HurtCtx {
        content,
        stats: &stats,
        effects: &effects,
        queue: &mut queue,
        rng: combat_rng,
        god: plan.god,
        outbox: &mut outbox,
        survival: &mut survival,
    };

    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        en.flash[i] = (en.flash[i] - DT).max(0.0);
        // 印记、反应冷却、熔金、控制递减的计时；淤泥每步由区域重新标记
        en.mark_t[i] -= DT;
        en.react_cd[i] -= DT;
        en.melt_t[i] -= DT;
        en.hard_t[i] -= DT;
        en.soft_t[i] -= DT;
        en.mud[i] = 0.0;
        let def = &content.enemies[en.kind[i] as usize];

        let (mut x, mut y) = (en.x[i], en.y[i]);
        let (dx, dy) = (px - x, py - y);
        let d = (dx * dx + dy * dy).sqrt().max(1e-3);

        x += en.kx[i] * DT * (1.0 - resist);
        y += en.ky[i] * DT * (1.0 - resist);
        en.kx[i] *= decay;
        en.ky[i] *= decay;

        // 被冻住、击晕、定身、晕头时，蓄力和冲锋都被打断，重新冷却
        let held = en.frozen[i] > 0.0 || en.stun[i] > 0.0 || en.root[i] > 0.0 || en.confuse[i] > 0.0;
        if held
            && let Some(ch) = &def.charge
            && matches!(en.charge[i], CHARGE_WINDUP | CHARGE_DASH)
        {
            en.charge[i] = CHARGE_IDLE;
            en.charge_t[i] = ch.every;
        }

        if en.frozen[i] > 0.0 {
            en.frozen[i] -= held_tick;
            if en.frozen[i] <= 0.0 {
                en.blast_frozen[i] = false;
            }
        } else if en.stun[i] > 0.0 {
            en.stun[i] -= held_tick;
        } else if en.root[i] > 0.0 {
            // 定身：不能移动，但仍会还手
            en.root[i] -= held_tick;
        } else {
            let mut sp = en.speed[i] * deep_speed;
            if en.slow_t[i] > 0.0 {
                en.slow_t[i] -= DT;
                sp *= 1.0 - en.slow_amount[i] * (1.0 - resist);
                if en.slow_t[i] <= 0.0 {
                    en.slow_amount[i] = 0.0;
                }
            }
            // 合围：加速合拢，进入一定距离以内恢复原速
            if en.rush[i] > 0.0 {
                if dx * dx + dy * dy < release2 {
                    en.rush[i] = 0.0;
                } else {
                    sp *= en.rush[i];
                }
            }
            // 点亮的石灯笼光区里减速
            if !reveal.zones.is_empty()
                && reveal.zones.iter().any(|&(c, r)| (x - c.x) * (x - c.x) + (y - c.y) * (y - c.y) <= r * r)
            {
                sp *= 1.0 - zone_slow;
            }
            if dark_speed > 0.0 && !reveal.covers(Vec2::new(x, y)) {
                sp *= 1.0 + dark_speed;
            }
            // 冲锋：速度不吃“疾”“狂”和难度的移速加成，只吃减速、光区这类倍率
            let charge_step = match &def.charge {
                Some(ch) if en.confuse[i] <= 0.0 => {
                    let ratio = if en.speed[i] > 0.0 { sp / en.speed[i] } else { 1.0 };
                    charge(en, i, ch, (dx / d, dy / d), d, ch.speed * ratio)
                }
                _ => None,
            };
            if let Some(step) = charge_step {
                x += step.x * DT;
                y += step.y * DT;
            } else if en.confuse[i] > 0.0 {
                // 晕头：朝随机方向乱走
                en.confuse[i] -= DT;
                let (s, c) = ops::sin_cos(en.confuse_dir[i]);
                x += c * sp * DT;
                y += s * sp * DT;
            } else {
                match def.movement {
                    Movement::Chase => {
                        x += dx / d * sp * DT;
                        y += dy / d * sp * DT;
                    }
                    Movement::Flee => {
                        // 背着玩家逃，路线左右摇摆，略慢于玩家，追得上
                        let (s, c) = ops::sin_cos(ops::sin(t * 3.0 + en.wob[i]) * 0.6);
                        let (ax, ay) = (-dx / d, -dy / d);
                        x += (ax * c - ay * s) * sp * DT;
                        y += (ax * s + ay * c) * sp * DT;
                    }
                }
            }
        }

        // 离得太远的普通妖物绕到玩家前方；上一步位置一起改，画面插值不会拖出残影
        if def.rank == Rank::Normal && def.movement == Movement::Chase && d > relocate_dist {
            let a = face_angle + relocate_rng.range_f32(-spread, spread);
            let (s, c) = ops::sin_cos(a);
            let r = view.radius + content.run.spawn.ring_extra;
            x = px + c * r;
            y = py + s * r;
            en.px[i] = x;
            en.py[i] = y;
        }
        en.x[i] = x;
        en.y[i] = y;
        if en.affix[i] & cloak_bit != 0 {
            en.cloaked[i] = !reveal.covers(Vec2::new(x, y));
        }

        let kind = en.kind[i];
        let (contact, by) = match &def.charge {
            Some(ch) if en.charge[i] == CHARGE_DASH => {
                (en.damage[i] * ch.damage_mult, HurtBy::Charge { kind })
            }
            _ => (en.damage[i], HurtBy::Contact { kind }),
        };
        if d < en.r[i] + pr
            && contact > 0.0
            && hurt_player(&mut player, &mut health, pos.0, contact, by, &mut ctx)
            && thorn > 0.0
            && ctx.rng.chance(thorn)
        {
            apply_hard(en, i, def.rank, Hard::Freeze { blast: false }, thorn_time);
        }
    }
}

/// 冲锋走一步（docs/BALANCE.md 第 12.6 节）。返回这一步的速度；`None` 表示照常追击。
/// to_player 是指向主角的单位向量，d 是到主角的距离，speed 是这一步的冲锋速度。
fn charge(
    en: &mut Enemies,
    i: usize,
    ch: &ChargeDef,
    to_player: (f32, f32),
    d: f32,
    speed: f32,
) -> Option<Vec2> {
    en.charge_t[i] -= DT;
    let done = en.charge_t[i] <= 0.0;
    match en.charge[i] {
        CHARGE_WINDUP => {
            // 蓄力：原地转向跟着主角，出手前 lock 秒锁定方向；时间到就冲出
            if en.charge_t[i] > ch.lock {
                en.charge_dx[i] = to_player.0;
                en.charge_dy[i] = to_player.1;
            }
            if done {
                en.charge[i] = CHARGE_DASH;
                en.charge_t[i] = ch.duration;
            }
            Some(Vec2::ZERO)
        }
        CHARGE_DASH => {
            if done {
                en.charge[i] = CHARGE_RECOVER;
                en.charge_t[i] = ch.recover;
            }
            Some(Vec2::new(en.charge_dx[i], en.charge_dy[i]) * speed)
        }
        CHARGE_RECOVER => {
            if done {
                en.charge[i] = CHARGE_IDLE;
                en.charge_t[i] = ch.every;
            }
            Some(Vec2::ZERO)
        }
        _ => {
            // 冷却：照常追击；冷却好了、主角又在范围里就开始蓄力
            if done && d <= ch.range {
                en.charge[i] = CHARGE_WINDUP;
                en.charge_t[i] = ch.windup;
                en.charge_dx[i] = to_player.0;
                en.charge_dy[i] = to_player.1;
                return Some(Vec2::ZERO);
            }
            en.charge_t[i] = en.charge_t[i].max(0.0);
            None
        }
    }
}
