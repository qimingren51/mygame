"""提灯夜行 · 美术管线冒烟测试（水墨风精灵，无头 Blender / bpy）

验证本机（无 GPU、无 EGL/OSMesa）上哪条无头渲染路径可用，并测时间：
  - Workbench / EEVEE（需要 GPU 上下文，预计失败；在子进程里跑，避免拖垮主脚本）
  - Cycles CPU：自发光“假卡通”填色 + Freestyle 墨线 + 法线图 + 8 方向小图
  - 后处理预览：缩小到 128px 的像素预览、放大图、夜景合成（需要 Pillow）

运行方式（二选一）：
  art/.venv/bin/python art/render/smoke_test.py            # pip 安装的 bpy 模块
  blender -b --factory-startup -P art/render/smoke_test.py  # 官方 Blender 可执行文件
输出全部写到 art/out/smoke/，结果汇总在 art/out/smoke/report.json。
"""

import json
import math
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

_t_import = time.perf_counter()
import bpy  # noqa: E402  （在 blender -P 下 bpy 已加载，耗时≈0）
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402
IMPORT_BPY_S = time.perf_counter() - _t_import

try:  # Blender 自带的 Python 里没有 Pillow；缺失时跳过拼图/预览，只记录警告
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

ART = Path(__file__).resolve().parents[1]
OUT = ART / "out" / "smoke"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 参数
RES = 512            # 主渲染分辨率
DIR_RES = 256        # 8 方向快速渲染分辨率
SAMPLES = 16
DIR_SAMPLES = 4
LIGHT_DIR = Vector((-0.45, -0.55, 0.70)).normalized()  # 固定“光照”方向（世界空间，左上前方）

# 纸墨色调（sRGB hex）
PAPER_LIT, PAPER_MID, PAPER_SHADOW = "#EDE4CF", "#B4B2AA", "#7C7D82"
VERMILION, VERMILION_SHADOW = "#C9392F", "#7E231E"
INK = "#141414"
PAPER_BG = "#F2EBDA"
NIGHT_AMBIENT = "#161B2C"
LANTERN_WARM = "#FFB45E"

report = {"warnings": [], "timings_s": {}, "cpu_cores_used": {}}


def warn(msg):
    print("[WARN]", msg)
    report["warnings"].append(msg)


def _cpu():
    t = os.times()
    return t.user + t.system


class Timer:
    """with Timer("名字"): ...  墙钟耗时写进 report["timings_s"]，
    进程 CPU 时间 / 墙钟 写进 report["cpu_cores_used"]（≈1 说明单线程，≈4 说明吃满 4 核）。"""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        self.t0, self.c0 = time.perf_counter(), _cpu()
        return self

    def __exit__(self, *exc):
        self.dt = time.perf_counter() - self.t0
        report["timings_s"][self.key] = round(self.dt, 3)
        report["cpu_cores_used"][self.key] = round((_cpu() - self.c0) / max(self.dt, 1e-6), 2)
        print(f"[TIME] {self.key}: {self.dt:.2f}s")
        return False


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hex_rgb_255(h, a=255):
    return tuple(int(c * 255 + 0.5) for c in hex_rgb(h)) + (a,)


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h, a=1.0):
    """hex → Blender 线性 RGBA（材质里填的是线性值）"""
    return tuple(srgb_to_linear(c) for c in hex_rgb(h)) + (a,)


def is_blender_binary():
    """bpy 模块模式下 binary_path 为空；官方 Blender 可执行文件模式下非空。"""
    return bool(bpy.app.binary_path)


# ================================================================ a. 引擎探测
def list_engines():
    names = ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "CYCLES"]
    for cls in bpy.types.RenderEngine.__subclasses__():
        idn = getattr(cls, "bl_idname", None)
        if idn and idn not in names:
            names.append(idn)
    ok = []
    sc = bpy.context.scene
    old = sc.render.engine
    for n in names:
        try:
            sc.render.engine = n
            ok.append(n)
        except Exception:
            pass
    sc.render.engine = old
    return ok


