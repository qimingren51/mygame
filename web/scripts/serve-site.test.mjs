import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { Writable } from 'node:stream';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSiteServer } from './serve-site.mjs';

test('预览服务器拒绝非法编码、越界路径及符号链接，并继续提供正常页面', async (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'lantern-site-'));
  const site = join(dir, '_site');
  const privateDir = join(dir, '_site-private');
  mkdirSync(join(site, 'game'), { recursive: true });
  mkdirSync(privateDir);
  writeFileSync(join(site, 'index.html'), '首页');
  writeFileSync(join(site, 'game/index.html'), '游戏');
  writeFileSync(join(privateDir, 'secret'), '站点外文件');
  symlinkSync(privateDir, join(site, 'outside'), 'dir');
  symlinkSync(join(privateDir, 'secret'), join(site, 'secret'));
  const server = createSiteServer(site);
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  // 直接调用真实请求处理器；不占端口，也可在禁止监听的沙箱里运行。
  const request = (path) => new Promise((resolve, reject) => {
    let body = '';
    let status;
    let headers = {};
    const res = new Writable({ write(chunk, _encoding, done) { body += chunk; done(); } });
    res.writeHead = (code, values = {}) => { status = code; headers = values; res.headersSent = true; return res; };
    res.once('finish', () => resolve({ status, body, location: headers.Location }));
    res.once('error', reject);
    server.emit('request', { url: path }, res);
  });
  for (const path of ['/mygame/%', '/mygame/%E0%A4', '/mygame/%00']) {
    assert.equal((await request(path)).status, 400);
  }
  for (const path of ['/mygame/../_site-private/secret', '/mygame/%2e%2e/_site-private/secret', '/mygame/outside/secret', '/mygame/secret']) {
    assert.equal((await request(path)).status, 403);
  }
  assert.equal((await request('/mygame/missing')).status, 404);
  assert.equal((await request('/mygame/game')).location, '/mygame/game/');
  assert.equal((await request('/mygame/game/')).body, '游戏');
  // 路径检查后、流打开前文件消失，错误也不能变成未捕获异常。
  writeFileSync(join(site, 'vanish'), '即将删除');
  const pending = request('/mygame/vanish');
  rmSync(join(site, 'vanish'));
  assert.equal((await pending).status, 500);
  assert.equal((await request('/mygame/')).body, '首页');
});
