// 高频特效事件（命中、击杀、伤害数字、拾取）。
// 每帧可能有上千条，所以用预先分配好的 Float32Array，不产生内存垃圾。

export const FX = {
  /** a = 伤害值，b = 标志位（FX_CRIT 等） */
  HIT: 1,
  /** a = 妖物类型编号，b = 1 表示精英 */
  KILL: 2,
  /** a = 魂火价值 */
  GEM_PICK: 3,
} as const;

export const FX_CRIT = 1;

const STRIDE = 5;

export class FxQueue {
  readonly capacity: number;
  private readonly buf: Float32Array;
  private n = 0;
  private dropped = 0;

  constructor(capacity = 4096) {
    this.capacity = capacity;
    this.buf = new Float32Array(capacity * STRIDE);
  }

  push(code: number, x: number, y: number, a = 0, b = 0): void {
    if (this.n >= this.capacity) {
      this.dropped++;
      return;
    }
    const o = this.n * STRIDE;
    this.buf[o] = code;
    this.buf[o + 1] = x;
    this.buf[o + 2] = y;
    this.buf[o + 3] = a;
    this.buf[o + 4] = b;
    this.n++;
  }

  get length(): number {
    return this.n;
  }

  /** 本帧因队列满而丢弃的条数。 */
  get droppedCount(): number {
    return this.dropped;
  }

  drain(handler: (code: number, x: number, y: number, a: number, b: number) => void): void {
    const buf = this.buf;
    for (let i = 0; i < this.n; i++) {
      const o = i * STRIDE;
      handler(buf[o] as number, buf[o + 1] as number, buf[o + 2] as number, buf[o + 3] as number, buf[o + 4] as number);
    }
    this.n = 0;
    this.dropped = 0;
  }

  clear(): void {
    this.n = 0;
    this.dropped = 0;
  }
}
