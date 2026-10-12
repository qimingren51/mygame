// 本局规则修正（夜签、心灯会改这些值；移植自旧版 baseMods 与 meta）。
// 里程碑 2 后半段加入夜签和心灯，现在全部取默认值。

import type { ElementId } from './elements';

export interface Mods {
  xp: number;
  spawn: number;
  crit: number;
  light: number;
  dmg: number;
  maxHp: number;
  chestMin: number;
  elites: number;
  speed: number;
  enemySpeed: number;
  chestRain: boolean;
  enemyHp: number;
  favor: ElementId | null;
  oil: number;
  noHeal: boolean;
  choices: number;
  events: number;
}

export const baseMods = (): Mods => ({
  xp: 1,
  spawn: 1,
  crit: 0,
  light: 1,
  dmg: 1,
  maxHp: 1,
  chestMin: 1,
  elites: 1,
  speed: 1,
  enemySpeed: 1,
  chestRain: false,
  enemyHp: 1,
  favor: null,
  oil: 1,
  noHeal: false,
  choices: 3,
  events: 1,
});

/** 心灯（局外成长）等级 */
export interface MetaLevels {
  dmg: number;
  hp: number;
  agi: number;
  luck: number;
}

export const NO_META: MetaLevels = { dmg: 0, hp: 0, agi: 0, luck: 0 };
