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
| `out/assets*/ui/` | 59 个图标（1 倍 64²、2 倍 128²，锚点居中）：法器 5、进化 5、心法 10、五行 5、补给 2、心灯 4 × 点亮 / 未点亮、奇遇 5、古灯增益 4、夜签 10（朱砂双圈）、信息栏 5；另有 13 枚朱砂印章（`post/ui_seals.py`，由 ui_icons 一起生成）。`meta.json` 里每项有 `kind`、`id`、`name` |
| `out/assets*/weapons/` | 新增 `foxfire_0..2`（夜主弹幕，白色可染色，叠加，朝 +X，建议染 #FF6B5A） |
| `out/assets*/ground/` | 新增 `spring`（灵泉）、`rift` + `rift_glow`（裂隙与叠加辉光，建议染 #D2386A）、`reed_0..2`、`leaves_0..1`、`pebbles_0..1`、`puddle_0`、`bamboo_0..1` |
| `out/review*/` | `additions_sheet.png`、`ui_icons_more.png`（图标和印章原大 / 32 / 24 像素、纸色底和夜色底、放进界面的效果）、`ground_mock.png`（白天和夜晚的地面合成） |

2D 贴图也按 `LANTERN_ART_DENSITY` 出图：噪声在 1 倍网格上生成再放大，所以 2 倍和 1 倍是同一张画，只是边缘更清楚。
1 倍的 PNG 逐字节固定，基准在 `post/golden_1x.json`（依赖锁定的 Pillow 12.3.0）。

## 打包桌面版图集

```bash
A=art/out/assets@2x
art/.venv/bin/python art/post/pack_atlas.py --paper $A/ground/paper.png --out assets/atlas
art/.venv/bin/python art/post/pack_atlas.py --name actors --out assets/atlas $A/hero $A/shade $A/wisp $A/toad $A/golem $A/fox $A/ghoul $A/stonelord $A/fox_wisp $A/bamboo_wraith $A/taofeng_fox $A/rock_a $A/rock_b $A/rock_c $A/stone_lantern $A/stone_lantern_dark $A/ancient_lamp $A/blood_altar $A/merchant $A/bamboo_clump $A/bamboo_clump_broken $A/fox_shrine $A/stone_fox $A/fox_lanterns $A/fox_shrine_grand $A/fox_gate $A/fox_eave_lamp $A/fox_eave_lamp_lit
art/.venv/bin/python art/post/pack_atlas.py --name lanterns --out assets/atlas $A/lantern_red $A/lantern_mirror $A/lantern_frost
art/.venv/bin/python art/post/pack_atlas.py --name boss --out assets/atlas $A/boss
art/.venv/bin/python art/post/pack_atlas.py --name vfx --out assets/atlas $A/vfx $A/weapons $A/vfx_leaves
art/.venv/bin/python art/post/pack_atlas.py --name ground --out assets/atlas $A/ground
art/.venv/bin/python art/post/pack_atlas.py --name ui --no-trim --out assets/atlas $A/ui $A/portrait $A/lamp_icons $A/ui_wash
mkdir -p assets/atlas/screens && cp art/out/screens/{title,logo,scroll_qingqiu,scroll_qingqiu_dawn,scroll_roller}.png art/out/screens/scroll_roller.json assets/atlas/screens/
art/.venv/bin/python art/post/check_atlas.py         # 按游戏读取器的规则检查 assets/atlas
```

格式约定见 `docs/DESIGN.md` 第 15 节。界面图集要加 `--no-trim`（不裁边）。灯笼叠层单独打成 `lanterns`，不要放进 actors。
一页放不下（单页最大 4096²）时自动分页为 `<名>_0`、`<名>_1`……，`index.json` 的 `pages` 跟着改；页数变了要删掉旧的页文件（例如 `actors.json`、`actors.png`）。

**整套重打还是只换几个素材**：

- 用上面的 `pack_atlas.py` 整套重打：本机 `art/out/assets@2x/` 里这个图集的**每一个**素材都是要发布的版本（刚按正式管线全部重渲过，或者改了打包器、图集格式）。
  `art/out/` 不进 git，别人提交的素材本机不一定有最新的，整套重打会把它们悄悄换掉。
