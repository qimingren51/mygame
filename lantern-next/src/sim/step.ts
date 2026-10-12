// 模拟的一步（固定 1/60 秒）。执行顺序沿用旧版 update()：
// 玩家 → 刷怪 → 建网格 → 妖物移动 → 互相推开 → 法器 → 魂火。
// 技术验证阶段只包含：移动、闪避、刷怪、灯火、命中击杀、魂火。

import { FX, FX_CRIT } from '../core/fxqueue';
import { TAU } from '../core/math';
import {
  ENEMY_SOFT_CAP,
  PLAYER,
  enemyDmgScale,
  gemValueScale,
  hpScale,
  spawnRate,
  xpNeed,
} from '../data/balance';
import { ENEMY, ENEMY_ID, ENEMY_TYPES, type EnemyType } from '../data/enemies';
import { W } from '../data/weapons';
import { LAMP_MAX_FLAMES, type InputFrame, type World, viewRadius } from './state';

/** 跑分模式每步最多补充的妖物数 */
const BENCH_REFILL_PER_STEP = 60;

export function step(w: World, dt: number, input: InputFrame): void {
  w.tick++;
  w.t += dt;
  updatePlayer(w, dt, input);
  savePrevPositions(w);
  updateSpawns(w, dt);
  const R = viewRadius(w) * 1.8;
  w.grid.build(w.enemies, w.player.x, w.player.y, R, R);
  updateEnemies(w, dt);
  separate(w, dt);
  updateLamp(w, dt);
  updateGems(w, dt);
}

// ---------------------------------------------------------------------------
// 玩家
// ---------------------------------------------------------------------------

function updatePlayer(w: World, dt: number, input: InputFrame): void {
  const p = w.player;
  p.px = p.x;
  p.py = p.y;

  let mx = input.mx;
  let my = input.my;
  const len = Math.hypot(mx, my);
  if (len > 1) {
    mx /= len;
    my /= len;
  }
  p.moving = len > 0.001;
  if (p.moving) {
    const l = Math.hypot(mx, my);
    p.faceX = mx / l;
    p.faceY = my / l;
  }

  for (const c of w.commands) {
    if (c.k === 'dash' && p.dashCd <= 0) {
      p.dashT = PLAYER.dashTime;
      p.dashVX = p.faceX * PLAYER.dashSpeed;
      p.dashVY = p.faceY * PLAYER.dashSpeed;
      p.iframe = Math.max(p.iframe, PLAYER.dashIframe);
      p.dashCd = PLAYER.dashCd;
      w.bus.emit({ k: 'dash' });
    }
  }
  w.commands.length = 0;

  if (p.dashT > 0) {
    p.dashT -= dt;
    p.x += p.dashVX * dt;
    p.y += p.dashVY * dt;
  } else {
    p.x += mx * w.stats.speed * dt;
    p.y += my * w.stats.speed * dt;
  }
  p.moved = Math.hypot(p.x - p.px, p.y - p.py);
  p.iframe = Math.max(0, p.iframe - dt);
  p.dashCd = Math.max(0, p.dashCd - dt);
}

function damagePlayer(w: World, amount: number): void {
  const p = w.player;
  if (p.iframe > 0 || p.dashT > 0) return;
  p.iframe = PLAYER.iframe;
  if (w.god) return;
  const dmg = Math.max(1, amount);
  p.hp -= dmg;
  w.bus.emit({ k: 'hurt', amount: dmg });
  w.bus.emit({ k: 'shake', amount: 5 });
  w.bus.emit({ k: 'flash', color: 0xff3b30, a: 0.18 });
  // 技术验证阶段不结束游戏：生命归零时恢复
  if (p.hp <= 0) p.hp = p.maxHp;
}

// ---------------------------------------------------------------------------
// 刷怪
// ---------------------------------------------------------------------------