# ================================================================ b. 会让进程 abort 的探测放进子进程
# 无 GPU 时 Blender 初始化 GPU 上下文会 SIGABRT（无法用 try/except 捕获），所以每项单独起子进程。
#   BLENDER_WORKBENCH / BLENDER_EEVEE：最小场景 64x64
#   COMP_FREESTYLE：Freestyle 开 + 合成器（Render Layers.Freestyle → 输出），即“合成器取线条通道”方案
def probe_main(kind):
    """子进程入口。成功则打印 PROBE_OK。"""
    out_png = OUT / f"probe_{kind.lower()}.png"
    if kind == "COMP_FREESTYLE":
        sc = reset_scene()
        build_figure(sc)
        setup_camera(sc)
        vl = setup_freestyle(sc)
        set_comp_freestyle_pass(sc, vl, True)
        render_to(sc, out_png)
        print("PROBE_OK")
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    me = bpy.data.meshes.new("cube")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    sc.collection.objects.link(bpy.data.objects.new("cube", me))
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.location = (0, -4, 2)
    cam.rotation_euler = (math.radians(65), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.engine = kind
    sc.render.resolution_x = sc.render.resolution_y = 64
    render_to(sc, out_png)
    print("PROBE_OK")


def run_probe(kind, timeout=180):
    out_png = OUT / f"probe_{kind.lower()}.png"
    if out_png.exists():
        out_png.unlink()
    if is_blender_binary():
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", "-P", __file__, "--", "--probe", kind]
    else:
        cmd = [sys.executable, __file__, "--probe", kind]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, text = p.returncode, (p.stdout + "\n" + p.stderr)
    except subprocess.TimeoutExpired as e:
        rc, text = "timeout", str(e)
    dt = time.perf_counter() - t0
    ok = rc == 0 and "PROBE_OK" in text and out_png.exists()
    # 只保留看起来像错误的行，方便写进报告
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("Fra:")]
    keys = ("error", "fail", "unable", "egl", "gpu", "abort", "segfault", "signal", "exception", "couldn't")
    err = [l for l in lines if any(k in l.lower() for k in keys)]
    if out_png.exists() and kind != "COMP_FREESTYLE":
        out_png.unlink()
    return {"ok": ok, "returncode": rc, "seconds": round(dt, 2),
            "error": None if ok else "\n".join((err or lines)[-12:])[:2000]}


# ================================================================ d'. 无压缩多层 EXR 读取（取 Freestyle 渲染通道用）
def read_exr_none(path):
    """极简 OpenEXR 读取器：仅支持无压缩(NONE)的扫描线图，单 part 或多 part。
    返回 {通道名: float32 数组 (H, W)}。Blender 5.x 的多层 EXR 是多 part，每个通道组一个 part。"""
    import struct
    b = Path(path).read_bytes()
    magic, ver = struct.unpack_from("<II", b, 0)
    assert magic == 20000630, "不是 EXR 文件"
    assert not ver & 0x200, "不支持 tiled EXR"
    multipart = bool(ver & 0x1000)
    pos, headers = 8, []
    while True:  # 头部：属性列表 name\0 type\0 int32(size) value ... \0
        h = {}
        while b[pos] != 0:
            e = b.index(b"\0", pos); name = b[pos:e].decode(); pos = e + 1
            e = b.index(b"\0", pos); typ = b[pos:e].decode(); pos = e + 1
            (size,) = struct.unpack_from("<i", b, pos); pos += 4
            h[name] = (typ, b[pos:pos + size]); pos += size
        pos += 1
        headers.append(h)
        if not multipart:
            break
        if b[pos] == 0:  # 多 part：头部列表以额外的 \0 结束
            pos += 1
            break
    parts, out = [], {}
    for h in headers:
        assert h["compression"][1] == b"\0", "只支持 exr_codec='NONE'"
        cl, p, chans = h["channels"][1], 0, []
        while cl[p] != 0:  # chlist：name\0 int32(pixel_type) uint8 pLinear 3xpad int32 xs int32 ys
            e = cl.index(b"\0", p)
            chans.append((cl[p:e].decode(), {0: "<u4", 1: "<f2", 2: "<f4"}[struct.unpack_from("<i", cl, e + 1)[0]]))
            p = e + 17
        x0, y0, x1, y1 = struct.unpack("<4i", h["dataWindow"][1])
        W, H = x1 - x0 + 1, y1 - y0 + 1
        n = struct.unpack("<i", h["chunkCount"][1])[0] if "chunkCount" in h else H
        parts.append((chans, W, H, y0, n))
        for c, _ in chans:
            out[c] = np.zeros((H, W), np.float32)
    tables = []
    for *_, n in parts:  # 每个 part 一张 uint64 偏移表
        tables.append(np.frombuffer(b, "<u8", n, pos)); pos += 8 * n
    for pi, (chans, W, H, y0, _) in enumerate(parts):
        for o in tables[pi]:
            o = int(o) + (4 if multipart else 0)  # 多 part 的块前有 int32 part 号
            y, _size = struct.unpack_from("<ii", b, o); o += 8
            for c, dt in chans:  # 无压缩：每行按通道顺序依次存放 W 个值
                out[c][y - y0] = np.frombuffer(b, dt, W, o); o += W * np.dtype(dt).itemsize
    return out


