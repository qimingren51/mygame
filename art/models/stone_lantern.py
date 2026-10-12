"""石灯笼：底座、灯柱、托台、火袋（带窗，内有暖光）、宝盖（翘檐）、宝珠，总高约 1.4 米。

颜色：石头清墨/淡墨/重墨三档；朝上的面零星长着淡彩石绿的苔（独立的苔壳，噪声镂空，不描线）；
窗口是发光材质（FLAME_LIGHT），夜里叠加用的发光遮罩从同一次渲染得到。
道具用 PROP_ANCHOR，帧尺寸 FRAME["prop"]（96px）。挂点：flame（正面窗口中心）、feet（原点）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402

HEIGHT = 1.40
BOX_Z = (0.80, 1.05)  # 火袋上下


def moss_material(name="Moss", coverage=0.58, up=0.45, seed=0.0):
    """苔：淡彩石绿三档；只留朝上（法线 z > up）且噪声大于阈值的地方，其余透明。"""
    m = B.toon_material(name, S.WASH["shilv"], wash=0.2, edge=0.2, seed=seed)
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    link = out.inputs["Surface"].links[0]
    src = link.from_socket
    nt.links.remove(link)
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], sep.inputs[0])
    g1 = N.new("ShaderNodeMath"); g1.operation = "GREATER_THAN"; g1.inputs[1].default_value = up
    L.new(sep.outputs["Z"], g1.inputs[0])
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 9.0
    nz.inputs["Detail"].default_value = 4.0
    nz.noise_dimensions = "4D"  # 先切到 4D，W 插口才可用
    nz.inputs["W"].default_value = seed
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    g2 = N.new("ShaderNodeMath"); g2.operation = "GREATER_THAN"; g2.inputs[1].default_value = coverage
    L.new(nz.outputs["Fac"], g2.inputs[0])
    both = N.new("ShaderNodeMath"); both.operation = "MULTIPLY"
    L.new(g1.outputs["Value"], both.inputs[0]); L.new(g2.outputs["Value"], both.inputs[1])
    tr = N.new("ShaderNodeBsdfTransparent")
    mix = N.new("ShaderNodeMixShader")
    L.new(both.outputs["Value"], mix.inputs["Fac"])
    L.new(tr.outputs["BSDF"], mix.inputs[1])
    L.new(src, mix.inputs[2])
    L.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


def _prism(r_bot, r_top, z0, z1, seg=6, rot=math.radians(30)):
    def build(bm):
        bot = [bm.verts.new((r_bot * math.cos(rot + 2 * math.pi * i / seg), r_bot * math.sin(rot + 2 * math.pi * i / seg), z0))
               for i in range(seg)]
        top = [bm.verts.new((r_top * math.cos(rot + 2 * math.pi * i / seg), r_top * math.sin(rot + 2 * math.pi * i / seg), z1))
               for i in range(seg)]
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((bot[i], bot[j], top[j], top[i]))
        bm.faces.new(list(reversed(bot)))
        bm.faces.new(top)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _box(w, h, d):
    """面朝 -Y 的长方块：宽 w（x）、高 h（z）、厚 d（y）。"""
    def build(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    return build


def _roof_build(seg=6, rot=math.radians(30)):
    """宝盖：六角，檐口外缘略向上翘（每个角再挑高一点）。"""
    prof = [(0.33, 1.05), (0.335, 1.085), (0.25, 1.13), (0.15, 1.19), (0.07, 1.245), (0.035, 1.27)]

    def build(bm):
        rings = []
        n = seg * 4
        for r, z in prof:
            ring = []
            for i in range(n):
                th = rot + 2 * math.pi * i / n
                corner = abs(math.cos(seg / 2 * (th - rot)))  # 1 在角上
                rr = r * (0.90 + 0.10 * corner)
                zz = z + (0.035 * corner ** 6 if r > 0.3 else 0.0)
                ring.append(bm.verts.new((rr * math.cos(th), rr * math.sin(th), zz)))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            for i in range(n):
                bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def build_stone_lantern():
    I = S.INK
    root = B.empty("StoneLantern")
    stone = B.toon_material("StoneInk", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.35, wash_scale=4.0,
                            edge=0.5, seed=21.0)
    inner = B.flat_material("StoneInside", I["nong"])
    glow = B.emissive_material("StoneFlame", S.FLAME_LIGHT, 1.0)
    moss = moss_material(seed=3.0)
    obj = B.mesh_object
    pieces = [
        ("Base", _prism(0.30, 0.29, 0.0, 0.09)),
        ("Base2", _prism(0.23, 0.20, 0.09, 0.17)),
        ("Pillar", _prism(0.095, 0.085, 0.17, 0.72, seg=8, rot=math.radians(22.5))),
        ("Deck", _prism(0.22, 0.24, 0.72, 0.80)),
    ]
    for name, build in pieces:
        obj(name, build, stone, "outer", root, smooth=False)
        obj(name + "Moss", build, moss, "none", root, smooth=False, scale=(1.015, 1.015, 1.012), contour=True)
    # 火袋：六角框，正面与背面开窗（窗里发光），两侧小圆窗
    obj("Box", _prism(0.16, 0.15, BOX_Z[0], BOX_Z[1]), stone, "outer", root, smooth=False)
    wz = (BOX_Z[0] + BOX_Z[1]) / 2
    apothem = 0.16 * math.cos(math.radians(30))
    for k, ang in enumerate((-90, 90)):  # -90 = 正面（-Y）
        a = math.radians(ang)
        n = Vector((math.cos(a), math.sin(a), 0))
        rz = (0, 0, a + math.radians(90))  # 把面朝 -Y 的方块转到朝 n
        obj(f"WindowRim{k}", _box(0.13, 0.16, 0.012), inner, "inner", root, smooth=False,
            loc=n * (apothem + 0.004) + Vector((0, 0, wz)), rot=rz)
        obj(f"Window{k}", _box(0.09, 0.12, 0.010), glow, "none", root, smooth=False,
            loc=n * (apothem + 0.010) + Vector((0, 0, wz - 0.005)), rot=rz)
    obj("Roof", _roof_build(), stone, "outer", root, smooth=False)
    obj("RoofMoss", _roof_build(), moss, "none", root, smooth=False, scale=(1.01, 1.01, 1.008), contour=True)
    obj("Jewel", B.uv_sphere(1.0, 12, 8, scale=(0.055, 0.055, 0.06)), stone, "outer", root, loc=(0, 0, 1.31))
    obj("JewelTip", B.cylinder(0.03, 0.0, 0.05, 8), stone, "inner", root, loc=(0, 0, 1.375))
    sock_flame = B.empty("SocketFlame", root, loc=(0, -apothem - 0.012, wz))
    sockets = {"flame": sock_flame, "feet": B.empty("StoneLanternFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets
