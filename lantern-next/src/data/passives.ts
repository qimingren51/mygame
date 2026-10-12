// 心法（被动技能，移植自旧版 PASSIVES）。

import type { ElementId } from './elements';

export const PASSIVE_IDS = ['changming', 'luxin', 'jianyi', 'ruimu', 'jingxin', 'yinhun', 'zhezhi', 'jixing', 'houde', 'panshi'] as const;
export type PassiveId = (typeof PASSIVE_IDS)[number];

export interface PassiveDef {
  name: string;
  el: ElementId;
  desc: string;
}

export const PASSIVES: Record<PassiveId, PassiveDef> = {
  changming: { name: '长明', el: 'fire', desc: '攻击范围 +10%' },
  luxin: { name: '炉心', el: 'fire', desc: '伤害 +8%' },
  jianyi: { name: '剑意', el: 'metal', desc: '暴击伤害 +20%' },
  ruimu: { name: '锐目', el: 'metal', desc: '暴击率 +5%' },
  jingxin: { name: '静心', el: 'water', desc: '冷却 -6%' },
  yinhun: { name: '引魂', el: 'water', desc: '拾取范围 +25%' },
  zhezhi: { name: '折纸', el: 'wood', desc: '1 / 3 / 5 级时数量 +1' },
  jixing: { name: '疾行', el: 'wood', desc: '移动速度 +8%' },
  houde: { name: '厚德', el: 'earth', desc: '生命上限 +20，护甲 +1' },
  panshi: { name: '磐石', el: 'earth', desc: '受到伤害 -5%' },
};
