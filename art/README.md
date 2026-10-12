# 提灯夜行 · 美术管线（无头 Blender）

用程序化 3D 模型 + Blender 无头渲染，批量产出水墨风精灵（填色 / 墨线 / 法线 / 8 方向）。
本目录目前只有冒烟测试，用来确认这台机器（无 GPU、无 libEGL/OSMesa）上哪条渲染路径能跑通。

## 安装

需要 Python 3.13，因为 bpy 5.2.2 只发布了 cp313 的 wheel。

```bash
cd art
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # bpy 5.2.2 + pillow 12.3.0 + numpy 2.5.3
```

wheel 下载约 383 MB，装好后 `.venv` 约 1.1 GB，安装大约 1 分钟。
本机用的是 **pip 装的 bpy 模块**，没有下载官方 Blender 压缩包。
脚本也兼容官方可执行文件（`blender -b --factory-startup -P render/smoke_test.py`），但这条路径**没有实测**。
另外 Blender 自带的 Python 里没有 Pillow，用这条路径时拼图和预览两步会跳过。

## 运行冒烟测试

```bash
art/.venv/bin/python art/render/smoke_test.py     # 在仓库根目录执行
```

全程约 7 秒。输出都在 `out/smoke/`：

| 文件 | 内容 |
|---|---|
| `fill.png` | 只有填色（Cycles CPU，512²，16 spp，自发光假卡通 3 档） |
| `combined.png` | 填色 + Freestyle 墨线 |
| `lines.png` | 只有墨线（Freestyle 渲染通道，从多层 EXR 解出） |
| `lines_holdout.png` | 只有墨线（Holdout 覆盖材质法，作对照） |
| `fill_from_exr.png` | 与 `lines.png` 同一次渲染得到的填色 |
| `normal.png` | 相机空间法线，OpenGL 约定（R=右，G=上，B=朝向观察者），线性写出 |
| `contact_dirs.png` | 8 方向（每 45° 一张），256²、4 spp，带墨线 |
| `preview_128.png` / `preview_zoom.png` | 缩到 128px 铺纸色底的预览，以及 3 倍最近邻放大 |
| `night.png` | 夜景：靛蓝环境光 × 灯笼暖光的径向衰减 |
| `fallback_hull.png` / `fallback_sobel_lines.png` | 后备描边：反向外壳，以及对法线图做 Sobel 边缘 |
| `report.json` | 版本、引擎、各阶段耗时、CPU 占用、线条方法、OIDN 等 |

## 实测耗时

测试环境：4 核 Xeon 2.1 GHz，无 GPU。测试小人约 1.2k 面。

| 阶段 | 耗时 | 平均占用核数 |
|---|---|---|
| `import bpy` | 0.55 s | – |
| 场景搭建 | 0.08 s | 1.2 |
| 仅填色 512² | 0.31 s | 3.5 |
| 填色 + Freestyle 512² | 0.60 s，Freestyle 额外 0.29 s | 3.4 |
| 填色 + 线条通道写多层 EXR 512²（一次渲染出两层） | 0.60 s，numpy 解码另需 0.01 s | 3.5 |
| 仅线条（Holdout）512² | 0.57 s | 3.4 |
| 法线 512² | 0.30 s | 3.6 |
| 反向外壳描边 512² | 0.40 s | 3.8 |
| 8 方向 256²，带 Freestyle | 平均每帧 0.09 s，共 0.74 s | – |
| Workbench / EEVEE 探测（子进程） | 约 0.7 s，然后 abort | – |

## 结论：哪些能用

- **Cycles CPU 可以用**，Freestyle 在无头模式下也能正常出线。
- **Workbench 和 EEVEE 不能用**。它们需要 GPU 上下文，进程会因为找不到 `libEGL.so.1` 直接 SIGABRT（返回码 -6）。
  这种崩溃用 try/except 拦不住，所以脚本把它们放在子进程里探测。
- **单独取线条的推荐做法**：开启 `freestyle_settings.as_render_pass`，把输出设成多层 EXR（`exr_codec='NONE'`），
  再用脚本里的 `read_exr_none()` 读出 `ViewLayer.Freestyle` 通道。
  这样一次渲染就能同时得到填色和线条。Pillow 读不了 EXR，wheel 里也没有 OpenImageIO，所以写了一个 numpy 的小读取器。
