// 地面：宣纸平铺 + 按区块生成的水墨装饰（晕染、草）和竖立的道具（石块、石灯笼）。
// 区块内容只由区块坐标决定，走开再回来看到的是同一幅画。

import { Container, Sprite, TilingSprite } from 'pixi.js';
import { hash2 } from '../core/math';
import { Rng } from '../core/rng';
import type { ArtSet } from './art';
import type { Camera } from './camera';

const CHUNK = 512; // 世界单位

export interface Prop {
  kind: 'rock' | 'stoneLantern';
  x: number;
  y: number;
  variant: number;
  /** 镜像 */
  flip: boolean;
  /** 火光闪烁的相位 */
  phase: number;
}

interface Chunk {
  sprites: Sprite[];
  props: Prop[];
}

export class Ground {
  readonly paper: TilingSprite;
  /** 平铺在地面上的装饰（在影子和角色下面） */
  readonly decals = new Container();
  private readonly chunks = new Map<number, Chunk>();
  private readonly spritePool: Sprite[] = [];
  /** 当前已生成区块里的全部道具，角色层每帧从这里取可见的 */
  readonly props: Prop[] = [];
  private propsDirty = true;
  private readonly inv: number;
  private readonly art: ArtSet;

  constructor(art: ArtSet) {
    this.art = art;
    this.inv = 1 / art.pxPerUnit;
    this.paper = new TilingSprite({ texture: art.ground.paper, width: 1, height: 1 });
    this.paper.tileScale.set(this.inv);
  }

  update(cam: Camera): void {
    // 宣纸铺满可见范围，纹理锚定在世界原点
    const left = cam.x - cam.viewW / 2 - 16;
    const top = cam.y - cam.viewH / 2 - 16;
    const p = this.paper;
    p.position.set(left, top);
    p.width = cam.viewW + 32;
    p.height = cam.viewH + 32;
    p.tilePosition.set(-left, -top);

    // 需要的区块：可见范围外再多一圈
    const c0x = Math.floor((left - 64) / CHUNK);
    const c1x = Math.floor((left + cam.viewW + 96) / CHUNK);
    const c0y = Math.floor((top - 64) / CHUNK);
    const c1y = Math.floor((top + cam.viewH + 160) / CHUNK);
    for (const [key, ch] of this.chunks) {
      const cx = Math.floor(key / 65536) - 32768;
      const cy = (key % 65536) - 32768;
      if (cx < c0x - 1 || cx > c1x + 1 || cy < c0y - 1 || cy > c1y + 1) this.retire(key, ch);
    }
    for (let cy = c0y; cy <= c1y; cy++) {
      for (let cx = c0x; cx <= c1x; cx++) {
        const key = (cx + 32768) * 65536 + (cy + 32768);
        if (!this.chunks.has(key)) this.chunks.set(key, this.build(cx, cy));
      }
    }
    if (this.propsDirty) {
      this.props.length = 0;
      for (const ch of this.chunks.values()) for (const pr of ch.props) this.props.push(pr);
      this.propsDirty = false;
    }
  }

  private sprite(): Sprite {
    const s = this.spritePool.pop() ?? new Sprite();
    this.decals.addChild(s);
    return s;
  }

  private build(cx: number, cy: number): Chunk {
    const rng = new Rng(hash2(cx * 7 + 3, cy * 13 + 5) || 1);
    const ox = cx * CHUNK;
    const oy = cy * CHUNK;
    const sprites: Sprite[] = [];
    const props: Prop[] = [];
    const g = this.art.ground;
    const inv = this.inv;

    const washes = 1 + rng.int(3);
    for (let i = 0; i < washes; i++) {
      const s = this.sprite();
      s.texture = rng.pick(g.wash);
      s.anchor.set(0.5);
      const k = rng.range(0.9, 1.8);
      s.scale.set(k * inv * (rng.chance(0.5) ? -1 : 1), k * inv * rng.range(0.8, 1.1));
      s.rotation = rng.range(-0.25, 0.25);
      s.alpha = rng.range(0.55, 1);
      s.position.set(ox + rng.range(0, CHUNK), oy + rng.range(0, CHUNK));
      sprites.push(s);
    }
    const tufts = 4 + rng.int(6);
    for (let i = 0; i < tufts; i++) {
      // 草成丛出现
      const bx = ox + rng.range(0, CHUNK);
      const by = oy + rng.range(0, CHUNK);
      const n = 1 + rng.int(3);
      for (let j = 0; j < n; j++) {
        const s = this.sprite();
        s.texture = rng.pick(g.grass);
        s.anchor.set(0.5, 1);
        const k = rng.range(0.7, 1.15);
        s.scale.set(k * inv * (rng.chance(0.5) ? -1 : 1), k * inv);
        s.rotation = 0;
        s.alpha = rng.range(0.7, 1);
        s.position.set(bx + rng.range(-18, 18), by + rng.range(-8, 8));
        sprites.push(s);
      }
    }
    const rocks = rng.int(3);
    for (let i = 0; i < rocks; i++) {
      props.push({
        kind: 'rock',
        x: ox + rng.range(0, CHUNK),
        y: oy + rng.range(0, CHUNK),
        variant: rng.int(this.art.props.rocks.length),
        flip: rng.chance(0.5),
        phase: 0,
      });
    }
    // 出生点附近不放石灯笼，免得一开局就有一盏
    if (rng.chance(0.3) && !(cx === 0 && cy === 0) && !(cx === -1 && cy === -1)) {
      props.push({
        kind: 'stoneLantern',
        x: ox + rng.range(64, CHUNK - 64),
        y: oy + rng.range(64, CHUNK - 64),
        variant: 0,
        flip: rng.chance(0.5),
        phase: rng.range(0, 10),
      });
    }
    this.propsDirty = true;
    return { sprites, props };
  }

  private retire(key: number, ch: Chunk): void {
    for (const s of ch.sprites) {
      this.decals.removeChild(s);
      this.spritePool.push(s);
    }
    this.chunks.delete(key);
    this.propsDirty = true;
  }
}
