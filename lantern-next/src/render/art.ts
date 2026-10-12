// 美术素材集：渲染层只通过这个接口取贴图。
// 现在由 placeholders.ts 用代码生成占位图；Blender 图集就绪后由 atlas.ts 加载，帧命名一致。

import type { Texture } from 'pixi.js';

/** 8 个朝向，屏幕坐标 y 向下：0=东 1=东南 2=南 3=西南 4=西 5=西北 6=北 7=东北 */
export const DIRS = ['E', 'SE', 'S', 'SW', 'W', 'NW', 'N', 'NE'] as const;
export type Dir = (typeof DIRS)[number];

export interface Point {
  x: number;
  y: number;
}

/** 贴图上的挂点，单位是贴图像素，相对锚点（脚底） */
export type Socket = Point;

export interface ActorAnim {
  frames: Texture[];
  /** 白色剪影帧，受击闪白用；与 frames 一一对应 */
  flash: Texture[];
}

export interface ArtSet {
  /** 贴图像素 / 世界单位 */
  pxPerUnit: number;
  hero: {
    idle: Texture[][]; // [方向][帧]
    walk: Texture[][];
    /** 灯笼挂点 [动画名][方向][帧] */
    lantern: { idle: Socket[][]; walk: Socket[][] };
  };
  enemies: Record<'shade' | 'wisp', ActorAnim & { eyes: Socket }>;
  vfx: {
    light: Texture;
    glow: Texture;
    eyes: Texture;
    shadow: Texture;
    spark: Texture;
    gem: Texture[]; // 小、中、大
    flame: Texture[];
    ink: Texture[];
    lantern: Texture;
  };
  /** 竖立的道具，和角色在同一张图集上（ParticleContainer 要求同一贴图源），参与 y 排序 */
  props: {
    rocks: Texture[];
    stoneLantern: Texture;
    /** 石灯笼火光的位置，贴图像素，相对锚点 */
    stoneLanternFlame: Socket;
  };
  /** 平铺在地面上的装饰 */
  ground: {
    paper: Texture;
    wash: Texture[];
    grass: Texture[];
  };
}
