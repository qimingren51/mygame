// 分析：整局埋点（草稿副本专用）
import { writeFileSync } from 'node:fs';
import { describe, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { PROBE } from '../../src/sim/probe';
import type { InputFrame, World } from '../../src/sim/state';
import { createRun, step } from '../../src/sim/step';
import { botInput, respond } from './bot';

const OUT = process.env.PROBE_OUT ?? '/tmp/probe.json';

function snap(w: World) {
  return {
    t: Math.round(w.t),
    level: w.level,
    kills: w.kills,
    alive: w.enemies.count,
    gems: w.gems.n,
    evolutions: w.evolutions,
    weapons: w.weapons.map((x) => `${x.id}${x.evo ? '*' : x.lv}`).join(' '),
    passives: w.passives.map((x) => `${x.id}${x.lv}`).join(' '),
    tier: { ...w.tier },
    taiji: w.taiji,
    stats: { dmg: w.stats.dmg, crit: w.stats.critChance, critMult: w.stats.critMult, area: w.stats.area, cd: w.stats.cd, amount: w.stats.amount, maxHp: w.stats.maxHp },
    hp: w.player.hp,
    ult: w.ult,
    probe: JSON.parse(JSON.stringify({ eff: PROBE.eff, raw: PROBE.raw, boss: PROBE.boss, hits: PROBE.hits, crits: PROBE.crits, spawnHp: PROBE.spawnHp, spawnN: PROBE.spawnN, spawnByType: PROBE.spawnByType, incoming: PROBE.incoming, hitsTaken: PROBE.hitsTaken })),
  };
}

/** 风筝机器人：远离附近妖物的“重心”，同时绕圈；被围时闪避 */
function kiteInput(w: World, input: InputFrame): void {
  const p = w.player;
  const en = w.enemies;
  let rx = 0;
  let ry = 0;
  let close = 0;
  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i]) continue;
    const dx = p.x - (en.x[i] as number);
    const dy = p.y - (en.y[i] as number);
    const d2 = dx * dx + dy * dy;
    if (d2 > 220 * 220) continue;
    const d = Math.sqrt(d2) || 1;
    const wgt = 1 / Math.max(20, d) ** 2;
    rx += (dx / d) * wgt;
    ry += (dy / d) * wgt;
    if (d < 40) close++;
  }
  for (const f of w.foes) {
    const dx = p.x - f.x;
    const dy = p.y - f.y;
    const d = Math.hypot(dx, dy) || 1;
    if (d < 120) {
      rx += (dx / d) * 3 / Math.max(20, d) ** 2;
      ry += (dy / d) * 3 / Math.max(20, d) ** 2;
    }
  }
  // 切向分量：绕着妖群转，而不是一路直线逃跑
  const tx = -ry;
  const ty = rx;
  let mx = rx + tx * 0.6;
  let my = ry + ty * 0.6;
  const l = Math.hypot(mx, my);
  if (l < 1e-9) {
    const a = w.tick * 0.01;
    mx = Math.cos(a);
    my = Math.sin(a * 0.7);
  } else {
    mx /= l;
    my /= l;
  }
  input.mx = mx;
  input.my = my;
  if (close >= 3 && p.dashCd <= 0) w.commands.push({ k: 'dash' });
}

function runOnce(seed: number, god: boolean, kite: boolean) {
  PROBE.reset();
  const w = createRun({ seed, god });
  const input: InputFrame = { mx: 0, my: 0 };
  const samples: ReturnType<typeof snap>[] = [snap(w)];
  let bossAt = -1;
  for (let s = 0; s < 60 * 60 * 12 && w.phase !== 'over'; s++) {
    respond(w);
    if (kite) kiteInput(w, input);
    else botInput(w, input);
    step(w, SIM_DT, input);
    w.bus.drain((e) => {
      if (e.k === 'boss') bossAt = w.t;
    });
    w.fx.clear();
    if (w.phase === 'play' && w.tick % 1800 === 0) samples.push(snap(w));
  }
  samples.push(snap(w));
  return { seed, god, kite, won: w.over?.won ?? false, end: w.t, bossAt, samples };
}

describe('probe', () => {
  it('runs', { timeout: 3_600_000 }, () => {
    const res: unknown[] = [];
    const mode = process.env.PROBE_MODE ?? 'god';
    const seeds = (process.env.PROBE_SEEDS ?? '424242,1,2,3').split(',').map(Number);
    for (const seed of seeds) {
      if (mode === 'god') res.push(runOnce(seed, true, false));
      else if (mode === 'godkite') res.push(runOnce(seed, true, true));
      else if (mode === 'mortal') res.push(runOnce(seed, false, false));
      else if (mode === 'kite') res.push(runOnce(seed, false, true));
    }
    writeFileSync(OUT, JSON.stringify(res));
  });
});
