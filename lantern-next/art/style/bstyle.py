"""提灯夜行 · Blender 侧的风格辅助函数（bpy）。

所有颜色、尺寸、相机、线条参数都从 style.py 取，这里只负责把它们变成 Blender 场景设置。
用法（脚本里先把 art/ 加进 sys.path）：

    from style import style as S
    from style import bstyle as B

    B.reset_scene()
    B.setup_render(S.FRAME["hero"])
    B.setup_camera(S.FRAME["hero"])
    B.setup_freestyle()
    ...建模，B.add_object(ob, line="outer") ...
    with B.render_lock():
        layers = B.render_layers(out_dir / "hero_idle_S_00")

经验做法都来自 render/smoke_test.py：
  - 只用 Cycles CPU（EEVEE/Workbench 无 libEGL 会 abort）；
  - Freestyle 用 as_render_pass 输出到无压缩多层 EXR，再用 numpy 读，一次渲染同时得到填色和线条；
  - 不走合成器（开 Freestyle 时合成器会触发 EGL 初始化并 abort）；
  - dither_intensity=0，view_transform='Standard'，保证 hex 颜色原样输出。
"""

from __future__ import annotations

import contextlib
import fcntl
import math
import os
import struct
import sys
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import style as S  # noqa: E402

# ---------------------------------------------------------------- 本文件内的可调参数
# （只影响 Blender 侧的笔触/晕染手感，不是全局风格常量；全局常量都在 style.py）

WASH_AMOUNT = 0.22  # 水墨晕染：物体空间噪声对光照点积的扰动幅度（让明暗分界不规则）
WASH_SCALE = 2.2  # 晕染噪声频率（每米）
WASH_VALUE = 0.04  # 晕染造成的明度起伏（±2%，后期吸附调色板时会被收回到容差内）
EDGE_AMOUNT = 0.55  # 积墨：越靠近轮廓越暗，对点积的最大压低量
EDGE_POWER = 3.0  # 积墨只集中在轮廓附近
CREASE_ANGLE_DEG = 128.0  # Freestyle 折痕角：两面法线夹角大于 180-此值 才算折痕
SAMPLING_PX = 1.5  # 线条重采样间距（最终像素）
SPLIT_ANGLE_DEG = 115.0  # 笔画在小于这个 2D 角度的拐角处断开，每段单独收笔
PRESSURE_PERIOD = 1500.0  # Freestyle 粗细噪声的 period（内部单位，见 _linestyle 注释）

# 线宽分级用的集合：物体放进哪个集合，就用哪一档线
LINE_COLLECTIONS = {"outer": "InkOuter", "inner": "InkInner", "none": "InkNone"}

LOCK_PATH = ART / "out" / ".render.lock"


# ================================================================ 小工具
def hex_lin(h: str, a: float = 1.0) -> tuple[float, float, float, float]:
    """sRGB hex → Blender 节点用的线性 RGBA。"""
    return (*S.hex_to_linear(h), a)


def sock(sockets, ident):
    """按 identifier 取节点插口（Mix 节点等同名插口多，按名字取会取错）。"""
    return next(s for s in sockets if s.identifier == ident)


def _new_node_material(name: str):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:  # 兼容旧版本；5.x 新材质自带节点树，use_nodes 已弃用
        m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return m, nt


