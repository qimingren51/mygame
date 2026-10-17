"""狐妖两种：赤面狐（精英，半立的狐妖，破袍、白色能面狐面具）和 夜主 · 九尾（首领，九尾巨狐）。

赤面狐：半直立前倾，穿淡彩朱砂的破袍（袖口、下摆参差），白色狐面具上有朱砂纹，眼睛 EYE['fox'] 从面具眼缝里透出；
  浓墨毛色的耳朵、腿和三条大尾巴（尾尖朱砂）。动画 move：8 帧潜行小跑。帧 FRAME["elite"]（160px）。
九尾：四足巨狐，浓墨毛，白面具（朱砂、藤黄纹），颈部一圈墨色鬃刺，九条尾巴在身后扇形展开（尾尖朱砂、
  前面一圈藤黄）。悬浮（离地约 0.15 米），动画 move：8 帧悬浮踏步，尾巴依次波动。帧 FRAME["boss"]（320px）。
两者都只渲染 E，身体朝镜头偏一点，眼睛/面具在 E 向读得出来。挂点：eyes、feet。
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


def pose_fox(parts, anim, frame, n):
    """move：潜行小跑——两腿交替（髋前后摆、膝随之屈伸），身体轻微起伏，前爪交替探出，尾巴波动，破袍飘。"""
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


def _ring_body_build(spine, attrs_out, segs=20):
    """沿脊线的椭圆截面体（躯干、颈）：spine = [(中心点, 横半径, 竖半径), ...]。
    attrs_out 按顶点顺序填“由背到腹”的 0..1（截面里越靠下越大），给 BODY_BANDS 分段上色。"""
    pts = [Vector(p) for p, _, _ in spine]
    n = len(pts)

    def build(bm):
        rings = []
        for i, (p, rx, rz) in enumerate(spine):
            p = Vector(p)
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            side = tan.cross(Vector((0, 0, 1)))
            side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
            up = side.cross(tan).normalized()
            ring = []
            for j in range(segs):
                th = 2 * math.pi * j / segs
                ring.append(bm.verts.new(p + side * (math.cos(th) * rx) + up * (math.sin(th) * rz)))
                attrs_out.append(0.5 - 0.5 * math.sin(th))  # 顶 0，底 1
            rings.append(ring)
        for a_, b_ in zip(rings, rings[1:]):
            for j in range(segs):
                bm.faces.new((a_[j], a_[(j + 1) % segs], b_[(j + 1) % segs], b_[j]))
        for ring, rev in ((rings[0], True), (rings[-1], False)):  # 两端收成一点（圆头）
            c = sum((v.co for v in ring), Vector()) / segs
            cv = bm.verts.new(c + (pts[0] - pts[1]).normalized() * 0.08 if rev else c + (pts[-1] - pts[-2]).normalized() * 0.08)
            attrs_out.append(0.5)
            for j in range(segs):
                bm.faces.new((ring[(j + 1) % segs], ring[j], cv) if rev else (ring[j], ring[(j + 1) % segs], cv))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _cone_build(base, tip, r0, r1, flat=1.0, segs=12, side_hint=Vector((1, 0, 0))):
    """从 base 到 tip 的锥（吻部、下颌、耳朵）；flat 压扁“竖向”截面。"""
    return K.tube_build(K.curve_points(base, tip, n=6), lambda t: r0 + (r1 - r0) * t, segs, flat=flat)


def _boss_head(prefix, parent, M, eye_mat, red_rim):
    """真正的狐狸头（米为单位，面朝 -Y）：楔形头骨收进中等长度的锥形吻部；白色面纹在吻部、下颌和两颊，
    两颊的白毛向后炸开成三簇尖；额头和耳朵是墨色；黑鼻头、一道嘴线；眼睛是杏仁形细缝（藤黄发光、朱砂细边），
    眼上两笔朱砂火焰纹；耳朵是宽底大三角（底宽约为高的 0.6），微外撇，内耳白、带一簇毛。返回眼睛挂点。"""
    obj = B.mesh_object

    def skull(bm):  # 楔形：前半截逐渐收窄
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1.0)
        for v in bm.verts:
            x, y, z = v.co
            k = 1 - 0.30 * max(0.0, -y)  # 越往前（-Y）越窄
            v.co = Vector((x * 0.21 * k, y * 0.25, z * 0.19 * (1 - 0.15 * max(0.0, -y))))
    obj(f"{prefix}Skull", skull, M["fur"], "outer", parent)
    # 吻部：起点和两眼间距一样宽，长约头骨高的 1.2 倍；下颌在下面
    obj(f"{prefix}Muzzle", _cone_build((0, -0.14, -0.05), (0, -0.56, -0.11), 0.105, 0.032, flat=0.72), M["mask"],
        "outer", parent)
    obj(f"{prefix}Jaw", _cone_build((0, -0.12, -0.12), (0, -0.46, -0.15), 0.075, 0.022, flat=0.6), M["mask"],
        "outer", parent)
    obj(f"{prefix}Nose", K.ellipsoid((0.038, 0.032, 0.028), 10, 6), M["ink"], "none", parent, loc=(0, -0.57, -0.10))
    for sx in (-1, 1):
        mouth = [Vector((0.035 * sx, -0.50, -0.135)), Vector((0.055 * sx, -0.36, -0.14)), Vector((0.075 * sx, -0.24, -0.13))]
        obj(f"{prefix}Mouth{sx:+d}", K.strip_build(mouth, 0.012, 0.004, side_hint=Vector((0, 0, 1)), taper=(0.8, 1.0)),
            M["ink"], "none", parent)
        # 白颊 + 向后炸开的三簇尖毛
        obj(f"{prefix}Cheek{sx:+d}", K.ellipsoid((0.10, 0.12, 0.09), 14, 8), M["mask"], "outer", parent,
            loc=(0.12 * sx, -0.07, -0.08))
        for k_, (dy, dz, ln) in enumerate(((0.0, 0.02, 0.20), (0.04, -0.05, 0.24), (0.06, -0.12, 0.18))):
            base = Vector((0.17 * sx, -0.04 + dy, -0.06 + dz))
            tip = base + Vector((0.10 * sx, 0.16 + 0.05 * k_, -0.04 - 0.05 * k_)) * (ln / 0.2)
            obj(f"{prefix}Ruff{sx:+d}{k_}", K.tube_build(K.curve_points(base, tip, n=5), lambda t: 0.045 * (1 - t) + 0.002, 8,
                                                           flat=0.6), M["mask"], "outer", parent)
        # 杏仁眼：朱砂细边在后，藤黄（EYE['boss']）发光的细缝在前
        eye_loc = Vector((0.085 * sx, -0.205, 0.035))
        rot = (0, math.radians(-22 * sx), math.radians(-14 * sx))
        obj(f"{prefix}EyeRim{sx:+d}", K.ellipsoid((0.056, 0.012, 0.022), 12, 6), red_rim, "none", parent,
            loc=eye_loc + Vector((0, 0.004, 0)), rot=rot)
        obj(f"{prefix}Eye{sx:+d}", K.ellipsoid((0.046, 0.012, 0.013), 12, 6), eye_mat, "none", parent,
            loc=eye_loc + Vector((0, -0.004, 0)), rot=rot)
        # 眼上一笔朱砂火焰纹
        flame = [Vector((0.05 * sx, -0.215, 0.075)), Vector((0.075 * sx, -0.20, 0.12)), Vector((0.06 * sx, -0.17, 0.17))]
        obj(f"{prefix}Flame{sx:+d}", K.strip_build(flame, 0.030, 0.006, side_hint=Vector((1, 0, 0)), taper=(1.0, 0.1)),
            M["red"], "none", parent)
        # 大三角耳：底宽约为高的 0.6，微外撇；内耳白 + 一簇毛
        base, tip = Vector((0.12 * sx, 0.04, 0.13)), Vector((0.22 * sx, 0.08, 0.49))
        obj(f"{prefix}Ear{sx:+d}", _cone_build(base, tip, 0.11, 0.004, flat=0.38, segs=10), M["fur"], "outer", parent)
        obj(f"{prefix}EarIn{sx:+d}", _cone_build(base + Vector((-0.01 * sx, -0.035, 0.03)), tip + Vector((-0.012 * sx, -0.02, -0.07)),
                                               0.065, 0.004, flat=0.3, segs=8), M["mask"], "none", parent)
        tuft = K.curve_points(base + Vector((-0.02 * sx, -0.05, 0.02)), base + Vector((0.02 * sx, -0.09, 0.15)), n=5)
        obj(f"{prefix}EarTuft{sx:+d}", K.tube_build(tuft, lambda t: 0.022 * (1 - t) + 0.002, 6), M["mask"], "none", parent)
    return B.empty(f"{prefix}SocketEyes", parent, loc=(0, -0.21, 0.035))


def _leg_build(path, radii, attrs_out=None):
    """有关节的锥形腿：沿关节点折线插值成管，半径逐段渐细（关节处可以略鼓）。"""
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
    return K.tube_build(pts, lambda t: float(np.interp(t, np.linspace(0, 1, n), rr)), 10)


def build_boss():
    M = _mats("Boss")
    eye = B.emissive_material("BossEye", S.EYE["boss"], 1.0)
    tail_mat = K.banded_toon_material("BossTailInk", TAIL_BANDS, edge=0.3, seed=58.0)
    ruff_mat = K.banded_toon_material("BossRuffInk", RUFF_BANDS, edge=0.3, seed=59.0)
    body_mat = K.banded_toon_material("BossBodyInk", BODY_BANDS, edge=0.3, noise_amt=0.12, seed=60.0)
    root = B.empty("BossRoot")
    yaw = K.yaw_pivot("BossYaw", root, -20)
    body = B.empty("BossBody", yaw)  # 着地潜行（不再悬浮）
    parts = {"root": root, "body": body, "M": M, "tails": [], "tail_mat": tail_mat}
    obj = B.mesh_object
    # 躯干：深胸、收腹，腹线向后腿抬起；尾根粗（尾巴根点 (0, 1.28, 1.86) 不变）
    spine = [((0, -1.02, 1.92), 0.12, 0.14), ((0, -0.88, 1.84), 0.33, 0.50), ((0, -0.60, 1.82), 0.38, 0.52),
             ((0, -0.26, 1.88), 0.32, 0.40), ((0, 0.10, 1.95), 0.27, 0.29), ((0, 0.45, 1.95), 0.29, 0.31),
             ((0, 0.80, 1.90), 0.35, 0.37), ((0, 1.12, 1.88), 0.31, 0.32), ((0, 1.34, 1.88), 0.15, 0.16)]
    shade: list = []
    torso = obj("BossTorso", _ring_body_build(spine, shade), body_mat, "outer", body, sharp_deg=0)
    B.set_point_attr(torso, "fade", shade)
    # 粗壮弓起的颈
    neck_sp = [((0, -0.78, 2.02), 0.30, 0.34), ((0, -1.02, 2.30), 0.27, 0.30), ((0, -1.25, 2.42), 0.23, 0.25),
               ((0, -1.42, 2.40), 0.19, 0.20)]
    shade = []
    neck = obj("BossNeck", _ring_body_build(neck_sp, shade), body_mat, "outer", body, sharp_deg=0)
    B.set_point_attr(neck, "fade", shade)
    # 鬃毛：沿颈背向后飘
    for i in range(12):
        f = i / 11
        a = math.radians(-70 + 140 * f)
        p0 = Vector((0, -1.30 + 0.45 * f, 2.50 - 0.25 * f))
        base = p0 + Vector((0.20 * math.sin(a), 0.0, 0.10 * math.cos(a)))
        tip = base + Vector((0.30 * math.sin(a), 0.60, -0.10 + 0.12 * math.cos(a)))
        fades: list = []
        ob = obj(f"BossRuff{i}", K.tube_build(K.curve_points(base, tip, bend=Vector((0, 0.05, 0.10)), n=7),
                                             K.bushy(0.13, peak=0.3), 8, flat=0.7, fades=fades), ruff_mat, "outer", body)
        B.set_point_attr(ob, "fade", fades)
    head = B.empty("BossHead", body, loc=(0, -1.58, 2.36), rot=(math.radians(4), 0, math.radians(-22)))
    parts["head"] = head
    sock = _boss_head("BossH", head, M, eye, M["red"])
    # 四肢：前腿细、有腕；后腿 粗大腿 → 细小腿 → 向后的跗关节 → 长跖骨 → 爪；肘后、跗后各一簇毛
    legs = {}
    for nm, sx, front in (("FL", 1, True), ("FR", -1, True), ("HL", 1, False), ("HR", -1, False)):
        if front:
            hip = B.empty(f"BossHip{nm}", body, loc=(0.24 * sx, -0.66, 1.78))
            path = [(0, 0, 0), (0.01 * sx, 0.07, -0.66), (0.01 * sx, -0.03, -1.42), (0.0, -0.07, -1.70)]
            radii = [0.16, 0.085, 0.052, 0.046]
            tuft_at, tuft_dir = Vector(path[1]), Vector((0, 0.16, -0.06))
        else:
            hip = B.empty(f"BossHip{nm}", body, loc=(0.27 * sx, 0.92, 1.80))
            obj(f"BossHaunch{nm}", K.ellipsoid((0.20, 0.36, 0.40), 16, 10), M["fur"], "outer", hip, loc=(0.02 * sx, -0.04, -0.20))
            path = [(0, 0, -0.10), (0.01 * sx, -0.30, -0.66), (0.01 * sx, 0.20, -1.16), (0.0, 0.04, -1.72)]
            radii = [0.17, 0.075, 0.050, 0.044]
            tuft_at, tuft_dir = Vector(path[2]), Vector((0, 0.15, 0.02))
        obj(f"BossLeg{nm}", _leg_build(path, radii), M["fur"], "outer", hip, sharp_deg=0)
        obj(f"BossJoint{nm}", K.ellipsoid((0.06, 0.065, 0.06), 10, 6), M["fur"], "outer", hip,
            loc=Vector(path[2]) if front else Vector(path[2]))  # 腕 / 跗关节
        tuft = K.curve_points(tuft_at, tuft_at + tuft_dir, n=5)
        obj(f"BossTuft{nm}", K.tube_build(tuft, lambda t: 0.04 * (1 - t) + 0.002, 6, flat=0.6), M["fur"], "outer", hip)
        paw_c = Vector(path[-1]) + Vector((0, -0.06, -0.01))
        obj(f"BossPaw{nm}", K.ellipsoid((0.065, 0.10, 0.042), 12, 6), M["fur"], "outer", hip, loc=paw_c)
        for t_ in (-1, 0, 1):  # 墨色趾缝
            pts = [paw_c + Vector((0.025 * t_, -0.06, 0.02)), paw_c + Vector((0.03 * t_, -0.10, 0.0))]
            obj(f"BossToe{nm}{t_}", K.strip_build(pts, 0.008, 0.004, side_hint=Vector((1, 0, 0)), taper=(1.0, 0.5)),
                M["ink"], "none", hip)
        legs[nm] = hip
    parts["legs"] = legs
    troot = Vector((0, 1.28, 1.86))
    for i in range(BOSS_TAILS):
        fades: list = []
        ob = obj(f"BossTail{i}", K.tube_build(_boss_tail(troot, i, 0.0), _brush, 12, flat=0.62, fades=fades),
                 tail_mat, "outer", body, sharp_deg=0)
        B.set_point_attr(ob, "fade", fades)
        parts["tails"].append((ob, troot, i))
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


def pose_boss(parts, anim, frame, n):
    """move：潜行——头前伸、略低于肩线；对角两腿同步交替轻抬（肩/髋绕横轴摆），身体微起伏，九尾依次波动。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.012 * math.cos(2 * ph)
    parts["head"].rotation_euler = (math.radians(4 + 1.5 * math.sin(2 * ph + 0.6)), 0, math.radians(-22))
    for nm, off in (("FL", 0.0), ("HR", 0.0), ("FR", math.pi), ("HL", math.pi)):
        s_ = math.sin(ph + off)
        leg = parts["legs"][nm]
        leg.rotation_euler.x = math.radians(-9 * s_)
        leg.location.z = (1.78 if nm[0] == "F" else 1.80) + 0.03 * max(0.0, -math.cos(ph + off))  # 向前摆时抬爪
    for ob, troot, i in parts["tails"]:
        fades: list = []
        build = K.tube_build(_boss_tail(troot, i, ph), _brush, 12, flat=0.62, fades=fades)
        K.replace_mesh(ob, build)
        B.set_point_attr(ob, "fade", fades)
    bpy.context.view_layer.update()
