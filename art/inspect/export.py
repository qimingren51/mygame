#!/usr/bin/env python3
"""检视模型：建模 → Cycles 烘焙 → 导出 glb（规格见 docs/DESIGN.md 第 15 节“检视模型”）。

用法（仓库根目录）：
  art/.venv/bin/python art/inspect/export.py sword wind_wheel     # 正式：→ assets/models/inspect/<id>.glb
  art/.venv/bin/python art/inspect/export.py sword --draft        # 试做：512 贴图、少采样 → art/out/_inspect_tmp/draft/<id>.glb
  art/.venv/bin/python art/inspect/export.py --list               # 列出能做的 id

流程（每件）：
  1. models.py 里的函数建零件（程序化网格 + 单个 Principled 的程序材质）；
  2. 同一节点的零件合成一个网格；同一套贴图的节点一起展 UV（Smart UV Project，按零件的贴图密度缩放后再排）；
  3. 逐个通道烘焙到浮点图：底色、粗糙度、金属度、自发光、透明度（各自接到自发光上烘）、切线空间法线、AO；
  4. numpy：底色乘 AO（材质里已经有笔触）、往 UV 岛外扩边、空白处填平均色；粗糙度和金属度打包成 glTF 的
     metallicRoughness（G = 粗糙度，B = 金属度）；自发光按最亮处归一，亮度写进 KHR_materials_emissive_strength；
  5. 换成烘好的材质，摆好节点（挂点、实例），按包围球缩放到半径 1、原点在几何中心；
  6. 生成描边外壳（顶点沿法线外推、翻面，名字以 _outline 结尾）；
  7. idle 动画（转轮、摆动、形变），首尾同一帧；
  8. 导出 glb，再改写一遍：贴图换成 Pillow 压过的 PNG，几条动画合成一条 idle，根节点写 extras。
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

EMIT_CH = ("base", "rough", "metal", "alpha", "emit")


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def log(msg):
    print(f"[inspect] {msg}", flush=True)


# ====================================================================== 场景


def reset_scene():
    bpy = _bpy()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.use_denoising = False
    cy.max_bounces = 4
    cy.diffuse_bounces = 2
    cy.glossy_bounces = 2
    cy.transparent_max_bounces = 8
    w = bpy.data.worlds.new("World")
    sc.world = w
    K.set_world((0.0, 0.0, 0.0), 0.0)
    return sc


def join_node(name, parts):
    return kit.join_objects(parts, name)


# ====================================================================== UV


def unwrap_pack(objs, premade=(), margin=0.004, split_len=None):
    """objs 一起展 UV（BakeUV 层）：不是现成 UV 的面做 Smart UV Project；每个岛按三维面积统一密度、乘零件的 dens；
    最后一起排进 0..1（能转 90°，重叠的岛当一个排）。premade 里的物体整个保留现成的 BakeUV（只参与排）。"""
    bpy = _bpy()
    for o in objs:
        me = o.data
        me.uv_layers.active = me.uv_layers["BakeUV"]
        me.uv_layers["BakeUV"].active_render = True
    with kit.plain_materials(objs):
        _unwrap_pack(objs, premade, margin, split_len)


def _unwrap_pack(objs, premade, margin, split_len):
    bpy = _bpy()
    smart = [o for o in objs if o not in premade]
    if smart:
        kit._edit_select(smart, lambda o, pm: pm < 0.5)
        bpy.ops.uv.smart_project(angle_limit=math.radians(58), island_margin=0.0, area_weight=0.0, correct_aspect=False,
                                 scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    if [o for o in objs if o not in premade]:
        kit.uv_islands_rescale([o for o in objs if o not in premade], skip_premade=False, split_len=split_len)
    kit._edit_select(objs, lambda o, pm: True)
    kw = dict(rotate=True, margin=margin, scale=True, merge_overlap=True, shape_method="CONCAVE", margin_method="FRACTION")
    bpy.ops.uv.pack_islands(**kw)
    bpy.ops.object.mode_set(mode="OBJECT")


# ====================================================================== 烘焙


def principled_of(mat):
    for n in mat.node_tree.nodes:
        if n.type == "OUTPUT_MATERIAL" and n.is_active_output:
            out = n
            break
    else:
        return None, None
    link = out.inputs["Surface"].links
    if not link or link[0].from_node.type != "BSDF_PRINCIPLED":
        return None, out
    return link[0].from_node, out


def _src(nt, sock):
    """输入插口的来源：连着的输出插口，或者它的默认值。"""
    if sock.is_linked:
        return sock.links[0].from_socket
    return sock.default_value


def rewire(mat, channel, img):
    """把材质的某个通道接到自发光上（EMIT 烘焙用）；返回恢复函数。img 是烘焙目标（放一个选中的图像节点）。"""
    nt = mat.node_tree
    P, out = principled_of(mat)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.select = True
    nt.nodes.active = tex
    added = [tex]
    if channel in EMIT_CH and P is not None:
        em = nt.nodes.new("ShaderNodeEmission")
        added.append(em)
        if channel == "emit":
            src_c, src_s = _src(nt, P.inputs["Emission Color"]), _src(nt, P.inputs["Emission Strength"])
        else:
            key = {"base": "Base Color", "rough": "Roughness", "metal": "Metallic", "alpha": "Alpha"}[channel]
            src_c, src_s = _src(nt, P.inputs[key]), 1.0
        if isinstance(src_c, (float, int)):
            em.inputs["Color"].default_value = (src_c, src_c, src_c, 1.0)
        elif hasattr(src_c, "node"):
            nt.links.new(src_c, em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = tuple(src_c)
        if hasattr(src_s, "node"):
            nt.links.new(src_s, em.inputs["Strength"])
        else:
            em.inputs["Strength"].default_value = float(src_s)
        nt.links.new(em.outputs[0], out.inputs["Surface"])

    def restore():
        if P is not None:
            nt.links.new(P.outputs[0], out.inputs["Surface"])
        for n in added:
            nt.nodes.remove(n)

    return restore


def bake_channel(objs, channel, size, samples):
    """把 objs 的某个通道烘到一张 size² 的浮点图，返回 (h, w, 4) 数组（第 0 行在上），alpha > 0 是烘到的像素。"""
    bpy = _bpy()
    img = bpy.data.images.new(f"bake_{channel}", size, size, alpha=True, float_buffer=True)
    img.generated_color = (0.0, 0.0, 0.0, 0.0)
    restores = []
    mats = []
    for o in objs:
        for m in o.data.materials:
            if m is not None and m not in mats:
                mats.append(m)
    for m in mats:
        restores.append(rewire(m, channel, img))
    sc = bpy.context.scene
    sc.cycles.samples = samples
    kit.select_only(objs)
    t0 = time.perf_counter()
    btype = {"normal": "NORMAL", "ao": "AO"}.get(channel, "EMIT")
    kw = dict(type=btype, margin=3, margin_type="EXTEND", use_clear=True, target="IMAGE_TEXTURES")
    if btype == "NORMAL":
        kw.update(normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z")
    bpy.ops.object.bake(**kw)
    for r in restores:
        r()
    px = np.zeros(size * size * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    log(f"  烘 {channel:6s} {size}² {samples} spp：{time.perf_counter() - t0:.1f}s")
    return px.reshape(size, size, 4)[::-1].copy()


def uv_coverage(objs, size):
    """BakeUV 三角形覆盖到的像素（第 0 行在上）：PIL 逐个三角形填，部分覆盖的像素也算。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    for o in objs:
        me = o.data
        uv = np.zeros(len(me.loops) * 2, np.float32)
        me.uv_layers["BakeUV"].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2) * size
        uv[:, 1] = size - uv[:, 1]
        ls = np.zeros(len(me.polygons), np.int64)
        lt = np.zeros(len(me.polygons), np.int64)
        me.polygons.foreach_get("loop_start", ls)
        me.polygons.foreach_get("loop_total", lt)
        for a, n in zip(ls, lt):
            dr.polygon([tuple(p) for p in uv[a:a + n]], fill=255)
    return np.asarray(im) > 0


