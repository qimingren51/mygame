// 一局的全部模拟状态。这里只有数据，不依赖 DOM、Pixi 或浏览器 API。

import { EventBus } from '../core/bus';
import { FxQueue } from '../core/fxqueue';
import { createStreams, type Streams } from '../core/rng';
import { PLAYER, VIEW_HEIGHT } from '../data/balance';
import { ELEMENT_IDS, type ElementId } from '../data/elements';
import { baseMods, NO_META, type MetaLevels, type Mods } from '../data/mods';
import type { PassiveId } from '../data/passives';
import type { WeaponId } from '../data/weapons';
import { Enemies } from './enemies';
import { Gems } from './gems';
import { Shots } from './shots';
import { SpatialGrid } from './spatial';

/** 每一步的玩家输入（已归一化的移动方向）。 */
export interface InputFrame {
  mx: number;
  my: number;
}

export const NO_INPUT: Readonly<InputFrame> = { mx: 0, my: 0 };

/** 界面发给模拟的命令。choose / reroll / skip 用于升级选择，ack 用于确认宝箱和进化演出。 */
export type Command = { k: 'dash' } | { k: 'ult' } | { k: 'choose'; i: number } | { k: 'reroll' } | { k: 'skip' } | { k: 'ack' };

/**
 * 局面阶段。只有 play 时时间才会推进；其余阶段等待界面发来命令。
 * levelup：升级选择；chest：宝箱揭晓；evo：进化演出；over：结束。
 */
export type Phase = 'play' | 'levelup' | 'chest' | 'evo' | 'over';

export interface Player {
  x: number;
  y: number;
  px: number;
  py: number;
  r: number;
  hp: number;
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
  /** 土·固 的护盾 */
  shield: number;
  shieldMax: number;
  shieldT: number;
}

export interface Stats {
  area: number;
  dmg: number;
  critChance: number;
  critMult: number;
  cd: number;
  magnet: number;
  amount: number;
  speed: number;
  maxHp: number;
  armor: number;
  taken: number;
  regen: number;
  burnMult: number;
  shieldCd: number;
  kb: number;
}

export const LAMP_MAX_FLAMES = 24;

export interface Crane {
  x: number;
  y: number;
  px: number;
  py: number;
  vx: number;
  vy: number;
  /** 0 = 绕身休息，1 = 扑击 */
  state: 0 | 1;
  t: number;
  /** 目标妖物的句柄，-1 表示没有 */
  target: number;
  ang: number;
}

export interface WeaponState {
  id: WeaponId;
  lv: number;
  evo: boolean;
  /** 冷却计时 */
  t: number;
  /** 灯火的旋转角 */
  angle: number;
  /** 寒山钟的全屏钟鸣计时 */
  big: number;
  // 灯火：当前的火焰数量、半径、大小（画面层读取）
  count: number;
  radius: number;
  size: number;
  cranes: Crane[];
}

export interface PassiveState {
  id: PassiveId;
  lv: number;
}

interface WeaponOption<T extends string> {
  type: T;
  id: WeaponId;
  weight: number;
}

interface PassiveOption<T extends string> {
  type: T;
  id: PassiveId;
  weight: number;
}

/** 每种选项单独一个类型，TypeScript 才能按 type 正确收窄 */
export type Option =
  | WeaponOption<'evo'>
  | WeaponOption<'wup'>
  | WeaponOption<'wnew'>
  | PassiveOption<'pup'>
  | PassiveOption<'pnew'>
  | { type: 'heal'; weight: number }
  | { type: 'oil'; weight: number };

export interface Choice {
  options: Option[];
  /** 灵光一闪：四选一 */
  lingguang: boolean;
  /** 这次升级前后的等级（界面显示 Lv a → b） */
  fromLevel: number;
}

export interface ChestReveal {
  n: number;
  items: Option[];
}

/** 山印的落点预警，到时落地 */
export interface SealWarn {
  x: number;
  y: number;
  r: number;
  t: number;
  life: number;
  dmg: number;
  evo: boolean;
}

/** 镇岳的地裂：持续伤害并减速 */
export interface Zone {
  x: number;
  y: number;
  r: number;
  life: number;
  max: number;
  tick: number;
  dmg: number;
}

