# CLAUDE.md

本仓库是一个网页小游戏合集：一个仓库、一个 GitHub Pages 站点，每个游戏放在独立的子文件夹里。

- 线上地址：`https://qimingren51.github.io/mygame/`
- 单个游戏：`https://qimingren51.github.io/mygame/<游戏名>/`

## 目录结构

```
mygame/
├── index.html        ← 首页，列出所有游戏的链接
├── CLAUDE.md
├── snake/
│   └── index.html    ← 每个游戏的入口都是自己文件夹下的 index.html
├── breakout/
│   └── index.html
└── 2048/
    └── index.html
```

## 开发约定

- **每个游戏自成一体**：一个游戏的所有文件（HTML、JS、CSS、图片、音频）只放在它自己的文件夹里，不跨文件夹引用其他游戏的文件。
- **文件夹命名**：小写英文加连字符，例如 `space-shooter/`。文件夹名就是网址的一部分。
- **只用相对路径**：引用资源写 `./img/a.png` 或 `img/a.png`，**不要**写 `/img/a.png`。站点部署在 `/mygame/` 子路径下，以 `/` 开头的绝对路径会找不到文件。
- **默认无构建步骤**：小游戏优先用原生 HTML + CSS + JavaScript，直接打开 `index.html` 就能跑。需要构建的大游戏按下面“需要构建的游戏”的约定来做。
- **localStorage 键名加前缀**：所有游戏共用同一个域名的浏览器存储，键名必须以游戏文件夹名开头，例如 `snake_highscore`、`2048_save`，避免互相覆盖。
- **控制体积**：GitHub Pages 站点建议不超过 1GB。不要提交大视频、大音频；图片和音频尽量压缩。
- **兼顾手机**：页面加上 `<meta name="viewport" content="width=device-width, initial-scale=1">`，尽量同时支持键盘和触屏操作。
- **每个游戏提供返回首页的链接**：指向 `../`。

## 需要构建的游戏

目前是 `lantern-next/`（TypeScript + Vite + PixiJS）。约定如下：

- 游戏文件夹里有自己的 `package.json`、`package-lock.json` 和 `vite.config.ts`，依赖锁定精确版本。
- `vite.config.ts` 里写 `base: './'`，构建产物只用相对路径，放在任何子路径下都能运行。
- 构建产物（`dist/`）、`node_modules/` 不提交，由 GitHub Actions 构建。
- localStorage 前缀由文件夹名在构建时自动生成（`__STORE_PREFIX__`）。
- 美术源文件（Blender、Python 脚本）放在游戏的 `art/` 里；只提交打包好的图集，中间文件和虚拟环境不提交。
- 重构中的预览版用 `<游戏名>-next/` 命名，不放进首页列表；完成后改名替换原文件夹。
- 单个游戏的开发：在游戏文件夹里 `npm ci`，再 `npm run dev`（手机连同一局域网测试用 `npm run dev -- --host`）；提交前跑 `npm run typecheck` 和 `npm test`。

## 新增游戏的步骤

1. 新建文件夹 `<游戏名>/`，入口为 `<游戏名>/index.html`。
2. 在根目录 `index.html` 的游戏列表中加入链接（使用相对路径 `<游戏名>/`）。
3. 在 `README.md` 的游戏列表中加一行，写上在线地址 `https://qimingren51.github.io/mygame/<游戏名>/`。
4. 本地预览确认无误后提交。推送到默认分支后 GitHub Pages 会自动更新。

较大的游戏在自己文件夹里放一份 `DESIGN.md`，记录玩法设计和实现进度。

## 本地预览

用和线上相同的方式组装整站，再按线上路径 `/mygame/` 访问（不要直接双击打开文件，部分浏览器功能在 `file://` 下受限）：

```bash
node scripts/build-site.mjs       # 组装到 _site/（加 --ci 会同时跑类型检查和测试）
node scripts/serve-site.mjs       # 访问 http://localhost:8000/mygame/
```

每个游戏都应能从 `http://localhost:8000/mygame/<游戏名>/` 正常加载。只改静态小游戏时，也可以在仓库根目录用 `python3 -m http.server 8000` 快速预览。

## 部署

推送到 `master` 后，GitHub Actions（`.github/workflows/pages.yml`）运行 `node scripts/build-site.mjs --ci` 组装整站并发布到 GitHub Pages，通常两三分钟生效。仓库设置里 Pages 的来源必须是 “GitHub Actions”。

`scripts/build-site.mjs` 的规则：
- 根目录的网页文件原样复制，Markdown 文档不发布。
- 有 `vite.config.ts` 的文件夹先构建，再把 `dist/` 放到 `_site/<文件夹>/`。
- 只有 `index.html` 的文件夹原样复制。
- 构建后会检查绝对路径、每个目录的 `index.html` 以及 JS 体积，不通过则构建失败、不会发布。

根目录的 `.nojekyll` 保留即可（在 Actions 发布方式下不起作用，但无害）。
