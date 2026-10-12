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
    M = _mats("Fox")
    eye = B.emissive_material("FoxEye", S.EYE["fox"], 1.0)
    root = B.empty("FoxRoot")
    yaw = K.yaw_pivot("FoxYaw", root, -18, loc=(0.12, -0.05, 0))
    body = B.empty("FoxBody", yaw)
    parts = {"root": root, "body": body, "M": M, "tails": []}
    obj = B.mesh_object
    # 躯干（前倾 35°）+ 破袍
    torso = B.empty("FoxTorso", body, loc=(0, 0.18, 0.95), rot=(math.radians(35), 0, 0))
    parts["torso"] = torso
    obj("FoxChest", K.ellipsoid((0.23, 0.19, 0.42)), M["robe"], "outer", torso, loc=(0, 0, 0.36))
    obj("FoxCollar", B.lathe([(0.10, 0.0), (0.13, 0.04), (0.10, 0.08)], 16), M["robe_dark"], "inner", torso,
        loc=(0, -0.02, 0.70))
    obj("FoxSash", B.lathe([(0.205, 0.0), (0.215, 0.05), (0.205, 0.10)], 20, scale_y=0.85), M["robe_dark"], "inner",
        torso, loc=(0, 0, 0.10))
    rags = []
    for i, (c, w) in enumerate(((-90, 80), (90, 90), (0, 70), (180, 70))):
        ob = obj(f"FoxRag{i}", K.grid_build(K.rag_panel_rows(c, w, 0.21, 0.95, 0.62, seed=i, tatter=0.35)),
                 M["robe"], "outer", body, loc=(0, 0.18, 0), sharp_deg=0)
        rags.append((ob, c, w, i))
    parts["rags"] = rags
    # 头：探在前上方，朝镜头再偏一点
    head = B.empty("FoxHead", body, loc=(0, -0.64, 1.70), rot=(math.radians(-8), 0, math.radians(-25)))
    parts["head"] = head
    sock = _fox_head("FoxH", head, M, eye, s=1.35, ear_h=0.26)
    # 前肢：破袖 + 墨爪，向前探
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"FoxShoulder{nm}", body, loc=(0.20 * sx, -0.30, 1.40))
        K.limb(f"FoxSleeve{nm}", (0, 0, 0), (0.06 * sx, -0.20, -0.30), 0.085, 0.12, M["robe"], "outer", sh)
        K.limb(f"FoxArm{nm}", (0.06 * sx, -0.20, -0.30), (0.03 * sx, -0.42, -0.42), 0.04, 0.03, M["fur"], "outer", sh)
        for c in (-1, 0, 1):
            K.limb(f"FoxClaw{nm}{c}", (0.03 * sx, -0.42, -0.42), (0.03 * sx + 0.025 * c, -0.52, -0.50), 0.014, 0.0,
                   M["ink"], "inner", sh, segs=6)
        parts[f"arm_{nm}"] = sh
        # 后腿：趾行（大腿向前、小腿向后、跖向前下）
        hip = B.empty(f"FoxHip{nm}", body, loc=(0.13 * sx, 0.20, 0.92))
        K.limb(f"FoxThigh{nm}", (0, 0, 0), (0.02 * sx, -0.20, -0.36), 0.10, 0.07, M["fur"], "outer", hip)
        knee = B.empty(f"FoxKnee{nm}", hip, loc=(0.02 * sx, -0.20, -0.36))
        K.limb(f"FoxShin{nm}", (0, 0, 0), (0, 0.26, -0.32), 0.06, 0.045, M["fur"], "outer", knee)
        K.limb(f"FoxFoot{nm}", (0, 0.26, -0.32), (0, 0.10, -0.52), 0.045, 0.035, M["fur"], "outer", knee)
        B.mesh_object(f"FoxPaw{nm}", K.ellipsoid((0.05, 0.09, 0.035)), M["fur"], "outer", knee, loc=(0, 0.06, -0.535))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    # 尾巴
    troot = Vector((0, 0.42, 0.98))
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
    return _tail_points(Vector(root) + Vector((xo, 0, 0)), d, ln, phase + tph, 0.08, curl=0.5)


