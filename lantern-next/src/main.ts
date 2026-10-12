// 入口：创建画布、世界和画面，跑自己的 requestAnimationFrame 循环。
// 里程碑 1 的技术验证：直接进入光照 + 千只妖物的场景。

import { Application } from 'pixi.js';
import { FixedStep } from './core/loop';
import { clamp } from './core/math';
import { randomSeed } from './core/rng';
import { Input } from './platform/input';
import { loadArt } from './render/atlas';
import { Presenter } from './render/presenter';
import { QualityScaler, type BloomMode, type QualityLocks } from './render/quality';
import { createWorld } from './sim/state';
import { step } from './sim/step';
import './ui/style.css';

const params = new URLSearchParams(location.search);
const num = (k: string): number | undefined => {
  const v = params.get(k);
  if (v === null || v === '') return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
};
const bloomParam = params.get('bloom');
const isBloom = (v: string | null): v is BloomMode => v === 'off' || v === 'baked' || v === 'filter';

async function boot(): Promise<void> {
  const build = document.getElementById('build');
  if (build) build.textContent = `构建 ${__BUILD_ID__}`;
  const host = document.getElementById('game') as HTMLElement;

  const maxRes = Math.min(window.devicePixelRatio || 1, 2);
  const locks: QualityLocks = {};
  const resLock = num('res');
  if (resLock !== undefined) locks.res = clamp(resLock, 0.5, 3);
  const lsLock = num('ls');
  if (lsLock !== undefined) locks.ls = clamp(lsLock, 0.125, 1);
  if (isBloom(bloomParam)) locks.bloom = bloomParam;
  const quality = new QualityScaler(maxRes, 'baked', locks);

  const app = new Application();
  await app.init({
    preference: 'webgl',
    antialias: false,
    autoDensity: true,
    resolution: quality.current.res,
    width: host.clientWidth || innerWidth,
    height: host.clientHeight || innerHeight,
    backgroundColor: 0x161b2c,
    autoStart: false,
    sharedTicker: false,
    powerPreference: 'high-performance',
  });
  host.appendChild(app.canvas);

  const seed = num('seed') ?? randomSeed();
  const bench = num('enemies');
  const world = createWorld({ seed, benchTarget: bench === undefined ? 1000 : clamp(Math.round(bench), 0, 2000), god: true });
  const { art, report } = await loadArt();
  if (report.errors.length) console.warn('图集加载问题：', report.errors);
  const presenter = new Presenter(art, {
    actors: params.get('actors') === 'A' ? 'A' : 'B',
    maxLights: clamp(num('lights') ?? 300, 1, 2000),
    gemLights: 200,
  });
  const input = new Input(host);
  input.auto = params.get('auto') === '1';
  const loop = new FixedStep();

  let cssW = 0;
  let cssH = 0;
  const fit = (force: boolean) => {
    const w = host.clientWidth || innerWidth;
    const h = host.clientHeight || innerHeight;
    if (!force && w === cssW && h === cssH) return;
    cssW = w;
    cssH = h;
    presenter.resize(app.renderer, cssW, cssH, quality.current, world);
  };
  fit(true);

  // WebGL 上下文丢失（iOS 切后台、内存紧张时会发生）：暂停，恢复后继续
  let lost = false;
  app.canvas.addEventListener('webglcontextlost', () => (lost = true));
  app.canvas.addEventListener('webglcontextrestored', () => {
    lost = false;
    fit(true);
  });

  const hud = document.getElementById('perf');
  let hudT = 0;
  let frames = 0;
  let worst = 0;
  let last = performance.now();
  const tick = (now: number) => {
    requestAnimationFrame(tick);
    // rAF 的时间戳可能早于上一次 performance.now()，第一帧会得到负数
    const dtMs = Math.max(0, now - last);
    last = now;
    if (lost) return;
    fit(false);
    if (quality.sample(dtMs)) fit(true);
    const dt = Math.min(dtMs / 1000, 0.1);
    const alpha = loop.advance(dt, (sdt) => {
      input.flushCommands(world.commands);
      step(world, sdt, input.sample(sdt));
    });
    presenter.frame(app.renderer, world, alpha, dt);

    frames++;
    hudT += dtMs;
    worst = Math.max(worst, dtMs);
    if (hud && hudT >= 500) {
      const q = quality.current;
      const s = presenter.stats;
      hud.textContent =
        `${Math.round((frames * 1000) / hudT)} fps  最慢 ${worst.toFixed(0)}ms  妖 ${world.enemies.count}  ` +
        `光 ${s.lights}  辉 ${s.glow}  分辨率 ${q.res}  光照 ${q.ls}  辉光 ${q.bloom}`;
      hudT = 0;
      frames = 0;
      worst = 0;
    }
  };
  requestAnimationFrame(tick);

  // 调试接口（Playwright 和手动调试用）
  (window as unknown as { __lantern: unknown }).__lantern = { app, world, presenter, quality, input, loop, artReport: report };
}

boot().catch((err: unknown) => {
  console.error(err);
  const el = document.getElementById('fatal');
  if (el) {
    el.textContent = `启动失败：${err instanceof Error ? err.message : String(err)}`;
    el.hidden = false;
  }
});
