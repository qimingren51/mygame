// 镜头：跟随插值后的主角位置，按屏幕高度决定缩放，叠加震屏。

import type { Container } from 'pixi.js';
import { clamp } from '../core/math';
import { VIEW_HEIGHT } from '../data/balance';

export class Camera {
  /** 镜头中心（世界坐标） */
  x = 0;
  y = 0;
  /** 每个世界单位对应的 CSS 像素 */
  zoom = 1;
  screenW = 1;
  screenH = 1;
  /** 设备像素比（画面分辨率）；镜头平移按设备像素取整，避免静止的地面闪烁 */
  resolution = 1;
  private shakeAmp = 0;
  private shakeX = 0;
  private shakeY = 0;

  resize(cssW: number, cssH: number, resolution: number): void {
    this.screenW = cssW;
    this.screenH = cssH;
    this.resolution = resolution;
    this.zoom = clamp(cssH / VIEW_HEIGHT, 0.75, 1.8);
  }

  /** 可见范围（世界单位） */
  get viewW(): number {
    return this.screenW / this.zoom;
  }

  get viewH(): number {
    return this.screenH / this.zoom;
  }

  shake(amount: number): void {
    this.shakeAmp = Math.min(14, Math.max(this.shakeAmp, amount));
  }

  update(targetX: number, targetY: number, dt: number): void {
    this.x = targetX;
    this.y = targetY;
    if (this.shakeAmp > 0.05) {
      this.shakeX = (Math.random() * 2 - 1) * this.shakeAmp;
      this.shakeY = (Math.random() * 2 - 1) * this.shakeAmp;
      this.shakeAmp *= Math.exp(-dt * 14);
    } else {
      this.shakeAmp = 0;
      this.shakeX = 0;
      this.shakeY = 0;
    }
  }

  /** 把镜头变换应用到一个容器上；scale 用于缩小的光照图。 */
  apply(c: Container, scale = 1): void {
    const z = this.zoom * scale;
    const snap = this.resolution * scale;
    const tx = (this.screenW / 2) * scale - (this.x + this.shakeX) * z;
    const ty = (this.screenH / 2) * scale - (this.y + this.shakeY) * z;
    c.scale.set(z);
    c.position.set(Math.round(tx * snap) / snap, Math.round(ty * snap) / snap);
  }

  /** 世界坐标 → 屏幕 CSS 像素 */
  toScreenX(wx: number): number {
    return this.screenW / 2 + (wx - this.x - this.shakeX) * this.zoom;
  }

  toScreenY(wy: number): number {
    return this.screenH / 2 + (wy - this.y - this.shakeY) * this.zoom;
  }

  /** 世界坐标的矩形是否在屏幕内（带边距，世界单位） */
  visible(wx: number, wy: number, margin: number): boolean {
    const hw = this.viewW / 2 + margin;
    const hh = this.viewH / 2 + margin;
    return wx > this.x - hw && wx < this.x + hw && wy > this.y - hh && wy < this.y + hh;
  }
}