function savePrevPositions(w: World): void {
  const en = w.enemies;
  for (let i = 0; i < en.hi; i++) {
    en.px[i] = en.x[i] as number;
    en.py[i] = en.y[i] as number;
  }
  const g = w.gems;
  for (let i = 0; i < g.n; i++) {
    g.px[i] = g.x[i] as number;
    g.py[i] = g.y[i] as number;
  }
}

export function spawnEnemy(w: World, type: EnemyType, x: number, y: number): number {
  const en = w.enemies;
  const i = en.alloc();
  if (i < 0) return -1;
  const d = ENEMY[type];
  const m = w.t / 60;
  const sc = d.boss ? 1 : hpScale(m);
  en.type[i] = ENEMY_ID[type];
  en.x[i] = x;
  en.y[i] = y;
  en.px[i] = x;
  en.py[i] = y;
  en.r[i] = d.r;
  en.hp[i] = d.hp * sc;
  en.maxHp[i] = d.hp * sc;
  en.speed[i] = d.speed * w.rng.spawn.range(0.9, 1.1);
  en.dmg[i] = d.dmg * enemyDmgScale(m);
  en.wob[i] = w.rng.spawn.range(0, TAU);
  return i;
}

/** 屏幕外一圈的随机位置（对应旧版 ringPos） */
function ringPos(w: World, extra: number, out: { x: number; y: number }): void {
  const a = w.rng.spawn.range(0, TAU);
  const R = viewRadius(w) + extra;
  out.x = w.player.x + Math.cos(a) * R;
  out.y = w.player.y + Math.sin(a) * R;
}

const tmpPos = { x: 0, y: 0 };

function updateSpawns(w: World, dt: number): void {
  const en = w.enemies;
  if (w.benchTarget !== null) {
    let missing = Math.min(w.benchTarget - en.count, BENCH_REFILL_PER_STEP);
    while (missing-- > 0) {
      ringPos(w, 40, tmpPos);
      spawnEnemy(w, w.rng.spawn.chance(0.2) ? 'wisp' : 'shade', tmpPos.x, tmpPos.y);
    }
    return;
  }
  const m = w.t / 60;
  let rate = spawnRate(m);
  if (en.count > ENEMY_SOFT_CAP) rate = 0;
  w.spawnAcc += rate * dt;
  while (w.spawnAcc >= 1) {
    w.spawnAcc -= 1;
    const type: EnemyType = m >= 1 && w.rng.spawn.chance(0.2) ? 'wisp' : 'shade';
    ringPos(w, 40, tmpPos);
    spawnEnemy(w, type, tmpPos.x, tmpPos.y);
  }
}

// ---------------------------------------------------------------------------
// 妖物
// ---------------------------------------------------------------------------

function updateEnemies(w: World, dt: number): void {
  const en = w.enemies;
  const p = w.player;
  const decay = Math.exp(-8 * dt);
  const relocateDist = viewRadius(w) * 1.7;
  const toad = ENEMY_ID.toad;

  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i]) continue;
    en.flash[i] = Math.max(0, (en.flash[i] as number) - dt);
    en.wob[i] = (en.wob[i] as number) + dt * 5;

    let x = en.x[i] as number;
    let y = en.y[i] as number;
    const dx = p.x - x;
    const dy = p.y - y;
    const d = Math.hypot(dx, dy) || 1;

    x += (en.kx[i] as number) * dt;
    y += (en.ky[i] as number) * dt;
    en.kx[i] = (en.kx[i] as number) * decay;
    en.ky[i] = (en.ky[i] as number) * decay;

    if ((en.frozen[i] as number) > 0) {
      en.frozen[i] = (en.frozen[i] as number) - dt;
    } else if ((en.stun[i] as number) > 0) {
      en.stun[i] = (en.stun[i] as number) - dt;
    } else {
      let sp = en.speed[i] as number;
      if ((en.slow[i] as number) > 0) {
        en.slow[i] = (en.slow[i] as number) - dt;
        sp *= 1 - (en.slowAmt[i] as number);
        if ((en.slow[i] as number) <= 0) en.slowAmt[i] = 0;
      }
      x += (dx / d) * sp * dt;
      y += (dy / d) * sp * dt;
    }

    const def = ENEMY[ENEMY_TYPES[en.type[i] as number] as EnemyType];
    // 离得太远的普通妖物绕到玩家前方
    if (!def.elite && !def.boss && en.type[i] !== toad && d > relocateDist) {
      const a = Math.atan2(p.faceY, p.faceX) + w.rng.spawn.range(-0.8, 0.8);
      const R = viewRadius(w) + 40;
      x = p.x + Math.cos(a) * R;
      y = p.y + Math.sin(a) * R;
      // 瞬移：上一步位置也一起改，画面插值时不会拖出残影
      en.px[i] = x;
      en.py[i] = y;
    }
    en.x[i] = x;
    en.y[i] = y;

    if (d < (en.r[i] as number) + p.r && (en.dmg[i] as number) > 0) damagePlayer(w, en.dmg[i] as number);
  }
}

