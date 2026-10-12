// 纯画面特效：墨点飞溅、地上的墨迹、火星、临时光、伤害数字。
// 只用于表现，随机数用 Math.random，不影响玩法。全部用定长数组，不产生垃圾。

import { Rectangle, Texture } from 'pixi.js';
import type { ArtSet } from './art';
import type { Camera } from './camera';
import type { Lighting } from './lighting';
import { packColor, ParticleLayer } from './particles';

const INK = 0x17140f;

const KIND_DROP = 0; // 飞溅的墨点
const KIND_SPLAT = 1; // 留在地上的墨迹
const KIND_SPARK = 2; // 火星（自发光）

export class FxParticles {
  readonly cap: number;
  private n = 0;
  private readonly kind: Uint8Array;
  private readonly x: Float32Array;
  private readonly y: Float32Array;
  private readonly vx: Float32Array;
  private readonly vy: Float32Array;
  private readonly life: Float32Array;
  private readonly max: Float32Array;
  private readonly size: Float32Array;
  private readonly rot: Float32Array;
  private readonly color: Uint32Array;
  private readonly tex: Uint8Array;

  private readonly art: ArtSet;

  constructor(art: ArtSet, cap = 1600) {
    this.art = art;
    this.cap = cap;
    this.kind = new Uint8Array(cap);
    this.x = new Float32Array(cap);
    this.y = new Float32Array(cap);
    this.vx = new Float32Array(cap);
    this.vy = new Float32Array(cap);
    this.life = new Float32Array(cap);
    this.max = new Float32Array(cap);
    this.size = new Float32Array(cap);
    this.rot = new Float32Array(cap);
    this.color = new Uint32Array(cap);
    this.tex = new Uint8Array(cap);
  }

  get count(): number {
    return this.n;
  }

  private spawn(kind: number, x: number, y: number, vx: number, vy: number, life: number, size: number, color: number): void {
    // 满了就覆盖最旧的一个（下标 0 附近的通常最旧）
    const i = this.n < this.cap ? this.n++ : (Math.random() * this.cap) | 0;
    this.kind[i] = kind;
    this.x[i] = x;
    this.y[i] = y;
    this.vx[i] = vx;
    this.vy[i] = vy;
    this.life[i] = life;
    this.max[i] = life;
    this.size[i] = size;
    this.rot[i] = Math.random() * Math.PI * 2;
    this.color[i] = color;
    this.tex[i] = (Math.random() * this.art.vfx.ink.length) | 0;
  }

  hit(x: number, y: number, fromX: number, fromY: number): void {
    let dx = x - fromX;
    let dy = y - fromY;
    const l = Math.hypot(dx, dy) || 1;
    dx /= l;
    dy /= l;
    for (let k = 0; k < 2; k++) {
      const s = 60 + Math.random() * 70;
      const a = (Math.random() - 0.5) * 1.2;
      const c = Math.cos(a);
      const sn = Math.sin(a);
      this.spawn(KIND_DROP, x, y - 8, (dx * c - dy * sn) * s, (dy * c + dx * sn) * s - 20, 0.35, 0.18 + Math.random() * 0.12, INK);
    }
  }

  kill(x: number, y: number, eye: number, big: boolean): void {
    this.spawn(KIND_SPLAT, x, y, 0, 0, big ? 2.4 : 1.4, big ? 1.6 : 0.7 + Math.random() * 0.3, INK);
    const drops = big ? 10 : 5;
    for (let k = 0; k < drops; k++) {
      const a = Math.random() * Math.PI * 2;
      const s = 50 + Math.random() * 110;
      this.spawn(KIND_DROP, x, y - 8, Math.cos(a) * s, Math.sin(a) * s * 0.6 - 30, 0.45, 0.15 + Math.random() * 0.15, INK);
    }
    const sparks = big ? 14 : 6;
    for (let k = 0; k < sparks; k++) {
      const a = Math.random() * Math.PI * 2;
      const s = 40 + Math.random() * 90;
      this.spawn(KIND_SPARK, x, y - 10, Math.cos(a) * s, Math.sin(a) * s - 40, 0.5 + Math.random() * 0.4, 0.6 + Math.random() * 0.6, eye);
    }
  }

