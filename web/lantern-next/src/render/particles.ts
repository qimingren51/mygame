// 粒子层：一个 ParticleContainer + 一池预先创建的 Particle。
// 每帧 begin() → add() 若干次 → end()；粒子对象反复使用，不产生垃圾。
// 同一层的所有贴图必须来自同一张图集（ParticleContainer 的限制）。

import { Particle, ParticleContainer, Rectangle, type BLEND_MODES, type Texture } from 'pixi.js';

/** 把 0xRRGGBB 和透明度打包成 Particle.color 的格式（ABGR）。 */
export function packColor(rgb: number, alpha = 1): number {
  const bgr = ((rgb & 0xff) << 16) | (rgb & 0xff00) | ((rgb >>> 16) & 0xff);
  return (bgr + (((alpha < 0 ? 0 : alpha > 1 ? 1 : alpha) * 255) << 24)) >>> 0;
}

export const WHITE = packColor(0xffffff, 1);

export class ParticleLayer {
  readonly view: ParticleContainer<Particle>;
  private readonly pool: Particle[] = [];
  private n = 0;
  readonly capacity: number;

  constructor(texture: Texture, capacity: number, blendMode: BLEND_MODES = 'normal') {
    this.capacity = capacity;
    this.view = new ParticleContainer<Particle>({
      texture,
      // 贴图、位置、大小、颜色每帧都在变
      dynamicProperties: { position: true, vertex: true, rotation: true, uvs: true, color: true },
    });
    this.view.blendMode = blendMode;
    // ParticleContainer 不自己计算包围盒；给一个足够大的范围，避免被裁剪或让滤镜失效
    this.view.boundsArea = new Rectangle(-1e6, -1e6, 2e6, 2e6);
  }

  get count(): number {
    return this.n;
  }

  begin(): void {
    this.n = 0;
  }

  /** 取一个粒子并设置常用字段；超过容量时返回 null。锚点取贴图的 defaultAnchor。 */
  add(tex: Texture, x: number, y: number, sx: number, sy: number, color: number, rotation = 0): Particle | null {
    if (this.n >= this.capacity) return null;
    let p = this.pool[this.n];
    if (!p) {
      p = new Particle({ texture: tex });
      this.pool.push(p);
    }
    this.n++;
    p.texture = tex;
    p.x = x;
    p.y = y;
    p.scaleX = sx;
    p.scaleY = sy;
    p.anchorX = tex.defaultAnchor?.x ?? 0;
    p.anchorY = tex.defaultAnchor?.y ?? 0;
    p.rotation = rotation;
    p.color = color;
    return p;
  }

  end(): void {
    const list = this.view.particleChildren;
    const n = this.n;
    for (let i = 0; i < n; i++) list[i] = this.pool[i] as Particle;
    list.length = n;
  }
}
