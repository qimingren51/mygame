// 五件法器与进化（移植自旧版 WEAPON_UPDATE、updateShots、sealImpact、updateZones）。

import { FX, RING_BELL, RING_BIGBELL } from '../core/fxqueue';
import { TAU } from '../core/math';
import { W } from '../data/weapons';
import { HIT_BONUS, HIT_DOT, HIT_NOCRIT, enemyDef, fireSword, hitEnemy } from './combat';
import { onScreen, viewRadius, type Crane, type WeaponState, type World } from './state';

export function updateWeapons(w: World, dt: number): void {
  for (const wp of w.weapons) {
    switch (wp.id) {
      case 'lamp':
        wp.angle += (wp.evo ? 2.4 : 3.2 + wp.lv * 0.12) * dt;
        lamp(w, wp);
        break;
      case 'sword':
        sword(w, wp, dt);
        break;
      case 'bell':
        bell(w, wp, dt);
        break;
      case 'crane':
        crane(w, wp, dt);
        break;
      case 'seal':
        seal(w, wp, dt);
        break;
    }
  }
  updateShots(w, dt);
  updateSeals(w, dt);
  updateZones(w, dt);
}

// ---------------------------------------------------------------------------
// 灯火 / 不夜城：火焰环绕周身
// ---------------------------------------------------------------------------

function lamp(w: World, wp: WeaponState): void {
  const s = w.stats;
  const p = w.player;
  const base = W.lamp(wp.lv);
  const count = (wp.evo ? 10 : base.count) + s.amount;
  const radius = (wp.evo ? 92 : base.radius) * s.area;
  const dmg = base.dmg * (wp.evo ? 2.2 : 1);
  const size = (wp.evo ? 12 : 10) * Math.sqrt(s.area);
  wp.count = count;
  wp.radius = radius;
  wp.size = size;
  const ids = w.scratch.ids;
  const en = w.enemies;
  for (let f = 0; f < count; f++) {
    const a = wp.angle + (f * TAU) / count;
    const x = p.x + Math.cos(a) * radius;
    const y = p.y + Math.sin(a) * radius;
    const n = w.grid.queryCircle(en, x, y, size, ids);
    for (let k = 0; k < n; k++) {
      const i = ids[k] as number;
      if (!en.alive[i] || (en.cdLamp[i] as number) > w.t) continue;
      en.cdLamp[i] = w.t + 0.45;
      hitEnemy(w, i, dmg, 50, p.x, p.y);
    }
  }
}

// ---------------------------------------------------------------------------
// 符剑 / 万剑归宗：追踪飞剑，可穿透
// ---------------------------------------------------------------------------

function sword(w: World, wp: WeaponState, dt: number): void {
  wp.t -= dt;
  if (wp.t > 0) return;
  const s = w.stats;
  const p = w.player;
  const base = W.sword(wp.lv);
  const count = (wp.evo ? 3 : base.count) + s.amount;
  const near = w.scratch.near;
  const n = w.grid.nearestK(w.enemies, p.x, p.y, 460, Math.min(count, near.length), near, w.scratch.d2);
  if (!n) {
    wp.t = 0.2;
    return;
  }
  wp.t = (wp.evo ? 0.42 : base.cd) * s.cd;
  const en = w.enemies;
  for (let i = 0; i < count; i++) {
    const t = near[i % n] as number;
    const ang = Math.atan2((en.y[t] as number) - p.y, (en.x[t] as number) - p.x) + (i - (count - 1) / 2) * 0.14;
    fireSword(w, p.x, p.y, ang, base.dmg * (wp.evo ? 1.6 : 1), wp.evo ? 999 : base.pierce, en.handle(t), wp.evo, false);
  }
  w.bus.emit({ k: 'sword' });
}