  spark(x: number, y: number, color: number, n: number): void {
    for (let k = 0; k < n; k++) {
      const a = Math.random() * Math.PI * 2;
      const s = 20 + Math.random() * 50;
      this.spawn(KIND_SPARK, x, y, Math.cos(a) * s, Math.sin(a) * s - 30, 0.35 + Math.random() * 0.2, 0.5 + Math.random() * 0.4, color);
    }
  }

  update(dt: number): void {
    let i = 0;
    while (i < this.n) {
      const life = (this.life[i] as number) - dt;
      if (life <= 0) {
        this.removeAt(i);
        continue;
      }
      this.life[i] = life;
      const k = this.kind[i];
      if (k !== KIND_SPLAT) {
        this.x[i] = (this.x[i] as number) + (this.vx[i] as number) * dt;
        this.y[i] = (this.y[i] as number) + (this.vy[i] as number) * dt;
        const drag = Math.exp(-dt * (k === KIND_DROP ? 5 : 3));
        this.vx[i] = (this.vx[i] as number) * drag;
        this.vy[i] = (this.vy[i] as number) * drag + (k === KIND_DROP ? 260 : -20) * dt;
      }
      i++;
    }
  }

  private removeAt(i: number): void {
    const last = --this.n;
    if (i === last) return;
    this.kind[i] = this.kind[last] as number;
    this.x[i] = this.x[last] as number;
    this.y[i] = this.y[last] as number;
    this.vx[i] = this.vx[last] as number;
    this.vy[i] = this.vy[last] as number;
    this.life[i] = this.life[last] as number;
    this.max[i] = this.max[last] as number;
    this.size[i] = this.size[last] as number;
    this.rot[i] = this.rot[last] as number;
    this.color[i] = this.color[last] as number;
    this.tex[i] = this.tex[last] as number;
  }

  /** ink：墨点和墨迹（在暗层下面，只在光里看得见）；glow：火星（自发光，叠加） */
  draw(ink: ParticleLayer, glow: ParticleLayer): void {
    const v = this.art.vfx;
    const inkTex = v.ink;
    for (let i = 0; i < this.n; i++) {
      const k = this.kind[i];
      const t = (this.life[i] as number) / (this.max[i] as number); // 1 → 0
      const s = this.size[i] as number;
      const x = this.x[i] as number;
      const y = this.y[i] as number;
      if (k === KIND_SPARK) {
        const a = t * t;
        glow.add(v.spark, x, y, s, s, packColor(this.color[i] as number, a));
        glow.add(v.glow, x, y, s * 0.35, s * 0.35, packColor(this.color[i] as number, a * 0.5));
      } else {
        const tex = inkTex[this.tex[i] as number] as Texture;
        const a = k === KIND_SPLAT ? Math.min(1, t * 2.5) * 0.8 : t;
        const grow = k === KIND_SPLAT ? 1 + (1 - t) * 0.15 : 1;
        ink.add(tex, x, y, s * grow, s * grow * (k === KIND_SPLAT ? 0.6 : 1), packColor(INK, a), this.rot[i] as number);
      }
    }
  }
}

/** 临时光源：击杀、爆炸时闪一下 */
export class FlashLights {
  private readonly x = new Float32Array(64);
  private readonly y = new Float32Array(64);
  private readonly r = new Float32Array(64);
  private readonly c = new Uint32Array(64);
  private readonly life = new Float32Array(64);
  private readonly max = new Float32Array(64);
  private n = 0;

  add(x: number, y: number, r: number, color: number, life: number): void {
    const i = this.n < 64 ? this.n++ : (Math.random() * 64) | 0;
    this.x[i] = x;
    this.y[i] = y;
    this.r[i] = r;
    this.c[i] = color;
    this.life[i] = life;
    this.max[i] = life;
  }

  update(dt: number, lighting: Lighting): void {
    let i = 0;
    while (i < this.n) {
      const life = (this.life[i] as number) - dt;
      if (life <= 0) {
        const last = --this.n;
        this.x[i] = this.x[last] as number;
        this.y[i] = this.y[last] as number;
        this.r[i] = this.r[last] as number;
        this.c[i] = this.c[last] as number;
        this.life[i] = this.life[last] as number;
        this.max[i] = this.max[last] as number;
        continue;
      }
      this.life[i] = life;
      const t = life / (this.max[i] as number);
      lighting.add(this.x[i] as number, this.y[i] as number, (this.r[i] as number) * (0.7 + 0.3 * t), this.c[i] as number, t);
      i++;
    }
  }
}

