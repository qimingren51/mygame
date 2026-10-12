"""石妖：几块开裂的水墨巨石拼成的佝偻怪物，背上长着淡彩石绿的苔，拳头拖在地上，步子沉重、左右摇晃。

颜色：淡墨三档（比山石深一档，和地上的石头区分开），裂纹用暗示轮廓线（皴笔）；眼睛 EYE['golem']，
藏在头部的焦墨凹缝里。只渲染 E（身体朝镜头偏 25°）。挂点：eyes、feet。帧尺寸 FRAME["golem"]（112px）。
游戏碰撞半径 19 单位 → 身体占地直径约 1.5 米（4×19=76px）。
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
from stone_lantern import moss_material  # noqa: E402

SCALE = 0.92
DEPTH_SHIFT = 0.30  # 身体整体向后（远离镜头）挪，锚点在身体前沿附近；见 kit 说明


def build_golem():
    I = S.INK
    k = SCALE
    stone = K.toon("GolemStone", I["dan"], wash=0.40, wash_scale=3.0, edge=0.6, edge_power=2.5, seed=31.0)
    moss = moss_material("GolemMoss", coverage=0.54, up=0.50, seed=5.0)
    hollow = B.flat_material("GolemHollow", I["jiao"])
    eye = B.emissive_material("GolemEye", S.EYE["golem"], 1.0)
    root = B.empty("GolemRoot")
    # 朝镜头只偏 12°：帧下方只有 14px（ANCHOR 0.875），身体朝镜头一侧的厚度不能超过约 0.55 米
    # 再整体往远离镜头的方向挪 0.2 米（E 向时建模 +X = 世界 +Y），画面上约上移 5px，不贴下边
    yaw = K.yaw_pivot("GolemYaw", root, -12, loc=(DEPTH_SHIFT, 0, 0))
    body = B.empty("GolemBody", yaw)
    parts = {"root": root, "body": body}

    def rock(name, size, loc, seed, parent, mossy=False, rot=(0, 0, 0)):
        size = tuple(s * k for s in size)
        loc = Vector(loc) * k
        ob = B.mesh_object(name, K.boulder_build(size, seed, 0.22, 0.08), stone, "outer", parent, loc=loc, rot=rot,
                           sharp_deg=0, cun=True)
        if mossy:
            B.mesh_object(name + "Moss", K.boulder_build(size, seed, 0.22, 0.08), moss, "none", parent, loc=loc,
                          rot=rot, scale=(1.03, 1.03, 1.03), sharp_deg=0, contour=True)
        return ob

    # 躯干：一大块，背上隆起一块（长苔）
    rock("Torso", (0.60, 0.50, 0.50), (0, 0.10, 0.88), 1.0, body, mossy=True)
    rock("Hump", (0.46, 0.40, 0.30), (0.02, 0.18, 1.26), 2.0, body, mossy=True)
    # 头：低低地探在前面；焦墨凹缝里两只眼
    head = B.empty("GolemHead", body, loc=Vector((0, -0.46, 0.98)) * k, rot=(0, 0, math.radians(-20)))
    parts["head"] = head
    rock("Head", (0.27, 0.25, 0.22), (0, 0, 0), 3.0, head, mossy=True)
    B.mesh_object("GolemBrow", K.ellipsoid((0.20 * k, 0.07 * k, 0.07 * k)), hollow, "inner", head,
                  loc=Vector((0, -0.21, 0.0)) * k)
    sock = K.slit_eyes("Golem", head, Vector((0, -0.265, 0.005)) * k, 0.15 * k, (0.045 * k, 0.02 * k, 0.026 * k), eye,
                       tilt_deg=-12)
    # 手臂：肩、上臂、前臂、拳（拳头几乎拖地）
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"GolemShoulder{nm}", body, loc=Vector((0.50 * sx, -0.02, 1.08)) * k)
        rock(f"Shoulder{nm}", (0.26, 0.24, 0.22), (0, 0, 0), 4.0 + sx, sh)
        rock(f"UpperArm{nm}", (0.18, 0.17, 0.24), (0.04 * sx, -0.12, -0.36), 5.0 + sx, sh)
        rock(f"Forearm{nm}", (0.17, 0.17, 0.22), (0.03 * sx, -0.20, -0.68), 6.0 + sx, sh)
        rock(f"Fist{nm}", (0.20, 0.24, 0.17), (0.0 * sx, -0.24, -0.93), 7.0 + sx, sh)
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"GolemHip{nm}", body, loc=Vector((0.26 * sx, 0.24, 0.46)) * k)
        rock(f"Leg{nm}", (0.20, 0.20, 0.22), (0, 0, -0.14), 8.0 + sx, hip)
        rock(f"Foot{nm}", (0.22, 0.26, 0.12), (0, -0.05, -0.36), 9.0 + sx, hip)
        parts[f"leg_{nm}"] = hip
    sockets = {"eyes": sock, "feet": B.empty("GolemFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_golem(parts, anim, frame, n):
    """move：沉重的摇摆步——身体左右滚（绕前后轴）、轻微起伏；两臂交替前后摆、拳头擦地；短腿交替迈步。"""
    ph = 2 * math.pi * (frame % n) / n
    body = parts["body"]
    # 摆幅都很小：配准检查量的是背上的最高点（FOOT_TOLERANCE_PX=1.5）
    body.rotation_euler = (math.radians(4 + 0.6 * math.sin(2 * ph)), math.radians(1.2 * math.sin(ph)), 0)
    body.location.z = 0.010 * math.cos(2 * ph)
    for nm, sgn in (("L", 1), ("R", -1)):
        parts[f"arm_{nm}"].rotation_euler = (math.radians(14 * sgn * math.sin(ph)), 0, 0)
        parts[f"leg_{nm}"].rotation_euler = (math.radians(-10 * sgn * math.sin(ph)), 0, 0)
        parts[f"leg_{nm}"].location.z = SCALE * 0.46 + 0.04 * max(0.0, sgn * math.sin(ph))
    parts["head"].rotation_euler = (math.radians(2 * math.sin(2 * ph + 0.5)), 0, math.radians(-20))
    bpy.context.view_layer.update()
