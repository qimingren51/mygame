// 代码生成的占位素材，用来在 Blender 素材到位前把渲染管线跑通。
// 角色画在同一张图集上（ParticleContainer 要求同一贴图源），特效画在另一张图集上。

import { Rectangle, Texture } from 'pixi.js';
import { DIRS, type ArtSet, type Socket } from './art';

const PX = 2; // 贴图像素 / 世界单位

class AtlasBuilder {
  readonly canvas: HTMLCanvasElement;
  readonly ctx: CanvasRenderingContext2D;
  private x = 2;
  private y = 2;
  private rowH = 0;
  private readonly frames: { x: number; y: number; w: number; h: number; ax: number; ay: number; out: { tex?: Texture } }[] = [];

  readonly size: number;

  constructor(size: number) {
    this.size = size;
    this.canvas = document.createElement('canvas');
    this.canvas.width = size;
    this.canvas.height = size;
    this.ctx = this.canvas.getContext('2d') as CanvasRenderingContext2D;
  }

  /** 预留一块区域并在上面作画；返回一个稍后填上贴图的占位对象。 */
  add(w: number, h: number, ax: number, ay: number, draw: (ctx: CanvasRenderingContext2D) => void): { tex?: Texture } {
    if (this.x + w + 2 > this.size) {
      this.x = 2;
      this.y += this.rowH + 2;
      this.rowH = 0;
    }
    const out = {};
    const fx = this.x;
    const fy = this.y;
    this.ctx.save();
    this.ctx.translate(fx, fy);
    this.ctx.beginPath();
    this.ctx.rect(0, 0, w, h);
    this.ctx.clip();
    draw(this.ctx);
    this.ctx.restore();
    this.frames.push({ x: fx, y: fy, w, h, ax, ay, out });
    this.x += w + 2;
    this.rowH = Math.max(this.rowH, h);
    return out;
  }

  build(): void {
    const base = Texture.from(this.canvas);
    for (const f of this.frames) {
      f.out.tex = new Texture({
        source: base.source,
        frame: new Rectangle(f.x, f.y, f.w, f.h),
        defaultAnchor: { x: f.ax, y: f.ay },
      });
    }
  }
}

const tex = (o: { tex?: Texture }): Texture => o.tex as Texture;

// ---------------------------------------------------------------------------
// 角色
// ---------------------------------------------------------------------------

const INK = '#1d1d22';
const PAPER = '#ede4cf';

