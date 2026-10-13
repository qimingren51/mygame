// 冒烟测试：在 /mygame/lantern-next/ 下加载构建好的页面，走一遍标题 → 游戏 → 返回 → 跑分。

import { expect, test, type Page } from '@playwright/test';

interface Debug {
  mode: string;
  world: { player: { x: number; y: number }; enemies: { count: number } };
  presenter: { stats: { lights: number; actors: number } };
  artReport: { vfx: boolean; ground: boolean; paper: boolean; actors: boolean; errors: string[] };
}

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('response', (r) => {
    if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
  });
  return errors;
}

const dbg = (page: Page) => page.evaluate(() => (window as unknown as { __lantern: Debug }).__lantern);

test('标题、游戏、返回', async ({ page }, info) => {
  const errors = watchErrors(page);
  await page.goto('./');
  await page.waitForFunction(() => 'world' in ((window as unknown as { __lantern?: object }).__lantern ?? {}));
  await expect(page.locator('#title')).toBeVisible();
  await expect(page.locator('a.back-link')).toHaveAttribute('href', '../');

  const art = await page.evaluate(() => (window as unknown as { __lantern: Debug }).__lantern.artReport);
  expect(art.errors).toEqual([]);
  expect(art.vfx && art.ground && art.paper).toBe(true);

  // 标题后面场景在跑：主角自动走动、光源和角色都在画
  await page.waitForTimeout(1500);
  const bg = await dbg(page);
  expect(bg.mode).toBe('title');
  expect(bg.presenter.stats.lights).toBeGreaterThan(0);
  expect(bg.presenter.stats.actors).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('title.png') });

  await page.locator('#start-btn').click();
  await expect(page.locator('#game-hud .pause-btn')).toBeVisible();
  await expect(page.locator('#game-hud .ult-btn')).toBeVisible();
  // 触屏摇杆：在左半屏按住向右拖
  const start = (await dbg(page)).world.player.x;
  await page.mouse.move(200, 250);
  await page.mouse.down();
  await page.mouse.move(260, 250, { steps: 4 });
  await page.waitForTimeout(1200);
  await page.mouse.up();
  const moved = (await dbg(page)).world.player.x - start;
  expect(moved).toBeGreaterThan(40);
  await page.screenshot({ path: info.outputPath('play.png') });

  // 升级三选一：直接给经验，等卡片出现，点第一张
  await page.evaluate(() => {
    (window as unknown as { __lantern: { world: { pendingLevels: number } } }).__lantern.world.pendingLevels = 1;
  });
  await expect(page.locator('#levelup-screen .card').first()).toBeVisible();
  const cards = await page.locator('#levelup-screen .card').count();
  expect(cards).toBeGreaterThanOrEqual(3);
  await page.screenshot({ path: info.outputPath('levelup.png') });
  await page.locator('#levelup-screen .card').first().click();
  await expect(page.locator('#levelup-screen')).toBeHidden();
  expect((await dbg(page)).mode).toBe('play');

  // 暂停 → 放弃本局 → 回到标题
  await page.locator('#game-hud .pause-btn').click();
  await expect(page.locator('#pause-screen')).toBeVisible();
  await page.locator('#pause-screen [data-act="quit"]').click();
  await expect(page.locator('#title')).toBeVisible();
  expect(errors).toEqual([]);
});

test('跑分出结果卡片', async ({ page }, info) => {
  const errors = watchErrors(page);
  await page.goto('./?benchStage=1500');
  await page.waitForFunction(() => 'world' in ((window as unknown as { __lantern?: object }).__lantern ?? {}));
  await page.locator('#bench-btn').click();
  await expect(page.locator('#bench-card')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.bench-table tbody tr')).toHaveCount(4);
  const text = await page.locator('.bench-text').textContent();
  expect(text).toContain('1500');
  await page.screenshot({ path: info.outputPath('bench.png') });
  await page.locator('#bench-card [data-act="back"]').click();
  await expect(page.locator('#title')).toBeVisible();
  expect(errors).toEqual([]);
});

test('竖屏时提示横过来', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  await page.goto('./');
  await expect(page.locator('.rotate-hint')).toBeVisible();
  await ctx.close();
});

test('连续宝箱可以逐个确认，连续进化会重新计时', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => 'world' in ((window as unknown as { __lantern?: object }).__lantern ?? {}));
  await page.locator('#start-btn').click();
  await page.evaluate(() => {
    const w = (window as unknown as { __lantern: { world: import('../../src/sim/state').World } }).__lantern.world;
    w.god = true;
    w.chestQueue = 2;
  });
  const ok = page.locator('#chest-screen [data-act="ok"]');
  await expect(ok).toBeEnabled();
  await page.evaluate(() => { document.querySelector('#chest-screen button')?.setAttribute('data-first', 'true'); });
  await ok.click();
  await expect(page.locator('#chest-screen [data-first]')).toHaveCount(0);
  await expect(ok).toBeEnabled();
  await ok.click();
  await expect(page.locator('#chest-screen')).toBeHidden();
  await page.waitForFunction(() =>
    (window as unknown as { __lantern: { world: import('../../src/sim/state').World } }).__lantern.world.phase === 'play');

  await page.evaluate(() => {
    const w = (window as unknown as { __lantern: { world: import('../../src/sim/state').World } }).__lantern.world;
    // 相同法器也算两个演出实例，不能依赖法器名变化来刷新。
    w.pendingEvos.push(w.weapons[0]!.id, w.weapons[0]!.id);
    w.pendingLevels = 1;
  });
  await page.locator('#levelup-screen [data-act="skip"]').click();
  await expect(page.locator('#evo-screen')).toBeVisible();
  const firstId = await page.evaluate(() =>
    (window as unknown as { __lantern: { world: import('../../src/sim/state').World } }).__lantern.world.choiceId);
  await page.waitForFunction((id) => {
    const w = (window as unknown as { __lantern: { world: import('../../src/sim/state').World } }).__lantern.world;
    return w.choiceId > id && w.phase === 'evo';
  }, firstId);
  await page.waitForTimeout(300);
  await expect(page.locator('#evo-screen')).toBeVisible();
  await expect(page.locator('#evo-screen')).toBeHidden({ timeout: 5000 });
});
