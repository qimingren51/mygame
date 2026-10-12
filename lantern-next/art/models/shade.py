"""影妖：带兜帽的墨色幽灵，水滴形身体，下摆是破碎的墨缕，悬浮在地面上方约 0.3 米。

约定：锚点（原点）是它正下方的地面点；建模面朝 -Y。身体宽约 1.0 米（游戏碰撞半径 13 单位 = 0.52 米）。
颜色：身体浓墨三档（重/浓/焦），轮廓与下摆晕开成淡墨；兜帽里是焦墨的空洞，两只斜挑的发光眼（EYE['shade']）。
妖物只渲染一个朝向 "E"（游戏里镜像得到西）。正侧面时脸会完全转开，所以头部可以朝镜头偏转 look_deg，
让 E 向的画面里两只眼都看得见。
挂点：eyes（两眼之间）、feet（原点）。帧尺寸 FRAME["small"]（80px）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402

FLOAT_Z = 0.30  # 墨缕最低点离地高度
TOP_Z = 1.30  # 兜帽尖
BODY_R = 0.50  # 最宽处半径（身体宽约 1.0 米）


def ghost_material(name="ShadeBody", seed=0.0):
    """浓墨身体，轮廓处和下摆晕成淡墨/清墨（与主角的“积墨”相反：鬼魅的边缘是化开的）。
    做法：在假卡通三档的基础上，按 (Facing^p + 噪声 + 下摆渐变) 的阈值换成淡墨、再往外换成清墨。"""
    I = S.INK
    m = B.toon_material(name, ramp=[I["zhong"], I["nong"], I["jiao"]], edge=0.0, wash=0.30, seed=seed)
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    emi = next(n for n in N if n.type == "EMISSION")
    col_link = emi.inputs["Color"].links[0]
    col_src = col_link.from_socket
    nt.links.remove(col_link)

    lw = N.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = 2.2
    L.new(lw.outputs["Facing"], pw.inputs[0])
    # 下摆渐变：物体坐标 z 越低越“化”
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sep.inputs[0])
    low = N.new("ShaderNodeMapRange")
    low.inputs["From Min"].default_value = 0.80
    low.inputs["From Max"].default_value = FLOAT_Z
    low.inputs["To Min"].default_value = 0.0
    low.inputs["To Max"].default_value = 0.75
    L.new(sep.outputs["Z"], low.inputs["Value"])
    noise = N.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 4.5
    noise.inputs["Detail"].default_value = 4.0
    noise.inputs["Roughness"].default_value = 0.65
    L.new(tc.outputs["Object"], noise.inputs["Vector"])
    nz = N.new("ShaderNodeMath"); nz.operation = "MULTIPLY_ADD"
    nz.inputs[1].default_value = 0.55; nz.inputs[2].default_value = -0.275
    L.new(noise.outputs["Fac"], nz.inputs[0])
    s1 = N.new("ShaderNodeMath"); s1.operation = "ADD"
    L.new(pw.outputs["Value"], s1.inputs[0]); L.new(low.outputs["Result"], s1.inputs[1])
    s2 = N.new("ShaderNodeMath"); s2.operation = "ADD"
    L.new(s1.outputs["Value"], s2.inputs[0]); L.new(nz.outputs["Value"], s2.inputs[1])

    def step(th):
        g = N.new("ShaderNodeMath"); g.operation = "GREATER_THAN"; g.inputs[1].default_value = th
        L.new(s2.outputs["Value"], g.inputs[0])
        return g

    def mix(fac, a_sock, b_hex):
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MIX"
        L.new(fac.outputs["Value"], B.sock(mx.inputs, "Factor_Float"))
        L.new(a_sock, B.sock(mx.inputs, "A_Color"))
        B.sock(mx.inputs, "B_Color").default_value = B.hex_lin(b_hex)
        return B.sock(mx.outputs, "Result_Color")

    c1 = mix(step(0.42), col_src, I["dan"])
    c2 = mix(step(0.85), c1, I["qing"])
    L.new(c2, emi.inputs["Color"])
    m["toon_ramp"] = [I["zhong"], I["nong"], I["jiao"], I["dan"], I["qing"]]
    return m


def _body_build(seed=3, segs=40):
    """水滴形身体：上部是兜帽圆顶，最宽处在胸口，向下收成墨缕；下半身向后（+Y）拖。
    最下一圈按角度起伏成 5~7 条长短不一的“舌头”，就是破碎的下摆。"""
    rng = np.random.default_rng(seed)
    prof = [(0.00, TOP_Z), (0.09, 1.25), (0.21, 1.15), (0.33, 1.04), (0.44, 0.93), (BODY_R, 0.82),
            (0.47, 0.71), (0.39, 0.61), (0.28, 0.52), (0.18, 0.45), (0.12, 0.41)]
    n_tongue = 6
    ph = rng.uniform(0, 2 * math.pi, 3)
    amp = rng.uniform(0.6, 1.0, n_tongue)

    def tongue(th):
        # 0..1，越大越长
        k = (math.cos(n_tongue * th + ph[0]) * 0.5 + 0.5) ** 2.5
        idx = int(((th + ph[0] / n_tongue) % (2 * math.pi)) / (2 * math.pi) * n_tongue) % n_tongue
        return k * amp[idx]

    def trail(z):  # 下半身往后拖
        t = max(0.0, (0.88 - z) / 0.58)
        return 0.42 * t * t

    def build(bm):
        rings = []
        for r, z in prof:
            if r == 0:  # 兜帽尖：往后挑
                rings.append([bm.verts.new((0, 0.24, z))])
                continue
            hood = max(0.0, (z - 0.95) / (TOP_Z - 0.95)) ** 1.5 * 0.22  # 越往上越向后弯
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                wob = 1 + 0.04 * math.sin(3 * th + ph[1]) * (1.2 - z)
                ring.append(bm.verts.new((r * wob * math.cos(th), r * wob * math.sin(th) * 0.88 + trail(z) + hood, z)))
            rings.append(ring)
        # 下摆的墨缕：两圈，按角度往下拉长、往里收尖
        for lvl, (rk, dz) in enumerate(((0.75, 0.0), (0.35, 0.0))):
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                tg = tongue(th)
                r = 0.15 * (rk + 0.35 * tg) * (1.0 if lvl == 0 else 0.6 + 0.4 * tg)
                z = 0.40 - (0.05 + 0.05 * lvl) - (0.10 if lvl == 0 else 0.0) * tg - (0.0 if lvl == 0 else 0.0)
                if lvl == 1:
                    z = FLOAT_Z + (1 - tg) * 0.10
                zz = z
                ring.append(bm.verts.new((r * math.cos(th), r * math.sin(th) * 0.88 + trail(zz) + 0.06 * tg * lvl, zz)))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1:
                for i in range(segs):
                    bm.faces.new((b[(i + 1) % segs], b[i], a[0]))
            else:
                for i in range(segs):
                    bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
        bm.faces.new(list(reversed(rings[-1])))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _wisp_build(length=0.42, r0=0.075):
    """袖子一样的墨缕（两侧各一条），沿局部 -Z 方向收尖、略弯。"""
    def build(bm):
        segs, n = 10, 7
        rings = []
        for j in range(n):
            t = j / (n - 1)
            r = r0 * (1 - t) ** 0.8 + 0.004
            c = Vector((0.0, 0.10 * t * t, -length * t))
            rings.append([bm.verts.new(c + Vector((r * math.cos(2 * math.pi * i / segs),
                                                   r * math.sin(2 * math.pi * i / segs), 0))) for i in range(segs)])
        for a, b in zip(rings, rings[1:]):
            for i in range(segs):
                bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def build_shade(look_deg: float = 42.0, seed: int = 3):
    """返回 (root, parts, sockets)。look_deg：头部朝镜头偏转的角度（建模坐标里绕 Z 转，
    E 向时正好转向镜头）。"""
    I = S.INK
    root = B.empty("ShadeRoot")
    body = B.empty("ShadeBody", root)
    parts = {"root": root, "body": body}
    m_body = ghost_material(seed=float(seed))
    m_hollow = B.flat_material("ShadeHollow", I["jiao"])
    m_eye = B.emissive_material("ShadeEye", S.EYE["shade"], 1.0)

    B.mesh_object("ShadeMain", _body_build(seed), m_body, "outer", body, sharp_deg=0)
    for sx in (-1, 1):
        w = B.mesh_object(f"ShadeWisp{sx:+d}", _wisp_build(), m_body, "outer", body,
                          loc=(0.40 * sx, 0.02, 0.82), rot=(math.radians(-10), math.radians(28 * sx), 0))
        parts[f"wisp_{sx:+d}"] = w

    # 兜帽开口 + 眼睛：放在一个可以朝镜头偏转的枢轴上
    face = B.empty("ShadeFace", body, loc=(0, 0, 0.90), rot=(0, 0, math.radians(-look_deg)))
    parts["face"] = face
    B.mesh_object("ShadeHollow", B.uv_sphere(1.0, 20, 12, scale=(0.25, 0.10, 0.19)), m_hollow, "inner", face,
                  loc=(0, -0.385, 0.0), rot=(math.radians(-14), 0, 0))
    for sx in (-1, 1):
        B.mesh_object(f"ShadeEye{sx:+d}", B.uv_sphere(1.0, 12, 6, scale=(0.088, 0.03, 0.027)), m_eye, "none", face,
                      loc=(0.10 * sx, -0.47, 0.005), rot=(math.radians(-12), math.radians(-20 * sx), 0))
    sock_eyes = B.empty("SocketEyes", face, loc=(0, -0.48, 0.005))
    sock_feet = B.empty("SocketFeet", root)
    sockets = {"eyes": sock_eyes, "feet": sock_feet}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_shade(parts: dict, anim: str, frame: int, n_frames: int):
    """idle/move：上下浮动 + 墨缕摆动（后续代理细化）。"""
    ph = 2 * math.pi * (frame % n_frames) / n_frames
    parts["body"].location.z = 0.025 * math.sin(ph)
    for sx in (-1, 1):
        w = parts[f"wisp_{sx:+d}"]
        w.rotation_euler.x = math.radians(-10 + 8 * math.sin(ph - 0.8))
    bpy.context.view_layer.update()
