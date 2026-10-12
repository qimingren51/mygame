// 伤害与击杀（移植自旧版 hitEnemy / killEnemy / killToad / damagePlayer / quake）。

import { FX, FX_BONUS, FX_CRIT, FX_DOT, RING_QUAKE } from '../core/fxqueue';
import { TAU } from '../core/math';
import { PLAYER, xpNeed } from '../data/balance';
import { ENEMY, ENEMY_TYPES, type EnemyDef, type EnemyType } from '../data/enemies';
import { BLAST_CAP, type World } from './state';

/** hitEnemy 的标志位 */
export const HIT_NOCRIT = 1;
/** 持续伤害：不触发灼烧、减速等命中效果 */
export const HIT_DOT = 2;
/** 金·锐追加的飞剑，不再触发追加 */
export const HIT_BONUS = 4;

export const enemyDef = (w: World, i: number): EnemyDef => ENEMY[ENEMY_TYPES[w.enemies.type[i] as number] as EnemyType];

/**
 * 对妖物 i 造成伤害。kb 为击退力度，从 (fromX, fromY) 方向推开。
 * bossCap > 0 时对夜主的单次伤害不超过它。
 */
export function hitEnemy(w: World, i: number, base: number, kb: number, fromX: number, fromY: number, flags = 0, bossCap = 0): void {
  const en = w.enemies;
  if (!en.alive[i]) return;
  const s = w.stats;
  const def = enemyDef(w, i);
  let dmg = base * s.dmg;
  const crit = flags & HIT_NOCRIT ? false : w.rng.combat.next() < s.critChance || ((en.stun[i] as number) > 0 && !!w.sheng['土生金']);
  if (crit) dmg *= s.critMult;
  if ((en.frozen[i] as number) > 0 && w.tier.water >= 3) dmg *= 1.5;
  if (def.boss && bossCap > 0) dmg = Math.min(dmg, bossCap);
  en.hp[i] = (en.hp[i] as number) - dmg;
  en.flash[i] = 0.08;
  const x = en.x[i] as number;
  const y = en.y[i] as number;
  w.fx.push(
    FX.HIT,
    x,
    y - (en.r[i] as number) - 4,
    dmg,
    (crit ? FX_CRIT : 0) | (flags & HIT_DOT ? FX_DOT : 0) | (flags & HIT_BONUS ? FX_BONUS : 0),
  );

  if (!(flags & HIT_DOT)) {
    if (w.tier.fire >= 1) {
      en.burnT[i] = 3;
      en.burnStacks[i] = w.tier.fire >= 2 ? Math.min(5, (en.burnStacks[i] as number) + 1) : 1;
      en.burnDps[i] = Math.max((en.burnDps[i] as number) * 0.9, dmg * 0.2 * s.burnMult);
    }
    if (w.tier.water >= 1) {
      en.slow[i] = Math.max(en.slow[i] as number, 1);
      en.slowAmt[i] = Math.max(en.slowAmt[i] as number, 0.2);
    }
    if (crit && w.sheng['金生水']) {
      en.slow[i] = Math.max(en.slow[i] as number, 1.5);
      en.slowAmt[i] = Math.max(en.slowAmt[i] as number, 0.35);
    }
    if (w.tier.water >= 2 && !def.boss && w.rng.combat.chance(0.12)) en.frozen[i] = 1;
    if (crit && w.tier.metal >= 3 && !(flags & HIT_BONUS) && w.rng.combat.chance(0.5)) {
      const p = w.player;
      const ang = Math.atan2(y - p.y, x - p.x);
      fireSword(w, p.x, p.y, ang, 10 + w.level, 2, en.handle(i), false, true);
    }
    if (kb > 0 && !def.boss) {
      const dx = x - fromX;
      const dy = y - fromY;
      const d = Math.hypot(dx, dy) || 1;
      const f = (kb * s.kb) / (def.elite ? 3 : 1);
      en.kx[i] = (en.kx[i] as number) + (dx / d) * f;
      en.ky[i] = (en.ky[i] as number) + (dy / d) * f;
    }
  }
  if ((en.hp[i] as number) <= 0) killEnemy(w, i);
}

export function fireSword(w: World, x: number, y: number, ang: number, dmg: number, pierce: number, target: number, big: boolean, bonus: boolean): void {
  const speed = 380;
  w.shots.add(x, y, Math.cos(ang) * speed, Math.sin(ang) * speed, dmg, pierce, target, big, bonus);
}