- 用 `post/atlas_swap.py` 只换几个素材（平时换一两只妖物、一个道具都用这个）：没换的素材从现有图集还原（裁过边的帧按原尺寸放回），
  只换上给出的文件夹（按 meta 的 `name` 对上，没有的加在最后），重打后逐帧核对没换的帧像素、裁边、锚点、meta、动画序列都不变，不一致时退出码 1；
  旧的页文件会先删掉，页数变了也不会留下多余的文件。

```bash
art/.venv/bin/python art/post/atlas_swap.py --atlas assets/atlas --name actors $A/shade $A/fox   # 只换影妖、赤面狐
art/.venv/bin/python art/post/atlas_swap.py --atlas assets/atlas --name boss $A/boss
art/.venv/bin/python art/post/check_atlas.py
```

## 界面九宫格皮肤（post/ui_skin.py）

```bash
art/.venv/bin/python art/post/ui_skin.py        # → out/skin/*.png + skin.json，审图 out/review@2x/ui_skin_sheet.png、ui_skin_mock.png（约 1 分钟）
art/.venv/bin/python art/post/test_ui_skin.py   # 自检：清单与文件一致、slice 合法、平铺无缝、拉伸带一致、直通 alpha、确定性、体积
mkdir -p assets/atlas/skin && cp art/out/skin/* assets/atlas/skin/
```

只给桌面版用，按 1080p 逻辑像素的 2 倍画，与 `LANTERN_ART_DENSITY` 无关。`ui_skin.nine_slice()` 按 Bevy `TextureSlicer` 的规则切图，审图和样张都用它。
格式和 Bevy 端的用法见 `docs/DESIGN.md` 第 15 节。

## 标题画面与主角头像（render/portrait.py、post/title_screen.py）

```bash
art/.venv/bin/python art/render/portrait.py --all        # 主角胸像 → out/assets*/portrait/（1 倍 128²、2 倍 256²），约 17 秒
art/.venv/bin/python art/post/title_screen.py            # 标题画 + logo → out/screens/，审图 → out/review@2x/title_review*.png，约 1.5 分钟
art/.venv/bin/python art/post/title_screen.py --sample   # 只出候选 out/screens/title_candidate.png 和新旧对比 review@2x/title_fix_sample.png，不动 title.png
```

- 胸像用真实的主角模型、同样的墨线和后期，装进界面图标的圆框；`meta.json` 的 `name` 写 `ui`，所以打包后帧名是 `ui/portrait_hero`。
- 标题画是夜色水墨长卷，只用 Pillow + numpy，不用 Blender（`render/title_hero.py` 已不再使用）：
  - 远山三层，层间隔着雾，有阴阳，近山用披麻皴；
  - 月、松；
  - 坡上提灯往山路走的主角背影和两座石灯笼用写意画法；
  - 左侧留给菜单；
  - 纸用短而软的纤维，暗处不像裂纹。
- 人物笔法在 `post/ink_figure.py`，`hub_scroll.py` 和 `title_screen.py` 共用：留白、洇墨、提按的墨线、局部坐标 `Fig` 和姿态 `pose`、飘带、手。
- logo 用完整版马善政字体写“提灯夜行”，加飞白、墨晕和“夜行”朱砂印。
- 界面美术用的完整字体由 `post/ui_fonts.py` 下载并缓存到 `out/fonts/`（OFL）；`assets/fonts/` 里只是游戏用的子集。

## 青丘道具（render/props_qingqiu.py）

```bash
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/props_qingqiu.py   # → out/assets@2x/<道具>/，审图 review@2x/qq_props_sample.png（约 1 分半）
```

审图两张：`qq_props_sample.png`（前五件）和 `qq_courtyard_sample.png`（狐祠庭院四件：和主角、石灯笼、放大 2.5 倍的小狐仙祠比大小；
大狐仙祠挂上留灯，宣纸上、主角灯光里、灯光外；照 `crates/view/src/ground.rs` 摆的庭院，光半径按游戏的世界单位）。

只出 2 倍。渲法同 `produce.py` 的道具（`render_asset`、`PROP_ANCHOR`、`idle_S_00` 一帧、渲染锁）；模型在 `models/qingqiu_props.py`。
`--only a,b` 只重渲部分，`--review` 只自检和重拼审图，`--sample` 渲到 `out/qq_props_sample@2x/` 试样。EXR 中间文件放 `out/_tmp_qq/`。

