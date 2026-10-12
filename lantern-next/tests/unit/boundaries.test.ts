// 模拟层必须是纯逻辑：不能用 Math.random，也不能碰 DOM、Pixi、界面、音频、平台层。
// 这样同一个种子在浏览器和 Node 里能跑出完全相同的结果。

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = new URL('../../src/', import.meta.url).pathname;
const FORBIDDEN = [
  /Math\.random/,
  /\bdocument\./,
  /\bwindow\./,
  /localStorage/,
  /from ['"]pixi/,
  /from ['"]\.\.\/(render|ui|audio|platform|debug)\//,
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p) : p.endsWith('.ts') ? [p] : [];
  });
}

describe('模块边界', () => {
  for (const area of ['sim', 'data']) {
    it(`src/${area}/ 不依赖随机源和表现层`, () => {
      for (const file of files(join(SRC, area))) {
        const text = readFileSync(file, 'utf8');
        for (const re of FORBIDDEN) expect(text, `${file} 命中 ${re}`).not.toMatch(re);
      }
    });
  }
});