export function killEnemy(w: World, i: number): void {
  const en = w.enemies;
  if (!en.alive[i]) return;
  const typeId = en.type[i] as number;
  const def = enemyDef(w, i);
  const x = en.x[i] as number;
  const y = en.y[i] as number;
  const frozen = (en.frozen[i] as number) > 0;
  en.kill(i);
  w.fx.push(FX.KILL, x, y, typeId, def.elite || def.boss ? 1 : 0);
  if (def.toad) {
    killToad(w, x, y);
    return;
  }
  w.kills++;
  w.combo = w.comboT > 0 ? w.combo + 1 : 1;
  w.comboT = 2.2;
  if (w.combo > w.bestCombo) w.bestCombo = w.combo;
  if (w.combo === 100 || w.combo === 300 || w.combo === 500 || w.combo === 1000) w.bus.emit({ k: 'combo', n: w.combo });
  w.ult = Math.min(1, w.ult + (def.elite ? 0.15 : 1 / 140));

  const m = w.t / 60;
  const loot = w.rng.loot;
  if (def.xp > 0) {
    const value = def.xp * (1 + 0.25 * m) * w.mods.xp;
    if (def.elite) {
      for (let k = 0; k < 8; k++) w.gems.drop(x + loot.range(-20, 20), y + loot.range(-20, 20), value / 8);
    } else {
      w.gems.drop(x, y, value);
    }
  }
  if (def.elite) {
    w.pickups.push({ kind: 'chest', x, y, t: 0 });
    w.pickups.push({ kind: 'bell', x: x + 24, y, t: 0 });
  } else if (loot.chance(1 / 220)) w.pickups.push({ kind: 'bell', x, y, t: 0 });
  else if (!w.mods.noHeal && loot.chance(1 / 260)) w.pickups.push({ kind: 'lotus', x, y, t: 0 });

  if (w.tier.wood >= 3 && !w.mods.noHeal) w.player.hp = Math.min(w.stats.maxHp, w.player.hp + 0.4);
  if (w.tier.fire >= 3) queueBlast(w, x, y, 46, 8 + 4 * m, 0);
  if (w.tier.water >= 3 && frozen) queueBlast(w, x, y, 52, 10 + 5 * m, 1);

  if (def.boss) {
    w.boss = -1;
    w.wonAt = w.t + 0.6; // 慢镜头之后进入结算
    w.bus.emit({ k: 'flash', color: 0xfff1c2, a: 0.6 });
    w.bus.emit({ k: 'shake', amount: 12 });
  }
}

/** 金蟾：被打死时散落大量魂火与灯油 */
function killToad(w: World, x: number, y: number): void {
  const total = xpNeed(w.level) * 1.3;
  for (let i = 0; i < 24; i++) {
    const a = w.rng.loot.range(0, TAU);
    const r = w.rng.loot.range(10, 60);
    w.gems.drop(x + Math.cos(a) * r, y + Math.sin(a) * r, total / 24);
  }
  w.oilBonus += 30;
  w.bus.emit({ k: 'flash', color: 0xffd98a, a: 0.2 });
}

export function queueBlast(w: World, x: number, y: number, r: number, dmg: number, kind: 0 | 1): void {
  const b = w.blasts;
  if (b.n >= BLAST_CAP) return;
  const i = b.n++;
  b.x[i] = x;
  b.y[i] = y;
  b.r[i] = r;
  b.dmg[i] = dmg;
  b.kind[i] = kind;
}

/** 处理本步之前排队的连锁爆炸；处理中新排队的留到下一步（与旧版一致） */
export function processBlasts(w: World): void {
  const b = w.blasts;
  const n0 = b.n;
  if (!n0) return;
  w.bus.emit({ k: 'blast' });
  const ids = w.scratch.ids;
  const en = w.enemies;
  for (let k = 0; k < n0; k++) {
    const x = b.x[k] as number;
    const y = b.y[k] as number;
    const r = b.r[k] as number;
    const dmg = b.dmg[k] as number;
    w.fx.push(FX.BLAST, x, y, r, b.kind[k] as number);
    const n = w.grid.queryCircle(en, x, y, r, ids);
    for (let j = 0; j < n; j++) hitEnemy(w, ids[j] as number, dmg, 0, x, y, HIT_NOCRIT | HIT_DOT);
  }
  // 处理期间新排队的爆炸移到前面
  const extra = b.n - n0;
  b.x.copyWithin(0, n0, b.n);
  b.y.copyWithin(0, n0, b.n);
  b.r.copyWithin(0, n0, b.n);
  b.dmg.copyWithin(0, n0, b.n);
  b.kind.copyWithin(0, n0, b.n);
  b.n = extra;
}

export function damagePlayer(w: World, amount: number): void {
  const p = w.player;
  if (p.iframe > 0 || p.dashT > 0 || w.phase !== 'play') return;
  const s = w.stats;
  let dmg = Math.max(1, amount * s.taken - s.armor);
  if (p.shield > 0) {
    const absorbed = Math.min(p.shield, dmg);
    p.shield -= absorbed;
    dmg -= absorbed;
    if (p.shield <= 0) {
      p.shieldT = s.shieldCd;
      if (w.tier.earth >= 3) quake(w);
    }
  }
  p.iframe = PLAYER.iframe;
  if (dmg <= 0 || w.god) return;
  p.hp -= dmg;
  w.bus.emit({ k: 'hurt', amount: dmg });
  w.bus.emit({ k: 'shake', amount: 5 });
  w.bus.emit({ k: 'flash', color: 0xff3b30, a: 0.18 });
  w.fx.push(FX.PLAYER_HIT, p.x, p.y - 18, dmg, 0);
  if (p.hp <= 0) {
    p.hp = 0;
    endRun(w, false);
  }
}

/** 土·固 6 点：护盾破碎时震地 */
export function quake(w: World): void {
  const p = w.player;
  w.fx.push(FX.RING, p.x, p.y, 150, RING_QUAKE);
  w.bus.emit({ k: 'shake', amount: 8 });
  const ids = w.scratch.ids;
  const en = w.enemies;
  const n = w.grid.queryCircle(en, p.x, p.y, 150, ids);
  const dmg = 30 + 6 * (w.t / 60);
  for (let k = 0; k < n; k++) {
    const i = ids[k] as number;
    if (!en.alive[i]) continue;
    hitEnemy(w, i, dmg, 120, p.x, p.y);
    if (en.alive[i]) en.stun[i] = Math.max(en.stun[i] as number, 0.8);
  }
}

export function endRun(w: World, won: boolean): void {
  if (w.phase === 'over') return;
  w.phase = 'over';
  w.over = { won };
  w.choice = null;
  w.bus.emit({ k: 'over', won });
}
