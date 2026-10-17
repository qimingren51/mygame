"""石妖（精修三维）：青灰山石垒成的矮胖身子。

设定（LORE 附录）：山石在长夜里吸了魂，就成了精。走得慢，皮硬，敲碎了，魂从石缝里飞出来。
造型：一摞垒起来的山石——两块矮墩墩的腿石，上面压一块又宽又扁的“肚石”、一块略小的“胸石”，往前探出一块扁头石，
头顶再码一块小石片、一颗石子（像路边垒的石堆）；两臂各是三块石头（肩、小臂、拳），拳头大、垂到膝下。
石头是斧劈出来的块面（椭球按随机的平面削出平面，块面之间有硬棱），青灰：暗部偏暖的褐灰、亮部偏冷的青灰，
棱上描形线、凹处有皴笔（暗示轮廓线）。石与石之间夹着一片发光的魂（白天是暗暖的一线，夜里透出暖光），
头石正面一道焦墨深缝，缝里两只暖橙的眼。
动画 move 8 帧：两条腿石交替抬起迈步，身子一步一沉、左右晃；越往上的石头晃得越晚、越多（垒起来的东西那样
摇摇欲坠），头顶的石片、石子跟着磕；两臂和腿反着摆，拳头擦着地。
帧 224²（2 倍），锚点 (0.5, 0.8)（大妖物）。

    root, parts, sockets = build_golem()
    pose_golem(parts, "move", i, 8)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector, noise as mnoise

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
import v2kit as V2  # noqa: E402

I, A_ = S.INK, S.ACCENT
EYE = "#FFB46B"  # 同 enemies.ron 的 eye
EYE_HOT = "#FFF0D2"
SEAM_DAY = "#2B231D"  # 石缝里的魂：白天只是一道暗暖的缝
GLOW = "#FFB46B"
# 青灰的色带（d 从暗到亮）：暗部偏暖的褐灰 → 青灰 → 亮部偏冷、发白
STONE_STOPS = [(0.00, "#25262A"), (0.20, "#323538"), (0.38, "#444C51"), (0.54, "#566268"), (0.68, "#6B787C"),
               (0.84, "#879497"), (1.00, "#A6AFAA")]
RIM = S.mix("#BFD3DA", I["qing"], 0.3)
SCALE = 1.22  # 整体（米）：身高约 42 单位，正面最前约 18 单位（碰撞半径 19）
YAW = -10.0  # 身子朝镜头偏一点（看得到近侧的臂和脸）

# 石头：名字 → (父, 中心（米，相对父）, 半径（左右, 前后, 上下）, 转角（度 xyz）, 种子, 削的深浅)
# 布局：两块腿石上压一块又宽又扁的肚石；背上一块驼起的大石（往前倾），头石从它前面低低地探出来；
# 背顶上码一块石片、一颗石子（垒石堆的样子）。两臂各三块（肩、小臂、拳），拳垂到膝下。
STONES = {
    "LegN": ("leg_n", (0.0, 0.0, 0.0), (0.13, 0.15, 0.15), (0, 0, 8), 1, 0.24),
    "LegF": ("leg_f", (0.0, 0.0, 0.0), (0.13, 0.15, 0.15), (0, 0, -6), 2, 0.24),
    "Belly": ("s0", (0.0, 0.0, 0.0), (0.44, 0.46, 0.24), (0, 3, 0), 3, 0.24),
    "Back": ("s1", (0.0, 0.0, 0.0), (0.36, 0.38, 0.22), (12, -4, 10), 4, 0.26),
    "Head": ("s2", (0.0, 0.0, 0.0), (0.22, 0.23, 0.15), (-8, 5, -8), 5, 0.24),
    "Cap": ("s3", (0.0, 0.0, 0.0), (0.15, 0.17, 0.06), (4, -6, 25), 6, 0.2),
    "Pebble": ("s4", (0.0, 0.0, 0.0), (0.07, 0.08, 0.045), (0, 10, 40), 7, 0.16),
    "ShoulderN": ("arm_n", (0.0, 0.0, 0.0), (0.14, 0.15, 0.13), (0, 10, 0), 8, 0.24),
    "ForearmN": ("arm_n", (0.02, -0.08, -0.27), (0.11, 0.12, 0.15), (8, 0, 15), 9, 0.24),
    "FistN": ("arm_n", (0.02, -0.14, -0.52), (0.15, 0.16, 0.13), (0, -8, -10), 10, 0.22),
    "ShoulderF": ("arm_f", (0.0, 0.0, 0.0), (0.14, 0.15, 0.13), (0, -10, 0), 11, 0.24),
    "ForearmF": ("arm_f", (-0.02, -0.08, -0.27), (0.11, 0.12, 0.15), (8, 0, -15), 12, 0.24),
    "FistF": ("arm_f", (-0.02, -0.14, -0.52), (0.15, 0.16, 0.13), (0, 8, 10), 13, 0.22),
}
# 骨架（米，静止、绝对）：石头之间留一道缝（夹着发光的魂）
JOINTS = {"leg_n": (-0.18, 0.04, 0.14), "leg_f": (0.18, 0.07, 0.14), "s0": (0.0, 0.02, 0.44),
          "s1": (0.0, 0.10, 0.915), "s2": (0.0, -0.30, 0.86), "s3": (0.02, 0.16, 1.207), "s4": (0.0, 0.18, 1.318),
          "arm_n": (-0.42, -0.06, 0.90), "arm_f": (0.42, 0.04, 0.90)}
SEAMS = [("s0", "s1", (0.27, 0.28), 0.6875), ("s1", "s3", (0.11, 0.13), 1.141)]  # (下, 上, 半径, 高)
# 收尾修整（缝里的光）：腿石和肚石、头石和背石、两臂各节之间也夹着魂；(挂在哪, 位置（相对那个关节）, 半径 (x, y, z))
SEAMS2 = [("leg_n", (0.0, 0.0, 0.11), (0.115, 0.125, 0.02)), ("leg_f", (0.0, 0.0, 0.11), (0.115, 0.125, 0.02)),
          ("s1", (0.0, -0.33, -0.03), (0.15, 0.02, 0.12)),
          ("arm_n", (0.01, -0.04, -0.14), (0.09, 0.09, 0.022)), ("arm_n", (0.02, -0.11, -0.40), (0.1, 0.1, 0.022)),
          ("arm_f", (-0.01, -0.04, -0.14), (0.09, 0.09, 0.022)), ("arm_f", (-0.02, -0.11, -0.40), (0.1, 0.1, 0.022))]
# 大石头上的裂缝（E 向画面上、相对那块石头的包围盒：0..1），缝里透魂光
CRACKS = {"Belly": [(0.30, 0.95), (0.36, 0.72), (0.31, 0.55), (0.40, 0.34), (0.35, 0.12)],
          "Back": [(0.62, 0.92), (0.55, 0.70), (0.60, 0.52), (0.52, 0.30)]}


BOXY = 0.72  # 超椭球的指数（<1 越方）


def chisel_rock(radii, seed, chip=0.18, n_planes=22, subdiv=3):
    """斧劈的山石：椭球按随机的平面削（平面以外的点压回平面上），块面之间成硬棱；再加一点起伏。"""
    rx, ry, rz = radii
    rng = np.random.default_rng(seed)
    planes = []
    for _ in range(n_planes):
        n = rng.normal(size=3)
        n[2] *= 0.8
        n /= np.linalg.norm(n)
        supp = math.sqrt((rx * n[0]) ** 2 + (ry * n[1]) ** 2 + (rz * n[2]) ** 2)  # 椭球在这个方向的支撑距离
        planes.append((Vector(n), supp * (1 - chip * rng.uniform(0.35, 1.0))))
    off = Vector((seed * 1.7, seed * 0.9, seed * 2.3))

    def build(bm):
        import bmesh
        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
        for v in bm.verts:
            q = [math.copysign(abs(c) ** BOXY, c) for c in v.co]  # 往方里推一点（超椭球）
            p = Vector((q[0] * rx, q[1] * ry, q[2] * rz))
            for n, d in planes:
                s = p.dot(n)
                if s > d:
                    p -= n * (s - d)
            p *= 1.0 + 0.035 * mnoise.noise(p * 7.0 + off)
            v.co = p
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def build_golem():
    root = B.empty("GolemRoot")
    yaw = B.empty("GolemYaw", root, rot=(0, 0, math.radians(YAW)))
    scl = B.empty("GolemScale", yaw)
    scl.scale = (SCALE, SCALE, SCALE)
    stone = V2.paint_material("GolemStone", STONE_STOPS, wash=0.40, wash_scale=3.2, seed=31.0, rim_hex=RIM, rim=0.40,
                              rim_power=2.6, value_var=0.10, edge=0.6, edge_power=2.0, bias=-0.22)
    bpy.context.view_layer.freestyle_settings.crease_angle = math.radians(148)  # 块面之间的棱也描（形线）
    joints = {}
    for nm, loc in JOINTS.items():  # 父在前、子在后（JOINTS 的顺序）
        pn = _parent_name(nm)
        par = joints[pn] if pn else scl
        joints[nm] = B.empty(f"Golem_{nm}", par, loc=Vector(loc) - (Vector(JOINTS[pn]) if pn else Vector()))
    obs = {}
    for nm, (jn, c, r, rot, seed, chip) in STONES.items():
        obs[nm] = B.mesh_object(f"Golem{nm}", chisel_rock(r, seed, chip), stone, "outer", joints[jn], loc=c,
                                rot=tuple(math.radians(a) for a in rot), sharp_deg=18, cun=True)
    # 石缝里的魂：夹在两块石头之间的一片发光的扁饼（只从缝里露出一线）
    m_seam = V2.glow_flat("GolemSeam", SEAM_DAY, 1.0)
    for lo, hi, (sx, sy), z in SEAMS:
        jl = joints[lo]
        p = Vector((0.0, (JOINTS[lo][1] + JOINTS[hi][1]) / 2, z)) - Vector(JOINTS[lo])
        B.mesh_object(f"GolemSeam_{lo}", K.ellipsoid((sx, sy, 0.022)), m_seam, "none", jl, loc=p)
    for k, (jn, p, r) in enumerate(SEAMS2):
        B.mesh_object(f"GolemSeam2_{k}", K.ellipsoid(r), m_seam, "none", joints[jn], loc=Vector(p))
    # 头石正面：一道焦墨深缝（眉下），缝里两只眼
    head = joints["s2"]
    m_hollow = B.flat_material("GolemHollow", I["jiao"])
    m_eye = B.emissive_material("GolemEye", EYE, 1.0)
    m_hot = B.emissive_material("GolemEyeHot", EYE_HOT, 1.0)
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(obs["Head"])
    fx, fy = _head_front(obs["Head"])
    V2.design_patch("GolemSlot", tree, V2.closed_smooth(_slot(fx, fy), 50), m_hollow, head, lift=0.004, spacing=0.35)
    eyes = _eyes(fx, fy)
    for k, ((ex, ey), hl, hh, tilt) in enumerate(eyes):
        V2.design_patch(f"GolemEye{k}", tree, _ellipse(ex, ey, hl, hh, tilt), m_eye, head, lift=0.006, spacing=0.25)
        V2.design_patch(f"GolemEyeHot{k}", tree, _ellipse(ex + 0.1, ey + 0.05, hl * 0.45, hh * 0.45, tilt), m_hot, head,
                        lift=0.007, spacing=0.2)
    # 大石头上的裂缝：一道焦墨的细缝，夜里缝里透出魂光
    m_crack = V2.glow_flat("GolemCrack", SEAM_DAY, 1.0)
    right, up, _ = B.camera_basis()
    for nm, rel in CRACKS.items():
        ob = obs[nm]
        mw = ob.matrix_world
        xy = np.array([(25.0 * (mw @ v.co).dot(right), 25.0 * (mw @ v.co).dot(up)) for v in ob.data.vertices])
        lo_, hi_ = xy.min(0), xy.max(0)
        pts = [(lo_[0] + (hi_[0] - lo_[0]) * u, lo_[1] + (hi_[1] - lo_[1]) * v) for u, v in rel]
        st = V2.bvh_world(ob)
        V2.design_outline(f"GolemCrack{nm}", st, pts, [0.25, 0.55, 0.6, 0.45, 0.2][:len(pts)], m_crack, ob,
                          lift=0.004, closed=False, step=0.25)
    sock = B.empty("GolemSocketEyes", head)
    e0, e1 = eyes[0][0], eyes[1][0]
    hits = V2.project_design(tree, [(e0[0] * 0.6 + e1[0] * 0.4, e0[1] * 0.6 + e1[1] * 0.4)])
    if hits[0][0] is not None:
        sock.location = head.matrix_world.inverted() @ hits[0][0]
    B.set_direction(root, "S")
    parts = {"root": root, "yaw": yaw, "joints": joints, "obs": obs, "sockets": {"eyes": sock}}
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


def _parent_name(nm):
    return {"s1": "s0", "s2": "s1", "s3": "s1", "s4": "s3", "arm_n": "s1", "arm_f": "s1"}.get(nm)


def _head_front(head_ob):
    """头石在 E 向画面里的前沿（设计稿单位）：最靠前的点的 x，和前沿那一截的竖向中线偏下的 y。"""
    right, up, _ = B.camera_basis()
    mw = head_ob.matrix_world
    pts = [(25.0 * (mw @ v.co).dot(right), 25.0 * (mw @ v.co).dot(up)) for v in head_ob.data.vertices]
    fx = max(x for x, _ in pts)
    ys = [y for x, y in pts if x > fx - 3.0]
    return fx, min(ys) + 0.42 * (max(ys) - min(ys))


def _slot(fx, fy):
    """头石正面的深缝（设计稿单位，E 向画面）：眼窝那一道横缝，前低后高。"""
    pts = [(-6.8, 0.9), (-4.0, 1.25), (-1.2, 0.85), (-0.3, 0.05), (-1.4, -0.6), (-4.2, -0.35), (-7.0, -0.2)]
    return [(fx + x, fy + y) for x, y in pts]


def _eyes(fx, fy):
    return [((fx - 4.9, fy + 0.35), 1.05, 0.5, 6.0), ((fx - 1.9, fy + 0.15), 0.8, 0.42, 2.0)]


def _ellipse(ex, ey, hl, hh, tilt, n=28):
    a = math.radians(tilt)
    return [(ex + hl * math.cos(t) * math.cos(a) - hh * math.sin(t) * math.sin(a),
             ey + hl * math.cos(t) * math.sin(a) + hh * math.sin(t) * math.cos(a))
            for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def pose_golem(parts, anim, frame, n):
    """move：沉重的摇摆步。ph 一圈两步：近腿在 ph∈(0,π) 抬起往前，远腿反过来；身子落脚时最低。
    垒起来的石头一层比一层晃得晚、晃得多（相位落后、幅度加大）。"""
    ph = 2 * math.pi * (frame % n) / n
    J = parts["joints"]
    lift_n = max(0.0, math.sin(ph)) ** 1.5
    lift_f = max(0.0, -math.sin(ph)) ** 1.5
    sw = math.cos(ph)  # 近腿：+1 在后、-1 在前（-Y 是前）
    J["leg_n"].location = Vector(JOINTS["leg_n"]) + Vector((0, 0.10 * sw, 0.07 * lift_n))
    J["leg_n"].rotation_euler = (math.radians(14 * -sw * 0.6 - 10 * lift_n), 0, 0)
    J["leg_f"].location = Vector(JOINTS["leg_f"]) + Vector((0, -0.10 * sw, 0.07 * lift_f))
    J["leg_f"].rotation_euler = (math.radians(14 * sw * 0.6 - 10 * lift_f), 0, 0)
    drop = 0.012 * (1 - abs(math.sin(ph)))  # 两脚都着地时（换步）身子沉一下
    roll = 1.0 * math.sin(ph)  # 重心压在着地的那条腿上：往那边歪（E 向画面里左右歪会变成上下动，不能大）
    J["s0"].location = Vector(JOINTS["s0"]) + Vector((roll * 0.002, 0, -drop))
    J["s0"].rotation_euler = (math.radians(1.2 * math.sin(2 * ph)), math.radians(roll), 0)
    lag = 0.7
    for k, (nm, amp) in enumerate((("s1", 1.5), ("s2", 3.0), ("s3", 4.0), ("s4", 6.0))):
        a = ph - lag * (k + 1)  # 前后点（画面里看得见），左右只晃一点
        J[nm].rotation_euler = (math.radians(amp * math.sin(2 * a)), math.radians(0.25 * amp * math.sin(a)), 0)
    for nm, sgn in (("arm_n", 1), ("arm_f", -1)):
        J[nm].rotation_euler = (math.radians(-16 * sgn * sw), 0, math.radians(4 * sgn))
    bpy.context.view_layer.update()
