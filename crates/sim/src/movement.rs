//! 妖物移动（移植自网页版 sim/step.ts 的 updateEnemies）。互相推开见 crowd 模块。

use bevy_ecs::prelude::*;
use bevy_math::{Vec2, ops};

use lantern_content::{ChargeDef, Movement, Rank, Stat};
use lantern_core::Stream;
use lantern_core::step::DT;

use crate::charms::Survival;
use crate::combat::{ActionQueue, Hard, HurtCtx, SLOW_CAP, apply_hard, hurt_player};
use crate::enemies::{CHARGE_DASH, CHARGE_IDLE, CHARGE_RECOVER, CHARGE_WINDUP, Enemies, TAG_REVEALED};
use crate::reveal::Reveal;
use crate::run::{Director, RunPlan, SimView};
use crate::spatial::Grid;
use crate::stats::{Effects, Stats};
use crate::weapons::drop::{Fissures, Wall};
use crate::{GameContent, Health, HurtBy, Player, Pos, SimEvent, SimOutbox, SimRng, Tick};

/// 以玩家为中心重建空间网格（妖物移动、互推之后，docs/DESIGN.md 第 6.3 节）。
pub(crate) fn build_grid(
    view: Res<SimView>,
    player: Single<&Pos, With<Player>>,
    en: Res<Enemies>,
    mut grid: ResMut<Grid>,
) {
    let r = view.radius * 1.8;
    grid.build(&en, player.0.x, player.0.y, r, r);
}

/// 地形移速倍率：地图竹丛和竹印的竹墙不连乘，取更慢的一个。
/// 竹墙挡普通妖物（降到墙的倍率，是墙不是减速，不受减速上限）；精英按一般减速算，最多减 70%；
/// 夜主和奇遇小动物不受竹墙影响。
fn terrain_speed(bamboo: &crate::bamboo::Bamboo, walls: &[Wall], rank: Rank, at: Vec2) -> f32 {
    let map = bamboo.speed_at(at);
    if walls.is_empty() {
        return map;
    }
    let wall = Fissures::wall_speed(walls, at);
    match rank {
        _ if wall >= 1.0 => map,
        Rank::Normal => map.min(wall),
        Rank::Elite => map.min(wall).max(1.0 - SLOW_CAP),
        Rank::Boss | Rank::Critter => map,
    }
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
    boss: Res<crate::boss::BossState>,
    mut rng: ResMut<SimRng>,
    mut en: ResMut<Enemies>,
    mut queue: ResMut<ActionQueue>,
    mut outbox: ResMut<SimOutbox>,
    mut survival: ResMut<Survival>,
    terrain: (Res<crate::bamboo::Bamboo>, Res<Fissures>, Local<Vec<Wall>>),
    player: Single<(&Pos, &mut Player, &mut Health)>,
) {
    let content = &content.0;
    let (bamboo, ground, mut walls) = terrain;
    // 竹墙每步收集一次，没有墙时不用逐只查
    ground.collect_walls(&mut walls);
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
        en.grace[i] = (en.grace[i] - DT).max(0.0);
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
            en.charge_t[i] = charge_every(ch, en.wob[i]);
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
            // 竹丛里减速，冲锋不减
            if charge_step.is_none() {
                sp *= terrain_speed(&bamboo, &walls, def.rank, Vec2::new(x, y));
            }
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
                    Movement::Circle | Movement::Keep => {
                        let step =
                            band_step(def.movement, def.band.unwrap_or((0.0, 0.0)), (dx, dy), d, en.wob[i]);
                        x += step.x * sp * DT;
                        y += step.y * sp * DT;
                    }
                }
            }
        }

        // 离得太远的普通妖物绕到玩家前方；上一步位置一起改，画面插值不会拖出残影
        if def.rank == Rank::Normal && def.movement != Movement::Flee && d > relocate_dist {
            let a = face_angle + relocate_rng.range_f32(-spread, spread);
            let (s, c) = ops::sin_cos(a);
            let r = view.radius + content.run.spawn.ring_extra;
            x = px + c * r;
            y = py + s * r;
            en.px[i] = x;
            en.py[i] = y;
        }
        // 狐火蓄力时钉住施法位置，尾尖聚火与地面弹道始终来自同一个原点。
        if def.boss.is_some()
            && let Some(v) = &boss.volley
            && director.boss == Some(en.handle(i))
        {
            x = v.origin.x;
            y = v.origin.y;
        }
        en.x[i] = x;
        en.y[i] = y;
        // 伪装（讨封狐）：照见圈外锁定不到；一进照见圈就现形、换成现形的速度，之后一直现形
        if let Some(dg) = &def.disguise
            && en.tags[i] & TAG_REVEALED == 0
        {
            if reveal.covers(Vec2::new(x, y)) {
                en.tags[i] |= TAG_REVEALED;
                if def.speed > 0.0 {
                    en.speed[i] *= dg.speed / def.speed;
                }
                en.cloaked[i] = false;
                ctx.outbox.0.push(SimEvent::Unmasked { pos: Vec2::new(x, y), kind: en.kind[i] });
            } else {
                en.cloaked[i] = true;
            }
        }
        if en.affix[i] & cloak_bit != 0 {
            en.cloaked[i] = !reveal.covers(Vec2::new(x, y));
        }

        let kind = en.kind[i];
        // 接触按画出来的身体算；冲锋时整个身子扑出去，按碰撞半径（docs/PLAYTEST.md）
        let (contact, by, reach) = match &def.charge {
            Some(ch) if en.charge[i] == CHARGE_DASH => {
                (en.damage[i] * ch.damage_mult, HurtBy::Charge { kind }, en.r[i])
            }
            _ => (en.damage[i], HurtBy::Contact { kind }, en.r[i] * def.contact_ratio()),
        };
        // 冻住、击晕的不伤人（定身照旧还手）；刚刷出来的也先不伤人
        let harmless = en.frozen[i] > 0.0 || en.stun[i] > 0.0 || en.grace[i] > 0.0;
        if !harmless
            && d < reach + pr
            && contact > 0.0
            && hurt_player(&mut player, &mut health, pos.0, contact, (by, Vec2::new(x, y)), &mut ctx)
            && thorn > 0.0
            && ctx.rng.chance(thorn)
        {
            apply_hard(en, i, def.rank, Hard::Freeze { blast: false }, thorn_time);
        }
    }
}

