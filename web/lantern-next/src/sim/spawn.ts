// 刷怪（移植自旧版 spawnEnemy / ringPos / spawnElite / updateSpawns / updateBoss）。

import { TAU } from '../core/math';
import { ENEMY_SOFT_CAP, enemyDmgScale, hpScale, spawnRate } from '../data/balance';
import { ENEMY, ENEMY_ID, type EnemyType } from '../data/enemies';
import { viewRadius, type World } from './state';

/** 跑分模式每步最多补充的妖物数 */
const BENCH_REFILL_PER_STEP = 60;

export function spawnEnemy(w: World, type: EnemyType, x: number, y: number): number {
  const en = w.enemies;
  const i = en.alloc();
  if (i < 0) return -1;
  const d = ENEMY[type];
  const m = w.t / 60;
  const sc = d.boss ? 1 : hpScale(m, w.mods.enemyHp);
  en.type[i] = ENEMY_ID[type];
  en.x[i] = x;
  en.y[i] = y;
  en.px[i] = x;
  en.py[i] = y;
  en.r[i] = d.r;
  en.hp[i] = d.hp * sc;
  en.maxHp[i] = d.hp * sc;
  en.speed[i] = d.speed * w.rng.spawn.range(0.9, 1.1) * (d.toad ? 1 : w.mods.enemySpeed);
  en.dmg[i] = d.dmg * enemyDmgScale(m);
  en.wob[i] = w.rng.spawn.range(0, TAU);
  return i;
}

const tmpPos = { x: 0, y: 0 };

/** 屏幕外一圈的随机位置 */
function ringPos(w: World, extra: number): { x: number; y: number } {
  const a = w.rng.spawn.range(0, TAU);
  const R = viewRadius(w) + extra;
  tmpPos.x = w.player.x + Math.cos(a) * R;
  tmpPos.y = w.player.y + Math.sin(a) * R;
  return tmpPos;
}

function spawnElite(w: World, pool: readonly ('fox' | 'ghoul' | 'stonelord')[]): void {
  const type = w.rng.spawn.pick(pool);
  for (let i = 0; i < w.mods.elites; i++) {
    const pos = ringPos(w, 40);
    spawnEnemy(w, type, pos.x, pos.y);
  }
  w.bus.emit({ k: 'elite', type, count: w.mods.elites });
}

export function updateSpawns(w: World, dt: number): void {
  const en = w.enemies;
  const rs = w.rng.spawn;
  if (w.benchTarget !== null) {
    let missing = Math.min(w.benchTarget - en.count, BENCH_REFILL_PER_STEP);
    while (missing-- > 0) {
      const pos = ringPos(w, 40);
      spawnEnemy(w, rs.chance(0.2) ? 'wisp' : 'shade', pos.x, pos.y);
    }
    return;
  }

  const m = w.t / 60;
  let rate = spawnRate(m, w.mods.spawn);
  if (w.surgeT > 0) {
    w.surgeT -= dt;
    rate *= 2.5;
  }
  if (w.boss >= 0) rate *= 0.4;
  if (en.count > ENEMY_SOFT_CAP) rate = 0;
  w.spawnAcc += rate * dt;
  while (w.spawnAcc >= 1) {
    w.spawnAcc -= 1;
    const r = rs.next();
    let type: EnemyType = 'shade';
    if (m >= 1 && r < w.mix.wisp * (m >= 5 ? 1.5 : 1)) type = 'wisp';
    else if (m >= 2.5 && r > 1 - w.mix.golem * (m >= 5 ? 1.6 : 1)) type = 'golem';
    const pos = ringPos(w, 40);
    spawnEnemy(w, type, pos.x, pos.y);
  }

  // 每 25 秒左右从随机方向涌来一群，制造“妖潮”的方向感
  if (w.t > 40 && w.t >= w.nextPack && en.count < 300) {
    w.nextPack = w.t + rs.range(18, 32);
    const base = ringPos(w, 60);
    const bx = base.x;
    const by = base.y;
    const n = Math.round((8 + m * 3) * w.mods.spawn);
    for (let i = 0; i < n; i++) {
      const type: EnemyType = m > 4 && rs.chance(w.mix.wisp * 2) ? 'wisp' : 'shade';
      spawnEnemy(w, type, bx + rs.range(-40, 40), by + rs.range(-40, 40));
    }
  }

  // 按本局随机计划出场
  for (const s of w.plan) {
    if (s.done || w.t < s.at) continue;
    s.done = true;
    if (s.kind === 'elite') {
      spawnElite(w, s.pool);
    } else if (s.kind === 'surge') {
      w.surgeT = 30;
      spawnElite(w, s.pool);
      w.bus.emit({ k: 'surge' });
      w.bus.emit({ k: 'shake', amount: 6 });
    } else if (s.kind === 'boss') {
      const pos = ringPos(w, 40);
      const i = spawnEnemy(w, 'boss', pos.x, pos.y);
      w.boss = i >= 0 ? en.handle(i) : -1;
      w.bus.emit({ k: 'boss' });
      w.bus.emit({ k: 'shake', amount: 10 });
      w.bus.emit({ k: 'flash', color: 0xff6b5a, a: 0.2 });
    }
  }

  // 夜签「天降宝箱」
  if (w.mods.chestRain) {
    w.chestRainT -= dt;
    if (w.chestRainT <= 0) {
      w.chestRainT = 100;
      const a = rs.range(0, TAU);
      w.pickups.push({ kind: 'chest', x: w.player.x + Math.cos(a) * 120, y: w.player.y + Math.sin(a) * 90, t: 0 });
    }
  }
}

/** 夜主：每 2.6 秒放一圈弹幕，每 7 秒召唤影妖 */
export function updateBoss(w: World, i: number, dt: number): void {
  const en = w.enemies;
  const x = en.x[i] as number;
  const y = en.y[i] as number;
  en.atk[i] = (en.atk[i] as number) - dt;
  if ((en.atk[i] as number) <= 0) {
    en.atk[i] = 2.6;
    const n = 14;
    const off = w.rng.combat.range(0, TAU);
    for (let k = 0; k < n; k++) {
      const a = off + (k * TAU) / n;
      w.foes.push({ x, y, px: x, py: y, vx: Math.cos(a) * 115, vy: Math.sin(a) * 115, r: 6, dmg: 14, life: 6 });
    }
  }
  en.summon[i] = (en.summon[i] as number) - dt;
  if ((en.summon[i] as number) <= 0) {
    en.summon[i] = 7;
    for (let k = 0; k < 6; k++) {
      const a = (k * TAU) / 6;
      spawnEnemy(w, 'shade', x + Math.cos(a) * 70, y + Math.sin(a) * 70);
    }
  }
}
