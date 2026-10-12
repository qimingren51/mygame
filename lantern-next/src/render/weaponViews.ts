// 法器与法术的画面：飞剑、纸鹤、寒波与各种环、石印、地裂、连锁爆炸、护盾、拾取物、夜主弹幕。
// 只读模拟状态；一次性的效果（环、印痕、爆炸）由画面层收到特效事件后在这里记下，自己计时淡出。

import type { Texture } from 'pixi.js';
import { RING_BELL, RING_BIGBELL, RING_QUAKE, RING_TAIJI, RING_ULT } from '../core/fxqueue';
import type { World } from '../sim/state';
import type { ArtSet } from './art';
import type { Lighting } from './lighting';
import { packColor, type ParticleLayer } from './particles';

const RING_COLOR = [0x6fb8ff, 0xa8d4ff, 0xc9925a, 0xffd98a, 0xffd98a];
const RING_LIFE = [0.45, 0.7, 0.5, 0.6, 1.0];
const MAX_FX = 128;

/** 一次性效果的种类 */
const K_RING = 0;
const K_MARK = 1;
const K_BLAST = 2;

export interface WeaponLayers {
  /** 地面上的墨迹（在暗层下面） */
  ground: ParticleLayer;
  /** 法器本体（在暗层上面，普通混合） */
  body: ParticleLayer;
  /** 发光（叠加） */
  glow: ParticleLayer;
}

export class WeaponViews {
  private readonly art: ArtSet;
  private readonly inv: number;
  private n = 0;
  private readonly kind = new Uint8Array(MAX_FX);
  private readonly sub = new Uint8Array(MAX_FX);
  private readonly x = new Float32Array(MAX_FX);
  private readonly y = new Float32Array(MAX_FX);
  private readonly r = new Float32Array(MAX_FX);
  private readonly t = new Float32Array(MAX_FX);
  private readonly life = new Float32Array(MAX_FX);
  private readonly rot = new Float32Array(MAX_FX);
  private time = 0;

  constructor(art: ArtSet) {
    this.art = art;
    this.inv = 1 / art.pxPerUnit;
  }

  private push(kind: number, sub: number, x: number, y: number, r: number, life: number): void {
    const i = this.n < MAX_FX ? this.n++ : (Math.random() * MAX_FX) | 0;
    this.kind[i] = kind;
    this.sub[i] = sub;
    this.x[i] = x;
    this.y[i] = y;
    this.r[i] = r;
    this.t[i] = 0;
    this.life[i] = life;
    this.rot[i] = Math.random() * Math.PI * 2;
  }

  ring(x: number, y: number, r: number, kind: number): void {
    this.push(K_RING, kind, x, y, r, RING_LIFE[kind] ?? 0.5);
  }

  sealHit(x: number, y: number, r: number, evo: boolean): void {
    this.push(K_MARK, evo ? 1 : 0, x, y, r, evo ? 3 : 2.2);
    this.push(K_RING, RING_QUAKE, x, y, r * 1.2, 0.35);
  }

  blast(x: number, y: number, r: number, ice: boolean): void {
    this.push(K_BLAST, ice ? 1 : 0, x, y, r, 0.3);
  }

