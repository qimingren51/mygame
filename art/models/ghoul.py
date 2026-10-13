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
    yaw = K.yaw_pivot("GhoulYaw", root, -10)
    body = B.empty("GhoulBody", yaw)
    body.scale = (1.05, 1.05, 1.05)  # 比人形高大一圈（BIG_ENEMY_ANCHOR 下头顶只剩 80% 帧高）
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
    for sx in (-1, 1):  # 獠牙：从下颌向上翻出，又大又弯
        tusk = K.curve_points((0.10 * sx, -0.21, -0.20), (0.15 * sx, -0.27, 0.02), bend=Vector((0.03 * sx, -0.04, 0)), n=6)
        obj(f"GhoulTusk{sx:+d}", K.tube_build(tusk, lambda t: 0.048 * (1 - t) ** 0.8 + 0.002, 8), bone, "outer", head)
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
        obj(f"GhoulDelt{nm}", K.ellipsoid((0.22, 0.22, 0.21)), skin, "outer", sh)
        K.limb(f"GhoulUpper{nm}", (0, 0, 0), (0.12 * sx, -0.15, -0.50), 0.15, 0.12, skin, "outer", sh)
        obj(f"GhoulBicep{nm}", K.ellipsoid((0.15, 0.16, 0.22)), skin, "outer", sh, loc=(0.07 * sx, -0.10, -0.26),
            rot=(math.radians(-15), 0, 0))  # 隆起的二头肌
        K.limb(f"GhoulFore{nm}", (0.12 * sx, -0.15, -0.50), (0.06 * sx, -0.38, -0.95), 0.13, 0.09, skin, "outer", sh)
        obj(f"GhoulForeM{nm}", K.ellipsoid((0.13, 0.13, 0.20)), skin, "outer", sh, loc=(0.10 * sx, -0.23, -0.64),
            rot=(math.radians(-30), 0, 0))  # 前臂肌肉
        obj(f"GhoulHand{nm}", K.ellipsoid((0.13, 0.14, 0.12)), skin, "outer", sh, loc=(0.06 * sx, -0.43, -1.02))
        for c in (-1.5, -0.5, 0.5, 1.5):  # 四根弯曲的墨爪
            a0 = Vector((0.06 * sx + 0.045 * c, -0.50, -1.04))
            claw = K.curve_points(a0, a0 + Vector((0.02 * c, -0.12, -0.14)), bend=Vector((0, -0.04, 0.02)), n=5)
            obj(f"GhoulClaw{nm}{c}", K.tube_build(claw, lambda t: 0.026 * (1 - t) + 0.002, 6), ink, "inner", sh)
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"GhoulHip{nm}", pelvis, loc=(0.24 * sx, 0, -0.05))
        K.limb(f"GhoulThigh{nm}", (0, 0, 0), (0.03 * sx, -0.18, -0.48), 0.19, 0.14, skin, "outer", hip)
        knee = B.empty(f"GhoulKnee{nm}", hip, loc=(0.03 * sx, -0.18, -0.48))
        K.limb(f"GhoulShin{nm}", (0, 0, 0), (0, 0.12, -0.44), 0.13, 0.09, skin, "outer", knee)
        obj(f"GhoulCalf{nm}", K.ellipsoid((0.12, 0.13, 0.18)), skin, "outer", knee, loc=(0, 0.08, -0.16))  # 小腿肚
        obj(f"GhoulFoot{nm}", K.ellipsoid((0.11, 0.18, 0.06)), skin, "outer", knee, loc=(0, 0.04, -0.49))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    sockets = {"eyes": sock, "feet": B.empty("GhoulFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


# 冲撞（charge，6 帧不循环）：0–1 低头蓄力（第 1 帧最低：上身前压、双角朝前、后腿往后刨地，游戏在预警期间停在这一帧），
# 2–5 低头猛冲的跑步循环（冲锋持续时 2–5 可以循环：meta loop_from=2）。
# 蓄力帧：(骨盆高, 上身前倾 deg, 头俯仰 deg, 左髋, 左膝, 右髋, 右膝, 左臂, 右臂, 风)
GHOUL_WINDUP = [
    (0.98, 36, 12, -14, 22, 18, 26, -10, 4, 0.30),
    (0.92, 46, 20, -22, 34, 30, 34, -18, -2, 0.40),  # 蓄力到底
]


def _rest_ghoul(parts):
    parts["torso"].rotation_euler = (math.radians(22), 0, 0)
    parts["head"].rotation_euler = (math.radians(-24), 0, math.radians(-22))


def _pose_ghoul_charge(parts, frame):
    if frame < 2:
        z, lean, head, hl, kl, hr, kr, al, ar, wind = GHOUL_WINDUP[frame]
        ph = 0.5 * frame
        parts["pelvis"].location.z = z
        parts["pelvis"].rotation_euler = (0, 0, 0)
        parts["torso"].rotation_euler = (math.radians(lean), 0, 0)
        parts["head"].rotation_euler = (math.radians(-24 + head - (lean - 22) * 0.35), 0, math.radians(-22))  # 低头、角朝前
        for nm, h, k, a in (("L", hl, kl, al), ("R", hr, kr, ar)):
            parts[f"hip_{nm}"].rotation_euler = (math.radians(h), 0, 0)
            parts[f"knee_{nm}"].rotation_euler = (math.radians(k), 0, 0)
            parts[f"arm_{nm}"].rotation_euler = (math.radians(a), 0, 0)
    else:  # 冲：4 帧一个跑步循环（相位 0, 90, 180, 270°），步子大、身子压低前冲、双臂大摆
        ph = 2 * math.pi * (frame - 2) / 4 + 0.6
        wind = 0.75
        # 冲锋时 2–5 帧循环播放：上身不晃不扭、只轻轻起伏（佝偻的背是锚点正上方剪影的顶，斜得很陡，
        # 身子稍一转，自检量到的顶就上下跳好几个像素）；跑的劲头靠腿、手臂和破袍
        parts["pelvis"].location.z = 0.97 + 0.012 * math.cos(2 * ph)
        parts["pelvis"].rotation_euler = (0, 0, 0)
        parts["torso"].rotation_euler = (math.radians(42), 0, 0)
        parts["head"].rotation_euler = (math.radians(-24 + 14), 0, math.radians(-22))
        for nm, sgn in (("L", 1), ("R", -1)):
            s_ = sgn * math.sin(ph)
            c_ = sgn * math.cos(ph)
            parts[f"hip_{nm}"].rotation_euler = (math.radians(-34 * s_ - 6), 0, 0)
            parts[f"knee_{nm}"].rotation_euler = (math.radians(12 + 40 * max(0.0, c_)), 0, 0)
            parts[f"arm_{nm}"].rotation_euler = (math.radians(16 * s_ - 2), 0, 0)  # 后摆不过背线
    for ob, c, w, i in parts["rags"]:
        K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, 0.36, 0.10, 0.62, phase=ph, wind=wind, seed=i + 7,
                                                         tatter=0.4)))
    bpy.context.view_layer.update()


def pose_ghoul(parts, anim, frame, n):
    """move：沉重大步——腿交替前后（膝随摆动屈伸），上身随步左右晃、微起伏，双臂与同侧腿反向摆，破袍飘。
    charge：见 GHOUL_WINDUP 和 _pose_ghoul_charge。"""
    _rest_ghoul(parts)
    if anim == "charge":
        return _pose_ghoul_charge(parts, frame)
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