function updateShots(w: World, dt: number): void {
  const sh = w.shots;
  const en = w.enemies;
  const ids = w.scratch.ids;
  for (let i = 0; i < sh.n; i++) {
    sh.px[i] = sh.x[i] as number;
    sh.py[i] = sh.y[i] as number;
    const life = (sh.life[i] as number) - dt;
    if (life <= 0) {
      sh.remove(i--);
      continue;
    }
    sh.life[i] = life;
    let vx = sh.vx[i] as number;
    let vy = sh.vy[i] as number;
    const t = en.resolve(sh.target[i] as number);
    if (t >= 0) {
      const want = Math.atan2((en.y[t] as number) - (sh.y[i] as number), (en.x[t] as number) - (sh.x[i] as number));
      const cur = Math.atan2(vy, vx);
      let diff = want - cur;
      while (diff > Math.PI) diff -= TAU;
      while (diff < -Math.PI) diff += TAU;
      const turn = Math.max(-8 * dt, Math.min(8 * dt, diff));
      const sp = Math.hypot(vx, vy);
      vx = Math.cos(cur + turn) * sp;
      vy = Math.sin(cur + turn) * sp;
      sh.vx[i] = vx;
      sh.vy[i] = vy;
    } else if ((sh.target[i] as number) >= 0) {
      sh.target[i] = -1;
    }
    const x = (sh.x[i] as number) + vx * dt;
    const y = (sh.y[i] as number) + vy * dt;
    sh.x[i] = x;
    sh.y[i] = y;
    let alive = true;
    const n = w.grid.queryCircle(en, x, y, sh.big[i] ? 9 : 6, ids);
    for (let k = 0; k < n && alive; k++) {
      const e = ids[k] as number;
      if (!en.alive[e]) continue;
      const h = en.handle(e);
      if (sh.hasHit(i, h)) continue;
      sh.markHit(i, h);
      if (sh.target[i] === h) sh.target[i] = -1;
      hitEnemy(w, e, sh.dmg[i] as number, 30, x, y, sh.bonus[i] ? HIT_BONUS : 0);
      const pierce = (sh.pierce[i] as number) - 1;
      sh.pierce[i] = pierce;
      if (pierce <= 0) alive = false;
    }
    if (!alive) sh.remove(i--);
  }
}

// ---------------------------------------------------------------------------
// 霜铃 / 寒山钟：周期寒波，减速；进化后每 6 秒全屏冻结
// ---------------------------------------------------------------------------