def dilate(rgb, cover, n):
    """往 UV 岛外扩 n 像素（每圈取已有邻居的平均），剩下的空白填覆盖区的平均色。"""
    out = rgb.copy()
    m = cover.astype(np.float32)
    acc = out * m[..., None]
    for _ in range(n):
        s = np.zeros_like(acc)
        c = np.zeros_like(m)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            s += np.roll(np.roll(acc, dy, 0), dx, 1)
            c += np.roll(np.roll(m, dy, 0), dx, 1)
        grow = (m == 0) & (c > 0)
        acc[grow] = s[grow] / c[grow][:, None]
        m = np.where(grow, 1.0, m)
    mean = (rgb[cover].mean(0) if cover.any() else np.zeros(rgb.shape[-1]))
    acc[m == 0] = mean
    return acc


def soften(a, sigma):
    """去掉烘焙的逐像素噪点（很轻的高斯）。"""
    if sigma <= 0:
        return a
    V = K.vfx()
    return np.stack([V.fft_blur(a[..., c], sigma) for c in range(a.shape[-1])], -1)


def quant(a, step):
    """0..1 → 8 位，按 step 取整（7 位色深，PNG 压得更小，肉眼看不出）。"""
    v = np.clip(a, 0, 1) * 255
    return (np.round(v / step) * step).clip(0, 255).astype(np.uint8)