- **备用做法**：把 `view_layer.material_override` 设成 Holdout 材质，再开 Freestyle 渲染。
  得到的线条与渲染通道法逐像素一致（都是 14546 个 alpha>0.5 的像素），代价是多渲一次。
- **走合成器取线条不可用**。合成器默认 `compositor_device='GPU'`，必须改成 `'CPU'`。
  但即使改成 CPU，只要同时开着 Freestyle，合成器仍然会触发 EGL 初始化并 abort。
  不开 Freestyle 时，CPU 合成器可以正常工作。
- **OIDN 降噪可用**：`_cycles.with_openimagedenoise=True`，CPU 设备支持 OIDN，开降噪的实测渲染也能跑通。
  不过假卡通材质不需要降噪。
- **后备描边**（反向外壳 + Sobel）已实现并验证可用。外壳只能画出外轮廓，内部的线要靠 Sobel 补。

## 已知限制和注意事项

- 线宽用的是 ABSOLUTE 模式，单位是像素。换分辨率时要按比例缩放，见 `setup_freestyle(line_scale=...)`。
- 渲染时把 `dither_intensity` 设为 0，否则 8 位 PNG 会带抖动噪点，不利于后续的调色板量化。
- `view_transform` 设为 Standard，保证 hex 颜色原样输出；法线图改用 Raw。
- 日志里的 `CUEW initialization failed` 是因为机器上没有 CUDA，可以忽略。
- Blender 5.x 的 API 有变化：`Material.use_nodes` 已弃用，新建的材质自带节点树；合成器改用 `scene.compositing_node_group`；
  多层 EXR 的格式名是 `OPEN_EXR_MULTILAYER`，并且要设置 `media_type='MULTI_LAYER_IMAGE'`，写出的是 multi-part 文件。
- 表里的耗时来自一个很简单的模型。Freestyle 的视图图计算会随边数增长，换成正式角色后需要重新测。

## 特效与地面贴图（post/vfx_textures.py）

不用 Blender，只用 Pillow + numpy 生成，颜色全部取自 `style/style.py`。固定随机种子，重复运行逐字节相同，约 15 秒。

```bash
art/.venv/bin/python art/post/vfx_textures.py        # 在仓库根目录执行
art/.venv/bin/python art/post/test_vfx_textures.py   # 自检（尺寸、锚点、宣纸接缝、光照边界与抖动、体积等）
```

| 输出 | 内容 |
|---|---|
| `out/assets/vfx/` | light glow eyes shadow spark gem_0..2 flame_0..3 ink_0..2 lantern + `meta.json`（尺寸、锚点、混合方式） |
| `out/assets/ground/` | paper（512² 可平铺，RGB）wash_0..2 grass_0..3 + `meta.json` |
| `out/review/` | `vfx_sheet.png`（纸色底 / 夜色底各一遍，2×）、`paper_tile_2x2.png`（看接缝）、`light_test.png`（看色带） |

名字、尺寸、锚点与 `src/render/placeholders.ts` 的占位图一一对应。PNG 都是直通（非预乘）alpha，白色贴图在游戏里染色。

## 法器、法术特效与拾取物贴图（post/weapon_textures.py）

同样只用 Pillow + numpy，笔刷、噪声、直通 alpha 输出等工具直接复用 `vfx_textures.py`（只 import，不改它的产物）。
固定随机种子，重复运行逐字节相同，约 20 秒。

```bash
art/.venv/bin/python art/post/weapon_textures.py        # 在仓库根目录执行
art/.venv/bin/python art/post/test_weapon_textures.py   # 自检（会先重新生成；尺寸、锚点、白色可染色、边框透明、朝向、确定性、体积、只写自己的目录）
```

| 输出 | 内容 |
|---|---|
| `out/assets/weapons/` | sword sword_evo sword_trail crane_0..3 crane_evo_0..3 ring ring_ink seal seal_evo seal_mark crack warn taiji blast shield chest soulbell lotus + `meta.json`（尺寸、锚点、blend、tint、note） |
| `out/review/` | `weapons_sheet.png`（3×，纸色底 / 夜色底，叠加贴图按游戏染色）、`weapons_ingame.png`（游戏比例的模拟场景 + 涟漪环 30–800 像素缩放条） |

