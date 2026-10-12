// 音频引擎（移植自旧版 audio.js）：所有音效与音乐都用 Web Audio 实时合成，不需要音频文件。
// 乐器：古筝式拨弦、编钟、太鼓、木鱼、锣；音阶：D 羽调五声音阶。
// 这里只有发声的基础设施；具体音效在 sfx.ts，背景音乐在 music.ts。

import { loadJSON, saveJSON } from '../platform/storage';

const SETTINGS_KEY = 'audio';
export const MUSIC_VOL = 0.42;
export const SFX_VOL = 0.75;

export interface AudioSettings {
  music: boolean;
  sfx: boolean;
}

export const settings: AudioSettings = { music: true, sfx: true, ...loadJSON<Partial<AudioSettings>>(SETTINGS_KEY, {}) };

/** 初始化后的音频图 */
export interface Graph {
  ctx: AudioContext;
  master: GainNode;
  sfxBus: GainNode;
  musicBus: GainNode;
  musicFilter: BiquadFilterNode;
  noiseBuf: AudioBuffer;
}

let graph: Graph | null = null;
const initHooks: ((g: Graph) => void)[] = [];

export function getGraph(): Graph | null {
  return graph;
}

/** 音频图建立后要做的事（启动音乐调度等） */
export function onInit(fn: (g: Graph) => void): void {
  if (graph) fn(graph);
  else initHooks.push(fn);
}

type WebkitWindow = Window & { webkitAudioContext?: typeof AudioContext };

// 初始化（必须在用户手势里调用，浏览器才允许出声）
export function init(): void {
  if (graph) {
    if (graph.ctx.state === 'suspended' && !document.hidden) void graph.ctx.resume();
    return;
  }
  const AC = window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
  if (!AC) return;
  const ctx = new AC();

  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -16;
  comp.ratio.value = 4;
  comp.connect(ctx.destination);
  const master = ctx.createGain();
  master.gain.value = 0.9;
  master.connect(comp);

  const reverb = ctx.createConvolver();
  reverb.buffer = makeImpulse(ctx, 2.6);
  reverb.connect(master);

  const sfxBus = ctx.createGain();
  sfxBus.gain.value = settings.sfx ? SFX_VOL : 0;
  sfxBus.connect(master);
  const sfxSend = ctx.createGain();
  sfxSend.gain.value = 0.18;
  sfxBus.connect(sfxSend);
  sfxSend.connect(reverb);

  const musicFilter = ctx.createBiquadFilter();
  musicFilter.type = 'lowpass';
  musicFilter.frequency.value = 12000;
  const musicBus = ctx.createGain();
  musicBus.gain.value = settings.music ? MUSIC_VOL : 0;
  musicFilter.connect(musicBus);
  musicBus.connect(master);
  const musicSend = ctx.createGain();
  musicSend.gain.value = 0.45;
  musicBus.connect(musicSend);
  musicSend.connect(reverb);

  graph = { ctx, master, sfxBus, musicBus, musicFilter, noiseBuf: makeNoise(ctx, 2) };
  for (const fn of initHooks) fn(graph);
  initHooks.length = 0;
}

// 解锁音频。iPhone 上有三个坑：
// 1. 只有“松手 / 点击”算用户手势，按下不算；所以每次手势都尝试恢复。
// 2. 需要在手势里真正播放一次声音才会解锁；这里播放一个空白缓冲。
// 3. 侧边静音键会静音网页合成的声音；把音频会话切到“播放”类型可以绕过。
let silentEl: HTMLAudioElement | null = null;

type AudioSessionNavigator = Navigator & { audioSession?: { type: string } };

export function unlock(): void {
  init();
  if (!graph) return;
  const ctx = graph.ctx;
  if (ctx.state !== 'running' && !document.hidden) ctx.resume().catch(() => {});
  if (ctx.state !== 'running') {
    const src = ctx.createBufferSource();
    src.buffer = ctx.createBuffer(1, 1, 22050);
    src.connect(ctx.destination);
    src.start(0);
  }
  const nav = navigator as AudioSessionNavigator;
  if (nav.audioSession && nav.audioSession.type !== 'playback') {
    try {
      nav.audioSession.type = 'playback';
    } catch {
      // 不支持时忽略
    }
  }
  if (!silentEl) {
    // 循环播放一段静音音频，让 iOS 把页面当作媒体播放，从而无视静音键
    silentEl = document.createElement('audio');
    silentEl.setAttribute('playsinline', '');
    silentEl.setAttribute('x-webkit-airplay', 'deny');
    silentEl.loop = true;
    silentEl.src = URL.createObjectURL(makeSilentWav());
  }
  if (silentEl.paused && !document.hidden) silentEl.play().catch(() => {});
}

/** 在页面上的任何点击 / 松手时尝试解锁（iOS 需要） */
export function installUnlock(): void {
  const h = () => unlock();
  for (const ev of ['pointerup', 'touchend', 'click', 'keydown'] as const) addEventListener(ev, h, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (!graph) return;
    if (document.hidden) {
      void graph.ctx.suspend();
      silentEl?.pause();
    } else {
      graph.ctx.resume().catch(() => {});
      silentEl?.play().catch(() => {});
    }
  });
}

export function setEnabled(kind: keyof AudioSettings, on: boolean): void {
  settings[kind] = on;
  saveJSON(SETTINGS_KEY, settings);
  if (!graph) return;
  const bus = kind === 'music' ? graph.musicBus : graph.sfxBus;
  bus.gain.setTargetAtTime(on ? (kind === 'music' ? MUSIC_VOL : SFX_VOL) : 0, graph.ctx.currentTime, 0.05);
}