def lin2srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def to8(a):
    return np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)


def save_png(path, arr):
    from PIL import Image  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path, optimize=True, compress_level=9)
    return path


def bake_atlas(mid, aname, at, objs_by_node, draft, tmpdir):
    """烘一套贴图，写 PNG，返回 {通道: 路径} 和自发光亮度。"""
    bpy = _bpy()
    size = 512 if draft else at["size"]
    esize = min(size, at.get("emit_size", size)) if not draft else 256
    chans = at["channels"]
    big = size >= 2048  # 2K 烘完还要缩小，噪点会被平均掉，采样可以少一半
    spp = dict(base=6 if draft else (20 if big else 32), rough=4 if draft else 12, metal=4 if draft else 8,
               alpha=4 if draft else 12, emit=4 if draft else 12, normal=4 if draft else (16 if big else 32),
               ao=16 if draft else (64 if big else 128))
    world = bpy.context.scene.world
    world.light_settings.distance = at.get("ao_dist", 0.02)
    # 按“烘的时候藏哪些物体”分组：组内一起烘
    groups: dict[tuple, list] = {}
    for node in at["nodes"]:
        hide = tuple(sorted(at.get("bake_hide", {}).get(node, ())))
        groups.setdefault(hide, []).append(node)
    want = ["base", "rough", "metal"] + (["alpha"] if "alpha" in chans else []) + (["emit"] if "emit" in chans else []) + \
        (["normal"] if "normal" in chans else []) + (["ao"] if at.get("ao", True) else [])
    acc = {c: np.zeros((size, size, 4), np.float32) for c in want}
    for hide, nodes in groups.items():
        hidden = []
        for o in bpy.context.scene.objects:
            if o.name in hide or any(o.name.startswith(h + ".") for h in hide):
                o.hide_render = True
                hidden.append(o)
        objs = [objs_by_node[n] for n in nodes]
        m = uv_coverage(objs, size)
        for c in want:
            px = bake_channel(objs, c, size, spp[c])
            if float(np.abs(px[m][:, :3]).max()) <= 0.0 and c not in ("metal", "emit"):
                raise RuntimeError(f"{mid}/{aname}：{c} 烘出来是空的（{', '.join(nodes)}）")
            acc[c][m] = px[m]
        for o in hidden:
            o.hide_render = False
    cover = np.zeros((size, size), bool)
    for hide, nodes in groups.items():
        cover |= uv_coverage([objs_by_node[n] for n in nodes], size)
    outs = dict(at.get("out", {}))
    if draft:
        outs = {k: max(128, v * size // at["size"]) for k, v in outs.items()}

    def shrink(a, key):
        """烘焙尺寸 → 输出尺寸（LANCZOS 缩小，比直接烘小图更干净）。a 是 0..1 浮点 (h, w, c)。"""
        osz = outs.get(key, size)
        if osz >= a.shape[0]:
            return a
        from PIL import Image  # noqa: PLC0415

        ch = [np.asarray(Image.fromarray(a[..., c].astype(np.float32), mode="F").resize((osz, osz), Image.LANCZOS))
              for c in range(a.shape[-1])]
        return np.stack(ch, -1).astype(np.float64)
    n_dil = 8 if size >= 1024 else 4
    res = {}
    ao = dilate(acc["ao"][..., :1], cover, n_dil)[..., 0] if "ao" in acc else np.ones((size, size))
    ao_k = at.get("ao_strength", 0.65)
    base = dilate(acc["base"][..., :3], cover, n_dil) * (1 - ao_k + ao_k * ao)[..., None]
    base_s = shrink(soften(lin2srgb(base), 0.35), "base")
    if "alpha" in acc:
        al = shrink(dilate(acc["alpha"][..., :1], cover, n_dil), "base")
        base_s = np.dstack([base_s, al])
    base8 = quant(base_s, 2)
    res["base"] = save_png(tmpdir / f"{mid}_{aname}_base.png", base8)
    if "mr" in chans:
        # 粗糙度、金属度变化慢，用半分辨率、量化成 64 / 16 级（PNG 小很多，看不出来）
        rough = dilate(acc["rough"][..., :1], cover, n_dil)[..., 0]
        metal = dilate(acc["metal"][..., :1], cover, n_dil)[..., 0]
        mr = np.dstack([np.full_like(rough, 1.0), rough, metal])
        outs.setdefault("mr", max(256, size // 2))
        mr8 = to8(shrink(mr, "mr"))
        mr8[..., 0] = 255
        mr8[..., 1] = (np.round(mr8[..., 1] / 4.0) * 4).clip(0, 255).astype(np.uint8)
        mr8[..., 2] = (np.round(mr8[..., 2] / 17.0) * 17).clip(0, 255).astype(np.uint8)
        res["mr"] = save_png(tmpdir / f"{mid}_{aname}_mr.png", mr8)
    else:
        res["rough_const"] = float(np.median(acc["rough"][cover][:, 0])) if cover.any() else 0.5
    if "normal" in chans:
        nm = dilate(acc["normal"][..., :3], cover, n_dil)
        far = dilate(cover[..., None].astype(np.float32), cover, n_dil)[..., 0] < 0.5
        nm[~cover & far] = (0.5, 0.5, 1.0)
        nm = shrink(soften(nm, 0.3), "normal")
        v = nm * 2 - 1
        v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)  # 缩小以后重新归一
        res["normal"] = save_png(tmpdir / f"{mid}_{aname}_normal.png", quant(v * 0.5 + 0.5, 2))
    strength = 0.0
    if "emit" in acc:
        em = dilate(acc["emit"][..., :3], cover, n_dil)
        em[~cover] = 0.0
        strength = float(em.max())
        if strength > 1e-4:
            outs.setdefault("emit", esize)
            res["emit"] = save_png(tmpdir / f"{mid}_{aname}_emit.png", quant(shrink(lin2srgb(em / strength), "emit"), 2))
    res["emit_strength"] = strength
    res["coverage"] = float(cover.mean())
    return res


def baked_material(name, tex, *, blend=False, alpha_from_base=False):
    """烘好的材质：底色（sRGB，可带 alpha）、法线贴图、metallicRoughness、自发光 × 亮度。导出器认得这种接法。"""
    bpy = _bpy()
    m = bpy.data.materials.new(name)
    m.use_backface_culling = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    P = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(P.outputs[0], out.inputs["Surface"])

    def img_node(path, cs):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(path), check_existing=False)
        t.image.colorspace_settings.name = cs
        t.interpolation = "Linear"
        return t

    tb = img_node(tex["base"], "sRGB")
    nt.links.new(tb.outputs["Color"], P.inputs["Base Color"])
    if alpha_from_base:
        nt.links.new(tb.outputs["Alpha"], P.inputs["Alpha"])
    if "mr" in tex:
        tm = img_node(tex["mr"], "Non-Color")
        sp = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(tm.outputs["Color"], sp.inputs["Color"])
        nt.links.new(sp.outputs["Green"], P.inputs["Roughness"])
        nt.links.new(sp.outputs["Blue"], P.inputs["Metallic"])
    else:
        P.inputs["Roughness"].default_value = tex.get("rough_const", 0.6)
        P.inputs["Metallic"].default_value = 0.0
    if "normal" in tex:
        tn = img_node(tex["normal"], "Non-Color")
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UVMap"
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], P.inputs["Normal"])
    if "emit" in tex:
        te = img_node(tex["emit"], "sRGB")
        nt.links.new(te.outputs["Color"], P.inputs["Emission Color"])
        P.inputs["Emission Strength"].default_value = tex["emit_strength"]
    if blend:
        m.surface_render_method = "BLENDED"
    return m


