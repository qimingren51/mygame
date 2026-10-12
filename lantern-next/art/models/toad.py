"""金蟾：三足金蟾，藤黄金身、墨线勾边，嘴里衔一枚方孔钱，背上几点朱砂钱斑。

两条前腿、一条后腿（居中）。眼睛 EYE['toad']（淡金白光），鼓在头顶。只渲染 E（朝镜头偏 30°）。
动画 move：6 帧一跳（蓄力→起跳→最高→下落→落地→回弹）。挂点：eyes、feet。帧尺寸 FRAME["small"]（80px）。
游戏碰撞半径 14 单位 → 身体占地直径约 1.1 米（56px）。
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

HOP = [  # (身体抬高 m, 身体俯仰 deg, 压扁 z, 腿伸展 0..1)
    (0.00, 6, 0.86, 0.0),  # 蓄力
    (0.12, -14, 1.08, 1.0),  # 起跳
    (0.24, -4, 1.04, 0.8),  # 最高
    (0.16, 8, 1.0, 0.4),  # 下落
    (0.00, 4, 0.82, 0.0),  # 落地
    (0.00, 0, 0.95, 0.1),  # 回弹
]


def build_toad():
    I, A = S.INK, S.ACCENT
    gold = K.toon("ToadGold", A["tenghuang"], edge=0.5, seed=41.0)
    belly = K.toon("ToadBelly", S.WASH["tenghuang"], seed=42.0)
    coin = K.toon("ToadCoin", A["zheshi"], seed=43.0)
    spot = K.toon("ToadSpot", A["zhusha"], seed=44.0)
    ink = B.flat_material("ToadInk", I["jiao"])
    eye = B.emissive_material("ToadEye", S.EYE["toad"], 1.0)
    root = B.empty("ToadRoot")
    yaw = K.yaw_pivot("ToadYaw", root, -8, loc=(0.22, 0, 0))  # 帧下方只有 10px：朝镜头偏得少，并整体后移 0.22 米
    body = B.empty("ToadBody", yaw)
    squash = B.empty("ToadSquash", body)
    parts = {"root": root, "body": body, "squash": squash}
    obj = B.mesh_object
    obj("ToadTrunk", K.ellipsoid((0.40, 0.46, 0.25), 24, 14), gold, "outer", squash, loc=(0, 0.06, 0.27))
    obj("ToadBellyM", K.ellipsoid((0.34, 0.36, 0.12), 20, 10), belly, "inner", squash, loc=(0, -0.05, 0.13))
    obj("ToadHead", K.ellipsoid((0.36, 0.28, 0.19), 22, 12), gold, "outer", squash, loc=(0, -0.30, 0.33))
    obj("ToadLip", K.ellipsoid((0.33, 0.05, 0.022), 16, 6), ink, "none", squash, loc=(0, -0.53, 0.27))
    # 方孔钱：衔在嘴前，竖着
    obj("ToadCoin", B.cylinder(0.12, 0.12, 0.03, 20), coin, "inner", squash, loc=(0, -0.60, 0.27),
        rot=(math.radians(90), 0, 0))
    obj("ToadCoinHole", B.cylinder(0.045, 0.045, 0.035, 4), ink, "none", squash, loc=(0, -0.618, 0.27),
        rot=(math.radians(90), 0, math.radians(45)))
    # 眼：鼓在头顶两侧，中间一道焦墨竖瞳
    for sx in (-1, 1):
        obj(f"ToadEyeBall{sx:+d}", K.ellipsoid((0.10, 0.095, 0.09), 14, 8), gold, "outer", squash,
            loc=(0.17 * sx, -0.34, 0.50))
        obj(f"ToadEyeGlow{sx:+d}", K.ellipsoid((0.075, 0.05, 0.065), 12, 6), eye, "none", squash,
            loc=(0.17 * sx, -0.405, 0.52))
        obj(f"ToadPupil{sx:+d}", K.ellipsoid((0.012, 0.014, 0.050), 8, 6), ink, "none", squash,
            loc=(0.17 * sx, -0.452, 0.52))
    sock = B.empty("ToadSocketEyes", squash, loc=(0, -0.45, 0.52))
    # 背上的朱砂钱斑
    for i, (x, y) in enumerate(((0.0, 0.10), (-0.18, 0.18), (0.18, 0.18), (-0.10, 0.34), (0.11, 0.33))):
        obj(f"ToadSpot{i}", B.cylinder(0.045, 0.040, 0.03, 12), spot, "none", squash, loc=(x, y, 0.505 - 0.25 * abs(y - 0.1)))
    # 三条腿：两前（向两侧撑开，像蛙）、一后（居中，折起）
    legs = {}
    for nm, sx in (("FL", 1), ("FR", -1)):
        hip = B.empty(f"ToadHip{nm}", body, loc=(0.22 * sx, -0.22, 0.20))
        K.limb(f"ToadArm{nm}", (0, 0, 0), (0.09 * sx, -0.06, -0.10), 0.065, 0.055, gold, "outer", hip)
        K.limb(f"ToadFore{nm}", (0.09 * sx, -0.06, -0.10), (0.11 * sx, -0.11, -0.19), 0.055, 0.045, gold, "outer", hip)
        obj(f"ToadFoot{nm}", K.ellipsoid((0.075, 0.10, 0.03), 12, 6), gold, "outer", hip, loc=(0.11 * sx, -0.14, -0.195))
        legs[nm] = hip
    hip = B.empty("ToadHipB", body, loc=(0.0, 0.36, 0.20))
    K.limb("ToadThighB", (0, 0, 0), (0, 0.20, -0.06), 0.10, 0.08, gold, "outer", hip)
    K.limb("ToadShinB", (0, 0.20, -0.06), (0, 0.06, -0.17), 0.075, 0.06, gold, "outer", hip)
    obj("ToadFootB", K.ellipsoid((0.10, 0.13, 0.03), 12, 6), gold, "outer", hip, loc=(0, 0.02, -0.195))
    legs["B"] = hip
    parts["legs"] = legs
    sockets = {"eyes": sock, "feet": B.empty("ToadFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_toad(parts, anim, frame, n):
    lift, pitch, sq, ext = HOP[frame % len(HOP)]
    body, squash = parts["body"], parts["squash"]
    body.location.z = lift
    body.rotation_euler.x = math.radians(pitch)
    squash.scale = (1 + (1 - sq) * 0.5, 1 + (1 - sq) * 0.3, sq)
    for nm, hip in parts["legs"].items():
        if nm == "B":
            hip.rotation_euler.x = math.radians(35 * ext)  # 后腿向后蹬直
            hip.location.z = 0.20 - 0.10 * ext
        else:
            hip.rotation_euler.x = math.radians(-25 * ext)  # 前腿向前伸
            hip.location.z = 0.20 - 0.06 * ext
    bpy.context.view_layer.update()
