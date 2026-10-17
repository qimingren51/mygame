#!/usr/bin/env python3
"""提灯夜行 · 升级卡插画：Blender Cycles 物件特写 + 夜色水墨底（Pillow / numpy）合成。

每张插画画一件物件的特写：
  - 3D（Cycles CPU，960×720）：程序化建模（细分、倒角、平滑着色），Principled BSDF 材质
    （纸用半透 + 透光、铜用金属 + 粗糙度噪声、火用自发光），轮廓光，浅景深，OIDN 降噪；
  - 2D（numpy）：一层夜色水墨晕染的底（湿边、积墨、留白、笔触），按物件的光源烘一圈光；
  - 后期：在线性光里合成、泛光，再统一调色（胶片曲线、暗部偏靛、亮部偏暖或偏冷）、叠绢纹，最后缩到 480×360。
    满幅出图：界面把它等比铺满 268×201 的插画区（1280×720 设计画布），按圆角 6 裁切；左上角压五行印、右上角压品阶签，
    所以两个上角（原图约 70×70）不放主体，并略压暗。

题材（世界观会话定稿）：
  lamp      灯火：纸灯笼特写，灯罩半透，里面一朵长明火，几朵火苗离开灯身、绕灯笼旋成一环；暖金。
  bell_evo  寒山钟（霜铃进化）：覆霜檐下的山寺大青铜古钟，铃口漫出一圈白霜寒波，钟身结冰花；冷白、铜青。
  jixing    疾行：一双绑腿草鞋踏在竹叶上正迈步，脚边卷起一道带竹叶的风（风属木）；青绿、墨。

输出：
  art/out/review@2x/card_art_<id>.png   480×360 RGBA（满幅，不透明），进图集的帧名 ui/card_<id>
  art/out/_card_tmp/<id>.npz            渲染结果缓存（线性 RGBA、深度、自发光、物体编号），只给后期用

用法（仓库根目录）：
  art/.venv/bin/python art/render/card_art.py                  # 三张都渲染并做后期
  art/.venv/bin/python art/render/card_art.py lamp --draft     # 半分辨率、少采样试渲
  art/.venv/bin/python art/render/card_art.py --post           # 只重做后期（读缓存）
另一个子代理也在用 Blender：最终渲染包在 bstyle.render_lock() 里。
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TMP = ART / "out" / "_card_tmp"
FONT_BRUSH = ART.parent / "assets" / "fonts" / "MaShanZheng-subset.ttf"
FONT_SERIF = ART.parent / "assets" / "fonts" / "NotoSerifSC-subset.ttf"
REVIEW = ART / "out" / "review@2x"
RW, RH = 960, 720  # 渲染尺寸
OW, OH = 480, 360  # 出图尺寸（2 倍密度）
IDS = ("jixing", "lamp", "bell_evo")
UI_CARDS = ART / "out" / "assets@2x" / "ui_cards"  # 交付：card_<id>.png + meta.json，打进 cards 页，帧名 ui/card_<id>

# 场景表：id → build（建 3D 场景）、bg（画水墨底）、grade（调色）、samples、seed、fog（远处隐进雾里的深度区间）。
# 本文件只有样张阶段的三张，其余在 card_weapons.py、card_passives.py 里用 @scene 注册。
SCENES: dict[str, dict] = {}
DEFAULT_GRADE = dict(exposure=1.0, shadow="#18223A", high="#FFF0DC", sat=1.0, bloom=0.30, contrast=1.04)


def scene(cid: str, *, name: str = "", samples: int = 128, grade: dict | None = None, seed: int | None = None,
          fog: tuple[float, float] | None = None):
    """注册一张插画的 3D 场景。被装饰的函数 build(draft) 建场景（相机、灯、物体），返回附加信息（可为 None）。"""

    def deco(build):
        SCENES[cid] = dict(build=build, bg=None, name=name, samples=samples, grade=grade or {}, seed=seed, fog=fog)
        return build

    return deco


def background(cid: str):
    """注册一张插画的水墨底：fn(P: Ink, h, w, rng, k) 往 P 上画（k = 宽 / 960）。"""

    def deco(fn):
        SCENES[cid]["bg"] = fn
        return fn

    return deco

# ====================================================================== Blender 侧
# bpy 只在渲染时导入：--post 只用 numpy / Pillow。


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


class Mat:
    """材质节点的小帮手：n() 建节点并设输入，l() 连线，out 是材质输出。"""

    def __init__(self, name: str):
        bpy = _bpy()
        self.m = bpy.data.materials.new(name)
        self.nt = self.m.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")
        self.out.target = "CYCLES"

    def n(self, typ: str, *args, **kw):
        node = self.nt.nodes.new(typ)
        for k, v in kw.items():
            if k.startswith("_"):
                setattr(node, k[1:], v)
            else:
                key = k if k in node.inputs else k.replace("_", " ")
                node.inputs[key].default_value = v
        return node

    def l(self, a, b):
        self.nt.links.new(a, b)
        return b

    # ---- 常用的小组合
    def math(self, op: str, a, b=None, c=None, clamp=False):
        nd = self.n("ShaderNodeMath", _operation=op, _use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                nd.inputs[i].default_value = v
            else:
                self.l(v, nd.inputs[i])
        return nd.outputs[0]

    def mix(self, fac, a, b, blend: str = "MIX", clamp=True):
        nd = self.n("ShaderNodeMix", _data_type="RGBA", _blend_type=blend, _clamp_result=clamp)
        ins = {s.identifier: s for s in nd.inputs}
        for key, v in (("Factor_Float", fac), ("A_Color", a), ("B_Color", b)):
            if isinstance(v, (int, float)):
                ins[key].default_value = v
            elif isinstance(v, tuple):
                ins[key].default_value = v if len(v) == 4 else (*v, 1.0)
            else:
                self.l(v, ins[key])
        return next(s for s in nd.outputs if s.identifier == "Result_Color")

    def mixf(self, fac, a, b):
        """浮点数的线性混合：a·(1-fac) + b·fac。"""
        nd = self.n("ShaderNodeMix", _data_type="FLOAT", _clamp_factor=True)
        ins = {s.identifier: s for s in nd.inputs}
        for key, v in (("Factor_Float", fac), ("A_Float", a), ("B_Float", b)):
            if isinstance(v, (int, float)):
                ins[key].default_value = v
            else:
                self.l(v, ins[key])
        return next(s for s in nd.outputs if s.identifier == "Result_Float")

    def ramp(self, fac, stops, interp="LINEAR"):
        nd = self.n("ShaderNodeValToRGB")
        cr = nd.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for e, (pos, c) in zip(cr.elements, stops):
            e.position = pos
            e.color = c if len(c) == 4 else (*c, 1.0)
        self.l(fac, nd.inputs["Fac"])
        return nd.outputs["Color"], nd.outputs["Alpha"]

    def maprange(self, v, a0, a1, b0=0.0, b1=1.0, clamp=True, interp="LINEAR"):
        nd = self.n("ShaderNodeMapRange", _interpolation_type=interp, _clamp=clamp)
        nd.inputs["From Min"].default_value = a0
        nd.inputs["From Max"].default_value = a1
        nd.inputs["To Min"].default_value = b0
        nd.inputs["To Max"].default_value = b1
        self.l(v, nd.inputs["Value"])
        return nd.outputs["Result"]

    def noise(self, vec=None, scale=5.0, detail=4.0, rough=0.55, w=None, dist=0.0, kind="FBM", lac=2.0):
        nd = self.n("ShaderNodeTexNoise", _noise_dimensions="4D" if w is not None else "3D", _noise_type=kind)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = dist
        nd.inputs["Lacunarity"].default_value = lac
        if w is not None:
            nd.inputs["W"].default_value = w
        if vec is not None:
            self.l(vec, nd.inputs["Vector"])
        return nd

    def coord(self, kind="Object"):
        return self.n("ShaderNodeTexCoord").outputs[kind]

    def bump(self, height, strength=0.3, distance=0.01, normal=None):
        nd = self.n("ShaderNodeBump", Strength=strength, Distance=distance)
        self.l(height, nd.inputs["Height"])
        if normal is not None:
            self.l(normal, nd.inputs["Normal"])
        return nd.outputs["Normal"]

    def principled(self, **kw):
        nd = self.n("ShaderNodeBsdfPrincipled")
        for k, v in kw.items():
            name = k.replace("_", " ")
            sockv = nd.inputs[name]
            if isinstance(v, (int, float)):
                sockv.default_value = v
            elif isinstance(v, tuple):
                sockv.default_value = v if len(v) != 3 or name in ("Subsurface Radius", "Normal", "Tangent") else (*v, 1.0)
            else:
                self.l(v, sockv)
        return nd

    def surface(self, shader):
        self.l(shader, self.out.inputs["Surface"])
        return self.m


def lin(h: str) -> tuple[float, float, float]:
    """sRGB hex → 线性 RGB（节点用）。"""
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def vfx():
    """导入 post/vfx_textures（它用 `import style` 取 art/style/style.py 这个模块；bstyle 用的是 style 包）。
    两种写法会抢 sys.modules["style"]：这里临时让出来，导入完再放回去。"""
    if "vfx_textures" in sys.modules:
        return sys.modules["vfx_textures"]
    if "style" not in sys.modules:
        import style  # noqa: F401, PLC0415  先占住 style 包（art/style/）
    saved = sys.modules.pop("style", None)
    sp = str(ART / "style")
    try:
        import vfx_textures as V  # noqa: PLC0415
    finally:
        if saved is not None:
            sys.modules["style"] = saved
        while sp in sys.path and saved is not None:
            sys.path.remove(sp)
    return V


# ---------------------------------------------------------------------- 场景
def reset_scene(samples: int, draft: bool):
    bpy = _bpy()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = RW, RH
    r.resolution_percentage = 50 if draft else 100
    r.film_transparent = True
    r.use_compositing = False
    r.use_sequencer = False
    r.compositor_device = "CPU"
    r.dither_intensity = 0.0
    r.threads_mode = "AUTO"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.012 if not draft else 0.03
    cy.adaptive_min_samples = 24
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cy.denoising_prefilter = "ACCURATE"
    cy.max_bounces = 12
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 4
    cy.transmission_bounces = 12
    cy.volume_bounces = 1
    cy.transparent_max_bounces = 32
    cy.sample_clamp_direct = 0.0
    cy.sample_clamp_indirect = 8.0
    cy.blur_glossy = 0.8
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.seed = 11
    cy.pixel_filter_type = "BLACKMAN_HARRIS"
    cy.filter_width = 1.5
    vl = sc.view_layers[0]
    vl.use_pass_combined = True
    vl.use_pass_z = True
    vl.use_pass_emit = True
    vl.use_pass_object_index = True
    vl.pass_alpha_threshold = 0.05
    sc.view_settings.view_transform = "Standard" if "Standard" in _enum(sc.view_settings, "view_transform") else sc.view_settings.view_transform
    w = bpy.data.worlds.new("World")
    sc.world = w
    return sc


def _enum(obj, prop):
    try:
        return [e.identifier for e in obj.bl_rna.properties[prop].enum_items]
    except Exception:  # noqa: BLE001
        return []


def set_world(color, strength=1.0):
    bpy = _bpy()
    w = bpy.context.scene.world
    nt = w.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (*color, 1.0)
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def link(ob, parent=None):
    bpy = _bpy()
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def look_rot(src, dst, up=(0, 0, 1)):
    from mathutils import Vector  # noqa: PLC0415

    d = Vector(dst) - Vector(src)
    return d.to_track_quat("-Z", "Y").to_euler()


def camera(loc, target, lens=50.0, fstop=None, focus=None, sensor=36.0, shift=(0.0, 0.0)):
    bpy = _bpy()
    from mathutils import Vector  # noqa: PLC0415

    cd = bpy.data.cameras.new("Cam")
    cam = link(bpy.data.objects.new("Cam", cd))
    cam.location = loc
    cam.rotation_euler = look_rot(loc, target)
    cd.lens = lens
    cd.sensor_width = sensor
    cd.sensor_fit = "HORIZONTAL"
    cd.clip_start = 0.01
    cd.clip_end = 200
    cd.shift_x, cd.shift_y = shift
    if fstop:
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = fstop
        cd.dof.focus_distance = focus if focus else (Vector(target) - Vector(loc)).length
        cd.dof.aperture_blades = 7
        cd.dof.aperture_rotation = math.radians(12)
    bpy.context.scene.camera = cam
    return cam


def area_light(name, loc, target, energy, size, color=(1, 1, 1), size_y=None, spread=180.0):
    bpy = _bpy()
    L = bpy.data.lights.new(name, "AREA")
    L.energy = energy
    L.color = color
    if size_y:
        L.shape = "RECTANGLE"
        L.size, L.size_y = size, size_y
    else:
        L.shape = "DISK"
        L.size = size
    L.spread = math.radians(spread)
    ob = link(bpy.data.objects.new(name, L))
    ob.location = loc
    ob.rotation_euler = look_rot(loc, target)
    return ob


def point_light(name, loc, energy, radius=0.01, color=(1, 1, 1)):
    bpy = _bpy()
    L = bpy.data.lights.new(name, "POINT")
    L.energy = energy
    L.color = color
    L.shadow_soft_size = radius
    ob = link(bpy.data.objects.new(name, L))
    ob.location = loc
    return ob


def sun_light(name, direction, strength, angle_deg=1.0, color=(1, 1, 1)):
    bpy = _bpy()
    from mathutils import Vector  # noqa: PLC0415

    L = bpy.data.lights.new(name, "SUN")
    L.energy = strength
    L.color = color
    L.angle = math.radians(angle_deg)
    ob = link(bpy.data.objects.new(name, L))
    ob.rotation_euler = (-Vector(direction)).to_track_quat("-Z", "Y").to_euler()
    return ob


# ---------------------------------------------------------------------- 几何
def make_obj(name, build, mats, *, smooth=True, subsurf=0, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), parent=None,
             index=0, sharp_deg=None, bevel=None):
    """bmesh 建网格物体：build(bm) 往里加几何。subsurf>0 加细分修改器；bevel=(宽, 段数) 加倒角修改器。"""
    bpy = _bpy()
    import bmesh  # noqa: PLC0415

    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
        if sharp_deg:
            me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    else:
        me.shade_flat()
    for m in mats if isinstance(mats, (list, tuple)) else [mats]:
        me.materials.append(m)
    ob = link(bpy.data.objects.new(name, me), parent)
    ob.location, ob.rotation_euler, ob.scale = loc, rot, scale
    ob.pass_index = index
    if bevel:
        md = ob.modifiers.new("Bevel", "BEVEL")
        md.width, md.segments = bevel
        md.limit_method = "ANGLE"
        md.angle_limit = math.radians(35)
        md.harden_normals = False
    if subsurf:
        md = ob.modifiers.new("Subsurf", "SUBSURF")
        md.levels = md.render_levels = subsurf
    return ob


def lathe_uv(profile, segments=64, radial=None, cap_top=False, cap_bottom=False, zfunc=None):
    """旋转体（带 UV：u = 角度 / 2π，v = 沿轮廓的弧长，单位米）。profile = [(r, z), ...] 自下而上。
    radial(theta, z, i) → 半径倍数。r≈0 的端点合成一个顶点。"""
    from mathutils import Vector  # noqa: PLC0415

    prof = [(float(r), float(z)) for r, z in profile]
    arcs = [0.0]
    for (r0, z0), (r1, z1) in zip(prof, prof[1:]):
        arcs.append(arcs[-1] + math.hypot(r1 - r0, z1 - z0))

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i, (r, z) in enumerate(prof):
            if r <= 1e-7:
                rings.append([bm.verts.new((0.0, 0.0, z))] * (segments + 1))
                continue
            ring = []
            for k in range(segments + 1):
                th = 2 * math.pi * (k % segments) / segments
                kk = radial(th, z, i) if radial else 1.0
                dz = zfunc(th, z, i) if zfunc else 0.0
                if k == segments:
                    ring.append(ring[0])
                else:
                    ring.append(bm.verts.new((r * kk * math.cos(th), r * kk * math.sin(th), z + dz)))
            rings.append(ring)
        for i in range(len(prof) - 1):
            a, b = rings[i], rings[i + 1]
            for k in range(segments):
                vs = [a[k], a[k + 1], b[k + 1], b[k]]
                uvs = [(k / segments, arcs[i]), ((k + 1) / segments, arcs[i]), ((k + 1) / segments, arcs[i + 1]),
                       (k / segments, arcs[i + 1])]
                if vs[0] is vs[1]:
                    vs, uvs = vs[1:], uvs[1:]
                elif vs[2] is vs[3]:
                    vs, uvs = vs[:3], uvs[:3]
                try:
                    f = bm.faces.new(vs)
                except ValueError:
                    continue
                for lp, uv in zip(f.loops, uvs):
                    lp[uvl].uv = uv
        for cap, ring in ((cap_bottom, rings[0]), (cap_top, rings[-1])):
            if cap and len(set(ring)) > 2:
                try:
                    f = bm.faces.new(list(dict.fromkeys(ring)))
                    for lp in f.loops:
                        lp[uvl].uv = (0.5 + 0.5 * lp.vert.co.x, 0.5 + 0.5 * lp.vert.co.y)
                except ValueError:
                    pass
        import bmesh  # noqa: PLC0415

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        _ = Vector

    return build


def frames_along(pts):
    """沿折线的平行移动标架：返回 (切线, 法线, 副法线) 列表，没有扭转突变。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    P = [Vector(p) for p in pts]
    n = len(P)
    T = [(P[min(i + 1, n - 1)] - P[max(i - 1, 0)]).normalized() for i in range(n)]
    a = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    N = [T[0].cross(a).normalized()]
    for i in range(1, n):
        ax = T[i - 1].cross(T[i])
        if ax.length < 1e-9:
            N.append(N[-1].copy())
        else:
            ang = math.acos(max(-1.0, min(1.0, T[i - 1].dot(T[i]))))
            N.append((Matrix.Rotation(ang, 3, ax.normalized()) @ N[-1]).normalized())
    Bn = [t.cross(nn) for t, nn in zip(T, N)]
    return P, T, N, Bn


