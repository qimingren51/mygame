import { describe, expect, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { buildOptions, computeStats, rollChoices } from '../../src/sim/build';
import { NO_INPUT, getWeapon, type World } from '../../src/sim/state';
import { createRun, step } from '../../src/sim/step';

const fresh = (seed = 1): World => createRun({ seed, god: true });

describe('属性与五行共鸣', () => {
  it('心法按等级叠加属性', () => {
    const w = fresh();
    w.passives.push({ id: 'changming', lv: 3 }, { id: 'ruimu', lv: 2 }, { id: 'houde', lv: 1 });
    computeStats(w);
    expect(w.stats.area).toBeCloseTo(1.3);
    expect(w.stats.maxHp).toBe(120);
    expect(w.stats.armor).toBe(1);
    // 锐目 2 级 +10%，没有金系共鸣
    expect(w.stats.critChance).toBeCloseTo(0.15);
  });

  it('满级法器计 2 点，2 点触发一阶共鸣，并发出事件', () => {
    const w = fresh();
    const lamp = getWeapon(w, 'lamp');
    if (!lamp) throw new Error('开局应有灯火');
    lamp.lv = 8;
    computeStats(w, true);
    expect(w.res.fire).toBe(2);
    expect(w.tier.fire).toBe(1);
    const events: string[] = [];
    w.bus.drain((e) => events.push(e.k));
    expect(events).toContain('resonance');
  });

  it('金系一阶共鸣：暴击率 +10%', () => {
    const w = fresh();
    w.passives.push({ id: 'jianyi', lv: 5 });
    computeStats(w);
    expect(w.tier.metal).toBe(1);
    expect(w.stats.critChance).toBeCloseTo(0.15);
  });

  it('相邻两系都激活时点亮相生，五系全开是太极', () => {
    const w = fresh();
    w.passives.push({ id: 'zhezhi', lv: 5 }, { id: 'luxin', lv: 5 });
    computeStats(w);
    expect(w.sheng['木生火']).toBe(true);
    expect(w.stats.burnMult).toBeCloseTo(1.3);
    w.passives.push({ id: 'jianyi', lv: 5 }, { id: 'jingxin', lv: 5 }, { id: 'houde', lv: 5 });
    computeStats(w);
    expect(w.taiji).toBe(true);
  });
});

describe('升级选项', () => {
  it('法器满级且持有对应心法时，进化以极高权重出现', () => {
    const w = fresh();
    const lamp = getWeapon(w, 'lamp');
    if (!lamp) throw new Error('开局应有灯火');
    lamp.lv = 8;
    w.passives.push({ id: 'changming', lv: 1 });
    const evo = buildOptions(w).find((o) => o.type === 'evo');
    expect(evo).toMatchObject({ type: 'evo', id: 'lamp', weight: 1000 });
    let hits = 0;
    for (let i = 0; i < 50; i++) if (rollChoices(w).options.some((o) => o.type === 'evo')) hits++;
    expect(hits).toBe(50);
  });

  it('没有满级心法时不出进化；已满级法器不再出升级', () => {
    const w = fresh();
    const lamp = getWeapon(w, 'lamp');
    if (!lamp) throw new Error('开局应有灯火');
    lamp.lv = 8;
    const opts = buildOptions(w);
    expect(opts.some((o) => o.type === 'evo')).toBe(false);
    expect(opts.some((o) => o.type === 'wup' && o.id === 'lamp')).toBe(false);
  });

  it('什么都满了只剩莲子和灯油', () => {
    const w = fresh();
    w.weapons = [];
    w.passives = [];
    for (const id of ['lamp', 'sword', 'bell', 'crane', 'seal'] as const) w.weapons.push({ id, lv: 8, evo: true, t: 0, angle: 0, big: 6, count: 0, radius: 0, size: 0, cranes: [] });
    for (const id of ['changming', 'luxin', 'jianyi', 'ruimu', 'jingxin', 'yinhun'] as const) w.passives.push({ id, lv: 5 });
    const r = rollChoices(w);
    expect(r.options.map((o) => o.type)).toEqual(['heal', 'oil']);
  });
});

describe('升级流程', () => {
  it('升级时暂停在三选一，选完继续', () => {
    const w = fresh(9);
    w.pendingLevels = 1;
    w.level = 2;
    step(w, SIM_DT, NO_INPUT);
    expect(w.phase).toBe('levelup');
    expect(w.choice?.options.length).toBeGreaterThanOrEqual(3);
    const t = w.t;
    step(w, SIM_DT, NO_INPUT);
    expect(w.t).toBe(t); // 选择期间时间不走
    const before = w.weapons.length + w.passives.length + w.weapons.reduce((a, x) => a + x.lv, 0) + w.passives.reduce((a, x) => a + x.lv, 0);
    w.commands.push({ k: 'choose', i: 0 });
    step(w, SIM_DT, NO_INPUT);
    expect(w.phase).toBe('play');
    const after = w.weapons.length + w.passives.length + w.weapons.reduce((a, x) => a + x.lv, 0) + w.passives.reduce((a, x) => a + x.lv, 0);
    expect(after).toBeGreaterThan(before);
  });

  it('重抽消耗次数，跳过得灯油', () => {
    const w = fresh(4);
    w.pendingLevels = 1;
    step(w, SIM_DT, NO_INPUT);
    const r0 = w.rerolls;
    w.commands.push({ k: 'reroll' });
    step(w, SIM_DT, NO_INPUT);
    expect(w.rerolls).toBe(r0 - 1);
    expect(w.phase).toBe('levelup');
    w.commands.push({ k: 'skip' });
    step(w, SIM_DT, NO_INPUT);
    expect(w.oilBonus).toBe(10);
    expect(w.phase).toBe('play');
  });

  it('选进化后进入进化演出，确认后继续', () => {
    const w = fresh(5);
    const lamp = getWeapon(w, 'lamp');
    if (!lamp) throw new Error('开局应有灯火');
    lamp.lv = 8;
    w.passives.push({ id: 'changming', lv: 1 });
    w.pendingLevels = 1;
    step(w, SIM_DT, NO_INPUT);
    const i = w.choice?.options.findIndex((o) => o.type === 'evo') ?? -1;
    expect(i).toBeGreaterThanOrEqual(0);
    w.commands.push({ k: 'choose', i });
    step(w, SIM_DT, NO_INPUT);
    expect(w.phase).toBe('evo');
    expect(w.evo).toBe('lamp');
    expect(lamp.evo).toBe(true);
    w.commands.push({ k: 'ack' });
    step(w, SIM_DT, NO_INPUT);
    expect(w.phase).toBe('play');
  });

  it('宝箱 1 / 3 / 5 连，内容直接生效', () => {
    const counts = new Set<number>();
    for (let seed = 1; seed <= 40; seed++) {
      const w = fresh(seed);
      w.chestQueue = 1;
      const lv0 = w.weapons.reduce((a, x) => a + x.lv, 0) + w.passives.reduce((a, x) => a + x.lv, 0);
      step(w, SIM_DT, NO_INPUT);
      expect(w.phase).toBe('chest');
      const n = w.chest?.n ?? 0;
      counts.add(n);
      const lv1 = w.weapons.reduce((a, x) => a + x.lv, 0) + w.passives.reduce((a, x) => a + x.lv, 0);
      expect(lv1).toBe(lv0 + n);
      w.commands.push({ k: 'ack' });
      step(w, SIM_DT, NO_INPUT);
      expect(w.phase).toBe('play');
    }
    expect([...counts].every((n) => n === 1 || n === 3 || n === 5)).toBe(true);
    expect(counts.has(1)).toBe(true);
  });
});