约定：tint=true 的贴图 RGB 恒为 255，只有 alpha 有形状，游戏里染色后叠加；剑、剑尾光、纸鹤旋转角为 0 时指向 +X；
剑尾光锚点在右端，放在剑的位置、画在剑后面；石印、宝箱、铃、莲的锚点是落地点。

## 界面图标、地面装饰与一键生成（post/ui_icons.py、post/ground_decor.py、post/make_2d.py）

```bash
art/.venv/bin/python art/post/make_2d.py            # 1 倍和 2 倍各生成一遍 vfx、weapons、ground、ui 和审图（约 6 分钟）
art/.venv/bin/python art/post/test_ui_icons.py      # 三个自检脚本没设 LANTERN_ART_DENSITY 时会 1 倍、2 倍各跑一遍
```

| 输出 | 内容 |
|---|---|
| `out/assets*/ui/` | 25 个图标（1 倍 64²、2 倍 128²，锚点居中）：法器 5、进化 5、心法 10、五行 5。`meta.json` 里每个图标有 `kind`、`id`、`el`、`name`，`el_colors` 是五行配色 |
| `out/assets*/weapons/` | 新增 `foxfire_0..2`（夜主弹幕，白色可染色，叠加，朝 +X，建议染 #FF6B5A） |
| `out/assets*/ground/` | 新增 `spring`（灵泉）、`rift` + `rift_glow`（裂隙与叠加辉光，建议染 #D2386A）、`reed_0..2`、`leaves_0..1`、`pebbles_0..1`、`puddle_0`、`bamboo_0..1` |
| `out/review*/` | `additions_sheet.png`（图标原大和 32 像素、纸色底和夜色底）、`ground_mock.png`（白天和夜晚的地面合成） |

2D 贴图也按 `LANTERN_ART_DENSITY` 出图：噪声在 1 倍网格上生成再放大，所以 2 倍和 1 倍是同一张画，只是边缘更清楚。
1 倍的 PNG 逐字节固定，基准在 `post/golden_1x.json`（依赖锁定的 Pillow 12.3.0）。

## 打包桌面版图集

```bash
A=art/out/assets@2x
art/.venv/bin/python art/post/pack_atlas.py --paper $A/ground/paper.png --out assets/atlas
art/.venv/bin/python art/post/pack_atlas.py --name actors --out assets/atlas $A/hero $A/shade $A/wisp $A/toad $A/golem $A/fox $A/ghoul $A/stonelord $A/rock_a $A/rock_b $A/rock_c $A/stone_lantern $A/ancient_lamp $A/blood_altar
art/.venv/bin/python art/post/pack_atlas.py --name boss --out assets/atlas $A/boss
art/.venv/bin/python art/post/pack_atlas.py --name vfx --out assets/atlas $A/vfx $A/weapons
art/.venv/bin/python art/post/pack_atlas.py --name ground --out assets/atlas $A/ground
art/.venv/bin/python art/post/pack_atlas.py --name ui --out assets/atlas $A/ui
```

格式约定见 `docs/DESIGN.md` 第 15 节。

## 正式管线

```bash
art/.venv/bin/python art/render/produce.py                         # 1 倍（网页版密度）→ out/assets/，审图 → out/review/
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/produce.py   # 2 倍（桌面版）→ out/assets@2x/，审图 → out/review@2x/
art/.venv/bin/python art/render/produce.py --only hero,boss        # 只重渲部分；--review 只自检 + 重拼审图
art/.venv/bin/python art/post/check_asset.py art/out/assets@2x/hero  # 单独自检（按素材 meta 里的 px_per_unit 换算阈值）
```

出图密度：`style.DENSITY`（环境变量 `LANTERN_ART_DENSITY`，1 或 2）。帧尺寸、线宽、墨晕、透明扩边、配准容差、
笔触采样、纸纹、审图里的光圈半径等都按密度缩放；模型用米建模，与密度无关。每个 meta.json 写 `px_per_unit`，
挂点是该密度下的最终像素。`LANTERN_RENDER_SCALE` 可改超采样倍数（默认 4）。2 倍出图约是 1 倍的 4 倍耗时。

