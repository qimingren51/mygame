//! 远程小妖（docs/BALANCE.md 第 12.1 节）：竹魅停在远处，锁定方向预警一会儿，再射一根竹刺。
//!
//! 竹刺进敌方弹幕池（`boss::Foes`），和九尾的狐火一样移动、命中，只是记着是谁射的。
//! 冷却用妖物池的 `atk_t`，预警用 `aim_t / aim_x / aim_y / aim_dx / aim_dy`。

use bevy_ecs::prelude::*;
use bevy_math::Vec2;

use lantern_core::step::DT;

use crate::boss::{Foe, Foes};
use crate::enemies::Enemies;
use crate::{GameContent, Player, Pos, SimEvent, SimOutbox};

pub(crate) fn enemy_shots(
    content: Res<GameContent>,
    mut en: ResMut<Enemies>,
    mut foes: ResMut<Foes>,
    mut outbox: ResMut<SimOutbox>,
    player: Single<&Pos, With<Player>>,
) {
    let c = &content.0;
    let p = player.0;
    let en = &mut *en;
    for i in 0..en.hi {
        if !en.alive[i] {
            continue;
        }
        let def = &c.enemies[en.kind[i] as usize];
        let Some(sh) = &def.shot else { continue };
        let held = en.frozen[i] > 0.0 || en.stun[i] > 0.0 || en.root[i] > 0.0 || en.confuse[i] > 0.0;
        let at = Vec2::new(en.x[i], en.y[i]);
        let kind = en.kind[i];
        // 受击正在后退时不蓄力；互推移出自身半径后也放弃旧起点，避免在空处射出竹刺。
        let knocked = en.kx[i] * en.kx[i] + en.ky[i] * en.ky[i] > 1.0;
        let displaced =
            en.aim_t[i] > 0.0 && at.distance_squared(Vec2::new(en.aim_x[i], en.aim_y[i])) > en.r[i] * en.r[i];
        // 出生保护期间不蓄力也不出手；控制结束后必须重新走完整预警。
        if held || knocked || displaced || en.grace[i] > 0.0 {
            if en.aim_t[i] > 0.0 {
                // 被控住：这一刺作废，冷却一半再来
                en.aim_t[i] = 0.0;
                en.atk_t[i] = sh.every * 0.5;
            }
            continue;
        }
        if en.aim_t[i] > 0.0 {
            en.aim_t[i] -= DT;
            if en.aim_t[i] <= 0.0 {
                en.aim_t[i] = 0.0;
                en.atk_t[i] = sh.every;
                // 伤害和接触伤害一样吃曲线和更的倍率
                let scale = if def.damage > 0.0 { en.damage[i] / def.damage } else { 1.0 };
                let dir = Vec2::new(en.aim_dx[i], en.aim_dy[i]);
                let at = Vec2::new(en.aim_x[i], en.aim_y[i]);
                foes.0.push(Foe {
                    pos: at,
                    prev: at,
                    vel: dir * sh.speed,
                    radius: sh.radius,
                    damage: sh.damage * scale,
                    life: sh.life,
                    kind: Some(kind),
                });
                outbox.0.push(SimEvent::EnemyShot { enemy: en.handle(i), pos: at, kind });
            }
            continue;
        }
        en.atk_t[i] -= DT;
        if en.atk_t[i] > 0.0 {
            continue;
        }
        let to = p - at;
        let d = to.length();
        if d > sh.range || d < 1e-3 {
            // 够不着：等主角进了射程马上开始瞄
            en.atk_t[i] = 0.0;
            continue;
        }
        let dir = to / d;
        en.aim_t[i] = sh.warn;
        en.aim_x[i] = at.x;
        en.aim_y[i] = at.y;
        en.aim_dx[i] = dir.x;
        en.aim_dy[i] = dir.y;
        outbox.0.push(SimEvent::EnemyAim { pos: at, dir, kind });
    }
}
