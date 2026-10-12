"""影妖 / 疾影：墨烟幽灵（同一个构造器，参数不同）。

造型：带兜帽的裹尸布 / 水滴形身体（帽尖向后挑，前额的兜帽檐略向前探），兜帽口是参差的淡墨布边，
里面是焦墨的空洞和两只斜挑的发光眼（emissive）。身体下部收细，化成 2~4 缕向后下方拖的墨烟，
烟缕是淡墨，越到尖端越透明（顶点属性 fade 驱动材质透明度），烟缕不描线。
身体：浓墨芯，轮廓处化成重墨 / 淡墨（ghost_material）。

约定：锚点（原点）是它正下方的地面点；建模面朝 -Y，悬浮。妖物只渲染 "E"，游戏里镜像得到西；
正侧面时脸会转开，所以脸（兜帽口 + 眼）朝镜头偏转 look_deg，E 向画面里两只眼都看得见。
挂点：eyes（两眼之间）、feet（原点）。帧尺寸 FRAME["small"]（80px）。

    root, parts, sockets = build_shade()      # 影妖：碰撞半径 13 单位，身体宽约 1 米
    root, parts, sockets = build_wisp()       # 疾影：碰撞半径 10 单位，更小更细长，烟缕更长更透
    pose_ghost(parts, "float", i, n)          # 上下浮动 + 烟缕摆动（每帧重建烟缕网格）
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402


@dataclass
class GhostSpec:
    name: str = "Shade"
    eye: str = S.EYE["shade"]
    scale: float = 1.0  # 整体缩放（相对影妖）
    float_z: float = 0.34  # 身体最低处离地
    top_z: float = 1.30  # 帽尖
    body_r: float = 0.47  # 最宽处半径
    stretch_y: float = 1.0  # 前后拉长（疾影 >1）
    lean_deg: float = 0.0  # 向前倾（疾影向前冲）
    look_deg: float = 42.0
    # 烟缕：(根部角度 deg（0=正后方，正值偏左 +X）, 长度 m, 根半径 m, 下垂 m, 相位)
    # 80px 帧里锚点两侧各只有 0.8 米，烟缕向后不能超过约 0.74 米（身体后拖 + 烟缕长度）
    tails: list = field(default_factory=lambda: [(-34, 0.42, 0.10, 0.26, 0.0), (6, 0.50, 0.11, 0.34, 1.7),
                                                 (40, 0.36, 0.09, 0.16, 3.1)])
    tail_fade_start: float = 0.12
    tail_noise: float = 0.6
    tail_ramp: tuple = (S.INK["dan"], S.mix(S.INK["dan"], S.INK["zhong"], 0.28), S.mix(S.INK["dan"], S.INK["zhong"], 0.55))
    bob_m: float = 0.03
    forward_m: float = 0.06  # 身体整体前移，让视觉重心落在锚点（碰撞圆心）上，烟缕往后才不出框
    seed: int = 3


SHADE = GhostSpec()
WISP = GhostSpec(name="Wisp", eye=S.EYE["wisp"], scale=0.77, float_z=0.36, top_z=1.12, body_r=0.36,
                 stretch_y=1.5, lean_deg=26.0, look_deg=50.0,
                 tails=[(-18, 0.48, 0.075, 0.10, 0.0), (4, 0.56, 0.085, 0.16, 1.4), (24, 0.44, 0.07, 0.04, 2.6),
                        (10, 0.36, 0.055, 0.24, 4.0)],
                 tail_fade_start=0.0, tail_noise=0.75, tail_ramp=(S.INK["qing"], S.mix(S.INK["qing"], S.INK["zhong"], 0.28),
                                                  S.mix(S.INK["qing"], S.INK["zhong"], 0.55)),
                 bob_m=0.022, forward_m=0.22, seed=11)


# ================================================================ 材质
def ghost_material(name="GhostBody", seed=0.0, rim1=0.42, rim2=0.85, low_from=(0.80, 0.34)):
    """浓墨身体，轮廓处和下摆化成重墨→淡墨（鬼魅的边缘是化开的，与主角的“积墨”相反）。
    做法：假卡通三档（重/浓/焦）之上，按 (Facing^p + 噪声 + 下摆渐变) 的阈值换成淡墨、再往外换成清墨。"""
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
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sep.inputs[0])
    low = N.new("ShaderNodeMapRange")  # 下摆渐变：物体坐标 z 越低越“化”
    low.inputs["From Min"].default_value = low_from[0]
    low.inputs["From Max"].default_value = low_from[1]
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

    c1 = mix(step(rim1), col_src, I["dan"])
    c2 = mix(step(rim2), c1, I["qing"])
    L.new(c2, emi.inputs["Color"])
    m["toon_ramp"] = [I["zhong"], I["nong"], I["jiao"], I["dan"], I["qing"]]
    return m


# ================================================================ 几何
def _body_build(g: GhostSpec, segs=40):
    """水滴形裹尸布：帽尖在上、向后挑；前额兜帽檐略向前探；最宽处在胸口；向下收细并向后拖；
    最下一圈按角度起伏成长短不一的“舌头”（破碎的下摆），烟缕从这里接出去。坐标已含 scale。"""
    k = g.scale
    rng = np.random.default_rng(g.seed)
    top, fz, R = g.top_z * k, g.float_z * k, g.body_r * k
    H = top - fz
    # (r 相对 R, z 相对：0=底 1=顶)
    prof = [(0.00, 1.00), (0.16, 0.95), (0.42, 0.87), (0.70, 0.76), (0.90, 0.65), (1.00, 0.55), (0.93, 0.44),
            (0.74, 0.33), (0.52, 0.23), (0.34, 0.14), (0.22, 0.07)]
    ph = rng.uniform(0, 2 * math.pi, 3)
    n_tongue = 7
    amp = rng.uniform(0.5, 1.0, n_tongue)

    def tongue(th):
        kk = (math.cos(n_tongue * th + ph[0]) * 0.5 + 0.5) ** 2.5
        idx = int(((th + ph[0] / n_tongue) % (2 * math.pi)) / (2 * math.pi) * n_tongue) % n_tongue
        return kk * amp[idx]

    def trail(zr):  # 下半身往后拖（+Y）
        t = max(0.0, (0.6 - zr) / 0.6)
        return 0.25 * k * t * t

    def hood(zr):  # 帽尖往后上方挑，像倒过来的水滴尖
        return max(0.0, (zr - 0.70) / 0.30) ** 1.8 * 0.36 * k

    def cowl(th, zr):  # 前额兜帽檐（-Y 方向）向前探
        front = max(0.0, -math.sin(th)) ** 3
        bump = math.exp(-((zr - 0.80) / 0.07) ** 2)
        return 1 + 0.16 * front * bump

    def build(bm):
        rings = []
        for rr, zr in prof:
            z = fz + zr * H
            if rr == 0:
                rings.append([bm.verts.new((0, hood(zr) * g.stretch_y, z))])
                continue
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                wob = 1 + 0.05 * math.sin(3 * th + ph[1]) * (1 - zr)
                r = rr * R * wob * cowl(th, zr)
                y = r * math.sin(th) * 0.86 * g.stretch_y + (trail(zr) + hood(zr)) * g.stretch_y
                ring.append(bm.verts.new((r * math.cos(th), y, z)))
            rings.append(ring)
        for lvl in range(2):  # 破碎下摆：两圈，按角度往下拉长、往里收尖
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                tg = tongue(th)
                r = 0.22 * R * ((0.85 if lvl == 0 else 0.45) + 0.25 * tg)
                z = fz + (0.02 * H if lvl == 0 else -0.10 * H * tg)
                y = r * math.sin(th) * 0.86 * g.stretch_y + trail(0.0) * g.stretch_y + 0.05 * k * tg * lvl
                ring.append(bm.verts.new((r * math.cos(th), y, z)))
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


def _ragged_ring_build(r_in, r_out, seed, n=20, thick=0.02):
    """兜帽口的参差布边：XZ 平面里的一圈（面朝 -Y），内外边缘半径都随机起伏。"""
    rng = np.random.default_rng(seed)
    ji = rng.uniform(0.86, 1.10, n)
    jo = rng.uniform(0.90, 1.22, n)

    def build(bm):
        inner, outer, inner_b, outer_b = [], [], [], []
        for i in range(n):
            th = 2 * math.pi * i / n
            c, s = math.cos(th), math.sin(th)
            pi = Vector((r_in[0] * ji[i] * c, 0.0, r_in[1] * ji[i] * s))
            po = Vector((r_out[0] * jo[i] * c, 0.0, r_out[1] * jo[i] * s))
            inner.append(bm.verts.new(pi + Vector((0, -thick / 2, 0))))
            outer.append(bm.verts.new(po + Vector((0, -thick / 2 + 0.02, 0))))
            inner_b.append(bm.verts.new(pi + Vector((0, thick / 2, 0))))
            outer_b.append(bm.verts.new(po + Vector((0, thick / 2 + 0.02, 0))))
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((inner[i], outer[i], outer[j], inner[j]))
            bm.faces.new((inner_b[j], outer_b[j], outer_b[i], inner_b[i]))
            bm.faces.new((outer[j], outer[i], outer_b[i], outer_b[j]))
            bm.faces.new((inner[i], inner[j], inner_b[j], inner_b[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _tail_points(g: GhostSpec, tail, phase, n=12):
    """一缕烟的中心线（身体坐标）：从下摆后方出发，向后、向下、略向一侧飘，带行进的波。"""
    ang, length, r0, drop, tph = tail
    k = g.scale
    a = math.radians(ang)
    root = Vector((0.08 * k * math.sin(a), 0.22 * k * g.stretch_y, (g.float_z + 0.08) * k))
    back = Vector((math.sin(a) * 0.55, math.cos(a), 0.0)).normalized()
    side = Vector((0, 0, 1)).cross(back).normalized()
    pts = []
    L = length * k
    for i in range(n):
        t = i / (n - 1)
        s = L * t
        p = root + back * s * g.stretch_y ** 0.5
        p.z -= drop * k * t ** 1.5
        w = math.sin(2 * math.pi * 1.3 * t - phase - tph)
        p += side * (0.09 * k * t * w) + Vector((0, 0, 0.05 * k * t * math.cos(2 * math.pi * 0.9 * t - phase - tph)))
        pts.append(p)
    return pts


def _tail_build(pts, r0, segs=8):
    """烟缕：圆管，半径从 r0 收到 0；顶点顺序 = 逐圈，fade 属性 = 沿长度 0→1（尖端是一个点）。"""
    n = len(pts)
    fades = []

    def build(bm):
        rings = []
        for i, p in enumerate(pts):
            t = i / (n - 1)
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            u = tan.cross(Vector((0, 0, 1)))
            u = u.normalized() if u.length > 1e-4 else Vector((1, 0, 0))
            v = tan.cross(u).normalized()
            if i == n - 1:
                rings.append([bm.verts.new(p)])
                fades.append(1.0)
                continue
            r = r0 * (1 - t) ** 0.7 * (1 + 0.25 * math.sin(9 * t))
            ring = []
            for j in range(segs):
                th = 2 * math.pi * j / segs
                ring.append(bm.verts.new(p + u * math.cos(th) * r + v * math.sin(th) * r * 0.8))
                fades.append(t)
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            if len(b) == 1:
                for j in range(segs):
                    bm.faces.new((a[j], a[(j + 1) % segs], b[0]))
            else:
                for j in range(segs):
                    bm.faces.new((a[j], a[(j + 1) % segs], b[(j + 1) % segs], b[j]))
        bm.faces.new(list(reversed(rings[0])))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build, fades


def _set_tail_mesh(ob, g, tail, phase):
    build, fades = _tail_build(_tail_points(g, tail, phase), tail[2] * g.scale)
    if ob.data.vertices:
        old = ob.data
        me = bpy.data.meshes.new(old.name)
        bm = bmesh.new(); build(bm); bm.to_mesh(me); bm.free()
        me.shade_smooth()
        for m in old.materials:
            me.materials.append(m)
        ob.data = me
        if old.users == 0:
            bpy.data.meshes.remove(old)
    B.set_point_attr(ob, "fade", fades)


# ================================================================ 组装
def build_ghost(g: GhostSpec):
    I = S.INK
    k = g.scale
    root = B.empty(f"{g.name}Root")
    body = B.empty(f"{g.name}Body", root, loc=(0, -g.forward_m * g.scale, 0),
                   rot=(math.radians(-g.lean_deg), 0, 0))  # 前倾：头往 -Y
    parts = {"root": root, "body": body, "spec": g, "tails": []}
    m_body = ghost_material(f"{g.name}Body", seed=float(g.seed),
                            low_from=((g.float_z + 0.45) * k, g.float_z * k))
    m_hollow = B.flat_material(f"{g.name}Hollow", I["jiao"])
    m_rim = B.toon_material(f"{g.name}HoodRim", S.INK["dan"], edge=0.3, seed=float(g.seed) + 2)
    m_eye = B.emissive_material(f"{g.name}Eye", g.eye, 1.0)
    m_tail = B.smoke_material(f"{g.name}Smoke", list(g.tail_ramp), fade_start=g.tail_fade_start,
                              fade_power=1.1, noise_amt=g.tail_noise, seed=float(g.seed) + 5, edge=0.0, wash=0.25)

    B.mesh_object(f"{g.name}Main", _body_build(g), m_body, "outer", body, sharp_deg=0)

    # 兜帽口：焦墨空洞 + 参差的淡墨布边 + 两只眼；整体朝镜头偏转
    fz, H = g.float_z * k, (g.top_z - g.float_z) * k
    face_z = fz + 0.70 * H
    face = B.empty(f"{g.name}Face", body, loc=(0, 0, face_z), rot=(0, 0, math.radians(-g.look_deg)))
    parts["face"] = face
    fy = -0.80 * g.body_r * k * 0.86 * min(g.stretch_y, 1.15)
    B.mesh_object(f"{g.name}Hollow", B.uv_sphere(1.0, 20, 12, scale=(0.24 * k, 0.09 * k, 0.17 * k)), m_hollow,
                  "inner", face, loc=(0, fy + 0.02 * k, 0.0), rot=(math.radians(-12), 0, 0))
    B.mesh_object(f"{g.name}HoodRim", _ragged_ring_build((0.22 * k, 0.16 * k), (0.31 * k, 0.24 * k), g.seed + 1),
                  m_rim, "inner", face, loc=(0, fy - 0.045 * k, 0.012 * k), rot=(math.radians(-12), 0, 0))
    for sx in (-1, 1):
        B.mesh_object(f"{g.name}Eye{sx:+d}", B.uv_sphere(1.0, 12, 6, scale=(0.088 * k, 0.03 * k, 0.026 * k)), m_eye,
                      "none", face, loc=(0.095 * sx * k, fy - 0.075 * k, -0.005 * k),
                      rot=(math.radians(-12), math.radians(-20 * sx), 0))
    sock_eyes = B.empty(f"{g.name}SocketEyes", face, loc=(0, fy - 0.08 * k, -0.005 * k))

    for ti, tail in enumerate(g.tails):  # 烟缕：不描线，越到尖越透明
        ob = B.mesh_object(f"{g.name}Tail{ti}", _tail_build(_tail_points(g, tail, 0.0), tail[2] * k)[0], m_tail,
                           "none", body, sharp_deg=0)
        _set_tail_mesh(ob, g, tail, 0.0)
        parts["tails"].append((ob, tail))
    sockets = {"eyes": sock_eyes, "feet": B.empty(f"{g.name}SocketFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def build_shade(look_deg: float | None = None):
    g = SHADE if look_deg is None else GhostSpec(**{**SHADE.__dict__, "look_deg": look_deg})
    return build_ghost(g)


def build_wisp():
    return build_ghost(WISP)


def pose_ghost(parts: dict, anim: str, frame: int, n_frames: int):
    """float：整体上下浮动（一个循环一次），烟缕的波沿长度向后传（每帧重建烟缕网格），兜帽略点头。"""
    g: GhostSpec = parts["spec"]
    ph = 2 * math.pi * (frame % n_frames) / n_frames
    parts["body"].location.z = g.bob_m * g.scale * math.sin(ph)
    parts["body"].rotation_euler.x = math.radians(-g.lean_deg + 1.5 * math.sin(ph - 0.7))
    for ob, tail in parts["tails"]:
        _set_tail_mesh(ob, g, tail, ph)
    bpy.context.view_layer.update()


pose_shade = pose_ghost
