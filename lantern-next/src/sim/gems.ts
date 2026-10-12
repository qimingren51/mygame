// 魂火（经验）：按字段分数组存储，删除时用末尾元素填补空位。

import { GEM_CAP } from '../data/balance';

export const GEM_CAPACITY = 512;

export class Gems {
  readonly x = new Float32Array(GEM_CAPACITY);
  readonly y = new Float32Array(GEM_CAPACITY);
  readonly px = new Float32Array(GEM_CAPACITY);
  readonly py = new Float32Array(GEM_CAPACITY);
  readonly v = new Float32Array(GEM_CAPACITY);
  readonly vx = new Float32Array(GEM_CAPACITY);
  readonly vy = new Float32Array(GEM_CAPACITY);
  readonly age = new Float32Array(GEM_CAPACITY);
  readonly pulled = new Uint8Array(GEM_CAPACITY);
  n = 0;

  /** 掉落一颗魂火；超过上限时并入最近的一颗，避免卡顿（与旧版一致）。 */
  drop(x: number, y: number, value: number): void {
    if (this.n > GEM_CAP) {
      let near = 0;
      let nd = Infinity;
      for (let i = 0; i < this.n; i++) {
        const dx = (this.x[i] as number) - x;
        const dy = (this.y[i] as number) - y;
        const d = dx * dx + dy * dy;
        if (d < nd) {
          nd = d;
          near = i;
        }
      }
      this.v[near] = (this.v[near] as number) + value;
      return;
    }
    const i = this.n++;
    this.x[i] = x;
    this.y[i] = y;
    this.px[i] = x;
    this.py[i] = y;
    this.v[i] = value;
    this.vx[i] = 0;
    this.vy[i] = 0;
    this.age[i] = 0;
    this.pulled[i] = 0;
  }

  remove(i: number): void {
    const last = --this.n;
    if (i === last) return;
    this.x[i] = this.x[last] as number;
    this.y[i] = this.y[last] as number;
    this.px[i] = this.px[last] as number;
    this.py[i] = this.py[last] as number;
    this.v[i] = this.v[last] as number;
    this.vx[i] = this.vx[last] as number;
    this.vy[i] = this.vy[last] as number;
    this.age[i] = this.age[last] as number;
    this.pulled[i] = this.pulled[last] as number;
  }

  clear(): void {
    this.n = 0;
  }
}
