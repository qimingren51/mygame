// 模拟性能基准：npm run bench（设置 PERF=1 时才运行，平时的 npm test 会跳过）
// 目标（在构建容器上）：1000 只妖物每步 ≤ 3 ms，2000 只 ≤ 6 ms。

import { describe, expect, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { createWorld } from '../../src/sim/state';
import { step } from '../../src/sim/step';

const TARGET_MS: Record<number, number> = { 1000: 3, 2000: 6 };

describe.skipIf(!process.env.PERF)('模拟性能', () => {
  for (const n of [1000, 2000]) {
    it(`${n} 只妖物`, () => {
      const w = createWorld({ seed: 5, benchTarget: n, god: true });
      const input = { mx: 0, my: 0 };
      const tick = (s: number) => {
        input.mx = Math.cos(s * 0.01);
        input.my = Math.sin(s * 0.01);
        step(w, SIM_DT, input);
        w.fx.clear();
        w.bus.clear();
      };
      // 先跑 5 秒，让妖物聚到玩家周围，也让 JIT 预热
      for (let s = 0; s < 300; s++) tick(s);
      const samples: number[] = [];
      for (let s = 0; s < 600; s++) {
        const t0 = performance.now();
        tick(300 + s);
        samples.push(performance.now() - t0);
      }
      samples.sort((a, b) => a - b);
      const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
      const p95 = samples[Math.floor(samples.length * 0.95)] as number;
      console.log(`${n} 只妖物：平均 ${avg.toFixed(2)} ms/步，p95 ${p95.toFixed(2)} ms，场上 ${w.enemies.count} 只`);
      expect(avg).toBeLessThanOrEqual(TARGET_MS[n] as number);
    });
  }
});