| 素材 | 帧（2 倍） | 内容 |
|---|---|---|
| `bamboo_clump` | 320² | 土丘上八竿墨竹，叶尖约 2.9 米（主角的 1.3 倍）。前排浓墨、后排淡彩石绿；竹叶是不描线的笔触。`broken_variant` |
| `bamboo_clump_broken` | 320² | 同画布、同锚点、同纸纹：斜劈的竹桩、倒地的断竹、落叶。打碎竹丛时直接换图。`intact_variant` |
| `fox_shrine` | 192² | 石龛、朱砂柱、淡墨四坡翘角顶；龛里白石狐，台阶上有供品，檐角一盏小青灯（`_emit`）。约 1.3 米（地标：和石灯笼差不多高，宽得多）。挂点 `glow` |
| `stone_fox` | 192² | 方石座上侧身蹲坐的石狐，带苔，褪色红围嘴，不发光。约 1.2 米 |
| `fox_lanterns` | 192² | 木柱、竹梁、翘角瓦檐，三盏带竹篾的青纸灯（`_emit`），柱上一条朱砂纸符。挂点 `glow`（中心）和 `glow_0..2` |
| `fox_shrine_grand` | 512² | 狐祠庭院的正殿，按这个尺寸建，原样摆（不要放大）：两层台基、四级台阶，三开间（明间龛里白石狐，次间小龛供白石狐珠、墙前垂褪色朱砂布幡），四根朱砂柱，重檐淡墨四坡顶、葫芦宝顶，供桌上团子、香炉、果子；右前檐角一盏小青灯（`_emit`）。约 98 × 90 单位（主角的 1.8 倍高）。挂点 `glow`（青灯，光半径 115）、`eave_lamp`（左次间檐下铁钩的下端，挂留灯） |
| `fox_gate` | 384² | 狐祠庭院入口的石牌坊（冲天柱式一间两柱一楼，不是鸟居）：夹杆石方墩，柱头宝珠，三层额枋带浮雕花板、空白石匾（只有一方朱砂小印）、雀替，两柱之间一段淡墨翘角瓦顶；带苔，左柱系褪色红布，不发光。约 75 × 74 单位，门洞净宽约 1.8 米、净高 2.4 米。锚点在两柱之间的地面中点 |
| `fox_eave_lamp` | 160² | 檐下留灯（没点）：小圆纸灯笼，素白纸、十二根竹篾，木顶盖、木底托、朱砂穗，挂绳顶上一个小铁钩；不发光。约 17 × 10.5 单位（不到石灯笼一半高）。`anchor_kind: "hanging"`，锚点 (0.5, 0.1) 是挂钩顶端；挂点 `flame`（灯芯）；`lit_variant` |
| `fox_eave_lamp_lit` | 160² | 同画布、同锚点、同纸纹：点着的留灯，纸壳透出暖色灯芯（`_emit`），`light_color: "#FF9A4A"`（主角红纸灯的火）、光半径 50。挂点 `flame`；`unlit_variant` |

发光的青丘道具在 meta 里写了 `light_color`（青火 `#8FE3C8`；留灯 `#FF9A4A`）和建议的光半径 `light_radius_units`（世界单位：狐灯 140、狐仙祠 90、
大狐仙祠 115、留灯 50）；meta 里还有 `region: "qingqiu"`。挂着的道具（`anchor_kind: "hanging"`，现在只有留灯）锚点是挂钩顶端，
`check_asset.py` 只要求锚点 x = 0.5、y ≤ 0.25；它的“身高中位数”量的是锚点以上，所以是 0。
`fox_eave_lamp_lit` 的灯芯占了大半个灯，`palette_extra` 里多列了纸纹压暗的灯芯色和灯芯与竹篾的过渡色（同 `lanterns.palette_extra`）。

## 青丘妖物与新动作（render/produce.py、render/qingqiu_review.py）

```bash
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/produce.py --only fox_wisp,bamboo_wraith,taofeng_fox   # 新妖物
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/produce.py --only fox:pounce,ghoul:charge,boss:sweep+summon  # 只渲新动作，原有 move 帧不动
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py review   # 审图和动图 → review@2x/qq_enemies_*、qq_gif_*（--diag 另渲九尾扫的 SE 斜向）
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py sample   # 样张：每个动作几帧到 out/qq_sample@2x/
```

