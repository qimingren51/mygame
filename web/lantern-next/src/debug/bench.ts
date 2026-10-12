// 跑分：250 / 500 / 1000 / 1500 只妖物各 10 秒，主角自动绕圈、无敌。
// 每段去掉前 2 秒（刷怪和画质稳定），统计平均帧率、第 95 百分位帧时间和最慢一帧。
// 跑分期间画质固定，不自动降级，结果才可比。

export const BENCH_STAGES = [250, 500, 1000, 1500] as const;

export interface StageResult {
  enemies: number;
  fps: number;
  p95: number;
  worst: number;
  lights: number;
  actors: number;
}

export class Bench {
  stage = 0;
  /** 每段时长；测试里可以用 ?benchStage= 缩短 */
  private readonly stageMs: number;
  private readonly warmupMs: number;
  private t = 0;
  private readonly samples = new Float32Array(2000);
  private n = 0;
  private lights = 0;
  private actors = 0;
  private statFrames = 0;
  readonly results: StageResult[] = [];

  constructor(stageMs = 10000) {
    this.stageMs = stageMs;
    this.warmupMs = Math.min(2000, stageMs * 0.2);
  }

  get target(): number {
    return BENCH_STAGES[Math.min(this.stage, BENCH_STAGES.length - 1)] as number;
  }

  get done(): boolean {
    return this.stage >= BENCH_STAGES.length;
  }

  /** 总进度 0~1 */
  get progress(): number {
    return Math.min(1, (this.stage * this.stageMs + this.t) / (BENCH_STAGES.length * this.stageMs));
  }

  /** 每帧调用；返回 true 表示进入了下一段（需要改妖物数量） */
  frame(dtMs: number, lights: number, actors: number): boolean {
    if (this.done) return false;
    this.t += dtMs;
    if (this.t > this.warmupMs && this.n < this.samples.length) {
      this.samples[this.n++] = dtMs;
      this.lights += lights;
      this.actors += actors;
      this.statFrames++;
    }
    if (this.t < this.stageMs) return false;
    this.finishStage();
    this.stage++;
    this.t = 0;
    this.n = 0;
    this.lights = 0;
    this.actors = 0;
    this.statFrames = 0;
    return !this.done;
  }

  private finishStage(): void {
    const s = Array.from(this.samples.subarray(0, this.n)).sort((a, b) => a - b);
    const total = s.reduce((a, b) => a + b, 0);
    const f = Math.max(1, this.statFrames);
    this.results.push({
      enemies: this.target,
      fps: s.length ? (s.length * 1000) / total : 0,
      p95: s.length ? (s[Math.min(s.length - 1, Math.floor(s.length * 0.95))] as number) : 0,
      worst: s.length ? (s[s.length - 1] as number) : 0,
      lights: Math.round(this.lights / f),
      actors: Math.round(this.actors / f),
    });
  }
}

export interface DeviceInfo {
  ua: string;
  dpr: number;
  screen: string;
  gpu: string;
  build: string;
  settings: string;
}

export function describeGpu(gl: WebGLRenderingContext | WebGL2RenderingContext | undefined): string {
  if (!gl) return '未知';
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  const name = ext ? (gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) as string) : (gl.getParameter(gl.RENDERER) as string);
  const ver = typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext ? 'WebGL2' : 'WebGL1';
  return `${name} (${ver})`;
}

/** 结果卡片的纯文本（复制给我用） */
export function formatResults(results: StageResult[], info: DeviceInfo): string {
  const lines = [
    `提灯夜行 新版跑分 · 构建 ${info.build}`,
    `设备：${info.ua}`,
    `屏幕 ${info.screen} · 像素比 ${info.dpr} · GPU ${info.gpu}`,
    `设置：${info.settings}`,
    '妖物  帧率   P95帧时间  最慢   光源  角色',
  ];
  for (const r of results) {
    lines.push(
      `${String(r.enemies).padStart(4)}  ${r.fps.toFixed(1).padStart(5)}  ${r.p95.toFixed(1).padStart(6)}ms  ${r.worst.toFixed(0).padStart(4)}ms  ${String(r.lights).padStart(4)}  ${String(r.actors).padStart(4)}`,
    );
  }
  return lines.join('\n');
}

/** 设备简述：从 UA 里挑出系统和浏览器 */
export function shortUA(ua: string): string {
  const ios = /OS (\d+[_\d]*) like Mac OS X/.exec(ua);
  const android = /Android ([\d.]+)/.exec(ua);
  const browser = /CriOS\/([\d.]+)/.exec(ua)
    ? `Chrome(iOS) ${/CriOS\/([\d.]+)/.exec(ua)?.[1] ?? ''}`
    : /EdgiOS|Edg\/([\d.]+)/.exec(ua)
      ? 'Edge'
      : /FxiOS|Firefox\/([\d.]+)/.exec(ua)
        ? 'Firefox'
        : /Chrome\/([\d.]+)/.exec(ua)
          ? `Chrome ${/Chrome\/([\d.]+)/.exec(ua)?.[1] ?? ''}`
          : /Version\/([\d.]+).*Safari/.exec(ua)
            ? `Safari ${/Version\/([\d.]+)/.exec(ua)?.[1] ?? ''}`
            : '其他浏览器';
  const os = ios ? `iOS ${ios[1]?.replace(/_/g, '.')}` : android ? `Android ${android[1]}` : /Mac OS X/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : '其他系统';
  const model = /iPhone|iPad/.exec(ua)?.[0] ?? '';
  return [model, os, browser].filter(Boolean).join(' · ');
}
