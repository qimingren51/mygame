"""狐妖两种：赤面狐（精英，半立的狐妖，破袍、白色能面狐面具）和 夜主 · 九尾（首领，九尾巨狐）。

赤面狐：半直立前倾，穿淡彩朱砂的破袍（袖口、下摆参差），白色狐面具上有朱砂纹，眼睛 EYE['fox'] 从面具眼缝里透出；
  浓墨毛色的耳朵、腿和三条大尾巴（尾尖朱砂）。动画 move：8 帧潜行小跑。帧 FRAME["elite"]（160px）。
九尾：四足巨狐，着地潜行。楔形头骨 + 锥形吻部，白色面纹（吻、下颌、两颊，颊毛向后炸开）、黑鼻头、嘴线，
  杏仁细缝眼（藤黄发光、朱砂细边）、眼上朱砂火焰纹，宽底大三角耳（内耳白）；粗颈后飘鬃毛；
  深胸收腰，墨色由背到腹渐淡（浓墨背 → 淡墨侧 → 白色胸围和腹）；有关节的细腿（前腿腕、小爪，
  后腿粗大腿 → 细小腿 → 向后的跗关节 → 长跖骨），肘后、跗后各一簇毛；九条毛笔形尾巴在身后扇形展开
  （根部浓墨 → 淡墨 → 清墨 → 藤黄 → 朱砂尖）。动画 move：8 帧潜行，尾巴依次波动。帧 FRAME["boss"]（320px × 密度）。
两者都只渲染 E，身体朝镜头偏一点，眼睛/脸在 E 向读得出来。挂点：eyes、feet。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402


def _mats(prefix):
    I, A = S.INK, S.ACCENT
    return {
        "fur": K.toon(f"{prefix}Fur", I["nong"], edge=0.4, seed=51.0),
        "mask": K.toon(f"{prefix}Mask", ramp=[S.PAPER, I["qing"], I["dan"]], edge=0.35, seed=52.0),
        "red": K.toon(f"{prefix}Red", A["zhusha"], seed=53.0),
        "gold": K.toon(f"{prefix}Gold", A["tenghuang"], seed=54.0),
        "robe": K.toon(f"{prefix}Robe", S.WASH["zhusha"], seed=55.0, edge=0.4),
        "robe_dark": K.toon(f"{prefix}RobeTrim", I["nong"], seed=56.0),
        "ink": B.flat_material(f"{prefix}Ink", I["jiao"]),
    }


def _fox_head(prefix, parent, M, eye_mat, s=1.0, ear_h=0.30):
    """狐头：浓墨毛的头 + 白面具（额、眼、吻部）+ 朱砂眼纹 + 发光眼缝 + 两只尖耳。返回眼睛挂点。
    头坐标系：原点在头心，面朝 -Y。"""
    obj = B.mesh_object
    obj(f"{prefix}Skull", K.ellipsoid((0.15 * s, 0.15 * s, 0.14 * s)), M["fur"], "outer", parent)
    obj(f"{prefix}MaskFace", K.ellipsoid((0.135 * s, 0.10 * s, 0.13 * s)), M["mask"], "outer", parent,
        loc=(0, -0.075 * s, 0.01 * s))
    obj(f"{prefix}Snout", K.ellipsoid((0.075 * s, 0.17 * s, 0.07 * s)), M["mask"], "outer", parent,
        loc=(0, -0.20 * s, -0.045 * s), rot=(math.radians(-10), 0, 0))
    obj(f"{prefix}Nose", K.ellipsoid((0.025 * s, 0.02 * s, 0.018 * s)), M["ink"], "none", parent,
        loc=(0, -0.365 * s, -0.035 * s))
    for sx in (-1, 1):  # 朱砂眼纹（眼角上挑的一笔）+ 耳朵
        pts = [Vector((0.035 * sx * s, -0.168 * s, 0.035 * s)), Vector((0.08 * sx * s, -0.15 * s, 0.05 * s)),
               Vector((0.115 * sx * s, -0.11 * s, 0.085 * s))]
        obj(f"{prefix}Mark{sx:+d}", K.strip_build(pts, 0.022 * s, 0.006 * s, side_hint=Vector((0, 0, 1)),
                                                  taper=(1.0, 0.3)), M["red"], "none", parent)
        K.limb(f"{prefix}Ear{sx:+d}", (0.075 * sx * s, -0.01 * s, 0.10 * s),
               (0.11 * sx * s, 0.02 * s, (0.10 + ear_h) * s), 0.055 * s, 0.0, M["fur"], "outer", parent, segs=8)
    obj(f"{prefix}Brow", K.ellipsoid((0.022 * s, 0.01 * s, 0.022 * s), 10, 6), M["red"], "none", parent,
        loc=(0, -0.168 * s, 0.10 * s))  # 额心朱砂点
    return K.slit_eyes(prefix, parent, Vector((0, -0.172 * s, 0.035 * s)), 0.105 * s,
                       (0.034 * s, 0.012 * s, 0.011 * s), eye_mat, tilt_deg=22)


def _tail_points(root, d, length, phase, amp, curl=0.5, n=14):
    """尾巴中心线：从 root 沿 d 伸出，中段向上拱，尖端回卷；带相位波动。"""
    d = Vector(d).normalized()
    side = Vector((0, 0, 1)).cross(d)
    side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
    up = d.cross(side).normalized()
    pts = []
    for i in range(n):
        t = i / (n - 1)
        p = Vector(root) + d * (length * t) + up * (length * 0.22 * math.sin(math.pi * t))
        p += up * (-curl * length * 0.25 * max(0.0, t - 0.7) ** 2 / 0.09)
        p += side * (amp * t * t * math.sin(phase - 2.5 * t))
        pts.append(p)
    return pts


def _tail_zones(t):  # 尾尖朱砂，前面一圈藤黄
    return 2 if t > 0.84 else (1 if t > 0.77 else 0)


# ================================================================ 赤面狐
# (仰角：0=水平向后 90=竖直向上, 长度, 相位, 左右偏移)。E 向画面里展开成扇形，三条分得开
FOX_TAILS = [(15, 1.15, 0.0, 0.06), (48, 1.30, 1.1, -0.04), (80, 1.10, 2.2, 0.02)]


def build_fox():
    """赤面狐：半立的狐妖，穿层叠的狩衣（白色内衣 + 淡彩朱砂外袍，浓墨镶边的广袖），
    细长的趾行腿，三条大尾巴。"""
    from hero import _sleeve_build  # 主角的广袖构造器（下垂的袖兜 + 浓墨袖口）
    M = _mats("Fox")
    M["under"] = K.toon("FoxUnder", ramp=[S.PAPER, S.INK["qing"], S.INK["dan"]], seed=57.0)
    eye = B.emissive_material("FoxEye", S.EYE["fox"], 1.0)
    root = B.empty("FoxRoot")
    yaw = K.yaw_pivot("FoxYaw", root, -18)
    body = B.empty("FoxBody", yaw)
    parts = {"root": root, "body": body, "M": M, "tails": []}
    obj = B.mesh_object
    # 躯干（前倾 30°，细腰）+ 交领
    torso = B.empty("FoxTorso", body, loc=(0, 0.14, 1.00), rot=(math.radians(30), 0, 0))
    parts["torso"] = torso
    obj("FoxChest", B.lathe([(0.16, 0.0), (0.17, 0.20), (0.21, 0.45), (0.25, 0.62), (0.22, 0.70), (0.10, 0.76),
                             (0.0, 0.78)], 20, scale_y=0.72), M["robe"], "outer", torso, sharp_deg=0)
    for sx in (-1, 1):  # 白色交领：两道斜线在胸前交叉
        pts = [Vector((0.08 * sx, -0.10, 0.74)), Vector((0.02 * sx, -0.17, 0.60)), Vector((-0.07 * sx, -0.17, 0.42))]
        obj(f"FoxCollarV{sx:+d}", K.strip_build(pts, 0.05, 0.012, side_hint=Vector((1, 0, 0)), taper=(1.0, 0.8)),
            M["under"], "inner", torso)
    obj("FoxCollar", B.lathe([(0.09, 0.0), (0.12, 0.04), (0.09, 0.08)], 16), M["robe_dark"], "inner", torso,
        loc=(0, -0.02, 0.70))
    obj("FoxSash", B.lathe([(0.175, 0.0), (0.185, 0.05), (0.175, 0.10)], 20, scale_y=0.85), M["robe_dark"], "inner",
        torso, loc=(0, 0, 0.10))
    # 狩衣下摆：白色内衣长、外袍短，几片层叠飘动
    rags = []
    # 长度只到膝下，露出趾行的小腿和爪
    for i, (c, w, ln, mat, r, fl) in enumerate(((-90, 90, 0.60, "under", 0.16, 0.20), (90, 100, 0.62, "under", 0.16, 0.20),
                                                (0, 60, 0.58, "under", 0.16, 0.18), (180, 60, 0.58, "under", 0.16, 0.18),
                                                (-55, 75, 0.44, "robe", 0.19, 0.16), (-125, 75, 0.44, "robe", 0.19, 0.16),
                                                (55, 85, 0.47, "robe", 0.19, 0.16), (125, 85, 0.47, "robe", 0.19, 0.16))):
        ob = obj(f"FoxRag{i}", K.grid_build(K.rag_panel_rows(c, w, r, 1.00, ln, seed=i, tatter=0.10, flare=fl)),
                 M[mat], "outer", body, loc=(0, 0.14, 0), sharp_deg=0)
        rags.append((ob, c, w, i, ln, r, fl))
    parts["rags"] = rags
    head = B.empty("FoxHead", body, loc=(0, -0.58, 1.70), rot=(math.radians(-8), 0, math.radians(-25)))
    parts["head"] = head
    sock = _fox_head("FoxH", head, M, eye, s=1.35, ear_h=0.30)
    # 广袖（淡彩朱砂，浓墨袖口）+ 细长墨爪
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"FoxShoulder{nm}", body, loc=(0.18 * sx, -0.30, 1.42))
        A_ = Vector((0, 0, 0))
        cuff = Vector((0.07 * sx, -0.30, -0.30))
        obj(f"FoxSleeve{nm}", _sleeve_build(A_, cuff, [(0.0, 0.07), (0.4, 0.10), (1.0, 0.17)], 0.32),
            [M["robe"], M["robe_dark"], M["robe_dark"]], "outer", sh, sharp_deg=0)
        K.limb(f"FoxArm{nm}", cuff, cuff + Vector((-0.02 * sx, -0.20, -0.08)), 0.03, 0.022, M["fur"], "outer", sh)
        tipb = cuff + Vector((-0.02 * sx, -0.20, -0.08))
        for c in (-1, 0, 1):
            K.limb(f"FoxClaw{nm}{c}", tipb, tipb + Vector((0.022 * c, -0.09, -0.06)), 0.011, 0.0, M["ink"], "inner",
                   sh, segs=6)
        parts[f"arm_{nm}"] = sh
        # 后腿：趾行（大腿前下、小腿后下、跖骨前下，踮着脚尖）
        hip = B.empty(f"FoxHip{nm}", body, loc=(0.11 * sx, 0.18, 0.96))
        K.limb(f"FoxThigh{nm}", (0, 0, 0), (0.02 * sx, -0.22, -0.34), 0.075, 0.05, M["fur"], "outer", hip)
        knee = B.empty(f"FoxKnee{nm}", hip, loc=(0.02 * sx, -0.22, -0.34))
        K.limb(f"FoxShin{nm}", (0, 0, 0), (0, 0.24, -0.36), 0.045, 0.032, M["fur"], "outer", knee)
        K.limb(f"FoxFoot{nm}", (0, 0.24, -0.36), (0, 0.12, -0.58), 0.032, 0.026, M["fur"], "outer", knee)
        B.mesh_object(f"FoxPaw{nm}", K.ellipsoid((0.04, 0.075, 0.03)), M["fur"], "outer", knee, loc=(0, 0.08, -0.595))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    troot = Vector((0, 0.40, 1.00))
    for i, (ang, ln, tph, xo) in enumerate(FOX_TAILS):
        ob = obj(f"FoxTail{i}", K.tube_build(_fox_tail(troot, ang, ln, 0.0, tph, xo), K.bushy(0.12), 12, _tail_zones),
                 [M["fur"], M["gold"], M["red"]], "outer", body, sharp_deg=0)
        parts["tails"].append((ob, troot, ang, ln, tph, xo))
    sockets = {"eyes": sock, "feet": B.empty("FoxFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def _fox_tail(root, ang, ln, phase, tph, xo=0.0):
    a = math.radians(ang)
    d = Vector((xo, math.cos(a), math.sin(a)))
    return _tail_points(Vector(root) + Vector((xo, 0, 0)), d, ln, phase + tph, 0.05, curl=0.5)


# 扑击（pounce，6 帧不循环）：0–1 伏低蓄力（第 1 帧最低，游戏在预警期间停在这一帧），2–4 腾空扑出，5 落地。
# (身体抬高 m, 身体前后 m, 整体前倾 deg, 上身前倾 deg, 髋 deg, 膝 deg, 手臂 deg, 头俯仰 deg, 尾巴仰角倍数, 尾巴加角 deg, 风)
FOX_POUNCE = [
    (-0.10, 0.06, 6, 46, -22, 30, 34, 12, 1.00, 12, 0.15),
    (-0.20, 0.12, 10, 58, -34, 46, 48, 20, 1.00, 24, 0.20),  # 伏到底（预警）
    (0.16, -0.04, 30, 36, 30, -6, -72, -6, 0.45, -2, 0.70),  # 蹬地扑出：后腿蹬直，前爪前探
    (0.30, -0.10, 36, 32, 38, -2, -84, -10, 0.30, -6, 0.90),  # 最高、身体拉平
    (0.12, -0.06, 26, 38, 10, 10, -66, -4, 0.45, 0, 0.70),  # 下落
    (-0.12, 0.00, 10, 46, -26, 36, -40, 2, 0.85, 8, 0.30),  # 落地：前爪按地
]


def _rest_fox(parts):
    """每次摆姿态前把会被改动的变换复位（同一个会话里先渲 move 再渲 pounce，互不影响）。"""
    parts["body"].location = (0, 0, 0)
    parts["body"].rotation_euler = (0, 0, 0)
    parts["head"].rotation_euler = (math.radians(-8), 0, math.radians(-25))
    parts["head"].location = (0, -0.58, 1.70)


def pose_fox(parts, anim, frame, n):
    """move：潜行小跑——两腿交替（髋前后摆、膝随之屈伸），身体轻微起伏，前爪交替探出，尾巴波动，破袍飘。
    pounce：见 FOX_POUNCE。"""
    _rest_fox(parts)
    if anim == "pounce":
        return _pose_fox_pounce(parts, frame)
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.006 * math.cos(2 * ph)
    parts["torso"].rotation_euler.x = math.radians(30)
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-16 * s), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(16 * max(0.0, -s) + 4), 0, 0)
        parts[f"arm_{nm}"].rotation_euler = (math.radians(9 * s), 0, 0)
    M = parts["M"]
    for ob, troot, ang, ln, tph, xo in parts["tails"]:
        K.replace_mesh(ob, K.tube_build(_fox_tail(troot, ang, ln, ph, tph, xo), K.bushy(0.12), 12, _tail_zones))
    for ob, c, w, i, ln, r, fl in parts["rags"]:
        K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, r, 1.00, ln, phase=ph, wind=0.12, seed=i,
                                                         tatter=0.10, flare=fl)))
    bpy.context.view_layer.update()


def _pose_fox_pounce(parts, frame):
    z, dy, pitch, lean, hip, knee, arm, head, tk, ta, wind = FOX_POUNCE[frame % len(FOX_POUNCE)]
    ph = 2 * math.pi * frame / len(FOX_POUNCE)
    body = parts["body"]
    # 整体前倾绕髋（离地约 1 米处）转，不绕脚底转，头不会一下子甩出画面
    pivot = Vector((0, 0.18, 0.96))
    R = Matrix.Rotation(math.radians(pitch), 3, "X")
    body.rotation_euler = (math.radians(pitch), 0, 0)
    body.location = pivot - R @ pivot + Vector((0, dy, z))
    parts["torso"].rotation_euler.x = math.radians(lean)
    parts["head"].rotation_euler = (math.radians(-8 + head - pitch * 0.6), 0, math.radians(-25))  # 正角 = 低头
    low = max(0.0, lean - 30) / 28  # 上身越往前压，头跟着越低、越往前
    parts["head"].location = (0, -0.58 - 0.06 * low, 1.70 - 0.12 * low)
    for nm, sgn in (("L", 1), ("R", -1)):
        stag = 4 * sgn  # 两腿略错开，不叠成一条
        parts[f"hip_{nm}"].rotation_euler = (math.radians(hip + stag), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(knee + 4 - stag * 0.5), 0, 0)
        parts[f"arm_{nm}"].rotation_euler = (math.radians(arm + 6 * sgn), 0, 0)
    for ob, troot, ang, ln, tph, xo in parts["tails"]:
        K.replace_mesh(ob, K.tube_build(_fox_tail(troot, ang * tk + ta, ln, ph, tph, xo), K.bushy(0.12), 12, _tail_zones))
    for ob, c, w, i, ln, r, fl in parts["rags"]:
        K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, r, 1.00, ln, phase=ph, wind=wind, seed=i,
                                                         tatter=0.10, flare=fl)))
    bpy.context.view_layer.update()


# ================================================================ 九尾
BOSS_TAILS = 9
TAIL_BANDS = [(0.0, S.INK["nong"]), (0.34, S.INK["dan"]), (0.52, S.INK["qing"]),
              (0.64, S.ACCENT["tenghuang"]), (0.74, S.ACCENT["zhusha"])]  # 根部浓墨 → 淡墨 → 清墨 → 藤黄 → 朱砂尖
RUFF_BANDS = [(0.0, S.INK["nong"]), (0.55, S.INK["zhong"]), (0.80, S.INK["qing"])]


def _brush(t):
    """毛笔形尾巴的半径：根部较粗，前三成鼓起，再一路收成尖。"""
    if t >= 1.0:
        return 0.0
    swell = math.sin(math.pi / 2 * min(t / 0.30, 1.0))
    taper = (1 - max(0.0, t - 0.30) / 0.70) ** 1.15
    return 0.36 * (0.55 + 0.45 * swell) * taper


BODY_BANDS = [(0.0, S.INK["nong"]), (0.36, S.INK["dan"]), (0.74, S.PAPER)]  # 背浓墨 → 侧淡墨 → 胸腹白
HEAD_BANDS = [(0.0, S.INK["nong"]), (0.40, S.INK["dan"]), (0.56, S.PAPER)]  # 额浓墨 → 淡墨 → 白色面纹
LEG_BANDS = [(0.0, S.INK["dan"]), (0.22, S.INK["nong"])]  # 大臂/大腿接侧腹的淡墨，往下是浓墨“袜子”
HEAD_S = 1.3  # 头整体放大（风格化：游戏尺寸下先读出狐狸头）
BODY_SHIFT = 0.28  # 身体相对锚点沿 +Y（向后）的偏移，见 build_boss


def _ring_body_build(spine, attrs_out, segs=20):
    """沿脊线的椭圆截面体（躯干、颈、头）：spine = [(中心点, 横半径, 竖半径[, 偏移]), ...]。
    attrs_out 按顶点顺序填“由背到腹”的 0..1（截面里越靠下越大）再加该截面的偏移，
    给 *_BANDS 分段上色：偏移越大白色越往上漫（胸前白围、喉部、吻部）。两端收成圆头。"""
    pts = [Vector(e[0]) for e in spine]
    n = len(pts)

    def build(bm):
        rings = []
        for i, e in enumerate(spine):
            p, rx, rz = Vector(e[0]), e[1], e[2]
            bias = e[3] if len(e) > 3 else 0.0
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            side = tan.cross(Vector((0, 0, 1)))
            side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
            up = side.cross(tan).normalized()
            ring = []
            for j in range(segs):
                th = 2 * math.pi * j / segs
                ring.append(bm.verts.new(p + side * (math.cos(th) * rx) + up * (math.sin(th) * rz)))
                attrs_out.append(0.5 - 0.5 * math.sin(th) + bias)  # 顶 0，底 1
            rings.append(ring)
        for a_, b_ in zip(rings, rings[1:]):
            for j in range(segs):
                bm.faces.new((a_[j], a_[(j + 1) % segs], b_[(j + 1) % segs], b_[j]))
        for ring, e, ax, rev in ((rings[0], spine[0], pts[0] - pts[1], True),
                                 (rings[-1], spine[-1], pts[-1] - pts[-2], False)):
            c = sum((v.co for v in ring), Vector()) / segs
            cv = bm.verts.new(c + ax.normalized() * 0.55 * min(e[1], e[2]))
            attrs_out.append(0.5 + (e[3] if len(e) > 3 else 0.0))
            for j in range(segs):
                bm.faces.new((ring[(j + 1) % segs], ring[j], cv) if rev else (ring[j], ring[(j + 1) % segs], cv))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _cone_build(base, tip, r0, r1, flat=1.0, segs=12):
    """从 base 到 tip 的锥（下颌）；flat 压扁“竖向”截面。"""
    return K.tube_build(K.curve_points(base, tip, n=6), lambda t: r0 + (r1 - r0) * t, segs, flat=flat)


def _ear_build(base, tip, half_w, half_d, facing, segs=12):
    """宽底三角耳：底面是 半宽 half_w × 半厚 half_d 的扁椭圆，收到 tip 一点；facing 是耳孔朝向。"""
    base, tip = Vector(base), Vector(tip)
    ax = (tip - base).normalized()
    f = Vector(facing) - ax * Vector(facing).dot(ax)
    f.normalize()
    w = ax.cross(f).normalized()

    def build(bm):
        ring = [bm.verts.new(base + w * math.cos(2 * math.pi * j / segs) * half_w
                             + f * math.sin(2 * math.pi * j / segs) * half_d) for j in range(segs)]
        apex, bc = bm.verts.new(tip), bm.verts.new(base - ax * 0.01)
        for j in range(segs):
            bm.faces.new((ring[j], ring[(j + 1) % segs], apex))
            bm.faces.new((ring[(j + 1) % segs], ring[j], bc))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _bvh(ob):
    """网格物体（自身坐标）的 BVH，用来把眼睛、纹样贴到头的表面上。"""
    me = ob.data
    return BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(p.vertices) for p in me.polygons])


def _on_surface(tree, p, out_dir, lift=0.0):
    """从 p 外侧沿 -out_dir 打射线，返回 (表面点 + 法线 * lift, 法线)。"""
    d = Vector(out_dir).normalized()
    hit, nrm, _, _ = tree.ray_cast(Vector(p) + d * 0.8, -d)
    if hit is None:
        return Vector(p), d
    if nrm.dot(d) < 0:
        nrm = -nrm
    return hit + nrm * lift, nrm


def _frame_rot(axis_x, nrm):
    """以 nrm 为局部 Z、axis_x 投到切平面为局部 X 的旋转（欧拉角）。"""
    x = Vector(axis_x) - nrm * Vector(axis_x).dot(nrm)
    x.normalize()
    y = nrm.cross(x).normalized()
    return Matrix((x, y, nrm)).transposed().to_euler(), x, y


def _boss_head(prefix, parent, M, eye_mat, head_mat, s=HEAD_S):
    """真正的狐狸头（头坐标系：原点在头心，面朝 -Y，单位米 × s）。
    一体的楔形头骨 → 中等长度的锥形吻部（起点与两眼间距同宽，长约头骨高的 1.15 倍）；HEAD_BANDS 上色：
    额头浓墨、鼻梁淡墨，吻部、下颌、两颊白色（同一个材质，不画分界线）；黑鼻头、嘴线；
    两颊白毛向后炸开成三簇尖；杏仁细缝眼（EYE['boss'] 发光、朱砂细边）贴在额止两侧，眼上各一笔朱砂火焰纹；
    宽底大三角耳（底宽约为高的 0.6），微外撇，内耳白、带一簇白毛。返回眼睛挂点。"""
    obj = B.mesh_object

    def V(x, y, z):
        return Vector((x * s, y * s, z * s))

    spine = [((0, 0.26, 0.04), 0.09, 0.09, -0.06), ((0, 0.18, 0.04), 0.19, 0.18, 0.0),
             ((0, 0.06, 0.02), 0.24, 0.20, 0.12), ((0, -0.06, 0.0), 0.22, 0.18, 0.16),  # 颧部最宽，下半白
             ((0, -0.16, -0.03), 0.16, 0.14, 0.22),  # 额止：吻部从这里起，宽度约等于两眼间距
             ((0, -0.28, -0.06), 0.11, 0.105, 0.34), ((0, -0.40, -0.08), 0.085, 0.085, 0.38),
             ((0, -0.50, -0.095), 0.06, 0.065, 0.38), ((0, -0.58, -0.10), 0.035, 0.04, 0.38)]
    spine = [(tuple(V(*p)), rx * s, rz * s, b) for p, rx, rz, b in spine]
    shade: list = []
    skull = obj(f"{prefix}Skull", _ring_body_build(spine, shade, segs=24), head_mat, "outer", parent, sharp_deg=0)
    B.set_point_attr(skull, "fade", shade)
    tree = _bvh(skull)
    obj(f"{prefix}Jaw", _cone_build(V(0, -0.12, -0.13), V(0, -0.48, -0.15), 0.08 * s, 0.024 * s, flat=0.55),
        M["mask"], "outer", parent)
    obj(f"{prefix}Nose", K.ellipsoid((0.042 * s, 0.034 * s, 0.032 * s), 10, 6), M["ink"], "none", parent,
        loc=V(0, -0.605, -0.095))
    eyes = []
    for sx in (-1, 1):
        # 嘴线：从鼻下沿吻侧往后，到嘴角微微上挑
        mouth = [_on_surface(tree, V(0.03 * sx, y, z), (sx * 0.6, 0, -0.8), 0.006 * s)[0]
                 for y, z in ((-0.56, -0.12), (-0.44, -0.135), (-0.32, -0.125), (-0.22, -0.10))]
        obj(f"{prefix}Mouth{sx:+d}", K.strip_build(mouth, 0.016 * s, 0.006 * s, side_hint=Vector((0, 0, 1)),
                                                   taper=(0.6, 1.0)), M["ink"], "none", parent)
        # 两颊白毛：向后、向外炸开的三簇尖
        for k_, (tip, w_) in enumerate((((0.31, 0.30, 0.05), 0.12), ((0.33, 0.33, -0.07), 0.13),
                                        ((0.27, 0.29, -0.19), 0.11))):
            base = V(0.18 * sx, 0.07, -0.01 - 0.07 * k_)
            tp = V(tip[0] * sx, tip[1], tip[2])
            pts = K.curve_points(base, tp, bend=V(0.03 * sx, -0.03, 0.02), n=5)
            obj(f"{prefix}Ruff{sx:+d}{k_}", K.strip_build(pts, w_ * s, 0.03 * s, side_hint=Vector((0, -0.3, 1)),
                                                            taper=(1.0, 0.05)), M["mask"], "outer", parent)
        # 杏仁眼：贴在额止两侧的表面上；眼角由前下斜向后上
        loc, nrm = _on_surface(tree, V(0.12 * sx, -0.15, 0.05), (sx * 0.72, -0.55, 0.42))
        rot, ex, ey = _frame_rot(Vector((0, 1, 0.30)), nrm)
        obj(f"{prefix}EyeRim{sx:+d}", K.ellipsoid((0.090 * s, 0.027 * s, 0.010 * s), 16, 6), M["red"], "none", parent,
            loc=loc + nrm * 0.004 * s, rot=rot)
        obj(f"{prefix}Eye{sx:+d}", K.ellipsoid((0.076 * s, 0.016 * s, 0.010 * s), 16, 6), eye_mat, "none", parent,
            loc=loc + nrm * 0.011 * s, rot=rot)
        eyes.append(loc)
        # 眼上一笔朱砂火焰纹：从眼头上方起笔，向上、向后挑出
        up = ey if ey.z > 0 else -ey
        flame = [_on_surface(tree, loc + (up * dy + ex * dx) * s, nrm, 0.007 * s)[0]
                 for dx, dy in ((-0.03, 0.055), (-0.02, 0.09), (0.0, 0.125), (0.035, 0.155))]
        obj(f"{prefix}Flame{sx:+d}", K.strip_build(flame, 0.032 * s, 0.006 * s, side_hint=ex, taper=(1.0, 0.08)),
            M["red"], "none", parent)
        # 宽底大三角耳：高约 0.38，底宽约 0.23（≈0.6 倍高），微外撇；耳孔朝前偏外
        base, tip = V(0.12 * sx, 0.05, 0.14), V(0.23 * sx, 0.10, 0.60)  # 高约 0.47，底宽 0.28
        facing = Vector((0.55 * sx, -0.83, 0.0))
        obj(f"{prefix}Ear{sx:+d}", _ear_build(base, tip, 0.14 * s, 0.085 * s, facing), M["fur"], "outer", parent,
            sharp_deg=0)
        ax = (tip - base).normalized()
        f = (facing - ax * facing.dot(ax)).normalized()
        ib = base + ax * 0.05 * s + f * 0.06 * s
        obj(f"{prefix}EarIn{sx:+d}", _ear_build(ib, tip - ax * 0.11 * s + f * 0.02 * s, 0.09 * s, 0.035 * s, facing),
            M["mask"], "none", parent, sharp_deg=0)
        tuft = K.curve_points(ib + f * 0.01 * s, ib + f * 0.05 * s + ax * 0.16 * s + Vector((0.03 * sx * s, 0, 0)), n=5)
        obj(f"{prefix}EarTuft{sx:+d}", K.tube_build(tuft, lambda t: 0.028 * s * (1 - t) + 0.002, 6, flat=0.6),
            M["mask"], "none", parent)
    c = (eyes[0] + eyes[1]) / 2
    return B.empty(f"{prefix}SocketEyes", parent, loc=c)


def _leg_build(path, radii, fades=None):
    """有关节的锥形腿：沿关节点折线插值成管，半径逐段渐细（关节处可以略鼓）。fades 填沿腿的 0..1。"""
    pts, rr = [], []
    for (a_, ra), (b_, rb) in zip(zip(path, radii), zip(path[1:], radii[1:])):
        a_, b_ = Vector(a_), Vector(b_)
        for k in range(4):
            t = k / 4
            pts.append(a_.lerp(b_, t))
            rr.append(ra + (rb - ra) * t)
    pts.append(Vector(path[-1]))
    rr.append(radii[-1])
    n = len(pts)
    return K.tube_build(pts, lambda t: float(np.interp(t, np.linspace(0, 1, n), rr)), 12, fades=fades)


# 四肢（髋/肩坐标系，地面在 -髋高）：前腿 肩 → 肘（略后）→ 细前臂 → 腕 → 短掌 → 小爪；
# 后腿 粗大腿（髋部肌肉）→ 膝（向前）→ 细小腿 → 跗关节（向后）→ 长跖骨 → 小爪。
FRONT_HIP, HIND_HIP = (0.22, -0.58, 1.70), (0.25, 0.62, 1.86)
FRONT_LEG = ([(0, 0.0, 0.12), (0, 0.08, -0.50), (0, 0.04, -0.82), (0, -0.01, -1.36), (0, -0.08, -1.58)],
             [0.19, 0.10, 0.064, 0.058, 0.050])
HIND_LEG = ([(0, 0.04, 0.10), (0, -0.20, -0.78), (0, 0.03, -1.00), (0, 0.26, -1.22), (0, 0.15, -1.74)],
            [0.31, 0.12, 0.07, 0.064, 0.050])


def build_boss():
    I = S.INK
    M = _mats("Boss")
    eye = B.emissive_material("BossEye", S.EYE["boss"], 1.0)
    tail_mat = K.banded_toon_material("BossTailInk", TAIL_BANDS, edge=0.3, seed=58.0)
    ruff_mat = K.banded_toon_material("BossRuffInk", RUFF_BANDS, edge=0.3, seed=59.0)
    body_mat = K.banded_toon_material("BossBodyInk", BODY_BANDS, edge=0.3, noise_amt=0.12, seed=60.0)
    head_mat = K.banded_toon_material("BossHeadInk", HEAD_BANDS, edge=0.3, noise_amt=0.08, seed=61.0)
    leg_mat = K.banded_toon_material("BossLegInk", LEG_BANDS, edge=0.3, noise_amt=0.10, seed=62.0)
    paw_mat = K.toon("BossPaw", I["dan"], edge=0.35, seed=63.0)
    root = B.empty("BossRoot")
    yaw = K.yaw_pivot("BossYaw", root, -20)
    # 四爪着地潜行（不悬浮）。整个身体相对锚点后移 0.28 米：尾根回到原来的位置 (0, 1.28, 1.94)，
    # 九尾的扇面不伸进锚点正上方的“头顶”检查列，锚点落在前胸与腰之间
    body = B.empty("BossBody", yaw, loc=(0, BODY_SHIFT, 0))
    parts = {"root": root, "body": body, "M": M, "tails": [], "tail_mat": tail_mat}
    obj = B.mesh_object

    def ringed(name, spine, mat):
        shade: list = []
        ob = obj(name, _ring_body_build(spine, shade), mat, "outer", body, sharp_deg=0)
        B.set_point_attr(ob, "fade", shade)
        return ob

    # 躯干：深胸（胸前白围）、收腰（腹线向后腿抬起，白腹）、髋部再鼓起；第四项是白色往上漫的偏移
    ringed("BossTorso", [((0, -0.96, 1.86), 0.13, 0.15, 0.28), ((0, -0.84, 1.82), 0.30, 0.44, 0.28),
                         ((0, -0.58, 1.80), 0.36, 0.50, 0.16), ((0, -0.26, 1.85), 0.32, 0.41, 0.08),
                         ((0, 0.08, 1.93), 0.25, 0.27, 0.12), ((0, 0.38, 1.95), 0.27, 0.31, 0.06),
                         ((0, 0.66, 1.93), 0.32, 0.36, 0.0), ((0, 0.90, 1.92), 0.27, 0.30, 0.0),
                         ((0, 1.06, 1.92), 0.13, 0.15, 0.0)], body_mat)
    # 粗壮、微弓的颈，喉部白
    neck = [((0, -0.62, 2.00), 0.30, 0.36, 0.14), ((0, -0.88, 2.12), 0.27, 0.31, 0.26),
            ((0, -1.10, 2.16), 0.24, 0.27, 0.30), ((0, -1.28, 2.12), 0.20, 0.22, 0.30)]
    ringed("BossNeck", neck, body_mat)
    # 鬃毛：沿颈背向后飘，左右交错
    for i in range(10):
        f = i / 9
        y = -1.22 + 0.64 * f
        zc = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [2.12, 2.16, 2.12, 2.00]))
        rz = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [0.22, 0.27, 0.31, 0.36]))
        rx = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [0.20, 0.24, 0.27, 0.30]))
        a = math.radians(-60 + 120 * ((i * 0.618) % 1.0))
        base = Vector((0.55 * rx * math.sin(a), y, zc + 0.80 * rz * math.cos(a)))
        tip = base + Vector((0.22 * math.sin(a), 0.56, 0.08 - 0.10 * f))
        fades: list = []
        ob = obj(f"BossMane{i}", K.tube_build(K.curve_points(base, tip, bend=Vector((0, 0.0, 0.07)), n=7),
                                             K.bushy(0.075, peak=0.3), 8, flat=0.6, fades=fades), ruff_mat, "outer", body)
        B.set_point_attr(ob, "fade", fades)
    head = B.empty("BossHead", body, loc=(0, -1.44, 2.12), rot=(math.radians(6), 0, math.radians(-8)))
    parts["head"] = head
    sock = _boss_head("BossH", head, M, eye, head_mat)
    # 四肢；肘后、跗后各一簇毛；小椭圆爪 + 墨色趾缝
    legs = {}
    for nm, sx, front in (("FL", 1, True), ("FR", -1, True), ("HL", 1, False), ("HR", -1, False)):
        hx, hy, hz = FRONT_HIP if front else HIND_HIP
        hip = B.empty(f"BossHip{nm}", body, loc=(hx * sx, hy, hz))
        path, radii = FRONT_LEG if front else HIND_LEG
        fades: list = []
        leg = obj(f"BossLeg{nm}", _leg_build(path, radii, fades), leg_mat, "outer", hip, sharp_deg=0)
        B.set_point_attr(leg, "fade", fades)
        j = Vector(path[3])  # 腕 / 跗关节略鼓
        obj(f"BossJoint{nm}", K.ellipsoid((radii[3] * 1.12, radii[3] * 1.3, radii[3] * 1.2), 10, 6), M["fur"], "outer",
            hip, loc=j)
        tuft_at = Vector(path[1]) + Vector((0, 0.06, -0.02)) if front else j + Vector((0, 0.04, 0.02))
        tuft_dir = Vector((0, 0.20, -0.10)) if front else Vector((0, 0.17, -0.07))
        fades = []
        tf = obj(f"BossTuft{nm}", K.tube_build(K.curve_points(tuft_at, tuft_at + tuft_dir, n=5),
                                               lambda t: 0.055 * (1 - t) + 0.002, 8, flat=0.6, fades=fades), ruff_mat,
                 "outer", hip)
        B.set_point_attr(tf, "fade", fades)
        ground = -hz
        paw_c = Vector((0, path[-1][1] - 0.05, ground + 0.05))
        obj(f"BossPaw{nm}", K.ellipsoid((0.075, 0.11, 0.05), 12, 6), paw_mat, "outer", hip, loc=paw_c)
        for t_ in (-1, 0, 1):  # 墨色趾缝：沿爪的前上表面
            pts = [paw_c + Vector((0.024 * t_, y_, 0.05 * math.sqrt(max(0.0, 1 - (y_ / 0.11) ** 2)) + 0.008))
                   for y_ in (-0.03, -0.07, -0.10)]
            obj(f"BossToe{nm}{t_}", K.strip_build(pts, 0.016, 0.006, side_hint=Vector((1, 0, 0)), taper=(1.0, 0.5)),
                M["ink"], "none", hip)
        legs[nm] = hip
    parts["legs"] = legs
    troot = Vector((0, 1.00, 1.94))  # 尾根粗，接在臀上
    for i in range(BOSS_TAILS):
        fades = []
        ob = obj(f"BossTail{i}", K.tube_build(_boss_tail(troot, i, 0.0), _brush, 12, flat=0.62, fades=fades),
                 tail_mat, "outer", body, sharp_deg=0)
        B.set_point_attr(ob, "fade", fades)
        parts["tails"].append((ob, troot, i))
    # 尾尖狐火（只在 summon 里显示）：每条尾尖一团朱红的火苗（发光，颜色同夜主弹幕 foxfire 的建议染色）
    fire = B.emissive_material("BossTipFire", S.EYE["fox"], 1.0)
    parts["tip_fires"] = []
    for i in range(BOSS_TAILS):
        ob = obj(f"BossTipFire{i}", lambda bm: None, fire, "thin", body, sharp_deg=0)
        ob.hide_render = True
        parts["tip_fires"].append(ob)
    sockets = {"eyes": sock, "feet": B.empty("BossFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def _boss_tail(root, i, phase):
    """第 i 条尾巴：在身后的竖直面里扇形展开（-8°..132°），中间的最长；尖端略回卷。"""
    f = i / (BOSS_TAILS - 1)
    a = math.radians(6 + 128 * f)
    xo = 0.12 * math.sin(i * 2.1)
    d = Vector((xo, math.cos(a), math.sin(a)))
    ln = 2.35 - 0.6 * abs(f - 0.45) * 2
    return _tail_points(Vector(root) + Vector((xo, 0, 0)), d, ln, phase + i * 0.7, 0.10, curl=0.5)


def _boss_tail_dir(root, i, phase, az_deg, el_deg, ln_k=1.0, amp=0.10, curl=0.5, xo_k=1.0):
    """第 i 条尾巴，按方位 az（0 = 正后方 +Y，90 = 镜头一侧 -X，180 = 正前方 -Y）和仰角 el 指向；
    长度同 _boss_tail（中间的最长）× ln_k。"""
    f = i / (BOSS_TAILS - 1)
    xo = 0.12 * math.sin(i * 2.1) * xo_k
    a, e = math.radians(az_deg), math.radians(el_deg)
    d = Vector((-math.sin(a) * math.cos(e) + xo * 0.3, math.cos(a) * math.cos(e), math.sin(e)))
    ln = (2.35 - 0.6 * abs(f - 0.45) * 2) * ln_k
    return _tail_points(Vector(root) + Vector((xo, 0, 0)), d, ln, phase + i * 0.7, amp, curl=curl)


# 九尾扫（sweep，6 帧不循环）：原地（绕锚点）转一圈，九尾扇开、贴着地面横扫一周（游戏里是身前 120° 的扇形）。
# 0 九尾拢成一束竖起；1 身子往回拧、伏低，尾束往远侧后方拉满（蓄力到底，游戏在预警期间停在这一帧）；
# 2 转过来（屁股甩向镜头一侧），尾巴边甩边扇开；3 转到背朝前方：九条尾巴扇形贴地扫过身前（最宽）；4 继续转；5 转回来，尾巴收回身后。
# 每帧：(转角 deg（绕锚点，正 = 从上往下看逆时针）, 尾巴方位起点, 方位跨度, 仰角起点, 仰角跨度, 长度倍数,
#        身体后坐 m, 头俯仰 deg, 前腿 deg, 后腿 deg)。尾巴方位：0 = 身后 +Y，90 = 身体左侧 -X（见 _boss_tail_dir）
BOSS_SWEEP = [
    (0, -34, 14, 52, 22, 0.92, 0.08, 10, -4, 6),
    (-24, -56, 12, 30, 16, 0.86, 0.15, 16, -10, 12),  # 拧到底（预警时停在这）
    (95, -52, 84, 18, 8, 0.88, 0.0, 2, 8, -6),
    (180, -62, 124, 12, 6, 0.74, -0.04, 4, 10, -8),  # 背朝前方：扇面贴地扫过身前
    (268, -40, 96, 18, 10, 0.84, 0.0, 2, 4, -4),
    (352, -18, 46, 30, 64, 0.95, 0.0, 2, 0, 0),
]
# 召唤 / 放狐火环（summon，4 帧不循环）：抬头长啸，九尾高高扇开，尾尖燃起狐火。
# (仰角起点, 仰角跨度, 横向张开倍数, 抬头 deg, 前身抬高 m, 尾尖火苗大小)
BOSS_SUMMON = [
    (30, 110, 1.6, -18, 0.08, 0.45),
    (22, 136, 2.4, -40, 0.16, 1.00),
    (20, 140, 2.6, -42, 0.16, 0.90),
    (26, 120, 2.0, -26, 0.10, 0.60),
]


def _rest_boss(parts):
    """每次摆姿态前复位会被改动的变换和显示（同一个会话里连渲 move / sweep / summon 互不影响）。"""
    parts["body"].location = (0, BODY_SHIFT, 0)
    parts["body"].rotation_euler = (0, 0, 0)
    parts["head"].location = (0, -1.44, 2.12)
    for ob in parts.get("tip_fires", []):
        ob.hide_render = True


def _set_boss_tails(parts, pts_of):
    for ob, troot, i in parts["tails"]:
        fades: list = []
        K.replace_mesh(ob, K.tube_build(pts_of(troot, i), _brush, 12, flat=0.62, fades=fades))
        B.set_point_attr(ob, "fade", fades)


def _pose_boss_legs(parts, front_deg, hind_deg):
    for nm in ("FL", "FR", "HL", "HR"):
        leg = parts["legs"][nm]
        front = nm[0] == "F"
        leg.rotation_euler.x = math.radians(front_deg if front else hind_deg)
        leg.location.z = (FRONT_HIP if front else HIND_HIP)[2]


def _pose_boss_sweep(parts, frame):
    spin, az0, azs, el0, els, lk, sit, head, fl, hl = BOSS_SWEEP[frame % len(BOSS_SWEEP)]
    ph = 0.8 * frame
    # 绕锚点转：锚点在身体坐标 (0, -BODY_SHIFT) 处，转的时候它不动；后坐沿身体自己的 +Y
    R = Matrix.Rotation(math.radians(spin), 3, "Z")
    c = Vector((0, -BODY_SHIFT - sit, 0))
    parts["body"].rotation_euler = (0, 0, math.radians(spin))
    parts["body"].location = -(R @ c) + Vector((0, 0, -0.25 * max(0.0, sit)))
    parts["head"].rotation_euler = (math.radians(6 + head), 0, math.radians(-8))
    _pose_boss_legs(parts, fl, hl)

    def pts_of(troot, i):
        f = i / (BOSS_TAILS - 1)
        return _boss_tail_dir(troot, i, ph, az0 + azs * f, el0 + els * math.sin(math.pi * f) * 0.5 + els * f * 0.5,
                              lk * (1 - 0.12 * abs(2 * f - 1)), amp=0.06, curl=0.35, xo_k=0.5)

    _set_boss_tails(parts, pts_of)
    bpy.context.view_layer.update()


def _pose_boss_summon(parts, frame):
    el0, els, spread, head, rise, fire = BOSS_SUMMON[frame % len(BOSS_SUMMON)]
    ph = 0.9 * frame
    parts["body"].location = (0, BODY_SHIFT, 0)
    # 前身抬起：绕后髋转（负角 = 头抬高）
    pivot = Vector((0, 0.62, 1.86))
    ang = -math.degrees(math.atan2(rise, 1.9))
    R = Matrix.Rotation(math.radians(ang), 3, "X")
    parts["body"].rotation_euler = (math.radians(ang), 0, 0)
    parts["body"].location = Vector((0, BODY_SHIFT, 0)) + pivot - R @ pivot
    parts["head"].rotation_euler = (math.radians(6 + head), 0, math.radians(-8))
    _pose_boss_legs(parts, -6 - 4 * fire, 4 - ang)
    tips = []

    def pts_of(troot, i):
        f = i / (BOSS_TAILS - 1)
        pts = _boss_tail_dir(troot, i, ph, 0, el0 + els * f, 1.0, amp=0.08, curl=0.45, xo_k=spread)
        tips.append((pts[-1], (pts[-1] - pts[-3]).normalized()))
        return pts

    _set_boss_tails(parts, pts_of)
    for k, ob in enumerate(parts["tip_fires"]):  # 尾尖狐火：一团往上窜的火苗
        p, d = tips[k]
        ob.hide_render = fire <= 0.01
        if ob.hide_render:
            continue
        up = (d * 0.35 + Vector((0, 0.15, 1.0))).normalized()
        L = 0.42 * fire * (0.85 + 0.15 * math.sin(k * 1.9 + frame))
        side = up.cross(Vector((1, 0, 0))).normalized()
        path = [p - up * 0.06 + side * 0.03 * t * math.sin(5 * t + k + frame) + up * (L * t) for t in
                (i_ / 7 for i_ in range(8))]
        K.replace_mesh(ob, K.tube_build(path, lambda t: 0.11 * fire * (1 - t) ** 0.8 * (0.7 + 0.6 * math.sin(math.pi * min(1.0, t * 1.6))), 10))
    bpy.context.view_layer.update()


def pose_boss(parts, anim, frame, n):
    """move：潜行——头前伸、略低于肩线；对角两腿同步交替（肩/髋绕横轴摆，向前摆的那条抬爪），
    身体微起伏，九尾依次波动。sweep：见 BOSS_SWEEP；summon：见 BOSS_SUMMON。"""
    _rest_boss(parts)
    if anim == "sweep":
        return _pose_boss_sweep(parts, frame)
    if anim == "summon":
        return _pose_boss_summon(parts, frame)
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.015 * math.cos(2 * ph)
    lp = ph + math.pi / 2  # 第 0 帧就是迈开的步子（审图用第 0 帧）
    parts["head"].rotation_euler = (math.radians(6 + 2.0 * math.sin(2 * ph + 0.6)), 0, math.radians(-8))
    for nm, off in (("FL", 0.0), ("HR", 0.0), ("FR", math.pi), ("HL", math.pi)):
        leg = parts["legs"][nm]
        leg.rotation_euler.x = math.radians(-10 * math.sin(lp + off))  # 负角 = 爪向前
        rest_z = (FRONT_HIP if nm[0] == "F" else HIND_HIP)[2]
        leg.location.z = rest_z + 0.05 * max(0.0, math.cos(lp + off))  # 向前摆（腾空）时抬爪
    for ob, troot, i in parts["tails"]:
        fades: list = []
        build = K.tube_build(_boss_tail(troot, i, ph), _brush, 12, flat=0.62, fades=fades)
        K.replace_mesh(ob, build)
        B.set_point_attr(ob, "fade", fades)
    bpy.context.view_layer.update()