只出 2 倍，妖物只画 E。批次表在 `produce.py` 的 `QINGQIU`（新妖物）和 `BATCH2_ACTIONS`（老妖物的新动作）；`--only 素材:动作+动作` 只重渲这几个动作，其他帧和 meta 保留。

| 素材 | 动作（帧 @ fps） | 说明 |
|---|---|---|
| `fox_wisp` 狐火 | `float` 8@10（平时）、`pounce` 4@10 | 青白火身、背上一排火舌、尾巴散成三缕；悬浮（`floating`）。出图后 `fox_wisp.finish_flame` 把火身吸附到火色，发光层里火身按亮度压暗，眼睛最亮 |
| `bamboo_wraith` 竹魅 | `idle` 4@4（藏在竹丛里）、`move` 6@8（平时）、`shoot` 5@10 | 竹节面具，竹枝甩出竹刺；`muzzle` 挂点是竹刺出手的位置 |
| `taofeng_fox` 讨封狐 | `disguise` 6@8（平时）、`move` 6@10、`reveal` 4@8 | 伪装是斗笠蓑衣的路人，`_emit` 是空的；`reveal` 甩掉蓑衣，眼睛亮起 |
| `fox` 赤面狐 | 新增 `pounce` 6@12 | 伏低蓄力后腾空扑出 |
| `ghoul` 青面鬼 | 新增 `charge` 6@10 | 0–1 蓄力，2–5 是冲锋的跑步循环（`loop_from: 2`） |
| `boss` 九尾 | 新增 `sweep` 6@10、`summon` 4@6 | 扫尾是原地转身一圈；召唤时九条尾尖各点一团狐火（其他动作里藏起来） |

meta：出手动作写 `loop: false` 和 `windup_frames: 2`（蓄力帧数），多个动作的素材写 `default_anim`，新妖物写 `eye_color`（狐火 #F2FFFC、竹魅 #9BF5C9、讨封狐 #FFD23F）。
自检对新动作会报“剪影高和全素材中位数不同”的警告（扑击腾空、伏低、尾扇高），属正常。渲染器在剪影边缘有少量逐次不同的像素，
所以只重渲新动作（`--only 素材:动作`），不要重渲原有的 `move`。

## 青丘地面、迷雾、竹刺、开场卷轴（post/ground_decor.py、vfx_textures.py、weapon_textures.py、scroll_qingqiu.py）

`make_2d.py` 会一起生成前三样（1 倍、2 倍各一遍）。另外：

```bash
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/ground_decor.py --sample   # 审图 review@2x/qq_2d_sample.png（宣纸上和夜里、迷雾 2×2 平铺）
art/.venv/bin/python art/post/scroll_qingqiu.py                               # 开场卷轴 → out/screens/scroll_qingqiu{,_dawn}.png，审图 review@2x/scroll_qingqiu_review.png
art/.venv/bin/python art/post/test_scroll_qingqiu.py                          # 卷轴自检（尺寸、旁白区够空、长夜版只有墨色、两张是同一幅画、确定性）
```

- `ground/qq_*`：落竹叶 `qq_bamboo_leaves_0..2`、竹笋 `qq_shoots_0..1`（锚点在底边）、苔点 `qq_moss_0..1`、青绿晕染 `qq_wash_0..1`（`max_alpha: 0.3`）、狐爪印 `qq_fox_tracks`（`flat: 0.7`）。
- `vfx/mist_0..1`：白色、可染色的无缝平铺雾（大团、碎团），2 倍 512²；meta 写 `tileable: true`、`tile_units: 128`、`alpha_hint`（0.2、0.15），**不写 `tile`**（写了打包会跳过）。建议染 #DDD9CF。
- `weapons/bamboo_spike`：竹刺，锚点居中、朝 +X，`length_units: 28`；`bamboo_spike_trail`：拖尾，叠加、可染色（建议 #A8E6B8），锚点在右端。
- 卷轴：2400×800 不透明，同一幅画两种天光（长夜只有墨色，天明上色）；左上留给旁白，文字由游戏画。

## 淡墨底、竹叶、卷轴轴头（post/fx_extras.py）

