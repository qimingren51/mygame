# 提灯夜行 · 我的小游戏

本仓库以**提灯夜行桌面版**为主，同时保留网页小游戏合集。

## 提灯夜行（桌面版，开发中）

水墨国风的肉鸽割草游戏：提灯的夜行人在黑夜里斩妖，撑过十分钟妖潮、击败夜主即为天明。桌面版用 Rust + Bevy 重写，先支持 Linux 和 Windows，目标是同屏五千只妖物、数百个光源保持流畅。

- **下载**：[GitHub Releases](https://github.com/qimingren51/mygame/releases)（发布第一个版本后提供）。开发中的测试包在 Actions 的 Release 工作流里手动运行生成。
- **架构设计**：[docs/DESIGN.md](docs/DESIGN.md)
- **进度**：M0（工程与发布管线）进行中，里程碑见设计文档第 17 节。

### 从源码运行

需要 Rust（版本由 `rust-toolchain.toml` 自动选择）。Linux 另外需要 `libasound2-dev libudev-dev libwayland-dev libxkbcommon-dev pkg-config`。

```bash
cargo run                  # 第一次编译 Bevy 需要几分钟
cargo test --workspace
```

操作：WASD / 方向键 / 手柄左摇杆移动，空格 / 手柄 A 闪避，Esc 暂停，F11 全屏。

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
