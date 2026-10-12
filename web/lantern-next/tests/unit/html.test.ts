import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('index.html', () => {
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8');

  it('只使用相对路径（站点部署在 /mygame/ 子路径下）', () => {
    expect(html).not.toMatch(/(?:src|href)=["']\/(?!\/)/);
  });

  it('提供返回首页的链接', () => {
    expect(html).toContain('href="../"');
  });
});
