#!/usr/bin/env node
// 在本地以 /mygame/ 路径提供 web/_site/，和 GitHub Pages 的线上路径一致。
// 用法：node web/scripts/serve-site.mjs   然后访问 http://localhost:8000/mygame/
// 环境变量 PORT 可以改端口。

import { createReadStream, existsSync, realpathSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path';
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

function inside(root, file) {
  const rel = relative(root, file);
  return rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel);
}

export function createSiteServer(site = SITE) {
  const root = realpathSync(site);
  return createServer((req, res) => {
    let url;
    try {
      url = decodeURIComponent((req.url || '/').split('?')[0]);
      if (url.includes('\0')) throw new URIError('路径包含空字符');
    } catch {
      res.writeHead(400).end();
      return;
    }
    if (!url.startsWith(BASE)) {
      res.writeHead(302, { Location: BASE }).end();
      return;
    }
    try {
      let file = resolve(root, url.slice(BASE.length));
      if (!inside(root, file)) {
        res.writeHead(403).end();
        return;
      }
      // 同时检查真实路径，目录或文件的符号链接不能指向站点外。
      file = realpathSync(file);
      if (!inside(root, file)) {
        res.writeHead(403).end();
        return;
      }
      if (statSync(file).isDirectory()) {
        if (!url.endsWith('/')) {
          const location = url.split('/').map(encodeURIComponent).join('/') + '/';
          res.writeHead(301, { Location: location }).end();
          return;
        }
        file = realpathSync(join(file, 'index.html'));
        if (!inside(root, file)) {
          res.writeHead(403).end();
          return;
        }
      }
      if (!statSync(file).isFile()) {
        res.writeHead(404).end();
        return;
      }
      const stream = createReadStream(file);
      stream.on('error', () => {
        if (res.headersSent) res.destroy();
        else res.writeHead(500).end();
      });
      stream.once('open', () => {
        res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
        stream.pipe(res);
      });
      res.on('close', () => stream.destroy());
    } catch (e) {
      const status = e.code === 'ENOENT' || e.code === 'ENOTDIR' ? 404 : e.code === 'EACCES' ? 403 : 500;
      res.writeHead(status).end();
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (!existsSync(SITE)) {
    console.error('找不到 _site/，请先运行 node web/scripts/build-site.mjs');
    process.exit(1);
  }
  createSiteServer().listen(PORT, () => {
    console.log(`http://localhost:${PORT}${BASE}`);
  });
}