// ---------------------------------------------------------------------------
// 伤害数字：数字字形画在一张小图集上，每个数字位是一个粒子，屏幕坐标。

const DIGIT_W = 30;
const DIGIT_H = 40;

export function createDigitTextures(): Texture[] {
  const canvas = document.createElement('canvas');
  canvas.width = DIGIT_W * 10 + 20;
  canvas.height = DIGIT_H + 4;
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D;
  ctx.font = `700 ${DIGIT_H - 6}px "Songti SC", "STSong", "Noto Serif SC", "SimSun", serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  for (let d = 0; d < 10; d++) {
    const cx = d * (DIGIT_W + 2) + DIGIT_W / 2 + 1;
    const cy = DIGIT_H / 2 + 2;
    ctx.lineWidth = 7;
    ctx.strokeStyle = 'rgba(16,13,10,0.92)';
    ctx.strokeText(String(d), cx, cy);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(String(d), cx, cy);
  }
  const base = Texture.from(canvas);
  const out: Texture[] = [];
  for (let d = 0; d < 10; d++) {
    out.push(
      new Texture({
        source: base.source,
        frame: new Rectangle(d * (DIGIT_W + 2) + 1, 2, DIGIT_W, DIGIT_H),
        defaultAnchor: { x: 0.5, y: 0.5 },
      }),
    );
  }
  return out;
}

const NUM_CAP = 96;

export class DamageNumbers {
  readonly layer: ParticleLayer;
  private readonly x = new Float32Array(NUM_CAP);
  private readonly y = new Float32Array(NUM_CAP);
  private readonly value = new Int32Array(NUM_CAP);
  private readonly t = new Float32Array(NUM_CAP);
  private readonly crit = new Uint8Array(NUM_CAP);
  private readonly jx = new Float32Array(NUM_CAP);
  private next = 0;
  private readonly digits: Texture[];
  enabled = true;

  constructor() {
    this.digits = createDigitTextures();
    this.layer = new ParticleLayer(this.digits[0] as Texture, NUM_CAP * 5);
    this.t.fill(99);
  }

  add(x: number, y: number, value: number, crit: boolean): void {
    if (!this.enabled) return;
    const i = this.next;
    this.next = (i + 1) % NUM_CAP;
    this.x[i] = x;
    this.y[i] = y;
    this.value[i] = Math.max(1, Math.round(value));
    this.t[i] = 0;
    this.crit[i] = crit ? 1 : 0;
    this.jx[i] = (Math.random() - 0.5) * 10;
  }

  draw(dt: number, cam: Camera): void {
    const L = this.layer;
    L.begin();
    const LIFE = 0.7;
    for (let i = 0; i < NUM_CAP; i++) {
      const t = (this.t[i] as number) + dt;
      this.t[i] = t;
      if (t >= LIFE) continue;
      const crit = this.crit[i] === 1;
      // 先弹出放大，再上浮淡出
      const pop = t < 0.12 ? 0.7 + (t / 0.12) * 0.5 : 1.2 - Math.min(0.2, (t - 0.12) * 0.8);
      const scale = (crit ? 0.62 : 0.42) * pop;
      const alpha = t < LIFE - 0.25 ? 1 : (LIFE - t) / 0.25;
      const sx = cam.toScreenX((this.x[i] as number) + (this.jx[i] as number));
      const sy = cam.toScreenY(this.y[i] as number) - 26 - t * 36;
      const color = packColor(crit ? 0xffc04a : 0xf4ead6, alpha);
      let v = this.value[i] as number;
      let digits = 0;
      for (let tmp = v; tmp > 0; tmp = (tmp / 10) | 0) digits++;
      const step = DIGIT_W * 0.72 * scale;
      let px = sx + ((digits - 1) * step) / 2;
      while (v > 0) {
        L.add(this.digits[v % 10] as Texture, px, sy, scale, scale, color);
        v = (v / 10) | 0;
        px -= step;
      }
    }
    L.end();
  }
}
