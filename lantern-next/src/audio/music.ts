// 背景音乐（移植自旧版 audio.js）：持续的低音 + 随机生成的五声旋律 + 随局势加强的鼓点。

import { Rng } from '../core/rng';
import { drum, gong, onInit, pent, pluck, wood, type Graph } from './engine';

export type MusicMode = 'none' | 'title' | 'play' | 'boss';

interface Drone {
  g: GainNode;
  a: OscillatorNode;
  b: OscillatorNode;
}

const music = {
  mode: 'none' as MusicMode,
  intensity: 0,
  step: 0,
  next: 0,
  rng: Math.random as () => number,
  motif: [] as (number | null)[],
  bar: 0,
};
let drone: Drone | null = null;
let graph: Graph | null = null;

onInit((g) => {
  graph = g;
  startDrone(g);
  setInterval(schedule, 50);
});

function startDrone(gr: Graph): void {
  const ctx = gr.ctx;
  const g = ctx.createGain();
  g.gain.value = 0;
  const f = ctx.createBiquadFilter();
  f.type = 'lowpass';
  f.frequency.value = 500;
  const a = ctx.createOscillator();
  const b = ctx.createOscillator();
  a.type = 'triangle';
  b.type = 'triangle';
  a.frequency.value = pent(-5); // D2
  b.frequency.value = pent(-2); // A2
  b.detune.value = 4;
  a.connect(f);
  b.connect(f);
  f.connect(g);
  g.connect(gr.musicFilter);
  a.start();
  b.start();
  drone = { g, a, b };
}

// 生成 16 个八分音符的旋律动机（随机游走，留出呼吸）
function makeMotif(restChance: number): (number | null)[] {
  const r = music.rng;
  const out: (number | null)[] = [];
  let d = 10 + Math.floor(r() * 4);
  for (let i = 0; i < 16; i++) {
    if (r() < restChance || (i % 4 === 3 && r() < 0.5)) {
      out.push(null);
      continue;
    }
    d += Math.floor(r() * 5) - 2;
    d = Math.max(7, Math.min(17, d));
    out.push(d);
  }
  return out;
}

function mutateMotif(): void {
  const r = music.rng;
  music.motif = music.motif.map((n) => {
    if (r() > 0.3) return n;
    if (n === null) return r() < 0.5 ? 10 + Math.floor(r() * 6) : null;
    return Math.max(7, Math.min(17, n + Math.floor(r() * 5) - 2));
  });
}

const BPM: Record<Exclude<MusicMode, 'none'>, number> = { title: 66, play: 84, boss: 104 };

function stepDur(): number {
  if (music.mode === 'none') return 0.25;
  const bpm = BPM[music.mode] + (music.mode === 'play' ? music.intensity * 5 : 0);
  return 60 / bpm / 2;
}

function schedule(): void {
  const g = graph;
  if (!g || music.mode === 'none' || g.ctx.state !== 'running') return;
  if (music.next < g.ctx.currentTime) music.next = g.ctx.currentTime + 0.05;
  while (music.next < g.ctx.currentTime + 0.2) {
    playStep(g, music.next, music.step);
    music.next += stepDur();
    music.step++;
  }
}

const BASS = [0, 3, 2, 0];

function playStep(g: Graph, t: number, step: number): void {
  const s = step % 16;
  if (s === 0) {
    music.bar++;
    if (music.bar % 4 === 0) {
      if (music.rng() < 0.35) music.motif = makeMotif(music.mode === 'title' ? 0.55 : 0.35);
      else mutateMotif();
    }
  }
  const mode = music.mode;
  const lvl = mode === 'boss' ? 3 : mode === 'title' ? -1 : music.intensity;
  const bus = g.musicFilter;

  // 低音拨弦
  if (s % 8 === 0) {
    const root = (BASS[Math.floor(step / 8) % 4] as number) + (mode === 'boss' ? -1 : 0);
    pluck(g, pent(root), t, mode === 'title' ? 0.12 : 0.15, bus, 1.6);
  }
  // 旋律
  const note = music.motif[s];
  if (note !== null && note !== undefined && (mode !== 'title' || s % 2 === 0)) {
    pluck(g, pent(note + (mode === 'boss' ? -1 : 0)), t, 0.1, bus, mode === 'title' ? 1.8 : 1.1);
  }
  // 打击乐随局势加强
  if (lvl >= 1 && s % 2 === 0) wood(g, t, s % 8 === 0 ? 0.08 : 0.045, bus, s % 8 === 0 ? 820 : 1050);
  if (lvl >= 2 && (s === 0 || s === 8)) drum(g, t, 0.3, bus, 100);
  if (lvl >= 3) {
    if (s === 6 || s === 12 || s === 14) drum(g, t, 0.26, bus, 85);
    if (s % 2 === 1) wood(g, t, 0.03, bus, 1400);
    if (s === 0 && music.bar % 4 === 0) gong(g, 49, t, 0.12, bus);
  }
}

function setDrone(level: number, boss = false): void {
  if (!drone || !graph) return;
  const t = graph.ctx.currentTime;
  drone.g.gain.cancelScheduledValues(t);
  drone.g.gain.setTargetAtTime(level, t, 0.8);
  drone.b.frequency.setTargetAtTime(boss ? pent(-5) * Math.pow(2, 6 / 12) : pent(-2), t, 0.5);
}

/** 切换音乐模式；seed 用于让同一局的旋律可复现。 */
export function setMusic(mode: MusicMode, seed?: number): void {
  if (!graph) {
    // 还没解锁：记下模式，解锁后再开始
    onInit(() => setMusic(mode, seed));
    return;
  }
  if (mode === music.mode && seed === undefined) return;
  music.mode = mode;
  if (seed !== undefined) {
    const r = new Rng(seed);
    music.rng = () => r.next();
  }
  if (mode === 'none') {
    setDrone(0);
    return;
  }
  if (mode !== 'boss' || !music.motif.length) music.motif = makeMotif(mode === 'title' ? 0.55 : 0.35);
  music.step = 0;
  music.bar = 0;
  music.next = graph.ctx.currentTime + 0.1;
  setDrone(mode === 'title' ? 0.05 : mode === 'boss' ? 0.07 : 0.04, mode === 'boss');
}

export function setIntensity(n: number): void {
  music.intensity = n;
}

/** 打开菜单时音乐变闷 */
export function muffle(on: boolean): void {
  if (!graph) return;
  graph.musicFilter.frequency.setTargetAtTime(on ? 650 : 12000, graph.ctx.currentTime, 0.15);
}
