"""石妖：几块开裂的水墨巨石拼成的佝偻怪物，背上长着淡彩石绿的苔，拳头拖在地上，步子沉重、左右摇晃。

颜色：清墨/淡墨/重墨的风化岩面，腹部与关节压暗，裂隙贴在岩面上；眼睛 EYE['golem']，
藏在头部的焦墨凹缝里。只渲染 E（身体朝镜头偏 22°）。挂点：eyes、feet。帧尺寸 FRAME["golem"]（112px）。
游戏碰撞半径 19 单位 → 身体占地直径约 1.5 米（4×19=76px）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
from stone_lantern import moss_material  # noqa: E402

SCALE = 0.92
HIP_HEIGHT = 0.48


def _weathered_mass(size, seed, exponent=0.78):
    """保留风化起伏，放平大岩面；不把每个身体部位都做成相同的石球。"""
    source = K.boulder_build(size, seed, 0.12, 0.025)

    def build(bm):
        source(bm)
        for vertex in bm.verts:
            for axis, radius in enumerate(size):
                q = vertex.co[axis] / radius
                vertex.co[axis] = math.copysign(abs(q) ** exponent, q) * radius
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _fissure(name, rock, size, marks, material, facing=(0, -1, 0)):
    """少量有方向的风化裂隙贴在岩面上，避免把全身网格边画成碎线。"""
    mesh = rock.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices], [tuple(p.vertices) for p in mesh.polygons])
    outward = Vector(facing).normalized()
    path = []
    knots = [Vector(tuple(a * b for a, b in zip(mark, size))) for mark in marks]
    # 沿每一段重新贴面；只投影端点会让段中间穿进凸岩，裂纹只剩几粒黑点。
    points = [a.lerp(b, i / 6) for a, b in zip(knots, knots[1:]) for i in range(6)] + knots[-1:]
    for point in points:
        hit, normal, _, _ = tree.ray_cast(point + outward * max(size) * 3, -outward)
        if hit is not None:
            path.append(hit + normal * 0.004)
    if len(path) >= 2:
        B.mesh_object(name, K.tube_build(path, lambda t: 0.004 + 0.004 * math.sin(math.pi * t), 5),
                      material, "none", rock, sharp_deg=0)


def build_golem():
    I = S.INK
    k = SCALE
    stone = K.toon("GolemStone", ramp=[S.shade_ramp(I["qing"])[1], I["dan"], I["zhong"]],
                   wash=0.32, wash_scale=3.0, edge=0.32, edge_power=2.5, seed=31.0)
    shaded = K.toon("GolemStoneDark", ramp=[I["dan"], I["zhong"], I["nong"]],
                    wash=0.24, wash_scale=3.0, edge=0.30, seed=32.0)
    moss = moss_material("GolemMoss", coverage=0.58, up=0.58, seed=5.0)
    # 只修改本素材的材质节点：大岩面连续过渡，苔斑降低频率，保留上侧积苔的方向。
    for material in (stone, shaded, moss):
        for node in material.node_tree.nodes:
            if node.type == "VALTORGB":
                node.color_ramp.interpolation = "EASE"
            elif material == moss and node.type == "TEX_NOISE" and node.inputs["Scale"].default_value == 9.0:
                node.inputs["Scale"].default_value = 5.3
                node.inputs["Detail"].default_value = 2.0
    hollow = B.flat_material("GolemHollow", I["jiao"])
    crack = B.flat_material("GolemCrack", I["nong"])
    eye = B.emissive_material("GolemEye", S.EYE["golem"], 1.0)
    root = B.empty("GolemRoot")
    # 让头与胸前岩面露出来；脚底与碰撞中心仍在原点，不借移动锚点制造站立感。
    yaw = K.yaw_pivot("GolemYaw", root, -22)
    body = B.empty("GolemBody", yaw)
    parts = {"root": root, "body": body}

    def rock(name, size, loc, seed, parent, mossy=False, rot=(0, 0, 0), dark=False, exponent=0.78):
        size = tuple(s * k for s in size)
        loc = Vector(loc) * k
        shape = _weathered_mass(size, seed, exponent)
        ob = B.mesh_object(name, shape, shaded if dark else stone, "outer", parent, loc=loc, rot=rot,
                           sharp_deg=0)
        if mossy:
            B.mesh_object(name + "Moss", shape, moss, "none", parent, loc=loc,
                          rot=rot, scale=(1.012, 1.012, 1.012), sharp_deg=0, contour=True)
        return ob

    # 胸肩承重、腹部内收；低矮背脊仍是山石，不做有甲裙与护心镜的翁仲石将。
    rock("GolemBelly", (0.33, 0.29, 0.25), (0, 0.10, 0.65), 1.0, body, dark=True)
    chest = rock("GolemChest", (0.49, 0.35, 0.34), (0, -0.015, 1.04), 2.0, body, mossy=True)
    rock("GolemBackRidge", (0.44, 0.32, 0.22), (0.02, 0.21, 1.27), 12.0, body, mossy=True)
    rock("GolemPelvis", (0.38, 0.27, 0.16), (0, 0.15, 0.46), 13.0, body, dark=True)
    _fissure("GolemChestSeam", chest, (0.49 * k, 0.35 * k, 0.34 * k),
              [(0.26, -1, 0.75), (0.1, -1, 0.25), (0.3, -1, -0.05), (0.16, -1, -0.65)], crack)
    _fissure("GolemSideSeam", chest, (0.49 * k, 0.35 * k, 0.34 * k),
              [(-1, 0.35, 0.7), (-1, 0.10, 0.3), (-1, 0.25, -0.3)], crack, facing=(-1, 0, 0))
    # 头略探出肩带，眉下的深缝藏魂眼；下颌是断裂岩面，不雕成人脸。
    head = B.empty("GolemHead", body, loc=Vector((0, -0.38, 1.31)) * k, rot=(0, 0, math.radians(-12)))
    parts["head"] = head
    crown = rock("GolemCrown", (0.255, 0.235, 0.235), (0, 0, 0.03), 3.0, head, mossy=True)
    rock("GolemBrowLedge", (0.25, 0.085, 0.065), (0, -0.15, 0.055), 16.0, head)
    rock("GolemJaw", (0.20, 0.125, 0.10), (0, -0.075, -0.15), 17.0, head)
    B.mesh_object("GolemEyeCleft", K.ellipsoid((0.19 * k, 0.04 * k, 0.052 * k)), hollow, "none", head,
                  loc=Vector((0, -0.235, -0.015)) * k)
    sock = K.slit_eyes("Golem", head, Vector((0, -0.275, -0.015)) * k, 0.18 * k,
                       (0.048 * k, 0.018 * k, 0.022 * k), eye, tilt_deg=-8)
    _fissure("GolemHeadCrack", crown, (0.255 * k, 0.235 * k, 0.235 * k),
              [(-0.35, -1, 0.75), (-0.12, -1, 0.4), (-0.18, -1, 0.12)], crack)
    # 肩、长臂、扁拳形成向下的重量；两只承重腿从较窄的腹下露出。
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"GolemShoulder{nm}", body, loc=Vector((0.48 * sx, -0.015, 1.12)) * k)
        shoulder = rock(f"GolemShoulderStone{nm}", (0.27, 0.235, 0.22), (0, 0, 0), 4.0 + sx, sh,
                        mossy=sx < 0)
        rock(f"GolemUpperArm{nm}", (0.17, 0.16, 0.27), (0.025 * sx, -0.07, -0.32), 5.0 + sx, sh)
        forearm = rock(f"GolemForearm{nm}", (0.185, 0.18, 0.25), (0.04 * sx, -0.15, -0.68), 6.0 + sx, sh,
                       exponent=0.70)
        rock(f"GolemFist{nm}", (0.24, 0.255, 0.15), (0.04 * sx, -0.21, -0.90), 7.0 + sx, sh, exponent=0.63)
        if sx < 0:
            _fissure(f"GolemShoulderCrack{nm}", shoulder, (0.27 * k, 0.235 * k, 0.22 * k),
                      [(-1, 0.35, 0.65), (-1, 0.08, 0.15), (-1, 0.16, -0.5)], crack, facing=(-1, 0, 0))
            _fissure(f"GolemArmCrack{nm}", forearm, (0.185 * k, 0.18 * k, 0.25 * k),
                      [(-1, -0.45, 0.65), (-1, -0.1, 0.2), (-1, -0.22, -0.6)], crack, facing=(-1, 0, 0))
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"GolemHip{nm}", body, loc=Vector((0.27 * sx, 0.23, HIP_HEIGHT)) * k)
        rock(f"GolemLeg{nm}", (0.215, 0.22, 0.28), (0, 0, -0.16), 8.0 + sx, hip, exponent=0.70)
        foot = rock(f"GolemFoot{nm}", (0.25, 0.30, 0.115), (0, -0.065, -0.37), 9.0 + sx, hip, exponent=0.60)
        parts[f"leg_{nm}"], parts[f"foot_{nm}"] = hip, foot
        parts[f"sole_{nm}"] = -min(vertex.co.z for vertex in foot.data.vertices)
    sockets = {"eyes": sock, "feet": B.empty("GolemFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def _weighted_step(t):
    """每腿五拍承重、三拍低抬回收；返回相对脚步、抬脚量和落脚后的压肩量。"""
    if t < 0.625:
        step = -0.18 + 0.36 * t / 0.625
        return step, 0.0, max(0.0, 1.0 - t / 0.25)
    swing = (t - 0.625) / 0.375
    eased = swing * swing * (3 - 2 * swing)
    return 0.18 - 0.36 * eased, 0.05 * math.sin(math.pi * swing), 0.0


def pose_golem(parts, anim, frame, n):
    """承重脚后送、另一脚低抬前收，肩臂反相；脚底原点不参与视觉位移。"""
    phase = (frame % n) / n
    states = {nm: _weighted_step((phase + offset) % 1.0)
              for nm, offset in (("L", 0.0), ("R", 0.5))}
    body = parts["body"]
    load_l, load_r = states["L"][2], states["R"][2]
    body.rotation_euler = (math.radians(4.0), math.radians(0.7 * (load_l - load_r)), 0)
    body.location = (0, 0, -0.008 * SCALE * (load_l + load_r))
    body_rotation = body.rotation_euler.to_quaternion()
    for nm, sx in (("L", 1), ("R", -1)):
        step, lift, load = states[nm]
        arm = parts[f"arm_{nm}"]
        arm.rotation_euler = (math.radians(-15.0 * step / 0.18), 0, 0)
        arm.location.z = SCALE * (1.12 - 0.026 * load)
        hip, foot = parts[f"leg_{nm}"], parts[f"foot_{nm}"]
        hip.rotation_euler = (math.radians(16.0 * step / 0.18), 0, 0)
        hip_rotation = hip.rotation_euler.to_quaternion()
        # 脚掌不跟着整根短腿翘起。按实际模型最低点落地，地面高度仍由 feet 原点定义。
        foot.rotation_mode = "QUATERNION"
        foot.rotation_quaternion = (body_rotation @ hip_rotation).inverted()
        target = Vector((0.27 * sx * SCALE, (0.23 - 0.065 + step) * SCALE,
                         parts[f"sole_{nm}"] + lift * SCALE))
        hip.location = body_rotation.inverted() @ (target - body.location) - hip_rotation @ foot.location
    parts["head"].rotation_euler = (math.radians(0.8 * math.sin(4 * math.pi * phase + 0.5)), 0,
                                     math.radians(-12))
    bpy.context.view_layer.update()
