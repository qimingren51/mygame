"""奇遇道具：古灯、血祭坛（道具帧 FRAME["prop"]，锚点 PROP_ANCHOR，只画 S 向一帧）。

古灯 ancient_lamp：风化的石座 + 青铜灯柱（赭石铜色，朝上的面泛淡彩石绿的铜锈）+ 铜灯笼（四根立柱围着发光的火窗）
  + 宝顶，约 1.6 米。火窗是发光材质（FLAME_LIGHT）。挂点 flame（火窗中心）、feet。
血祭坛 blood_altar：两层石台，侧面刻回纹（边标记），台面一只石盆，盆里是暗红的发光液面（朱砂色自发光）；
  台面和侧面泼着朱砂血迹、往下淌。挂点 glow（盆心）、feet。
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
from stone_lantern import moss_material, _prism  # noqa: E402


def _mark_horizontal(ob, keep=0.9, seed=0):
    me = ob.data
    rng = np.random.default_rng(seed)
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        v0, v1 = (me.vertices[i].co for i in e.vertices)
        d = v1 - v0
        vals.append(abs(d.z) < 0.2 * d.length and rng.random() < keep)
    attr.data.foreach_set("value", vals)


def build_ancient_lamp():
    I, A = S.INK, S.ACCENT
    stone = K.toon("LampStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.4, edge=0.5, seed=81.0)
    bronze = K.toon("LampBronze", A["zheshi"], wash=0.3, edge=0.5, seed=82.0)
    patina = moss_material("LampPatina", coverage=0.55, up=0.2, seed=8.0)
    flame = B.emissive_material("LampFlame", S.FLAME_LIGHT, 1.0)
    inner = B.flat_material("LampInner", I["nong"])
    root = B.empty("AncientLamp")
    obj = B.mesh_object
    obj("LampBase", _prism(0.30, 0.28, 0.0, 0.10, seg=8, rot=math.radians(22.5)), stone, "outer", root, smooth=False)
    obj("LampBase2", _prism(0.20, 0.17, 0.10, 0.22, seg=8, rot=math.radians(22.5)), stone, "outer", root, smooth=False)
    for nm, build in (("LampPillar", B.lathe([(0.075, 0.22), (0.06, 0.40), (0.055, 0.95), (0.07, 1.00), (0.05, 1.04)], 12)),
                      ("LampCup", B.lathe([(0.05, 1.04), (0.16, 1.10), (0.18, 1.13), (0.17, 1.15)], 12))):
        obj(nm, build, bronze, "outer", root, sharp_deg=50)
        obj(nm + "Patina", build, patina, "none", root, scale=(1.03, 1.03, 1.0), sharp_deg=50, contour=True)
    # 灯笼：火窗（发光方块）+ 四根铜立柱 + 宝顶
    obj("LampFlameBox", K.ellipsoid((0.10, 0.10, 0.12), 12, 8), flame, "none", root, loc=(0, 0, 1.27))
    obj("LampFloor", B.cylinder(0.15, 0.15, 0.03, 8), inner, "inner", root, loc=(0, 0, 1.16))
    for i in range(4):
        a = math.radians(45 + 90 * i)
        K.limb(f"LampPost{i}", (0.14 * math.cos(a), 0.14 * math.sin(a), 1.15), (0.13 * math.cos(a), 0.13 * math.sin(a), 1.42),
               0.022, 0.02, bronze, "inner", root, segs=6)
    roof = B.lathe([(0.25, 1.41), (0.24, 1.44), (0.14, 1.50), (0.06, 1.55), (0.03, 1.57)], 8,
                   radial=lambda th, z: 1 + 0.10 * abs(math.cos(2 * th)) ** 4)
    obj("LampRoof", roof, bronze, "outer", root, smooth=False)
    obj("LampRoofPatina", roof, patina, "none", root, smooth=False, scale=(1.02, 1.02, 1.01), contour=True)
    obj("LampFinial", K.ellipsoid((0.04, 0.04, 0.05), 10, 6), bronze, "outer", root, loc=(0, 0, 1.61))
    sockets = {"flame": B.empty("LampSocketFlame", root, loc=(0, 0, 1.27)), "feet": B.empty("LampFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


def _splat_build(r, seed, n=12):
    """一摊血迹：边缘参差的扁圆片（贴在面上）。"""
    rng = np.random.default_rng(seed)
    radii = r * rng.uniform(0.55, 1.15, n)

    def build(bm):
        c = bm.verts.new((0, 0, 0))
        ring = [bm.verts.new((radii[i] * math.cos(2 * math.pi * i / n), radii[i] * math.sin(2 * math.pi * i / n), 0))
                for i in range(n)]
        for i in range(n):
            bm.faces.new((c, ring[i], ring[(i + 1) % n]))
    return build


def build_blood_altar():
    I, A = S.INK, S.ACCENT
    stone = K.toon("AltarStone", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.4, edge=0.5, seed=91.0)
    blood = K.toon("AltarBlood", A["zhusha"], wash=0.2, edge=0.2, seed=92.0)
    pool = B.emissive_material("AltarGlow", A["zhusha"], 1.0)
    root = B.empty("BloodAltar")
    obj = B.mesh_object
    lower = obj("AltarLower", _prism(0.62, 0.58, 0.0, 0.16, seg=4, rot=math.radians(45)), stone, "outer", root,
                smooth=False, scale=(1.0, 0.72, 1.0))
    upper = obj("AltarUpper", _prism(0.50, 0.46, 0.16, 0.44, seg=4, rot=math.radians(45)), stone, "outer", root,
                smooth=False, scale=(1.0, 0.70, 1.0))
    # 回纹：上层侧面加几道水平细分再标边（像刻出来的纹带）
    for ob in (lower, upper):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        side = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.05]
        bmesh.ops.subdivide_edges(bm, edges=side, cuts=3, use_grid_fill=True)
        bm.to_mesh(ob.data)
        bm.free()
        _mark_horizontal(ob, keep=0.4, seed=3)
    obj("AltarRim", B.lathe([(0.0, 0.44), (0.30, 0.44), (0.32, 0.50), (0.28, 0.52), (0.24, 0.48)], 16, cap_top=False),
        stone, "outer", root, sharp_deg=50, scale=(1.0, 0.8, 1.0))
    obj("AltarPool", B.cylinder(0.25, 0.25, 0.01, 16), pool, "none", root, loc=(0, 0, 0.485), scale=(1.0, 0.8, 1.0))
    # 血迹：台面、侧面、地上几摊，正面有往下淌的痕
    for i, (pos, r, rot) in enumerate((((0.34, -0.10, 0.443), 0.10, (0, 0, 0)), ((-0.30, 0.12, 0.443), 0.08, (0, 0, 0)),
                                       ((0.20, -0.33, 0.30), 0.09, (math.radians(90), 0, 0)),
                                       ((-0.25, -0.44, 0.10), 0.07, (math.radians(90), 0, 0)),
                                       ((0.45, -0.55, 0.005), 0.12, (0, 0, 0)))):
        obj(f"AltarStain{i}", _splat_build(r, 10 + i), blood, "none", root, loc=pos, rot=rot, smooth=False)
    for i, x in enumerate((0.12, -0.05)):
        drip = K.curve_points((x, -0.33, 0.44), (x + 0.01, -0.335, 0.20 - 0.06 * i), n=5)
        obj(f"AltarDrip{i}", K.tube_build(drip, lambda t: 0.018 * (1 - 0.5 * t) + 0.004, 6, flat=0.4), blood, "none",
            root)
    sockets = {"glow": B.empty("AltarSocketGlow", root, loc=(0, 0, 0.49)), "feet": B.empty("AltarFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets
