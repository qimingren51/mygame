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
- **默认无构建步骤**：优先用原生 HTML + CSS + JavaScript，直接打开 `index.html` 就能跑。如果某个游戏需要引擎（如 Phaser），优先用 CDN 引入并锁定具体版本号；确实需要构建工具时，在该游戏文件夹内单独说明。
- **localStorage 键名加前缀**：所有游戏共用同一个域名的浏览器存储，键名必须以游戏文件夹名开头，例如 `snake_highscore`、`2048_save`，避免互相覆盖。
- **控制体积**：GitHub Pages 站点建议不超过 1GB。不要提交大视频、大音频；图片和音频尽量压缩。
- **兼顾手机**：页面加上 `<meta name="viewport" content="width=device-width, initial-scale=1">`，尽量同时支持键盘和触屏操作。
- **每个游戏提供返回首页的链接**：指向 `../`。

## 新增游戏的步骤

1. 新建文件夹 `<游戏名>/`，入口为 `<游戏名>/index.html`。
2. 在根目录 `index.html` 的游戏列表中加入链接（使用相对路径 `<游戏名>/`）。
3. 在 `README.md` 的游戏列表中加一行，写上在线地址 `https://qimingren51.github.io/mygame/<游戏名>/`。
4. 本地预览确认无误后提交。推送到默认分支后 GitHub Pages 会自动更新。

较大的游戏在自己文件夹里放一份 `DESIGN.md`，记录玩法设计和实现进度。

## 本地预览

在仓库根目录启动一个静态服务器（不要直接双击打开文件，部分浏览器功能在 `file://` 下受限）：

```bash
python3 -m http.server 8000
```

然后访问 `http://localhost:8000/`。在子路径下测试一次相对路径是否正确：每个游戏都应能从 `http://localhost:8000/<游戏名>/` 正常加载。

## 部署

GitHub Pages 从 `master` 分支的根目录发布（Settings → Pages → Deploy from a branch）。没有构建步骤，推送即上线，通常一两分钟内生效。

根目录的 `.nojekyll` 用于关闭 GitHub Pages 默认的 Jekyll 处理，让文件原样发布，不要删除。
