import { describe, expect, it } from 'vitest';
import { SIM_DT } from '../../src/core/loop';
import { createWorld, stateHash, type InputFrame, type World } from '../../src/sim/state';
import { step } from '../../src/sim/step';

/** 固定的输入脚本：绕大圈走，每 2 秒闪避一次 */
function run(seed: number, seconds: number, bench: number | null = null): World {
  const w = createWorld({ seed, benchTarget: bench });
  const input: InputFrame = { mx: 0, my: 0 };
  const steps = Math.round(seconds / SIM_DT);
  for (let s = 0; s < steps; s++) {
    const a = s * 0.01;
    input.mx = Math.cos(a);
    input.my = Math.sin(a);
    if (s % 120 === 0) w.commands.push({ k: 'dash' });
    step(w, SIM_DT, input);
    w.bus.clear();
    w.fx.clear();
  }
  return w;
}

describe('固定种子复现', () => {
  it('同一种子、同样输入，3 分钟后状态完全相同', () => {
    const a = run(20261012, 180);
    const b = run(20261012, 180);
    expect(a.kills).toBeGreaterThan(50);
    expect(stateHash(a)).toBe(stateHash(b));
  });

  it('不同种子得到不同结果', () => {
    expect(stateHash(run(1, 60))).not.toBe(stateHash(run(2, 60)));
  });

  it('跑分模式保持目标数量的妖物', () => {
    const w = run(7, 5, 1000);
    expect(w.enemies.count).toBeGreaterThanOrEqual(940);
    expect(w.enemies.count).toBeLessThanOrEqual(1000);
  });

  it('长时间运行不出现 NaN', () => {
    const w = run(3, 120, 600);
    const en = w.enemies;
    for (let i = 0; i < en.hi; i++) {
      if (!en.alive[i]) continue;
      expect(Number.isFinite(en.x[i] as number) && Number.isFinite(en.y[i] as number)).toBe(true);
    }
    expect(Number.isFinite(w.player.x)).toBe(true);
  });
});