/// 冲锋的冷却：every ± jitter，按每只妖物的随机相位错开（狐火 2–4 秒扑一次）。
pub(crate) fn charge_every(ch: &ChargeDef, wob: f32) -> f32 {
    ch.every + ch.jitter * ops::sin(wob)
}

/// 绕圈、守距的一步方向（长度不超过 1，乘移速就是这一步的速度）。
/// 带外：朝带里走，顺带一点横移；带里：绕圈全速横移，守距慢慢横移，并轻轻往带中间修正。
/// 横移的方向（顺时针或逆时针）按每只妖物的随机相位定。
fn band_step(movement: Movement, (near, far): (f32, f32), (dx, dy): (f32, f32), d: f32, wob: f32) -> Vec2 {
    let to = Vec2::new(dx / d, dy / d);
    let side = if wob < std::f32::consts::PI { 1.0 } else { -1.0 };
    let tangent = Vec2::new(-to.y, to.x) * side;
    let (radial, strafe) = if d > far {
        (1.0, 0.25)
    } else if d < near {
        (-1.0, 0.25)
    } else {
        let mid = 0.5 * (near + far);
        let pull = ((d - mid) / (far - near).max(1.0)).clamp(-0.5, 0.5);
        (pull, if movement == Movement::Circle { 1.0 } else { 0.35 })
    };
    let v = to * radial + tangent * strafe;
    if v.length_squared() > 1.0 { v.normalize() } else { v }
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
    en.charge_speed[i] = speed;
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
                en.charge_t[i] = charge_every(ch, en.wob[i]);
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bamboo::Bamboo;

    #[test]
    fn walls_block_normals_cap_elites_and_ignore_bosses() {
        let open = Bamboo::new(None);
        let walls = [Wall { pos: Vec2::ZERO, r2: 100.0, speed: 0.12 }];
        assert_eq!(terrain_speed(&open, &walls, Rank::Normal, Vec2::ZERO), 0.12, "普通妖物撞墙");
        assert_eq!(terrain_speed(&open, &walls, Rank::Elite, Vec2::ZERO), 1.0 - SLOW_CAP, "精英最多减 70%");
        assert_eq!(terrain_speed(&open, &walls, Rank::Boss, Vec2::ZERO), 1.0, "夜主不受竹墙影响");
        assert_eq!(terrain_speed(&open, &walls, Rank::Normal, Vec2::splat(50.0)), 1.0, "墙外照常");
        assert_eq!(terrain_speed(&open, &[], Rank::Normal, Vec2::ZERO), 1.0);
    }
}
