// 入口：创建画布、世界和画面，跑自己的 requestAnimationFrame 循环。
// 里程碑 1 的技术验证：标题界面后面一直跑着光照 + 千只妖物的场景；
// “开始测试”交给玩家操作，“跑分”按固定流程测帧率。

import { Application } from 'pixi.js';
import { onFx, onSimEvent } from './audio/bindings';
import { installUnlock, unlock } from './audio/engine';
import { setMusic } from './audio/music';
import { FixedStep } from './core/loop';
import { clamp } from './core/math';
import { randomSeed } from './core/rng';
import { isTouch } from './platform/fullscreen';
import { Input } from './platform/input';
import { loadArt } from './render/atlas';
import { Presenter } from './render/presenter';
import { QualityScaler, type BloomMode, type QualityLocks } from './render/quality';
import { createWorld, setView, type World } from './sim/state';
import { step } from './sim/step';
import { setupTitle } from './ui/title';
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
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

type Mode = 'title' | 'play' | 'bench';

async function boot(): Promise<void> {
  $('build').textContent = `构建 ${__BUILD_ID__}`;
  const host = $('game');
  installUnlock();

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

  const { art, report } = await loadArt();
  if (report.errors.length) console.warn('图集加载问题：', report.errors);
  const presenter = new Presenter(art, {
    actors: params.get('actors') === 'A' ? 'A' : 'B',
    maxLights: clamp(num('lights') ?? 300, 1, 2000),
    gemLights: 200,
  });
  presenter.listener = { event: onSimEvent, fx: onFx };
  const input = new Input(host);
  const loop = new FixedStep();
  const enemyTarget = clamp(Math.round(num('enemies') ?? 1000), 0, 2000);

  let mode: Mode = 'title';
  let world: World = newWorld(num('seed'));

  function newWorld(seed?: number): World {
    const w = createWorld({ seed: seed ?? randomSeed(), benchTarget: enemyTarget, god: true });
    setView(w, presenter.cam.viewW, presenter.cam.viewH);
    loop.reset();
    return w;
  }

  // ---- 界面
  const hud = $('hud');
  const perf = $('perf');
  perf.hidden = !(params.get('debug') === '1' || params.has('enemies'));
  const title = setupTitle({
    start: () => {
      world = newWorld(num('seed'));
      mode = 'play';
      input.auto = params.get('auto') === '1';
      input.enabled = true;
      title.hide();
      hud.hidden = false;
      setMusic('play');
    },
    bench: () => {
      // 跑分流程在 T10 补上；先进入自动行走的场景
      world = newWorld(12345);
      mode = 'bench';
      input.auto = true;
      input.enabled = false;
      title.hide();
      hud.hidden = false;
      perf.hidden = false;
      setMusic('play');
    },
  });
  const toTitle = () => {
    mode = 'title';
    input.auto = true;
    input.enabled = false;
    hud.hidden = true;
    title.show();
    setMusic('title');
  };
  $('back-btn').addEventListener('click', toTitle);
  addEventListener('keydown', (e) => {
    if (e.code === 'Escape' && mode !== 'title') toTitle();
  });
  const dashBtn = $('dash-btn');
  dashBtn.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    unlock();
    input.command({ k: 'dash' });
  });
  if (!isTouch()) dashBtn.hidden = true;

  // 标题界面后面：主角自动绕圈
  input.auto = true;
  input.enabled = false;
  setMusic('title');

  // ---- 尺寸与画质
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

  // ---- 主循环
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
    if (!perf.hidden && hudT >= 500) {
      const q = quality.current;
      const s = presenter.stats;
      perf.textContent =
        `${Math.round((frames * 1000) / hudT)} fps  最慢 ${worst.toFixed(0)}ms  妖 ${world.enemies.count}  ` +
        `光 ${s.lights}  辉 ${s.glow}  分辨率 ${q.res}  光照 ${q.ls}  辉光 ${q.bloom}`;
      hudT = 0;
      frames = 0;
      worst = 0;
    }
  };
  requestAnimationFrame(tick);

  // 调试接口（Playwright 和手动调试用）
  (window as unknown as { __lantern: unknown }).__lantern = {
    app,
    get world() {
      return world;
    },
    get mode() {
      return mode;
    },
    presenter,
    quality,
    input,
    loop,
    artReport: report,
  };
}

boot().catch((err: unknown) => {
  console.error(err);
  const el = document.getElementById('fatal');
  if (el) {
    el.textContent = `启动失败：${err instanceof Error ? err.message : String(err)}`;
    el.hidden = false;
  }
});
