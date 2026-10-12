// 平衡常数与公式（移植自旧版，数值保持一致）。

export const RUN_LENGTH = 600; // 10 分钟
export const BOSS_TIME = 570; // 9:30 夜主降临

export const xpNeed = (lv: number): number => 4 + 5 * lv + 0.6 * lv * lv;

/** 妖物血量倍率，m 为分钟 */
export const hpScale = (m: number, enemyHpMod = 1): number => (1 + 0.3 * m + 0.07 * m * m) * enemyHpMod;

/** 每秒刷怪数，m 为分钟 */
export const spawnRate = (m: number, spawnMod = 1): number => (1.6 + 1.1 * m + 0.1 * m * m) * spawnMod;

/** 魂火价值倍率，m 为分钟 */
export const gemValueScale = (m: number): number => 1 + 0.25 * m;

/** 妖物接触伤害随时间增长，m 为分钟 */
export const enemyDmgScale = (m: number): number => 1 + 0.1 * m;

export const PLAYER = {
  radius: 11,
  speed: 118,
  maxHp: 100,
  magnet: 65,
  iframe: 0.5,
  dashTime: 0.16,
  dashSpeed: 720,
  dashCd: 2.4,
  dashIframe: 0.3,
} as const;

/** 灯笼照亮的基础半径（世界单位），实际半径还乘以 √area 和夜签的光照倍率 */
export const LIGHT_RADIUS = 200;

/** 常规刷怪时的妖物数量上限（迁移期保持旧版的 360） */
export const ENEMY_SOFT_CAP = 360;

/** 魂火数量上限，超过后并入最近的一颗 */
export const GEM_CAP = 380;

/** 旧版的世界缩放：视野高度约 420 个世界单位 */
export const VIEW_HEIGHT = 420;
