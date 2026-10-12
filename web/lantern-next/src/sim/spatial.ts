// 空间网格：以玩家为中心的均匀网格，用计数排序一次建好，零分配。
// 语义与旧版 queryEnemies / nearestEnemies 保持一致：
// 查询“圆心在 (x, y)、半径 r 的圆”接触到的妖物（判定距离为 r + 妖物半径）。

import type { Enemies } from './enemies';
import { ENEMY_CAP } from './enemies';

export const CELL = 64;
/** 妖物的最大半径；查询时多扫这么远，保证不漏掉大体型妖物 */
const MAX_ENEMY_R = 48;
const MAX_COLS = 96;
const MAX_ROWS = 96;

export class SpatialGrid {
  cols = 1;
  rows = 1;
  /** 网格左上角的世界坐标 */
  ox = 0;
  oy = 0;

  /** 第 c 个格子里的妖物是 items[start[c] .. start[c+1]) */
  readonly start = new Int32Array(MAX_COLS * MAX_ROWS + 1);
  readonly items = new Int32Array(ENEMY_CAP);
  /** 建网格时每只妖物所在的格子 */
  readonly cellOf = new Int32Array(ENEMY_CAP);
  private readonly count = new Int32Array(MAX_COLS * MAX_ROWS);

  /** 以 (cx, cy) 为中心、半宽 hw、半高 hh 建网格；超出范围的妖物归到边缘格子。 */
  build(en: Enemies, cx: number, cy: number, hw: number, hh: number): void {
    this.cols = Math.min(MAX_COLS, Math.ceil((hw * 2) / CELL) + 1);
    this.rows = Math.min(MAX_ROWS, Math.ceil((hh * 2) / CELL) + 1);
    this.ox = Math.floor((cx - hw) / CELL) * CELL;
    this.oy = Math.floor((cy - hh) / CELL) * CELL;
    const n = this.cols * this.rows;
    const count = this.count;
    count.fill(0, 0, n);

    for (let i = 0; i < en.hi; i++) {
      if (!en.alive[i]) continue;
      const c = this.cellIndex(en.x[i] as number, en.y[i] as number);
      this.cellOf[i] = c;
      count[c] = (count[c] as number) + 1;
    }
    const start = this.start;
    let acc = 0;
    for (let c = 0; c < n; c++) {
      start[c] = acc;
      acc += count[c] as number;
      count[c] = 0;
    }
    start[n] = acc;
    for (let i = 0; i < en.hi; i++) {
      if (!en.alive[i]) continue;
      const c = this.cellOf[i] as number;
      this.items[(start[c] as number) + (count[c] as number)] = i;
      count[c] = (count[c] as number) + 1;
    }
  }

  private col(x: number): number {
    const c = Math.floor((x - this.ox) / CELL);
    return c < 0 ? 0 : c >= this.cols ? this.cols - 1 : c;
  }

  private row(y: number): number {
    const r = Math.floor((y - this.oy) / CELL);
    return r < 0 ? 0 : r >= this.rows ? this.rows - 1 : r;
  }

  cellIndex(x: number, y: number): number {
    return this.row(y) * this.cols + this.col(x);
  }

  /** 把接触到圆 (x, y, r) 的妖物槽位写进 out，返回数量。 */
  queryCircle(en: Enemies, x: number, y: number, r: number, out: Int32Array): number {
    const reach = r + MAX_ENEMY_R;
    const c0 = this.col(x - reach);
    const c1 = this.col(x + reach);
    const r0 = this.row(y - reach);
    const r1 = this.row(y + reach);
    let n = 0;
    for (let row = r0; row <= r1; row++) {
      for (let col = c0; col <= c1; col++) {
        const c = row * this.cols + col;
        const end = this.start[c + 1] as number;
        for (let k = this.start[c] as number; k < end; k++) {
          const i = this.items[k] as number;
          if (!en.alive[i]) continue;
          const dx = (en.x[i] as number) - x;
          const dy = (en.y[i] as number) - y;
          const rr = r + (en.r[i] as number);
          if (dx * dx + dy * dy <= rr * rr && n < out.length) out[n++] = i;
        }
      }
    }
    return n;
  }

  /** 距离 (x, y) 最近、且在 range 以内的 k 只妖物，按距离从近到远写进 out。 */
  nearestK(en: Enemies, x: number, y: number, range: number, k: number, out: Int32Array, scratch: Float64Array): number {
    const c0 = this.col(x - range);
    const c1 = this.col(x + range);
    const r0 = this.row(y - range);
    const r1 = this.row(y + range);
    const range2 = range * range;
    let n = 0;
    for (let row = r0; row <= r1; row++) {
      for (let col = c0; col <= c1; col++) {
        const c = row * this.cols + col;
        const end = this.start[c + 1] as number;
        for (let s = this.start[c] as number; s < end; s++) {
          const i = this.items[s] as number;
          if (!en.alive[i]) continue;
          const dx = (en.x[i] as number) - x;
          const dy = (en.y[i] as number) - y;
          const d2 = dx * dx + dy * dy;
          if (d2 > range2) continue;
          if (n === k && d2 >= (scratch[k - 1] as number)) continue;
          // 插入排序（k 很小）
          let j = n < k ? n++ : k - 1;
          while (j > 0 && (scratch[j - 1] as number) > d2) {
            scratch[j] = scratch[j - 1] as number;
            out[j] = out[j - 1] as number;
            j--;
          }
          scratch[j] = d2;
          out[j] = i;
        }
      }
    }
    return n;
  }
}
