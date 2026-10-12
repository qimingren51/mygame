#!/usr/bin/env node
// 组装整站到 _site/，本地和 GitHub Actions 共用。
//
// 规则：
// - 根目录的网页文件（index.html、.nojekyll 等）原样复制，Markdown 等文档不复制。
// - 一级文件夹里有 vite.config.ts 的：安装依赖并构建，把 dist/ 放到 _site/<文件夹>/。
// - 一级文件夹里只有 index.html 的：原样复制（静态游戏）。
//
// 参数：
//   --ci          用 npm ci 安装依赖，并在构建前跑类型检查和测试
//   --skip-tests  跳过测试（只在本地快速预览时使用）

import { execSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { dirname, extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, '_site');
const args = new Set(process.argv.slice(2));
const CI = args.has('--ci');
const SKIP_TESTS = args.has('--skip-tests');

const EXCLUDED_DIRS = new Set(['.git', '.github', 'scripts', 'node_modules', '_site']);
const EXCLUDED_ROOT_FILES = new Set(['.gitignore', 'package.json', 'package-lock.json']);
const JS_GZIP_BUDGET = 300 * 1024; // 单个游戏的 JS 压缩后体积上限

const run = (cmd, cwd) => {
  console.log(`\n$ ${cmd}   (${relative(ROOT, cwd) || '.'})`);
  execSync(cmd, { cwd, stdio: 'inherit' });
};

function walk(dir, fn) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, fn);
    else fn(p);
  }
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

// 根目录文件
for (const name of readdirSync(ROOT)) {
  const p = join(ROOT, name);
  if (statSync(p).isDirectory()) continue;
  if (EXCLUDED_ROOT_FILES.has(name) || extname(name) === '.md') continue;
  cpSync(p, join(OUT, name));
}

// 一级文件夹
const built = [];
for (const name of readdirSync(ROOT).sort()) {
  const dir = join(ROOT, name);
  if (!statSync(dir).isDirectory() || EXCLUDED_DIRS.has(name) || name.startsWith('.')) continue;

  if (existsSync(join(dir, 'vite.config.ts'))) {
    if (CI || !existsSync(join(dir, 'node_modules'))) run(CI ? 'npm ci' : 'npm install', dir);
    if (CI) run('npm run typecheck', dir);
    if (CI && !SKIP_TESTS) run('npm test', dir);
    run('npm run build', dir);
    cpSync(join(dir, 'dist'), join(OUT, name), { recursive: true });
    built.push(name);
  } else if (existsSync(join(dir, 'index.html'))) {
    cpSync(dir, join(OUT, name), {
      recursive: true,
      filter: (src) => !src.includes('/node_modules'),
    });
  } else {
    console.log(`跳过 ${name}/（没有 index.html 也没有 vite.config.ts）`);
  }
}

// 构建后检查
const problems = [];
for (const name of readdirSync(OUT)) {
  const p = join(OUT, name);
  if (statSync(p).isDirectory() && !existsSync(join(p, 'index.html'))) {
    problems.push(`${name}/ 缺少 index.html`);
  }
}
walk(OUT, (file) => {
  if (extname(file) !== '.html') return;
  const html = readFileSync(file, 'utf8');
  // 站点部署在 /mygame/ 子路径下，以 / 开头的路径会找不到文件
  const abs = html.match(/(?:src|href)=["']\/(?!\/)[^"']*/g);
  if (abs) problems.push(`${relative(OUT, file)} 含有绝对路径：${abs.join(', ')}`);
});

// 体积报告
console.log('\n体积报告：');
for (const name of readdirSync(OUT).sort()) {
  const p = join(OUT, name);
  if (!statSync(p).isDirectory()) continue;
  let total = 0;
  let jsGzip = 0;
  walk(p, (file) => {
    const size = statSync(file).size;
    total += size;
    if (extname(file) === '.js') jsGzip += gzipSync(readFileSync(file)).length;
  });
  const kb = (n) => `${(n / 1024).toFixed(0)} KB`;
  console.log(`  ${name.padEnd(16)} 总计 ${kb(total).padStart(8)}   JS 压缩后 ${kb(jsGzip).padStart(7)}`);
  if (built.includes(name) && jsGzip > JS_GZIP_BUDGET) {
    problems.push(`${name}/ 的 JS 压缩后 ${kb(jsGzip)}，超过上限 ${kb(JS_GZIP_BUDGET)}`);
  }
}

if (problems.length) {
  console.error('\n构建检查未通过：');
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(`\n_site 组装完成：${relative(process.cwd(), OUT) || OUT}`);