export type PickupKind = 'chest' | 'bell' | 'lotus';

export interface Pickup {
  kind: PickupKind;
  x: number;
  y: number;
  t: number;
}

/** 夜主的弹幕 */
export interface Foe {
  x: number;
  y: number;
  px: number;
  py: number;
  vx: number;
  vy: number;
  r: number;
  dmg: number;
  life: number;
}

export interface PlanStep {
  at: number;
  kind: 'elite' | 'surge' | 'boss';
  pool: ('fox' | 'ghoul' | 'stonelord')[];
  done: boolean;
}

export const BLAST_CAP = 256;

/** 本步排队的连锁爆炸（火·焚、水·凝 6 点） */
export interface Blasts {
  n: number;
  x: Float32Array;
  y: Float32Array;
  r: Float32Array;
  dmg: Float32Array;
  /** 0 = 火，1 = 冰 */
  kind: Uint8Array;
}

export interface World {
  readonly seed: number;
  readonly rng: Streams;
  phase: Phase;
  t: number;
  tick: number;
  /** 可见范围（世界单位），由画面层通过 setView 传入 */
  view: { w: number; h: number };
  readonly mods: Mods;
  readonly meta: MetaLevels;
  player: Player;
  readonly enemies: Enemies;
  readonly grid: SpatialGrid;
  readonly gems: Gems;
  readonly shots: Shots;
  weapons: WeaponState[];
  passives: PassiveState[];
  res: Record<ElementId, number>;
  tier: Record<ElementId, number>;
  sheng: Record<string, boolean>;
  taiji: boolean;
  taijiT: number;
  stats: Stats;
  kills: number;
  xp: number;
  level: number;
  pendingLevels: number;
  rerolls: number;
  choice: Choice | null;
  chestQueue: number;
  chest: ChestReveal | null;
  pendingEvos: WeaponId[];
  /** 正在演出的进化 */
  evo: WeaponId | null;
  evolutions: number;
  seals: SealWarn[];
  zones: Zone[];
  pickups: Pickup[];
  foes: Foe[];
  readonly blasts: Blasts;
  plan: PlanStep[];
  /** 本局妖群组成：疾影、石妖的比例 */
  mix: { wisp: number; golem: number };
  nextPack: number;
  surgeT: number;
  chestRainT: number;
  /** 夜主的句柄，-1 表示不在场 */
  boss: number;
  wonAt: number;
  /** 结束时的结果 */
  over: { won: boolean } | null;
  /** 燃灯（大招）充能 0~1 */
  ult: number;
  combo: number;
  comboT: number;
  bestCombo: number;
  oilBonus: number;
  intensity: number;
  spawnAcc: number;
  /** 跑分模式：保持场上妖物数量，不升级；null 表示正常的一局 */
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
  mods?: Mods;
  meta?: MetaLevels;
}

const zeroRes = (): Record<ElementId, number> => Object.fromEntries(ELEMENT_IDS.map((e) => [e, 0])) as Record<ElementId, number>;

export function newWeapon(id: WeaponId): WeaponState {
  return { id, lv: 1, evo: false, t: 0.6, angle: 0, big: 6, count: 0, radius: 0, size: 0, cranes: [] };
}