function bell(w: World, wp: WeaponState, dt: number): void {
  const s = w.stats;
  const p = w.player;
  const base = W.bell(wp.lv);
  const en = w.enemies;
  const ids = w.scratch.ids;
  wp.t -= dt;
  if (wp.t <= 0) {
    wp.t = base.cd * s.cd;
    const r = base.radius * s.area * (wp.evo ? 1.3 : 1);
    w.fx.push(FX.RING, p.x, p.y, r, RING_BELL);
    w.bus.emit({ k: 'bell', big: false });
    const n = w.grid.queryCircle(en, p.x, p.y, r, ids);
    for (let k = 0; k < n; k++) {
      const i = ids[k] as number;
      if (!en.alive[i]) continue;
      hitEnemy(w, i, base.dmg * (wp.evo ? 1.5 : 1), 40, p.x, p.y);
      if (!en.alive[i]) continue;
      en.slow[i] = Math.max(en.slow[i] as number, 1.5);
      en.slowAmt[i] = Math.max(en.slowAmt[i] as number, 0.35);
    }
  }
  if (wp.evo) {
    wp.big -= dt;
    if (wp.big <= 0) {
      wp.big = 6 * s.cd;
      w.fx.push(FX.RING, p.x, p.y, viewRadius(w), RING_BIGBELL);
      w.bus.emit({ k: 'flash', color: 0x6fb8ff, a: 0.18 });
      w.bus.emit({ k: 'bell', big: true });
      for (let i = 0; i < en.hi; i++) {
        if (!en.alive[i] || !onScreen(w, en.x[i] as number, en.y[i] as number)) continue;
        if (!enemyDef(w, i).boss) en.frozen[i] = 1.5;
        hitEnemy(w, i, base.dmg * 3, 0, p.x, p.y, 0, 400);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 纸鹤 / 千鹤引：纸鹤扑向妖物，撞击后折返
// ---------------------------------------------------------------------------

function newCrane(x: number, y: number): Crane {
  return { x, y, px: x, py: y, vx: 0, vy: 0, state: 0, t: 0.2, target: -1, ang: 0 };
}

function crane(w: World, wp: WeaponState, dt: number): void {
  const s = w.stats;
  const p = w.player;
  const base = W.crane(wp.lv);
  const n = (wp.evo ? 10 : base.count) + s.amount;
  while (wp.cranes.length < n) wp.cranes.push(newCrane(p.x, p.y));
  const speed = wp.evo ? 330 : 250 + wp.lv * 6;
  const dmg = base.dmg * (wp.evo ? 1.5 : 1);
  const en = w.enemies;
  const near = w.scratch.near;
  const total = wp.cranes.length;
  for (let i = 0; i < total; i++) {
    const c = wp.cranes[i] as Crane;
    c.px = c.x;
    c.py = c.y;
    c.t -= dt;
    let tx: number;
    let ty: number;
    if (c.state === 0) {
      const a = w.t * 2 + (i * TAU) / total;
      tx = p.x + Math.cos(a) * 34;
      ty = p.y + Math.sin(a) * 34;
      if (c.t <= 0) c.state = 1;
    } else {
      let t = en.resolve(c.target);
      if (t < 0 || ((en.x[t] as number) - p.x) ** 2 + ((en.y[t] as number) - p.y) ** 2 > 340 * 340) {
        const k = w.grid.nearestK(en, c.x, c.y, 340, 3, near, w.scratch.d2);
        t = k ? (near[w.rng.combat.int(k)] as number) : -1;
        c.target = t >= 0 ? en.handle(t) : -1;
      }
      if (t < 0) {
        c.state = 0;
        c.t = 0.3;
        continue;
      }
      tx = en.x[t] as number;
      ty = en.y[t] as number;
      const d = Math.hypot(tx - c.x, ty - c.y);
      if (d < (en.r[t] as number) + 6) {
        hitEnemy(w, t, dmg, 50, c.x, c.y);
        c.state = 0;
        c.t = wp.evo ? 0.2 : 0.35;
      }
    }
    const dx = tx - c.x;
    const dy = ty - c.y;
    const d = Math.hypot(dx, dy) || 1;
    const k = Math.min(1, dt * 7);
    c.vx += ((dx / d) * speed - c.vx) * k;
    c.vy += ((dy / d) * speed - c.vy) * k;
    c.x += c.vx * dt;
    c.y += c.vy * dt;
    c.ang = Math.atan2(c.vy, c.vx);
  }
}

// ---------------------------------------------------------------------------
// 山印 / 镇岳：石印从天而降，范围伤害并击晕；进化后留下地裂
// ---------------------------------------------------------------------------

function seal(w: World, wp: WeaponState, dt: number): void {
  wp.t -= dt;
  if (wp.t > 0) return;
  const s = w.stats;
  const p = w.player;
  const base = W.seal(wp.lv);
  wp.t = (wp.evo ? 2.6 : base.cd) * s.cd;
  const count = base.count + (wp.evo ? 1 : 0) + Math.floor(s.amount / 2);
  const radius = base.radius * s.area * (wp.evo ? 2 : 1);
  const near = w.scratch.near;
  let cands = w.grid.nearestK(w.enemies, p.x, p.y, 300, Math.min(12, near.length), near, w.scratch.d2);
  const en = w.enemies;
  const rng = w.rng.combat;
  for (let i = 0; i < count; i++) {
    let x: number;
    let y: number;
    if (cands > 0) {
      // 从候选里随机取一个并移除
      const j = rng.int(cands);
      const e = near[j] as number;
      near[j] = near[cands - 1] as number;
      cands--;
      x = en.x[e] as number;
      y = en.y[e] as number;
    } else {
      x = p.x + rng.range(-150, 150);
      y = p.y + rng.range(-100, 100);
    }
    w.seals.push({ x, y, r: radius, t: -i * 0.12, life: 0.45, dmg: base.dmg * (wp.evo ? 1.5 : 1), evo: wp.evo });
  }
}

function updateSeals(w: World, dt: number): void {
  const list = w.seals;
  const en = w.enemies;
  const ids = w.scratch.ids;
  for (let k = 0; k < list.length; k++) {
    const fx = list[k];
    if (!fx) continue;
    fx.t += dt;
    if (fx.t < fx.life) continue;
    // 落地
    list.splice(k--, 1);
    w.fx.push(FX.SEAL_HIT, fx.x, fx.y, fx.r, fx.evo ? 1 : 0);
    w.bus.emit({ k: 'shake', amount: fx.evo ? 7 : 3 });
    w.bus.emit({ k: 'seal' });
    const n = w.grid.queryCircle(en, fx.x, fx.y, fx.r, ids);
    for (let j = 0; j < n; j++) {
      const i = ids[j] as number;
      if (!en.alive[i]) continue;
      hitEnemy(w, i, fx.dmg, 90, fx.x, fx.y);
      if (en.alive[i]) en.stun[i] = Math.max(en.stun[i] as number, 0.5);
    }
    if (fx.evo) w.zones.push({ x: fx.x, y: fx.y, r: fx.r * 0.85, life: 2.5, max: 2.5, tick: 0, dmg: fx.dmg * 0.25 });
  }
}

function updateZones(w: World, dt: number): void {
  const list = w.zones;
  const en = w.enemies;
  const ids = w.scratch.ids;
  for (let k = 0; k < list.length; k++) {
    const z = list[k];
    if (!z) continue;
    z.life -= dt;
    z.tick -= dt;
    if (z.tick <= 0) {
      z.tick = 0.5;
      const n = w.grid.queryCircle(en, z.x, z.y, z.r, ids);
      for (let j = 0; j < n; j++) {
        const i = ids[j] as number;
        if (!en.alive[i]) continue;
        hitEnemy(w, i, z.dmg, 0, z.x, z.y, HIT_DOT | HIT_NOCRIT);
        if (!en.alive[i]) continue;
        en.slow[i] = Math.max(en.slow[i] as number, 0.6);
        en.slowAmt[i] = Math.max(en.slowAmt[i] as number, 0.4);
      }
    }
    if (z.life <= 0) list.splice(k--, 1);
  }
}
