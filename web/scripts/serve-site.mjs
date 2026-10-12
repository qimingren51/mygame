#!/usr/bin/env node
// 在本地以 /mygame/ 路径提供 web/_site/，和 GitHub Pages 的线上路径一致。
// 用法：node web/scripts/serve-site.mjs   然后访问 http://localhost:8000/mygame/
// 环境变量 PORT 可以改端口。

import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = join(dirname(fileURLToPath(import.meta.url)), '..', '_site');
const BASE = '/mygame/';
const PORT = Number(process.env.PORT || 8000);

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.ogg': 'audio/ogg',
};

if (!existsSync(SITE)) {
  console.error('找不到 _site/，请先运行 node web/scripts/build-site.mjs');
  process.exit(1);
}

createServer((req, res) => {
  const url = decodeURIComponent((req.url || '/').split('?')[0]);
  if (!url.startsWith(BASE)) {
    res.writeHead(302, { Location: BASE });
    res.end();
    return;
  }
  let file = normalize(join(SITE, url.slice(BASE.length)));
  if (!file.startsWith(SITE)) {
    res.writeHead(403);
    res.end();
    return;
  }
  if (existsSync(file) && statSync(file).isDirectory()) {
    // 和 GitHub Pages 一样：目录不带斜杠时重定向
    if (!url.endsWith('/')) {
      res.writeHead(301, { Location: `${url}/` });
      res.end();
      return;
    }
    file = join(file, 'index.html');
  }
  if (!existsSync(file)) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('404 Not Found');
    return;
  }
  res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
  createReadStream(file).pipe(res);
}).listen(PORT, () => {
  console.log(`http://localhost:${PORT}${BASE}`);
});
