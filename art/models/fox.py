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

import bpy
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


def _boss_head(prefix, parent, M, eye_mat, s):
    """细长吻部的狐头：墨色头骨 + 白面具（额、眼、长吻）+ 朱砂纹、藤黄额饰 + 高耸的尖耳。"""
    obj = B.mesh_object
    obj(f"{prefix}Skull", K.ellipsoid((0.14 * s, 0.16 * s, 0.13 * s)), M["fur"], "outer", parent)
    obj(f"{prefix}MaskFace", K.ellipsoid((0.125 * s, 0.10 * s, 0.115 * s)), M["mask"], "outer", parent,
        loc=(0, -0.08 * s, 0.01 * s))
    obj(f"{prefix}Snout", K.ellipsoid((0.055 * s, 0.25 * s, 0.055 * s)), M["mask"], "outer", parent,
        loc=(0, -0.27 * s, -0.05 * s), rot=(math.radians(12), 0, 0))  # 吻尖略向下
    obj(f"{prefix}Nose", K.ellipsoid((0.022 * s, 0.02 * s, 0.017 * s)), M["ink"], "none", parent,
        loc=(0, -0.505 * s, -0.10 * s))
    for sx in (-1, 1):
        pts = [Vector((0.03 * sx * s, -0.17 * s, 0.03 * s)), Vector((0.075 * sx * s, -0.15 * s, 0.05 * s)),
               Vector((0.11 * sx * s, -0.10 * s, 0.09 * s))]
        obj(f"{prefix}Mark{sx:+d}", K.strip_build(pts, 0.020 * s, 0.006 * s, side_hint=Vector((0, 0, 1)),
                                                  taper=(1.0, 0.3)), M["red"], "none", parent)
        ear = K.curve_points((0.07 * sx * s, 0.0, 0.09 * s), (0.10 * sx * s, 0.04 * s, 0.50 * s),
                             bend=Vector((0.02 * sx * s, 0.02 * s, 0)), n=8)
        obj(f"{prefix}Ear{sx:+d}", K.tube_build(ear, lambda t: 0.06 * s * (1 - t) ** 0.9 + 0.002, 8, flat=0.55),
            M["fur"], "outer", parent)
    obj(f"{prefix}Crest", K.ellipsoid((0.018 * s, 0.01 * s, 0.035 * s), 10, 6), M["gold"], "none", parent,
        loc=(0, -0.172 * s, 0.10 * s))
    return K.slit_eyes(prefix, parent, Vector((0, -0.175 * s, 0.035 * s)), 0.10 * s,
                       (0.034 * s, 0.011 * s, 0.010 * s), eye_mat, tilt_deg=24)


def build_boss():
    M = _mats("Boss")
    eye = B.emissive_material("BossEye", S.EYE["boss"], 1.0)
    tail_mat = K.banded_toon_material("BossTailInk", TAIL_BANDS, edge=0.3, seed=58.0)
    ruff_mat = K.banded_toon_material("BossRuffInk", RUFF_BANDS, edge=0.3, seed=59.0)
    root = B.empty("BossRoot")
    yaw = K.yaw_pivot("BossYaw", root, -20)
    body = B.empty("BossBody", yaw, loc=(0, 0, 0.15))  # 悬浮
    parts = {"root": root, "body": body, "M": M, "tails": [], "tail_mat": tail_mat}
    obj = B.mesh_object
    obj("BossTorso", K.ellipsoid((0.40, 1.08, 0.44), 28, 16), M["fur"], "outer", body, loc=(0, 0.28, 1.66))
    obj("BossChest", K.ellipsoid((0.44, 0.52, 0.58), 24, 14), M["fur"], "outer", body, loc=(0, -0.58, 1.86))
    obj("BossBib", K.ellipsoid((0.30, 0.26, 0.46), 20, 12), M["mask"], "outer", body, loc=(0, -0.88, 1.80))  # 白胸毛
    for sx in (-1, 1):  # 后腿根部的大腿肌肉
        obj(f"BossHaunch{sx:+d}", K.ellipsoid((0.20, 0.34, 0.34), 16, 10), M["fur"], "outer", body,
            loc=(0.30 * sx, 0.92, 1.42))
    K.limb("BossNeck", (0, -0.74, 2.10), (0, -1.00, 2.86), 0.30, 0.19, M["fur"], "outer", body, segs=16)
    # 颈部鬃毛：一圈向后下方飘的毛束，根部浓墨、尖端清墨
    for i in range(14):
        a = math.radians(-120 + i * (240 / 13))
        base = Vector((0.26 * math.sin(a), -0.92 + 0.08 * math.cos(a), 2.40 + 0.22 * math.cos(a)))
        tip = base + Vector((0.34 * math.sin(a), 0.85, -0.28 + 0.10 * math.cos(a)))  # 披向肩背的鬃毛
        fades: list = []
        ob = obj(f"BossRuff{i}", K.tube_build(K.curve_points(base, tip, bend=Vector((0, 0.05, 0.12)), n=7),
                                             K.bushy(0.15, peak=0.3), 8, flat=0.7, fades=fades), ruff_mat, "outer", body)
        B.set_point_attr(ob, "fade", fades)
    head = B.empty("BossHead", body, loc=(0, -1.06, 3.02), rot=(math.radians(-6), 0, math.radians(-24)))
    parts["head"] = head
    sock = _boss_head("BossH", head, M, eye, s=2.2)
    # 修长的四肢（趾行，后腿有跗关节）
    legs = {}
    for nm, (x, y, z), pts in (
            ("FL", (0.28, -0.62, 1.62), [(0.02, -0.02, -0.66), (0.02, -0.10, -1.26), (0.02, -0.18, -1.44)]),
            ("FR", (-0.28, -0.62, 1.62), [(-0.02, -0.02, -0.66), (-0.02, -0.10, -1.26), (-0.02, -0.18, -1.44)]),
            ("HL", (0.32, 0.98, 1.56), [(0.02, -0.32, -0.52), (0.02, 0.14, -1.06), (0.02, -0.02, -1.40)]),
            ("HR", (-0.32, 0.98, 1.56), [(-0.02, -0.32, -0.52), (-0.02, 0.14, -1.06), (-0.02, -0.02, -1.40)])):
        hip = B.empty(f"BossHip{nm}", body, loc=(x, y, z))
        prev, r = Vector((0, 0, 0)), (0.17, 0.11, 0.07, 0.055)
        for k_, pnt in enumerate(pts):
            K.limb(f"BossLeg{nm}{k_}", prev, pnt, r[k_], r[k_ + 1], M["fur"], "outer", hip)
            prev = Vector(pnt)
        obj(f"BossPaw{nm}", K.ellipsoid((0.08, 0.14, 0.05)), M["fur"], "outer", hip, loc=prev + Vector((0, -0.07, -0.02)))
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
    """move：悬浮踏步——身体上下浮动，四足交替轻划，九尾依次波动，头稳。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.15 + 0.03 * math.sin(ph)
    for nm, off in (("FL", 0.0), ("HR", 0.0), ("FR", math.pi), ("HL", math.pi)):
        parts["legs"][nm].rotation_euler.x = math.radians(-10 * math.sin(ph + off))
    for ob, troot, i in parts["tails"]:
        fades: list = []
        build = K.tube_build(_boss_tail(troot, i, ph), _brush, 12, flat=0.62, fades=fades)
        K.replace_mesh(ob, build)
        B.set_point_attr(ob, "fade", fades)
    bpy.context.view_layer.update()
