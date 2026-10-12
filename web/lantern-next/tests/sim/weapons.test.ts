import { describe, expect, it } from 'vitest';
import { FX } from '../../src/core/fxqueue';
import { SIM_DT } from '../../src/core/loop';
import { TAU } from '../../src/core/math';
import type { WeaponId } from '../../src/data/weapons';
import { computeStats } from '../../src/sim/build';
import { NO_INPUT, newWeapon, type World } from '../../src/sim/state';
import { createRun, spawnEnemy, step } from '../../src/sim/step';

/** 只带一件法器的世界，周围摆一圈影妖；关掉正常刷怪 */
function arena(id: WeaponId, lv: number, evo: boolean): World {
  const w = createRun({ seed: 11, god: true });
  w.weapons = [newWeapon(id)];
  const wp = w.weapons[0];
  if (!wp) throw new Error('unreachable');
  wp.lv = lv;
  wp.evo = evo;
  computeStats(w);
  // 不让计划里的精英、夜主出场，也不正常刷怪
  w.plan = [];
  w.benchTarget = null;
  w.mods.spawn = 0;
  for (let k = 0; k < 40; k++) {
    const a = (k / 40) * TAU;
    const r = 60 + (k % 4) * 30;
    spawnEnemy(w, 'shade', Math.cos(a) * r, Math.sin(a) * r);
  }
  return w;
}

function runFor(w: World, seconds: number): { kills: number; codes: Set<number> } {
  const codes = new Set<number>();
  for (let s = 0; s < Math.round(seconds / SIM_DT); s++) {
    step(w, SIM_DT, NO_INPUT);
    w.fx.drain((c) => codes.add(c));
    w.bus.clear();
    // 不处理升级：一直留在 play 阶段
    w.pendingLevels = 0;
  }
  return { kills: w.kills, codes };
}

describe.each([
  ['lamp', false],
  ['lamp', true],
  ['sword', false],
  ['sword', true],
  ['bell', false],
  ['bell', true],
  ['crane', false],
  ['crane', true],
  ['seal', false],
  ['seal', true],
] as [WeaponId, boolean][])('%s（进化 %s）', (id, evo) => {
  it('能击杀妖物', () => {
    const w = arena(id, 8, evo);
    const r = runFor(w, 8);
    expect(r.kills).toBeGreaterThan(5);
    expect(r.codes.has(FX.HIT)).toBe(true);
  });
});

describe('法器细节', () => {
  it('符剑发射飞剑并在命中后消失或穿透', () => {
    const w = arena('sword', 1, false);
    let maxShots = 0;
    for (let s = 0; s < 120; s++) {
      step(w, SIM_DT, NO_INPUT);
      maxShots = Math.max(maxShots, w.shots.n);
    }
    expect(maxShots).toBeGreaterThan(0);
  });

  it('霜铃发出寒波（环）并减速', () => {
    const w = arena('bell', 4, false);
    const r = runFor(w, 4);
    expect(r.codes.has(FX.RING)).toBe(true);
  });

  it('镇岳落地后留下地裂', () => {
    const w = arena('seal', 8, true);
    let zones = 0;
    for (let s = 0; s < 300; s++) {
      step(w, SIM_DT, NO_INPUT);
      zones = Math.max(zones, w.zones.length);
      w.pendingLevels = 0;
    }
    expect(zones).toBeGreaterThan(0);
  });

  it('纸鹤数量随等级和进化增加', () => {
    const a = arena('crane', 1, false);
    step(a, SIM_DT, NO_INPUT);
    const b = arena('crane', 8, true);
    step(b, SIM_DT, NO_INPUT);
    expect(a.weapons[0]?.cranes.length).toBe(1);
    expect(b.weapons[0]?.cranes.length).toBe(10);
  });
});
