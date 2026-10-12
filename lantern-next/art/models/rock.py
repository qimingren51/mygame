"""山石：随机点集的凸包，平直着色的大块面；Freestyle 折痕线落在棱上，像皴法的笔触。

颜色：亮面清墨（留白感）、中间淡墨、暗面重墨，轮廓处积墨更重，晕染噪声更大（块面里有深浅斑驳）。
build_rock(seed) 返回 (root, parts, sockets)；sockets 只有 feet（原点，石头底面中心）。
帧尺寸 FRAME["prop"]（96px）。
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
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402


def _rock_build(seed: int, size=(0.48, 0.38, 0.50), n_pts=34):
    rng = np.random.default_rng(seed)

    def build(bm):
        pts = []
        for _ in range(n_pts):
            v = rng.normal(size=3)
            v /= np.linalg.norm(v)
            r = rng.uniform(0.78, 1.0)
            x, y, z = v * r * np.array(size)
            z = abs(z) * (1.25 if z > 0 else 0.25)  # 底面压平，顶部高耸
            x += 0.25 * z * (1 if seed % 2 else -1)  # 微微倾斜，有山势
            pts.append(bm.verts.new((x, y, z)))
        for x, y in ((0.35, 0.0), (-0.35, 0.05), (0.0, 0.3), (0.05, -0.3)):  # 底座
            pts.append(bm.verts.new((x * size[0] / 0.5, y * size[1] / 0.4, 0.0)))
        bmesh.ops.convex_hull(bm, input=pts)
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
        # 合并近似共面的小面，块面更大更干脆
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(6), verts=bm.verts, edges=bm.edges)
        # 底面中心对准原点（倾斜会让包围盒偏到一边）
        xs = [v.co.x for v in bm.verts]
        ys = [v.co.y for v in bm.verts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        for v in bm.verts:
            v.co.x -= cx
            v.co.y -= cy
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def mark_cun_strokes(ob, seed: int, min_deg=14.0, keep=0.7):
    """皴笔：把二面角大于 min_deg 的棱随机挑一部分标成 Freestyle 边标记（内线集合会画出来）。
    Blender 4+ 的边标记是名为 freestyle_edge 的布尔边属性。"""
    me = ob.data
    rng = np.random.default_rng(seed + 100)
    edge_faces: dict = {}
    for poly in me.polygons:
        for ek in poly.edge_keys:
            edge_faces.setdefault(ek, []).append(poly.normal.copy())
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        ns = edge_faces.get(tuple(sorted(e.vertices)), [])
        ang = math.degrees(ns[0].angle(ns[1])) if len(ns) == 2 else 0.0
        vals.append(ang > min_deg and rng.random() < keep)
    attr.data.foreach_set("value", vals)
    return sum(vals)


def build_rock(seed: int = 1, scale: float = 1.15):
    I = S.INK
    root = B.empty(f"Rock{seed}")
    mat = B.toon_material(f"RockInk{seed}", ramp=[I["qing"], I["dan"], I["zhong"]],
                          wash=0.42, wash_scale=3.6, edge=0.75, edge_power=2.5, seed=float(seed))
    # 前后（y）只给 0.27：96px 帧里锚点下方只有 12px，石头前缘不能超出
    size = (0.48 * scale, 0.27 * scale, 0.50 * scale)
    ob = B.mesh_object(f"RockMesh{seed}", _rock_build(seed, size), mat, "outer", root, smooth=False)
    mark_cun_strokes(ob, seed)
    sockets = {"feet": B.empty(f"Rock{seed}Feet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets
