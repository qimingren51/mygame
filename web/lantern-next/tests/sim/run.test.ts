// 无界面整局：机器人玩 10 分钟，检查成长曲线和结束条件。

import { describe, expect, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { NO_INPUT, type InputFrame } from '../../src/sim/state';
import { createRun, spawnEnemy, step } from '../../src/sim/step';
import { botInput, respond } from './bot';

describe('整局模拟', () => {
  it('机器人（无敌）10 分钟内升到 20 级以上、出现进化，并在击败夜主后结束', { timeout: 60_000 }, () => {
    const w = createRun({ seed: 424242, god: true });
    const input: InputFrame = { mx: 0, my: 0 };
    const levels: number[] = [];
    let events = 0;
    for (let s = 0; s < 60 * 60 * 12 && w.phase !== 'over'; s++) {
      respond(w);
      botInput(w, input);
      step(w, SIM_DT, input);
      w.bus.drain(() => events++);
      w.fx.clear();
      if (w.tick % 1800 === 0 && w.phase === 'play') levels.push(w.level);
    }
    console.info(
      `整局：每 30 秒等级 ${levels.join(',')}；击杀 ${w.kills}；进化 ${w.evolutions}；用时 ${w.t.toFixed(0)} 秒；` +
        `法器 ${w.weapons.map((x) => `${x.id}${x.evo ? '★' : x.lv}`).join(' ')}；心法 ${w.passives.map((x) => `${x.id}${x.lv}`).join(' ')}`,
    );
    // 3、6、9 分钟时的等级
    expect(levels[5]).toBeGreaterThanOrEqual(8);
    expect(levels[11]).toBeGreaterThanOrEqual(14);
    expect(w.level).toBeGreaterThanOrEqual(20);
    expect(w.evolutions).toBeGreaterThanOrEqual(1);
    expect(w.kills).toBeGreaterThan(1000);
    expect(w.plan.every((p) => p.done)).toBe(true);
    // 无敌时只要击败夜主就会结束
    expect(w.phase).toBe('over');
    expect(w.over?.won).toBe(true);
    expect(events).toBeGreaterThan(0);
  });

  it('不无敌时贴身的妖物会造成伤害，生命不超过上限，归零即结束', () => {
    const w = createRun({ seed: 7, god: false });
    w.plan = [];
    w.mods.spawn = 0;
    // 石妖血厚，灯火一时打不死，贴身站着
    for (let k = 0; k < 6; k++) spawnEnemy(w, 'golem', Math.cos(k) * 8, Math.sin(k) * 8);
    let minHp = Infinity;
    for (let s = 0; s < 60 * 120 && w.phase !== 'over'; s++) {
      respond(w);
      step(w, SIM_DT, NO_INPUT);
      w.bus.clear();
      w.fx.clear();
      expect(w.player.hp).toBeLessThanOrEqual(w.stats.maxHp + 1e-6);
      minHp = Math.min(minHp, w.player.hp);
      // 一直补充贴身的石妖
      if (s % 60 === 0) spawnEnemy(w, 'golem', w.player.x + 5, w.player.y + 5);
    }
    expect(minHp).toBeLessThan(w.stats.maxHp);
    expect(w.phase).toBe('over');
    expect(w.over?.won).toBe(false);
    expect(w.player.hp).toBe(0);
  });
});

it('燃灯清掉贴身弹幕后不再造成伤害', () => {
  const w = createRun({ seed: 7 });
  w.plan = [];
  w.mods.spawn = 0;
  w.ult = 1;
  w.foes.push({ x: w.player.x, y: w.player.y, px: w.player.x, py: w.player.y, vx: 0, vy: 0, r: 5, life: 2, dmg: 14 });
  w.commands.push({ k: 'ult' });
  step(w, SIM_DT, NO_INPUT);
  expect(w.foes).toHaveLength(0);
  expect(w.player.hp).toBe(w.stats.maxHp);
  expect(w.ult).toBe(0);
});
