import { describe, expect, it } from 'vitest';
import { computeStats } from '../../src/sim/build';
import { getWeapon } from '../../src/sim/state';
import { createRun } from '../../src/sim/step';
import { optionInfo, optionNote, weaponUpgradeText } from '../../src/ui/optionText';

describe('升级卡片文字', () => {
  it('法器升级说明列出变化的数值', () => {
    expect(weaponUpgradeText('sword', 1)).toBe('伤害 +4，冷却 -0.06 秒。');
    // 2 → 3 级时数量和穿透各 +1
    expect(weaponUpgradeText('sword', 2)).toBe('数量 +1，伤害 +4，穿透 +1，冷却 -0.06 秒。');
    expect(weaponUpgradeText('lamp', 2)).toBe('数量 +1，伤害 +3，范围 +4。');
  });

  it('新法器、升级、心法、进化的品级与类别', () => {
    const w = createRun({ seed: 1 });
    expect(optionInfo(w, { type: 'wnew', id: 'sword', weight: 1 })).toMatchObject({ rarity: 'xuan', kind: '法器 · 新', name: '符剑', el: '金' });
    expect(optionInfo(w, { type: 'wup', id: 'lamp', weight: 1 })).toMatchObject({ rarity: 'ling', kind: '法器 · Lv1 → 2' });
    expect(optionInfo(w, { type: 'pnew', id: 'zhezhi', weight: 1 })).toMatchObject({ rarity: 'ling', icon: '折' });
    expect(optionInfo(w, { type: 'evo', id: 'lamp', weight: 1 })).toMatchObject({ rarity: 'tian', name: '不夜城' });
    expect(optionInfo(w, { type: 'heal', weight: 1 })).toMatchObject({ name: '莲子', el: null });
  });

  it('提示共鸣进度与进化线索', () => {
    const w = createRun({ seed: 1 });
    // 火 1 点，再拿一个火系心法到 2 点：共鸣激活
    const note = optionNote(w, { type: 'pnew', id: 'luxin', weight: 1 });
    expect(note?.title).toBe('火 1 → 2 · 共鸣激活');
    expect(note?.body).toContain('灼烧');
    // 新法器提示进化所需心法
    expect(optionNote(w, { type: 'wnew', id: 'crane', weight: 1 })?.body).toBe('进化需心法「折纸」');
    // 灯火满级 + 长明：可进化
    const lamp = getWeapon(w, 'lamp');
    if (!lamp) throw new Error('开局应有灯火');
    lamp.lv = 8;
    w.passives.push({ id: 'changming', lv: 1 });
    computeStats(w);
    expect(optionNote(w, { type: 'evo', id: 'lamp', weight: 1 })?.title).toBe('选择后立即进化');
    expect(optionNote(w, { type: 'pup', id: 'changming', weight: 1 })?.title).toBe('可进化');
  });
});