/** 主角占位：Q 版提灯人，斗笠 + 长袍 + 红灯笼。dir 0..7，phase 为走路相位。 */
function drawHero(ctx: CanvasRenderingContext2D, dir: number, phase: number, flash: boolean): Socket {
  const W = 128;
  const H = 128;
  const footX = W / 2;
  const footY = H * 0.875;
  const ang = (dir * Math.PI) / 4; // 朝向角，屏幕坐标
  const fx = Math.cos(ang);
  const fy = Math.sin(ang);
  const bob = Math.abs(Math.sin(phase * Math.PI)) * 3;
  const step = Math.sin(phase * Math.PI * 2) * 5;
  const fill = (c: string) => (flash ? '#ffffff' : c);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.lineWidth = 3;
  ctx.strokeStyle = flash ? '#ffffff' : INK;

  // 腿
  ctx.fillStyle = fill('#3b3b44');
  ctx.fillRect(footX - 9 + step * fx, footY - 18, 7, 18);
  ctx.fillRect(footX + 2 - step * fx, footY - 18, 7, 18);
  // 长袍
  const top = footY - 58 - bob;
  ctx.fillStyle = fill('#c8cdd8');
  ctx.beginPath();
  ctx.moveTo(footX - 13, top + 6);
  ctx.lineTo(footX + 13, top + 6);
  ctx.lineTo(footX + 21, footY - 14);
  ctx.quadraticCurveTo(footX, footY - 8, footX - 21, footY - 14);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // 腰带（朱砂）
  ctx.fillStyle = fill('#b8392f');
  ctx.fillRect(footX - 17, top + 24, 34, 5);
  // 头
  const hx = footX + fx * 3;
  const hy = top - 6 + Math.max(0, fy) * 2;
  ctx.fillStyle = fill('#ead6b8');
  ctx.beginPath();
  ctx.arc(hx, hy, 11, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  // 斗笠（赭石）
  ctx.fillStyle = fill('#a97c45');
  ctx.beginPath();
  ctx.ellipse(hx, hy - 8, 28, 8, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(hx - 22, hy - 9);
  ctx.lineTo(hx, hy - 30);
  ctx.lineTo(hx + 22, hy - 9);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // 灯杆与灯笼：右手（屏幕上取朝向的右前方）
  const rx = -fy;
  const ry = fx;
  const handX = footX + fx * 12 + rx * 12;
  const handY = top + 22 + fy * 4 + ry * 4;
  const tipX = handX + fx * 18 + rx * 6;
  const tipY = handY - 18;
  ctx.beginPath();
  ctx.moveTo(handX, handY);
  ctx.lineTo(tipX, tipY);
  ctx.stroke();
  const lx = tipX;
  const ly = tipY + 14;
  ctx.fillStyle = fill('#c9392f');
  ctx.beginPath();
  ctx.ellipse(lx, ly, 8, 10, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  return { x: lx - footX, y: ly - footY };
}

function drawGhost(ctx: CanvasRenderingContext2D, size: number, phase: number, flash: boolean, wisp: boolean): Socket {
  const cx = size / 2;
  const footY = size * 0.875;
  const r = wisp ? size * 0.26 : size * 0.34;
  const cy = footY - r - 6;
  const wave = Math.sin(phase * Math.PI * 2) * 3;
  ctx.fillStyle = flash ? '#ffffff' : wisp ? '#2a3442' : '#24202c';
  ctx.strokeStyle = flash ? '#ffffff' : '#0e0e12';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(cx - r, cy + r * 0.4);
  ctx.bezierCurveTo(cx - r * 1.1, cy - r * 1.2, cx + r * 1.1, cy - r * 1.2, cx + r, cy + r * 0.4);
  ctx.quadraticCurveTo(cx + r * 0.6, cy + r + wave, cx + r * 0.25, cy + r * 0.8);
  ctx.quadraticCurveTo(cx, cy + r * 1.2 - wave, cx - r * 0.25, cy + r * 0.8);
  ctx.quadraticCurveTo(cx - r * 0.6, cy + r + wave, cx - r, cy + r * 0.4);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  return { x: 0, y: cy - r * 0.15 - footY };
}

// ---------------------------------------------------------------------------
// 特效与地面
// ---------------------------------------------------------------------------

/** 径向渐变，带随机抖动消除 8 位色带 */
function drawRadial(ctx: CanvasRenderingContext2D, size: number, falloff: number): void {
  const img = ctx.createImageData(size, size);
  const c = size / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x + 0.5 - c, y + 0.5 - c) / c;
      let v = Math.max(0, 1 - d);
      v = Math.pow(v, falloff) * 255 + (Math.random() - 0.5) * 1.5;
      const o = (y * size + x) * 4;
      img.data[o] = 255;
      img.data[o + 1] = 255;
      img.data[o + 2] = 255;
      img.data[o + 3] = Math.max(0, Math.min(255, v));
    }
  }
  // putImageData 不受变换影响，先写到临时画布，再按图集里的偏移画上去
  const tmp = document.createElement('canvas');
  tmp.width = size;
  tmp.height = size;
  (tmp.getContext('2d') as CanvasRenderingContext2D).putImageData(img, 0, 0);
  ctx.drawImage(tmp, 0, 0);
}

function drawFlame(ctx: CanvasRenderingContext2D, phase: number): void {
  const g = ctx.createRadialGradient(16, 30, 2, 16, 26, 22);
  g.addColorStop(0, 'rgba(255,240,190,1)');
  g.addColorStop(0.35, 'rgba(255,170,80,0.95)');
  g.addColorStop(1, 'rgba(220,60,30,0)');
  ctx.fillStyle = g;
  const s = 1 + Math.sin(phase * Math.PI * 2) * 0.08;
  ctx.beginPath();
  ctx.moveTo(16, 4 + (1 - s) * 10);
  ctx.bezierCurveTo(28, 18, 28 * s, 34, 16, 44);
  ctx.bezierCurveTo(4 / s, 34, 4, 18, 16, 4 + (1 - s) * 10);
  ctx.fill();
}

function drawPaper(): HTMLCanvasElement {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d') as CanvasRenderingContext2D;
  const img = ctx.createImageData(size, size);
  // 可平铺的低频噪声 + 纤维
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const n =
        Math.sin((x / size) * Math.PI * 2 * 3) * Math.cos((y / size) * Math.PI * 2 * 2) * 4 +
        Math.sin(((x + y) / size) * Math.PI * 2 * 5) * 3 +
        (Math.random() - 0.5) * 8;
      const o = (y * size + x) * 4;
      img.data[o] = 237 + n;
      img.data[o + 1] = 228 + n;
      img.data[o + 2] = 207 + n * 0.8;
      img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  ctx.strokeStyle = 'rgba(150,130,100,0.08)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 160; i++) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const a = Math.random() * Math.PI;
    const l = 6 + Math.random() * 18;
    for (const ox of [-size, 0, size]) {
      for (const oy of [-size, 0, size]) {
        ctx.beginPath();
        ctx.moveTo(x + ox, y + oy);
        ctx.lineTo(x + ox + Math.cos(a) * l, y + oy + Math.sin(a) * l);
        ctx.stroke();
      }
    }
  }
  return c;
}

