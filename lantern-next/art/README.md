# 提灯夜行 · 美术管线（无头 Blender）

用程序化 3D 模型 + Blender 无头渲染，批量产出水墨风精灵（填色 / 墨线 / 法线 / 8 方向）。
本目录目前只有冒烟测试，用来确认这台机器（无 GPU、无 libEGL/OSMesa）上哪条渲染路径能跑通。

## 安装

需要 Python 3.13，因为 bpy 5.2.2 只发布了 cp313 的 wheel。

```bash
cd lantern-next/art
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # bpy 5.2.2 + pillow 12.3.0 + numpy 2.5.3
```

wheel 下载约 383 MB，装好后 `.venv` 约 1.1 GB，安装大约 1 分钟。
本机用的是 **pip 装的 bpy 模块**，没有下载官方 Blender 压缩包。
脚本也兼容官方可执行文件（`blender -b --factory-startup -P render/smoke_test.py`），但这条路径**没有实测**。
另外 Blender 自带的 Python 里没有 Pillow，用这条路径时拼图和预览两步会跳过。

## 运行冒烟测试

```bash
art/.venv/bin/python art/render/smoke_test.py     # 在仓库的 lantern-next/ 目录下执行
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

## 不提交到 git 的目录

`.gitignore` 忽略了 `.venv/`、`out/`、`.blender/`：

- `.venv/` 约 1.1 GB
- `out/` 是渲染产物
- `.blender/` 用来放官方 Blender 压缩包（如果以后要用）

需要提交的只有 `render/`、`requirements.txt`、`README.md` 和 `.gitignore`。