| 文件 | 作用 |
|---|---|
| `style/style.py` | 风格唯一来源（颜色、尺寸、相机、线条、后期参数、密度、输出约定），只读 |
| `style/bstyle.py` | Blender 侧：场景/渲染/相机（锚点数值校验）、假卡通材质（晕染+积墨）、发光材质、烟缕材质、墨线分档、一次渲染读出填色/墨线/发光遮罩、挂点投影、渲染锁 |
| `post/postprocess.py` | 缩小、调色板软吸附、墨线叠加与墨晕、纸纹、透明区扩色、闪白剪影 |
| `post/check_asset.py` | 按输出约定自检（尺寸、边距、配准漂移、身高、着地、调色板、墨线占比、挂点） |
| `post/contact_sheet.py` | 拼图、放大、夜景合成、游戏大小对比、动图 |
| `models/hero.py` | 白衣墨氅剑仙：idle 6、walk 8、dash 4、hurt 2、death 6（不循环），8 向 |
| `models/shade.py` | 影妖、疾影（墨烟幽灵，float） |
| `models/golem.py` `fox.py` `ghoul.py` `stonelord.py` `toad.py` | 石妖、赤面狐与夜主九尾、青面鬼、石将（翁仲）、金蟾（move，只画 E） |
| `models/kit.py` | 妖物建模公共件（石块、管状尾、毛笔形尾、分段晕染材质、破布片、发光眼） |
| `models/rock.py` `stone_lantern.py` `event_props.py` | 山石 a/b/c、石灯笼、古灯、血祭坛 |
| `render/pipeline.py` | 渲一个素材的全部帧并按输出约定写文件夹（出图脚本共用） |
| `render/produce.py` | 正式出图 + 自检 + 审图 |
| `render/style_frame.py` | 风格样张（早期） |

墨线分档（物体放进哪个集合就用哪档，见 `bstyle.LINE_COLLECTIONS`）：
outer 大形体（外轮廓 2.6px + 形线 1.4px + 折痕），inner 小部件（外轮廓 + 1.1px），
thin 细长彩色部件（只有 1.1px，不进粗外轮廓，灯杖、符纸），none 不描线（眼、发光芯、烟缕）；
`cun=True` 另加暗示轮廓线作皴笔。道具用 `setup_camera(..., anchor=PROP_ANCHOR)`，
石妖、精英、夜主用 `BIG_ENEMY_ANCHOR`（meta 里 `anchor_kind: "big_enemy"`）。
meta 里的 `vertical_motion`（整个素材或单个动画）表示动画本身大幅上下（金蟾跳、主角死亡倒地），自检只查水平配准。

实测要点（bpy 5.2.2）：
- 物体编号通道在 EXR 里叫 `ViewLayer.Object Index.X`；**只开 Object Index 时全是 0，要同时开 Depth 才会写出**。
- Freestyle 的“粗细噪声”修饰器会让平均线宽翻倍且与 amplitude 不成比例，没有用。
- 内部剪影若也用 2.6px 外线宽，128px 主角六成以上是墨，所以外线宽只给整体外轮廓，内部剪影降一档。
- 边标记是名为 `freestyle_edge` 的布尔边属性（山石的皴笔用它）。
- 每帧素材除了 `<动画>_<朝向>_<帧号>.png`，还写 `_emit.png`（发光部件，夜里叠加用），妖物另有 `_flash.png`。
- 一个物体可以同时链接到多个集合（Freestyle 按集合选线时照样认），外轮廓集合 InkContour 就是这样叠加的。
- 噪声纹理节点要先设 `noise_dimensions="4D"`，`W` 插口才存在。

## 不提交到 git 的目录

`.gitignore` 忽略了 `.venv/`、`out/`、`.blender/`、`__pycache__/`：

- `.venv/` 约 1.1 GB
- `out/` 是渲染产物
- `.blender/` 用来放官方 Blender 压缩包（如果以后要用）

需要提交的只有 `render/`、`post/`、`style/`、`requirements.txt`、`README.md` 和 `.gitignore`。