```bash
art/.venv/bin/python art/post/fx_extras.py        # → out/assets@2x/ui_wash/、vfx_leaves/，out/screens/scroll_roller.{png,json}，审图 review@2x/fx_extras_review.png
art/.venv/bin/python art/post/test_fx_extras.py   # 自检 13 项（尺寸、白色可染、四边透明、不像圆角方块、确定性、只写自己的文件、能打进图集）
```

只出 2 倍，质感会话要的三样：
- `ui/ink_wash`、`ui/ink_wash_1`：大标题后面垫的一笔淡墨；
- `vfx/bamboo_leaf_0..3`：竹丛打碎时飞的竹叶；
- `screens/scroll_roller.png`：开场卷轴展开时跟着那道边走的轴头。
格式和用法见 `docs/DESIGN.md` 第 15 节。打包时 `ui_wash` 跟 ui 一起用 `--no-trim`，`vfx_leaves` 跟 vfx 一起打。

## 灯驿长卷（post/hub_scroll.py）

```bash
art/.venv/bin/python art/post/hub_scroll.py            # → out/screens/hub/，审图 review@2x/hub_review_{states,figures,ui_720}.png（约 1.5 分钟）
art/.venv/bin/python art/post/hub_scroll.py --sample   # 只出样张 review@2x/hub_sample*.png，不写 out/screens/hub/
art/.venv/bin/python art/post/test_hub_scroll.py       # 自检 19 项，含确定性（另画两遍逐字节比对，约 70 秒；--quick 跳过）
art/.venv/bin/python art/post/hub_scroll.py --dawn-compare <旧目录>   # 另出 review@2x/hub_review_dawn_fix.png（晨光新旧对比）
mkdir -p assets/atlas/screens/hub && cp art/out/screens/hub/* assets/atlas/screens/hub/
```

只出桌面版，Pillow + numpy，不用 Blender。画法复用 `title_screen.py`、`scroll_qingqiu.py` 和 `ink_figure.py`（只 import）。固定种子，重复运行逐字节相同。

- **画面**（1920×1080）：
  - 夜空，月亮留白；
  - 六座远山，从左到右是常羊、章尾山（最远最淡最高）、北冥、幽都（山口里一座黑城）、丹穴、青丘；
  - 白墙、挂“灯驿”匾额的门楼、门边刻“正”字的墙、檐下的厅、更鼓、漏刻；
  - 院子偏左一棵灯树，挂 12 盏纸灯；
  - 四个写意人物，从左到右是老灯匠、货郎、灯童、说书人。货郎的墙影里有条狐狸尾巴。
- **人物画法**：先在宣纸上留白，洇两层淡墨淡彩，再用提按有变化的墨线勾轮廓和衣纹。整张画再乘长夜光照，长夜里只有墨色，只有灯边是暖的。
- **输出格式**（四层心灯、10 盏路灯、晨光和 mask、`hub.json`）见 `docs/DESIGN.md` 第 15 节“灯驿长卷”。晨光只照峰顶和上面四五成的山脊，东坡（右）为主；各层的裁切框固定在 `DAWN_RECTS`（游戏已在用），内容超出就报错。心灯 id 按顺序从 `assets/data/meta.ron` 读；节点数和画里的挂灯位置（`LAMP_SLOTS`，12 个）对不上时脚本报错。悟·金木水火土几盏点亮时，纸上带一丝那一系的颜色。
- **审图**：从盘上读回 PNG，按游戏的顺序合成，包括 0、6、12 盏灯和青丘天明，青丘晨光按 mask 铺开 25%、50%、75%、100%，以及 1280×720 叠名牌、压暗面板、4:3 裁切。
- **自检**：
  - 清单与文件、尺寸一致，节点和人物与 meta.ron、hub.ron 对得上；
  - 各层在画面里，该在 `safe` 里的都在；
  - 每盏灯只改自己那一块，点亮后够暖，叠加放大 1.4 倍时不冲白；叠加层峰值 ≤ 0.75、四边为 0；
  - 火苗 `base` 在火苗矩形里；mask 用满灰阶；晨光只落在自己那座山上；
  - 文字安全区够暗；离灯远处只有墨色；
  - 体积（hub.png < 3 MB，整个目录 < 5 MB）；确定性。
- **已知的不足**：
  - 人物近看仍有些规整，衣纹不多；
  - 墙上的影子只投在白墙上，地上那段是一团淡墨；
  - 章尾山晨光的上沿在 y 97，21:9 会裁掉最淡的一点天光。

