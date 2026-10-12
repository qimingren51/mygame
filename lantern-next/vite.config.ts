import { execSync } from 'node:child_process';
import { basename, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const here = dirname(fileURLToPath(import.meta.url));
// 文件夹名决定存档前缀：预览期 lantern-next_，切换为 lantern/ 后自动变回 lantern_
const folder = basename(here);

let buildId = 'dev';
try {
  buildId = execSync('git rev-parse --short HEAD', { cwd: here }).toString().trim();
} catch {
  // 不在 git 仓库里时使用 dev
}

export default defineConfig({
  // 相对路径：同一份构建产物放在任何子路径下都能用
  base: './',
  define: {
    __BUILD_ID__: JSON.stringify(buildId),
    __STORE_PREFIX__: JSON.stringify(`${folder}_`),
  },
  build: {
    target: ['es2022', 'safari15'],
    assetsInlineLimit: 0,
    sourcemap: true,
  },
  server: { host: true },
  plugins: [
    {
      // 预览版不让搜索引擎收录
      name: 'noindex-preview',
      transformIndexHtml(html) {
        if (folder === 'lantern') return html;
        return html.replace('<head>', '<head>\n  <meta name="robots" content="noindex">');
      },
    },
  ],
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.ts', 'tests/sim/**/*.test.ts'],
    benchmark: { include: ['tests/sim/**/*.bench.ts'] },
  },
});
