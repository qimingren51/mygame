// 妖物数据（移植自旧版 ENEMY）。
// 颜色只作为画面提示；玩法只读数值字段。

export const ENEMY_TYPES = ['shade', 'wisp', 'golem', 'fox', 'ghoul', 'boss', 'stonelord', 'toad'] as const;
export type EnemyType = (typeof ENEMY_TYPES)[number];

export interface EnemyDef {
  name: string;
  r: number;
  hp: number;
  speed: number;
  dmg: number;
  xp: number;
  elite?: boolean;
  boss?: boolean;
  toad?: boolean;
  /** 画面提示：身体、轮廓、眼睛、面具的颜色 */
  body: number;
  rim: number;
  eye: number;
  mask?: number;
}

export const ENEMY: Record<EnemyType, EnemyDef> = {
  shade: { name: '影妖', r: 13, hp: 10, speed: 46, dmg: 5, xp: 1, body: 0x1c1630, rim: 0x4a3873, eye: 0xff8a5b },
  wisp: { name: '疾影', r: 10, hp: 6, speed: 84, dmg: 4, xp: 1, body: 0x141e2c, rim: 0x3b5f80, eye: 0x9fe3ff },
  golem: { name: '石妖', r: 19, hp: 45, speed: 30, dmg: 10, xp: 3, body: 0x211b17, rim: 0x6a5238, eye: 0xffb46b },
  fox: { name: '赤面狐', r: 24, hp: 320, speed: 58, dmg: 14, xp: 20, elite: true, body: 0x2a1426, rim: 0xff6b5a, eye: 0xff6b5a, mask: 0xf4ebdd },
  ghoul: { name: '青面鬼', r: 30, hp: 900, speed: 50, dmg: 18, xp: 40, elite: true, body: 0x13231f, rim: 0x5fd4a0, eye: 0xc8ff6b, mask: 0xcfe8dc },
  boss: { name: '夜主 · 九尾', r: 44, hp: 36000, speed: 52, dmg: 22, xp: 0, boss: true, body: 0x2a1426, rim: 0xffb46b, eye: 0xffd98a, mask: 0xf4ebdd },
  stonelord: { name: '石将', r: 28, hp: 1100, speed: 34, dmg: 16, xp: 30, elite: true, body: 0x2a2119, rim: 0xc9925a, eye: 0xffb46b },
  toad: { name: '金蟾', r: 14, hp: 70, speed: 80, dmg: 0, xp: 0, toad: true, body: 0x5a4210, rim: 0xffd98a, eye: 0xfff1c2 },
};

/** 类型编号（存进 Uint8Array 用） */
export const ENEMY_ID: Record<EnemyType, number> = Object.fromEntries(ENEMY_TYPES.map((t, i) => [t, i])) as Record<EnemyType, number>;