/** 妖物之间互相推开（与旧版相同的规则，只在相邻 9 格内比较） */
function separate(w: World, dt: number): void {
  const en = w.enemies;
  const g = w.grid;
  const k = 0.5 * Math.min(1, dt * 12);
  const boss = ENEMY_ID.boss;
  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i] || en.type[i] === boss) continue;
    const c = g.cellOf[i] as number;
    const cr = Math.floor(c / g.cols);
    const cc = c - cr * g.cols;
    const ri = en.r[i] as number;
    let x = en.x[i] as number;
    let y = en.y[i] as number;
    for (let row = Math.max(0, cr - 1); row <= Math.min(g.rows - 1, cr + 1); row++) {
      for (let col = Math.max(0, cc - 1); col <= Math.min(g.cols - 1, cc + 1); col++) {
        const cell = row * g.cols + col;
        const end = g.start[cell + 1] as number;
        for (let s = g.start[cell] as number; s < end; s++) {
          const o = g.items[s] as number;
          if (o === i || !en.alive[o]) continue;
          const ox = x - (en.x[o] as number);
          const oy = y - (en.y[o] as number);
          const min = (ri + (en.r[o] as number)) * 0.85;
          const d2 = ox * ox + oy * oy;
          if (d2 < min * min && d2 > 0.01) {
            const dd = Math.sqrt(d2);
            const push = (min - dd) * k;
            x += (ox / dd) * push;
            y += (oy / dd) * push;
          }
        }
      }
    }
    en.x[i] = x;
    en.y[i] = y;
  }
}

// ---------------------------------------------------------------------------
// 命中与击杀
// ---------------------------------------------------------------------------

export function hitEnemy(w: World, i: number, base: number, kb: number, fromX: number, fromY: number): void {
  const en = w.enemies;
  if (!en.alive[i]) return;
  const s = w.stats;
  let dmg = base * s.dmg;
  const crit = w.rng.combat.next() < s.critChance;
  if (crit) dmg *= s.critMult;
  en.hp[i] = (en.hp[i] as number) - dmg;
  en.flash[i] = 0.08;
  w.fx.push(FX.HIT, en.x[i] as number, (en.y[i] as number) - (en.r[i] as number) - 4, dmg, crit ? FX_CRIT : 0);

  const def = ENEMY[ENEMY_TYPES[en.type[i] as number] as EnemyType];
  if (kb > 0 && !def.boss) {
    const dx = (en.x[i] as number) - fromX;
    const dy = (en.y[i] as number) - fromY;
    const d = Math.hypot(dx, dy) || 1;
    const f = (kb * s.kb) / (def.elite ? 3 : 1);
    en.kx[i] = (en.kx[i] as number) + (dx / d) * f;
    en.ky[i] = (en.ky[i] as number) + (dy / d) * f;
  }
  if ((en.hp[i] as number) <= 0) killEnemy(w, i);
}

