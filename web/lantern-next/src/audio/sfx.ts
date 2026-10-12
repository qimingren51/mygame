// 音效（移植自旧版 audio.js 的 sfx）。每个函数都可以随时调用：音频未解锁或已关闭时什么也不做。

import { bell, drum, getGraph, gong, noise, osc, pent, pluck, settings, wood, type Graph } from './engine';

const lastPlayed: Record<string, number> = {};

function ready(): Graph | null {
  const g = getGraph();
  return g && settings.sfx && g.ctx.state === 'running' ? g : null;
}

/** 同名音效的最短间隔，避免一帧几十次命中叠成噪音 */
function can(g: Graph, name: string, gap: number): boolean {
  const now = g.ctx.currentTime;
  const last = lastPlayed[name];
  if (last !== undefined && now - last < gap) return false;
  lastPlayed[name] = now;
  return true;
}

let gemChain = 0;
let gemLast = 0;

export const sfx = {
  click(): void {
    const g = ready();
    if (!g) return;
    wood(g, g.ctx.currentTime, 0.12, g.sfxBus, 1300);
  },
  hit(): void {
    const g = ready();
    if (!g || !can(g, 'hit', 0.045)) return;
    noise(g, g.ctx.currentTime, 0.035, 0.07, g.sfxBus, { type: 'highpass', freq: 2500 + Math.random() * 1800 });
  },
  kill(): void {
    const g = ready();
    if (!g || !can(g, 'kill', 0.04)) return;
    osc(g, 'sine', 240 + Math.random() * 90, g.ctx.currentTime, 0.12, 0.1, g.sfxBus, { slide: 85 });
  },
  gem(): void {
    const g = ready();
    if (!g || !can(g, 'gem', 0.05)) return;
    const t = g.ctx.currentTime;
    if (t - gemLast > 0.6) gemChain = 0;
    gemLast = t;
    // 连续拾取时音高一路爬升
    const f = pent(10 + (gemChain++ % 12));
    osc(g, 'sine', f, t, 0.18, 0.06, g.sfxBus);
    osc(g, 'triangle', f * 2, t, 0.08, 0.025, g.sfxBus);
  },
  levelUp(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    [10, 12, 13, 15, 17].forEach((d, i) => pluck(g, pent(d), t + i * 0.06, 0.16, g.sfxBus, 0.9));
    bell(g, pent(20), t + 0.32, 0.08, g.sfxBus, 1.6);
  },
  select(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    pluck(g, pent(12), t, 0.18, g.sfxBus, 0.8);
    pluck(g, pent(15), t + 0.05, 0.14, g.sfxBus, 0.8);
  },
  chest(n: number): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    for (let i = 0; i < 6; i++) wood(g, t + i * 0.045 * (1 - i * 0.08), 0.1, g.sfxBus, 700 + i * 60);
    for (let i = 0; i < n; i++) bell(g, pent(12 + i * 2), t + 0.15 + i * 0.28 + 0.2, 0.14, g.sfxBus, 1.4);
  },
  evolution(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    gong(g, 73.4, t, 0.32, g.sfxBus);
    drum(g, t, 0.6, g.sfxBus, 90);
    [5, 7, 10, 12, 15, 17, 20].forEach((d, i) => pluck(g, pent(d), t + 0.1 + i * 0.07, 0.15, g.sfxBus, 1));
    bell(g, pent(22), t + 0.7, 0.12, g.sfxBus, 2.5);
  },
  resonance(): void {
    const g = ready();
    if (!g || !can(g, 'res', 0.3)) return;
    const t = g.ctx.currentTime;
    [12, 15, 17].forEach((d, i) => pluck(g, pent(d), t + i * 0.08, 0.13, g.sfxBus, 1));
    bell(g, pent(19), t + 0.24, 0.07, g.sfxBus, 1.5);
  },
  ult(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    noise(g, t, 0.4, 0.25, g.sfxBus, { type: 'highpass', freq: 400, slide: 5000, attack: 0.3 });
    drum(g, t + 0.33, 0.9, g.sfxBus, 70);
    noise(g, t + 0.33, 0.9, 0.3, g.sfxBus, { type: 'lowpass', freq: 900, slide: 120 });
    gong(g, 55, t + 0.33, 0.22, g.sfxBus);
  },
  dash(): void {
    const g = ready();
    if (!g) return;
    noise(g, g.ctx.currentTime, 0.18, 0.14, g.sfxBus, { freq: 700, slide: 3200, q: 1.4 });
  },
  hurt(): void {
    const g = ready();
    if (!g || !can(g, 'hurt', 0.2)) return;
    const t = g.ctx.currentTime;
    osc(g, 'sine', 190, t, 0.25, 0.28, g.sfxBus, { slide: 60 });
    noise(g, t, 0.12, 0.15, g.sfxBus, { type: 'lowpass', freq: 600 });
  },
  sword(): void {
    const g = ready();
    if (!g || !can(g, 'sword', 0.1)) return;
    noise(g, g.ctx.currentTime, 0.07, 0.045, g.sfxBus, { type: 'highpass', freq: 4500, slide: 7000 });
  },
  bellPulse(): void {
    const g = ready();
    if (!g || !can(g, 'bellp', 0.4)) return;
    bell(g, pent(15), g.ctx.currentTime, 0.06, g.sfxBus, 1.1);
  },
  bigBell(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    bell(g, pent(5), t, 0.22, g.sfxBus, 3);
    bell(g, pent(10), t + 0.02, 0.12, g.sfxBus, 2.5);
  },
  seal(): void {
    const g = ready();
    if (!g || !can(g, 'seal', 0.12)) return;
    drum(g, g.ctx.currentTime, 0.22, g.sfxBus, 95);
  },
  blast(): void {
    const g = ready();
    if (!g || !can(g, 'blast', 0.09)) return;
    const t = g.ctx.currentTime;
    osc(g, 'sine', 130, t, 0.2, 0.1, g.sfxBus, { slide: 50 });
    noise(g, t, 0.15, 0.07, g.sfxBus, { type: 'lowpass', freq: 900 });
  },
  warn(big: boolean): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    const n = big ? 3 : 2;
    for (let i = 0; i < n; i++) drum(g, t + i * 0.24, 0.55, g.sfxBus, big ? 75 : 95);
    if (big) gong(g, 49, t + 0.72, 0.28, g.sfxBus);
  },
  soulBell(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    for (let i = 0; i < 8; i++) bell(g, pent(12 + i), t + i * 0.045, 0.06, g.sfxBus, 0.9);
  },
  heal(): void {
    const g = ready();
    if (!g || !can(g, 'heal', 0.5)) return;
    const t = g.ctx.currentTime;
    bell(g, pent(14), t, 0.1, g.sfxBus, 1.2);
    bell(g, pent(17), t + 0.08, 0.08, g.sfxBus, 1.2);
  },
  combo(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    bell(g, pent(17), t, 0.1, g.sfxBus, 1);
    bell(g, pent(20), t + 0.06, 0.08, g.sfxBus, 1.2);
  },
  event(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    bell(g, pent(13), t, 0.12, g.sfxBus, 1.6);
    bell(g, pent(16), t + 0.18, 0.1, g.sfxBus, 1.8);
  },
  coins(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime;
    for (let i = 0; i < 10; i++) osc(g, 'sine', pent(15 + (i % 5)) * 2, t + i * 0.035, 0.12, 0.05, g.sfxBus);
  },
  victory(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime + 0.1;
    const notes: [number, number][] = [[10, 0], [12, 0.25], [14, 0.5], [17, 0.75], [15, 1.1], [14, 1.35], [12, 1.6], [15, 1.85], [20, 2.3]];
    for (const [d, at] of notes) pluck(g, pent(d), t + at, 0.18, g.sfxBus, 1.4);
    gong(g, 73.4, t + 2.3, 0.2, g.sfxBus);
  },
  defeat(): void {
    const g = ready();
    if (!g) return;
    const t = g.ctx.currentTime + 0.1;
    const notes: [number, number][] = [[14, 0], [12, 0.45], [11, 0.9], [9, 1.35], [5, 1.9]];
    for (const [d, at] of notes) pluck(g, pent(d), t + at, 0.16, g.sfxBus, 1.8);
    drum(g, t + 1.9, 0.3, g.sfxBus, 70);
  },
};