# ================================================================ 场景与渲染设置
def reset_scene():
    """清空成空场景，并建好三档线宽集合。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    for key, name in LINE_COLLECTIONS.items():
        coll = bpy.data.collections.new(name)
        sc.collection.children.link(coll)
    return sc


def setup_render(frame_px: int, samples: int = S.SAMPLES, threads: int | None = None):
    """Cycles CPU、透明底、Standard 显示变换、无抖动，分辨率 = 最终帧 × RENDER_SCALE 的正方形。"""
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x = r.resolution_y = int(frame_px * S.RENDER_SCALE)
    r.resolution_percentage = 100
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    r.film_transparent = True
    r.dither_intensity = 0.0
    r.use_compositing = False
    r.use_sequencer = False
    r.compositor_device = "CPU"  # 默认 GPU，无 EGL 时会 abort
    if threads:
        r.threads_mode = "FIXED"
        r.threads = int(threads)
    else:
        r.threads_mode = "AUTO"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.display_settings.display_device = "sRGB"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = int(samples)
    cy.use_adaptive_sampling = False
    cy.max_bounces = 0
    cy.transparent_max_bounces = 8
    cy.use_denoising = False
    cy.seed = 0
    cy.pixel_filter_type = "BLACKMAN_HARRIS"
    cy.filter_width = 1.5
    vl = sc.view_layers[0]
    vl.use_pass_combined = True
    vl.use_pass_object_index = True
    # 实测（bpy 5.2.2）：只开 Object Index 时该通道全是 0；同时开 Depth 才会写出物体编号
    vl.use_pass_z = True
    vl.pass_alpha_threshold = 0.5  # 透明度高于一半的表面才写物体编号（灯笼纸壳透出内芯时用到）
    if sc.world is None:  # 没有世界时 Cycles 背景为黑；透明底下无影响，但保证存在
        sc.world = bpy.data.worlds.new("World")
    sc.world.color = (0, 0, 0)
    return sc


def camera_basis():
    """相机的右、上、前方向（世界坐标）。相机在 -Y 侧朝 +Y 看，俯角 CAMERA_PITCH_DEG。"""
    p = math.radians(S.CAMERA_PITCH_DEG)
    right = Vector((1.0, 0.0, 0.0))
    up = Vector((0.0, math.sin(p), math.cos(p)))
    fwd = Vector((0.0, math.cos(p), -math.sin(p)))
    return right, up, fwd


def setup_camera(frame_px: int, distance: float = 30.0):
    """正交相机：俯角 30°，取景宽度 ortho_scale(frame_px)。
    不用 shift，而是平移相机，让世界原点（脚底）正好落在 (ANCHOR[0]*W, ANCHOR[1]*H)。"""
    sc = bpy.context.scene
    cam = sc.camera
    if cam is None:
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cd = cam.data
    cd.type = "ORTHO"
    cd.ortho_scale = S.ortho_scale(frame_px)
    cd.shift_x = cd.shift_y = 0.0
    cd.sensor_fit = "AUTO"
    cd.clip_start = 0.1
    cd.clip_end = distance * 2.5
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (math.radians(90.0 - S.CAMERA_PITCH_DEG), 0.0, 0.0)
    right, up, fwd = camera_basis()
    w = cd.ortho_scale  # 正方形画面：宽 = 高 = ortho_scale（米）
    # 画面中心对准的世界点：原点向“画面右”挪 (0.5-ax)*w，向“画面上”挪 (ay-0.5)*w
    target = right * ((0.5 - S.ANCHOR[0]) * w) + up * ((S.ANCHOR[1] - 0.5) * w)
    cam.location = target - fwd * distance
    bpy.context.view_layer.update()
    return cam


def project_point(world_xyz, frame_px: int) -> tuple[float, float]:
    """世界坐标 → 最终像素，相对锚点（脚底），x 向右、y 向下。用于挂点。
    正交投影与帧尺寸无关：1 米 = PX_PER_M 像素；这里仍用当前相机做一次投影，便于和渲染结果一致。"""
    from bpy_extras.object_utils import world_to_camera_view

    sc = bpy.context.scene
    co = world_to_camera_view(sc, sc.camera, Vector(world_xyz))
    x = (co.x - S.ANCHOR[0]) * frame_px
    y = ((1.0 - co.y) - S.ANCHOR[1]) * frame_px
    return x, y


def project_point_analytic(world_xyz) -> tuple[float, float]:
    """不依赖相机物体的解析投影（同上，用于自检）。"""
    right, up, _ = camera_basis()
    v = Vector(world_xyz)
    return v.dot(right) * S.PX_PER_M, -v.dot(up) * S.PX_PER_M


def verify_camera(frame_px: int, verbose: bool = True) -> float:
    """数值验证：原点必须投影到锚点像素；几个随机点的解析投影与相机投影一致。返回最大误差（像素）。"""
    from bpy_extras.object_utils import world_to_camera_view

    sc = bpy.context.scene
    co = world_to_camera_view(sc, sc.camera, Vector((0, 0, 0)))
    W = H = frame_px * S.RENDER_SCALE
    px, py = co.x * W, (1 - co.y) * H
    err = max(abs(px - S.ANCHOR[0] * W), abs(py - S.ANCHOR[1] * H)) / S.RENDER_SCALE
    rng = np.random.default_rng(1)
    for p in rng.uniform(-1, 1, (8, 3)):
        a = project_point(p, frame_px)
        b = project_point_analytic(p)
        err = max(err, abs(a[0] - b[0]), abs(a[1] - b[1]))
    if verbose:
        print(f"[camera] 原点 → 渲染像素 ({px:.4f}, {py:.4f})，期望 ({S.ANCHOR[0]*W}, {S.ANCHOR[1]*H})；最大误差 {err:.2e} px")
    assert err < 1e-3, f"相机锚点偏差过大：{err}"
    return err


def set_direction(root_obj, d):
    """d 可以是 0..7 或 'E'/'SE'/...；按 dir_rotation_deg 绕 Z 旋转根物体。"""
    if isinstance(d, str):
        d = S.DIRS.index(d)
    root_obj.rotation_mode = "XYZ"
    root_obj.rotation_euler.z = math.radians(S.dir_rotation_deg(int(d)))
    bpy.context.view_layer.update()


# ================================================================ 材质
def toon_material(
    name: str,
    base_hex: str | None = None,
    ramp: list[str] | None = None,
    wash: float = WASH_AMOUNT,
    wash_scale: float = WASH_SCALE,
    wash_value: float = WASH_VALUE,
    edge: float = EDGE_AMOUNT,
    edge_power: float = EDGE_POWER,
    bias: float = 0.0,
    seed: float = 0.0,
):
    """自发光“假卡通”填色，不依赖灯光：

      d = dot(世界法线, KEY_LIGHT_DIR) + 晕染噪声 - 积墨(轮廓处压暗) + bias
      d → 常量 ColorRamp（SHADE_THRESHOLDS）→ 亮/中/暗三色 → × (1 ± 晕染明度) → Emission

    颜色默认取 shade_ramp(base_hex)；ramp 可直接给三档 hex（亮、中、暗），但必须都在调色板里
    （例如浓墨的 shade_ramp 越“暗”越浅，影妖改用 [重墨, 浓墨, 焦墨]）。
    节点里的颜色是线性值，Standard 显示变换后正好还原成 hex。"""
    cols = list(ramp) if ramp else S.shade_ramp(base_hex)
    assert len(cols) == 3
    m, nt = _new_node_material(name)
    m["toon_ramp"] = cols
    N, L = nt.nodes, nt.links

    geo = N.new("ShaderNodeNewGeometry")
    dot = N.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = Vector(S.KEY_LIGHT_DIR).normalized()
    L.new(geo.outputs["Normal"], dot.inputs[0])

    # 晕染：物体空间噪声，随模型一起转，不会在不同朝向间“游泳”
    tc = N.new("ShaderNodeTexCoord")
    noise = N.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = wash_scale
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.55
    noise.inputs["W"].default_value = seed
    L.new(tc.outputs["Object"], noise.inputs["Vector"])
    wash_off = N.new("ShaderNodeMath")
    wash_off.operation = "MULTIPLY_ADD"  # fac*wash - 0.5*wash
    wash_off.inputs[1].default_value = wash
    wash_off.inputs[2].default_value = -0.5 * wash + bias
    L.new(noise.outputs["Fac"], wash_off.inputs[0])

    # 积墨：Facing 越接近 1（越靠轮廓）越暗
    lw = N.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    powr = N.new("ShaderNodeMath")
    powr.operation = "POWER"
    powr.inputs[1].default_value = edge_power
    L.new(lw.outputs["Facing"], powr.inputs[0])
    edge_term = N.new("ShaderNodeMath")
    edge_term.operation = "MULTIPLY"
    edge_term.inputs[1].default_value = -edge
    L.new(powr.outputs["Value"], edge_term.inputs[0])

    add1 = N.new("ShaderNodeMath")
    add1.operation = "ADD"
    L.new(dot.outputs["Value"], add1.inputs[0])
    L.new(wash_off.outputs["Value"], add1.inputs[1])
    add2 = N.new("ShaderNodeMath")
    add2.operation = "ADD"
    L.new(add1.outputs["Value"], add2.inputs[0])
    L.new(edge_term.outputs["Value"], add2.inputs[1])

    cr_node = N.new("ShaderNodeValToRGB")
    cr = cr_node.color_ramp
    cr.interpolation = "CONSTANT"
    t_lit, t_mid = S.SHADE_THRESHOLDS
    cr.elements[0].position, cr.elements[0].color = 0.0, hex_lin(cols[2])
    cr.elements[1].position, cr.elements[1].color = t_lit, hex_lin(cols[0])
    e = cr.elements.new(t_mid)
    e.color = hex_lin(cols[1])
    L.new(add2.outputs["Value"], cr_node.inputs["Fac"])

    # 晕染明度：第二个噪声，幅度很小
    noise2 = N.new("ShaderNodeTexNoise")
    noise2.noise_dimensions = "4D"
    noise2.inputs["Scale"].default_value = wash_scale * 2.7
    noise2.inputs["Detail"].default_value = 2.0
    noise2.inputs["W"].default_value = seed + 11.0
    L.new(tc.outputs["Object"], noise2.inputs["Vector"])
    val = N.new("ShaderNodeMath")
    val.operation = "MULTIPLY_ADD"  # 1 + (fac-0.5)*wash_value
    val.inputs[1].default_value = wash_value
    val.inputs[2].default_value = 1.0 - 0.5 * wash_value
    L.new(noise2.outputs["Fac"], val.inputs[0])
    scale = N.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    L.new(cr_node.outputs["Color"], scale.inputs[0])
    L.new(val.outputs["Value"], sock(scale.inputs, "Scale"))

    emi = N.new("ShaderNodeEmission")
    emi.inputs["Strength"].default_value = 1.0
    out = N.new("ShaderNodeOutputMaterial")
    out.target = "CYCLES"
    L.new(scale.outputs["Vector"], emi.inputs["Color"])
    L.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def flat_material(name: str, hex_color: str):
    """单色自发光（眼睛墨点、灯笼盖等很小的部件，不需要三档）。"""
    m, nt = _new_node_material(name)
    m["toon_ramp"] = [hex_color] * 3
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = hex_lin(hex_color)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def emissive_material(name: str, hex_color: str, strength: float = 1.0):
    """发光部件（灯笼芯、妖眼）。用这个材质的物体由 add_object 自动设 pass_index=1，
    渲染时从同一个 EXR 的 IndexOB 通道得到发光遮罩。白天图里显示为 hex 原色（strength=1）。"""
    m, nt = _new_node_material(name)
    m["emissive"] = hex_color
    m["emit_strength"] = float(strength)
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = hex_lin(hex_color)
    emi.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def window_material(name: str, shell: bpy.types.Material, open_facing: float = 0.42):
    """灯笼纸壳：正对镜头的中心区域透明（露出里面的发光芯），边缘是朱砂三档。
    open_facing：Layer Weight Facing 小于此值的部分透明。"""
    m = shell.copy()
    m.name = name
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    emi_link = out.inputs["Surface"].links[0]
    emi_out = emi_link.from_socket
    nt.links.remove(emi_link)
    lw = N.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    tc = N.new("ShaderNodeTexCoord")
    noise = N.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    L.new(tc.outputs["Object"], noise.inputs["Vector"])
    jitter = N.new("ShaderNodeMath")
    jitter.operation = "MULTIPLY_ADD"
    jitter.inputs[1].default_value = 0.12
    jitter.inputs[2].default_value = -0.06
    L.new(noise.outputs["Fac"], jitter.inputs[0])
    f = N.new("ShaderNodeMath")
    f.operation = "ADD"
    L.new(lw.outputs["Facing"], f.inputs[0])
    L.new(jitter.outputs["Value"], f.inputs[1])
    gt = N.new("ShaderNodeMath")
    gt.operation = "GREATER_THAN"
    gt.inputs[1].default_value = open_facing
    L.new(f.outputs["Value"], gt.inputs[0])
    tr = N.new("ShaderNodeBsdfTransparent")
    mix = N.new("ShaderNodeMixShader")
    L.new(gt.outputs["Value"], mix.inputs["Fac"])
    L.new(tr.outputs["BSDF"], mix.inputs[1])
    L.new(emi_out, mix.inputs[2])
    L.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


# ================================================================ 物体
def add_object(ob, line: str = "outer", parent=None):
    """把物体放进对应线宽的集合（outer 粗线 / inner 细线 / none 不描线），
    用发光材质的物体自动设 pass_index=1。"""
    coll = bpy.data.collections[LINE_COLLECTIONS[line]]
    coll.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    mats = getattr(getattr(ob, "data", None), "materials", None)
    if mats and any(m is not None and "emissive" in m for m in mats):
        ob.pass_index = 1
    return ob


def mesh_object(name, build, mat, line="outer", parent=None, loc=(0, 0, 0), rot=(0, 0, 0),
                scale=(1, 1, 1), smooth=True, sharp_deg=40.0):
    """用 bmesh 建网格物体。build(bm) 往 bm 里加几何；mat 可以是材质或材质列表。"""
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
    for m in mat if isinstance(mat, (list, tuple)) else [mat]:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.rotation_euler, ob.scale = loc, rot, scale
    add_object(ob, line, parent)
    return ob


def empty(name, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.05
    ob.location, ob.rotation_euler = loc, rot
    add_object(ob, "none", parent)
    return ob


def face_count(root) -> int:
    n = 0
    for ob in [root, *root.children_recursive]:
        if ob.type == "MESH":
            n += len(ob.data.polygons)
    return n


# ================================================================ Freestyle 墨线
def _linestyle(name: str, width_px: float, seed: int):
    """一种笔触：书法粗细 + 粗细噪声 + 沿笔画收笔，几何上重采样 + 柏林噪声抖动。单位为渲染像素。"""
    rs = S.RENDER_SCALE
    w = width_px * rs
    st = bpy.data.linestyles.get(name) or bpy.data.linestyles.new(name)
    st.color = S.hex_to_linear(S.LINE_COLOR)
    st.alpha = 1.0
    st.thickness = w
    st.thickness_position = "CENTER"
    st.caps = "ROUND"
    st.chaining = "PLAIN"
    st.use_chaining = True
    st.use_same_object = True
    st.use_angle_min = True  # 在急转角处断笔，每段各自收笔，更像一笔一笔画出来的
    st.angle_min = math.radians(SPLIT_ANGLE_DEG)
    st.use_length_min = True  # 太短的碎线不画
    st.length_min = 1.2 * rs
    for mods in (st.thickness_modifiers, st.geometry_modifiers, st.color_modifiers, st.alpha_modifiers):
        for mo in list(mods):
            mods.remove(mo)

    g = st.geometry_modifiers
    samp = g.new(name="Sampling", type="SAMPLING")
    samp.sampling = SAMPLING_PX * rs
    stretch = g.new(name="Overshoot", type="BACKBONE_STRETCHER")  # 起笔/收笔略出头
    stretch.backbone_length = 0.6 * rs
    pn = g.new(name="Wobble", type="PERLIN_NOISE_1D")
    pn.frequency = 1.0 / (S.LINE_NOISE_PERIOD_PX * rs)
    pn.amplitude = S.LINE_NOISE_AMPLITUDE_PX * rs
    pn.octaves = 2
    pn.angle = math.radians(45)
    pn.seed = S.LINE_NOISE_SEED + seed

    t = st.thickness_modifiers
    cal = t.new(name="Calligraphy", type="CALLIGRAPHY")  # 45° 方向最粗，像斜握的毛笔
    cal.blend = "MIX"
    cal.orientation = math.radians(45)
    cal.thickness_min = 0.5 * w
    cal.thickness_max = 1.1 * w
    nz = t.new(name="Pressure", type="NOISE")  # 行笔压力起伏
    nz.blend = "ADD"
    nz.amplitude = 0.3 * w
    # 实测：这里的 period 不是像素（period≈50 时是逐点锯齿），1500 左右才是一笔里缓慢的轻重变化
    nz.period = PRESSURE_PERIOD
    nz.seed = S.LINE_NOISE_SEED + seed
    nz.use_asymmetric = False
    taper = t.new(name="Taper", type="ALONG_STROKE")  # 两端收笔到 LINE_TAPER
    taper.blend = "MULTIPLY"
    taper.mapping = "CURVE"
    taper.value_min, taper.value_max = 0.0, 1.0
    cm = taper.curve
    pts = cm.curves[0].points
    pts[0].location, pts[1].location = (0.0, S.LINE_TAPER), (1.0, S.LINE_TAPER)
    pts.new(0.18, 1.0)
    pts.new(0.75, 1.0)
    cm.update()
    return st


def setup_freestyle(view_layer=None):
    """两档墨线，作为渲染通道输出（不经合成器）：
      外线 LINE_OUTER_PX：剪影 + 边界 + 外轮廓（InkOuter 集合里的大形体）
      内线 LINE_INNER_PX：折痕 + 材质分界（所有描线物体）；以及 InkInner 集合里小部件的剪影/边界
      InkNone 集合（眼睛墨点、发光芯等）不描线。"""
    sc = bpy.context.scene
    r = sc.render
    r.use_freestyle = True
    r.line_thickness_mode = "ABSOLUTE"
    r.line_thickness = 1.0
    vl = view_layer or sc.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.mode = "EDITOR"
    fs.as_render_pass = True
    fs.crease_angle = math.radians(CREASE_ANGLE_DEG)
    fs.use_smoothness = True
    fs.use_culling = False
    fs.use_material_boundaries = True
    for ls in list(fs.linesets):
        fs.linesets.remove(ls)
    outer_style = _linestyle("InkOuter", S.LINE_OUTER_PX, 0)
    inner_style = _linestyle("InkInner", S.LINE_INNER_PX, 3)
    colls = {k: bpy.data.collections[v] for k, v in LINE_COLLECTIONS.items()}

    def lineset(name, style, types, coll, negation="INCLUSIVE"):
        ls = fs.linesets.new(name)
        ls.select_by_visibility = True
        ls.visibility = "VISIBLE"
        ls.select_by_edge_types = True
        ls.edge_type_negation = "INCLUSIVE"
        ls.edge_type_combination = "OR"
        for a in ("silhouette", "border", "crease", "external_contour", "contour",
                  "suggestive_contour", "ridge_valley", "material_boundary", "edge_mark"):
            setattr(ls, "select_" + a, a in types)
        ls.select_by_collection = True
        ls.collection = coll
        ls.collection_negation = negation
        ls.linestyle = style
        return ls

    lineset("Outer", outer_style, ("silhouette", "border", "external_contour"), colls["outer"])
    lineset("InnerCrease", inner_style, ("crease", "material_boundary"), colls["none"], "EXCLUSIVE")
    lineset("InnerDetail", inner_style, ("silhouette", "border", "external_contour"), colls["inner"])
    return vl


# ================================================================ 渲染与读取
def read_exr_none(path):
    """极简 OpenEXR 读取器（同 smoke_test.py）：只支持无压缩扫描线，单 part 或多 part。
    返回 {通道名: float32 (H, W)}，行序从上到下。"""
    b = Path(path).read_bytes()
    magic, ver = struct.unpack_from("<II", b, 0)
    assert magic == 20000630, "不是 EXR 文件"
    assert not ver & 0x200, "不支持 tiled EXR"
    multipart = bool(ver & 0x1000)
    pos, headers = 8, []
    while True:
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
        if b[pos] == 0:
            pos += 1
            break
    parts, out = [], {}
    for h in headers:
        assert h["compression"][1] == b"\0", "只支持 exr_codec='NONE'"
        cl, p, chans = h["channels"][1], 0, []
        while cl[p] != 0:
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
    for *_, n in parts:
        tables.append(np.frombuffer(b, "<u8", n, pos)); pos += 8 * n
    for pi, (chans, W, H, y0, _) in enumerate(parts):
        for o in tables[pi]:
            o = int(o) + (4 if multipart else 0)
            y, _size = struct.unpack_from("<ii", b, o); o += 8
            for c, dt in chans:
                out[c][y - y0] = np.frombuffer(b, dt, W, o); o += W * np.dtype(dt).itemsize
    return out


def _rgba(ch, prefix):
    return np.stack([ch[f"{prefix}.{c}"] for c in "RGBA"], -1).astype(np.float32)


def render_layers(out_prefix, keep_exr: bool = False) -> dict:
    """一次渲染得到三层（全是 numpy float32，分辨率 = 渲染分辨率，行序从上到下）：
      fill  (H,W,4) 填色，预乘 alpha 的线性 RGB
      lines (H,W,4) Freestyle 墨线，预乘 alpha 的线性 RGB
      emit  (H,W)   发光遮罩：IndexOB == 1 的像素（0/1）
    另有 time_s、exr（路径，keep_exr=True 时保留文件）。"""
    sc = bpy.context.scene
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    im = sc.render.image_settings
    im.media_type = "MULTI_LAYER_IMAGE"  # 5.x：先设媒体类型，格式自动变成多层 EXR
    if im.file_format != "OPEN_EXR_MULTILAYER":
        im.file_format = "OPEN_EXR_MULTILAYER"
    im.exr_codec = "NONE"
    im.color_depth = "32"
    im.color_mode = "RGBA"
    vl = sc.view_layers[0]
    vl.use_pass_object_index = True
    vl.use_pass_z = True
    exr = out_prefix.with_suffix(".exr")
    sc.render.filepath = str(exr)
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    dt = time.perf_counter() - t0
    ch = read_exr_none(exr)
    vname = vl.name
    res = {"time_s": dt, "exr": str(exr)}
    res["fill"] = _rgba(ch, f"{vname}.Combined")
    if f"{vname}.Freestyle.A" in ch:
        res["lines"] = _rgba(ch, f"{vname}.Freestyle")
    else:
        res["lines"] = np.zeros_like(res["fill"])
    # 5.x 的通道名是 "ViewLayer.Object Index.X"（旧版叫 IndexOB）
    idx_key = next((k for k in ch if k.startswith((f"{vname}.Object Index", f"{vname}.IndexOB"))), None)
    idx = ch[idx_key] if idx_key else np.zeros(res["fill"].shape[:2], np.float32)
    res["index"] = idx
    res["emit"] = (np.abs(idx - 1.0) < 0.5).astype(np.float32)
    if not keep_exr:
        exr.unlink(missing_ok=True)
        res["exr"] = None
    return res


@contextlib.contextmanager
def render_lock(path: Path = LOCK_PATH):
    """多个代理同时出图时串行化最终渲染（fcntl 文件锁，进程退出自动释放）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        t0 = time.perf_counter()
        fcntl.flock(f, fcntl.LOCK_EX)
        waited = time.perf_counter() - t0
        if waited > 0.5:
            print(f"[lock] 等待渲染锁 {waited:.1f}s")
        try:
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()}\n")
            f.flush()
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ================================================================ 几何小工具（bmesh）
def lathe(profile, segments=32, radial=None, scale_y=1.0, cap_top=True, cap_bottom=True):
    """旋转体：profile = [(r, z), ...] 自下而上。radial(theta, z) → 半径倍数（做褶皱、竹篾棱）。
    返回 build(bm) 函数。r=0 的端点合并成一个顶点。"""

    def build(bm):
        rings = []
        for r, z in profile:
            if r <= 1e-6:
                rings.append([bm.verts.new((0.0, 0.0, z))])
                continue
            ring = []
            for i in range(segments):
                th = 2 * math.pi * i / segments
                k = radial(th, z) if radial else 1.0
                ring.append(bm.verts.new((r * k * math.cos(th), r * k * math.sin(th) * scale_y, z)))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                for i in range(segments):
                    bm.faces.new((a[0], b[i], b[(i + 1) % segments]))
            elif len(b) == 1:
                for i in range(segments):
                    bm.faces.new((a[(i + 1) % segments], a[i], b[0]))
            else:
                for i in range(segments):
                    bm.faces.new((a[i], a[(i + 1) % segments], b[(i + 1) % segments], b[i]))
        if cap_bottom and len(rings[0]) > 1:
            bm.faces.new(list(reversed(rings[0])))
        if cap_top and len(rings[-1]) > 1:
            bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def sweep(path, width, thick, ups=None, width_fn=None):
    """带状物（围巾、腰带尾、领口）：沿 path 扫一个 width×thick 的矩形截面，两端封口。
    ups：每个点的“厚度方向”（默认 +Z 与切线叉乘）。width_fn(t) → 宽度倍数。"""
    pts = [Vector(p) for p in path]

    def build(bm):
        n = len(pts)
        rings = []
        for i, p in enumerate(pts):
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            up = Vector(ups[i]).normalized() if ups else Vector((0, 0, 1))
            side = tan.cross(up)
            if side.length < 1e-6:
                side = tan.cross(Vector((1, 0, 0)))
            side.normalize()
            nrm = side.cross(tan).normalized()
            wv = width * (width_fn(i / (n - 1)) if width_fn else 1.0) / 2
            tv = thick / 2
            rings.append([bm.verts.new(p + side * sx * wv + nrm * sy * tv)
                          for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        for a, b in zip(rings, rings[1:]):
            for k in range(4):
                bm.faces.new((a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def uv_sphere(r, u=24, v=12, scale=(1, 1, 1)):
    def build(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
        bmesh.ops.scale(bm, vec=scale, verts=bm.verts)

    return build


def cylinder(r1, r2, depth, seg=16):
    def build(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                              radius1=r1, radius2=r2, depth=depth)

    return build


def aim(ob, a, b):
    """把沿局部 Z 建的物体放到 a→b 线段上（位置取中点）。"""
    a, b = Vector(a), Vector(b)
    d = b - a
    ob.location = (a + b) / 2
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    return ob
