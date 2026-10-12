// 输入：键盘（WASD / 方向键 / 空格闪避）和触屏浮动摇杆。
// 每个模拟步读取一次 frame；闪避等一次性操作放进命令队列。

import type { Command, InputFrame } from '../sim/state';

const STICK_R = 46; // 摇杆最大偏移（CSS 像素）

export class Input {
  readonly frame: InputFrame = { mx: 0, my: 0 };
  private readonly keys = new Set<string>();
  private readonly pending: Command[] = [];
  private stickId: number | null = null;
  private ox = 0;
  private oy = 0;
  private sx = 0;
  private sy = 0;
  private readonly base: HTMLDivElement;
  private readonly knob: HTMLDivElement;
  /** 自动绕圈走（跑分用） */
  auto = false;
  private autoT = 0;
  enabled = true;

  constructor(surface: HTMLElement) {
    this.base = document.createElement('div');
    this.base.className = 'stick-base';
    this.knob = document.createElement('div');
    this.knob.className = 'stick-knob';
    this.base.appendChild(this.knob);
    document.body.appendChild(this.base);

    addEventListener('keydown', (e) => {
      if (e.repeat) return;
      this.keys.add(e.code);
      if (e.code === 'Space' || e.code === 'ShiftLeft' || e.code === 'KeyK') this.command({ k: 'dash' });
    });
    addEventListener('keyup', (e) => this.keys.delete(e.code));
    addEventListener('blur', () => this.keys.clear());

    surface.addEventListener('pointerdown', (e) => this.down(e));
    addEventListener('pointermove', (e) => this.move(e));
    addEventListener('pointerup', (e) => this.up(e));
    addEventListener('pointercancel', (e) => this.up(e));
  }

  command(c: Command): void {
    if (this.enabled) this.pending.push(c);
  }

  /** 把这一步的命令交给模拟（模拟读完会清空） */
  flushCommands(out: Command[]): void {
    for (const c of this.pending) out.push(c);
    this.pending.length = 0;
  }

  private down(e: PointerEvent): void {
    if (this.stickId !== null || !this.enabled) return;
    this.stickId = e.pointerId;
    this.ox = this.sx = e.clientX;
    this.oy = this.sy = e.clientY;
    this.base.style.transform = `translate(${this.ox}px, ${this.oy}px)`;
    this.knob.style.transform = 'translate(0px, 0px)';
    this.base.classList.add('on');
  }

  private move(e: PointerEvent): void {
    if (e.pointerId !== this.stickId) return;
    this.sx = e.clientX;
    this.sy = e.clientY;
    let dx = this.sx - this.ox;
    let dy = this.sy - this.oy;
    const l = Math.hypot(dx, dy);
    // 手指拖得太远时，摇杆底座跟着走
    if (l > STICK_R * 1.6) {
      const k = (l - STICK_R * 1.6) / l;
      this.ox += dx * k;
      this.oy += dy * k;
      this.base.style.transform = `translate(${this.ox}px, ${this.oy}px)`;
      dx = this.sx - this.ox;
      dy = this.sy - this.oy;
    }
    const l2 = Math.hypot(dx, dy);
    const c = l2 > STICK_R ? STICK_R / l2 : 1;
    this.knob.style.transform = `translate(${dx * c}px, ${dy * c}px)`;
  }

  private up(e: PointerEvent): void {
    if (e.pointerId !== this.stickId) return;
    this.stickId = null;
    this.base.classList.remove('on');
  }

  /** 每个模拟步调用，更新 frame */
  sample(dt: number): InputFrame {
    let mx = 0;
    let my = 0;
    if (this.enabled) {
      const k = this.keys;
      if (k.has('KeyA') || k.has('ArrowLeft')) mx -= 1;
      if (k.has('KeyD') || k.has('ArrowRight')) mx += 1;
      if (k.has('KeyW') || k.has('ArrowUp')) my -= 1;
      if (k.has('KeyS') || k.has('ArrowDown')) my += 1;
      if (this.stickId !== null) {
        const dx = this.sx - this.ox;
        const dy = this.sy - this.oy;
        const l = Math.hypot(dx, dy);
        if (l > 6) {
          const m = Math.min(1, l / STICK_R);
          mx = (dx / l) * m;
          my = (dy / l) * m;
        }
      }
    }
    if (this.auto && mx === 0 && my === 0) {
      // 慢慢变向的大圈，8 个朝向都会经过
      this.autoT += dt;
      const a = this.autoT * 0.45;
      mx = Math.cos(a);
      my = Math.sin(a);
    }
    const l = Math.hypot(mx, my);
    if (l > 1) {
      mx /= l;
      my /= l;
    }
    this.frame.mx = mx;
    this.frame.my = my;
    return this.frame;
  }
}
