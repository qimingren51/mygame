"""山石：圆润的卵石 / 太湖石感的块石（细分球 + 低频噪声位移 + 压平的底），平滑着色。

皴笔：Freestyle 的“暗示轮廓线”（suggestive contour，见 bstyle 的 InkCun 集合）会沿着起伏的凹处
画出弯曲的短笔触，比平面棱线更像披麻皴。外轮廓和形线照常。
颜色：亮面清墨（留白感）、中间淡墨、暗面重墨，轮廓处积墨，晕染噪声较大（块面里有深浅斑驳）。

    build_rock("a")  →  (root, parts, sockets)；三个变体 a/b/c
道具用 PROP_ANCHOR，帧尺寸 FRAME["prop"]（96px）。sockets 只有 feet（原点）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector, noise

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402

# 变体：[(尺寸 x,y,z 米, 中心偏移 x,y, 噪声种子, 大起伏, 小起伏, 倾斜)]，一个变体可以由几块石头组成
VARIANTS = {
    "a": [((0.50, 0.32, 0.36), (0.0, 0.0), 1.0, 0.20, 0.07, 0.10)],  # 扁圆的卵石
    "b": [((0.36, 0.28, 0.66), (0.0, 0.0), 4.0, 0.28, 0.10, -0.22)],  # 立石，起伏大（太湖石感）
    "c": [((0.40, 0.28, 0.40), (-0.12, 0.03), 7.0, 0.22, 0.08, 0.15),  # 一大一小两块
          ((0.22, 0.17, 0.20), (0.30, -0.08), 9.0, 0.18, 0.06, -0.1)],
}


def _boulder_build(size, seed, big, small, lean, subdiv=3):
    sx, sy, sz = size
    off = Vector((seed * 3.1, seed * 1.7, seed * 2.3))

    def build(bm):
        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
        for v in bm.verts:
            p = v.co.copy()
            d = 1 + big * noise.noise(p * 1.2 + off) + small * noise.noise(p * 3.3 + off * 2)
            q = p * d
            z = q.z
            z = z * sz if z > 0 else z * sz * 0.25  # 底面压扁
            x = q.x * sx + lean * max(z, 0.0)  # 微微倾斜，有山势
            v.co = Vector((x, q.y * sy, z))
        zmin = min(v.co.z for v in bm.verts)
        for v in bm.verts:
            v.co.z = max(v.co.z - zmin - 0.02, 0.0)  # 底平、坐在地上
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def build_rock(variant: str = "a"):
    I = S.INK
    root = B.empty(f"Rock_{variant}")
    seed = ord(variant)
    mat = B.toon_material(f"RockInk_{variant}", ramp=[I["qing"], I["dan"], I["zhong"]],
                          wash=0.40, wash_scale=3.0, edge=0.6, edge_power=2.5, seed=float(seed))
    for i, (size, (ox, oy), nseed, big, small, lean) in enumerate(VARIANTS[variant]):
        B.mesh_object(f"RockMesh_{variant}{i}", _boulder_build(size, nseed, big, small, lean), mat, "outer", root,
                      loc=(ox, oy, 0.0), smooth=True, sharp_deg=0, cun=True)
    sockets = {"feet": B.empty(f"Rock_{variant}Feet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets
