// 检查 public/assets 里打包好的图集：清单、帧范围、动画序列、游戏需要的帧名、体积预算。

import { existsSync, readFileSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const dir = new URL('../../public/assets/', import.meta.url);
const read = (name: string) => readFileSync(new URL(name, dir));

interface Frame {
  frame: { x: number; y: number; w: number; h: number };
  spriteSourceSize: { x: number; y: number; w: number; h: number };
  sourceSize: { w: number; h: number };
  anchor: { x: number; y: number };
}

interface Sheet {
  frames: Record<string, Frame>;
  animations: Record<string, string[]>;
  meta: { image: string; size: { w: number; h: number } };
}

/** 读 PNG 文件头里的宽高 */
function pngSize(buf: Buffer): { w: number; h: number } {
  expect(buf.subarray(1, 4).toString('latin1')).toBe('PNG');
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

const index = existsSync(new URL('index.json', dir))
  ? (JSON.parse(read('index.json').toString('utf8')) as { atlases: string[]; paper: boolean })
  : { atlases: [], paper: false };

const REQUIRED: Record<string, string[]> = {
  vfx: ['light', 'glow', 'eyes', 'shadow', 'spark', 'gem_0', 'gem_1', 'gem_2', 'flame_0', 'flame_1', 'flame_2', 'flame_3', 'ink_0', 'ink_1', 'ink_2', 'lantern'].map((n) => `vfx/${n}`),
  ground: ['ground/wash_0', 'ground/grass_0'],
  actors: [
    ...['E', 'SE', 'S', 'SW', 'W', 'NW', 'N', 'NE'].flatMap((d) => [`hero/idle_${d}_00`, `hero/walk_${d}_07`]),
    'shade/float_E_00',
    'shade/float_E_00_flash',
    'wisp/float_E_00',
    'wisp/float_E_00_flash',
    'rock_a/idle_S_00',
    'stone_lantern/idle_S_00',
  ],
};

describe.each(index.atlases)('图集 %s', (name) => {
  const sheet = JSON.parse(read(`${name}.json`).toString('utf8')) as Sheet;
  const img = pngSize(read(sheet.meta.image));

  it('图片尺寸与 JSON 一致，且不超过 2048²', () => {
    expect(img).toEqual(sheet.meta.size);
    expect(img.w).toBeLessThanOrEqual(2048);
    expect(img.h).toBeLessThanOrEqual(2048);
  });

  it('每一帧都在图片范围内，裁边信息自洽', () => {
    for (const [key, f] of Object.entries(sheet.frames)) {
      const r = f.frame;
      expect(r.x >= 0 && r.y >= 0 && r.x + r.w <= img.w && r.y + r.h <= img.h, key).toBe(true);
      const s = f.spriteSourceSize;
      expect(s.w === r.w && s.h === r.h, key).toBe(true);
      expect(s.x + s.w <= f.sourceSize.w && s.y + s.h <= f.sourceSize.h, key).toBe(true);
      expect(f.anchor.x >= 0 && f.anchor.x <= 1 && f.anchor.y >= 0 && f.anchor.y <= 1, key).toBe(true);
    }
  });

  it('动画序列引用的帧都存在', () => {
    for (const [anim, list] of Object.entries(sheet.animations)) {
      for (const k of list) expect(sheet.frames[k], `${anim} → ${k}`).toBeDefined();
    }
  });

  it('包含游戏需要的帧', () => {
    for (const k of REQUIRED[name] ?? []) expect(sheet.frames[k], k).toBeDefined();
  });
});

describe('素材体积', () => {
  it('public/assets 合计不超过 2.5 MB', () => {
    let total = 0;
    const files = [...index.atlases.flatMap((n) => [`${n}.json`, `${n}.png`]), ...(index.paper ? ['paper.webp'] : [])];
    for (const f of files) total += statSync(new URL(f, dir)).size;
    expect(total).toBeLessThan(2.5 * 1024 * 1024);
  });
});
