// 五行（移植自旧版 EL、SHENG、tierOf）。

export const ELEMENT_IDS = ['metal', 'wood', 'water', 'fire', 'earth'] as const;
export type ElementId = (typeof ELEMENT_IDS)[number];

export interface ElementDef {
  name: string;
  res: string;
  color: number;
  tiers: [string, string, string];
}

export const EL: Record<ElementId, ElementDef> = {
  metal: { name: '金', res: '锐', color: 0xe9d9a6, tiers: ['暴击率 +10%', '暴击伤害 +50%', '暴击时追加飞剑'] },
  wood: { name: '木', res: '生', color: 0x6fd6a0, tiers: ['每秒回复 0.5% 生命', '数量 +1', '击杀回复生命'] },
  water: { name: '水', res: '凝', color: 0x6fb8ff, tiers: ['命中减速', '命中有概率冰冻', '冰冻目标易伤并碎裂'] },
  fire: { name: '火', res: '焚', color: 0xff8a3d, tiers: ['命中附加灼烧', '灼烧可叠加', '妖物死亡时爆炸'] },
  earth: { name: '土', res: '固', color: 0xc9925a, tiers: ['周期获得护盾', '击退加倍', '护盾破碎时震地'] },
};

/** 相生：木 → 火 → 土 → 金 → 水 → 木 */
export const SHENG = [
  { a: 'wood', b: 'fire', name: '木生火', desc: '灼烧伤害 +30%' },
  { a: 'fire', b: 'earth', name: '火生土', desc: '护盾恢复加快' },
  { a: 'earth', b: 'metal', name: '土生金', desc: '被击晕的目标必定暴击' },
  { a: 'metal', b: 'water', name: '金生水', desc: '暴击使目标减速' },
  { a: 'water', b: 'wood', name: '水生木', desc: '生命回复翻倍' },
] as const satisfies readonly { a: ElementId; b: ElementId; name: string; desc: string }[];

export const tierOf = (n: number): 0 | 1 | 2 | 3 => (n >= 6 ? 3 : n >= 4 ? 2 : n >= 2 ? 1 : 0);