def pose_fox(parts, anim, frame, n):
    """move：潜行小跑——两腿交替（髋前后摆、膝随之屈伸），身体轻微起伏，前爪交替探出，尾巴波动，破袍飘。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.02 * math.cos(2 * ph)
    parts["torso"].rotation_euler.x = math.radians(35 + 2 * math.sin(2 * ph))
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-24 * s), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(14 * max(0.0, -s) + 6), 0, 0)
        parts[f"arm_{nm}"].rotation_euler = (math.radians(14 * s), 0, 0)
    M = parts["M"]
    for ob, troot, ang, ln, tph, xo in parts["tails"]:
        K.replace_mesh(ob, K.tube_build(_fox_tail(troot, ang, ln, ph, tph, xo), K.bushy(0.12), 12, _tail_zones))
    for ob, c, w, i in parts["rags"]:
        K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, 0.21, 0.95, 0.62, phase=ph, wind=0.35, seed=i,
                                                         tatter=0.35)))
    bpy.context.view_layer.update()


# ================================================================ 九尾
BOSS_TAILS = 9


def build_boss():
    M = _mats("Boss")
    eye = B.emissive_material("BossEye", S.EYE["boss"], 1.0)
    root = B.empty("BossRoot")
    yaw = K.yaw_pivot("BossYaw", root, -20, loc=(0.10, -0.45, 0))
    body = B.empty("BossBody", yaw, loc=(0, 0, 0.15))  # 悬浮
    parts = {"root": root, "body": body, "M": M, "tails": []}
    obj = B.mesh_object
    obj("BossTorso", K.ellipsoid((0.46, 1.05, 0.50), 28, 16), M["fur"], "outer", body, loc=(0, 0.25, 1.52))
    obj("BossChest", K.ellipsoid((0.56, 0.62, 0.72), 24, 14), M["fur"], "outer", body, loc=(0, -0.62, 1.78))
    K.limb("BossNeck", (0, -0.80, 2.05), (0, -1.10, 2.75), 0.38, 0.27, M["fur"], "outer", body, segs=16)
    # 颈部鬃刺：一圈墨色尖刺，向后
    for i in range(11):
        a = math.radians(-100 + i * 20)
        base = Vector((0.40 * math.sin(a), -0.92 + 0.10 * math.cos(a), 2.20 + 0.32 * math.cos(a)))
        tip = base + Vector((0.26 * math.sin(a), 0.50, 0.22 * math.cos(a) + 0.10))
        K.limb(f"BossRuff{i}", base, tip, 0.14, 0.0, M["mask"] if i % 2 else M["fur"], "outer", body, segs=6)
    head = B.empty("BossHead", body, loc=(0, -1.22, 2.95), rot=(math.radians(-10), 0, math.radians(-22)))
    parts["head"] = head
    sock = _fox_head("BossH", head, M, eye, s=2.6, ear_h=0.34)
    # 额心藤黄纹
    obj("BossCrest", K.ellipsoid((0.04, 0.02, 0.07), 10, 6), M["gold"], "none", head, loc=(0, -0.385, 0.30))
    # 四肢（浮空，爪尖离地）
    legs = {}
    for nm, (x, y, z), knee_off, paw in (("FL", (0.36, -0.70, 1.45), (0.02, -0.08, -0.62), (0.0, -0.18, -1.18)),
                                          ("FR", (-0.36, -0.70, 1.45), (-0.02, -0.08, -0.62), (0.0, -0.18, -1.18)),
                                          ("HL", (0.40, 0.95, 1.40), (0.02, -0.30, -0.55), (0.02, 0.10, -1.15)),
                                          ("HR", (-0.40, 0.95, 1.40), (-0.02, -0.30, -0.55), (-0.02, 0.10, -1.15))):
        hip = B.empty(f"BossHip{nm}", body, loc=(x, y, z))
        K.limb(f"BossUpper{nm}", (0, 0, 0), knee_off, 0.30, 0.16, M["fur"], "outer", hip)
        K.limb(f"BossLower{nm}", knee_off, paw, 0.14, 0.09, M["fur"], "outer", hip)
        obj(f"BossPaw{nm}", K.ellipsoid((0.14, 0.21, 0.08)), M["fur"], "outer", hip,
            loc=Vector(paw) + Vector((0, -0.06, -0.02)))
        legs[nm] = hip
    parts["legs"] = legs
    troot = Vector((0, 1.22, 1.72))
    for i in range(BOSS_TAILS):
        ob = obj(f"BossTail{i}", K.tube_build(_boss_tail(troot, i, 0.0), K.bushy(0.20), 12, _tail_zones),
                 [M["fur"], M["gold"], M["red"]], "outer", body, sharp_deg=0)
        parts["tails"].append((ob, troot, i))
    sockets = {"eyes": sock, "feet": B.empty("BossFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def _boss_tail(root, i, phase):
    """第 i 条尾巴：在身后的竖直面（E 向画面的平面）里扇形展开——仰角从 5°（水平向后）到 105°（略过头顶），
    左右只错开一点；中间的最长。"""
    f = i / (BOSS_TAILS - 1)  # 0..1
    a = math.radians(-8 + 140 * f)  # 从略低于水平向后，一直开到越过头顶向前
    xo = 0.12 * math.sin(i * 2.1)
    d = Vector((xo, math.cos(a), math.sin(a)))
    ln = 2.75 - 0.7 * abs(f - 0.45) * 2
    return _tail_points(Vector(root) + Vector((xo, 0, 0)), d, ln, phase + i * 0.7, 0.10, curl=0.4)


def pose_boss(parts, anim, frame, n):
    """move：悬浮踏步——身体上下浮动，四足交替轻划，九尾依次波动，头稳。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.15 + 0.03 * math.sin(ph)
    for nm, off in (("FL", 0.0), ("HR", 0.0), ("FR", math.pi), ("HL", math.pi)):
        parts["legs"][nm].rotation_euler.x = math.radians(-12 * math.sin(ph + off))
    for ob, troot, i in parts["tails"]:
        K.replace_mesh(ob, K.tube_build(_boss_tail(troot, i, ph), K.bushy(0.20), 12, _tail_zones))
    bpy.context.view_layer.update()
