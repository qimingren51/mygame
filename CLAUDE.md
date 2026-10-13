# CLAUDE.md

本仓库以**提灯夜行桌面版**为主（Rust + Bevy，先支持 Linux 和 Windows）。网页小游戏合集放在 `web/`，照常发布到 GitHub Pages。

## 桌面版

- 架构设计：`docs/DESIGN.md`。改架构或接口约定（图集格式、帧命名、内容数据结构）时，同步更新这份文档。
- 玩法与数值：`docs/GAMEPLAY.md`、`docs/BALANCE.md`（复现脚本在 `docs/baseline/`）。M2 照搬网页版作为平衡基线，M2.5 起按这两份文档改。
- 世界观与命名：`docs/LORE.md`。新增或改名先改那里；界面文字迁到 `assets/i18n/` 时，中文名以它为准。
- 质感（镜头、粒子、光、演出、音效）：`docs/FEEL.md`。
- 移植参考：`docs/PORTING-NOTES.md`、`web/lantern-next/`（已冻结的 TS 版）、`web/lantern/`（网页旧版，玩法设计见其中的 `DESIGN.md`）。

### 目录

```
Cargo.toml           工作区；所有依赖在 [workspace.dependencies] 统一声明版本
crates/core          定步长、随机流、状态哈希（不依赖引擎）
crates/content       内容数据结构、加载、校验
crates/sim           玩法模拟：只依赖 bevy_app / bevy_ecs / bevy_math / bevy_state
crates/view          渲染
crates/audio         音频（kira）
crates/ui            界面；fonts.py 裁剪字体子集
crates/platform      输入、数据目录、设置
crates/game          可执行程序 lantern，只做组装
crates/tools         命令行工具 lantern-tools（跑分、内容检查）
assets/              data/（RON 数据）atlas/（图集）fonts/（字体子集）i18n/
art/                 Blender 美术管线
packaging/           安装包附带的说明
```

### 常用命令

```bash
cargo run                                      # 运行游戏（参数：--seed <数字>、--windowed）
cargo run --features dev                       # 开发模式（Bevy 调试工具、资源热重载）
cargo test --workspace                         # 全部测试
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all
cargo run --release -p lantern-tools -- bench  # 模拟跑分（不开窗口，默认 5000 只妖物）
cargo run --release -p lantern-tools -- replay <文件>  # 校验回放：逐秒核对状态哈希
cargo run --release -p lantern-tools -- balance --runs 20  # 机器人批量跑局看平衡（加 --god 无敌跑完整局）
cargo run --release -p lantern-tools -- kite --runs 100 --tier 1 --meta none  # 会躲的机器人测胜率（--meta none/half/full）
cargo run --release -p lantern-tools -- kite --runs 200 --meta half --school all --csv out/  # 流派机器人对照（--combo all 跑反应组合，--endless 打无尽夜），写 CSV
cargo run --release -p lantern-tools -- kite --runs 1 --god --record bot.ron  # 机器人打一局存成回放并打印关键时刻（看后期画面用）
cargo run -- --replay <文件> [--from <秒>]     # 在游戏里观看回放（--from 跳到第几秒）
UPDATE_GOLDEN=1 cargo test -p lantern_sim      # 有意修改玩法后，更新确定性黄金哈希
python3 crates/ui/fonts.py                     # 新增界面文字后，重新裁剪字体（需要 fonttools；CI 用 --check 检查缺字）
```

Linux 编译需要：`pkg-config libasound2-dev libudev-dev libwayland-dev libxkbcommon-dev`。

### 约定

- **分层**：`sim` 不能依赖渲染、窗口、音频。`view`、`audio`、`ui` 只读模拟状态和 `SimOutbox` 里的事件；要改变模拟，只能发 `SimCommand`。`game` 里不写逻辑。
- **确定性**（`crates/core` 和 `crates/sim` 的 `clippy.toml` 会检查）：
  - 模拟不读真实时间，步长用 `lantern_core::step::DT`。
  - 随机数只从 `SimRng` 的分流里取。
  - 三角函数、指数函数用 `bevy_math::ops`。
  - 不遍历 `HashMap` / `HashSet`。
  - 往队列里写数据的系统要串行。
  - 有意改变玩法结果时，更新黄金文件，并在提交信息里说明。
- **内容数据**：写在 `assets/data/*.ron` 里。新增字段时，同步补上校验和测试。
- **依赖**：
  - Bevy 锁定 `=0.20.0`，只在里程碑之间升级。
  - 少用第三方 Bevy 插件。
  - `Cargo.lock` 要提交。