## 重做的妖物（精修三维，render/enemies_v2.py）

试玩第 1 轮用户嫌妖物“造型粗糙、像低模”，按世界观会话的外形描述全部重画（用户在 A 精修三维 / B 手绘分件两种样张里选了 A）。
素材名、动画名、方向、挂点都不变，游戏按名字取图，不用改代码。

```bash
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/produce.py --only shade,fox,wisp,golem,fox_wisp,bamboo_wraith,taofeng_fox,ghoul  # 正式出图（V2 表里的素材走 enemies_v2）
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/enemies_v2.py --preview fox:pounce:3 out.png   # 单帧预览（3 倍）
art/.venv/bin/python art/post/check_asset.py art/out/assets@2x/shade art/out/assets@2x/fox
art/.venv/bin/python art/post/enemy_review.py b1 shade fox   # 审图 → review@2x/redo_b1_*（和现版并排、1080p 实际大小、3 倍）、redo_<素材>_<动画>.gif
art/.venv/bin/python art/post/enemy_review.py b2 fox:b1 wisp  # “素材:批”：拿 out/assets@2x_<批>/ 里那一版对比（改过的）
art/.venv/bin/python art/post/atlas_swap.py --atlas assets/atlas --name actors art/out/assets@2x/shade art/out/assets@2x/fox
art/.venv/bin/python art/post/check_atlas.py
```

| 文件 | 作用 |
|---|---|
| `render/enemies_v2.py` | V2 表（素材 → 模型、帧尺寸、锚点、动画、挂点、碰撞半径、眼色）；出帧、逐帧挂点、meta（`style: "paint"`、`contact_radius`） |
| `models/v2kit.py` | 公共件：多档带色相偏移的绘画感材质（明暗和毛色分区走同一条色带）、轮廓光、AOV 缝光（夜里透出的微光）、按设计稿投到表面上的贴片（眼、裂缝；`design_patch` 做任意形状的整块贴片，例如脸谱）、离光越远越粗的墨线、设计稿平面里的笔画扁带和 `brush_material`（飞白、散锋，疾影、狐火用）、后期（不吸附调色板） |
| `models/shade_v2.py` `fox_v2.py` | 影妖、赤面狐 |
| `models/wisp_v2.py` | 疾影：卷云头 + 被风扯长的几笔薄墨（扁带），不描线 |
| `models/golem_v2.py` | 石妖：斧劈块面的山石垒起来，石缝里夹一片发光的魂 |
| `models/fox_wisp_v2.py` | 狐火：发光的火球头（明暗按视线，芯最亮）+ 立起来的火狐尾（扁带） |
| `models/bamboo_v2.py` | 竹魅：一节节竹段（段间墨色竹节）拼成的细长人形，头是一蓬披下来的竹叶（叶缝里焦墨的空、两点眼），手是三根挂竹叶的细竹枝；射刺像拉弓，竹节裂开、节缝透光 |
| `models/taofeng_v2.py` | 讨封狐：扮人是斗笠（顶上三片竹叶）、三层蓑衣、竹杖，蓑衣底下露一截尾巴；现形是穿旧靛蓝袍、长袖的直立狐狸，斗笠挂在背上，眯眼笑（头、耳、尾借用赤面狐） |
| `models/ghoul_v2.py` | 青面鬼：隐式曲面捏出来的驼背大鬼（躯干、大肚子、四肢、头各一块），肚皮发白、透着魂光（AOV），獠牙、黑爪、铁箍、焦墨乱发、暗红破布 |
| `post/enemy_design.py` | 设计稿（二维，纯数据）：比例、眼、裂缝、朱砂红脸的位置；赤面狐的骨架和每帧姿态 |
| `post/enemy_review.py` | 按批审图（现版备份在 `out/assets@2x_old/`） |
| `post/atlas_swap.py` | 图集里只换几个素材：没换的素材从现有图集还原（不依赖本机 out/），打包后逐帧核对没换的帧逐像素相同 |

- 影妖：帧 224²（原 160²），锚点 (0.5, 0.875) 是下摆墨烟的落地点，高约 46 单位（主角 0.88 倍），眼色暖金 `#FFC46B`。
  游戏会给悬浮的妖物整体抬高、上下起伏，帧里只留 ±0.5 单位的“呼吸”。