# ====================================================================== 网格整理


def apply_pivot(ob, pivot):
    """把物体原点移到 pivot（米），网格反向平移。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    ob.data.transform(Matrix.Translation(-Vector(pivot)))
    if ob.data.shape_keys:
        for kb in ob.data.shape_keys.key_blocks:
            co = np.zeros(len(kb.data) * 3)
            kb.data.foreach_get("co", co)
            kb.data.foreach_set("co", (co.reshape(-1, 3) - np.asarray(pivot)).ravel())
    ob.location = pivot


def world_points(objs):
    pts = []
    for o in objs:
        me = o.data
        co = np.zeros(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        M = np.array(o.matrix_world)
        co = co.reshape(-1, 3)
        pts.append(co @ M[:3, :3].T + M[:3, 3])
    return np.vstack(pts)


def normalize(objs):
    """包围球：中心 = 包围盒中心，半径 = 离中心最远的顶点。网格和形变键缩放 1/r，顶层物体的位置平移、缩放，子物体的位置缩放。"""
    bpy = _bpy()
    bpy.context.view_layer.update()
    P = world_points(objs)
    c = (P.min(0) + P.max(0)) / 2
    r = float(np.linalg.norm(P - c, axis=1).max())
    done = set()
    for o in objs:
        me = o.data
        if me.name in done:
            continue
        done.add(me.name)
        co = np.zeros(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        me.vertices.foreach_set("co", co / r)
        if me.shape_keys:
            for kb in me.shape_keys.key_blocks:
                kco = np.zeros(len(kb.data) * 3)
                kb.data.foreach_get("co", kco)
                kb.data.foreach_set("co", kco / r)
        me.update()
    for o in bpy.context.scene.objects:
        if o.parent is None:
            o.location = (np.asarray(o.location) - c) / r
        else:
            o.location = np.asarray(o.location) / r
    bpy.context.view_layer.update()
    return c, r


def add_shape_keys(ob, keys):
    """keys = {名字: f(basis 顶点 (N,3) 米, attr) → 位移 (N,3)}；attr(名字) 读点属性（没有时 None），向量属性是 (N,3)。"""
    me = ob.data
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)

    def attr(name):
        if name not in me.attributes:
            return None
        at = me.attributes[name]
        if at.data_type == "FLOAT_VECTOR":
            v = np.zeros(len(at.data) * 3, np.float32)
            at.data.foreach_get("vector", v)
            return v.reshape(-1, 3)
        v = np.zeros(len(at.data), np.float32)
        at.data.foreach_get("value", v)
        return v

    if not me.shape_keys:
        ob.shape_key_add(name="Basis", from_mix=False)
    for name, fn in keys.items():
        kb = ob.shape_key_add(name=name, from_mix=False)
        kb.slider_min, kb.slider_max = -1.0, 1.0
        kb.data.foreach_set("co", (co + fn(co, attr)).ravel())


def decimated(src_me, ratio):
    """减面后的网格副本（Decimate 塌边，ol 等属性跟着插值）。描边只管轮廓，用不着主体那么密。"""
    bpy = _bpy()
    tmp = bpy.data.objects.new("_dec", src_me.copy())
    bpy.context.scene.collection.objects.link(tmp)
    md = tmp.modifiers.new("Dec", "DECIMATE")
    md.decimate_type = "COLLAPSE"
    md.ratio = ratio
    md.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    old = tmp.data
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(old)
    return me


def make_outline(src_me, width, name, mat, ratio=1.0):
    """描边外壳：只取 ol > 0 的面（有形变键的不减面，其余按 ratio 减面），顶点沿（按角度加权的）顶点法线外推
    width × ol，再翻面。形变键照样各算一份。"""
    bpy = _bpy()
    import bmesh  # noqa: PLC0415

    if ratio < 1.0 and not src_me.shape_keys:
        src_me = decimated(src_me, ratio)
    bm = bmesh.new()
    bm.from_mesh(src_me)
    ol = bm.verts.layers.float.get("ol")
    orig = bm.verts.layers.int.new("orig")
    for v in bm.verts:
        v[orig] = v.index
    drop = [f for f in bm.faces if min(v[ol] for v in f.verts) <= 0.0]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.verts.ensure_lookup_table()
    idx = np.array([v[orig] for v in bm.verts])
    k = np.array([v[ol] for v in bm.verts])

    def offset_positions(base_co):
        for v, p in zip(bm.verts, base_co[idx]):
            v.co = p
        bm.normal_update()
        nrm = np.array([tuple(v.normal) for v in bm.verts])
        return base_co[idx] + nrm * (width * k)[:, None]

    def key_co(kb):
        a = np.zeros(len(kb.data) * 3)
        kb.data.foreach_get("co", a)
        return a.reshape(-1, 3)

    vco = np.zeros(len(src_me.vertices) * 3)
    src_me.vertices.foreach_get("co", vco)
    base = offset_positions(vco.reshape(-1, 3))
    keys = []
    if src_me.shape_keys:
        for kb in src_me.shape_keys.key_blocks[1:]:
            keys.append((kb.name, offset_positions(key_co(kb)), kb.slider_min, kb.slider_max))
    for v, p in zip(bm.verts, base):
        v.co = p
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for at in [a.name for a in me.attributes if not a.name.startswith(".") and a.name not in ("position",)]:
        try:
            me.attributes.remove(me.attributes[at])
        except (RuntimeError, KeyError):
            pass
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.shade_smooth()
    me.materials.append(mat)
    return me, keys


def outline_material(mid):
    bpy = _bpy()
    m = bpy.data.materials.new(f"{mid}_outline")
    m.use_backface_culling = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(rgb.outputs[0], out.inputs["Surface"])  # 导出成 KHR_materials_unlit 的纯黑
    return m


def clean_mesh(me):
    """导出前：只留烘焙 UV（改名 UVMap），删掉建模用的属性。"""
    if "UVMap" in me.uv_layers and "BakeUV" in me.uv_layers:
        me.uv_layers.remove(me.uv_layers["UVMap"])
    if "BakeUV" in me.uv_layers:
        me.uv_layers["BakeUV"].name = "UVMap"
    for at in [a.name for a in me.attributes]:
        if at in ("ol", "dens", "facet", "side", "edge_d", "premade") or at.startswith("k_"):
            me.attributes.remove(me.attributes[at])


# ====================================================================== 动画


def build_anim(spec, objs, outlines):
    """idle：frames 帧、fps；spin = {节点: (欧拉分量, 圈数)}；swing = {节点: [(分量, 度, 周期数, 相位)]}；
    weights = {节点: [(形变键, 幅度, 周期数, 相位)]}（节点的描边外壳同样动）。全部按帧采样、线性插值，第 0 帧 = 第 N 帧。"""
    bpy = _bpy()
    an = spec.get("anim")
    if not an:
        return None
    N, fps = an["frames"], an["fps"]
    sc = bpy.context.scene
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 0, N
    for node, (axis, cycles) in an.get("spin", {}).items():
        for o in [objs[node]]:
            base = o.rotation_euler[axis]
            for f in range(N + 1):
                o.rotation_euler[axis] = base + 2 * math.pi * cycles * f / N
                o.keyframe_insert("rotation_euler", index=axis, frame=f)
            o.rotation_euler[axis] = base
    for node, lst in an.get("swing", {}).items():
        o = objs[node]
        base = tuple(o.rotation_euler)
        for f in range(N + 1):
            rot = list(base)
            for axis, deg, cyc, ph in lst:
                rot[axis] = base[axis] + math.radians(deg) * math.sin(2 * math.pi * cyc * f / N + ph)
            o.rotation_euler = rot
            for axis, _, _, _ in lst:
                o.keyframe_insert("rotation_euler", index=axis, frame=f)
        o.rotation_euler = base
    for node, lst in an.get("weights", {}).items():
        mes = [objs[node].data] + ([outlines[node].data] if node in outlines else [])
        for me in mes:
            kbs = me.shape_keys.key_blocks
            for f in range(N + 1):
                for key, amp, cyc, ph in lst:
                    kbs[key].value = amp * math.sin(2 * math.pi * cyc * f / N + ph)
                    kbs[key].keyframe_insert("value", frame=f)
    for a in bpy.data.actions:
        fcs = []
        if hasattr(a, "fcurves"):
            fcs = list(a.fcurves)
        else:
            for layer in getattr(a, "layers", []):
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        fcs += list(bag.fcurves)
        for fc in fcs:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    return N / fps


# ====================================================================== 主流程


def export_one(mid, draft=False):
    bpy = _bpy()
    import models  # noqa: PLC0415

    t0 = time.perf_counter()
    reset_scene()
    spec = models.MODELS[mid](draft)
    tmpdir = kit.TMP / ("draft" if draft else "final") / mid
    tmpdir.mkdir(parents=True, exist_ok=True)
    parts = [o for o in bpy.context.scene.objects if "inspect_node" in o]
    groups = {node: [p for p in parts if p["inspect_node"] == node] for node in spec["nodes"]}
    objs = {node: join_node(node, ps) for node, ps in groups.items()}
    premade = {n for n, d in spec["nodes"].items() if d.get("uv") == "premade"}
    for o in objs.values():
        for kn in [k for k in o.keys() if k.startswith("inspect_")]:
            del o[kn]
    # 形变键（米）
    for node, d in spec["nodes"].items():
        if d.get("keys"):
            add_shape_keys(objs[node], spec["keys"][d["keys"]])
    # 先摆好位置（烘 AO 时要看到别的零件）
    for node, d in spec["nodes"].items():
        if "place" in d:
            loc, eul, order = d["place"]
            objs[node].rotation_mode = order
            objs[node].location, objs[node].rotation_euler = loc, eul
    for node, d in spec["nodes"].items():
        if d.get("parent"):
            objs[node].parent = objs[d["parent"]]
    inst = {}
    for new, (src, loc, eul, order) in spec.get("instances", {}).items():
        o = bpy.data.objects.new(new, objs[src].data)
        bpy.context.scene.collection.objects.link(o)
        o.rotation_mode = order
        o.location, o.rotation_euler = loc, eul
        o["inspect_src"] = src
        inst[new] = o
    for new, o in inst.items():
        par = spec["instance_parent"].get(new) if spec.get("instance_parent") else None
        if par:
            o.parent = inst.get(par) or objs[par]
    bpy.context.view_layer.update()
    # UV、烘焙
    tex = {}
    for aname, at in spec["atlases"].items():
        nodes = [objs[n] for n in at["nodes"]]
        if at.get("pack", True):
            unwrap_pack(nodes, premade=[objs[n] for n in at["nodes"] if n in premade], margin=at.get("margin", 0.004),
                        split_len=at.get("split_len"))
        else:
            for o in nodes:
                o.data.uv_layers.active = o.data.uv_layers["BakeUV"]
                o.data.uv_layers["BakeUV"].active_render = True
        log(f"{mid}/{aname}：烘焙 {', '.join(at['nodes'])}")
        tex[aname] = bake_atlas(mid, aname, at, objs, draft, tmpdir)
    # 换材质
    for aname, at in spec["atlases"].items():
        mats = {}
        for bname, opt in at.get("materials", {f"{mid}_{aname}": {}}).items():
            mats[bname] = baked_material(bname, tex[aname], blend=opt.get("blend", False), alpha_from_base=opt.get("blend", False))
        default = next(iter(mats.values()))
        for n in at["nodes"]:
            me = objs[n].data
            old = [m.name if m else "" for m in me.materials]
            remap = []
            for nm in old:
                tgt, best = default, -1
                for bname, opt in at.get("materials", {}).items():
                    for pre in opt.get("from", ()):
                        if nm.startswith(pre) and len(pre) > best:
                            tgt, best = mats[bname], len(pre)
                remap.append(tgt)
            uniq = list(dict.fromkeys(remap))
            mi = np.zeros(len(me.polygons), np.int64)
            me.polygons.foreach_get("material_index", mi)
            new_idx = np.array([uniq.index(remap[i]) for i in range(len(remap))]) if remap else np.zeros(1, np.int64)
            me.materials.clear()
            for m in uniq:
                me.materials.append(m)
            me.polygons.foreach_set("material_index", new_idx[mi] if len(remap) else mi)
    for m in [m for m in bpy.data.materials if m.users == 0]:
        bpy.data.materials.remove(m)
    # 挂点
    for node, d in spec["nodes"].items():
        if d.get("pivot"):
            apply_pivot(objs[node], d["pivot"])
    allobjs = list(objs.values()) + list(inst.values())
    center, radius = normalize(allobjs)
    log(f"包围球：中心 {np.round(center, 4).tolist()} 米，半径 {radius:.4f} 米")
    # 描边
    omat = outline_material(mid)
    width = spec.get("outline_width", 0.004)
    outlines, out_meshes = {}, {}
    for node, o in list(objs.items()) + list(inst.items()):
        me = o.data
        if me.name not in out_meshes:
            ol = np.zeros(len(me.vertices), np.float32)
            me.attributes["ol"].data.foreach_get("value", ol)
            if ol.max() <= 0:
                out_meshes[me.name] = None
                continue
            ome, keys = make_outline(me, width, f"{me.name}_outline", omat, ratio=spec.get("outline_ratio", 0.4))
            out_meshes[me.name] = ome
            ob_tmp = bpy.data.objects.new("_tmp", ome)
            bpy.context.scene.collection.objects.link(ob_tmp)
            if keys:
                ob_tmp.shape_key_add(name="Basis", from_mix=False)
                for kname, co, lo, hi in keys:
                    kb = ob_tmp.shape_key_add(name=kname, from_mix=False)
                    kb.slider_min, kb.slider_max = lo, hi
                    kb.data.foreach_set("co", co.ravel())
            bpy.data.objects.remove(ob_tmp)
        ome = out_meshes[me.name]
        if ome is None:
            continue
        oo = bpy.data.objects.new(f"{node}_outline", ome)
        bpy.context.scene.collection.objects.link(oo)
        oo.parent = o
        outlines[node] = oo
    for o in allobjs:
        clean_mesh(o.data)
    # 根节点
    root = bpy.data.objects.new(mid, None)
    bpy.context.scene.collection.objects.link(root)
    for o in allobjs:
        if o.parent is None:
            o.parent = root
    dur = build_anim(spec, {**objs, **inst}, outlines)
    tris_body = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in allobjs)
    tris_out = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in outlines.values())
    extras = {"id": mid, "up": "+Y", "front": "+Z", "radius": 1.0, "version": 1,
              "center_m": [round(float(v), 5) for v in center], "radius_m": round(radius, 5),
              "tris": int(tris_body), "outline_tris": int(tris_out), "outline_width": width,
              "emissive_strength": {a: round(t["emit_strength"], 3) for a, t in tex.items() if t.get("emit_strength")},
              "idle_seconds": dur}
    root["inspect"] = extras
    bpy.context.scene.frame_set(0)
    out = (kit.TMP / "draft" / f"{mid}.glb") if draft else (kit.OUT_DIR / f"{mid}.glb")
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", export_yup=True, export_apply=False,
                              export_texcoords=True, export_normals=True, export_tangents=False, export_materials="EXPORT",
                              export_image_format="AUTO", export_animations=dur is not None, export_animation_mode="ACTIONS",
                              export_force_sampling=True, export_frame_range=True, export_morph=True,
                              export_morph_normal=False, export_morph_tangent=False, export_extras=True,
                              export_cameras=False, export_lights=False, export_draco_mesh_compression_enable=False)
    pngs = {}
    for aname, t in tex.items():
        for ch in ("base", "mr", "normal", "emit"):
            if ch in t:
                pngs[t[ch].stem] = t[ch]
    info = postprocess(out, pngs, extras)
    log(f"{mid}：{out}  {out.stat().st_size / 1e6:.2f} MB，主体 {tris_body} 三角形，描边 {tris_out}，"
        f"{time.perf_counter() - t0:.0f}s")
    (tmpdir / "report.json").write_text(json.dumps({**extras, **info, "file": str(out)}, ensure_ascii=False, indent=1))
    return out


def postprocess(path, pngs, extras):
    """改写 glb：贴图换成自己压的 PNG（按图像名对上），几条动画合成一条 idle，根节点的 extras 写全。"""
    js, bins = CM.read_glb(path)
    views = js["bufferViews"]
    datas = [bins[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]] for v in views]
    swapped = []
    for im in js.get("images", []):
        nm = im.get("name", "")
        key = next((k for k in pngs if nm == k or nm.startswith(k)), None)
        if key is None:
            continue
        datas[im["bufferView"]] = pngs[key].read_bytes()
        im["mimeType"] = "image/png"
        swapped.append(nm)
    anims = js.get("animations", [])
    if anims:
        ch, sm = [], []
        for a in anims:
            off = len(sm)
            sm += a["samplers"]
            for c in a["channels"]:
                c = dict(c)
                c["sampler"] += off
                ch.append(c)
        js["animations"] = [{"name": "idle", "channels": ch, "samplers": sm}]
    for n in js["nodes"]:
        if n.get("name") == extras["id"]:
            n["extras"] = {"inspect": extras}
    CM.write_glb(path, js, datas)
    return {"swapped_images": swapped, "images": [im.get("name") for im in js.get("images", [])]}


def main(argv=None):
    import models  # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list or not a.ids:
        print(" ".join(models.MODELS))
        return 0
    for mid in a.ids:
        if mid not in models.MODELS:
            print(f"没有这件：{mid}（有：{' '.join(models.MODELS)}）")
            return 2
    for mid in a.ids:
        export_one(mid, a.draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
