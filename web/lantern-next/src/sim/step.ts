// 模拟的一步（固定 1/60 秒）。执行顺序沿用旧版 update()：
// 玩家 → 护盾 / 太极 → 刷怪 → 建网格 → 妖物（灼烧、移动、接触伤害）→ 互相推开
// → 法器（飞剑、石印、地裂）→ 弹幕 → 连锁爆炸 → 魂火 → 拾取物 → 升级 / 宝箱 / 胜利。

import { FX, FX_DOT, RING_TAIJI, RING_ULT } from '../core/fxqueue';
import { PLAYER, xpNeed } from '../data/balance';
import { ENEMY_ID } from '../data/enemies';
import { computeStats } from './build';
import { HIT_NOCRIT, damagePlayer, enemyDef, hitEnemy, killEnemy, processBlasts } from './combat';
import { checkFlow, handleChoiceCommand } from './flow';
import { updateBoss, updateSpawns } from './spawn';
import { createWorld, onScreen, viewRadius, type InputFrame, type World, type WorldOptions } from './state';
import { updateWeapons } from './weapons';

export { spawnEnemy } from './spawn';
export { hitEnemy } from './combat';

/** 开一局：建世界、算属性、满血。 */
export function createRun(opts: WorldOptions): World {
  const w = createWorld(opts);
  computeStats(w);
  w.player.hp = w.stats.maxHp;
  return w;
}

export function step(w: World, dt: number, input: InputFrame): void {
  if (w.phase !== 'play') {
    // 等待界面：只处理选择命令，时间不推进
    for (const c of w.commands) handleChoiceCommand(w, c);
    w.commands.length = 0;
    return;
  }
  w.tick++;
  w.t += dt;
  updatePlayer(w, dt, input);
  if (w.phase !== 'play') return;
  savePrevPositions(w);
  updateTimers(w, dt);
  updateSpawns(w, dt);
  const R = viewRadius(w) * 1.8;
  w.grid.build(w.enemies, w.player.x, w.player.y, R, R);
  updateEnemies(w, dt);
  separate(w, dt);
  updateWeapons(w, dt);
  updateFoes(w, dt);
  processBlasts(w);
  updateGems(w, dt);
  updatePickups(w, dt);
  checkFlow(w);
}

// ---------------------------------------------------------------------------
// 玩家
// ---------------------------------------------------------------------------

function updatePlayer(w: World, dt: number, input: InputFrame): void {
  const p = w.player;
  const s = w.stats;
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
    } else if (c.k === 'ult') {
      ultimate(w);
    }
  }
  w.commands.length = 0;

  if (p.dashT > 0) {
    p.dashT -= dt;
    p.x += p.dashVX * dt;
    p.y += p.dashVY * dt;
  } else {
    p.x += mx * s.speed * dt;
    p.y += my * s.speed * dt;
  }
  p.moved = Math.hypot(p.x - p.px, p.y - p.py);
  p.iframe = Math.max(0, p.iframe - dt);
  p.dashCd = Math.max(0, p.dashCd - dt);
  p.hp = Math.min(s.maxHp, p.hp + s.regen * dt);
}

/** 燃灯：清屏大招，充满后可用 */
function ultimate(w: World): void {
  if (w.ult < 1) return;
  w.ult = 0;
  const p = w.player;
  w.fx.push(FX.RING, p.x, p.y, viewRadius(w) * 1.1, RING_ULT);
  w.bus.emit({ k: 'ult' });
  w.bus.emit({ k: 'flash', color: 0xffd98a, a: 0.55 });
  w.bus.emit({ k: 'shake', amount: 12 });
  const dmg = 120 * (1 + 0.4 * (w.t / 60));
  const en = w.enemies;
  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i] || !onScreen(w, en.x[i] as number, en.y[i] as number, 60)) continue;
    if (enemyDef(w, i).boss) hitEnemy(w, i, (en.maxHp[i] as number) * 0.05, 0, p.x, p.y, HIT_NOCRIT);
    else hitEnemy(w, i, dmg, 160, p.x, p.y);
  }
  w.foes.length = 0;
}

