import { describe, expect, it } from 'vitest';
import { Rng, createStreams, deriveSeed } from '../../src/core/rng';

// 旧版 game.js 里的 seeded()，用来确认算法完全一致
function oldSeeded(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe('Rng', () => {
  it('与旧版 seeded() 输出完全一致', () => {
    for (const seed of [0, 1, 42, 123456789, 0xdeadbeef]) {
      const a = new Rng(seed);
      const b = oldSeeded(seed | 0);
      for (let i = 0; i < 100; i++) expect(a.next()).toBe(b());
    }
  });

  it('range、int、chance 落在正确区间', () => {
    const r = new Rng(7);
    for (let i = 0; i < 1000; i++) {
      const v = r.range(-3, 5);
      expect(v).toBeGreaterThanOrEqual(-3);
      expect(v).toBeLessThan(5);
      const n = r.int(6);
      expect(Number.isInteger(n) && n >= 0 && n < 6).toBe(true);
    }
  });

  it('派生种子稳定，且不同用途互不相同', () => {
    expect(deriveSeed(12345, 'spawn')).toBe(deriveSeed(12345, 'spawn'));
    expect(deriveSeed(12345, 'spawn')).not.toBe(deriveSeed(12345, 'combat'));
    expect(deriveSeed(12345, 'spawn')).not.toBe(deriveSeed(12346, 'spawn'));
  });

  it('各随机流互相独立：多用一次某个流不影响其他流', () => {
    const a = createStreams(99);
    const b = createStreams(99);
    a.combat.next();
    a.combat.next();
    for (let i = 0; i < 20; i++) expect(a.spawn.next()).toBe(b.spawn.next());
  });
});