- **提交前**：`cargo fmt --all --check`、`clippy -D warnings`、`cargo test --workspace` 都要通过。
- **代码风格**：注释和面向玩家的文字用中文，简洁直白。
- **界面文字**：固定文字写在 `crates/ui` 的代码里，名字和说明写在 `assets/data/`；加第二种语言时再统一移到 `assets/i18n/`。改了文字要重新运行 `fonts.py`。
- **美术**：
  - Blender 管线在 `art/`，在仓库根目录运行，产物输出到 `assets/atlas/`。
  - 只提交脚本和打包好的图集，中间文件（`art/out/`、`art/.venv/`）不提交。

### 构建与发布

- `.github/workflows/ci.yml`：桌面版相关文件有改动时运行。
  - Linux：格式、clippy、测试、跑分。
  - Windows：确定性测试，以及检查能否编译。
- `.github/workflows/release.yml`：
  - 推送 `v*` 标签时，打包 Linux 和 Windows 版本，发布到 GitHub Releases。
  - 手动运行时只打包，产物在这次运行的 Artifacts 里。

### 协作

目前有五个 Claude 会话分工合作（架构、美术、玩法与数值、世界观与命名、质感），各自负责的文件见 `docs/DESIGN.md` 第 19 节。改对方负责的文件之前，先发消息商量。推送前先 `git pull --rebase origin master`。

## 网页小游戏（`web/`）

- 线上地址：`https://qimingren51.github.io/mygame/`
- 单个游戏：`https://qimingren51.github.io/mygame/<游戏名>/`
- `web/` 下的目录结构对应网址：`web/index.html` 是首页，`web/<游戏名>/index.html` 是每个游戏的入口。

### 开发约定

- **每个游戏自成一体**：一个游戏的所有文件（HTML、JS、CSS、图片、音频）只放在它自己的文件夹里，不跨文件夹引用其他游戏的文件。
- **文件夹命名**：小写英文加连字符，例如 `space-shooter/`。文件夹名就是网址的一部分。
- **只用相对路径**：引用资源写 `./img/a.png` 或 `img/a.png`，**不要**写 `/img/a.png`。站点部署在 `/mygame/` 子路径下，以 `/` 开头的绝对路径会找不到文件。
- **默认无构建步骤**：小游戏优先用原生 HTML + CSS + JavaScript，直接打开 `index.html` 就能跑。
- **localStorage 键名加前缀**：所有游戏共用同一个域名的浏览器存储，键名必须以游戏文件夹名开头，例如 `snake_highscore`、`2048_save`，避免互相覆盖。
- **控制体积**：GitHub Pages 站点建议不超过 1GB。不要提交大视频、大音频；图片和音频尽量压缩。
- **兼顾手机**：页面加上 `<meta name="viewport" content="width=device-width, initial-scale=1">`，尽量同时支持键盘和触屏操作。
- **每个游戏提供返回首页的链接**：指向 `../`。

### 需要构建的游戏

目前只有 `web/lantern-next/`（TypeScript + Vite + PixiJS），**已冻结**，后续开发转到桌面版，只做必要的修复。它的约定：
- `vite.config.ts` 里写 `base: './'`。
- `dist/` 和 `node_modules/` 不提交。
- localStorage 前缀由文件夹名在构建时生成。
- 本地开发：`npm ci` 后运行 `npm run dev`；提交前运行 `npm run typecheck` 和 `npm test`。

### 新增网页游戏的步骤

1. 新建文件夹 `web/<游戏名>/`，入口为 `web/<游戏名>/index.html`。
2. 在 `web/index.html` 的游戏列表中加入链接（使用相对路径 `<游戏名>/`）。
3. 在 `README.md` 的网页小游戏列表中加一行，写上在线地址。
4. 本地预览确认无误后提交。

### 本地预览与部署

```bash
node web/scripts/build-site.mjs   # 组装到 web/_site/（加 --ci 会同时跑类型检查和测试）
node web/scripts/serve-site.mjs   # 访问 http://localhost:8000/mygame/
```

- **网页检查**：涉及 `web/` 的 PR 运行类型检查、单测、整站构建和 Playwright 浏览器流程；部署仅在检查通过后执行。本地运行浏览器测试前，在 `web/lantern-next/` 执行 `npx playwright install chromium`，组装整站后运行 `npm run e2e`。
- **自动部署**：推送到 `master` 且 `web/` 有改动时，`.github/workflows/pages.yml` 会组装网页站点并发布到 GitHub Pages。仓库设置里 Pages 的来源必须保持“GitHub Actions”；如果改回“从分支部署”，GitHub 会对仓库根目录另跑一次 Jekyll 部署，把网站覆盖掉。
- **`build-site.mjs` 的组装规则**：
  - `web/` 根目录的网页文件原样复制，Markdown 不发布。
  - 有 `vite.config.ts` 的文件夹先构建，再把 `dist/` 放进去。
  - 只有 `index.html` 的文件夹原样复制。
  - 最后检查绝对路径、每个目录的 `index.html` 和 JS 体积。
