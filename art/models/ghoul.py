"""青面鬼：青面獠牙的恶鬼。佝偻的巨汉，宽肩长臂，皮肤石绿，脸是淡彩石绿的面具（眉骨压低、獠牙上翻），
骨色双角，焦墨乱发向后飞；身披浓墨破袍，下摆参差。眼睛 EYE['ghoul']。
动画 move：8 帧沉重的大步（腿交替、上身左右晃、双臂反向摆）。帧 FRAME["elite"]（160px）。只渲染 E。
游戏碰撞半径 30 单位 → 占地直径约 2.4 米。
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


def build_ghoul():
    I, A = S.INK, S.ACCENT
    skin = K.toon("GhoulSkin", A["shilv"], edge=0.5, seed=61.0)
    face = K.toon("GhoulFace", S.WASH["shilv"], edge=0.4, seed=62.0)
    robe = K.toon("GhoulRobe", I["nong"], edge=0.3, seed=63.0)
    bone = K.toon("GhoulBone", ramp=[S.PAPER, I["qing"], I["dan"]], seed=64.0)
    hair = K.toon("GhoulHair", I["jiao"], seed=65.0)
    ink = B.flat_material("GhoulInk", I["jiao"])
    eye = B.emissive_material("GhoulEye", S.EYE["ghoul"], 1.0)
    root = B.empty("GhoulRoot")
    yaw = K.yaw_pivot("GhoulYaw", root, -10, loc=(0.28, 0, 0))
    body = B.empty("GhoulBody", yaw)
    body.scale = (1.12, 1.12, 1.12)  # 比人形高大一圈
    parts = {"root": root, "body": body}
    obj = B.mesh_object
    pelvis = B.empty("GhoulPelvis", body, loc=(0, 0.10, 1.05))
    parts["pelvis"] = pelvis
    torso = B.empty("GhoulTorso", pelvis, rot=(math.radians(22), 0, 0))
    parts["torso"] = torso
    obj("GhoulChest", K.ellipsoid((0.46, 0.34, 0.56)), robe, "outer", torso, loc=(0, 0, 0.50))
    obj("GhoulBelly", K.ellipsoid((0.30, 0.20, 0.30)), skin, "outer", torso, loc=(0, -0.22, 0.42))  # 破袍敞口露肚
    rags = []
    for i, (c, w) in enumerate(((-90, 100), (90, 110), (0, 70), (180, 70))):
        ob = obj(f"GhoulRag{i}", K.grid_build(K.rag_panel_rows(c, w, 0.36, 0.10, 0.62, seed=i + 7, tatter=0.4)),
                 robe, "outer", pelvis, sharp_deg=0)
        rags.append((ob, c, w, i))
    parts["rags"] = rags
    # 头：低探在前，青面、眉骨、獠牙、双角、乱发
    head = B.empty("GhoulHead", torso, loc=(0, -0.22, 1.08), rot=(math.radians(-24), 0, math.radians(-22)))
    parts["head"] = head
    obj("GhoulSkull", K.ellipsoid((0.23, 0.22, 0.25)), face, "outer", head)
    obj("GhoulJaw", K.ellipsoid((0.21, 0.18, 0.12)), face, "outer", head, loc=(0, -0.08, -0.17))
    obj("GhoulBrow", K.ellipsoid((0.22, 0.06, 0.04)), ink, "inner", head, loc=(0, -0.19, 0.10), rot=(math.radians(-10), 0, 0))
    obj("GhoulMouth", K.ellipsoid((0.15, 0.04, 0.025)), ink, "none", head, loc=(0, -0.235, -0.13))
    for sx in (-1, 1):
        K.limb(f"GhoulFang{sx:+d}", (0.09 * sx, -0.235, -0.16), (0.10 * sx, -0.25, -0.04), 0.03, 0.0, bone, "inner",
               head, segs=6)
        horn = K.curve_points((0.12 * sx, -0.05, 0.18), (0.30 * sx, 0.18, 0.52), bend=Vector((0.06 * sx, -0.10, 0.04)), n=8)
        obj(f"GhoulHorn{sx:+d}", K.tube_build(horn, lambda t: 0.065 * (1 - t) + 0.004, 8), bone, "outer", head)
    sock = K.slit_eyes("Ghoul", head, Vector((0, -0.232, 0.03)), 0.16, (0.058, 0.018, 0.024), eye, tilt_deg=-20)
    for i in range(7):  # 乱发：向后飞的墨束
        a = math.radians(-60 + i * 20)
        base = Vector((0.18 * math.sin(a), 0.05, 0.20 + 0.04 * math.cos(a)))
        tip = base + Vector((0.25 * math.sin(a), 0.45 + 0.1 * (i % 2), 0.10 - 0.18 * abs(math.sin(a))))
        obj(f"GhoulHair{i}", K.tube_build(K.curve_points(base, tip, bend=Vector((0, 0, 0.08)), n=6),
                                         lambda t: 0.07 * (1 - t), 6), hair, "inner", head)
    # 手臂：粗壮，长到膝下，墨爪
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"GhoulShoulder{nm}", torso, loc=(0.48 * sx, -0.02, 0.86))
        obj(f"GhoulDelt{nm}", K.ellipsoid((0.19, 0.19, 0.18)), skin, "outer", sh)
        K.limb(f"GhoulUpper{nm}", (0, 0, 0), (0.12 * sx, -0.15, -0.50), 0.15, 0.12, skin, "outer", sh)
        K.limb(f"GhoulFore{nm}", (0.12 * sx, -0.15, -0.50), (0.06 * sx, -0.38, -0.95), 0.12, 0.09, skin, "outer", sh)
        obj(f"GhoulHand{nm}", K.ellipsoid((0.10, 0.12, 0.11)), skin, "outer", sh, loc=(0.06 * sx, -0.42, -1.02))
        for c in (-1, 0, 1):
            K.limb(f"GhoulClaw{nm}{c}", (0.06 * sx + 0.04 * c, -0.48, -1.06), (0.06 * sx + 0.05 * c, -0.56, -1.18),
                   0.022, 0.0, ink, "inner", sh, segs=6)
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"GhoulHip{nm}", pelvis, loc=(0.24 * sx, 0, -0.05))
        K.limb(f"GhoulThigh{nm}", (0, 0, 0), (0.03 * sx, -0.18, -0.48), 0.17, 0.13, skin, "outer", hip)
        knee = B.empty(f"GhoulKnee{nm}", hip, loc=(0.03 * sx, -0.18, -0.48))
        K.limb(f"GhoulShin{nm}", (0, 0, 0), (0, 0.12, -0.44), 0.12, 0.09, skin, "outer", knee)
        obj(f"GhoulFoot{nm}", K.ellipsoid((0.11, 0.18, 0.06)), skin, "outer", knee, loc=(0, 0.04, -0.49))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    sockets = {"eyes": sock, "feet": B.empty("GhoulFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_ghoul(parts, anim, frame, n):
    """move：沉重大步——腿交替前后（膝随摆动屈伸），上身随步左右晃、微起伏，双臂与同侧腿反向摆，破袍飘。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["pelvis"].location.z = 1.05 + 0.010 * math.cos(2 * ph)
    parts["pelvis"].rotation_euler = (0, math.radians(0.8 * math.sin(ph)), math.radians(1.5 * math.sin(ph)))
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-20 * s), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(18 * max(0.0, s)), 0, 0)
        parts[f"arm_{nm}"].rotation_euler = (math.radians(16 * s), 0, 0)
    for ob, c, w, i in parts["rags"]:
        K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, 0.36, 0.10, 0.62, phase=ph, wind=0.25, seed=i + 7,
                                                         tatter=0.4)))
    bpy.context.view_layer.update()
