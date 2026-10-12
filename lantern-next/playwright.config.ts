// 端到端测试：先在仓库根目录 node scripts/build-site.mjs 组装整站，
// 这里起 serve-site 以线上相同的 /mygame/ 路径访问构建后的页面。
// 运行：npm run e2e

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8130);

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: 'test-results',
  use: {
    baseURL: `http://localhost:${PORT}/mygame/lantern-next/`,
    // 手机横屏：844×390，3 倍像素（iPhone 14 一类）
    ...devices['iPhone 14 landscape'],
    // 设备描述里默认是 WebKit；这里用预装的 Chromium 跑，只验证功能，不代表性能
    browserName: 'chromium',
    defaultBrowserType: 'chromium',
    launchOptions: {
      executablePath: process.env.PW_CHROMIUM,
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
  },
  webServer: {
    command: `node ../scripts/serve-site.mjs`,
    env: { PORT: String(PORT) },
    url: `http://localhost:${PORT}/mygame/`,
    reuseExistingServer: true,
  },
});