- 竹魅：帧 320²、锚点 (0.5, 0.875)，挂点 eyes、muzzle（蓄力时在竹刺尖上）。讨封狐：帧 256²（原 224²），reveal 写了 `vertical_motion`
  （一跳、蓑衣掀起，身高一帧一个样）。青面鬼：帧 320²、锚点 (0.5, 0.8)，身子整体往后挪，锚点在身子中心底下；move、charge 都写了
  `vertical_motion`（一步一沉）。
- `v2kit.sdf_mesh`：隐式曲面网格化（surface nets，纯 numpy），配 `smin`、`sd_round_cone`、`sd_ellipsoid` 捏肌肉、肚子这种圆滚滚的形体；
  设计稿三维（x 前、y 上、z 左右，单位）里建，换到模型坐标时注意左右手互换（面要翻过来，见 ghoul_v2._sdf_arrays）。
- 疾影、狐火：帧 224²（原 160²），锚点 (0.5, 0.875)，悬浮。石妖：帧 224²、锚点 (0.5, 0.8)，`register_x_only`
  （锚点正上方是驼背的斜坡，不是头顶）。赤面狐 move 一步一起伏 1.7 单位，写了 `vertical_motion`（自检不查逐帧身高；游戏不读）。
- `contact_radius`：量法同 `docs/PLAYTEST.md` 的表（朝东的帧，锚点往上 52 单位内每行最靠前的点，取第 90 百分位，各帧取中位数），
  默认动画的值和 `game_radius` 取小；各动画分别量的值在 `contact_radius_by_anim`。
- `check_asset.py`：`style: "paint"` 的素材不查调色板比例、墨线占比（多档渐变、焦墨的影妖本来就不在旧的三档色板里），其余照查；
  四足兽用 `register_band`（赤面狐 [0.70, 0.92]）取躯干做 x 配准，迈步的膝盖不算漂移。
- 打包：换素材用 `atlas_swap.py`（见上面“打包桌面版图集”）。actors 一页放得下时是 `actors.json`（第三批起），放不下自动分成 `actors_0`、`actors_1`……（游戏和冒烟测试都按 `index.json` 找页）。

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
| `models/golem.py` `fox.py` `ghoul.py` `stonelord.py` `toad.py` | 石妖、赤面狐与夜主九尾、青面鬼、石将（翁仲）、金蟾（move，只画 E；赤面狐、青面鬼、九尾另有出手动作） |
| `models/fox_wisp.py` `bamboo_wraith.py` `taofeng_fox.py` | 青丘的狐火、竹魅、讨封狐 |
| `models/kit.py` | 妖物建模公共件（石块、管状尾、毛笔形尾、分段晕染材质、破布片、发光眼） |
| `models/lanterns.py` | 主角的灯笼头：红纸灯 red、铜镜灯 mirror、霜瓷灯 frost（id 和光色取自 `assets/data/lamps.ron`） |
| `models/rock.py` `stone_lantern.py` `event_props.py` | 山石 a/b/c、石灯笼（亮 / 未点亮 `stone_lantern_dark`）、古灯、血祭坛、货郎担 `merchant` |
| `render/pipeline.py` | 渲一个素材的全部帧并按输出约定写文件夹（出图脚本共用）；可以每个姿态连渲几层（variants） |
| `render/produce.py` | 正式出图 + 自检 + 审图 |
| `render/qingqiu_review.py` | 青丘妖物的样张、审图和动图 |
| `render/lantern_review.py` | 灯笼拆层的样张和审图（合成、旧帧对比热图、道具）；`full` 出正式素材的 8 向动图、三灯夜景、全帧对比 |
| `render/lamp_icons.py` | 灯的界面图标 `ui/icon_lamp_<灯>`（灯笼头单独渲染，装进图标圆框） |
| `render/style_frame.py` | 风格样张（早期） |

墨线分档（物体放进哪个集合就用哪档，见 `bstyle.LINE_COLLECTIONS`）：
outer 大形体（外轮廓 2.6px + 形线 1.4px + 折痕），inner 小部件（外轮廓 + 1.1px），
thin 细长彩色部件（只有 1.1px，不进粗外轮廓，灯杖、符纸），none 不描线（眼、发光芯、烟缕）；
`cun=True` 另加暗示轮廓线作皴笔。道具用 `setup_camera(..., anchor=PROP_ANCHOR)`，
石妖、精英、夜主用 `BIG_ENEMY_ANCHOR`（meta 里 `anchor_kind: "big_enemy"`）。
meta 里的 `vertical_motion`（整个素材或单个动画）表示动画本身大幅上下（金蟾跳、主角死亡倒地），自检只查水平配准。

