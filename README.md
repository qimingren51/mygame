# 我的小游戏

网页小游戏合集，点开链接就能玩，电脑和手机都支持。

**在线游玩：<https://qimingren51.github.io/mygame/>**

## 游戏列表

| 游戏 | 在线地址 | 简介 |
| --- | --- | --- |
| 提灯夜行 | <https://qimingren51.github.io/mygame/lantern/> | 横屏肉鸽割草：五行共鸣、法器进化，撑过十分钟妖潮迎来天明。建议手机横屏游玩。 |
| 贪吃蛇 | <https://qimingren51.github.io/mygame/snake/> | 经典贪吃蛇，吃到食物会变长，别撞到墙或自己。 |

## 本地运行

无需安装依赖，在仓库根目录启动一个静态服务器：

```bash
python3 -m http.server 8000
```

然后打开 <http://localhost:8000/>。

## 目录结构

```
mygame/
├── index.html      首页，列出所有游戏
├── lantern/        提灯夜行（设计文档见 lantern/DESIGN.md）
└── snake/          贪吃蛇
```

每个游戏是一个独立的文件夹，推送到 `master` 分支后由 GitHub Pages 自动发布。开发约定见 [CLAUDE.md](CLAUDE.md)。
