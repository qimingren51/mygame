// 法器数据（移植自旧版 WEAPONS 与 W）。

import type { ElementId } from './elements';

export const WEAPON_IDS = ['lamp', 'sword', 'bell', 'crane', 'seal'] as const;
export type WeaponId = (typeof WEAPON_IDS)[number];

export const WEAPON_MAX = 8;
export const PASSIVE_MAX = 5;
export const SLOT_MAX = 6;

export interface WeaponDef {
  name: string;
  icon: string;
  el: ElementId;
  evoPassive: string;
  evoName: string;
  desc: string;
  evoDesc: string;
}

export const WEAPONS: Record<WeaponId, WeaponDef> = {
  lamp: {
    name: '灯火', icon: '灯', el: 'fire', evoPassive: 'changming', evoName: '不夜城',
    desc: '火焰环绕周身，烧灼靠近的妖物。',
    evoDesc: '十盏灯笼环城而行，范围更大、伤害翻倍',
  },
  sword: {
    name: '符剑', icon: '剑', el: 'metal', evoPassive: 'jianyi', evoName: '万剑归宗',
    desc: '自动射出追踪符剑，可穿透。',
    evoDesc: '飞剑连发，无限穿透',
  },
  bell: {
    name: '霜铃', icon: '铃', el: 'water', evoPassive: 'jingxin', evoName: '寒山钟',
    desc: '周期震出寒波，伤害并减速周围妖物。',
    evoDesc: '每 6 秒钟鸣全屏，冻结所有妖物',
  },
  crane: {
    name: '纸鹤', icon: '鹤', el: 'wood', evoPassive: 'zhezhi', evoName: '千鹤引',
    desc: '纸鹤自动扑向妖物，撞击后折返。',
    evoDesc: '十只纸鹤随身，扑击更快更狠',
  },
  seal: {
    name: '山印', icon: '印', el: 'earth', evoPassive: 'houde', evoName: '镇岳',
    desc: '石印从天而降，范围伤害并击晕。',
    evoDesc: '巨岩砸出地裂，裂缝持续伤害并减速',
  },
};

/** 各法器每级数值 */
export const W = {
  lamp: (lv: number) => ({ count: [3, 3, 4, 4, 5, 5, 6, 6][lv - 1] as number, radius: 50 + lv * 4, dmg: 12 + lv * 3 }),
  sword: (lv: number) => ({ cd: 1.15 - lv * 0.06, count: 1 + Math.floor(lv / 3), dmg: 12 + lv * 4, pierce: 1 + Math.floor(lv / 3) }),
  bell: (lv: number) => ({ cd: 3 - lv * 0.15, radius: 70 + lv * 9, dmg: 6 + lv * 3 }),
  crane: (lv: number) => ({ count: [1, 1, 2, 2, 3, 3, 4, 4][lv - 1] as number, dmg: 9 + lv * 3 }),
  seal: (lv: number) => ({ cd: 4.2 - lv * 0.22, count: 1 + Math.floor(lv / 3), radius: 38 + lv * 4, dmg: 22 + lv * 8 }),
};