function makeSilentWav(): Blob {
  const rate = 8000;
  const samples = rate / 2;
  const buf = new ArrayBuffer(44 + samples * 2);
  const v = new DataView(buf);
  const str = (o: number, t: string) => {
    for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i));
  };
  str(0, 'RIFF');
  v.setUint32(4, 36 + samples * 2, true);
  str(8, 'WAVE');
  str(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, 'data');
  v.setUint32(40, samples * 2, true);
  return new Blob([buf], { type: 'audio/wav' });
}

function makeNoise(ctx: AudioContext, sec: number): AudioBuffer {
  const buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * sec), ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return buf;
}

function makeImpulse(ctx: AudioContext, sec: number): AudioBuffer {
  const len = Math.floor(ctx.sampleRate * sec);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
  }
  return buf;
}

// ---------------------------------------------------------------
// 基础发声
// ---------------------------------------------------------------

function env(g: GainNode, t: number, vol: number, attack: number, dur: number): void {
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
}

export interface OscOpts {
  slide?: number;
  slideTime?: number;
  detune?: number;
  attack?: number;
}

export function osc(g: Graph, type: OscillatorType, freq: number, t: number, dur: number, vol: number, dest: AudioNode, opt: OscOpts = {}): void {
  const ctx = g.ctx;
  const o = ctx.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  if (opt.slide) o.frequency.exponentialRampToValueAtTime(opt.slide, t + (opt.slideTime ?? dur));
  if (opt.detune) o.detune.value = opt.detune;
  const gn = ctx.createGain();
  env(gn, t, vol, opt.attack ?? 0.004, dur);
  o.connect(gn);
  gn.connect(dest);
  o.start(t);
  o.stop(t + dur + 0.05);
}

export interface NoiseOpts {
  type?: BiquadFilterType;
  freq?: number;
  slide?: number;
  q?: number;
  attack?: number;
}

export function noise(g: Graph, t: number, dur: number, vol: number, dest: AudioNode, opt: NoiseOpts = {}): void {
  const ctx = g.ctx;
  const src = ctx.createBufferSource();
  src.buffer = g.noiseBuf;
  const f = ctx.createBiquadFilter();
  f.type = opt.type ?? 'bandpass';
  f.frequency.setValueAtTime(opt.freq ?? 1200, t);
  if (opt.slide) f.frequency.exponentialRampToValueAtTime(opt.slide, t + dur);
  f.Q.value = opt.q ?? 1;
  const gn = ctx.createGain();
  env(gn, t, vol, opt.attack ?? 0.003, dur);
  src.connect(f);
  f.connect(gn);
  gn.connect(dest);
  const offset = Math.random() * Math.max(0, g.noiseBuf.duration - dur - 0.1);
  src.start(t, offset, dur + 0.05);
}

// D 羽调五声音阶：D F G A C
const STEPS = [0, 3, 5, 7, 10];
const ROOT = 146.83; // D3
export function pent(i: number): number {
  const o = Math.floor(i / 5);
  const s = STEPS[((i % 5) + 5) % 5] as number;
  return ROOT * Math.pow(2, o + s / 12);
}

// 古筝式拨弦：起音略高后回落，带泛音
export function pluck(g: Graph, freq: number, t: number, vol: number, dest: AudioNode, decay = 1.2): void {
  const ctx = g.ctx;
  const o = ctx.createOscillator();
  o.type = 'triangle';
  o.frequency.setValueAtTime(freq * 1.012, t);
  o.frequency.exponentialRampToValueAtTime(freq, t + 0.06);
  const gn = ctx.createGain();
  env(gn, t, vol, 0.003, decay);
  o.connect(gn);
  gn.connect(dest);
  o.start(t);
  o.stop(t + decay + 0.05);
  osc(g, 'sine', freq * 2, t, decay * 0.5, vol * 0.35, dest);
  osc(g, 'sine', freq * 3, t, decay * 0.25, vol * 0.12, dest);
  noise(g, t, 0.03, vol * 0.25, dest, { freq: Math.min(8000, freq * 4), q: 2 });
}

// 编钟：非整数倍泛音
export function bell(g: Graph, freq: number, t: number, vol: number, dest: AudioNode, decay = 2): void {
  osc(g, 'sine', freq, t, decay, vol, dest);
  osc(g, 'sine', freq * 2.76, t, decay * 0.5, vol * 0.4, dest);
  osc(g, 'sine', freq * 5.4, t, decay * 0.25, vol * 0.18, dest);
}

// 太鼓
export function drum(g: Graph, t: number, vol: number, dest: AudioNode, pitch = 110): void {
  osc(g, 'sine', pitch, t, 0.45, vol, dest, { slide: pitch * 0.42, slideTime: 0.3 });
  noise(g, t, 0.12, vol * 0.45, dest, { type: 'lowpass', freq: 420 });
}

// 木鱼
export function wood(g: Graph, t: number, vol: number, dest: AudioNode, pitch = 900): void {
  osc(g, 'sine', pitch, t, 0.08, vol, dest);
  noise(g, t, 0.03, vol * 0.6, dest, { freq: pitch * 2, q: 6 });
}

// 锣
export function gong(g: Graph, freq: number, t: number, vol: number, dest: AudioNode): void {
  [1, 1.48, 2.02, 2.74, 3.9].forEach((m, i) => {
    osc(g, 'sine', freq * m, t, 3.4 - i * 0.5, vol / (i + 1), dest, { detune: (Math.random() - 0.5) * 14, attack: 0.01 });
  });
  noise(g, t, 0.4, vol * 0.35, dest, { type: 'lowpass', freq: 700 });
}