export function createWorld(opts: WorldOptions): World {
  const view = opts.view ?? { w: (VIEW_HEIGHT * 16) / 9, h: VIEW_HEIGHT };
  const rng = createStreams(opts.seed);
  const meta = opts.meta ?? NO_META;
  const r = rng.run;
  const w: World = {
    seed: opts.seed,
    rng,
    phase: 'play',
    t: 0,
    tick: 0,
    view,
    mods: opts.mods ?? baseMods(),
    meta,
    player: {
      x: 0,
      y: 0,
      px: 0,
      py: 0,
      r: PLAYER.radius,
      hp: PLAYER.maxHp,
      faceX: 1,
      faceY: 0,
      moving: false,
      moved: 0,
      iframe: 0,
      dashT: 0,
      dashCd: 0,
      dashVX: 0,
      dashVY: 0,
      shield: 0,
      shieldMax: 0,
      shieldT: 0,
    },
    enemies: new Enemies(),
    grid: new SpatialGrid(),
    gems: new Gems(),
    shots: new Shots(),
    weapons: [newWeapon('lamp')],
    passives: [],
    res: zeroRes(),
    tier: zeroRes(),
    sheng: {},
    taiji: false,
    taijiT: 0,
    stats: {
      area: 1,
      dmg: 1,
      critChance: 0.05,
      critMult: 2,
      cd: 1,
      magnet: PLAYER.magnet,
      amount: 0,
      speed: PLAYER.speed,
      maxHp: PLAYER.maxHp,
      armor: 0,
      taken: 1,
      regen: 0,
      burnMult: 1,
      shieldCd: 10,
      kb: 1,
    },
    kills: 0,
    xp: 0,
    level: 1,
    pendingLevels: 0,
    rerolls: 2 + meta.luck,
    choice: null,
    chestQueue: 0,
    chest: null,
    pendingEvos: [],
    evo: null,
    evolutions: 0,
    seals: [],
    zones: [],
    pickups: [],
    foes: [],
    blasts: {
      n: 0,
      x: new Float32Array(BLAST_CAP),
      y: new Float32Array(BLAST_CAP),
      r: new Float32Array(BLAST_CAP),
      dmg: new Float32Array(BLAST_CAP),
      kind: new Uint8Array(BLAST_CAP),
    },
    // 精英与妖潮的出场时间、种类每局随机（旧版 makePlan）
    plan: [
      { at: r.range(150, 200), kind: 'elite', pool: ['fox', 'stonelord'], done: false },
      { at: r.range(270, 320), kind: 'elite', pool: ['ghoul', 'stonelord', 'fox'], done: false },
      { at: r.range(370, 420), kind: 'elite', pool: ['fox', 'ghoul', 'stonelord'], done: false },
      { at: r.range(450, 500), kind: 'surge', pool: ['fox', 'ghoul', 'stonelord'], done: false },
      { at: 570, kind: 'boss', pool: [], done: false },
    ],
    mix: { wisp: r.range(0.08, 0.3), golem: r.range(0.05, 0.2) },
    nextPack: 40,
    surgeT: 0,
    chestRainT: 100,
    boss: -1,
    wonAt: -1,
    over: null,
    ult: 0,
    combo: 0,
    comboT: 0,
    bestCombo: 0,
    oilBonus: 0,
    intensity: -1,
    spawnAcc: 0,
    benchTarget: opts.benchTarget ?? null,
    god: opts.god ?? false,
    bus: new EventBus(),
    fx: new FxQueue(),
    commands: [],
    scratch: { ids: new Int32Array(2048), near: new Int32Array(32), d2: new Float64Array(32) },
  };
  return w;
}

/** 视口对角线的一半（世界单位），对应旧版 viewRadius()。 */
export const viewRadius = (w: World): number => Math.hypot(w.view.w, w.view.h) / 2;

/** 是否在屏幕内（对应旧版 onScreen） */
export const onScreen = (w: World, x: number, y: number, margin = 30): boolean =>
  Math.abs(x - w.player.x) < w.view.w / 2 + margin && Math.abs(y - w.player.y) < w.view.h / 2 + margin;

export function setView(w: World, width: number, height: number): void {
  w.view.w = width;
  w.view.h = height;
}

export const getWeapon = (w: World, id: WeaponId): WeaponState | undefined => w.weapons.find((x) => x.id === id);
export const getPassive = (w: World, id: PassiveId): PassiveState | undefined => w.passives.find((x) => x.id === id);
export const plv = (w: World, id: PassiveId): number => getPassive(w, id)?.lv ?? 0;

/** 状态摘要：用于验证同一种子、同样输入能得到完全相同的结果。 */
export function stateHash(w: World): number {
  let h = 0x811c9dc5;
  const mix = (v: number) => {
    h = Math.imul(h ^ ((Math.fround(v) * 1000) | 0), 0x01000193);
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
  mix(w.level);
  for (const wp of w.weapons) {
    mix(wp.lv);
    mix(wp.evo ? 1 : 0);
  }
  for (const p of w.passives) mix(p.lv);
  for (const r of Object.values(w.rng)) mix(r.state);
  return h >>> 0;
}
