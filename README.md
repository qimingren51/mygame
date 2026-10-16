# 提灯夜行 · 我的小游戏

本仓库以**提灯夜行桌面版**为主，同时保留网页小游戏合集。

## 提灯夜行（桌面版，开发中）

水墨国风的肉鸽割草游戏：提灯的夜行人在黑夜里斩妖，撑过十分钟妖潮、击败夜主即为天明。桌面版用 Rust + Bevy 重写，先支持 Linux 和 Windows，目标是同屏五千只妖物、数百个光源保持流畅。

- **下载**：[GitHub Releases](https://github.com/qimingren51/mygame/releases)（发布第一个版本后提供）。开发中的测试包在 Actions 的 Release 工作流里手动运行生成。
- **架构设计**：[docs/DESIGN.md](docs/DESIGN.md)
- **进度**：`develop` 正在打磨青丘首轮体验：清晰月夜、升级卡与状态栏、铜钱剑、三种青丘妖物，以及暂停内的属性与构筑查询。当前分工与集成状态见 [docs/TEAM.md](docs/TEAM.md)，历史里程碑见设计文档第 17 节。

### 下载校验与 Windows SmartScreen

从同一次 GitHub Release 下载发布包和 `SHA256SUMS.txt`，放在同一目录，先校验再解压运行。校验文件包含所有 ZIP 和 Linux tar.gz 发布包的 SHA-256。

Windows 在 PowerShell 中运行（把文件名换成实际下载的 ZIP）：

```powershell
Get-FileHash .\lantern-v0.1.0-windows-x86_64.zip -Algorithm SHA256
```

将输出的 `Hash` 与 `SHA256SUMS.txt` 中相同文件名那一行的哈希逐字比较（忽略大小写），必须完全一致；不一致时不要运行，请重新下载。

Linux 在下载目录运行，确认已下载的包显示 `OK`（未下载的其他平台包会跳过）：

```bash
sha256sum --check --ignore-missing SHA256SUMS.txt
```

Windows 首次启动可能出现 SmartScreen「Windows 已保护你的电脑」，未签名或信誉尚未积累的版本都可能遇到。确认来自本仓库的 GitHub Releases 且校验一致后，点击「更多信息」→「仍要运行」。

发布维护：在仓库 Actions secrets 中同时配置 `WINDOWS_CERT_PFX_BASE64`（含私钥的 PFX 文件的 Base64）和 `WINDOWS_CERT_PASSWORD`（PFX 密码），工作流就会在打包前用 SignTool 签名、添加 RFC3161 时间戳并验签；签名或验证失败会终止发布。缺少任一 secret 时打印提示并生成未签名包。`SHA256SUMS.txt` 在标签发布时生成，随压缩包一起上传到 Release。

### 从源码运行

需要 Rust（版本由 `rust-toolchain.toml` 自动选择）。Linux 另外需要 `libasound2-dev libudev-dev libwayland-dev libxkbcommon-dev pkg-config`。

```bash
cargo run                  # 第一次编译 Bevy 需要几分钟
cargo test --workspace
```

开发调试时用 `cargo run -- --god --windowed` 开启手动游玩的无敌模式，可加 `--seed 42` 固定种子。此次启动中的新对局和重开都保持无敌，不计奖励与成绩；退出后不带 `--god` 启动即可恢复正常。观看回放使用录制时的设置，不能同时传入 `--god`。

Windows EXE 图标、版本信息和应用清单会在构建时嵌入；图标来源、重新生成和验证方法见 [Windows 程序资源](packaging/windows/README.md)。

操作：WASD / 方向键 / 手柄左摇杆移动，空格 / 手柄 A 闪避，Esc 暂停，F11 全屏，F3 性能面板。标题界面按 B 跑分（250 到 5000 只妖物，结果存到数据目录的 `bench/`）。

## 网页小游戏

点开链接就能玩，电脑和手机都支持。**在线游玩：<https://qimingren51.github.io/mygame/>**

| 游戏 | 在线地址 | 简介 |
| --- | --- | --- |
| 提灯夜行（网页版） | <https://qimingren51.github.io/mygame/lantern/> | 横屏肉鸽割草：五行共鸣、法器进化、夜签与奇遇让每局都不同，配有国风音效与音乐。建议手机横屏游玩。 |
| 贪吃蛇 | <https://qimingren51.github.io/mygame/snake/> | 经典贪吃蛇，吃到食物会变长，别撞到墙或自己。 |

提灯夜行重构版预览 <https://qimingren51.github.io/mygame/lantern-next/>（PixiJS + 水墨美术）已冻结，后续开发转到桌面版。

### 手机游玩建议

- **安卓**：用 Chrome 等浏览器打开，标题页点「全屏」或直接「出发」会自动全屏横屏。也可以在浏览器菜单里「添加到主屏幕」，之后从桌面图标打开就是全屏应用。
- **iPhone**：Safari 不支持网页全屏。点底部「分享」→「添加到主屏幕」，再从桌面图标打开，就能全屏横屏游玩。
- **微信 / QQ 内**：无法全屏，请点右上角「…」→「在浏览器打开」。
- **声音**：需要先点一下屏幕才能出声。iPhone 的侧边静音键打开时也能播放，但请确认媒体音量没有调到最低。

### 本地预览

需要 Node 22。和线上一样组装整站后预览：

```bash
node web/scripts/build-site.mjs
node web/scripts/serve-site.mjs
```

然后打开 <http://localhost:8000/mygame/>。

## 目录结构

```
mygame/
├── crates/        桌面版源码（core、content、sim、view、audio、ui、platform、game、tools）
├── assets/        桌面版资源：图集、数据表、字体
├── art/           Blender 美术管线（脚本）
├── docs/          设计文档
├── packaging/     安装包附带的说明
└── web/           网页小游戏合集（GitHub Pages）
    ├── index.html   首页
    ├── lantern/     提灯夜行网页版
    ├── lantern-next/ 提灯夜行重构版预览（已冻结）
    ├── snake/       贪吃蛇
    └── scripts/     整站组装与本地预览脚本
```

开发约定见 [CLAUDE.md](CLAUDE.md)。