function drawWash(ctx: CanvasRenderingContext2D, w: number, h: number, seed: number): void {
  for (let i = 0; i < 5; i++) {
    const x = w * (0.3 + ((seed * 7 + i * 13) % 10) / 25);
    const y = h * (0.35 + ((seed * 3 + i * 7) % 10) / 30);
    const r = Math.min(w, h) * (0.18 + ((seed + i) % 5) / 30);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(40,40,48,0.16)');
    g.addColorStop(1, 'rgba(40,40,48,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }
}

function drawGrass(ctx: CanvasRenderingContext2D, w: number, h: number, seed: number): void {
  ctx.strokeStyle = 'rgba(30,30,36,0.75)';
  ctx.lineCap = 'round';
  for (let i = 0; i < 6; i++) {
    const x = w / 2 + (i - 2.5) * 5 + (seed % 3);
    const len = h * (0.45 + ((seed + i * 3) % 5) / 12);
    ctx.lineWidth = 2.5 - i * 0.2;
    ctx.beginPath();
    ctx.moveTo(x, h - 2);
    ctx.quadraticCurveTo(x + (i - 2.5) * 3, h - len * 0.6, x + (i - 2.5) * 6, h - len);
    ctx.stroke();
  }
}

function drawRock(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = 'rgba(120,118,112,0.55)';
  ctx.strokeStyle = 'rgba(25,25,30,0.9)';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(w * 0.1, h * 0.85);
  ctx.quadraticCurveTo(w * 0.15, h * 0.3, w * 0.5, h * 0.2);
  ctx.quadraticCurveTo(w * 0.85, h * 0.25, w * 0.9, h * 0.85);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(w * 0.45, h * 0.3);
  ctx.lineTo(w * 0.55, h * 0.6);
  ctx.stroke();
}

function drawStoneLantern(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = 'rgba(150,146,138,0.85)';
  ctx.strokeStyle = INK;
  ctx.lineWidth = 3;
  const cx = w / 2;
  const base = h - 6;
  ctx.fillRect(cx - 18, base - 10, 36, 10);
  ctx.strokeRect(cx - 18, base - 10, 36, 10);
  ctx.fillRect(cx - 6, base - 34, 12, 24);
  ctx.strokeRect(cx - 6, base - 34, 12, 24);
  ctx.fillRect(cx - 14, base - 54, 28, 20);
  ctx.strokeRect(cx - 14, base - 54, 28, 20);
  ctx.fillStyle = '#2a2a30';
  ctx.fillRect(cx - 6, base - 49, 12, 10);
  ctx.fillStyle = 'rgba(150,146,138,0.9)';
  ctx.beginPath();
  ctx.moveTo(cx - 26, base - 54);
  ctx.lineTo(cx + 26, base - 54);
  ctx.lineTo(cx + 15, base - 66);
  ctx.lineTo(cx - 15, base - 66);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
}

// ---------------------------------------------------------------------------

export function createPlaceholderArt(): ArtSet {
  const actors = new AtlasBuilder(2048);
  const vfx = new AtlasBuilder(512);
  const ground = new AtlasBuilder(1024);

  const heroIdle: { tex?: Texture }[][] = [];
  const heroWalk: { tex?: Texture }[][] = [];
  const lanternIdle: Socket[][] = [];
  const lanternWalk: Socket[][] = [];
  for (let d = 0; d < DIRS.length; d++) {
    heroIdle.push([]);
    lanternIdle.push([]);
    heroWalk.push([]);
    lanternWalk.push([]);
    for (let f = 0; f < 4; f++) {
      let s: Socket = { x: 0, y: 0 };
      heroIdle[d]?.push(actors.add(128, 128, 0.5, 0.875, (ctx) => (s = drawHero(ctx, d, 0, false))));
      lanternIdle[d]?.push(s);
    }
    for (let f = 0; f < 8; f++) {
      let s: Socket = { x: 0, y: 0 };
      heroWalk[d]?.push(actors.add(128, 128, 0.5, 0.875, (ctx) => (s = drawHero(ctx, d, f / 8, false))));
      lanternWalk[d]?.push(s);
    }
  }

  const enemy = (wisp: boolean) => {
    const size = 80;
    const frames: { tex?: Texture }[] = [];
    const flash: { tex?: Texture }[] = [];
    const eyes: Socket[] = [];
    for (let f = 0; f < 6; f++) {
      frames.push(actors.add(size, size, 0.5, 0.875, (ctx) => eyes.push(drawGhost(ctx, size, f / 6, false, wisp))));
      flash.push(actors.add(size, size, 0.5, 0.875, (ctx) => drawGhost(ctx, size, f / 6, true, wisp)));
    }
    return { frames, flash, eyes };
  };
  const shade = enemy(false);
  const wisp = enemy(true);

  const light = vfx.add(128, 128, 0.5, 0.5, (ctx) => drawRadial(ctx, 128, 1.6));
  const glow = vfx.add(64, 64, 0.5, 0.5, (ctx) => drawRadial(ctx, 64, 2.4));
  const eyes = vfx.add(24, 10, 0.5, 0.5, (ctx) => {
    for (const x of [6, 18]) {
      const g = ctx.createRadialGradient(x, 5, 0, x, 5, 5);
      g.addColorStop(0, 'rgba(255,255,255,1)');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = g;
      ctx.fillRect(x - 5, 0, 10, 10);
    }
  });
  const shadow = vfx.add(64, 24, 0.5, 0.5, (ctx) => {
    ctx.scale(1, 24 / 64);
    const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, 'rgba(0,0,0,0.5)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
  });
  const spark = vfx.add(12, 12, 0.5, 0.5, (ctx) => drawRadial(ctx, 12, 1.2));
  const gems = [6, 9, 12].map((r) =>
    vfx.add(r * 2 + 8, r * 2 + 8, 0.5, 0.5, (ctx) => {
      const c = r + 4;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.moveTo(c, c - r);
      ctx.lineTo(c + r * 0.7, c);
      ctx.lineTo(c, c + r);
      ctx.lineTo(c - r * 0.7, c);
      ctx.closePath();
      ctx.fill();
    }),
  );
  const flames = [0, 1, 2, 3].map((f) => vfx.add(32, 48, 0.5, 0.6, (ctx) => drawFlame(ctx, f / 4)));
  const inks = [0, 1, 2].map((k) =>
    vfx.add(20, 20, 0.5, 0.5, (ctx) => {
      ctx.fillStyle = 'rgba(20,20,24,1)';
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        ctx.arc(10 + Math.cos(i * 2 + k) * 4, 10 + Math.sin(i * 3 + k) * 4, 3 + ((i + k) % 3), 0, Math.PI * 2);
        ctx.fill();
      }
    }),
  );
  const lantern = vfx.add(20, 24, 0.5, 0.5, (ctx) => {
    ctx.fillStyle = '#ffd9a0';
    ctx.beginPath();
    ctx.ellipse(10, 12, 7, 9, 0, 0, Math.PI * 2);
    ctx.fill();
  });

  const washes = [0, 1, 2].map((k) => ground.add(240, 160, 0.5, 0.5, (ctx) => drawWash(ctx, 240, 160, k)));
  const grasses = [0, 1, 2, 3].map((k) => ground.add(48, 40, 0.5, 1, (ctx) => drawGrass(ctx, 48, 40, k)));
  const rocks = [0, 1].map(() => actors.add(72, 52, 0.5, 0.85, (ctx) => drawRock(ctx, 72, 52)));
  const stoneLantern = actors.add(72, 96, 0.5, 0.94, (ctx) => drawStoneLantern(ctx, 72, 96));

  actors.build();
  vfx.build();
  ground.build();

  const paper = Texture.from(drawPaper());
  paper.source.addressMode = 'repeat';

  const anim = (e: ReturnType<typeof enemy>) => ({ frames: e.frames.map(tex), flash: e.flash.map(tex), eyes: e.eyes });
  return {
    pxPerUnit: PX,
    hero: {
      idle: heroIdle.map((d) => d.map(tex)),
      walk: heroWalk.map((d) => d.map(tex)),
      lantern: { idle: lanternIdle, walk: lanternWalk },
      strideUnits: 64,
      idleFps: 6,
    },
    enemies: { shade: anim(shade), wisp: anim(wisp) },
    vfx: {
      light: tex(light),
      glow: tex(glow),
      eyes: tex(eyes),
      shadow: tex(shadow),
      spark: tex(spark),
      gem: gems.map(tex),
      flame: flames.map(tex),
      ink: inks.map(tex),
      lantern: tex(lantern),
    },
    props: { rocks: rocks.map(tex), stoneLantern: tex(stoneLantern), stoneLanternFlame: { x: 0, y: -44 } },
    ground: { paper, wash: washes.map(tex), grass: grasses.map(tex) },
  };
}

export { PAPER };