def linear_to_srgb8(x):
    x = np.clip(x, 0, 1)
    s = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def save_pass_png(chans, prefix, path):
    """把某个渲染通道（预乘 alpha 的线性 RGBA）存成直通 alpha 的 sRGB PNG。"""
    a = chans[prefix + ".A"]
    rgb = np.stack([chans[prefix + c] for c in (".R", ".G", ".B")], -1)
    rgb = np.where(a[..., None] > 1e-4, rgb / np.maximum(a[..., None], 1e-4), 0)
    img = np.concatenate([linear_to_srgb8(rgb), (np.clip(a, 0, 1)[..., None] * 255 + 0.5).astype(np.uint8)], -1)
    Image.fromarray(img, "RGBA").save(path)


# ================================================================ c. 场景与材质
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x = r.resolution_y = RES
    r.resolution_percentage = 100
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    r.image_settings.color_depth = "8"
    r.dither_intensity = 0.0  # 默认 1.0 会给 8 位输出加抖动噪点，平涂色块/调色板量化不需要
    r.use_compositing = False
    r.compositor_device = "CPU"  # 默认是 GPU：无 EGL 时会直接 abort 整个进程
    try:
        sc.view_settings.view_transform = "Standard"  # 不要 AgX/Filmic，保证 hex 颜色原样输出
    except TypeError:
        warn("view_transform Standard 不可用")
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = SAMPLES
    cy.use_adaptive_sampling = False
    cy.max_bounces = 0
    cy.use_denoising = False
    cy.pixel_filter_type = "BLACKMAN_HARRIS"
    return sc


