// 角色层：主角、妖物、竖立的道具，按脚底 y 排序后绘制。
// 两种实现放在同一个接口后面，里程碑 1 在真机上对比：
//   B（默认）：对象池里的 Sprite；
//   A：一个 ParticleContainer（要求所有贴图来自同一张图集）。
// 两者都不对子节点排序：先把本帧要画的东西按 y 排好，再按顺序填进固定的对象池。

import { Container, Sprite, type Texture } from 'pixi.js';
import { packColor, ParticleLayer } from './particles';

export type ActorMode = 'A' | 'B';

const ID_BITS = 4096; // 每帧最多 4096 个角色

export abstract class ActorBatch {
  abstract readonly view: Container;
  protected n = 0;
  protected readonly tex: (Texture | null)[] = new Array<Texture | null>(ID_BITS).fill(null);
  protected readonly x = new Float32Array(ID_BITS);
  protected readonly y = new Float32Array(ID_BITS);
  protected readonly sx = new Float32Array(ID_BITS);
  protected readonly sy = new Float32Array(ID_BITS);
  protected readonly tint = new Uint32Array(ID_BITS);
  protected readonly alpha = new Float32Array(ID_BITS);
  private readonly keys = new Float64Array(ID_BITS);

  get count(): number {
    return this.n;
  }

  begin(): void {
    this.n = 0;
  }

  /** sortY 是脚底的世界 y（贴图本身可能画在悬浮高度上） */
  push(tex: Texture, x: number, y: number, sx: number, sy: number, sortY: number, tint = 0xffffff, alpha = 1): void {
    const i = this.n;
    if (i >= ID_BITS) return;
    this.tex[i] = tex;
    this.x[i] = x;
    this.y[i] = y;
    this.sx[i] = sx;
    this.sy[i] = sy;
    this.tint[i] = tint;
    this.alpha[i] = alpha;
    // 键 = 量化后的 y × 4096 + 序号；Float64Array 的 sort 是数值排序
    this.keys[i] = Math.floor(sortY * 8) * ID_BITS + i;
    this.n++;
  }

  end(): void {
    const n = this.n;
    const keys = this.keys.subarray(0, n);
    keys.sort();
    this.write(keys, n);
  }

  protected static index(key: number): number {
    return key - Math.floor(key / ID_BITS) * ID_BITS;
  }

  protected abstract write(sorted: Float64Array, n: number): void;
}

/** 实现 B：Sprite 对象池 */
export class SpriteActors extends ActorBatch {
  readonly view = new Container();
  private readonly pool: Sprite[] = [];

  protected write(sorted: Float64Array, n: number): void {
    const pool = this.pool;
    while (pool.length < n) {
      const s = new Sprite();
      pool.push(s);
      this.view.addChild(s);
    }
    for (let k = 0; k < n; k++) {
      const i = ActorBatch.index(sorted[k] as number);
      const s = pool[k] as Sprite;
      const t = this.tex[i] as Texture;
      if (s.texture !== t) {
        s.texture = t;
        const ax = t.defaultAnchor?.x ?? 0;
        const ay = t.defaultAnchor?.y ?? 0;
        if (s.anchor.x !== ax || s.anchor.y !== ay) s.anchor.set(ax, ay);
      }
      s.visible = true;
      s.position.set(this.x[i] as number, this.y[i] as number);
      s.scale.set(this.sx[i] as number, this.sy[i] as number);
      const tint = this.tint[i] as number;
      if (s.tint !== tint) s.tint = tint;
      s.alpha = this.alpha[i] as number;
    }
    for (let k = n; k < pool.length; k++) (pool[k] as Sprite).visible = false;
  }
}

/** 实现 A：ParticleContainer */
export class ParticleActors extends ActorBatch {
  private readonly layer: ParticleLayer;
  readonly view: Container;

  constructor(atlasTexture: Texture) {
    super();
    this.layer = new ParticleLayer(atlasTexture, ID_BITS);
    this.view = this.layer.view;
  }

  protected write(sorted: Float64Array, n: number): void {
    const layer = this.layer;
    layer.begin();
    for (let k = 0; k < n; k++) {
      const i = ActorBatch.index(sorted[k] as number);
      layer.add(
        this.tex[i] as Texture,
        this.x[i] as number,
        this.y[i] as number,
        this.sx[i] as number,
        this.sy[i] as number,
        packColor(this.tint[i] as number, this.alpha[i] as number),
      );
    }
    layer.end();
  }
}