**主角和灯笼分层**（灯可以换，docs/GAMEPLAY.md 11.4 节）：主角出两种文件夹，每个姿态在同一个 Blender 会话里连渲 4 遍——
- `hero/`：不带灯笼头的底图（灯杖、杖头留着），没有 `_emit`；`lantern` 挂点照旧（灯芯中心，放光源用），`overlays` 列出叠层；
- `lantern_<灯>/`：这盏灯的叠层，画布、锚点、帧名、`anims` 和底图完全相同，`_emit` 是灯芯。渲的时候只显示这盏灯，
  主角身体（含灯杖）换成 Holdout 材质当遮挡物：被身体挡住的灯笼像素是透明的，墨线也被挡住（身体仍在 Freestyle 视图图里），
  各线条集合临时换成只含这盏灯的（`bstyle.render_scope`）。所以游戏里把叠层原样画在主角帧上面就行，不用管前后。
  纸纹用底图的偏移（`process_layers(grain_name="hero")`），叠起来对得上。meta：`category: "overlay"`、`base: "hero"`、
  `lamp`、`lamp_name`、`light_color`（lamps.ron 里的光色）、`layers: ["emit"]`、`palette_extra`（调色板外的颜色）、`sockets: {}`。
- 自检对叠层另有一套（`check_asset.check_overlay`）：不查身高、配准、着地、墨线占比；查与底图的尺寸、锚点、动画完全一致，
  每帧都有 `_emit`，以及发光重心对准底图的 `lantern` 挂点（灯芯没被挡住的帧 2 倍密度下 ≤2px；被身体挡住一部分的帧、
  死亡倒地的帧只在超过 6px 时警告；全透明的帧不算错）。调色板按全部帧合起来要求 ≥90%（发光像素不算）；单帧只在样本
  ≥300 像素时也要求 ≥90%，更少的只警告——灯笼只露出一小块时，几个被纸纹压暗的藤黄、朱砂像素就能把比例拉到八成，
  这些像素和拆层前的主角帧逐像素相同，只是分母从整个人变成了一盏灯。
- `--only hero:dash+death` 时叠层也只重渲这几个动画。
- 铜镜灯的铜镜立在灯芯后面（朝主角一侧，镜面朝前聚光）：背面朝向（N、NE、NW）灯芯被镜子挡住，叠层几乎没有 `_emit`，
  光源照旧放在 `lantern` 挂点。霜瓷灯的冰裂纹格条是半透明的，发光遮罩仍是整个圆窗。
- 审图：`LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/lantern_review.py full`（约 4 分钟）——每盏灯 walk、idle、
  dash、death 的 8 向动图（宣纸底 / 夜里），三盏灯并排的夜景，旧单遍帧对比底图 + 红纸灯的全帧差异（按动画 × 朝向），自检报告。
  整套主角 + 三份叠层 2 倍约 55 分钟（208 个姿态 × 4 遍，每遍约 3.5 秒）。

**灯的界面图标**（`render/lamp_icons.py`，只出 2 倍）：

```bash
LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/lamp_icons.py   # → out/assets@2x/lamp_icons/，审图 review@2x/lamp_icons_review*.png
```

每盏灯的灯笼头单独渲（四分之三侧面、相机略向下看、灯芯点亮、线宽加粗 1.25 倍好在 32 像素下看清），再按
`render/portrait.py` 装头像的办法装进 `post/ui_icons.py` 的圆框（`disc_back` / `ring_front`，只读借用）：
宣纸圆底、灯后一团该灯光色的晕、灯芯由白热到灯色、色弧是灯的光色兑国画颜料（同五行色弧的配法：火兑朱砂、金兑藤黄赭石、水兑花青）。
128²（64 逻辑像素 × 2），meta 是特效格式，`name: "ui"`，所以打包后帧名是 `ui/icon_lamp_<灯>`；每项有 `kind: "lamp"`、
`id`、`name`（中文名）、`light_color`、`arc_color`。打包时和 `ui/` 一起用 `--no-trim`。

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
