// 可复现的随机数。
// 一局用一个种子，再按用途派生出互相独立的随机流：
// 改动某一处的随机调用（例如多抽一次升级选项）不会影响刷怪等其他流程。

/** mulberry32，与旧版 seeded() 相同的算法。 */
export class Rng {
  private s: number;

  constructor(seed: number) {
    this.s = seed | 0;
  }

  /** [0, 1) */
  next(): number {
    this.s = (this.s + 0x6d2b79f5) | 0;
    let t = Math.imul(this.s ^ (this.s >>> 15), 1 | this.s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** [a, b) */
  range(a: number, b: number): number {
    return a + this.next() * (b - a);
  }

  /** [0, n) 的整数 */
  int(n: number): number {
    return Math.floor(this.next() * n);
  }

  chance(p: number): boolean {
    return this.next() < p;
  }

  pick<T>(arr: readonly T[]): T {
    return arr[this.int(arr.length)] as T;
  }

  /** 当前内部状态，用于快照和比对。 */
  get state(): number {
    return this.s;
  }
}

function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function splitmix32(x: number): number {
  x = (x + 0x9e3779b9) | 0;
  x = Math.imul(x ^ (x >>> 16), 0x85ebca6b);
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35);
  return (x ^ (x >>> 16)) >>> 0;
}

/** 由一局的种子和用途名派生出该用途的种子。 */
export function deriveSeed(runSeed: number, name: string): number {
  return splitmix32((runSeed ^ fnv1a(name)) | 0);
}

export const STREAMS = ['omen', 'run', 'spawn', 'combat', 'loot', 'events', 'choices', 'chest'] as const;
export type StreamName = (typeof STREAMS)[number];
export type Streams = Record<StreamName, Rng>;

export function createStreams(runSeed: number): Streams {
  const out = {} as Streams;
  for (const name of STREAMS) out[name] = new Rng(deriveSeed(runSeed, name));
  return out;
}

/** 生成新的一局种子（只在界面层调用，模拟内部不使用）。 */
export function randomSeed(): number {
  const buf = new Uint32Array(1);
  globalThis.crypto.getRandomValues(buf);
  return buf[0] as number;
}
