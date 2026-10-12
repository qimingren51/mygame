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
import { Bench, describeGpu, formatResults, shortUA } from './debug/bench';
import { createPanel } from './debug/panel';
import { isTouch } from './platform/fullscreen';
import { Input } from './platform/input';
import { loadArt } from './render/atlas';
import { Presenter } from './render/presenter';
import { QualityScaler, type BloomMode, type Quality, type QualityLocks } from './render/quality';
import { createWorld, setView, type World } from './sim/state';
import { step } from './sim/step';
import { showBenchCard } from './ui/benchCard';
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

type Mode = 'title' | 'play' | 'bench' | 'result';

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
  /** 调试面板或跑分手动指定的画质；null 表示用自动画质的当前档位 */
  let manual: Quality | null = null;
  const currentQ = (): Quality => manual ?? quality.current;
  let bench: Bench | null = null;

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
    bench: () => startBench(),
  });

  function startBench(): void {
    // 固定种子、固定画质（自动降级关掉，结果才可比）
    world = newWorld(12345);
    bench = new Bench();
    world.benchTarget = bench.target;
    manual = { ...quality.levels[0] } as Quality;
    quality.auto = false;
    fit(true);
    mode = 'bench';
    input.auto = true;
    input.enabled = false;
    title.hide();
    hud.hidden = false;
    perf.hidden = false;
    setMusic('play');
  }

  function finishBench(b: Bench): void {
    mode = 'result';
    const q = currentQ();
    const text = formatResults(b.results, {
      ua: shortUA(navigator.userAgent),
      dpr: window.devicePixelRatio || 1,
      screen: `${screen.width}×${screen.height}（画布 ${cssW}×${cssH}）`,
      gpu: describeGpu((app.renderer as unknown as { gl?: WebGLRenderingContext }).gl),
      build: __BUILD_ID__,
      settings: `分辨率 ${q.res} · 光照图 ${q.ls} · 辉光 ${q.bloom} · 角色 ${presenter.actorMode} · 光源上限 ${presenter.lighting.maxLights}`,
    });
    console.info(text);
    showBenchCard(b.results, text, { again: startBench, back: toTitle });
    hud.hidden = true;
  }
  function toTitle(): void {
    if (mode === 'bench' || mode === 'result') {
      // 跑分结束后恢复自动画质
      manual = null;
      quality.auto = true;
      world.benchTarget = enemyTarget;
      fit(true);
    }
    bench = null;
    document.getElementById('bench-card')?.remove();
    mode = 'title';
    input.auto = true;
    input.enabled = false;
    hud.hidden = true;
    title.show();
    setMusic('title');
  }
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
    presenter.resize(app.renderer, cssW, cssH, currentQ(), world);
  };
  fit(true);

  // ---- 调试面板（实时生效）
  const setQ = (patch: Partial<Quality>) => {
    manual = { ...currentQ(), ...patch };
    quality.auto = false;
    fit(true);
  };
  const panel = createPanel([
    { label: '光照', values: [true, false], get: () => presenter.lightsOn, set: (v: boolean) => (presenter.lightsOn = v), show: (v: boolean) => (v ? '开' : '关') },
    { label: '数字', values: [true, false], get: () => presenter.showNumbers, set: (v: boolean) => (presenter.showNumbers = v), show: (v: boolean) => (v ? '开' : '关') },
    { label: '辉光', values: ['baked', 'filter', 'off'] as BloomMode[], get: () => currentQ().bloom, set: (v: BloomMode) => setQ({ bloom: v }), show: (v: BloomMode) => ({ off: '关', baked: '烘焙', filter: '滤镜' })[v] },
    { label: '分辨率', values: [2, 1.5, 1.25, 1], get: () => currentQ().res, set: (v: number) => setQ({ res: v }) },
    { label: '光照图', values: [0.5, 0.25], get: () => currentQ().ls, set: (v: number) => setQ({ ls: v }) },
    { label: '角色', values: ['B', 'A'], get: () => presenter.actorMode, set: (v: 'A' | 'B') => presenter.setActorMode(v), show: (v: string) => (v === 'A' ? 'A 粒子' : 'B 精灵') },
    { label: '妖物', values: [250, 500, 1000, 1500, 2000], get: () => world.benchTarget ?? 0, set: (v: number) => (world.benchTarget = v) },
    {
      label: '自动画质',
      values: [true, false],
      get: () => quality.auto && manual === null,
      set: (v: boolean) => {
        quality.auto = v;
        if (v) manual = null;
        fit(true);
      },
      show: (v: boolean) => (v ? '开' : '关'),
    },
    { label: '性能', values: [true, false], get: () => !perf.hidden, set: (v: boolean) => (perf.hidden = !v), show: (v: boolean) => (v ? '显示' : '隐藏') },
  ]);
  $('dbg-btn').addEventListener('click', () => panel.toggle());

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
    if (mode === 'bench' && bench) {
      if (bench.frame(dtMs, presenter.stats.lights, presenter.stats.actors)) world.benchTarget = bench.target;
      if (bench.done) finishBench(bench);
    }

    frames++;
    hudT += dtMs;
    worst = Math.max(worst, dtMs);
    if (!perf.hidden && hudT >= 500) {
      const q = currentQ();
      const s = presenter.stats;
      perf.textContent =
        `${Math.round((frames * 1000) / hudT)} fps  最慢 ${worst.toFixed(0)}ms  妖 ${world.enemies.count}  ` +
        `光 ${s.lights}  辉 ${s.glow}  分辨率 ${q.res}  光照 ${q.ls}  辉光 ${q.bloom}` +
        (mode === 'bench' && bench ? `\n跑分 ${Math.round(bench.progress * 100)}% · 第 ${bench.stage + 1}/4 段 ${bench.target} 只` : '');
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