function updateTimers(w: World, dt: number): void {
  const p = w.player;
  // 土·固：护盾
  if (w.tier.earth >= 1 && p.shield <= 0) {
    p.shieldT -= dt;
    if (p.shieldT <= 0) {
      p.shield = 20 + 5 * (w.t / 60);
      p.shieldMax = p.shield;
    }
  }
  // 太极：每 30 秒全屏轮转五行之力
  if (w.taiji) {
    w.taijiT += dt;
    if (w.taijiT >= 30) {
      w.taijiT = 0;
      w.fx.push(FX.RING, p.x, p.y, viewRadius(w), RING_TAIJI);
      const en = w.enemies;
      const dmg = 40 * (1 + 0.4 * (w.t / 60));
      for (let i = 0; i < en.hi; i++) {
        if (en.alive[i] && onScreen(w, en.x[i] as number, en.y[i] as number)) hitEnemy(w, i, dmg, 0, p.x, p.y, 0, 600);
      }
    }
  }
  const intensity = w.t < 180 ? 0 : w.t < 390 ? 1 : 2;
  if (intensity !== w.intensity) {
    w.intensity = intensity;
    w.bus.emit({ k: 'intensity', level: intensity });
  }
  w.comboT -= dt;
  if (w.comboT <= 0) w.combo = 0;
}

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
  for (const f of w.foes) {
    f.px = f.x;
    f.py = f.y;
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
  const bossType = ENEMY_ID.boss;

  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i]) continue;
    en.flash[i] = Math.max(0, (en.flash[i] as number) - dt);
    en.wob[i] = (en.wob[i] as number) + dt * 5;

    // 灼烧
    if ((en.burnT[i] as number) > 0) {
      en.burnT[i] = (en.burnT[i] as number) - dt;
      const dmg = (en.burnDps[i] as number) * (en.burnStacks[i] as number) * dt;
      en.hp[i] = (en.hp[i] as number) - dmg;
      en.burnAcc[i] = (en.burnAcc[i] as number) + dmg;
      en.burnShow[i] = (en.burnShow[i] as number) - dt;
      if ((en.burnShow[i] as number) <= 0 && (en.burnAcc[i] as number) >= 1) {
        w.fx.push(FX.HIT, en.x[i] as number, (en.y[i] as number) - (en.r[i] as number), en.burnAcc[i] as number, FX_DOT);
        en.burnAcc[i] = 0;
        en.burnShow[i] = 0.5;
      }
      if ((en.hp[i] as number) <= 0) {
        killEnemy(w, i);
        continue;
      }
    } else {
      en.burnStacks[i] = 0;
      en.burnDps[i] = 0;
    }

    let x = en.x[i] as number;
    let y = en.y[i] as number;
    const dx = p.x - x;
    const dy = p.y - y;
    const d = Math.hypot(dx, dy) || 1;

    x += (en.kx[i] as number) * dt;
    y += (en.ky[i] as number) * dt;
    en.kx[i] = (en.kx[i] as number) * decay;
    en.ky[i] = (en.ky[i] as number) * decay;

    const type = en.type[i] as number;
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
      if (type === toad) {
        // 金蟾背着玩家逃，略慢于玩家，追得上
        const wob = Math.sin(w.t * 3 + (en.wob[i] as number)) * 0.6;
        const ax = -dx / d;
        const ay = -dy / d;
        x += (ax * Math.cos(wob) - ay * Math.sin(wob)) * sp * dt;
        y += (ax * Math.sin(wob) + ay * Math.cos(wob)) * sp * dt;
      } else {
        x += (dx / d) * sp * dt;
        y += (dy / d) * sp * dt;
      }
    }
    en.x[i] = x;
    en.y[i] = y;

    if (type === bossType) updateBoss(w, i, dt);

    const def = enemyDef(w, i);
    // 离得太远的普通妖物绕到玩家前方
    if (!def.elite && !def.boss && type !== toad && d > relocateDist) {
      const a = Math.atan2(p.faceY, p.faceX) + w.rng.spawn.range(-0.8, 0.8);
      const R = viewRadius(w) + 40;
      en.x[i] = p.x + Math.cos(a) * R;
      en.y[i] = p.y + Math.sin(a) * R;
      // 瞬移：上一步位置也一起改，画面插值时不会拖出残影
      en.px[i] = en.x[i] as number;
      en.py[i] = en.y[i] as number;
    }

    if (d < (en.r[i] as number) + p.r && (en.dmg[i] as number) > 0) damagePlayer(w, en.dmg[i] as number);
    if (w.phase !== 'play') return;
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
// 夜主弹幕
// ---------------------------------------------------------------------------

function updateFoes(w: World, dt: number): void {
  const p = w.player;
  const list = w.foes;
  for (let k = 0; k < list.length; k++) {
    const f = list[k];
    if (!f) continue;
    f.life -= dt;
    f.x += f.vx * dt;
    f.y += f.vy * dt;
    if ((f.x - p.x) ** 2 + (f.y - p.y) ** 2 < (f.r + p.r) ** 2) {
      damagePlayer(w, f.dmg);
      list.splice(k--, 1);
      continue;
    }
    if (f.life <= 0) list.splice(k--, 1);
  }
}

// ---------------------------------------------------------------------------
// 魂火与拾取物
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

function updatePickups(w: World, dt: number): void {
  const p = w.player;
  const list = w.pickups;
  const reach = (p.r + 16) ** 2;
  for (let k = 0; k < list.length; k++) {
    const it = list[k];
    if (!it) continue;
    it.t += dt;
    if ((it.x - p.x) ** 2 + (it.y - p.y) ** 2 >= reach) continue;
    list.splice(k--, 1);
    if (it.kind === 'chest') {
      w.chestQueue++;
    } else if (it.kind === 'bell') {
      const g = w.gems;
      for (let i = 0; i < g.n; i++) g.pulled[i] = 1;
      w.bus.emit({ k: 'flash', color: 0x5fd4c4, a: 0.15 });
    } else {
      const heal = w.stats.maxHp * 0.3;
      p.hp = Math.min(w.stats.maxHp, p.hp + heal);
      w.fx.push(FX.PLAYER_HEAL, p.x, p.y - 20, heal, 0);
      w.bus.emit({ k: 'heal', amount: heal });
    }
    w.bus.emit({ k: 'pickup', kind: it.kind });
  }
}