def new_mesh_obj(name, build, mat, parent, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), smooth=True):
    """用 bmesh 构建网格（不依赖 bpy.ops 上下文）。build(bm) 往 bm 里加几何。"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(40))  # 圆柱侧面平滑、底面保持硬边
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.rotation_euler, ob.scale = loc, rot, scale
    ob.parent = parent
    bpy.context.scene.collection.objects.link(ob)
    return ob


def cone(r1, r2, depth, seg=32):
    return lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                                            radius1=r1, radius2=r2, depth=depth)


def sphere(r, u=32, v=16):
    return lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)


def sock(sockets, ident):
    return next(s for s in sockets if s.identifier == ident)


def new_node_material(name):
    """新建空节点材质。Blender 5.x 新材质默认就带节点树（use_nodes 已弃用）。"""
    m = bpy.data.materials.new(name)
    if m.node_tree is None:  # 兼容旧版本
        m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return m, nt


def toon_material(name, lit_hex, shadow_hex):
    """自发光假卡通：dot(N, L) → ColorRamp(CONSTANT, 3 档) → Mix(暗色, 亮色) → Emission。
    不依赖任何灯光，max_bounces=0 也能出正确颜色。"""
    m, nt = new_node_material(name)
    N = nt.nodes
    geo = N.new("ShaderNodeNewGeometry")
    dot = N.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = LIGHT_DIR  # 常量光照方向
    ramp = N.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    # 3 档：暗 (dot<0.15) / 中 (0.15~0.6) / 亮 (>=0.6)，输出灰度作为 Mix 因子
    cr.elements[0].position, cr.elements[0].color = 0.0, (0, 0, 0, 1)
    cr.elements[1].position, cr.elements[1].color = 0.6, (1, 1, 1, 1)
    mid = cr.elements.new(0.15)
    mid.color = (0.5, 0.5, 0.5, 1)
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MIX"
    sock(mix.inputs, "A_Color").default_value = hex_lin(shadow_hex)
    sock(mix.inputs, "B_Color").default_value = hex_lin(lit_hex)
    emi = N.new("ShaderNodeEmission")
    out = N.new("ShaderNodeOutputMaterial")
    L = nt.links
    L.new(geo.outputs["Normal"], dot.inputs[0])
    L.new(dot.outputs["Value"], ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"], sock(mix.inputs, "Factor_Float"))
    L.new(sock(mix.outputs, "Result_Color"), emi.inputs["Color"])
    L.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def normal_material():
    """法线图覆盖材质：世界法线 → 相机空间 → *0.5+0.5 → Emission。
    Cycles 的相机空间 +Z 指向画面里（远离相机），这里把 Z 取反，
    得到常见的 OpenGL 约定：R=右, G=上, B=朝向观察者。"""
    m, nt = new_node_material("NormalOverride")
    N, L = nt.nodes, nt.links
    geo = N.new("ShaderNodeNewGeometry")
    vt = N.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "NORMAL", "WORLD", "CAMERA"
    flip = N.new("ShaderNodeVectorMath")
    flip.operation = "MULTIPLY"
    flip.inputs[1].default_value = (1.0, 1.0, -1.0)
    ma = N.new("ShaderNodeVectorMath")
    ma.operation = "MULTIPLY_ADD"
    ma.inputs[1].default_value = (0.5, 0.5, 0.5)
    ma.inputs[2].default_value = (0.5, 0.5, 0.5)
    emi = N.new("ShaderNodeEmission")
    out = N.new("ShaderNodeOutputMaterial")
    L.new(geo.outputs["Normal"], vt.inputs["Vector"])
    L.new(vt.outputs["Vector"], flip.inputs[0])
    L.new(flip.outputs["Vector"], ma.inputs[0])
    L.new(ma.outputs["Vector"], emi.inputs["Color"])
    L.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def holdout_material():
    m, nt = new_node_material("HoldoutOverride")
    h = nt.nodes.new("ShaderNodeHoldout")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(h.outputs["Holdout"], out.inputs["Surface"])
    return m


def build_figure(sc):
    """程序化 Q 版小人：球头、斗笠（锥 + 宽扁圆柱帽檐）、锥形长袍、两条小腿、
    右手（画面左侧）举一根细杆挑着朱红小灯笼。人物面向 -Y（朝相机）。"""
    paper = toon_material("Paper", PAPER_LIT, PAPER_SHADOW)
    ink_dark = toon_material("Robe", PAPER_MID, PAPER_SHADOW)
    lantern_m = toon_material("Lantern", VERMILION, VERMILION_SHADOW)

    root = bpy.data.objects.new("FigureRoot", None)  # 空物体，旋转它即可出 8 方向
    sc.collection.objects.link(root)

    for x in (-0.1, 0.1):  # 腿
        new_mesh_obj(f"Leg{x:+.1f}", cone(0.07, 0.07, 0.3, 16), ink_dark, root, loc=(x, 0, 0.15))
    new_mesh_obj("Robe", cone(0.36, 0.2, 0.62), paper, root, loc=(0, 0, 0.56))
    new_mesh_obj("Head", sphere(0.28), paper, root, loc=(0, 0, 1.12))
    new_mesh_obj("HatBrim", cone(0.56, 0.56, 0.035, 48), ink_dark, root, loc=(0, 0, 1.30))
    new_mesh_obj("HatCone", cone(0.32, 0.0, 0.34, 48), ink_dark, root, loc=(0, 0, 1.49))

    # 杆：从手（画面左下）斜向外上方伸出；人物的右手 = 世界 -X
    hand, tip = Vector((-0.30, -0.12, 0.62)), Vector((-0.78, -0.22, 1.22))
    mid, d = (hand + tip) / 2, tip - hand
    pole = new_mesh_obj("Pole", cone(0.018, 0.018, d.length, 8), ink_dark, root, loc=mid)
    pole.rotation_mode = "QUATERNION"
    pole.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    # 灯笼挂在杆尖下方，用细绳连接
    lantern = new_mesh_obj("Lantern", sphere(0.12), lantern_m, root,
                           loc=(tip.x, tip.y, tip.z - 0.26), scale=(1, 1, 1.25))
    new_mesh_obj("String", cone(0.006, 0.006, 0.12, 6), ink_dark, root, loc=(tip.x, tip.y, tip.z - 0.07))
    return root, lantern


def setup_camera(sc):
    """正交相机，rotation_x=60°（俯视 30°），看向人物中心。"""
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.3
    cam.rotation_euler = (math.radians(60), 0, 0)
    target = Vector((-0.12, 0, 0.82))
    fwd = cam.rotation_euler.to_matrix() @ Vector((0, 0, -1))
    cam.location = target - fwd * 10.0
    cam.data.clip_end = 50
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam


# ================================================================ d. Freestyle 墨线
def setup_freestyle(sc, line_scale=1.0):
    """绝对像素线宽；剪影+边界+折痕+外轮廓；书法线宽 + 沿笔画两端收尖 + 1D 柏林噪声抖动。"""
    r = sc.render
    r.use_freestyle = True
    r.line_thickness_mode = "ABSOLUTE"
    r.line_thickness = 1.0
    vl = sc.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.mode = "EDITOR"
    fs.crease_angle = math.radians(120)
    ls_set = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("Ink")
    ls_set.select_by_visibility = True
    ls_set.visibility = "VISIBLE"
    ls_set.select_by_edge_types = True
    for attr in ("select_silhouette", "select_border", "select_crease", "select_external_contour"):
        setattr(ls_set, attr, True)
    for attr in ("select_contour", "select_suggestive_contour", "select_ridge_valley",
                 "select_material_boundary", "select_edge_mark"):
        setattr(ls_set, attr, False)

    st = ls_set.linestyle or bpy.data.linestyles.new("InkStyle")
    ls_set.linestyle = st
    st.color = hex_lin(INK)[:3]
    st.thickness = 4.0 * line_scale
    st.caps = "ROUND"
    st.chaining = "PLAIN"
    for mods in (st.thickness_modifiers, st.geometry_modifiers):
        for m in list(mods):
            mods.remove(m)
    # 采样（几何修改器顺序：先采样再加噪声）
    samp = st.geometry_modifiers.new(name="Sampling", type="SAMPLING")
    samp.sampling = 2.0
    noise = st.geometry_modifiers.new(name="Noise", type="PERLIN_NOISE_1D")
    noise.frequency, noise.amplitude, noise.octaves, noise.seed = 12.0, 1.2 * line_scale, 2, 7
    # 书法：45° 方向最粗
    cal = st.thickness_modifiers.new(name="Calligraphy", type="CALLIGRAPHY")
    cal.orientation = math.radians(45)
    cal.thickness_min, cal.thickness_max = 2.0 * line_scale, 8.0 * line_scale
    cal.blend = "MIX"
    # 沿笔画：两端收尖（乘法）
    along = st.thickness_modifiers.new(name="Taper", type="ALONG_STROKE")
    along.blend = "MULTIPLY"
    along.mapping = "CURVE"
    along.value_min, along.value_max = 0.0, 1.0
    cm = along.curve
    pts = cm.curves[0].points
    pts[0].location, pts[1].location = (0.0, 0.15), (1.0, 0.15)
    pts.new(0.2, 1.0)
    pts.new(0.8, 1.0)
    cm.update()
    return vl


def set_comp_freestyle_pass(sc, vl, on):
    """as_render_pass：线条作为单独的 Freestyle 渲染通道；用合成器把该通道接到输出。"""
    vl.freestyle_settings.as_render_pass = on
    if not on:
        sc.render.use_compositing = False
        return
    ng = bpy.data.node_groups.new("CompLines", "CompositorNodeTree")
    ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    rl.scene, rl.layer = sc, vl.name
    gout = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Freestyle"], gout.inputs[0])
    sc.compositing_node_group = ng
    sc.render.compositor_device = "CPU"
    sc.render.use_compositing = True


def render_to(sc, path):
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def alpha_count(path, thr=0.5):
    if Image is None:
        return None
    a = np.asarray(Image.open(path).convert("RGBA"))[..., 3] / 255.0
    return int((a > thr).sum())


# ================================================================ e. OIDN
def check_oidn(sc):
    info = {}
    try:
        import _cycles
        info["with_openimagedenoise"] = bool(_cycles.with_openimagedenoise)
        # available_devices 元组第 6 项(索引 5)=该设备支持 OIDN
        devs = _cycles.available_devices("CPU")
        info["cpu_device"] = devs[0][0] if devs else None
        info["cpu_supports_oidn"] = bool(devs[0][5]) if devs else None
    except Exception as e:
        info["error"] = repr(e)
    # 实测：128px 开降噪渲一张
    r, cy = sc.render, sc.cycles
    old = (r.resolution_x, r.use_freestyle)
    try:
        r.resolution_x = r.resolution_y = 128
        r.use_freestyle = False
        cy.use_denoising = True
        cy.denoiser = "OPENIMAGEDENOISE"
        t0 = time.perf_counter()
        render_to(sc, OUT / "oidn_test.png")
        info["test_render_ok"] = True
        info["test_render_s"] = round(time.perf_counter() - t0, 2)
    except Exception as e:
        info["test_render_ok"] = False
        info["test_error"] = repr(e)
    finally:
        cy.use_denoising = False
        r.resolution_x = r.resolution_y = old[0]
        r.use_freestyle = old[1]
    return info


# ================================================================ 3. 后备方案：反向外壳 + Sobel
def inverted_hull_material():
    """配合 Solidify(翻转法线) 外壳得到轮廓线。
    外壳法线朝内：靠近相机的那半边是“背面”→ 透明（露出本体）；
    远端那半边是“正面”，只在本体轮廓外露出一圈 → 墨色自发光。
    （按原始法线方向理解，就是“外壳的背面涂黑、正面透明”。）"""
    m, nt = new_node_material("HullInk")
    N, L = nt.nodes, nt.links
    geo = N.new("ShaderNodeNewGeometry")
    tr = N.new("ShaderNodeBsdfTransparent")
    emi = N.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = hex_lin(INK)
    mix = N.new("ShaderNodeMixShader")
    out = N.new("ShaderNodeOutputMaterial")
    L.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    L.new(emi.outputs["Emission"], mix.inputs[1])  # Backfacing=0（翻转后的正面）→ 墨色
    L.new(tr.outputs["BSDF"], mix.inputs[2])       # Backfacing=1 → 透明
    L.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


def add_inverted_hulls(root, thickness=0.02):
    hull = inverted_hull_material()
    mods = []
    for ob in root.children:
        if ob.type != "MESH":
            continue
        ob.data.materials.append(hull)
        md = ob.modifiers.new("InkHull", "SOLIDIFY")
        md.thickness = -thickness * (0.4 if ob.name in ("Pole", "String") else 1.0)
        md.offset = -1.0
        md.use_flip_normals = True
        md.use_rim = False
        md.material_offset = 1  # 外壳用第 2 个材质槽
        mods.append((ob, md))
    return mods


def sobel_lines(normal_png, out_png, thr=0.9):
    """对法线图做 Sobel，边缘强处 → 墨色像素（RGBA）。"""
    n = np.asarray(Image.open(normal_png).convert("RGBA")).astype(np.float32) / 255.0
    rgb, a = n[..., :3] * 2 - 1, n[..., 3]
    feat = np.concatenate([rgb * a[..., None], a[..., None] * 2.0], axis=-1)
    pad = np.pad(feat, ((1, 1), (1, 1), (0, 0)), mode="edge")
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], np.float32)
    gx = np.zeros_like(feat)
    gy = np.zeros_like(feat)
    H, W = feat.shape[:2]
    for dy in range(3):
        for dx in range(3):
            win = pad[dy:dy + H, dx:dx + W]
            gx += kx[dy, dx] * win
            gy += kx.T[dy, dx] * win
    mag = np.sqrt((gx ** 2 + gy ** 2).sum(-1))
    edge = np.clip((mag - thr) / thr, 0, 1)
    ink = np.array(hex_rgb(INK)) * 255
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = ink.astype(np.uint8)
    img[..., 3] = (edge * 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(out_png)
    return int((edge > 0.5).sum())


# ================================================================ 4. 后处理预览
def postprocess(lantern_uv):
    src = Image.open(OUT / "combined.png").convert("RGBA")
    # 4x 缩小（LANCZOS）后铺纸色底
    small = src.resize((src.width // 4, src.height // 4), Image.LANCZOS)
    bg = Image.new("RGBA", small.size, hex_rgb_255(PAPER_BG))
    prev = Image.alpha_composite(bg, small)
    prev.save(OUT / "preview_128.png")
    prev.resize((small.width * 3, small.height * 3), Image.NEAREST).save(OUT / "preview_zoom.png")

    # 夜景：图像 × (靛蓝环境光 + 灯笼处的暖色径向光)，再叠在深色底上
    arr = np.asarray(src).astype(np.float32) / 255.0
    H, W = arr.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = lantern_uv[0] * W, (1 - lantern_uv[1]) * H
    d2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / (0.33 * W) ** 2
    glow = np.exp(-d2)[..., None]
    amb = np.array(hex_rgb(NIGHT_AMBIENT))
    warm = np.array(hex_rgb(LANTERN_WARM))
    light = np.clip(amb * 2.2 + warm * glow * 1.15, 0, 1.4)  # 环境光略提亮，否则人物几乎全黑
    lit = arr[..., :3] * light
    # 灯笼本体（朱红色像素）保持自发光
    lan = np.asarray(src.convert("RGB")).astype(np.float32) / 255.0
    is_red = ((lan[..., 0] > lan[..., 1] * 1.6) & (arr[..., 3] > 0.5))[..., None]
    lit = np.where(is_red, np.clip(arr[..., :3] * 1.25 + 0.05, 0, 1), lit)
    sky = amb * (0.85 + 0.6 * glow * warm / warm.max())  # 背景：靛蓝 + 灯笼周围一点暖晕
    a = arr[..., 3:4]
    rgb = lit * a + sky * (1 - a)
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB").save(OUT / "night.png")


# ================================================================ 主流程
def main():
    T0 = time.perf_counter()
    report["timings_s"]["import_bpy"] = round(IMPORT_BPY_S, 3)
    with Timer("engine_list"):
        report["mode"] = "blender_binary" if is_blender_binary() else "bpy_module"
        report["blender_path"] = bpy.app.binary_path or str(Path(bpy.__file__).parent)
        report["python"] = sys.version.split()[0]
        report["version"] = bpy.app.version_string
        report["engines"] = list_engines()
        try:
            import PIL
            report["pillow"] = PIL.__version__
        except ImportError:
            report["pillow"] = None
        report["numpy"] = np.__version__
    print("Blender", report["version"], "engines:", report["engines"])

    # b. Workbench / EEVEE / 合成器+Freestyle（子进程，失败也不影响主流程）
    report["probes"] = {}
    for kind in ("BLENDER_WORKBENCH", "BLENDER_EEVEE", "COMP_FREESTYLE"):
        with Timer(f"probe_{kind.lower()}"):
            res = run_probe(kind)
        report["probes"][kind] = res
        print(f"probe {kind}: ok={res['ok']} rc={res['returncode']}")
        if res["error"]:
            print("   ", res["error"].replace("\n", "\n    "))

    # c. 场景搭建
    with Timer("scene_build"):
        sc = reset_scene()
        root, lantern = build_figure(sc)
        cam = setup_camera(sc)
        bpy.context.view_layer.update()  # 刷新 matrix_world，否则投影坐标全是原点
    from bpy_extras.object_utils import world_to_camera_view
    lp = world_to_camera_view(sc, cam, lantern.matrix_world.translation)
    report["lantern_screen_uv"] = [round(lp.x, 4), round(lp.y, 4)]

    # c. 仅填色 512（先渲一张 64px 预热，排除首次加载内核/建 BVH 的时间）
    try:
        sc.render.use_freestyle = False
        sc.render.resolution_x = sc.render.resolution_y = 64
        with Timer("cycles_warmup_64"):
            render_to(sc, OUT / "_warmup.png")
        (OUT / "_warmup.png").unlink()
        sc.render.resolution_x = sc.render.resolution_y = RES
        with Timer("fill_512"):
            render_to(sc, OUT / "fill.png")
        report["cycles_ok"] = True
    except Exception as e:
        report["cycles_ok"] = False
        warn("Cycles 渲染失败: " + repr(e))
        raise

    # d. Freestyle：填色+线条合成
    vl = setup_freestyle(sc)
    report["freestyle"] = {}
    try:
        with Timer("freestyle_combined_512"):
            render_to(sc, OUT / "combined.png")
        report["freestyle"]["combined_ok"] = True
        report["timings_s"]["freestyle_overhead_512"] = round(
            report["timings_s"]["freestyle_combined_512"] - report["timings_s"]["fill_512"], 3)
    except Exception as e:
        report["freestyle"]["combined_ok"] = False
        warn("Freestyle 合成渲染失败: " + repr(e))

    # d(b). 仅线条，三种方法：
    #   1a 合成器取 Freestyle 通道 → 已在子进程 COMP_FREESTYLE 里测（无 GPU 时 abort）
    #   1b as_render_pass + 无压缩多层 EXR → numpy 解出 Freestyle 通道（一次渲染同时得到填色和线条）
    #   2  material_override=Holdout → 只剩线条
    comp = report["probes"]["COMP_FREESTYLE"]
    report["freestyle"]["pass_via_compositor_ok"] = comp["ok"]
    method = "freestyle_render_pass+compositor" if comp["ok"] else None
    if comp["ok"]:
        os.replace(OUT / "probe_comp_freestyle.png", OUT / "lines.png")
    try:
        vl.freestyle_settings.as_render_pass = True
        im = sc.render.image_settings
        im.media_type, im.exr_codec, im.color_depth = "MULTI_LAYER_IMAGE", "NONE", "16"
        exr = OUT / "passes.exr"
        with Timer("fill_plus_lines_pass_exr_512"):
            render_to(sc, exr)
        with Timer("exr_decode"):
            ch = read_exr_none(exr)
        report["freestyle"]["exr_channels"] = sorted(ch)
        if Image is not None and "ViewLayer.Freestyle.A" in ch:
            save_pass_png(ch, "ViewLayer.Freestyle", OUT / ("lines.png" if not method else "lines_exr.png"))
            save_pass_png(ch, "ViewLayer.Combined", OUT / "fill_from_exr.png")
            n = int((ch["ViewLayer.Freestyle.A"] > 0.5).sum())
            report["freestyle"]["exr_pass_line_pixels"] = n
            if n and not method:
                method = "freestyle_render_pass+multilayer_exr"
        exr.unlink()
    except Exception:
        warn("as_render_pass + EXR 失败: " + traceback.format_exc(limit=2))
    finally:
        vl.freestyle_settings.as_render_pass = False
        im = sc.render.image_settings
        im.media_type, im.color_depth = "IMAGE", "8"
        im.file_format, im.color_mode = "PNG", "RGBA"
    try:
        vl.material_override = holdout_material()
        target = OUT / ("lines_holdout.png" if method else "lines.png")
        with Timer("lines_holdout_512"):
            render_to(sc, target)
        n = alpha_count(target)
        report["freestyle"]["holdout_line_pixels"] = n
        if n and not method:
            method = "material_override_holdout"
    except Exception as e:
        warn("Holdout 覆盖渲染失败: " + repr(e))
    finally:
        vl.material_override = None
    report["freestyle"]["lines_method"] = method
    freestyle_ok = bool(method) and report["freestyle"].get("combined_ok")

    # e. OIDN
    with Timer("oidn_check"):
        report["oidn"] = check_oidn(sc)

    # f. 法线图
    sc.render.use_freestyle = False
    view_tf = sc.view_settings.view_transform
    try:
        sc.view_settings.view_transform = "Raw"  # 法线值线性写出，不做显示变换
    except TypeError:
        warn("view_transform Raw 不可用，法线图会被 sRGB 编码")
    vl.material_override = normal_material()
    with Timer("normal_512"):
        render_to(sc, OUT / "normal.png")
    vl.material_override = None
    sc.view_settings.view_transform = view_tf
    if Image is not None:  # 球头中心应接近 (0.5, 0.5+, 1.0)
        nrm = np.asarray(Image.open(OUT / "normal.png").convert("RGBA"))
        hc = world_to_camera_view(sc, cam, Vector((0, 0, 1.12)) + Vector((0, -0.3, 0)))
        px = nrm[int((1 - hc.y) * RES), int(hc.x * RES)]
        report["normal_sample_head_front_rgba"] = [int(v) for v in px]

    # g. 线条像素统计
    report["line_pixel_count"] = alpha_count(OUT / "lines.png") if (OUT / "lines.png").exists() else None

    # 3. 后备：反向外壳 + Sobel（Freestyle 不可用时才是主方案；这里始终跑一次以便对比时间）
    report["fallback"] = {}
    try:
        sc.render.use_freestyle = False
        mods = add_inverted_hulls(root)
        with Timer("fallback_hull_512"):
            render_to(sc, OUT / "fallback_hull.png")
        for ob, md in mods:
            ob.modifiers.remove(md)
            ob.data.materials.pop()
        report["fallback"]["inverted_hull_ok"] = True
        if Image is not None:
            with Timer("fallback_sobel"):
                report["fallback"]["sobel_edge_pixels"] = sobel_lines(OUT / "normal.png", OUT / "fallback_sobel_lines.png")
    except Exception:
        report["fallback"]["inverted_hull_ok"] = False
        warn("反向外壳后备方案失败: " + traceback.format_exc(limit=2))

    # h. 8 方向 256px，开 Freestyle（Freestyle 不可用时退回反向外壳描边）
    sc.render.resolution_x = sc.render.resolution_y = DIR_RES
    sc.cycles.samples = DIR_SAMPLES
    if freestyle_ok:
        setup_freestyle(sc, line_scale=DIR_RES / RES)
        report["dir8_line_method"] = "freestyle"
    else:
        sc.render.use_freestyle = False
        add_inverted_hulls(root, thickness=0.02)
        report["dir8_line_method"] = "inverted_hull_fallback"
    frames, times = [], []
    for i in range(8):
        root.rotation_euler = (0, 0, math.radians(45 * i))
        p = OUT / f"dir_{i}.png"
        t0 = time.perf_counter()
        render_to(sc, p)
        times.append(time.perf_counter() - t0)
        frames.append(p)
    root.rotation_euler = (0, 0, 0)
    report["timings_s"]["dir8_total_256"] = round(sum(times), 3)
    report["timings_s"]["dir8_avg_frame_256"] = round(sum(times) / 8, 3)
    if Image is not None:
        sheet = Image.new("RGBA", (DIR_RES * 8, DIR_RES), hex_rgb_255(PAPER_BG))
        for i, p in enumerate(frames):
            im = Image.open(p).convert("RGBA")
            sheet.alpha_composite(im, (i * DIR_RES, 0))
        sheet.save(OUT / "contact_dirs.png")
        for p in frames:
            p.unlink()
    else:
        warn("没有 Pillow：跳过 contact_dirs.png，单帧保留为 dir_*.png")

    # 4. 后处理预览
    if Image is not None and (OUT / "combined.png").exists():
        with Timer("postprocess"):
            postprocess(report["lantern_screen_uv"])
    else:
        warn("跳过后处理预览（缺 Pillow 或 combined.png）")

    report["timings_s"]["total"] = round(time.perf_counter() - T0, 3)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["timings_s"], indent=2))
    print("report →", OUT / "report.json")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if argv[:1] == ["--probe"]:
        probe_main(argv[1])
    else:
        main()