def tube_uv(pts, radius, sides=10, radius_fn=None, caps=True, twist=0.0, flat=1.0, roll=0.0):
    """沿折线扫圆截面（UV：u = 弧长米，v = 绕一圈 0..1）。radius_fn(t) 是半径倍数；flat<1 时截面压扁成椭圆。"""
    P, T, N, Bn = frames_along(pts)
    n = len(P)
    lens = [0.0]
    for i in range(1, n):
        lens.append(lens[-1] + (P[i] - P[i - 1]).length)

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i in range(n):
            t = i / (n - 1)
            r = radius * (radius_fn(t) if radius_fn else 1.0)
            ring = []
            for k in range(sides):
                th = 2 * math.pi * k / sides + twist * lens[i] + roll
                off = N[i] * (math.cos(th) * r) + Bn[i] * (math.sin(th) * r * flat)
                ring.append(bm.verts.new(P[i] + off))
            rings.append(ring)
        for i in range(n - 1):
            for k in range(sides):
                k1 = (k + 1) % sides
                f = bm.faces.new((rings[i][k], rings[i + 1][k], rings[i + 1][k1], rings[i][k1]))
                for lp, uv in zip(f.loops, ((lens[i], k / sides), (lens[i + 1], k / sides), (lens[i + 1], (k + 1) / sides),
                                           (lens[i], (k + 1) / sides))):
                    lp[uvl].uv = uv
        if caps:
            for ring, rev in ((rings[0], True), (rings[-1], False)):
                c = bm.verts.new(sum((v.co for v in ring), ring[0].co * 0) / len(ring))
                for k in range(sides):
                    k1 = (k + 1) % sides
                    try:
                        f = bm.faces.new((c, ring[k1], ring[k]) if rev else (c, ring[k], ring[k1]))
                        for lp in f.loops:
                            lp[uvl].uv = (0.0, 0.0)
                    except ValueError:
                        pass
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def ribbon_uv(pts, width, ups=None, width_fn=None, segs_w=4, curl=None):
    """沿折线的带子（风、飘带）：UV u = 0..1 沿长，v = 0..1 横跨。ups 给每点的横向方向（默认副法线）。
    curl(t, s) → 横向截面在法线方向的偏移（让带子横截面弯成弧）。"""
    from mathutils import Vector  # noqa: PLC0415

    P, T, N, Bn = frames_along(pts)
    n = len(P)

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for i in range(n):
            t = i / (n - 1)
            side = Vector(ups[i]).normalized() if ups else Bn[i]
            nrm = T[i].cross(side).normalized()
            w = width * (width_fn(t) if width_fn else 1.0)
            row = []
            for j in range(segs_w + 1):
                s = j / segs_w - 0.5
                off = side * (s * w)
                if curl:
                    off = off + nrm * curl(t, s) * w
                row.append(bm.verts.new(P[i] + off))
            grid.append(row)
        for i in range(n - 1):
            for j in range(segs_w):
                f = bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
                for lp, uv in zip(f.loops, ((i / (n - 1), j / segs_w), (i / (n - 1), (j + 1) / segs_w),
                                           ((i + 1) / (n - 1), (j + 1) / segs_w), ((i + 1) / (n - 1), j / segs_w))):
                    lp[uvl].uv = uv

    return build


def ico_cloud(points, radii, subdiv=1):
    """一堆小球（火星、冰晶点）合成一个网格。"""

    def build(bm):
        import bmesh  # noqa: PLC0415
        from mathutils import Matrix  # noqa: PLC0415

        for p, r in zip(points, radii):
            res = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r)
            bmesh.ops.translate(bm, vec=p, verts=res["verts"])
        _ = Matrix

    return build


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------- 渲染
def render_to_cache(cid: str, draft: bool) -> dict:
    """渲染当前场景，读回 EXR，存成 npz（float16）。返回耗时等信息。"""
    bpy = _bpy()
    from style import bstyle as B  # noqa: PLC0415

    sc = bpy.context.scene
    TMP.mkdir(parents=True, exist_ok=True)
    im = sc.render.image_settings
    im.media_type = "MULTI_LAYER_IMAGE"
    if im.file_format != "OPEN_EXR_MULTILAYER":
        im.file_format = "OPEN_EXR_MULTILAYER"
    im.exr_codec = "NONE"
    im.color_depth = "32"
    im.color_mode = "RGBA"
    tag = cid + ("_draft" if draft else "")
    exr = TMP / f"{tag}.exr"
    sc.render.filepath = str(exr)
    t0 = time.perf_counter()
    with B.render_lock():
        t1 = time.perf_counter()
        bpy.ops.render.render(write_still=True)
    t2 = time.perf_counter()
    ch = B.read_exr_none(exr)
    vn = sc.view_layers[0].name

    def rgba(prefix):
        return np.stack([ch[f"{vn}.{prefix}.{c}"] for c in "RGBA"], -1)

    out = {"rgba": rgba("Combined")}
    out["depth"] = ch.get(f"{vn}.Depth.Z", np.zeros(out["rgba"].shape[:2], np.float32))
    em = [ch.get(f"{vn}.Emit.{c}") for c in "RGB"]
    out["emit"] = np.stack(em, -1) if em[0] is not None else np.zeros(out["rgba"].shape[:2] + (3,), np.float32)
    idx_key = next((k for k in ch if k.startswith((f"{vn}.Object Index", f"{vn}.IndexOB"))), None)
    out["index"] = ch[idx_key] if idx_key else np.zeros(out["rgba"].shape[:2], np.float32)
    np.savez_compressed(TMP / f"{tag}.npz", **{k: v.astype(np.float16) if k != "depth" else v.astype(np.float32)
                                              for k, v in out.items()})
    exr.unlink(missing_ok=True)
    info = {"wait_s": round(t1 - t0, 2), "render_s": round(t2 - t1, 2), "samples": sc.cycles.samples,
            "size": [sc.render.resolution_x * sc.render.resolution_percentage // 100,
                     sc.render.resolution_y * sc.render.resolution_percentage // 100]}
    print(f"[{tag}] 渲染 {info['render_s']}s（等锁 {info['wait_s']}s）{info['size']} {info['samples']} spp")
    return info


# ====================================================================== 场景：灯火
FIRE_CORE = (1.0, 0.86, 0.55)
FIRE_GOLD = (1.0, 0.56, 0.16)
FIRE_ORANGE = (1.0, 0.30, 0.055)
FIRE_RED = (0.55, 0.07, 0.018)


def mat_fire(name, strength=18.0, alpha=1.0, tail_fade=0.9, seed=0.0, hot=0.0):
    """火舌：UV.x = 0（头）→ 1（尾）。颜色白金 → 金 → 橙 → 红，越靠边越透（Layer Weight），
    尾部拉长的噪声把火打成一缕缕。"""
    M = Mat(name)
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u = sep.outputs["X"]
    col, _ = M.ramp(u, [(0.0, (1.0, 0.95, 0.80)), (0.12 - 0.08 * hot, FIRE_CORE), (0.35, FIRE_GOLD), (0.7, FIRE_ORANGE),
                        (1.0, FIRE_RED)])
    lw = M.n("ShaderNodeLayerWeight", Blend=0.35)
    facing = lw.outputs["Facing"]
    edge = M.math("POWER", M.math("SUBTRACT", 1.0, facing, clamp=True), 1.6)
    # 沿流向拉长的噪声：物体坐标里沿 UV 方向很难做，直接用 UV（u 方向尺度小、v 方向尺度大）
    mp = M.n("ShaderNodeMapping", _vector_type="POINT")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (2.2, 9.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=2.4, detail=6.0, rough=0.62, w=seed)
    streak = M.maprange(nz.outputs["Fac"], 0.32, 0.72)
    tail = M.math("POWER", M.math("SUBTRACT", 1.0, u, clamp=True), tail_fade)
    a = M.math("MULTIPLY", edge, tail)
    a = M.math("MULTIPLY", a, M.math("ADD", M.math("MULTIPLY", streak, 0.75), M.math("MULTIPLY", M.math("SUBTRACT", 1.0, u), 0.45)),
               clamp=True)
    a = M.math("MULTIPLY", a, alpha, clamp=True)
    emi = M.n("ShaderNodeEmission")
    M.l(col, emi.inputs["Color"])
    st = M.math("MULTIPLY", M.math("ADD", M.math("MULTIPLY", M.math("SUBTRACT", 1.0, u), 1.2), 0.25), strength)
    M.l(st, emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(emi.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def mat_lantern_paper(name, glyph_img=None):
    """红纸灯罩：朱砂纸（漫反射）+ 透光（Translucent），少量直接透明（隐约看得到里面的火与竹篾）。
    透光色随朝向变：正对镜头的地方薄、亮、偏金橙，转到边上纸层叠厚、偏深朱（真灯笼的样子）。
    纸的纤维用噪声做厚薄与轻微凹凸；glyph_img 给出时，纸上写一个墨字（墨挡光）。"""
    M = Mat(name)
    oc = M.coord("Object")
    fib = M.noise(oc, scale=210.0, detail=8.0, rough=0.72)
    fib2 = M.noise(oc, scale=26.0, detail=3.0, rough=0.5)
    thick = M.maprange(M.math("ADD", M.math("MULTIPLY", fib.outputs["Fac"], 0.45), M.math("MULTIPLY", fib2.outputs["Fac"], 0.55)),
                       0.3, 0.7, 0.8, 1.2)
    nrm = M.bump(fib.outputs["Fac"], strength=0.10, distance=0.002)
    lw = M.n("ShaderNodeLayerWeight", Blend=0.5)
    face = M.math("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True)  # 1 = 正对镜头
    tcol, _ = M.ramp(face, [(0.0, (0.30, 0.020, 0.010)), (0.35, (0.75, 0.10, 0.025)), (0.72, (1.0, 0.34, 0.07)),
                            (1.0, (1.0, 0.55, 0.16))])
    tcol = M.mix(M.maprange(thick, 0.8, 1.2, 0.0, 0.55), tcol, (0.45, 0.04, 0.012, 1.0))
    ink = None
    if glyph_img is not None:
        # 从正面（-Y）平面投影：物体坐标 x → 横、z → 竖；只印在朝镜头的半边
        sep = M.n("ShaderNodeSeparateXYZ")
        M.l(oc, sep.inputs[0])
        gx0, gw, gz0, gh = -0.058, 0.116, -0.064, 0.128
        cu = M.n("ShaderNodeCombineXYZ")
        M.l(M.math("DIVIDE", M.math("SUBTRACT", sep.outputs["X"], gx0), gw), cu.inputs["X"])
        M.l(M.math("DIVIDE", M.math("SUBTRACT", sep.outputs["Z"], gz0), gh), cu.inputs["Y"])
        tex = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
        tex.image = glyph_img
        M.l(cu.outputs[0], tex.inputs["Vector"])
        ink = M.math("MULTIPLY", tex.outputs["Alpha"], M.math("LESS_THAN", sep.outputs["Y"], -0.02))
        ink = M.math("MULTIPLY", ink, 1.25, clamp=True)
        tcol = M.mix(ink, tcol, (0.006, 0.0015, 0.001, 1.0))
    diff_c = (0.50, 0.045, 0.018, 1.0)
    dcol = M.mix(M.math("MULTIPLY", ink, 0.9), diff_c, (0.015, 0.012, 0.01, 1.0)) if ink is not None else diff_c
    diff = M.n("ShaderNodeBsdfDiffuse", Roughness=0.8)
    if isinstance(dcol, tuple):
        diff.inputs["Color"].default_value = dcol
    else:
        M.l(dcol, diff.inputs["Color"])
    M.l(nrm, diff.inputs["Normal"])
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(tcol, trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    m1 = M.n("ShaderNodeMixShader")
    m1.inputs[0].default_value = 0.80  # 透光占比
    M.l(diff.outputs[0], m1.inputs[1])
    M.l(trn.outputs[0], m1.inputs[2])
    tr = M.n("ShaderNodeBsdfTransparent", Color=(1.0, 0.55, 0.30, 1.0))
    m2 = M.n("ShaderNodeMixShader")
    see = M.math("MULTIPLY", M.math("SUBTRACT", 1.25, thick), 0.20, clamp=True)  # 薄处多透一点
    if ink is not None:
        see = M.math("MULTIPLY", see, M.math("SUBTRACT", 1.0, ink, clamp=True))
    M.l(see, m2.inputs[0])
    M.l(m1.outputs[0], m2.inputs[1])
    M.l(tr.outputs[0], m2.inputs[2])
    # 外面一层很薄的桐油光
    gl = M.n("ShaderNodeBsdfGlossy", Roughness=0.30, Color=(1.0, 0.82, 0.64, 1.0))
    M.l(nrm, gl.inputs["Normal"])
    fr = M.n("ShaderNodeLayerWeight", Blend=0.10)
    m3 = M.n("ShaderNodeMixShader")
    M.l(fr.outputs["Fresnel"], m3.inputs[0])
    M.l(m2.outputs[0], m3.inputs[1])
    M.l(gl.outputs[0], m3.inputs[2])
    return M.surface(m3.outputs[0])


def mat_fire_volume(name, R, flames, *, rise=0.040, strength=12.0, seed=1.0, turb=0.008, ring_glow=0.10):
    """绕灯的火（体积自发光，一个材质画全部火苗）。物体坐标里火环在 XY 平面、半径 R，局部 +Z 是“上”。
    flames = [(phi0, 大小, 尾长, 尾端半径或 None, 尾端高度)]：火头在 phi0，向 phi 减小的方向拖尾（火往 phi 增大的方向转）。
    尾端半径给出时，火尾沿螺线收到那个半径（从灯身飘出来的那一缕）。
    场 f = Σ 亮度(s) · 截面衰减(d)：s = 火头后方的弧长，d = 到火轴的距离 / 截面半径；再乘一道沿环拉长的噪声，
    把火打成一缕缕。颜色按 f 取（红 → 橙 → 金 → 白金），亮度 ∝ f^1.4。"""
    M = Mat(name)
    oc = M.coord("Object")
    tn = M.noise(oc, scale=16.0, detail=3.0, rough=0.5, w=seed)
    off = M.n("ShaderNodeVectorMath", _operation="MULTIPLY_ADD")
    M.l(tn.outputs["Color"], off.inputs[0])
    off.inputs[1].default_value = (2 * turb, 2 * turb, 2 * turb)
    off.inputs[2].default_value = (-turb, -turb, -turb)
    pv = M.n("ShaderNodeVectorMath", _operation="ADD")
    M.l(oc, pv.inputs[0])
    M.l(off.outputs[0], pv.inputs[1])
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(pv.outputs[0], sep.inputs[0])
    x, y, z = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]
    m = M.math
    rxy = m("SQRT", m("ADD", m("MULTIPLY", x, x), m("MULTIPLY", y, y)))
    phi = m("ARCTAN2", y, x)
    total = None
    for phi0, size, tail, r_end, z_end in flames:
        head = 0.026 * size
        dphi = m("SUBTRACT", m("WRAP", m("ADD", m("SUBTRACT", phi0, phi), 0.7), 2 * math.pi, 0.0), 0.7)
        sarc = m("MULTIPLY", dphi, R)
        spos = m("MAXIMUM", sarc, 0.0)
        sneg = m("MINIMUM", sarc, 0.0)
        u = m("DIVIDE", spos, tail)  # 0 头 → 1 尾长
        if r_end is not None:
            g = m("POWER", m("MINIMUM", u, 1.0), 0.8)
            rax = m("ADD", R, m("MULTIPLY", g, r_end - R))
            zax = m("MULTIPLY", g, z_end)
        else:
            rax = R
            zax = m("MULTIPLY", m("MULTIPLY", u, u), rise * size)
        rr = m("SUBTRACT", rxy, rax)
        zz = m("SUBTRACT", z, zax)
        rho_f = m("MULTIPLY", m("SQRT", m("MAXIMUM", m("SUBTRACT", 1.0, m("POWER", m("DIVIDE", sneg, head), 2.0)), 0.0)), head)
        rho_b = m("ADD", m("MULTIPLY", m("POWER", m("MAXIMUM", m("SUBTRACT", 1.0, m("MULTIPLY", u, 0.92)), 0.0), 1.15), head), 0.0015)
        gt = m("GREATER_THAN", sarc, 0.0)
        rho = m("ADD", m("MULTIPLY", gt, rho_b), m("MULTIPLY", m("SUBTRACT", 1.0, gt), rho_f))
        d = m("DIVIDE", m("SQRT", m("ADD", m("MULTIPLY", rr, rr), m("MULTIPLY", zz, zz))), m("MAXIMUM", rho, 1e-4))
        lum = m("EXPONENT", m("MULTIPLY", u, -2.4))
        body = m("POWER", m("SUBTRACT", 1.0, d, clamp=True), 1.3)
        core = m("MULTIPLY", m("EXPONENT", m("MULTIPLY", m("MULTIPLY", d, d), -9.0)), m("EXPONENT", m("MULTIPLY", u, -7.0)))
        fk = m("ADD", m("MULTIPLY", lum, body), m("MULTIPLY", core, 0.55))
        total = fk if total is None else m("ADD", total, fk)
    # 整圈一道很淡的火痕：看得出火是绕着转的（被噪声打断）
    rr0 = m("SUBTRACT", rxy, R)
    dr = m("DIVIDE", m("SQRT", m("ADD", m("MULTIPLY", rr0, rr0), m("MULTIPLY", z, z))), 0.006)
    total = m("ADD", total, m("MULTIPLY", m("EXPONENT", m("MULTIPLY", m("MULTIPLY", dr, dr), -1.0)), ring_glow))
    # 沿环拉长的细噪声（火舌）
    cx = M.n("ShaderNodeCombineXYZ")
    M.l(m("MULTIPLY", phi, R * 9.0), cx.inputs["X"])
    M.l(m("MULTIPLY", rxy, 70.0), cx.inputs["Y"])
    M.l(m("MULTIPLY", z, 70.0), cx.inputs["Z"])
    dn = M.noise(cx.outputs[0], scale=1.0, detail=5.0, rough=0.6, w=seed + 3.0)
    mod = m("ADD", m("MULTIPLY", M.maprange(dn.outputs["Fac"], 0.36, 0.64, interp="SMOOTHSTEP"), 1.15), 0.22)
    f = m("MULTIPLY", total, mod, clamp=True)
    col, _ = M.ramp(f, [(0.0, (0.45, 0.04, 0.008)), (0.18, FIRE_ORANGE), (0.42, FIRE_GOLD), (0.7, FIRE_CORE), (1.0, (1.0, 0.97, 0.88))])
    emi = M.n("ShaderNodeEmission")
    M.l(col, emi.inputs["Color"])
    M.l(m("MULTIPLY", m("POWER", f, 1.4), strength), emi.inputs["Strength"])
    M.l(emi.outputs[0], M.out.inputs["Volume"])
    return M.m


def glyph_image(text, size=1024, font="brush", ink_px=None):
    """写一个毛笔字（马善政子集字体）到图像，返回 bpy 图像（alpha = 墨）。"""
    bpy = _bpy()
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: PLC0415

    f = ImageFont.truetype(str(FONT_BRUSH if font == "brush" else FONT_SERIF), int(size * 0.78))
    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    bb = dr.textbbox((0, 0), text, font=f)
    dr.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), text, font=f, fill=255)
    im = im.filter(ImageFilter.GaussianBlur(size / 700))
    a = np.asarray(im, np.float32) / 255.0
    rng = np.random.default_rng(5)
    n = rng.standard_normal(a.shape)
    dry = vfx().fft_blur(n, (size / 60, size / 900), angle=0.6)
    dry = (dry - dry.mean()) / (dry.std() + 1e-9)
    a = np.clip(a * (0.86 + 0.14 * np.tanh(dry)), 0, 1)
    img = bpy.data.images.new(f"glyph_{text}", size, size, alpha=True)
    px = np.zeros((size, size, 4), np.float32)
    px[..., 3] = a[::-1]
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


def mat_lacquer(name, color=(0.012, 0.009, 0.008), rough=0.16, coat=1.0, scratch=0.25):
    """黑漆木件：底色近黑、带一点点暖，清漆层 + 细划痕（各向噪声调粗糙度）。"""
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=90.0, detail=5.0, rough=0.6)
    rr = M.maprange(nz.outputs["Fac"], 0.35, 0.7, rough * (1 - scratch), rough * (1 + scratch))
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=rr, Coat_Weight=coat, Coat_Roughness=0.08,
                        Specular_IOR_Level=0.5)
    return M.surface(bsdf.outputs[0])


def mat_gold(name, color=(0.92, 0.62, 0.24), rough=0.28, worn=0.0):
    """金饰：金属，粗糙度带噪声；worn>0 时凹处偏暗（用 AO 近似磨损与积垢）。"""
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=60.0, detail=6.0, rough=0.65)
    rr = M.maprange(nz.outputs["Fac"], 0.3, 0.75, rough * 0.6, rough * 1.5)
    base = (*color, 1.0)
    if worn:
        ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.01, _samples=8)
        base = M.mix(M.math("MULTIPLY", M.math("SUBTRACT", 1.0, ao.outputs["AO"]), worn, clamp=True), base,
                     (color[0] * 0.25, color[1] * 0.18, color[2] * 0.1, 1.0))
    bsdf = M.principled(Base_Color=base, Metallic=1.0, Roughness=rr)
    return M.surface(bsdf.outputs[0])


