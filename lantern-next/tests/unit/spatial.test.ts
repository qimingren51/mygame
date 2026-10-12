import { describe, expect, it } from 'vitest';
import { Rng } from '../../src/core/rng';
import { Enemies } from '../../src/sim/enemies';
import { SpatialGrid } from '../../src/sim/spatial';

function scatter(en: Enemies, rng: Rng, n: number, spread: number) {
  for (let k = 0; k < n; k++) {
    const i = en.alloc();
    en.x[i] = rng.range(-spread, spread);
    en.y[i] = rng.range(-spread, spread);
    en.r[i] = rng.pick([10, 13, 19, 24, 30, 44]);
  }
  // 杀掉一部分，确认会跳过死亡的槽位
  for (let i = 0; i < en.hi; i += 7) en.kill(i);
}

describe('SpatialGrid', () => {
  const rng = new Rng(2024);
  const en = new Enemies();
  scatter(en, rng, 1500, 900);
  const grid = new SpatialGrid();
  grid.build(en, 30, -20, 800, 800);
  const out = new Int32Array(2048);

  it('queryCircle 与暴力查找结果一致', () => {
    for (let q = 0; q < 2000; q++) {
      const x = rng.range(-700, 700);
      const y = rng.range(-700, 700);
      const r = rng.range(0, 160);
      const n = grid.queryCircle(en, x, y, r, out);
      const got = Array.from(out.subarray(0, n)).sort((a, b) => a - b);
      const want: number[] = [];
      for (let i = 0; i < en.hi; i++) {
        if (!en.alive[i]) continue;
        const dx = (en.x[i] as number) - x;
        const dy = (en.y[i] as number) - y;
        const rr = r + (en.r[i] as number);
        if (dx * dx + dy * dy <= rr * rr) want.push(i);
      }
      expect(got).toEqual(want);
    }
  });

  it('nearestK 与按距离排序的暴力结果一致', () => {
    const d2 = new Float64Array(16);
    for (let q = 0; q < 500; q++) {
      const x = rng.range(-600, 600);
      const y = rng.range(-600, 600);
      const range = rng.range(50, 460);
      const k = 1 + rng.int(12);
      const n = grid.nearestK(en, x, y, range, k, out, d2);
      const cand: [number, number][] = [];
      for (let i = 0; i < en.hi; i++) {
        if (!en.alive[i]) continue;
        const dx = (en.x[i] as number) - x;
        const dy = (en.y[i] as number) - y;
        const dd = dx * dx + dy * dy;
        if (dd <= range * range) cand.push([dd, i]);
      }
      cand.sort((a, b) => a[0] - b[0]);
      const want = cand.slice(0, k).map((c) => c[0]);
      const got = Array.from(out.subarray(0, n)).map((i) => {
        const dx = (en.x[i] as number) - x;
        const dy = (en.y[i] as number) - y;
        return dx * dx + dy * dy;
      });
      expect(got).toEqual(want);
    }
  });
});

describe('Enemies', () => {
  it('句柄在槽位复用后失效', () => {
    const en = new Enemies();
    const i = en.alloc();
    const h = en.handle(i);
    expect(en.resolve(h)).toBe(i);
    en.kill(i);
    expect(en.resolve(h)).toBe(-1);
    const j = en.alloc();
    expect(j).toBe(i); // 槽位被复用
    expect(en.resolve(h)).toBe(-1); // 旧句柄仍然无效
    expect(en.resolve(en.handle(j))).toBe(j);
    expect(en.count).toBe(1);
  });
});
