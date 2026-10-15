import { describe, expect, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { ENEMY_ID } from '../../src/data/enemies';
import { spawnEnemy, updateSpawns } from '../../src/sim/spawn';
import { createRun } from '../../src/sim/step';

describe('夜主出场', () => {
  it('满池时保留事件，释放槽位后只出场一次', () => {
    const w = createRun({ seed: 7, god: true });
    const boss = w.plan.find((s) => s.kind === 'boss')!;
    w.plan = [boss];
    w.t = boss.at;
    w.nextPack = Infinity;
    w.mods.spawn = 0;
    while (spawnEnemy(w, 'shade', 1000, 0) >= 0) { /* 填满池 */ }
    const cap = w.enemies.count;

    for (let k = 0; k < 2; k++) {
      updateSpawns(w, SIM_DT);
      expect(boss.done).toBe(false);
      expect(w.boss).toBe(-1);
      const events: string[] = [];
      w.bus.drain((e) => events.push(e.k));
      expect(events).not.toContain('boss');
      expect(events).not.toContain('shake');
      expect(events).not.toContain('flash');
    }

    w.enemies.kill(0);
    updateSpawns(w, SIM_DT);
    const handle = w.boss;
    expect(w.enemies.type[w.enemies.resolve(handle)]).toBe(ENEMY_ID.boss);
    expect(w.enemies.count).toBe(cap);
    expect(boss.done).toBe(true);
    const events: string[] = [];
    w.bus.drain((e) => events.push(e.k));
    expect(events.filter((k) => k === 'boss')).toHaveLength(1);

    w.enemies.kill(1);
    updateSpawns(w, SIM_DT);
    expect(w.boss).toBe(handle);
    expect(w.enemies.count).toBe(cap - 1);
    w.bus.drain((e) => expect(e.k).not.toBe('boss'));
  });
});
