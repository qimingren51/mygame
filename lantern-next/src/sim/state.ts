// 一局的全部模拟状态。这里只有数据，不依赖 DOM、Pixi 或浏览器 API。

import { EventBus } from '../core/bus';
import { FxQueue } from '../core/fxqueue';
import { createStreams, type Streams } from '../core/rng';
import { PLAYER, VIEW_HEIGHT } from '../data/balance';
import { Enemies } from './enemies';
import { Gems } from './gems';
import { SpatialGrid } from './spatial';

/** 每一步的玩家输入（已归一化的移动方向）。 */
export interface InputFrame {
  mx: number;
  my: number;
}

export const NO_INPUT: Readonly<InputFrame> = { mx: 0, my: 0 };

export type Command = { k: 'dash' };

export interface Player {
  x: number;
  y: number;
  px: number;
  py: number;
  r: number;
  hp: number;
  maxHp: number;
  faceX: number;
  faceY: number;
  moving: boolean;
  /** 本步移动的距离（画面层用来推进走路动画） */
  moved: number;
  iframe: number;
  dashT: number;
  dashCd: number;
  dashVX: number;
  dashVY: number;
}

export interface Stats {
  speed: number;
  magnet: number;
  area: number;
  dmg: number;
  critChance: number;
  critMult: number;
  kb: number;
}

export const LAMP_MAX_FLAMES = 16;

export interface Lamp {
  lv: number;
  angle: number;
  count: number;
  radius: number;
  size: number;
  fx: Float32Array;
  fy: Float32Array;
}

export interface World {
  readonly seed: number;
  readonly rng: Streams;
  t: number;
  tick: number;
  /** 可见范围（世界单位），由画面层通过 setView 传入 */
  view: { w: number; h: number };
  player: Player;
  readonly enemies: Enemies;
  readonly grid: SpatialGrid;
  readonly gems: Gems;
  lamp: Lamp;
  stats: Stats;
  kills: number;
  xp: number;
  level: number;
  pendingLevels: number;
  spawnAcc: number;
  /** 跑分模式：保持场上妖物数量；null 表示按正常节奏刷怪 */
  benchTarget: number | null;
  /** 无敌（跑分和调试用） */
  god: boolean;
  readonly bus: EventBus;
  readonly fx: FxQueue;
  readonly commands: Command[];
  /** 热路径用的临时数组，避免每步分配 */
  readonly scratch: { ids: Int32Array; near: Int32Array; d2: Float64Array };
}

export interface WorldOptions {
  seed: number;
  benchTarget?: number | null;
  god?: boolean;
  view?: { w: number; h: number };
}

export function createWorld(opts: WorldOptions): World {
  const view = opts.view ?? { w: (VIEW_HEIGHT * 16) / 9, h: VIEW_HEIGHT };
  return {
    seed: opts.seed,
    rng: createStreams(opts.seed),
    t: 0,
    tick: 0,
    view,
    player: {
      x: 0,
      y: 0,
      px: 0,
      py: 0,
      r: PLAYER.radius,
      hp: PLAYER.maxHp,
      maxHp: PLAYER.maxHp,
      faceX: 1,
      faceY: 0,
      moving: false,
      moved: 0,
      iframe: 0,
      dashT: 0,
      dashCd: 0,
      dashVX: 0,
      dashVY: 0,
    },
    enemies: new Enemies(),
    grid: new SpatialGrid(),
    gems: new Gems(),
    lamp: {
      lv: 1,
      angle: 0,
      count: 0,
      radius: 0,
      size: 0,
      fx: new Float32Array(LAMP_MAX_FLAMES),
      fy: new Float32Array(LAMP_MAX_FLAMES),
    },
    stats: { speed: PLAYER.speed, magnet: PLAYER.magnet, area: 1, dmg: 1, critChance: 0.05, critMult: 2, kb: 1 },
    kills: 0,
    xp: 0,
    level: 1,
    pendingLevels: 0,
    spawnAcc: 0,
    benchTarget: opts.benchTarget ?? null,
    god: opts.god ?? false,
    bus: new EventBus(),
    fx: new FxQueue(),
    commands: [],
    scratch: { ids: new Int32Array(2048), near: new Int32Array(32), d2: new Float64Array(32) },
  };
}

/** 视口对角线的一半（世界单位），对应旧版 viewRadius()。 */
export const viewRadius = (w: World): number => Math.hypot(w.view.w, w.view.h) / 2;

export function setView(w: World, width: number, height: number): void {
  w.view.w = width;
  w.view.h = height;
}

/** 状态摘要：用于验证同一种子、同样输入能得到完全相同的结果。 */
export function stateHash(w: World): number {
  let h = 0x811c9dc5;
  const mix = (v: number) => {
    h = Math.imul(h ^ (Math.fround(v) * 1000) | 0, 0x01000193);
  };
  const en = w.enemies;
  for (let i = 0; i < en.hi; i++) {
    if (!en.alive[i]) continue;
    mix(i);
    mix(en.x[i] as number);
    mix(en.y[i] as number);
    mix(en.hp[i] as number);
  }
  mix(w.player.x);
  mix(w.player.y);
  mix(w.player.hp);
  mix(w.gems.n);
  mix(w.kills);
  mix(w.xp);
  for (const r of Object.values(w.rng)) mix(r.state);
  return h >>> 0;
}