def mat_silk_thread(name, color, sheen=0.8, rough=0.45):
    M = Mat(name)
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    wave = M.n("ShaderNodeTexWave", _wave_type="BANDS", _bands_direction="Y", Scale=6.0, Distortion=1.5, Detail=2.0)
    M.l(uv, wave.inputs["Vector"])
    nrm = M.bump(wave.outputs["Fac"], strength=0.25, distance=0.0005)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=rough, Sheen_Weight=sheen, Sheen_Roughness=0.35,
                        Sheen_Tint=(1.0, 0.85, 0.75, 1.0), Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_bamboo_dark(name):
    """灯杖竹：深褐近墨的老竹，纵向纤维纹，半光。"""
    M = Mat(name)
    oc = M.coord("Object")
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (60.0, 60.0, 2.0)
    nz = M.noise(mp.outputs["Vector"], scale=3.0, detail=6.0, rough=0.6)
    col, _ = M.ramp(nz.outputs["Fac"], [(0.3, (0.030, 0.022, 0.014)), (0.7, (0.075, 0.052, 0.028))])
    nrm = M.bump(nz.outputs["Fac"], strength=0.15, distance=0.001)
    bsdf = M.principled(Base_Color=col, Roughness=0.42, Coat_Weight=0.4, Coat_Roughness=0.25, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_wax(name):
    M = Mat(name)
    bsdf = M.principled(Base_Color=(0.55, 0.05, 0.03, 1.0), Roughness=0.35, Subsurface_Weight=0.8,
                        Subsurface_Radius=(0.02, 0.006, 0.004), Subsurface_Scale=0.02)
    return M.surface(bsdf.outputs[0])


def build_lamp(draft: bool):
    """灯火：朱砂纸灯笼（十八根竹篾、黑漆上下盖、金口、朱砂穗）挂在画面中间，
    灯里一朵长明火；三朵火苗离开灯身，沿一圈斜着的轨道绕灯旋转，拖着火尾和火星；一缕火从灯肩飘出接进火环。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    set_world(lin("#0B0F1A"), 1.0)
    rng = np.random.default_rng(31)
    # ---------------- 灯罩
    H, R, RC, NR = 0.150, 0.136, 0.054, 18

    def shell_r(z):
        t = max(0.0, 1 - (z / H) ** 2)
        return RC + (R - RC) * t ** 0.58

    def crease(th, z, i):
        a = (th * NR / (2 * math.pi)) % 1.0
        d = min(a, 1 - a) * (2 * math.pi / NR)  # 到最近一根篾的角距离（弧度）
        k = 1 - 0.026 * math.exp(-((d / 0.022) ** 2))
        wr = 0.004 * math.sin(th * 7 + z * 40) * math.sin(z * 23 + 1.3) + 0.002 * math.sin(th * 31 + z * 90)
        return k + wr

    zs = np.linspace(-H, H, 72)
    paper = mat_lantern_paper("LanternPaper", glyph_image("明") if GLYPH else None)
    make_obj("Shell", lathe_uv([(shell_r(z), z) for z in zs], segments=NR * 14, radial=crease), paper, index=1)
    rib_m = mat_bamboo_dark("Rib")
    for i in range(NR):
        th = 2 * math.pi * i / NR
        pts = [((shell_r(z) * 0.968 - 0.0016) * math.cos(th), (shell_r(z) * 0.968 - 0.0016) * math.sin(th), z)
               for z in np.linspace(-H + 0.004, H - 0.004, 40)]
        make_obj(f"Rib{i}", tube_uv(pts, 0.0021, sides=6), rib_m, index=2)
    # ---------------- 上下盖（黑漆木圈 + 金口）
    lac = mat_lacquer("Lacquer")
    gold = mat_gold("Gold", worn=0.6)

    def ring_profile(r_in, r_out, h, bev=0.004):
        return [(r_in, 0.0), (r_out - bev, 0.0), (r_out, bev), (r_out, h - bev), (r_out - bev, h), (r_in, h), (r_in, 0.0)]

    for sgn in (1, -1):
        z0 = sgn * (H - 0.008)
        hh = 0.030
        zb = z0 if sgn > 0 else z0 - hh
        make_obj(f"Cap{sgn}", lathe_uv([(r, z + zb) for r, z in ring_profile(0.036, 0.064, hh)], segments=96), lac,
                 index=2, sharp_deg=50)
        for zz, rr, tr in ((zb + (0.004 if sgn > 0 else hh - 0.004), 0.0655, 0.0032), (zb + (hh - 0.003 if sgn > 0 else 0.003), 0.0648, 0.0022)):
            make_obj(f"Trim{sgn}_{zz:.3f}", torus_build(rr, tr, 96, 12), gold, loc=(0, 0, zz), index=2)
        # 盖面一圈凸起的回纹带：用一圈小方块表示（金）
        nb = 28
        for k in range(nb):
            th = 2 * math.pi * k / nb
            zc = zb + hh * 0.5
            make_obj(f"Stud{sgn}_{k}", box_build(0.0035, 0.0065, 0.006), gold,
                     loc=(0.0645 * math.cos(th), 0.0645 * math.sin(th), zc), rot=(0, 0, th), index=2, bevel=(0.0008, 2))
    # 顶：金钮 + 提梁 + 挂绳
    top = H - 0.008 + 0.030
    make_obj("Knob", lathe_uv([(0.0, top), (0.022, top), (0.024, top + 0.004), (0.016, top + 0.010), (0.007, top + 0.016),
                               (0.009, top + 0.022), (0.0, top + 0.027)], segments=48), gold, index=2)
    bail = [(0.060 * math.cos(a), 0.0, top + 0.002 + 0.075 * math.sin(a)) for a in np.linspace(0.05, math.pi - 0.05, 48)]
    bail_ob = make_obj("Bail", tube_uv(bail, 0.0028, sides=10), gold, index=2)
    bail_ob.rotation_euler = (0, 0, math.radians(32))
    cord_m = mat_silk_thread("Cord", (0.42, 0.03, 0.02), sheen=0.6)
    cord = [(0.0, 0.0, top + 0.077 + 0.02 * s) for s in range(0, 40)]
    cord = [(0.006 * math.sin(i * 0.25), 0.003 * math.sin(i * 0.17), z) for i, (_, _, z) in enumerate(cord)]
    make_obj("CordUp", tube_uv(cord, 0.0035, sides=10, twist=120.0), cord_m, index=2)
    make_obj("Hook", torus_build(0.010, 0.0026, 48, 10), gold, loc=(0, 0, top + 0.081), rot=(math.radians(90), 0, 0.5), index=2)
    # ---------------- 底：穗子
    bot = -(H - 0.008) - 0.030
    make_obj("BotKnob", lathe_uv([(0.0, bot - 0.012), (0.012, bot - 0.010), (0.020, bot - 0.004), (0.024, bot), (0.0, bot)],
                                 segments=48), gold, index=2)
    make_obj("TasselCord", tube_uv([(0, 0, bot - 0.010), (0.001, 0, bot - 0.030)], 0.0028, sides=10), cord_m, index=2)
    make_obj("Bead", lathe_uv([(0.0, -0.0105), (0.006, -0.0095), (0.0098, -0.005), (0.0105, 0.0), (0.0098, 0.005),
                               (0.006, 0.0095), (0.0, 0.0105)], segments=40), gold, loc=(0.001, 0, bot - 0.040), index=2)
    th_top = bot - 0.052
    silk = mat_silk_thread("Tassel", (0.50, 0.035, 0.02), sheen=1.0, rough=0.4)
    make_obj("TasselHead", lathe_uv([(0.0, th_top + 0.003), (0.0065, th_top + 0.001), (0.0085, th_top - 0.008),
                                     (0.0095, th_top - 0.016), (0.0, th_top - 0.016)], segments=40), silk, index=2)
    make_obj("TasselBand", torus_build(0.0094, 0.0018, 40, 8), gold, loc=(0, 0, th_top - 0.009), index=2)

    def strands(bm):
        import bmesh  # noqa: PLC0415

        for k in range(70):
            a = rng.uniform(0, 2 * math.pi)
            rr = 0.0085 * math.sqrt(rng.uniform(0.1, 1.0))
            L = rng.uniform(0.085, 0.105)
            sway = rng.normal(0, 0.004)
            pts = []
            for t in np.linspace(0, 1, 10):
                spread = rr * (1 + 0.9 * t)
                pts.append((spread * math.cos(a) + 0.010 * t * t + sway * t, spread * math.sin(a) * 0.9,
                            th_top - 0.014 - L * t))
            tmp = bmesh.new()
            tube_uv(pts, 0.00065, sides=4, caps=False)(tmp)
            me = _bpy().data.meshes.new("tmp")
            tmp.to_mesh(me)
            tmp.free()
            bm.from_mesh(me)
            _bpy().data.meshes.remove(me)

    make_obj("Strands", strands, silk, index=2)
    # ---------------- 灯里的长明火：小红烛 + 火焰 + 点光
    floor_z = -(H - 0.008)
    make_obj("Plate", lathe_uv([(0.0, floor_z), (0.036, floor_z), (0.036, floor_z + 0.004), (0.0, floor_z + 0.004)], segments=48),
             lac, index=2)
    make_obj("Candle", lathe_uv([(0.0, floor_z + 0.004), (0.0125, floor_z + 0.004), (0.0125, floor_z + 0.092), (0.010, floor_z + 0.096),
                                 (0.0, floor_z + 0.094)], segments=40), mat_wax("Wax"), index=2)
    fz = floor_z + 0.100
    core = make_obj("Flame", lathe_uv([(0.0, 0.0), (0.008, 0.006), (0.0125, 0.017), (0.011, 0.030), (0.0065, 0.046), (0.0, 0.066)],
                                      segments=40), mat_core_flame("CoreFlame"), loc=(0, 0, fz), index=3)
    core.scale = (1.0, 1.0, 1.0)
    point_light("CoreLight", (0, 0, fz + 0.022), 9.0, radius=0.012, color=(1.0, 0.62, 0.30))
    # ---------------- 火环（体积自发光）
    ring_c = Vector((0.0, 0.0, -0.004))
    Rr = 0.272
    rot = Matrix.Rotation(math.radians(-19), 3, "X") @ Matrix.Rotation(math.radians(-8), 3, "Y")
    e1, e2, en = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0)), rot @ Vector((0, 0, 1))
    heads = [math.radians(a) for a in (212.0, 322.0, 82.0)]  # 三朵火：左前、右前、右后（相机在 -Y）
    flames = [(heads[0], 1.35, 0.42, None, 0.0), (heads[1], 1.2, 0.38, None, 0.0), (heads[2], 1.1, 0.34, None, 0.0),
              (heads[1] - 1.05, 0.8, 0.22, 0.118, 0.085)]  # 第四缕：刚从灯肩飘出来，尾巴还连着灯身
    fire = mat_fire_volume("FireVol", Rr, flames, strength=320.0, seed=2.0)
    euler = rot.to_euler()
    make_obj("FireRing", lathe_uv([(Rr - 0.06, -0.05), (Rr + 0.065, -0.05), (Rr + 0.065, 0.09), (Rr - 0.06, 0.09),
                                   (Rr - 0.06, -0.05)], segments=160), fire, loc=ring_c, rot=euler, index=4, smooth=False)
    # 第四缕的尾巴在火环内侧：另一块不重叠的包围体（同一个材质、同一个物体坐标系）
    w0, w1 = heads[1] - 0.95 - 0.95, heads[1] - 0.95 + 0.12

    def wedge(bm):
        import bmesh  # noqa: PLC0415

        rings = []
        for a in np.linspace(w0, w1, 40):
            ring = [bm.verts.new((r * math.cos(a), r * math.sin(a), zz)) for r, zz in
                    ((0.095, -0.03), (Rr - 0.06, -0.03), (Rr - 0.06, 0.13), (0.095, 0.13))]
            rings.append(ring)
        for r0, r1 in zip(rings, rings[1:]):
            for k in range(4):
                bm.faces.new((r0[k], r0[(k + 1) % 4], r1[(k + 1) % 4], r1[k]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    make_obj("FireWedge", wedge, fire, loc=ring_c, rot=euler, index=4, smooth=False)

    def ring_pt(phi, rad=Rr, up=0.0):
        return ring_c + e1 * (rad * math.cos(phi)) + e2 * (rad * math.sin(phi)) + en * up

    def tangent(phi):
        return (-e1 * math.sin(phi) + e2 * math.cos(phi)).normalized()

    for k, (phi0, s, *_r) in enumerate(flames[:3]):
        point_light(f"FlameLight{k}", tuple(ring_pt(phi0 - 0.05, Rr, 0.004)), 1.2 * s, radius=0.025, color=(1.0, 0.48, 0.16))
    # 火星：拉长的小粒（像被转起来甩出的），多在火尾后面，少量往上飘
    ember = mat_ember("Ember")
    for k in range(28):
        fl = flames[k % 3]
        phi = fl[0] - abs(rng.normal(0.0, 0.9)) - 0.1
        rad = Rr + rng.normal(0, 0.020)
        p = ring_pt(phi, rad, rng.normal(0.012, 0.016) + 0.02 * abs(rng.normal()))
        tg = tangent(phi)
        L = rng.uniform(0.003, 0.010)
        r0 = rng.uniform(0.0006, 0.0013)
        q = tg.to_track_quat("X", "Z")
        make_obj(f"Ember{k}", lathe_uv([(0.0, -1.0), (0.6, -0.6), (1.0, 0.0), (0.6, 0.6), (0.0, 1.0)], segments=8),
                 ember, loc=tuple(p), rot=q.to_euler(), scale=(r0, r0, L), index=4)
        ob = _bpy().data.objects[f"Ember{k}"]
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = tg.to_track_quat("Z", "Y")
    for k in range(18):
        p = Vector((rng.normal(0, 0.14), rng.normal(-0.05, 0.1), rng.uniform(0.14, 0.32)))
        make_obj(f"Ash{k}", ico_cloud([(0, 0, 0)], [rng.uniform(0.0008, 0.0015)], 1), ember, loc=tuple(p), index=4)
    # ---------------- 灯光与相机
    area_light("Rim", (-0.55, 0.75, 0.42), (0, 0, 0), 9.0, 0.5, color=(0.55, 0.68, 1.0))
    area_light("Rim2", (0.62, 0.55, -0.15), (0, 0, 0), 3.5, 0.4, color=(0.5, 0.62, 1.0))
    area_light("Fill", (-0.3, -1.0, 0.5), (0, 0, 0), 0.6, 1.0, color=(0.55, 0.62, 0.9))
    camera((0.05, -1.62, -0.045), (0.0, 0.0, -0.022), lens=72.0, fstop=3.5, focus=1.50)
    return {"light": "warm"}


def mat_core_flame(name):
    M = Mat(name)
    gen = M.coord("Generated")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(gen, sep.inputs[0])
    col, _ = M.ramp(sep.outputs["Z"], [(0.0, (0.35, 0.55, 1.0)), (0.12, (1.0, 0.95, 0.85)), (0.55, FIRE_CORE), (1.0, FIRE_GOLD)])
    emi = M.n("ShaderNodeEmission", Strength=36.0)
    M.l(col, emi.inputs["Color"])
    lw = M.n("ShaderNodeLayerWeight", Blend=0.3)
    a = M.math("POWER", M.math("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True), 0.8)
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(emi.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def mat_ember(name):
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=40.0, detail=1.0)
    col = M.mix(nz.outputs["Fac"], (*FIRE_GOLD, 1.0), (*FIRE_ORANGE, 1.0))
    emi = M.n("ShaderNodeEmission", Strength=22.0)
    M.l(col, emi.inputs["Color"])
    return M.surface(emi.outputs[0])


def bez3(a, b, c, d, t):
    return a * (1 - t) ** 3 + b * 3 * (1 - t) ** 2 * t + c * 3 * (1 - t) * t * t + d * t ** 3


def torus_build(R, r, seg=64, ring=12):
    def build(bm):
        import bmesh  # noqa: PLC0415

        vs = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            row = []
            for j in range(ring):
                b = 2 * math.pi * j / ring
                rr = R + r * math.cos(b)
                row.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), r * math.sin(b))))
            vs.append(row)
        for i in range(seg):
            for j in range(ring):
                bm.faces.new((vs[i][j], vs[(i + 1) % seg][j], vs[(i + 1) % seg][(j + 1) % ring], vs[i][(j + 1) % ring]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def box_build(sx, sy, sz):
    def build(bm):
        import bmesh  # noqa: PLC0415

        res = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=res["verts"])

    return build


def comet_build(ring_pt, tangent, en, phi0, Rr, *, length, head, rng, rise):
    """一朵沿轨道飞的火：头圆尾尖，整条顺着圆弧弯，尾巴往上飘（火往上走）；截面加几道火舌的起伏。
    UV.x = 0（头）→ 1（尾）。"""
    from mathutils import Vector  # noqa: PLC0415

    ns, nr = 56, 20
    ph = rng.uniform(0, 6.28, 4)

    def rad(t):
        s = t * length
        if s < head:
            return head * math.sqrt(max(0.0, 1 - ((head - s) / head) ** 2)) ** 0.9
        return head * (1 - (s - head) / (length - head)) ** 1.25

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i in range(ns + 1):
            t = i / ns
            s = t * length - head * 0.15
            phi = phi0 - s / Rr
            c = ring_pt(phi) + en * (rise * t * t)
            tg = tangent(phi)
            radial = (c - ring_pt(phi, 0.0)).normalized()
            up = tg.cross(radial).normalized()
            r0 = rad(t)
            ring = []
            for j in range(nr):
                b = 2 * math.pi * j / nr
                wav = 1 + 0.22 * t * math.sin(3 * b + ph[0] + 9 * t) + 0.12 * t * math.sin(5 * b + ph[1] - 14 * t)
                off = radial * (math.cos(b) * r0 * wav) + up * (math.sin(b) * r0 * wav * 1.15)
                ring.append(bm.verts.new(c + off))
            rings.append(ring)
        tip = bm.verts.new(ring_pt(phi0 - (length * 1.02 - head * 0.15) / Rr) + en * (rise * 1.05))
        for i in range(ns):
            for j in range(nr):
                j1 = (j + 1) % nr
                f = bm.faces.new((rings[i][j], rings[i + 1][j], rings[i + 1][j1], rings[i][j1]))
                for lp, uv in zip(f.loops, ((i / ns, j / nr), ((i + 1) / ns, j / nr), ((i + 1) / ns, (j + 1) / nr), (i / ns, (j + 1) / nr))):
                    lp[uvl].uv = uv
        front = bm.verts.new(ring_pt(phi0 + head * 0.85 / Rr))
        for j in range(nr):
            j1 = (j + 1) % nr
            f = bm.faces.new((front, rings[0][j], rings[0][j1]))
            for lp in f.loops:
                lp[uvl].uv = (0.0, j / nr)
            f = bm.faces.new((tip, rings[-1][j1], rings[-1][j]))
            for lp in f.loops:
                lp[uvl].uv = (1.0, j / nr)
        import bmesh  # noqa: PLC0415

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        _ = Vector

    return build


# ====================================================================== 场景：寒山钟
ICE = (0.66, 0.76, 0.86)


def frost_ferns(w, h, rng, n_seeds=90, v_bias=0.35, max_len=260, step=0.7, wrap_x=True):
    """冰花（窗花一样的羽状冰晶）：从种子点长出主枝，每隔几个像素往两侧 ±60° 长侧枝，侧枝再长小枝。
    返回 (h, w) 的覆盖度 0..1（x 方向周期，可以绕钟一圈）。种子偏向图的下方（v_bias：钟口一带）。"""
    acc = np.zeros((h, w), np.float32)
    xs_all, ys_all, ws_all = [], [], []

    def grow(x, y, ang, length, width, depth):
        n = max(int(length / step), 2)
        bend = rng.normal(0, 0.004) * 0 + rng.normal(0, 0.0035)
        a = ang
        xs, ys = [x], [y]
        for i in range(n):
            a += bend + rng.normal(0, 0.012)
            x += math.cos(a) * step
            y += math.sin(a) * step
            xs.append(x)
            ys.append(y)
        xs, ys = np.array(xs), np.array(ys)
        t = np.linspace(0, 1, len(xs))
        xs_all.append(xs)
        ys_all.append(ys)
        ws_all.append(width * (1 - 0.75 * t))
        if depth <= 0:
            return
        gap = rng.uniform(6.0, 9.5) * (1.0 if depth == 2 else 0.85)
        k = int(gap / step)
        for i in range(k, len(xs) - k // 2, k):
            tt = i / len(xs)
            L = length * (0.42 if depth == 2 else 0.5) * (1 - tt) ** 0.9 * rng.uniform(0.7, 1.1)
            if L < 3:
                continue
            for sgn in (-1, 1):
                if rng.random() < 0.12:
                    continue
                grow(xs[i], ys[i], ang + sgn * math.radians(rng.normal(60, 6)), L, width * 0.62, depth - 1)

    for _ in range(n_seeds):
        x = rng.uniform(0, w)
        y = h * (1 - v_bias * rng.power(0.7)) if rng.random() < 0.8 else rng.uniform(0, h)
        ang = -math.pi / 2 + rng.normal(0, 0.55)  # 大致往上长（图像 y 向下）
        grow(x, y, ang, rng.uniform(0.35, 1.0) * max_len, rng.uniform(0.9, 1.5), 2)
    X = np.concatenate(xs_all)
    Y = np.concatenate(ys_all)
    Wt = np.concatenate(ws_all)
    ok = (Y >= 0) & (Y < h - 1)
    X, Y, Wt = X[ok], Y[ok], Wt[ok]
    x0 = np.floor(X).astype(int)
    y0 = np.floor(Y).astype(int)
    fx, fy = X - x0, Y - y0
    for dx, dy, wt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        np.add.at(acc, ((y0 + dy) % h, (x0 + dx) % w), wt * Wt)
    V = vfx()
    acc = V.fft_blur(acc.astype(np.float64), 0.75, wrap=True)
    return np.clip(acc * 0.95, 0, 1).astype(np.float32)


def np_image(name, arr, alpha=None, colorspace="Non-Color"):
    """numpy (h, w[, 3]) 0..1 → 存成 16 位 PNG 再让 Blender 读进来（行序从上到下）。
    直接往 float 图像里写像素再 pack 会丢数据（实测 bpy 5.2.2 全变成 0），所以走文件。"""
    bpy = _bpy()
    from PIL import Image  # noqa: PLC0415

    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"tex_{name}.png"
    a = np.clip(arr, 0, 1)
    if a.ndim == 2:
        Image.fromarray(np.round(a * 65535).astype(np.uint16)).save(path)
    else:
        rgb = np.round(a * 255).astype(np.uint8)
        if alpha is not None:
            rgb = np.dstack([rgb, np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8)])
        Image.fromarray(rgb).save(path)
    img = bpy.data.images.load(str(path), check_existing=False)
    img.colorspace_settings.name = colorspace
    return img


BELL_BANDS_Z = (0.105, 0.520, 0.880, 1.190)  # 横向凸带
BELL_VBANDS = tuple(math.radians(a) for a in (45, 135, 225, 315))  # 竖向凸带（前面板正对镜头 270°）


def bell_relief(W=4096, Hh=1680, rng=None):
    """钟身浮雕图（圆柱展开：x = 绕钟一圈，y = 高度 0..1.68 米，自上而下）：
    上层四块面板铸铭文（楷书竖排，阳文，鎏金），钟口一圈回纹带。返回 (高度, 鎏金遮罩)。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: PLC0415

    hm = Image.new("L", (W, Hh), 0)
    gm = Image.new("L", (W, Hh), 0)
    dh, dg = ImageDraw.Draw(hm), ImageDraw.Draw(gm)
    zpx = lambda z: int(round((1.68 - z) / 1.68 * Hh))  # noqa: E731
    text = ("夜半钟声到客船" "月落乌啼霜满天" "江枫渔火对愁眠" "姑苏城外寒山寺" "风调雨顺国泰民安" "法轮常转佛日增辉" "钟声所及众生安乐")
    f = ImageFont.truetype(str(FONT_BRUSH), 44)
    for k in range(4):
        u0 = (BELL_VBANDS[k] / (2 * math.pi)) * W + 34
        u1 = (BELL_VBANDS[(k + 1) % 4] / (2 * math.pi) + (1 if k == 3 else 0)) * W - 34
        z_top, z_bot = BELL_BANDS_Z[3] - 0.035, BELL_BANDS_Z[2] + 0.035
        y0, y1 = zpx(z_top), zpx(z_bot)
        cols = int((u1 - u0) // 54)
        idx = k * 11
        for c in range(cols):
            x = u1 - 30 - c * 54  # 竖排，从右往左
            y = y0 + 4
            while y + 44 < y1:
                ch = text[idx % len(text)]
                idx += 1
                for dr_ in (dh, dg):
                    dr_.text((x % W - 22, y), ch, font=f, fill=255)
                y += 47
        # 面板的边框（阳线）
        for dr_, wv in ((dh, 255), ):
            dr_.rectangle([u0 - 14, y0 - 14, u1 + 14, y1 + 14], outline=wv, width=5)
    # 钟口回纹带
    yb0, yb1 = zpx(0.088), zpx(0.022)
    hh = yb1 - yb0
    step = hh
    for i in range(int(W / step) + 1):
        x0 = i * step
        pts = [(x0, yb1), (x0, yb0), (x0 + step * 0.8, yb0), (x0 + step * 0.8, yb1 - hh * 0.75), (x0 + step * 0.3, yb1 - hh * 0.75),
               (x0 + step * 0.3, yb1 - hh * 0.35), (x0 + step * 0.55, yb1 - hh * 0.35)]
        dh.line(pts, fill=255, width=6, joint="curve")
    a = np.asarray(hm.filter(ImageFilter.GaussianBlur(2.2)), np.float32) / 255.0
    g = np.asarray(gm.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0
    return a, g


def mat_bronze_bell(name, relief_img, gilt_img, frost_img, frost=1.0):
    """钟的青铜（老铜器的样子）：通体一层深青绿的锈，凹处和斑块结浅色铜锈壳；凸带、浮雕顶面、棱上磨出金褐色的铜，
    带金属光；铭文鎏金；钟口一带和朝上的面结霜（冰花贴图 + 积霜）。只用一个 Principled，各层参数先混好。
    贴图用圆柱投影：u = 角度、v = 高度（物体坐标 z / 1.68）。"""
    M = Mat(name)
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    m = M.math
    ang = m("ARCTAN2", sep.outputs["Y"], sep.outputs["X"])
    u = m("WRAP", m("DIVIDE", ang, 2 * math.pi), 1.0, 0.0)
    v = m("DIVIDE", sep.outputs["Z"], 1.68)
    uvv = M.n("ShaderNodeCombineXYZ")
    M.l(u, uvv.inputs["X"])
    M.l(v, uvv.inputs["Y"])

    def tex(img):
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="REPEAT")
        t.image = img
        M.l(uvv.outputs[0], t.inputs["Vector"])
        sc = M.n("ShaderNodeSeparateColor")
        M.l(t.outputs["Color"], sc.inputs[0])
        return sc.outputs[0]

    hgt, gmask, fern = tex(relief_img), tex(gilt_img), tex(frost_img)
    n1 = M.noise(oc, scale=2.4, detail=5.0, rough=0.6)
    n2 = M.noise(oc, scale=26.0, detail=8.0, rough=0.72)
    n3 = M.noise(oc, scale=8.0, detail=6.0, rough=0.65, dist=0.4)
    geo = M.n("ShaderNodeNewGeometry")
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.04, _samples=12)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    # 锈：深青绿底 + 浅色锈壳（斑块、凹处）
    crust = m("ADD", M.maprange(n3.outputs["Fac"], 0.56, 0.74), m("MULTIPLY", cav, 1.3), clamp=True)
    crust = m("MULTIPLY", crust, M.maprange(n2.outputs["Fac"], 0.3, 0.7, 0.45, 1.1), clamp=True)
    patina = M.mix(crust, (0.008, 0.020, 0.017, 1.0), (0.055, 0.135, 0.105, 1.0))
    # 磨出的铜：凸起（尖度、浮雕高度）+ 大斑
    raised = m("MAXIMUM", M.maprange(geo.outputs["Pointiness"], 0.502, 0.53), m("MULTIPLY", hgt, 0.9))
    wear = m("ADD", m("MULTIPLY", raised, M.maprange(n2.outputs["Fac"], 0.30, 0.55)),
             m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.50, 0.70), 0.75), clamp=True)
    wear = m("MULTIPLY", wear, m("SUBTRACT", 1.0, m("MULTIPLY", cav, 1.5), clamp=True))
    bronze = M.mix(M.maprange(n2.outputs["Fac"], 0.3, 0.7), (0.20, 0.115, 0.045, 1.0), (0.34, 0.21, 0.085, 1.0))
    base = M.mix(wear, patina, bronze)
    metal = wear
    rough = M.mixf(wear, M.maprange(n2.outputs["Fac"], 0.3, 0.7, 0.55, 0.75), 0.30)
    # 鎏金铭文
    g = m("MULTIPLY", gmask, m("SUBTRACT", 1.0, m("MULTIPLY", crust, 0.45), clamp=True))
    base = M.mix(g, base, (0.88, 0.60, 0.22, 1.0))
    metal = m("MAXIMUM", metal, g)
    rough = M.mixf(g, rough, 0.24)
    # 霜：冰花（钟口一带最密）+ 朝上的面积霜
    nz = M.n("ShaderNodeSeparateXYZ")
    M.l(geo.outputs["Normal"], nz.inputs[0])
    top = m("MULTIPLY", M.maprange(nz.outputs["Z"], 0.55, 0.95), 0.75)
    low = M.maprange(sep.outputs["Z"], 0.50, 0.0)
    fr = m("ADD", m("MULTIPLY", fern, m("ADD", m("MULTIPLY", low, 0.85), 0.03)), m("MULTIPLY", top, M.maprange(n2.outputs["Fac"], 0.40, 0.62)),
           clamp=True)
    fr = m("MAXIMUM", fr, m("MULTIPLY", m("POWER", low, 4.0), M.maprange(n1.outputs["Fac"], 0.50, 0.66, 0.0, 0.6)))
    fr = m("MULTIPLY", fr, frost)
    base = M.mix(fr, base, (*ICE, 1.0))
    metal = m("MULTIPLY", metal, m("SUBTRACT", 1.0, fr, clamp=True))
    rough = M.mixf(fr, rough, 0.42)
    hb = m("ADD", m("ADD", hgt, m("MULTIPLY", fern, 0.30)), m("MULTIPLY", crust, 0.12))
    nrm = M.bump(hb, strength=0.6, distance=0.004)
    nrm = M.bump(n2.outputs["Fac"], strength=0.08, distance=0.003, normal=nrm)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(base, bsdf.inputs["Base Color"])
    M.l(metal, bsdf.inputs["Metallic"])
    M.l(rough, bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    M.l(m("MULTIPLY", fr, 0.35), bsdf.inputs["Subsurface Weight"])
    bsdf.inputs["Subsurface Radius"].default_value = (0.02, 0.03, 0.05)
    bsdf.inputs["Subsurface Scale"].default_value = 0.02
    return M.surface(bsdf.outputs[0])


def mat_ice(name, rough=0.06, tint=(0.82, 0.92, 1.0)):
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=40.0, detail=4.0)
    nrm = M.bump(nz.outputs["Fac"], strength=0.15, distance=0.002)
    bsdf = M.principled(Base_Color=(*tint, 1.0), Roughness=rough, IOR=1.31, Transmission_Weight=1.0, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_snow(name):
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=60.0, detail=6.0, rough=0.7)
    sp = M.noise(oc, scale=900.0, detail=1.0)
    nrm = M.bump(nz.outputs["Fac"], strength=0.4, distance=0.01)
    rough = M.maprange(sp.outputs["Fac"], 0.55, 0.75, 0.6, 0.2)
    bsdf = M.principled(Base_Color=(0.80, 0.86, 0.95, 1.0), Roughness=rough, Subsurface_Weight=0.6,
                        Subsurface_Radius=(0.05, 0.07, 0.10), Subsurface_Scale=0.05, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_wood(name):
    """老木梁：暗褐近黑，顺纹（沿 X 拉长的噪声）与几道干裂；夜里梁底背光，所以整体压得很暗。"""
    M = Mat(name)
    oc = M.coord("Object")
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (0.5, 22.0, 22.0)
    grain = M.noise(mp.outputs["Vector"], scale=3.0, detail=8.0, rough=0.62, dist=0.6)
    mp2 = M.n("ShaderNodeMapping")
    M.l(oc, mp2.inputs["Vector"])
    mp2.inputs["Scale"].default_value = (0.35, 9.0, 9.0)
    crack = M.noise(mp2.outputs["Vector"], scale=3.0, detail=3.0, rough=0.5)
    ck = M.maprange(crack.outputs["Fac"], 0.68, 0.71)
    col = M.mix(M.maprange(grain.outputs["Fac"], 0.3, 0.7), (0.012, 0.008, 0.006, 1.0), (0.040, 0.027, 0.017, 1.0))
    col = M.mix(ck, col, (0.003, 0.002, 0.002, 1.0))
    h = M.math("ADD", M.math("MULTIPLY", grain.outputs["Fac"], 0.4), M.math("MULTIPLY", ck, -1.0))
    nrm = M.bump(h, strength=0.4, distance=0.006)
    bsdf = M.principled(Base_Color=col, Roughness=0.75, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_iron(name):
    M = Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=40.0, detail=6.0, rough=0.7)
    col = M.mix(M.maprange(nz.outputs["Fac"], 0.4, 0.7), (0.025, 0.022, 0.022, 1.0), (0.12, 0.07, 0.04, 1.0))
    nrm = M.bump(nz.outputs["Fac"], strength=0.25, distance=0.004)
    bsdf = M.principled(Base_Color=col, Metallic=0.7, Roughness=0.62, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_coldwave(name, strength=3.0, front=0.92, kind="skirt", seed=0.0):
    """寒波：UV.y = 0（钟口）→ 1（波前）。一道亮的波前 + 后面拖着的薄霜雾，噪声打散成一缕缕；冷白偏青。
    kind="curtain"：波前上竖起来的一圈霜幕，UV.y = 0（底）→ 1（顶），往上淡出。"""
    M = Mat(name)
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    m = M.math
    uu, vv = sep.outputs["X"], sep.outputs["Y"]
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (60.0, 2.0, 1.0) if kind == "skirt" else (34.0, 2.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.62, w=seed)
    wisp = M.maprange(nz.outputs["Fac"], 0.35, 0.68, interp="SMOOTHSTEP")
    if kind == "skirt":
        frontv = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", m("SUBTRACT", vv, front), 0.022), 2.0), -1.0))
        trail = m("MULTIPLY", M.maprange(vv, 0.0, front, 0.0, 1.0), m("LESS_THAN", vv, front))
        trail = m("MULTIPLY", m("POWER", trail, 2.5), 0.22)
        mouth = m("MULTIPLY", M.maprange(vv, 0.10, 0.0), 0.10)
        a = m("ADD", m("ADD", m("MULTIPLY", frontv, 0.95), trail), mouth)
        a = m("MULTIPLY", a, m("ADD", m("MULTIPLY", wisp, 0.85), 0.25), clamp=True)
    else:
        a = m("MULTIPLY", m("POWER", m("SUBTRACT", 1.0, vv, clamp=True), 1.8), m("ADD", m("MULTIPLY", wisp, 0.9), 0.1))
        a = m("MULTIPLY", a, M.maprange(vv, 0.0, 0.08), clamp=True)
    emi = M.n("ShaderNodeEmission", Color=(0.78, 0.90, 1.0, 1.0))
    M.l(m("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def mat_wavefront(name, strength=8.0, seed=0.0, soft=1.3, gaps=0.40, color=(0.62, 0.84, 1.0)):
    """霜环：发光的半透明管，越靠管边越透（Layer Weight），沿环用拉长的噪声打成一缕缕、留几处断口。"""
    M = Mat(name)
    uv = M.coord("UV")
    m = M.math
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (40.0, 1.5, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.6, w=seed)
    mp2 = M.n("ShaderNodeMapping")
    M.l(uv, mp2.inputs["Vector"])
    mp2.inputs["Scale"].default_value = (7.0, 1.0, 1.0)
    big = M.noise(mp2.outputs["Vector"], scale=1.0, detail=2.0, w=seed + 2.0)
    lw = M.n("ShaderNodeLayerWeight", Blend=0.4)
    core = m("POWER", m("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True), soft)
    a = m("MULTIPLY", core, m("ADD", m("MULTIPLY", M.maprange(nz.outputs["Fac"], 0.35, 0.68, interp="SMOOTHSTEP"), 0.85), 0.2))
    a = m("MULTIPLY", a, M.maprange(big.outputs["Fac"], gaps - 0.12, gaps + 0.12), clamp=True)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def temple_bell(frost: bool = True):
    """山寺大青铜钟（钟口在 z=0、钟顶约 1.5 米，蒲牢钮在顶上）：横竖凸带、铭文面板、莲花撞座、钟口回纹、荷叶口。
    frost=False 时不结霜（静心）。返回钟的材质。"""
    from mathutils import Vector  # noqa: PLC0415

    # ---------------- 钟身轮廓（外壁自下而上，再沿内壁回到钟口）：口外撇、腰微收、肩圆
    def r_body(z):
        base = 0.600 - 0.085 * smoothstep(0.08, 1.20, z) - 0.012 * math.sin(math.pi * min(1.0, max(0.0, (z - 0.15) / 1.0)))
        return base

    outer = [(0.615, -0.004), (0.632, 0.010), (0.634, 0.036), (0.626, 0.070), (0.612, 0.092), (0.600, 0.104)]
    for z in np.linspace(0.12, 1.24, 70):
        r = r_body(z)
        for zc in BELL_BANDS_Z[1:]:
            r += 0.014 * math.exp(-((z - zc) / 0.012) ** 2) + 0.010 * math.exp(-((z - zc - 0.036) / 0.008) ** 2)
        r += 0.012 * math.exp(-((z - 0.125) / 0.01) ** 2)
        outer.append((r, z))
    r_sh = r_body(1.24)
    for a in np.linspace(0, 1, 26)[1:]:
        th = a * math.pi / 2
        outer.append((r_sh * math.cos(th) ** 0.85, 1.24 + 0.26 * math.sin(th) ** 1.15))
    outer[-1] = (0.0, 1.50)
    inner = [(0.0, 1.44), (0.28, 1.42), (0.42, 1.33), (0.47, 1.18), (0.50, 0.60), (0.555, 0.12), (0.575, -0.004)]

    def mouth_wave(th, z, i):
        return -0.026 * (0.5 + 0.5 * math.cos(8 * th)) * (1 - smoothstep(0.0, 0.10, z))

    def petals(th, z, i):
        k = 1.0
        if z > 1.26:  # 钟肩一圈莲瓣
            t = (z - 1.26) / 0.22
            ph = (th * 16 / (2 * math.pi)) % 1.0
            k += 0.020 * math.sin(math.pi * min(1.0, t * 1.25)) * (1 - abs(ph - 0.5) * 2) ** 0.6
        if 0.12 < z < 1.19:  # 竖向凸带
            for b in BELL_VBANDS:
                d = abs((th - b + math.pi) % (2 * math.pi) - math.pi)
                k += 0.022 * math.exp(-((d / 0.030) ** 4)) + 0.010 * math.exp(-(((d - 0.05) / 0.008) ** 2))
        if z < 0.10:  # 荷叶口：八瓣微微外翻
            k += 0.012 * (0.5 + 0.5 * math.cos(8 * th)) * (1 - z / 0.10)
        return k

    prof = outer + inner
    relief, gilt = bell_relief()
    if frost:
        fern = frost_ferns(2048, 840, np.random.default_rng(9), n_seeds=95, v_bias=0.40, max_len=210)
    else:
        fern = np.zeros((840, 2048))
    bell_m = mat_bronze_bell("Bronze", np_image("relief", relief), np_image("gilt", gilt), np_image("fern", fern),
                             frost=1.0 if frost else 0.0)
    make_obj("Bell", lathe_uv(prof, segments=360, radial=petals, zfunc=mouth_wave), bell_m, index=1)
    # 莲花撞座（前后各一）
    for th in (math.radians(270), math.radians(90)):
        r0 = 0.585
        c = Vector((r0 * math.cos(th), r0 * math.sin(th), 0.36))
        q = Vector((math.cos(th), math.sin(th), 0)).to_track_quat("Z", "Y")

        def medallion(bm):
            import bmesh  # noqa: PLC0415

            tmp = lathe_uv([(0.0, 0.034), (0.03, 0.033), (0.05, 0.028), (0.07, 0.020), (0.09, 0.012), (0.105, 0.0)], segments=96,
                           radial=lambda a, z, i: 1 + 0.10 * (abs(math.sin(a * 6)) ** 0.5 - 0.6) * (z < 0.025))
            tmp(bm)

        make_obj(f"Lotus{th:.2f}", medallion, bell_m, loc=tuple(c), rot=q.to_euler(), index=1)
    # 蒲牢（钟钮）：一道粗拱，脚下外撇接进钟顶，拱背一道脊；铁环穿过钮孔挂到梁上
    rot18 = math.radians(18)
    arch = [(0.165 * math.cos(a), 0.0, 1.455 + 0.235 * math.sin(a)) for a in np.linspace(-0.05, math.pi + 0.05, 64)]
    make_obj("Pulao", tube_uv(arch, 0.050, sides=24, radius_fn=lambda t: 1.0 + 0.45 * abs(math.cos(math.pi * t)) ** 6 +
                              0.05 * math.sin(46 * t) ** 2), bell_m, rot=(0, 0, rot18), index=1)
    for sx in (-1, 1):
        make_obj(f"PulaoFoot{sx}", lathe_uv([(0.11, 0.0), (0.095, 0.02), (0.07, 0.05), (0.055, 0.08), (0.0, 0.09)], segments=40),
                 bell_m, loc=(sx * 0.165 * math.cos(rot18), sx * 0.165 * math.sin(rot18), 1.445), index=1)
    make_obj("Pearl", lathe_uv([(0.0, 0.0), (0.05, 0.01), (0.07, 0.045), (0.05, 0.085), (0.0, 0.095)], segments=40), bell_m,
             loc=(0, 0, 1.49), index=1)
    return bell_m


def build_bell_evo(draft: bool):
    """寒山钟：覆霜木梁下挂一口山寺大青铜钟（蒲牢钮、横竖凸带、铭文面板、莲花撞座、钟口回纹），
    钟口漫出一圈白霜寒波，钟身结冰花、钟口垂冰凌，空中冰晶。月光从左后打轮廓，寒波从下面照亮钟身。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    rng = np.random.default_rng(73)
    set_world(lin("#0A1222"), 1.0)
    bell_m = temple_bell()
    rot18 = math.radians(18)  # 蒲牢钮的朝向（铁环跟着转）
    iron = mat_iron("Iron")
    beam_z = 2.13
    make_obj("Shackle", torus_build(0.125, 0.026, 64, 14), iron, loc=(0, 0, 1.765), rot=(math.radians(90), 0, rot18 + math.radians(90)),
             index=2)
    make_obj("Strap", box_build(0.10, 0.07, 0.12), iron, loc=(0, 0.0, beam_z - 0.235), index=2, bevel=(0.006, 2))
    # ---------------- 木梁（顶上积霜、下沿冰凌）
    wood = mat_wood("Wood")
    make_obj("Beam", box_build(7.0, 0.36, 0.40), wood, loc=(0, 0.0, beam_z), index=2, bevel=(0.02, 3))
    snow = mat_snow("Snow")

    def snow_cap(bm):
        nx, ny = 280, 12
        vs = []
        for i in range(nx + 1):
            x = -3.4 + 6.8 * i / nx
            row = []
            for j in range(ny + 1):
                y = -0.17 + 0.36 * j / ny
                edge = min(j, ny - j) / (ny / 2)
                hgt = 0.045 * (edge ** 0.5) * (0.75 + 0.35 * math.sin(x * 3.1 + 1.0) * math.sin(x * 7.3)) + 0.004
                row.append(bm.verts.new((x, y + 0.05, beam_z + 0.20 + hgt)))
            vs.append(row)
        for i in range(nx):
            for j in range(ny):
                bm.faces.new((vs[i][j], vs[i + 1][j], vs[i + 1][j + 1], vs[i][j + 1]))

    make_obj("SnowCap", snow_cap, snow, index=2)
    ice = mat_ice("Ice")
    pts, rad = [], []
    for k in range(60):  # 梁下沿的冰凌
        x = rng.uniform(-2.2, 2.2)
        if abs(x) < 0.28:
            continue
        L = rng.uniform(0.04, 0.24) * (1.0 if rng.random() < 0.7 else 0.4)
        y = -0.13 + rng.uniform(-0.01, 0.01)
        make_obj(f"Icicle{k}", lathe_uv([(0.0, -L), (0.004, -L * 0.85), (0.012, -L * 0.45), (0.020, -0.01), (0.024, 0.0), (0.0, 0.0)],
                                        segments=12, radial=lambda a, z, i: 1 + 0.12 * math.sin(a * 3 + z * 40)),
                 ice, loc=(x, y, beam_z - 0.20), index=3)
    for k in range(44):  # 钟口的冰凌
        th = rng.uniform(0, 2 * math.pi)
        if math.sin(th) > 0.3:  # 背面看不见
            continue
        L = rng.uniform(0.03, 0.16)
        r0 = 0.604
        make_obj(f"LipIce{k}", lathe_uv([(0.0, -L), (0.003, -L * 0.8), (0.009, -L * 0.4), (0.014, -0.004), (0.0, 0.0)], segments=10),
                 ice, loc=(r0 * math.cos(th), r0 * math.sin(th), 0.004), index=3)
    # 冰晶簇：钟口、钟钮、钟肩上
    def crystal(L, r):
        return lathe_uv([(0.0, -0.02 * L), (r, 0.0), (r, L * 0.8), (0.0, L)], segments=6)

    for k in range(70):
        where = rng.random()
        if where < 0.55:
            th = rng.uniform(math.radians(190), math.radians(350))
            p = Vector((0.61 * math.cos(th), 0.61 * math.sin(th), rng.uniform(0.0, 0.05)))
            nrm = Vector((math.cos(th), math.sin(th), rng.uniform(-0.6, 0.4))).normalized()
        else:
            th = rng.uniform(0, 2 * math.pi)
            rr = rng.uniform(0.25, 0.5)
            p = Vector((rr * math.cos(th), rr * math.sin(th), 1.5 + (0.5 - rr) * 0.2))
            nrm = Vector((math.cos(th) * 0.5, math.sin(th) * 0.5, 1.0)).normalized()
        d = (nrm + Vector(rng.normal(0, 0.35, 3))).normalized()
        L = rng.uniform(0.025, 0.07)
        ob = make_obj(f"Xtal{k}", crystal(L, L * 0.16), ice, loc=tuple(p), index=3, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = d.to_track_quat("Z", "Y")
    # ---------------- 寒波：钟口漫出、浮在半空的一圈霜环（不落地），环后拖着很淡的放射霜纹，外面一道余波
    Rw = 1.30

    def skirt(r0, r1, z0, z1, n=200, m=40):
        def build(bm):
            uvl = bm.loops.layers.uv.new("UVMap")
            grid = []
            for j in range(m + 1):
                t = j / m
                rr = r0 + (r1 - r0) * t
                zz = z0 + (z1 - z0) * (1 - (1 - t) ** 2.2)
                row = []
                for i in range(n + 1):
                    a = 2 * math.pi * i / n
                    w = 1 + 0.035 * math.sin(a * 5 + 1.0) * t + 0.02 * math.sin(a * 11) * t
                    row.append(bm.verts.new((rr * w * math.cos(a), rr * w * math.sin(a), zz + 0.03 * math.sin(a * 7) * t)))
                grid.append(row)
            for j in range(m):
                for i in range(n):
                    f = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
                    for lp, uv in zip(f.loops, ((i / n, j / m), ((i + 1) / n, j / m), ((i + 1) / n, (j + 1) / m), (i / n, (j + 1) / m))):
                        lp[uvl].uv = uv
        return build

    def wave_ring(R, r, zc, n=260, k=16):
        """霜环：扁一点的圆管，UV.x 绕环一圈 0..1，UV.y 绕管 0..1。"""
        def build(bm):
            uvl = bm.loops.layers.uv.new("UVMap")
            grid = []
            for i in range(n + 1):
                a = 2 * math.pi * i / n
                Rr_ = R * (1 + 0.03 * math.sin(a * 5 + 1.0) + 0.018 * math.sin(a * 11))
                zz = zc + 0.025 * math.sin(a * 7)
                row = []
                for j in range(k + 1):
                    b_ = 2 * math.pi * j / k
                    rr = Rr_ + r * math.cos(b_) * 1.25
                    row.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), zz + r * 0.7 * math.sin(b_))))
                grid.append(row)
            for i in range(n):
                for j in range(k):
                    f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                    for lp, uv in zip(f.loops, ((i / n, j / k), ((i + 1) / n, j / k), ((i + 1) / n, (j + 1) / k), (i / n, (j + 1) / k))):
                        lp[uvl].uv = uv
        return build

    make_obj("WaveRing", wave_ring(Rw, 0.032, -0.02), mat_wavefront("WaveFront", strength=3.2, seed=1.0, soft=1.6, gaps=0.52), index=5)
    make_obj("WaveRing2", wave_ring(Rw * 0.96, 0.20, 0.02), mat_wavefront("WaveHaze", strength=0.32, seed=4.0, soft=3.2, gaps=0.40), index=5)
    make_obj("WaveEcho", wave_ring(Rw * 1.34, 0.032, -0.05), mat_wavefront("WaveEchoM", strength=2.4, seed=7.0, gaps=0.58), index=5)
    make_obj("WaveSkirt", skirt(0.64, Rw * 0.985, -0.01, -0.03), mat_coldwave("WaveM", strength=2.2, front=0.999, seed=1.0), index=5)
    for k in range(130):
        a = rng.uniform(0, 2 * math.pi)
        rr = Rw * rng.uniform(0.70, 1.20)
        p = Vector((rr * math.cos(a), rr * math.sin(a), rng.uniform(-0.12, 0.35) * rng.random()))
        d = Vector(rng.normal(0, 1, 3)).normalized()
        L = rng.uniform(0.015, 0.045)
        ob = make_obj(f"Flake{k}", crystal(L, L * 0.2), ice, loc=tuple(p), index=3, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = d.to_track_quat("Z", "Y")
    # ---------------- 灯光与相机
    area_light("Moon", (-3.0, 3.2, 3.2), (0, 0, 0.9), 1150.0, 1.6, color=(0.70, 0.80, 1.0))
    area_light("MoonFill", (3.2, 2.6, 1.6), (0, 0, 0.7), 200.0, 1.4, color=(0.55, 0.70, 1.0))
    area_light("Front", (-1.8, -4.0, 2.4), (0, 0, 0.8), 18.0, 3.0, color=(0.62, 0.72, 1.0))
    area_light("Warm", (3.0, -2.8, 0.9), (0, 0, 0.8), 60.0, 1.2, color=(1.0, 0.70, 0.45))
    area_light("WaveGlow", (0, -1.2, -0.30), (0, 0, 0.4), 90.0, 2.4, size_y=0.3, color=(0.70, 0.88, 1.0))
    camera((0.55, -5.0, 0.45), (0.0, 0.0, 0.80), lens=45.0, fstop=4.0, focus=4.45)
    return {"light": "cold"}


# ====================================================================== 场景：疾行
FOOT_T = np.array([0.0, 0.03, 0.10, 0.25, 0.45, 0.62, 0.75, 0.86, 0.94, 0.985, 1.0])
FOOT_HW = np.array([0.004, 0.019, 0.028, 0.031, 0.033, 0.041, 0.045, 0.044, 0.037, 0.022, 0.006])
FOOT_ZB_T = np.array([0.0, 0.04, 0.10, 0.80, 0.95, 1.0])
FOOT_ZB = np.array([-0.060, -0.072, -0.075, -0.075, -0.072, -0.067])
FOOT_ZT_T = np.array([0.0, 0.05, 0.15, 0.30, 0.45, 0.60, 0.75, 0.88, 0.96, 1.0])
FOOT_ZT = np.array([-0.052, -0.022, 0.012, 0.014, -0.004, -0.024, -0.039, -0.047, -0.055, -0.063])
FOOT_X0, FOOT_LEN = -0.070, 0.262
BALL_X, SOLE_Z = 0.118, -0.075
SANDAL_T = 0.014  # 草鞋底厚


def foot_sec(t):
    """脚（布袜）在 t（0 脚跟 → 1 脚尖）处的截面：(x, 半宽, 底 z, 顶 z)。脚的局部坐标：原点在踝，x 朝前，z 朝上。"""
    return (FOOT_X0 + FOOT_LEN * t, float(np.interp(t, FOOT_T, FOOT_HW)), float(np.interp(t, FOOT_ZB_T, FOOT_ZB)),
            float(np.interp(t, FOOT_ZT_T, FOOT_ZT)))


def foot_pt(t, phi, off=0.0):
    """脚面上的点：phi = 0 外侧（+y）、90° 脚背、180° 内侧、270° 脚底。off 沿近似法线外推。"""
    x, hw, zb, zt = foot_sec(t)
    zc, hh = (zb + zt) / 2, (zt - zb) / 2
    c, s_ = math.cos(phi), math.sin(phi)
    p_ = 2.2 if s_ >= 0 else 3.6
    y = (hw + off) * math.copysign(abs(c) ** (2 / p_), c)
    z = zc + (hh + off) * math.copysign(abs(s_) ** (2 / p_), s_)
    return (x, y, z)


def make_bend(alpha_deg):
    """蹬地：前掌（BALL_X 以前）贴地不动，后面的脚绕前掌横轴抬起 alpha 度。返回 f(p) → p'。"""
    a = math.radians(alpha_deg)

    def f(p):
        x, y, z = p
        w = smoothstep(BALL_X + 0.012, BALL_X - 0.03, x)
        ang = -a * w
        dx, dz = x - BALL_X, z - (SOLE_Z - SANDAL_T)
        return (BALL_X + dx * math.cos(ang) - dz * math.sin(ang), y, (SOLE_Z - SANDAL_T) + dx * math.sin(ang) + dz * math.cos(ang))

    return f


def foot_build(bend, n_len=40, n_rad=28):
    def build(bm):
        import bmesh  # noqa: PLC0415

        rings = []
        for i in range(n_len + 1):
            t = i / n_len
            ring = [bm.verts.new(bend(foot_pt(t, 2 * math.pi * k / n_rad))) for k in range(n_rad)]
            rings.append(ring)
        for a_, b_ in zip(rings, rings[1:]):
            for k in range(n_rad):
                bm.faces.new((a_[k], a_[(k + 1) % n_rad], b_[(k + 1) % n_rad], b_[k]))
        for ring, rev in ((rings[0], True), (rings[-1], False)):
            c = bm.verts.new(sum((v.co for v in ring), ring[0].co * 0) / len(ring))
            for k in range(n_rad):
                bm.faces.new((c, ring[(k + 1) % n_rad], ring[k]) if rev else (c, ring[k], ring[(k + 1) % n_rad]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def sole_build(bend, n_len=48, n_w=10):
    """草鞋底：沿脚长的圆角厚板，比脚大一圈，脚尖略翘。顶点属性 along（米）、across（-1..1）、side（0 顶 1 侧 2 底）。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        la = bm.verts.layers.float.new("along")
        lc = bm.verts.layers.float.new("across")
        lsd = bm.verts.layers.float.new("side")
        rings = []
        for i in range(n_len + 1):
            t = i / n_len
            x = FOOT_X0 - 0.010 + (FOOT_LEN + 0.022) * t
            hw = float(np.interp(t, FOOT_T, FOOT_HW)) + 0.009
            hw = max(hw, 0.012) if 0.02 < t < 0.98 else hw * 0.7 + 0.004
            lift = 0.010 * smoothstep(0.86, 1.0, t)
            zt, zb = SOLE_Z + lift, SOLE_Z - SANDAL_T + lift * 1.3
            sec = []
            for j in range(n_w + 1):  # 顶面从外侧到内侧
                sv = -1 + 2 * j / n_w
                sec.append(((x, sv * hw * (1 - 0.06 * sv * sv), zt + 0.0015 * (1 - sv * sv)), sv, 0.0))
            for sv in (1.0, ):
                sec.append(((x, hw * 1.02, (zt + zb) / 2), sv, 1.0))
            for j in range(n_w + 1):  # 底面从内侧回到外侧
                sv = 1 - 2 * j / n_w
                sec.append(((x, sv * hw * (1 - 0.06 * sv * sv), zb), sv, 2.0))
            sec.append(((x, -hw * 1.02, (zt + zb) / 2), -1.0, 1.0))
            ring = []
            for co, sv, sd in sec:
                v = bm.verts.new(bend(co))
                v[la] = x - FOOT_X0
                v[lc] = sv
                v[lsd] = sd
                ring.append(v)
            rings.append(ring)
        n = len(rings[0])
        for a_, b_ in zip(rings, rings[1:]):
            for k in range(n):
                bm.faces.new((a_[k], b_[k], b_[(k + 1) % n], a_[(k + 1) % n]))
        for ring, rev in ((rings[0], False), (rings[-1], True)):
            c = bm.verts.new(sum((v.co for v in ring), ring[0].co * 0) / n)
            c[la] = ring[0][la]
            c[lsd] = 1.0
            for k in range(n):
                bm.faces.new((c, ring[(k + 1) % n], ring[k]) if rev else (c, ring[k], ring[(k + 1) % n]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def mat_straw(name):
    """草鞋：稻草编的底（横向密密的纬、四道纵向的经绳槽），草色有深浅，槽里发暗。用顶点属性 along / across 定纹路。"""
    M = Mat(name)
    m = M.math
    at_a = M.n("ShaderNodeAttribute", _attribute_name="along", _attribute_type="GEOMETRY").outputs["Fac"]
    at_c = M.n("ShaderNodeAttribute", _attribute_name="across", _attribute_type="GEOMETRY").outputs["Fac"]
    oc = M.coord("Object")
    jit = M.noise(oc, scale=60.0, detail=3.0)
    ph = m("ADD", m("MULTIPLY", at_a, 1.0 / 0.0042), m("MULTIPLY", jit.outputs["Fac"], 1.2))
    weft = m("MULTIPLY", m("ADD", m("SINE", m("MULTIPLY", ph, 2 * math.pi)), 1.0), 0.5)  # 0..1
    # 纬草是斜着压的：按 across 正负分两半，形成人字
    ph2 = m("ADD", ph, m("MULTIPLY", m("ABSOLUTE", at_c), 3.0))
    weft2 = m("MULTIPLY", m("ADD", m("SINE", m("MULTIPLY", ph2, 2 * math.pi)), 1.0), 0.5)
    warp = m("ABSOLUTE", m("SINE", m("MULTIPLY", at_c, math.pi * 2.0)))  # 四道经槽
    groove = M.maprange(warp, 0.0, 0.18, 1.0, 0.0)
    h = m("SUBTRACT", m("MAXIMUM", weft, m("MULTIPLY", weft2, 0.8)), m("MULTIPLY", groove, 0.8))
    fib = M.noise(oc, scale=300.0, detail=4.0)
    col, _ = M.ramp(M.noise(oc, scale=18.0, detail=4.0).outputs["Fac"],
                    [(0.3, (0.28, 0.19, 0.075)), (0.55, (0.46, 0.33, 0.14)), (0.75, (0.56, 0.44, 0.22))])
    col = M.mix(m("MULTIPLY", m("SUBTRACT", 1.0, h), 0.65, clamp=True), col, (0.10, 0.065, 0.03, 1.0))
    col = M.mix(m("MULTIPLY", fib.outputs["Fac"], 0.25), col, (0.75, 0.62, 0.36, 1.0))
    hb = m("ADD", h, m("MULTIPLY", fib.outputs["Fac"], 0.25))
    nrm = M.bump(hb, strength=0.9, distance=0.0012)
    bsdf = M.principled(Base_Color=col, Roughness=0.62, Sheen_Weight=0.3, Sheen_Roughness=0.4, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_rope(name, color=(0.42, 0.31, 0.13)):
    """草绳：两股绞成，UV.x = 弧长（米），UV.y = 绕一圈。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    ph = m("ADD", m("MULTIPLY", sep.outputs["X"], 1.0 / 0.0055), m("MULTIPLY", sep.outputs["Y"], 2.0))
    tw = m("ABSOLUTE", m("SINE", m("MULTIPLY", ph, math.pi)))
    oc = M.coord("Object")
    fib = M.noise(oc, scale=400.0, detail=3.0)
    col = M.mix(m("MULTIPLY", m("SUBTRACT", 1.0, tw), 0.8), (*color, 1.0), (color[0] * 0.3, color[1] * 0.3, color[2] * 0.3, 1.0))
    nrm = M.bump(m("ADD", tw, m("MULTIPLY", fib.outputs["Fac"], 0.3)), strength=0.7, distance=0.0012)
    bsdf = M.principled(Base_Color=col, Roughness=0.7, Sheen_Weight=0.4, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_cloth(name, color, weave=380.0, rough=0.82, edge=None, uv_edge=False, dirt=0.0):
    """布：细密的经纬（UV 或物体坐标上的两组细条纹）+ 绒光（sheen）。edge 给出时，布条边缘（UV.y 两端）换一个颜色。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    w1 = M.n("ShaderNodeTexWave", _wave_type="BANDS", _bands_direction="X", Scale=weave, Distortion=0.4)
    w2 = M.n("ShaderNodeTexWave", _wave_type="BANDS", _bands_direction="Y", Scale=weave, Distortion=0.4)
    M.l(oc, w1.inputs["Vector"])
    M.l(oc, w2.inputs["Vector"])
    hw = m("MULTIPLY", w1.outputs["Fac"], w2.outputs["Fac"])
    nz = M.noise(oc, scale=30.0, detail=5.0)
    col = M.mix(M.maprange(nz.outputs["Fac"], 0.3, 0.7), (color[0] * 0.75, color[1] * 0.75, color[2] * 0.75, 1.0), (*color, 1.0))
    if edge is not None:
        uv = M.coord("UV")
        sep = M.n("ShaderNodeSeparateXYZ")
        M.l(uv, sep.inputs[0])
        e = m("ADD", M.maprange(sep.outputs["Y"], 0.14, 0.0), M.maprange(sep.outputs["Y"], 0.86, 1.0), clamp=True)
        col = M.mix(e, col, (*edge, 1.0))
    if dirt:
        low = M.maprange(M.n("ShaderNodeSeparateXYZ").outputs["Z"], 0.0, 1.0)
        _ = low
    nrm = M.bump(m("ADD", hw, m("MULTIPLY", nz.outputs["Fac"], 0.4)), strength=0.55, distance=0.0008)
    bsdf = M.principled(Base_Color=col, Roughness=rough, Sheen_Weight=0.6, Sheen_Roughness=0.5, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_leaf(name, wind=False):
    """竹叶：叶脉是沿叶长的细平行纹，颜色从叶柄到叶尖、按每片叶子的随机数在青绿、黄绿、枯黄之间变；背光透一点绿。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    info = M.n("ShaderNodeObjectInfo")
    rnd = info.outputs["Random"]
    veins = m("ABSOLUTE", m("SINE", m("MULTIPLY", sep.outputs["Y"], math.pi * 9.0)))
    mid = M.maprange(m("ABSOLUTE", m("SUBTRACT", sep.outputs["Y"], 0.5)), 0.0, 0.05, 1.0, 0.0)
    fresh = M.mix(sep.outputs["X"], (0.050, 0.130, 0.040, 1.0), (0.095, 0.180, 0.055, 1.0))
    dry = M.mix(sep.outputs["X"], (0.200, 0.160, 0.055, 1.0), (0.300, 0.220, 0.080, 1.0))
    dead = (0.12, 0.075, 0.035, 1.0)
    col = M.mix(M.maprange(rnd, 0.55, 0.80), fresh, dry)
    col = M.mix(M.maprange(rnd, 0.86, 0.95), col, dead)
    if wind:
        col = M.mix(0.0, col, col)
    oc = M.coord("Object")
    spot = M.noise(oc, scale=90.0, detail=3.0)
    col = M.mix(m("MULTIPLY", M.maprange(spot.outputs["Fac"], 0.6, 0.75), 0.5), col, (0.06, 0.05, 0.02, 1.0))
    nrm = M.bump(m("ADD", m("MULTIPLY", veins, 0.4), mid), strength=0.25, distance=0.0006)
    bsdf = M.principled(Base_Color=col, Roughness=0.62, Specular_IOR_Level=0.22, Normal=nrm)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(M.mix(0.4, col, (0.20, 0.45, 0.10, 1.0)), trn.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.22
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def leaf_build(L, W, fold=0.25, curl=0.15, twist=0.0, n=16, side_n=3):
    """一片竹叶（沿 +X，叶柄在原点）：披针形，最宽在 30% 处，叶尖收尖；沿中脉折一点（V 形），整片沿长弯一点。
    UV：x = 0（叶柄）→ 1（叶尖），y = 0..1 横跨。"""
    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for i in range(n + 1):
            t = i / n
            if t < 0.3:
                w = W * math.sin(t / 0.3 * math.pi / 2) ** 0.8
            else:
                w = W * (1 - ((t - 0.3) / 0.7) ** 1.6) ** 0.9
            w = max(w, 0.0004)
            ang = twist * t
            row = []
            for j in range(2 * side_n + 1):
                sv = -1 + j / side_n
                y = sv * w / 2
                z = abs(sv) * w * fold + curl * L * t * t
                yy = y * math.cos(ang) - z * math.sin(ang)
                zz = y * math.sin(ang) + z * math.cos(ang)
                row.append(bm.verts.new((L * t, yy, zz)))
            grid.append(row)
        for i in range(n):
            for j in range(2 * side_n):
                f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                for lp, uv in zip(f.loops, ((i / n, j / (2 * side_n)), ((i + 1) / n, j / (2 * side_n)),
                                           ((i + 1) / n, (j + 1) / (2 * side_n)), (i / n, (j + 1) / (2 * side_n)))):
                    lp[uvl].uv = uv

    return build


def mat_wind(name, strength=2.6, seed=0.0, color=(0.72, 0.95, 0.84)):
    """风：一道半透明的光带，UV.x 沿长 0..1、UV.y 横跨 0..1。两头淡出，横向边缘柔，沿长拉出一道道细丝（像一笔扫出的风）。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 0.9)
    ends = m("MULTIPLY", M.maprange(u, 0.0, 0.25), M.maprange(u, 1.0, 0.55))
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (1.6, 46.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=7.0, rough=0.7, w=seed)
    streak = M.maprange(nz.outputs["Fac"], 0.44, 0.62, interp="SMOOTHSTEP")
    mp3 = M.n("ShaderNodeMapping")
    M.l(uv, mp3.inputs["Vector"])
    mp3.inputs["Scale"].default_value = (5.0, 3.0, 1.0)
    big = M.noise(mp3.outputs["Vector"], scale=1.0, detail=2.0, w=seed + 5.0)
    streak = m("MULTIPLY", streak, M.maprange(big.outputs["Fac"], 0.35, 0.6))
    edge = m("MULTIPLY", M.maprange(v, 0.05, 0.25), M.maprange(v, 0.95, 0.75))
    a = m("MULTIPLY", m("MULTIPLY", across, ends), m("ADD", m("MULTIPLY", streak, 0.9), m("MULTIPLY", edge, 0.0)))
    a = m("MULTIPLY", a, m("ADD", 0.25, m("MULTIPLY", M.maprange(u, 0.2, 0.7), 0.75)), clamp=True)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def shin_wrap_build(A, K, rfun, s0=0.07, s1=0.84, pitch=0.040, width=0.050, gap_off=0.0030, n_per_turn=40, phase=0.0, seed=0):
    """绑腿：一条布带从踝上往膝下螺旋缠，每一圈压住上一圈的上沿（瓦片一样：带子下沿离腿远、上沿离腿近）。
    UV：x = 沿带长（米），y = 0（下沿）→ 1（上沿）。"""
    from mathutils import Vector  # noqa: PLC0415

    A, K = Vector(A), Vector(K)
    d = (K - A)
    Lg = d.length
    d.normalize()
    a = Vector((0, 1, 0)) if abs(d.y) < 0.9 else Vector((1, 0, 0))
    e1 = d.cross(a).normalized()
    e2 = d.cross(e1).normalized()
    turns = (s1 - s0) * Lg / pitch
    n = int(turns * n_per_turn)

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        rows = []
        lens = [0.0]
        prev = None
        rr_ = np.random.default_rng(seed)
        wob = vfx().fft_blur(rr_.standard_normal((1, n + 1)), (6.0, 0.0))[0]
        wob = wob / (np.abs(wob).max() + 1e-9)
        for i in range(n + 1):
            t = i / n
            s = s0 + (s1 - s0) * t + 0.006 * wob[i] / Lg
            th = 2 * math.pi * turns * t + phase
            er = e1 * math.cos(th) + e2 * math.sin(th)
            row = []
            # 带子是斜着缠的：跟着角度一侧高一侧低（倾斜），宽度略有起伏
            tilt = 0.30 * math.cos(th + 0.6)
            wd = width * (1 + 0.12 * wob[i])
            for j, sv in enumerate((-0.5, -0.25, 0.0, 0.25, 0.5)):
                ss = s + (sv * wd + tilt * sv * 0.02) / Lg
                r = rfun(min(max(ss, 0.0), 1.0)) + gap_off + (-sv) * 0.0014 + 0.0008 * abs(wob[i]) * (sv > 0.3)
                row.append(bm.verts.new(A + d * (ss * Lg) + er * r))
            c = A + d * (s * Lg) + er * rfun(s)
            if prev is not None:
                lens.append(lens[-1] + (c - prev).length)
            prev = c
            rows.append(row)
        for i in range(n):
            for j in range(4):
                f = bm.faces.new((rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1]))
                for lp, uv in zip(f.loops, ((lens[i], j / 4), (lens[i + 1], j / 4), (lens[i + 1], (j + 1) / 4), (lens[i], (j + 1) / 4))):
                    lp[uvl].uv = uv

    return build, (A, d, e1, e2, Lg)


def build_jixing(draft: bool):
    """疾行：低机位侧面看一双绑腿草鞋正迈步——后脚蹬地（脚跟抬起、露出草鞋底的编纹），前脚脚跟落地踩在竹叶上；
    地上铺满落下的竹叶；一道青白的风从后脚卷起，绕过脚踝往前上方旋，带着几片竹叶（运动模糊）。
    月光从左后打轮廓，前方右上一盏灯笼的暖光照在草鞋上。"""
    bpy = _bpy()
    from mathutils import Euler, Matrix, Vector  # noqa: PLC0415

    rng = np.random.default_rng(17)
    set_world(lin("#0B1118"), 1.0)
    sc = bpy.context.scene
    sock_m = mat_cloth("Sock", (0.40, 0.37, 0.31), weave=520.0)
    straw = mat_straw("Straw")
    rope = mat_rope("Rope")
    wrap_m = mat_cloth("Wrap", (0.030, 0.042, 0.066), weave=420.0, edge=(0.075, 0.085, 0.105))
    pants = mat_cloth("Pants", (0.075, 0.078, 0.085), weave=300.0)
    tie = mat_rope("Tie", (0.18, 0.05, 0.03))

    def place(fn, M4):
        return lambda p: tuple(M4 @ Vector(fn(p)))

    legs = []
    for side, (alpha, beta, X, Y, yaw, knee_off) in {
        "rear": (40.0, 0.0, -0.25, -0.065, -6.0, (0.25, 0.0, 0.37)),
        "front": (0.0, 13.0, 0.14, 0.075, 4.0, (0.015, 0.0, 0.44)),
    }.items():
        bend = make_bend(alpha)
        if beta:  # 前脚：绕脚跟着地点把脚尖抬起来
            hx, hz = FOOT_X0 + 0.004, SOLE_Z - SANDAL_T
            b = math.radians(beta)

            def bend(p, b=b, hx=hx, hz=hz):  # noqa: E306
                dx, dz = p[0] - hx, p[2] - hz
                return (hx + dx * math.cos(b) - dz * math.sin(b), p[1], hz + dx * math.sin(b) + dz * math.cos(b))
            contact = Vector((hx, 0.0, hz))
        else:
            contact = Vector((BALL_X, 0.0, SOLE_Z - SANDAL_T))
        R = Matrix.Rotation(math.radians(yaw), 4, "Z")
        T = Matrix.Translation(Vector((X, Y, 0.0)) - (R @ contact))
        M4 = T @ R
        fpt = place(bend, M4)
        make_obj(f"Foot_{side}", foot_build(fpt), sock_m, subsurf=1, index=1)
        make_obj(f"Sole_{side}", sole_build(fpt), straw, subsurf=1, index=1)
        # ---- 草绳：前绳、两侧绳、后绳绕踝打结、脚跟绳；鞋耳
        def cord(pts, r=0.0034, name="c"):
            make_obj(f"{name}_{side}", tube_uv([fpt(q) for q in pts], r, sides=8), rope, index=1)

        def surf(t, ph, off=0.0036):
            return foot_pt(t, math.radians(ph), off)

        tip = (FOOT_X0 + FOOT_LEN + 0.004, 0.0, SOLE_Z + 0.002)
        knot = surf(0.50, 90, 0.005)
        cord([tip, surf(0.96, 90), surf(0.86, 90), surf(0.72, 90), surf(0.58, 90), knot], name="CordToe")
        for sgn, ph in ((1, 0), (-1, 180)):
            ear = (FOOT_X0 + FOOT_LEN * 0.64, sgn * (float(np.interp(0.64, FOOT_T, FOOT_HW)) + 0.006), SOLE_Z + 0.003)
            cord([ear, surf(0.62, ph + sgn * 25), surf(0.58, ph + sgn * 55), surf(0.53, 90 - sgn * 20), knot], name=f"CordSide{sgn}")
            ear2 = (FOOT_X0 + FOOT_LEN * 0.20, sgn * (float(np.interp(0.20, FOOT_T, FOOT_HW)) + 0.006), SOLE_Z + 0.003)
            make_obj(f"Ear{sgn}a_{side}", torus_build(0.008, 0.0024, 24, 8), rope, index=1,
                     loc=fpt(ear), rot=(math.radians(90), 0, 0))
            make_obj(f"Ear{sgn}b_{side}", torus_build(0.008, 0.0024, 24, 8), rope, index=1,
                     loc=fpt(ear2), rot=(math.radians(90), 0, 0))
            # 后绳：从后鞋耳上来，绕踝一圈半，在踝前打结
            pts = [ear2, surf(0.22, ph + sgn * 40, 0.004), (0.0, sgn * 0.038, -0.03)]
            for k in range(14):
                a = math.radians(-90 * sgn) + sgn * k / 13 * math.pi * 1.25
                pts.append((0.036 * math.cos(a) * 1.05, 0.036 * math.sin(a), 0.020 + 0.010 * k / 13 + 0.004 * sgn))
            pts.append((0.040, 0.004 * sgn, 0.032))
            cord(pts, r=0.0031, name=f"CordAnkle{sgn}")
        make_obj(f"Knot_{side}", ico_cloud([fpt((0.040, 0.0, 0.032))], [0.0075], 2), rope, index=1)
        for sgn in (1, -1):
            cord([(0.041, 0.003 * sgn, 0.030), (0.050, 0.010 * sgn, 0.012), (0.056, 0.016 * sgn, -0.010), (0.058, 0.022 * sgn, -0.026)],
                 r=0.0026, name=f"CordEnd{sgn}")
        cord([(FOOT_X0 + 0.02, 0.034, SOLE_Z + 0.004), surf(0.04, 60, 0.004), surf(0.0, 90, 0.005), surf(0.04, 120, 0.004),
              (FOOT_X0 + 0.02, -0.034, SOLE_Z + 0.004)], r=0.003, name="CordHeel")
        # ---- 小腿与绑腿
        Aw = Vector(fpt((0.0, 0.0, 0.0)))
        Kw = Aw + (R @ Vector(knee_off).to_4d()).to_3d()
        prof = lambda s: float(np.interp(s, [0.0, 0.10, 0.30, 0.55, 0.80, 1.0], [0.030, 0.033, 0.043, 0.050, 0.045, 0.043]))  # noqa: E731
        shin_pts = [Aw + (Kw - Aw) * (i / 30) for i in range(31)]
        make_obj(f"Shin_{side}", tube_uv(shin_pts, 1.0, sides=24, radius_fn=prof), sock_m, index=1)
        wb, _ = shin_wrap_build(Aw, Kw, prof, s0=0.10, s1=0.86, phase=rng.uniform(0, 6.28), seed=int(rng.integers(1000)))
        make_obj(f"Wrap_{side}", wb, wrap_m, index=1)
        top = Aw + (Kw - Aw) * 0.865
        make_obj(f"WrapTie_{side}", tube_uv([top + (Kw - Aw).normalized().orthogonal().normalized() * 0 + Vector(
            (math.cos(a) * (prof(0.865) + 0.007), math.sin(a) * (prof(0.865) + 0.007), 0)) for a in np.linspace(0, 2 * math.pi, 40)],
            0.0025, sides=8), tie, index=1)
        pant_pts = [Aw + (Kw - Aw) * s for s in np.linspace(0.84, 1.25, 20)]
        make_obj(f"Pants_{side}", tube_uv(pant_pts, 1.0, sides=28, radius_fn=lambda t: 0.050 + 0.030 * math.sin(min(1.0, t * 1.6) * math.pi / 2)
                                          + 0.002 * math.sin(t * 30)), pants, index=1)
        legs.append((Aw, Kw))
    # ---------------- 地面与落叶
    leaf_m = mat_leaf("Leaf")
    ground = Mat("Ground")
    gn = ground.noise(ground.coord("Object"), scale=8.0, detail=6.0)
    gc = ground.mix(gn.outputs["Fac"], (0.004, 0.0036, 0.003, 1.0), (0.014, 0.012, 0.009, 1.0))
    gb = ground.principled(Base_Color=gc, Roughness=1.0, Specular_IOR_Level=0.1,
                           Normal=ground.bump(gn.outputs["Fac"], strength=0.3, distance=0.01))
    make_obj("Ground", lambda bm: __import__("bmesh").ops.create_grid(bm, x_segments=2, y_segments=2, size=3.0), ground.surface(gb.outputs[0]),
             loc=(0, 0.6, -0.001), index=0)
    n_leaf = 120 if draft else 240
    for k in range(n_leaf):
        x = rng.uniform(-0.85, 0.75)
        y = rng.uniform(-0.45, 1.1)
        if rng.random() < 0.35:  # 脚边多一些
            x, y = rng.normal(0.0, 0.25), rng.normal(0.0, 0.15)
        L = rng.uniform(0.085, 0.15)
        W = L * rng.uniform(0.13, 0.17)
        yaw = rng.uniform(0, 2 * math.pi)
        z = 0.0015 + 0.0025 * rng.random()
        make_obj(f"GLeaf{k}", leaf_build(L, W, fold=rng.uniform(0.1, 0.3), curl=rng.uniform(0.02, 0.18), twist=rng.normal(0, 0.3)),
                 leaf_m, loc=(x, y, z), rot=(rng.normal(0, 0.05), rng.normal(0, 0.05), yaw), index=2)
    # 前脚踩着的两片
    for k, (dx, dy, yaw) in enumerate(((0.06, 0.07, 0.4), (0.20, 0.10, -0.3))):
        make_obj(f"StepLeaf{k}", leaf_build(0.14, 0.021, fold=0.05, curl=0.0), leaf_m, loc=(0.17 + dx - 0.05, dy, 0.0008),
                 rot=(0, 0, yaw), index=2)
    # ---------------- 风：从后脚跟后面贴地卷起，绕过两只脚踝，往前上方旋开
    # 主风：从后脚跟后面贴地吹来，从后脚踝前面（靠镜头一侧）扬起，往前上方斜着卷出画面，竹叶跟着飞；
    # 副风：前脚跟边上贴地一旋；一道贴地的细风丝
    wind_paths = [
        [(-0.88, 0.04, 0.018), (-0.60, -0.03, 0.022), (-0.40, -0.10, 0.032), (-0.24, -0.14, 0.055), (-0.10, -0.15, 0.090),
         (0.02, -0.13, 0.135), (0.12, -0.10, 0.175), (0.22, -0.08, 0.205), (0.34, -0.07, 0.225)],
        [(-0.05, 0.16, 0.010), (0.10, 0.13, 0.014), (0.23, 0.06, 0.024), (0.27, -0.05, 0.040), (0.20, -0.11, 0.058),
         (0.10, -0.12, 0.070), (0.02, -0.10, 0.090)],
        [(-0.95, 0.26, 0.008), (-0.60, 0.19, 0.010), (-0.25, 0.13, 0.013), (0.10, 0.08, 0.018), (0.45, 0.03, 0.026)],
    ]
    for k, ctrl in enumerate(wind_paths):
        c = np.asarray(ctrl, np.float64)
        pts = catmull(c, 220)
        w = (0.110, 0.055, 0.030)[k]
        ups = []
        P, T, N, Bn = frames_along([tuple(q) for q in pts])
        for i in range(len(P)):
            up = Vector((0, 0, 1))
            side = T[i].cross(up)
            if side.length < 1e-6:
                side = Bn[i]
            ups.append(tuple(side.cross(T[i]).normalized() * 0.6 + up * 0.4))
        make_obj(f"Wind{k}", ribbon_uv([tuple(q) for q in pts], w, ups=ups, width_fn=lambda t: 0.35 + 0.65 * math.sin(math.pi * t) ** 0.7,
                                       segs_w=6, curl=lambda t, s: -0.25 * s * s),
                 mat_wind(f"WindM{k}", strength=(1.5, 1.2, 0.9)[k], seed=k * 2.3), index=5)
        # 风里带着的竹叶（运动模糊）
        nfly = (10, 4, 2)[k]
        for j in range(nfly):
            t = 0.18 + 0.75 * (j + rng.uniform(-0.3, 0.3)) / nfly
            i0 = int(t * (len(pts) - 1))
            i1 = min(i0 + 6, len(pts) - 1)
            p0 = Vector(pts[i0]) + Vector(rng.normal(0, 0.012, 3))
            p1 = Vector(pts[i1]) + Vector(rng.normal(0, 0.012, 3))
            L = rng.uniform(0.07, 0.12)
            ob = make_obj(f"FlyLeaf{k}_{j}", leaf_build(L, L * 0.15, fold=0.2, curl=rng.uniform(-0.2, 0.3), twist=rng.normal(0, 0.8)),
                          leaf_m, loc=tuple(p0), rot=tuple(rng.uniform(0, 6.28, 3)), index=3)
            ob.keyframe_insert("location", frame=1)
            ob.keyframe_insert("rotation_euler", frame=1)
            ob.location = tuple(p1)
            ob.rotation_euler = tuple(Vector(ob.rotation_euler) + Vector(rng.normal(0, 0.6, 3)))
            ob.keyframe_insert("location", frame=3)
            ob.keyframe_insert("rotation_euler", frame=3)
    sc.frame_set(2)
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.32
    # ---------------- 灯光与相机
    area_light("Moon", (-1.2, 1.5, 1.2), (0, 0, 0.15), 210.0, 0.8, color=(0.62, 0.74, 1.0))
    area_light("MoonFill", (-1.4, -0.8, 0.9), (0, 0, 0.1), 12.0, 1.2, color=(0.55, 0.66, 0.95))
    point_light("Lantern", (0.70, -0.50, 0.45), 32.0, radius=0.05, color=(1.0, 0.66, 0.36))
    camera((0.24, -1.22, 0.25), (-0.035, 0.02, 0.105), lens=50.0, fstop=3.5, focus=1.20)
    return {"light": "jade"}


def catmull(ctrl, n=80):
    c = np.asarray(ctrl, dtype=np.float64)
    c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
    out = []
    for i in range(1, len(c) - 2):
        p0, p1, p2, p3 = c[i - 1], c[i], c[i + 1], c[i + 2]
        t = np.linspace(0, 1, 24, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(c[-2][None])
    pts = np.vstack(out)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    sl = np.concatenate([[0.0], np.cumsum(seg)])
    u = np.linspace(0.0, sl[-1], n)
    return np.stack([np.interp(u, sl, pts[:, k]) for k in range(3)], -1)


# ====================================================================== 后期（只用 numpy / Pillow）
def srgb_to_lin(x):
    x = np.clip(x, 0, None)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def aces(x):
    """胶片曲线（ACES 拟合）：线性光 → 0..1。高光自然发白、暗部有一点趾部。"""
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def aces_inv(y):
    """aces 的反函数：把画好的水墨底（显示值）换回线性光，合成后再过曲线时原样还原。"""
    y = np.clip(y, 0, 0.98)
    a, b, c = 2.43 * y - 2.51, 0.59 * y - 0.03, 0.14 * y
    disc = np.sqrt(np.maximum(b * b - 4 * a * c, 0))
    return np.maximum((-b - disc) / (2 * a), 0)


def _blur(a, sigma, angle=0.0):
    return vfx().fft_blur(a, sigma, angle=angle)


def _noise(rng, shape, sigma, angle=0.0):
    return vfx().noise(rng, shape, sigma, angle)


def _fbm(rng, shape, sigmas, weights):
    return vfx().fbm(rng, shape, sigmas, weights)


def _ss(e0, e1, x):
    return vfx().smoothstep(e0, e1, x)


def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


class Ink:
    """一张夜色水墨底（显示值 sRGB 0..1）。glaze 罩染（相乘，越叠越深），over 覆盖，light 提亮（屏幕叠加）。"""

    def __init__(self, h, w, rng):
        self.h, self.w, self.rng = h, w, rng
        self.Y, self.X = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
        self.rgb = np.zeros((h, w, 3))

    def fill_grad(self, top, bottom, cloud=0.05):
        t = (self.Y / self.h)[..., None]
        base = hexc(top) * (1 - t) + hexc(bottom) * t
        c = _fbm(self.rng, (self.h, self.w), (220.0, 90.0, 30.0), (0.5, 0.35, 0.15))[..., None]
        self.rgb = base * (1 + cloud * c)

    def glaze(self, a, color):
        a = np.clip(a, 0, 1)[..., None]
        self.rgb = self.rgb * (1 - a) + self.rgb * hexc(color) * a / max(hexc(color).max(), 1e-6) * 0 + \
            self.rgb * (1 - a * (1 - hexc(color)))  # 乘一个颜色（白 = 不变）
        self.rgb = self.rgb / 2

    def darken(self, a, k=0.5):
        """墨：按 a 往暗里压（k = 最多压掉多少）。"""
        self.rgb = self.rgb * (1 - k * np.clip(a, 0, 1)[..., None])

    def over(self, a, color):
        a = np.clip(a, 0, 1)[..., None]
        self.rgb = self.rgb * (1 - a) + (hexc(color) if isinstance(color, str) else np.asarray(color)) * a

    def light(self, a, color):
        a = np.clip(a, 0, 1)[..., None]
        c = hexc(color) if isinstance(color, str) else np.asarray(color)
        self.rgb = 1 - (1 - self.rgb) * (1 - c * a)

    def blob(self, cx, cy, rx, ry, *, ang=0.0, rough=0.35, rim=0.3, soft=0.25):
        """一团水墨晕染的覆盖度（不规则椭圆，边上一圈水痕略深）。返回 (h, w) 0..1。"""
        dx, dy = self.X - cx, self.Y - cy
        ca, sa = math.cos(ang), math.sin(ang)
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        n = _noise(self.rng, (self.h, self.w), max(rx, ry) * 0.16)
        d = np.hypot(u, v) * (1 + rough * 0.35 * n)
        body = _ss(1.0, 1.0 - soft, d)
        ring = np.exp(-((d - (1.0 - soft * 0.4)) / 0.05) ** 2) * rim
        tex = 0.85 + 0.15 * _noise(self.rng, (self.h, self.w), 5.0)
        return np.clip(body * tex + ring * body, 0, 1)

    def dry_stroke(self, pts, halfw, *, dry=0.6, dry_start=0.35):
        """一笔干笔（飞白）的覆盖度。pts 是中线（像素）。"""
        V = vfx()
        pts = np.asarray(pts, np.float64)
        hwv = np.broadcast_to(np.asarray(halfw, np.float64), (len(pts),)).copy()
        cov, _ = V.brush_stroke(self.X, self.Y, pts, hwv, self.rng, dry=dry, dry_start=dry_start, edge_jitter=0.2)
        return cov


def ridge(xs, base, peaks, rng, rough=6.0):
    """山脊线 y(x)：peaks = [(中心, 高, 左半宽, 右半宽)]。"""
    y = np.full(xs.shape, float(base))
    for cx, hgt, wl, wr in peaks:
        t = np.where(xs < cx, (cx - xs) / wl, (xs - cx) / wr)
        y = np.minimum(y, base - hgt * np.clip(1 - t, 0, 1) ** 1.6)
    n = _blur(rng.standard_normal((1, xs.size)), (12.0, 0))[0]
    n2 = _blur(rng.standard_normal((1, xs.size)), (3.0, 0))[0]
    return y + rough * (n / (n.std() + 1e-9)) + 0.35 * rough * (n2 / (n2.std() + 1e-9))


def bg_mountains(P, layers, rng, k):
    """几层远山：layers = [(底边 0..1, [(中心, 高, 左半宽, 右半宽) 均按 0..1], 颜色, 浓度, 往下淡出, 山脊毛糙)]，
    自远而近。山脊处墨浓、往下淡进雾里；每层山脚一道薄雾。"""
    h, w = P.h, P.w
    xs = np.arange(w) + 0.5
    for base, peaks, col, a, fade, rough, *mist in layers:
        ry_ = ridge(xs, base * h, [(c * w, hh * h, l * w, r * w) for c, hh, l, r in peaks], rng, rough=rough * k)
        depth = P.Y - ry_[None, :] + 1.2 * _noise(rng, (h, w), 1.0 * k)
        inside = _ss(-1.2 * k, 1.2 * k, depth)
        top = np.exp(-np.maximum(depth, 0) / (6.0 * k))
        body = 0.45 + 0.55 * np.exp(-np.maximum(depth, 0) / (fade * h))
        tex = 1 + 0.18 * _noise(rng, (h, w), (18 * k, 4 * k), angle=math.pi / 2 + 0.35) + 0.12 * _noise(rng, (h, w), 40 * k)
        P.over(np.clip(a * inside * (body * tex + 0.25 * top), 0, 1), col)
        mcol = mist[0] if mist else "#6E8CAA"
        mist_y = (base + 0.035) * h
        P.light(np.exp(-((P.Y - mist_y) / (0.03 * h)) ** 2) * (0.6 + 0.4 * _noise(rng, (h, w), (70 * k, 6 * k))) * 0.10, mcol)


def bg_mist(P, y, half, color, a, rng, k, sx=90.0):
    """一道横雾：中心 y、半高 half（都按 0..1），沿横向拉长的噪声打散。"""
    h, w = P.h, P.w
    P.light(np.exp(-((P.Y - y * h) / (half * h)) ** 2) * (0.5 + 0.5 * _noise(rng, (h, w), (sx * k, 8 * k))) * a, color)


def bg_glow(P, cx, cy, rx, ry, color, a, soft=0.9, rough=0.45):
    """一团光晕（光照在夜雾上），边缘按水渍打散。"""
    P.light(P.blob(cx * P.w, cy * P.h, rx * P.w, ry * P.h, rough=rough, rim=0.15, soft=soft) * a, color)


def bg_ink(P, spots, k_dark=0.5):
    """几团湿墨压暗：spots = [(cx, cy, rx, ry, 角度)]（按 0..1）。"""
    for cx, cy, rx, ry, ang in spots:
        P.darken(P.blob(cx * P.w, cy * P.h, rx * P.w, ry * P.h, ang=ang, rough=0.6, rim=0.5, soft=0.5), k_dark)


def bg_moon(P, cx, cy, r, rng, k, color="#E8EEF6", halo="#7E95B4", a=0.9, halo_a=0.35):
    """月亮：边缘柔和的圆，边上略暗（临边昏暗），月面几块很淡的大斑；外面两层月晕。"""
    h, w = P.h, P.w
    d = np.hypot(P.X - cx * w, P.Y - cy * h) / (r * w)
    disc = _ss(1.0, 0.985 - 0.6 * k / (r * w), d)
    limb = 1 - 0.18 * np.clip(d, 0, 1) ** 3
    blobs = _blur(rng.standard_normal((h, w)), 0.22 * r * w)
    blobs = blobs / (blobs.std() + 1e-9)
    mare = 0.10 * _ss(0.3, 1.2, blobs)
    P.light(np.exp(-np.maximum(d - 1, 0) ** 2 / 0.5) * (1 - disc) * halo_a, halo)
    P.light(np.exp(-np.maximum(d - 1, 0) ** 2 / 6.0) * (1 - disc) * halo_a * 0.45, halo)
    P.over(disc * a, np.clip(hexc(color) * (limb * (1 - mare))[..., None], 0, 1))


def bg_river(P, y0, y1, rng, k, color="#2A3C55", glint="#9FB6D6", a=0.8, glint_x=0.5, glint_a=0.35):
    """江面：y0..y1 一带横向的水（越近越暗），水面上一道月光碎影（横向短笔触），远岸一道淡雾。"""
    h, w = P.h, P.w
    t = np.clip((P.Y - y0 * h) / ((y1 - y0) * h), 0, 1)
    band = _ss(y0 * h - 1.5 * k, y0 * h + 1.5 * k, P.Y)
    tex = 1 + 0.10 * _noise(rng, (h, w), (60 * k, 2.0 * k))
    P.over(band * a * (0.65 + 0.35 * t) * tex, color)
    ripple = _ss(0.35, 0.9, _noise(rng, (h, w), (14 * k, 1.1 * k)))
    col = np.exp(-((P.X - glint_x * w) / ((0.04 + 0.10 * t) * w)) ** 2)
    P.light(band * ripple * col * glint_a * (1 - 0.6 * t), glint)
    P.light(np.exp(-((P.Y - y0 * h) / (0.012 * h)) ** 2) * 0.18 * (0.6 + 0.4 * _noise(rng, (h, w), (80 * k, 4 * k))), glint)


def bg_roofs(P, y, rng, k, color="#0D1119", a=0.92, n=7, x0=0.0, x1=1.0, height=0.10, lit="#C9822E", lit_a=0.0):
    """远处一排屋顶剪影（歇山顶：正脊、往两头下凹的坡、檐口两端翘起），lit_a>0 时窗里点几盏暖灯。"""
    h, w = P.h, P.w
    m = np.zeros((h, w))
    xs = np.sort(rng.uniform(x0, x1, n))
    for cx in xs:
        hw_ = rng.uniform(0.05, 0.085) * w
        hh = rng.uniform(0.65, 1.0) * height * h
        base = y * h + rng.uniform(-0.01, 0.02) * h
        u = np.abs(P.X - cx * w) / hw_
        y_top = base - hh + hh * 0.75 * np.clip((u - 0.45) / 0.70, 0, None) ** 1.4
        y_eave = base - 0.22 * hh - 0.38 * hh * np.clip((u - 0.78) / 0.37, 0, None) ** 2
        roof = (u < 1.15) & (P.Y > y_top) & (P.Y < y_eave)
        ridge = (u < 0.62) & (np.abs(P.Y - (base - hh)) < 0.06 * hh)
        wall = (u < 0.80) & (P.Y >= base - 0.25 * hh)
        m = np.maximum(m, (roof | ridge | wall).astype(float))
        if lit_a > 0:
            for _ in range(rng.integers(1, 3)):
                wx = cx * w + rng.uniform(-0.5, 0.5) * hw_
                wy = base + rng.uniform(0.1, 0.4) * hh
                P.light(np.exp(-(((P.X - wx) / (5 * k)) ** 2 + ((P.Y - wy) / (4 * k)) ** 2)) * lit_a, lit)
    m = _blur(m, 0.8 * k)
    P.over(m * a, color)


def paint_bg(cid, h, w, rng):
    """各张插画的水墨底（显示值）。光晕位置与 3D 里的光源大致对上。"""
    P = Ink(h, w, rng)
    k = w / 960.0
    if SCENES.get(cid, {}).get("bg"):
        SCENES[cid]["bg"](P, h, w, rng, k)
    elif cid == "lamp":
        P.fill_grad("#10141E", "#0B0E15", cloud=0.10)
        # 灯光照在夜雾上：一大团暖晕，边缘按水渍打散
        P.light(P.blob(0.50 * w, 0.46 * h, 0.40 * w, 0.42 * h, rough=0.5, rim=0.25, soft=0.85) * 0.30, "#7A3E14")
        P.light(P.blob(0.50 * w, 0.47 * h, 0.22 * w, 0.26 * h, rough=0.4, rim=0.15, soft=0.9) * 0.28, "#B8661E")
        # 四角压墨：几团湿墨 + 两笔干笔
        for cx, cy, rx, ry, ang in ((0.06, 0.10, 0.30, 0.20, 0.2), (0.96, 0.92, 0.34, 0.22, -0.3), (0.95, 0.06, 0.22, 0.16, 0.5),
                                    (0.04, 0.95, 0.25, 0.18, -0.2)):
            P.darken(P.blob(cx * w, cy * h, rx * w, ry * h, ang=ang, rough=0.6, rim=0.5, soft=0.5), 0.55)
        for y0, x0, x1, hw_ in ((0.88, -0.05, 0.42, 22), (0.12, 0.62, 1.05, 18)):
            pts = np.stack([np.linspace(x0 * w, x1 * w, 60), y0 * h + 10 * k * np.sin(np.linspace(0, 2.5, 60))], -1)
            P.darken(P.dry_stroke(pts, hw_ * k, dry=0.55), 0.5)
    elif cid == "bell_evo":
        P.fill_grad("#0E1626", "#152035", cloud=0.12)
        # 钟后一大团冷光（月光照着寒雾）
        P.light(P.blob(0.50 * w, 0.48 * h, 0.46 * w, 0.40 * h, rough=0.45, rim=0.2, soft=0.9) * 0.34, "#5C7898")
        P.light(P.blob(0.52 * w, 0.42 * h, 0.24 * w, 0.24 * h, rough=0.4, rim=0.1, soft=0.95) * 0.22, "#9DB6D2")
        # 寒山：三层远山，一层比一层近、一层比一层重；山脊处墨浓、往下淡进雾里，山脊线毛而不齐
        xs = np.arange(w) + 0.5
        layers = (
            (0.70, [(0.10, 0.17, 0.12, 0.10), (0.24, 0.24, 0.10, 0.14), (0.47, 0.13, 0.14, 0.12), (0.80, 0.26, 0.14, 0.12),
                    (0.95, 0.18, 0.10, 0.12)], "#2F425A", 0.62, 0.11, 7.0),
            (0.77, [(0.02, 0.15, 0.10, 0.14), (0.30, 0.12, 0.16, 0.12), (0.62, 0.17, 0.12, 0.16), (0.88, 0.12, 0.12, 0.10)],
             "#1F2D44", 0.78, 0.09, 6.0),
            (0.86, [(0.18, 0.10, 0.20, 0.16), (0.55, 0.07, 0.18, 0.18), (0.97, 0.13, 0.20, 0.10)], "#121B2C", 0.90, 0.08, 5.0),
        )
        for base, peaks, col, a, fade, rough in layers:
            ry_ = ridge(xs, base * h, [(c * w, hh * h, l * w, r * w) for c, hh, l, r in peaks], rng, rough=rough * k)
            depth = P.Y - ry_[None, :] + 1.2 * _noise(rng, (h, w), 1.0 * k)
            inside = _ss(-1.2 * k, 1.2 * k, depth)
            top = np.exp(-np.maximum(depth, 0) / (6.0 * k))
            body = 0.45 + 0.55 * np.exp(-np.maximum(depth, 0) / (fade * h))
            tex = 1 + 0.18 * _noise(rng, (h, w), (18 * k, 4 * k), angle=math.pi / 2 + 0.35) + 0.12 * _noise(rng, (h, w), 40 * k)
            P.over(np.clip(a * inside * (body * tex + 0.25 * top), 0, 1), col)
            # 山脚的雾
            mist_y = (base + 0.035) * h
            P.light(np.exp(-((P.Y - mist_y) / (0.03 * h)) ** 2) * (0.6 + 0.4 * _noise(rng, (h, w), (70 * k, 6 * k))) * 0.10, "#6E8CAA")
        # 地平线上的一道寒雾
        P.light(np.exp(-((P.Y - 0.80 * h) / (0.05 * h)) ** 2) * (0.5 + 0.5 * _noise(rng, (h, w), (90 * k, 8 * k))) * 0.20, "#8FB0D0")
        for cx, cy, rx, ry, ang in ((0.02, 0.08, 0.24, 0.18, 0.2), (0.98, 0.10, 0.22, 0.18, -0.4)):
            P.darken(P.blob(cx * w, cy * h, rx * w, ry * h, ang=ang, rough=0.6, rim=0.5, soft=0.5), 0.45)
    else:  # jixing
        P.fill_grad("#0E1416", "#0A0F10", cloud=0.10)
        P.light(P.blob(0.46 * w, 0.52 * h, 0.42 * w, 0.30 * h, rough=0.5, rim=0.2, soft=0.9) * 0.22, "#3E6A5A")
        # 竹林：几竿远竹（淡、糊）和近竹（浓），竹节一道白
        for x0, wd, tone, blur_, lean in ((0.08, 13, 0.30, 2.5, -0.02), (0.20, 9, 0.18, 3.5, 0.015), (0.31, 16, 0.42, 1.8, 0.01),
                                          (0.62, 11, 0.22, 3.0, -0.012), (0.73, 18, 0.48, 1.5, 0.02), (0.88, 10, 0.20, 3.5, -0.01),
                                          (0.96, 14, 0.36, 2.0, 0.0)):
            xc = x0 * w + lean * (P.Y - h)
            d = np.abs(P.X - xc) - wd * k
            stalk = _ss(1.5, -1.5, d) * _ss(0.80 * h, 0.55 * h, P.Y)
            stalk = _blur(stalk, blur_ * k)
            nodes = np.zeros((h, w))
            for yy in np.arange(rng.uniform(0, 70) * k, h, rng.uniform(95, 140) * k):
                nodes += np.exp(-((P.Y - yy) / (1.6 * k)) ** 2)
            P.light(stalk * (1 - 0.7 * np.clip(nodes, 0, 1)) * tone * 0.55, "#4E6E62")
            P.light(stalk * np.clip(nodes, 0, 1) * 0.12, "#8FB0A2")
        P.light(np.exp(-((P.Y - 0.46 * h) / (0.06 * h)) ** 2) * (0.6 + 0.4 * _noise(rng, (h, w), (80 * k, 6 * k))) * 0.12, "#7FA898")
        for cx, cy, rx, ry, ang in ((0.0, 0.05, 0.26, 0.18, 0.2), (1.0, 0.04, 0.24, 0.18, -0.4), (0.98, 0.98, 0.3, 0.2, 0.3)):
            P.darken(P.blob(cx * w, cy * h, rx * w, ry * h, ang=ang, rough=0.6, rim=0.5, soft=0.5), 0.45)
    # 墨的颗粒与纸纤维（很淡）
    P.rgb *= (1 + 0.035 * _noise(rng, (h, w), 0.8))[..., None]
    return np.clip(P.rgb, 0, 1)


def brush_alpha(h, w, rng, strokes=()):
    """插画的边：水墨晕开的边。圆角矩形内全不透明，往外按云状噪声不规则地淡出（像一大片淡墨洇到边上自己停住），
    淡出带里有纸面吸墨的颗粒；边上一圈积墨的水痕（rim，返回给颜色压暗用）。strokes = [(控制点, 半宽, 干度)]：
    几笔干笔从画里拖出去（坐标按 0..1）。返回 (alpha, rim)。"""
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    k = w / 960.0
    ix, iy, fx, fy = 0.050 * w, 0.055 * h, 0.12 * w, 0.13 * h
    dx = np.maximum(np.maximum(ix + fx - X, X - (w - ix - fx)), 0) / fx
    dy = np.maximum(np.maximum(iy + fy - Y, Y - (h - iy - fy)), 0) / fy
    d = np.hypot(dx, dy)
    n1 = _noise(rng, (h, w), 62.0 * k)
    n2 = _noise(rng, (h, w), 16.0 * k)
    n3 = _noise(rng, (h, w), 4.0 * k)
    e = d + 0.30 * n1 + 0.10 * n2 + 0.035 * n3
    a = _ss(1.08, 0.38, e)
    gr = _noise(rng, (h, w), 1.1 * k)
    mid = np.clip(a * (1 - a) * 4, 0, 1)
    a = np.clip(a * (1 - 0.22 * mid * np.clip(gr, 0, None)), 0, 1)
    rim = np.exp(-((e - 0.70) / 0.075) ** 2) * np.clip(0.55 + 0.45 * n2, 0, 1)
    V = vfx()
    for ctrl, hw_, dry in strokes:
        pts = V.bezier([(cx * w, cy * h) for cx, cy in ctrl], 120)
        hwv = hw_ * h * np.interp(np.linspace(0, 1, len(pts)), [0, 0.15, 0.7, 1.0], [0.75, 1.0, 0.9, 0.55])
        cov, _ = V.brush_stroke(X, Y, pts, hwv, rng, dry=dry, dry_start=0.30, edge_jitter=0.18)
        a = np.maximum(a, cov * 0.92)
    border = _ss(0, 3, np.minimum(np.minimum(X, w - X), np.minimum(Y, h - Y)))
    return np.clip(a * border, 0, 1), rim * a


STROKES = {  # 每张插画从画里拖出去的两笔干笔（避开主体）
    "lamp": [([(0.30, 0.86), (0.18, 0.90), (0.07, 0.93), (-0.02, 0.97)], 0.040, 0.62),
             ([(0.70, 0.12), (0.82, 0.08), (0.92, 0.06), (1.02, 0.03)], 0.034, 0.66)],
    "bell_evo": [([(0.28, 0.90), (0.16, 0.93), (0.06, 0.95), (-0.02, 0.98)], 0.036, 0.62),
                 ([(0.74, 0.10), (0.86, 0.08), (0.94, 0.06), (1.02, 0.04)], 0.030, 0.66)],
    "jixing": [([(0.66, 0.88), (0.80, 0.91), (0.92, 0.94), (1.02, 0.97)], 0.038, 0.62),
               ([(0.30, 0.10), (0.18, 0.08), (0.08, 0.06), (-0.02, 0.04)], 0.030, 0.66)],
}


GRADE = {
    # 曝光、暗部染色、亮部染色、饱和度、泛光强度
    "lamp": dict(exposure=0.95, shadow="#1A2236", high="#FFE2B0", sat=1.02, bloom=0.32, contrast=1.04),
    "bell_evo": dict(exposure=1.05, shadow="#16243C", high="#E4F0FF", sat=0.95, bloom=0.30, contrast=1.06),
    "jixing": dict(exposure=1.15, shadow="#142224", high="#E8F4E4", sat=1.0, bloom=0.30, contrast=1.05),
}


def finish(cid: str, draft: bool = False, out_dir: Path | None = None) -> Path:
    """读渲染缓存 → 水墨底 → 线性光合成 + 泛光 → 胶片曲线 → 调色、纸纹 → 笔触边 alpha → 缩到 480×360。"""
    from PIL import Image  # noqa: PLC0415

    t0 = time.perf_counter()
    tag = cid + ("_draft" if draft else "")
    d = np.load(TMP / f"{tag}.npz")
    rgba = d["rgba"].astype(np.float64)
    depth = d["depth"].astype(np.float64)
    h, w = rgba.shape[:2]
    sc = SCENES[cid]
    seed = sc["seed"] if sc["seed"] is not None else zlib.crc32(cid.encode()) % 100000
    rng = np.random.default_rng(seed)
    g = {**DEFAULT_GRADE, **sc["grade"]}
    bg = paint_bg(cid, h, w, rng)
    a = np.clip(rgba[..., 3], 0, 1)
    obj = rgba[..., :3]
    if sc["fog"]:  # 远处的地面隐进雾里（用深度；只对物体编号 0 的地面）
        d0, d1 = sc["fog"]
        fog = _ss(d0, d1, depth) * (a > 0.01) * (np.abs(d["index"].astype(np.float64)) < 0.5)
        bgl = aces_inv(srgb_to_lin(bg)) / g["exposure"]
        obj = obj * (1 - fog[..., None]) + bgl * a[..., None] * fog[..., None]
    # 泛光：亮处（多为自发光）按几档半径模糊后加回去
    lum = obj @ np.array([0.2126, 0.7152, 0.0722])
    bright = obj * _ss(0.6, 2.5, lum)[..., None]
    bloom = np.zeros_like(obj)
    for sg, wt in ((3.0, 0.30), (10.0, 0.30), (28.0, 0.25), (70.0, 0.15)):
        sgk = sg * w / 960
        bloom += wt * np.stack([_blur(bright[..., c], sgk) for c in range(3)], -1)
    lin_bg = aces_inv(srgb_to_lin(bg)) / g["exposure"]
    comp = obj + lin_bg * (1 - a[..., None]) + bloom * g["bloom"]
    disp = lin_to_srgb(aces(comp * g["exposure"]))
    # 调色：暗部偏靛（或偏青）、亮部偏暖（或偏冷）；轻微对比与饱和
    L = disp @ np.array([0.299, 0.587, 0.114])
    sh, hi = hexc(g["shadow"]), hexc(g["high"])
    tint = sh * (1 - L[..., None]) ** 2 * 0.18 + 0 * hi
    disp = disp * (1 - 0.18 * (1 - L[..., None]) ** 2) + tint
    disp = disp * (1 - 0.12 * L[..., None] ** 2) + disp * hi * 0.12 * L[..., None] ** 2
    m = disp.mean(-1, keepdims=True)
    disp = m + (disp - m) * g["sat"]
    disp = 0.5 + (disp - 0.5) * g["contrast"]
    # 绢纹：极细的经纬 + 一点纤维，正片叠底
    yy, xx = np.mgrid[0:h, 0:w]
    weave = 0.5 + 0.25 * np.sin(xx * math.pi * 0.92) * np.sin(yy * math.pi * 0.92 + 0.6)
    fib = _blur(rng.standard_normal((h, w)), (6.0, 0.6), angle=0.05)
    fib = fib / (fib.std() + 1e-9)
    tex = 1 + 0.018 * (weave - 0.5) + 0.012 * fib
    disp = np.clip(disp * tex[..., None], 0, 1)
    # 满幅：界面按圆角 6 裁切，不在图里烘淡出边。四角略压暗（左上压五行印、右上压品阶签，压暗了更清楚），
    # 边上一圈很淡的积墨，像整幅画的边。
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    for cx in (0.0, w):
        dd = np.hypot((X - cx) / (0.30 * w), Y / (0.36 * h))
        disp = disp * (1 - 0.30 * np.exp(-dd ** 2))[..., None]
    edge = np.minimum(np.minimum(X, w - X), np.minimum(Y, h - Y))
    disp = disp * (1 - 0.18 * np.exp(-edge / (0.035 * w)))[..., None]
    alpha = np.ones((h, w))
    # 缩到 480×360：预乘后用 Lanczos
    pm = np.dstack([disp * alpha[..., None], alpha]).astype(np.float32)
    outs = [np.asarray(Image.fromarray(pm[..., c], "F").resize((OW, OH), Image.LANCZOS)) for c in range(3)]
    rgb2 = np.clip(np.stack(outs, -1), 0, 1)
    img = Image.fromarray(np.dstack([np.round(rgb2 * 255), np.full((OH, OW), 255.0)]).astype(np.uint8), "RGBA")
    out_dir = out_dir or (TMP if draft else REVIEW)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (f"card_art_{cid}.png" if not draft else f"draft_card_art_{cid}.png")
    img.save(path, optimize=True)
    if not draft:  # 交付：ui_cards/card_<id>.png（打进 cards 页，帧名 ui/card_<id>）
        UI_CARDS.mkdir(parents=True, exist_ok=True)
        img.save(UI_CARDS / f"card_{cid}.png", optimize=True)
        write_meta()
    # 960×720 的全尺寸也存一张（只给审图看细节，不交付）
    Image.fromarray(np.round(np.clip(disp, 0, 1) * 255).astype(np.uint8)).save(TMP / f"{tag}_full.png")
    print(f"[{tag}] 后期 {time.perf_counter() - t0:.1f}s → {path}")
    return path


# ====================================================================== 入口
GLYPH = True  # 灯笼上写一个“明”字
scene("lamp", name="灯火", samples=160, seed=101, grade=GRADE["lamp"])(build_lamp)
scene("bell_evo", name="寒山钟", samples=160, seed=202, grade=GRADE["bell_evo"])(build_bell_evo)
scene("jixing", name="疾行", samples=200, seed=303, grade=GRADE["jixing"], fog=(1.5, 2.4))(build_jixing)
SCENE_MODULES = ("card_weapons", "card_passives")


def load_scenes():
    """导入其余场景模块（它们 import card_art 注册场景；直接运行本文件时让它们拿到同一个模块）。"""
    import importlib  # noqa: PLC0415

    sys.modules.setdefault("card_art", sys.modules[__name__])
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    for m in SCENE_MODULES:
        if (Path(here) / f"{m}.py").exists():
            importlib.import_module(m)


def write_meta():
    """ui_cards/meta.json：按目录里现有的 card_*.png 重写（pack_atlas 读）。"""
    import json  # noqa: PLC0415

    files = {}
    for p in sorted(UI_CARDS.glob("card_*.png")):
        cid = p.stem[5:]
        files[p.name] = {"size": [OW, OH], "anchor": [0.5, 0.5], "blend": "normal", "tint": False, "kind": "card_art",
                         "id": cid, "name": SCENES.get(cid, {}).get("name", "")}
    meta = {"name": "ui", "generator": "art/render/card_art.py",
            "format": "PNG RGBA（不透明、满幅），480×360；界面铺满 268×201 的插画区、按圆角 6 裁切，左上压五行印、右上压品阶签",
            "px_per_unit": 4, "display_px_1x": [268, 201], "files": files}
    (UI_CARDS / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def render_one(cid: str, draft: bool, samples: int | None):
    t0 = time.perf_counter()
    reset_scene(samples or (48 if draft else SCENES[cid]["samples"]), draft)
    params = SCENES[cid]["build"](draft)
    t1 = time.perf_counter()
    info = render_to_cache(cid, draft)
    info["build_s"] = round(t1 - t0, 2)
    info.update(params or {})
    return info


def main(argv=None) -> int:
    load_scenes()
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help=f"插画 id（默认全部）：{' '.join(SCENES)}")
    ap.add_argument("--draft", action="store_true", help="半分辨率、少采样")
    ap.add_argument("--post", action="store_true", help="只做后期（读缓存）")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--no-post", action="store_true", help="只渲染")
    a = ap.parse_args(argv)
    for cid in a.ids or list(SCENES):
        if cid not in SCENES:
            raise SystemExit(f"没有这张插画：{cid}")
        if not a.post:
            render_one(cid, a.draft, a.samples)
        if not a.no_post:
            finish(cid, draft=a.draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
