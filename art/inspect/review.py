#!/usr/bin/env python3
"""检视模型的审图：把导出的 glb 重新导入 Blender，用 Cycles（CPU）渲转台、拼图和 idle 动图，顺便验证导出没坏。

用法（仓库根目录）：
  art/.venv/bin/python art/inspect/review.py sword --sample           # 试渲两张小图（正面、四分之三）→ art/out/_inspect_tmp/sample_<id>.png
  art/.venv/bin/python art/inspect/review.py sword wind_wheel         # 正式 → art/out/review@2x/inspect_<id>_turn.gif、_sheet.png、_idle.gif
  art/.venv/bin/python art/inspect/review.py sword --draft --sample   # 用 export.py --draft 的产物
  只出某几样：--only turn,sheet,idle

布置：
  - 模型转、镜头和三点光不动（主光左上前方暖白，补光右下前方冷、四分之一强度，轮廓光右后上方），
    另有一层很暗的天光渐变给金属反光；描边外壳按引擎的画法（背面剔除、纯黑、不受光）在 Cycles 里模拟；
  - 渲成透明底，再铺到宣纸（assets/atlas/paper.png）上，加一笔淡墨晕；自发光的部分加一点泛光（引擎里有 bloom）。
最终渲染包在 bstyle.render_lock() 里。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit  # noqa: E402
from kit import K  # noqa: E402

sys.path.insert(0, str(kit.ART / "post"))
import check_models as CM  # noqa: E402

PAPER = kit.REPO / "assets" / "atlas" / "paper.png"
FONT_LABEL = kit.ART / "out" / "fonts" / "NotoSerifSC-VF.ttf"
LENS = 70.0
FIT = 1.06  # 包围球外留一点边


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def log(msg):
    print(f"[review] {msg}", flush=True)


# ====================================================================== 场景


def setup(glb, mid, size, samples):
    bpy = _bpy()
    from mathutils import Vector  # noqa: PLC0415

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x = r.resolution_y = size
    r.resolution_percentage = 100
    r.film_transparent = True
    r.use_compositing = False
    r.use_sequencer = False
    r.dither_intensity = 0.0
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.max_bounces = 8
    cy.glossy_bounces = 4
    cy.transparent_max_bounces = 24
    cy.sample_clamp_indirect = 6.0
    sc.view_settings.view_transform = "Standard"
    vl = sc.view_layers[0]
    vl.use_pass_emit = True
    w = bpy.data.worlds.new("World")
    sc.world = w
    bpy.ops.import_scene.gltf(filepath=str(glb))
    root = bpy.data.objects[mid]
    extras = dict(root.get("inspect", {})) if root.get("inspect") else {}
    if not extras:
        js, _ = CM.read_glb(glb)
        extras = next(n for n in js["nodes"] if n.get("name") == mid).get("extras", {}).get("inspect", {})
    # 描边外壳：引擎里是背面剔除 + 纯黑不受光；Cycles 不认背面剔除，用 Backfacing 把朝向镜头的那半边变透明
    om = bpy.data.materials.new("review_outline")
    nt = om.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.012, 0.010, 0.009, 1.0)
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], mx.inputs[0])
    nt.links.new(em.outputs[0], mx.inputs[1])
    nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith("_outline"):
            o.data.materials.clear()
            o.data.materials.append(om)
            o.visible_shadow = o.visible_diffuse = o.visible_glossy = o.visible_transmission = False
            o.visible_volume_scatter = False
    # 转台：模型挂在一个空物体下转
    turn = bpy.data.objects.new("Turn", None)
    sc.collection.objects.link(turn)
    turn.rotation_mode = "ZYX"
    root.parent = turn
    # 镜头和灯挂在 rig 下（特写时整体平移）
    rig = bpy.data.objects.new("Rig", None)
    sc.collection.objects.link(rig)
    d = FIT / math.sin(math.atan(18.0 / LENS))
    cam = K.camera((0.0, -d, 0.0), (0.0, 0.0, 0.0), lens=LENS)
    cam.parent = rig
    for name, loc, energy, size_, col in (("Key", (-3.2, -3.6, 3.4), 650.0, 1.3, (1.0, 0.93, 0.84)),
                                          ("Fill", (3.6, -2.8, -0.8), 220.0, 2.6, (0.78, 0.86, 1.0)),
                                          ("Rim", (2.4, 4.2, 3.0), 1100.0, 1.6, (0.92, 0.95, 1.0)),
                                          ("Rim2", (-3.0, 3.6, -1.2), 380.0, 1.6, (1.0, 0.86, 0.72))):
        L = K.area_light(name, loc, (0, 0, 0), energy, size_, color=col)
        L.parent = rig
    _world_gradient()
    bpy.context.view_layer.update()
    return {"root": root, "turn": turn, "rig": rig, "cam": cam, "dist": d, "extras": extras}


def _world_gradient():
    """很暗的天光：上方淡暖、地平一道亮、下方暗，给金属一点反光。"""
    bpy = _bpy()
    w = bpy.context.scene.world
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.30, (0.020, 0.020, 0.024, 1.0)
    cr.elements[1].position, cr.elements[1].color = 0.95, (0.30, 0.28, 0.25, 1.0)
    e = cr.elements.new(0.52)
    e.color = (0.42, 0.40, 0.37, 1.0)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.38
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    o = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], o.inputs["Surface"])


def pose(S, az=0.0, el=0.0, target=None, dist=None, lens=None):
    """模型转到 (方位角, 仰角)（度；方位角正 = 从右侧看，仰角正 = 从上面看）；target 给出时镜头对着那一点（归一化坐标，转之前的）。"""
    bpy = _bpy()
    from mathutils import Euler, Vector  # noqa: PLC0415

    S["turn"].rotation_euler = (math.radians(el), 0.0, math.radians(-az))
    cam = S["cam"]
    cam.data.lens = lens or LENS
    if target is None:
        S["rig"].location = (0.0, 0.0, 0.0)
        cam.location = (0.0, -S["dist"], 0.0)
    else:
        R = Euler((math.radians(el), 0.0, math.radians(-az)), "ZYX").to_matrix()
        p = R @ Vector(target)
        S["rig"].location = p
        cam.location = (0.0, -dist, 0.0)
    cam.rotation_euler = K.look_rot(cam.location, (0.0, 0.0, 0.0))
    bpy.context.view_layer.update()


def norm_point(S, p_m):
    ex = S["extras"]
    c = np.asarray(ex.get("center_m", [0, 0, 0]))
    r = float(ex.get("radius_m", 1.0))
    return tuple((np.asarray(p_m) - c) / r)


def render(path_exr):
    """渲一张，返回 (rgba 线性预乘, emit 线性)。"""
    bpy = _bpy()
    from style import bstyle as B  # noqa: PLC0415

    sc = bpy.context.scene
    im = sc.render.image_settings
    im.media_type = "MULTI_LAYER_IMAGE"
    if im.file_format != "OPEN_EXR_MULTILAYER":
        im.file_format = "OPEN_EXR_MULTILAYER"
    im.exr_codec = "NONE"
    im.color_depth = "32"
    im.color_mode = "RGBA"
    sc.render.filepath = str(path_exr)
    with B.render_lock():
        bpy.ops.render.render(write_still=True)
    ch = B.read_exr_none(path_exr)
    vn = sc.view_layers[0].name
    rgba = np.stack([ch[f"{vn}.Combined.{c}"] for c in "RGBA"], -1)
    em = np.stack([ch.get(f"{vn}.Emit.{c}", np.zeros(rgba.shape[:2], np.float32)) for c in "RGB"], -1)
    Path(path_exr).unlink(missing_ok=True)
    return rgba, em


# ====================================================================== 后期（numpy / Pillow）


def paper_bg(h, w, seed=3, ink=0.16):
    """宣纸底 + 一笔淡墨晕（线性光）。"""
    from PIL import Image  # noqa: PLC0415

    if PAPER.exists():
        p = np.asarray(Image.open(PAPER).convert("RGB"), np.float64) / 255.0
        reps = (int(math.ceil(h / p.shape[0])), int(math.ceil(w / p.shape[1])), 1)
        p = np.tile(p, reps)[:h, :w]
    else:
        p = np.ones((h, w, 3)) * K.hexc("#EDE4CF")
    lin = K.srgb_to_lin(p)
    rng = np.random.default_rng(seed)
    Y, X = np.mgrid[0:h, 0:w] / max(h, w)
    n = K._noise(rng, (h, w), max(h, w) / 9.0)
    d = np.hypot(X - 0.52, (Y - 0.55) * 1.25)
    blob = np.clip(1.0 - d / 0.62 + 0.25 * n, 0, 1) ** 1.6
    edge = np.clip((np.hypot(X - 0.5, Y - 0.5) - 0.42) / 0.35, 0, 1) ** 2
    shade = 1.0 - ink * blob - 0.10 * edge
    tint = np.array([0.93, 0.95, 1.0])
    return lin * shade[..., None] * (1 - (1 - tint) * blob[..., None] * 0.5)


def finish(rgba, emit, exposure=1.0, bloom=0.35):
    """预乘的线性 RGBA 铺到宣纸上，加泛光，转 sRGB 8 位。"""
    h, w = rgba.shape[:2]
    bg = paper_bg(h, w)
    col = rgba[..., :3] * exposure + bg * (1 - rgba[..., 3:4])
    if bloom and emit.max() > 0:
        e = np.clip(emit * exposure, 0, 8)
        V = K.vfx()
        glow = sum(np.stack([V.fft_blur(e[..., c], s * h / 512) for c in range(3)], -1) * wgt
                   for s, wgt in ((3.0, 0.5), (10.0, 0.35), (28.0, 0.25)))
        col = col + glow * bloom
    lum = col.max(-1, keepdims=True)
    knee = 0.72
    over = np.maximum(lum - knee, 0)
    col = col * np.where(lum > knee, (knee + over / (1 + over * 1.6)) / np.maximum(lum, 1e-6), 1.0)  # 亮处软收，不剪成死白
    return np.round(np.clip(K.lin_to_srgb(np.clip(col, 0, 1)), 0, 1) * 255).astype(np.uint8)


def label_font(size):
    from PIL import ImageFont  # noqa: PLC0415

    for fp in (FONT_LABEL, K.FONT_SERIF):
        try:
            return ImageFont.truetype(str(fp), size)
        except OSError:
            continue
    return ImageFont.load_default()


def put_label(img, text, size=None, pos=(16, 12), color=(40, 34, 28)):
    from PIL import ImageDraw  # noqa: PLC0415

    dr = ImageDraw.Draw(img)
    f = label_font(size or max(14, img.width // 28))
    dr.text(pos, text, font=f, fill=color)
    return img


def save_gif(frames, path, fps=12):
    from PIL import Image  # noqa: PLC0415

    ims = [Image.fromarray(f) for f in frames]
    mosaic = Image.new("RGB", (ims[0].width * 4, ims[0].height * 2))
    for i, k in enumerate(np.linspace(0, len(ims) - 1, 8).astype(int)):
        mosaic.paste(ims[k], ((i % 4) * ims[0].width, (i // 4) * ims[0].height))
    pal = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for im in ims]
    path.parent.mkdir(parents=True, exist_ok=True)
    q[0].save(path, save_all=True, append_images=q[1:], duration=int(1000 / fps), loop=0, optimize=True)


# ====================================================================== 主流程


def views_of(spec_review):
    """拼图的格子：(标题, az, el, 特写)。"""
    base = [("正面", 0.0, 0.0, None), ("背面", 180.0, 0.0, None), ("侧面（右）", 90.0, 0.0, None),
            ("俯视", 0.0, 90.0, None), ("仰视", 0.0, -90.0, None)]
    for title, tgt, dist, az, el in spec_review.get("closeups", []):
        base.append((f"特写：{title}", az, el, (tgt, dist)))
    base.append(("四分之三", -32.0, 18.0, None))
    return base


def run(mid, glb, only, sample=False):
    bpy = _bpy()
    import models  # noqa: PLC0415

    sys.path.insert(0, str(kit.ART))
    tmp = kit.TMP / "review"
    tmp.mkdir(parents=True, exist_ok=True)
    spec_review = _review_spec(models, mid)
    t0 = time.perf_counter()
    if sample:
        S = setup(glb, mid, 400, 24)
        bpy.context.scene.frame_set(0)
        tiles = []
        for title, az, el, cu in [("正面", 0.0, 0.0, None), ("四分之三", -32.0, 18.0, None)] + \
                [(f"特写：{c[0]}", c[3], c[4], (c[1], c[2])) for c in spec_review.get("closeups", [])]:
            _pose_view(S, az, el, cu)
            rgba, em = render(tmp / f"{mid}_s.exr")
            from PIL import Image  # noqa: PLC0415

            tiles.append(put_label(Image.fromarray(finish(rgba, em)), title))
        from PIL import Image  # noqa: PLC0415

        cols = 3
        out = Image.new("RGB", (400 * cols, 400 * int(math.ceil(len(tiles) / cols))))
        for i, t in enumerate(tiles):
            out.paste(t, (400 * (i % cols), 400 * (i // cols)))
        path = kit.TMP / f"sample_{mid}.png"
        out.save(path)
        log(f"试渲 → {path}（{time.perf_counter() - t0:.0f}s）")
        return
    kit.REVIEW.mkdir(parents=True, exist_ok=True)
    if "sheet" in only:
        S = setup(glb, mid, 1024, 64)
        bpy.context.scene.frame_set(0)
        from PIL import Image  # noqa: PLC0415

        tiles = []
        for title, az, el, cu in views_of(spec_review):
            _pose_view(S, az, el, cu)
            rgba, em = render(tmp / f"{mid}_v.exr")
            tiles.append(put_label(Image.fromarray(finish(rgba, em)), title, size=34, pos=(26, 20)))
            log(f"  {title}：{time.perf_counter() - t0:.0f}s")
        cols = 4
        rows = int(math.ceil((len(tiles) + 1) / cols))
        sheet = Image.new("RGB", (1024 * cols, 1024 * rows), (237, 228, 207))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * 1024, (i // cols) * 1024))
        _info_tile(sheet, mid, glb, len(tiles), cols)
        sheet.save(kit.REVIEW / f"inspect_{mid}_sheet.png", optimize=True)
        sheet.resize((sheet.width // 4, sheet.height // 4), Image.LANCZOS).save(tmp / f"thumb_{mid}_sheet.png")
        log(f"拼图 → {kit.REVIEW / f'inspect_{mid}_sheet.png'}")
    if "turn" in only:
        S = setup(glb, mid, 512, 20)
        bpy.context.scene.frame_set(0)
        frames = []
        for k in range(36):
            pose(S, az=k * 10.0, el=12.0)
            rgba, em = render(tmp / f"{mid}_t.exr")
            frames.append(finish(rgba, em))
        save_gif(frames, kit.REVIEW / f"inspect_{mid}_turn.gif", fps=12)
        log(f"转台 → {kit.REVIEW / f'inspect_{mid}_turn.gif'}（{time.perf_counter() - t0:.0f}s）")
    if "detail" in only and spec_review.get("closeups"):
        # 特写的小转台：绕第一处特写左右摆 ±30°，看刃口、轮圈的反光怎么走
        S = setup(glb, mid, 512, 24)
        bpy.context.scene.frame_set(0)
        title, tgt, dist, az0, el0 = spec_review["closeups"][spec_review.get("detail_gif", 0)]
        frames = []
        n = 24
        for k in range(n):
            az = az0 + 30.0 * math.sin(2 * math.pi * k / n)
            _pose_view(S, az, el0 + 6.0 * math.cos(2 * math.pi * k / n), (tgt, dist))
            rgba, em = render(tmp / f"{mid}_d.exr")
            from PIL import Image  # noqa: PLC0415

            frames.append(np.asarray(put_label(Image.fromarray(finish(rgba, em)), f"特写：{title}", size=22)))
        save_gif(frames, kit.REVIEW / f"inspect_{mid}_detail.gif", fps=10)
        log(f"特写动图 → {kit.REVIEW / f'inspect_{mid}_detail.gif'}（{time.perf_counter() - t0:.0f}s）")
    if "idle" in only:
        S = setup(glb, mid, 384, 20)
        sc = bpy.context.scene
        ex = S["extras"]
        dur = ex.get("idle_seconds") or 0
        if dur:
            fps = sc.render.fps
            n = 48
            frames = []
            for k in range(n):
                fr = k / n * dur * fps
                sc.frame_set(int(fr), subframe=fr - int(fr))
                pose(S, az=-32.0, el=18.0)
                rgba, em = render(tmp / f"{mid}_i.exr")
                frames.append(finish(rgba, em))
            save_gif(frames, kit.REVIEW / f"inspect_{mid}_idle.gif", fps=n / dur)
            log(f"idle → {kit.REVIEW / f'inspect_{mid}_idle.gif'}（{time.perf_counter() - t0:.0f}s）")


def _pose_view(S, az, el, cu):
    if cu is None:
        pose(S, az=az, el=el)
    else:
        tgt_m, dist_m = cu
        ex = S["extras"]
        pose(S, az=az, el=el, target=norm_point(S, tgt_m), dist=dist_m / float(ex.get("radius_m", 1.0)))


def _review_spec(models, mid):
    return models.REVIEW.get(mid, {})


def _info_tile(sheet, mid, glb, n_tiles, cols):
    """拼图最后一格写信息：面数、贴图、体积、动画。"""
    from PIL import ImageDraw  # noqa: PLC0415

    res = CM.check_file(Path(glb))
    s = res["stats"]
    i = n_tiles
    x0, y0 = (i % cols) * 1024, (i // cols) * 1024
    if y0 >= sheet.height:
        return
    dr = ImageDraw.Draw(sheet)
    f = label_font(34)
    f2 = label_font(26)
    lines = [f"{mid}.glb", "",
             f"体积 {s['file_bytes'] / 1e6:.2f} MB",
             f"主体 {s.get('tris')} 三角形",
             f"描边外壳 {s.get('outline_tris')} 三角形",
             f"包围球半径 {s.get('radius')}",
             f"动画 {', '.join(s.get('animations') or ['无'])}  {s.get('idle_seconds', '')} 秒", ""]
    for t in s.get("textures", []):
        lines.append(f"{t['name']}  {t['size'][0]}×{t['size'][1]}  {t['bytes'] / 1e3:.0f} KB")
    lines.append("")
    lines.append("自检：" + ("通过" if not res["errors"] else "；".join(res["errors"])))
    y = y0 + 60
    for k, ln in enumerate(lines):
        dr.text((x0 + 60, y), ln, font=f if k == 0 else f2, fill=(40, 34, 28))
        y += 50 if k == 0 else 40


def main(argv=None):
    ap = argparse.ArgumentParser(description="检视模型审图")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--glb", default=None)
    ap.add_argument("--draft", action="store_true", help="用 export.py --draft 的产物")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--only", default="sheet,turn,detail,idle")
    a = ap.parse_args(argv)
    for mid in a.ids:
        glb = Path(a.glb) if a.glb else ((kit.TMP / "draft" / f"{mid}.glb") if a.draft else (kit.OUT_DIR / f"{mid}.glb"))
        run(mid, glb, set(a.only.split(",")), sample=a.sample)
    return 0


if __name__ == "__main__":
    sys.exit(main())