function killEnemy(w: World, i: number): void {
  const en = w.enemies;
  if (!en.alive[i]) return;
  const typeId = en.type[i] as number;
  const def = ENEMY[ENEMY_TYPES[typeId] as EnemyType];
  const x = en.x[i] as number;
  const y = en.y[i] as number;
  w.kills++;
  w.fx.push(FX.KILL, x, y, typeId, def.elite ? 1 : 0);
  if (def.xp > 0) {
    const value = def.xp * gemValueScale(w.t / 60);
    if (def.elite) {
      for (let k = 0; k < 8; k++) w.gems.drop(x + w.rng.loot.range(-20, 20), y + w.rng.loot.range(-20, 20), value / 8);
    } else {
      w.gems.drop(x, y, value);
    }
  }
  en.kill(i);
}

// ---------------------------------------------------------------------------
// 法器：灯火（环绕的火焰）
// ---------------------------------------------------------------------------

function updateLamp(w: World, dt: number): void {
  const L = w.lamp;
  const p = w.player;
  const s = w.stats;
  const base = W.lamp(L.lv);
  L.angle += (3.2 + L.lv * 0.12) * dt;
  L.count = Math.min(LAMP_MAX_FLAMES, base.count);
  L.radius = base.radius * s.area;
  L.size = 10 * Math.sqrt(s.area);
  const ids = w.scratch.ids;
  const en = w.enemies;
  for (let f = 0; f < L.count; f++) {
    const a = L.angle + (f * TAU) / L.count;
    const x = p.x + Math.cos(a) * L.radius;
    const y = p.y + Math.sin(a) * L.radius;
    L.fx[f] = x;
    L.fy[f] = y;
    const n = w.grid.queryCircle(en, x, y, L.size, ids);
    for (let k = 0; k < n; k++) {
      const i = ids[k] as number;
      if (!en.alive[i] || (en.cdLamp[i] as number) > w.t) continue;
      en.cdLamp[i] = w.t + 0.45;
      hitEnemy(w, i, base.dmg, 50, p.x, p.y);
    }
  }
}

// ---------------------------------------------------------------------------
// 魂火
// ---------------------------------------------------------------------------

function updateGems(w: World, dt: number): void {
  const g = w.gems;
  const p = w.player;
  const mag2 = w.stats.magnet * w.stats.magnet;
  for (let i = 0; i < g.n; i++) {
    const dx = p.x - (g.x[i] as number);
    const dy = p.y - (g.y[i] as number);
    const d2 = dx * dx + dy * dy;
    g.age[i] = (g.age[i] as number) + dt;
    // 魂火归灯：落地 8 秒没被捡的魂火会自己飞向灯笼
    if (!g.pulled[i] && (d2 < mag2 || (g.age[i] as number) > 8)) g.pulled[i] = 1;
    if (!g.pulled[i]) continue;
    const d = Math.sqrt(d2) || 1;
    const sp = Math.min(520, Math.hypot(g.vx[i] as number, g.vy[i] as number) + 900 * dt);
    g.vx[i] = (dx / d) * sp;
    g.vy[i] = (dy / d) * sp;
    g.x[i] = (g.x[i] as number) + (g.vx[i] as number) * dt;
    g.y[i] = (g.y[i] as number) + (g.vy[i] as number) * dt;
    if (d < p.r + 8) {
      addXp(w, g.v[i] as number);
      w.fx.push(FX.GEM_PICK, p.x, p.y, g.v[i] as number, 0);
      g.remove(i);
      i--;
    }
  }
}

function addXp(w: World, v: number): void {
  w.xp += v;
  while (w.xp >= xpNeed(w.level)) {
    w.xp -= xpNeed(w.level);
    w.level++;
    w.pendingLevels++;
  }
}