  draw(w: World, alpha: number, dt: number, L: WeaponLayers, lighting: Lighting, hx: number, hy: number): void {
    this.time += dt;
    const inv = this.inv;
    const A = this.art.weapons;
    const time = this.time;

    // ---- 地裂（镇岳）：地面上的墨痕
    for (const z of w.zones) {
      const k = (z.r * 2) / A.crack.frame.width;
      L.ground.add(A.crack, z.x, z.y, k, k * 0.75, packColor(0xffffff, Math.min(1, z.life / z.max + 0.2) * 0.85));
    }

    // ---- 一次性效果
    let i = 0;
    while (i < this.n) {
      const t = (this.t[i] as number) + dt;
      const life = this.life[i] as number;
      if (t >= life) {
        this.removeAt(i);
        continue;
      }
      this.t[i] = t;
      const u = t / life;
      const x = this.x[i] as number;
      const y = this.y[i] as number;
      const r = this.r[i] as number;
      const sub = this.sub[i] as number;
      const kind = this.kind[i];
      if (kind === K_RING) {
        if (sub === RING_TAIJI) {
          // 太极：在主角脚下转一圈后淡出
          const k = (Math.min(1, u * 3) * r * 0.5) / A.taiji.frame.width;
          L.body.add(A.taiji, hx, hy, k, k * 0.6, packColor(0xffffff, (1 - u) * 0.85), time * 2.5);
          L.glow.add(A.ring, hx, hy, (r * 2 * u) / A.ring.frame.width, (r * 2 * u * 0.6) / A.ring.frame.width, packColor(0xffd98a, 1 - u));
        } else {
          const rr = 12 + (r - 12) * (1 - (1 - u) * (1 - u));
          const k = (rr * 2) / A.ring.frame.width;
          L.glow.add(A.ring, x, y, k, k, packColor(RING_COLOR[sub] ?? 0xffffff, (1 - u) * (sub === RING_BIGBELL || sub === RING_ULT ? 1 : 0.85)));
          if (sub === RING_BELL || sub === RING_BIGBELL) {
            const ki = (rr * 1.9) / A.ringInk.frame.width;
            L.ground.add(A.ringInk, x, y, ki, ki, packColor(0x3e5a7e, (1 - u) * 0.35), this.rot[i] as number);
          }
          if (sub === RING_ULT || sub === RING_BIGBELL) lighting.add(x, y, rr * 1.1, RING_COLOR[sub] ?? 0xffffff, (1 - u) * 0.8);
        }
      } else if (kind === K_MARK) {
        // 山印落地：朱砂印痕，慢慢淡去
        const k = (r * 0.9) / A.sealMark.frame.width;
        const fade = u < 0.7 ? 1 : 1 - (u - 0.7) / 0.3;
        L.ground.add(A.sealMark, x, y, k, k * 0.62, packColor(0xffffff, fade * 0.9), (this.rot[i] as number) * 0.15 - 0.15);
      } else {
        const k = (r * 2 * (0.5 + u * 0.7)) / A.blast.frame.width;
        const c = sub ? 0x6fb8ff : 0xff8a3d;
        L.glow.add(A.blast, x, y, k, k, packColor(c, 1 - u));
        lighting.add(x, y, r * 1.6, c, (1 - u) * 0.8);
      }
      i++;
    }

    // ---- 山印预警与下落的石印
    for (const s of w.seals) {
      const k = (s.r * 2) / A.warn.frame.width;
      const pulse = 0.55 + 0.25 * Math.sin(time * 18);
      const show = s.t > -0.05 ? 1 : 0.4;
      L.glow.add(A.warn, s.x, s.y, k, k * 0.62, packColor(0xc9925a, pulse * show));
      if (s.t > 0) {
        const f = Math.min(1, s.t / s.life);
        const drop = (1 - f) * (1 - f) * 150;
        const tex = s.evo ? A.sealEvo : A.seal;
        const sk = inv * (s.evo ? 1.3 : 1) * (0.8 + f * 0.2);
        L.body.add(tex, s.x, s.y - drop, sk, sk, packColor(0xffffff, Math.min(1, f * 3)));
      }
    }

    // ---- 飞剑
    const sh = w.shots;
    for (let k = 0; k < sh.n; k++) {
      const x = (sh.px[k] as number) + ((sh.x[k] as number) - (sh.px[k] as number)) * alpha;
      const y = (sh.py[k] as number) + ((sh.y[k] as number) - (sh.py[k] as number)) * alpha;
      const ang = Math.atan2(sh.vy[k] as number, sh.vx[k] as number);
      const big = sh.big[k] === 1;
      const bonus = sh.bonus[k] === 1;
      const trailC = big ? 0xffd98a : bonus ? 0xcfe3f5 : 0xe9f1ff;
      L.glow.add(A.swordTrail, x, y, inv * (big ? 1.4 : 1.1), inv * (big ? 1.2 : 0.9), packColor(trailC, 0.75), ang);
      L.body.add(big ? A.swordEvo : A.sword, x, y, inv * (big ? 1.15 : 1), inv, packColor(0xffffff, 1), ang);
      lighting.add(x, y, big ? 40 : 28, big ? 0xffd98a : 0xcfe3f5, 0.5);
    }

    // ---- 纸鹤
    for (const wp of w.weapons) {
      if (wp.id !== 'crane') continue;
      const frames = wp.evo ? A.craneEvo : A.crane;
      for (let c = 0; c < wp.cranes.length; c++) {
        const cr = wp.cranes[c];
        if (!cr) continue;
        const x = cr.px + (cr.x - cr.px) * alpha;
        const y = cr.py + (cr.y - cr.py) * alpha;
        const tex = frames[Math.floor(time * 12 + c * 1.3) % frames.length] as Texture;
        // 向左飞时上下翻转，保持鹤背朝上
        const flip = Math.cos(cr.ang) < 0 ? -1 : 1;
        L.body.add(tex, x, y - 6, inv, inv * flip, packColor(0xffffff, 1), cr.ang);
        if (wp.evo) L.glow.add(this.art.vfx.glow, x, y - 6, 0.3, 0.3, packColor(0xffd98a, 0.35));
      }
    }

    // ---- 护盾
    const p = w.player;
    if (p.shield > 0) {
      const k = (p.r * 3.2) / A.shield.frame.width;
      L.glow.add(A.shield, hx, hy - 14, k, k, packColor(0xc9925a, 0.35 + 0.15 * Math.sin(time * 4)), time * 0.6);
    }

    // ---- 拾取物
    for (const it of w.pickups) {
      const bob = Math.sin(time * 3 + it.x * 0.1) * 2;
      const tex = it.kind === 'chest' ? A.chest : it.kind === 'bell' ? A.soulbell : A.lotus;
      L.body.add(tex, it.x, it.y + bob - 2, inv, inv, packColor(0xffffff, 1));
      const c = it.kind === 'chest' ? 0xffd98a : it.kind === 'bell' ? 0x5fd4c4 : 0xffb0c0;
      L.glow.add(this.art.vfx.glow, it.x, it.y - 8, 0.5, 0.5, packColor(c, 0.45));
      lighting.add(it.x, it.y, it.kind === 'chest' ? 60 : 36, c, 0.6);
    }

    // ---- 夜主弹幕
    for (const f of w.foes) {
      const x = f.px + (f.x - f.px) * alpha;
      const y = f.py + (f.y - f.py) * alpha;
      L.glow.add(this.art.vfx.glow, x, y, 0.35, 0.35, packColor(0xff6b5a, 0.9));
      L.glow.add(this.art.vfx.spark, x, y, 1.2, 1.2, packColor(0xffe0c0, 1));
    }
  }

  private removeAt(i: number): void {
    const last = --this.n;
    if (i === last) return;
    this.kind[i] = this.kind[last] as number;
    this.sub[i] = this.sub[last] as number;
    this.x[i] = this.x[last] as number;
    this.y[i] = this.y[last] as number;
    this.r[i] = this.r[last] as number;
    this.t[i] = this.t[last] as number;
    this.life[i] = this.life[last] as number;
    this.rot[i] = this.rot[last] as number;
  }

  clear(): void {
    this.n = 0;
  }
}
