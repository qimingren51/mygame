"""赤面狐（精修三维）：造型、骨架姿态按设计稿 post/enemy_design.py。

躯干：沿脊线的变截面网格（胸深、腰收、臀圆），颈接着往前上方伸到头下；头：沿吻轴车出来（颅圆、吻尖），
两只大耳（耳背墨色、耳里米白）；四条腿是变径的管（近侧的腿在镜头这边）；尾巴是一根中轴管加一圈朝尖的毛簇，
尾尖墨色；胸前、颊后、腹下、肘后有毛簇（只进外轮廓，不画内线）。毛色：明暗和毛色分区走同一条色带
（暗 → 赭、亮 → 米白），顶点属性 zone 把腹、胸、颊往米白推、把背脊往赭推；笔毛丝顺着身子走。
脸上的朱砂（额头 → 鼻梁 → 两颊）、浓眉、丹凤眼、鼻都是按设计稿投到头上的贴片；颈上一圈红绳打结。
姿态：每帧用设计稿的 fox_move_pose / fox_pounce_pose（二维骨架角度），换算成三维（前 = -Y，高 = 设计稿高 / 21.65）。

    root, parts, sockets = build_fox()
    pose_fox(parts, "move", i, 8)
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
import enemy_design as DZ  # noqa: E402

I, A_ = S.INK, S.ACCENT
EYE = "#FF6B5A"
EYE_HOT = "#FFE2C2"
MASK_GLOW = "#E2553C"  # 朱砂在夜里隐隐透出的红（发光层里很淡的一层）
CREAM = "#F3EAD6"
MID = S.mix(A_["zheshi"], S.PAPER, 0.52)
DARK = S.mix(A_["zheshi"], S.PAPER, 0.12)
SHADOW = S.mix(A_["zheshi"], I["zhong"], 0.45)
RED = A_["zhusha"]
RED_DARK = S.mix(A_["zhusha"], I["jiao"], 0.35)
# 毛的色带（d 从暗到亮）：暗赭 → 赭 → 淡赭 → 米白；暗部偏暖偏灰，亮部偏冷的米白
FUR_STOPS = [(0.00, S.mix(SHADOW, I["nong"], 0.3)), (0.22, SHADOW), (0.36, DARK), (0.50, S.mix(DARK, MID, 0.6)),
             (0.60, MID), (0.72, S.mix(MID, CREAM, 0.55)), (0.84, CREAM), (1.00, "#FBF6EA")]
INK_STOPS = [(0.0, I["jiao"]), (0.6, I["jiao"]), (0.85, I["nong"]), (1.0, S.mix(I["nong"], I["zhong"], 0.6))]
RIM = S.mix(CREAM, A_["huaqing"], 0.25)
VZ = 25.0 * math.cos(math.radians(S.CAMERA_PITCH_DEG))  # 设计稿的高（单位）→ 米：除以它
# 腿的半径（米，沿腿从根到掌）：第二批加粗两成
LEG_R = {"front": [r * 1.2 for r in (0.11, 0.085, 0.056, 0.046, 0.042, 0.038)],
         "hind": [r * 1.2 for r in (0.165, 0.12, 0.062, 0.05, 0.043, 0.038)]}
PAW_R = (0.045, 0.069, 0.029)


def d2m(x_u, y_u, lat=0.0):
    """设计稿（单位，x 前、y 上）→ 模型坐标（米，前 = -Y）。lat：左右（-X 是镜头这边，E 向时）。"""
    return Vector((lat, -x_u / 25.0, y_u / VZ))


def fur_material(name, seed, zone=True, streak=0.18):
    return V2.paint_material(name, FUR_STOPS, wash=0.26, wash_scale=2.6, seed=seed, shade_attr="zone" if zone else None,
                             shade_gain=1.0, streak=streak, streak_scale=(4.0, 60.0), rim_hex=RIM, rim=0.6,
                             rim_power=2.4, value_var=0.05, edge=0.22, bias=-0.42)


# ================================================================ 几何
def ring_body(spine, prof, nu=48, seed=1, zone_fn=None):
    """沿脊线的变截面体：spine = 点列（模型坐标），prof(t) → (左右半宽, 上半高, 下半高, 上下中心偏移)。
    返回 (顶点, 面, 属性)。两端收成一点。"""
    sp = np.asarray([tuple(p) for p in spine], np.float64)
    seg = np.linalg.norm(np.diff(sp, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    nv = 64
    u = np.linspace(0, s[-1], nv)
    C = np.stack([np.interp(u, s, sp[:, k]) for k in range(3)], -1)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9
    side = np.array([1.0, 0, 0])
    verts, zones, su, sv = [], [], [], []
    off = Vector((seed * 1.3, seed * 0.7, seed * 2.1))
    for j in range(nv):
        t = j / (nv - 1)
        up = np.cross(T[j], side)
        up /= np.linalg.norm(up) + 1e-9
        if up[2] < 0:
            up = -up
        rx, rz_up, rz_dn, dz = prof(t)
        for i in range(nu):
            th = 2 * math.pi * i / nu
            c, sn = math.cos(th), math.sin(th)
            rz = rz_up if sn > 0 else rz_dn
            p = C[j] + side * (rx * c) + up * (rz * sn + dz)
            n_ = mnoise.noise(Vector(p) * 6.0 + off) * 0.006
            p = p + (side * c + up * sn) * n_
            verts.append(p)
            zones.append(zone_fn(t, sn, c) if zone_fn else 0.0)
            su.append(t)
            sv.append(th / (2 * math.pi))
    faces = []
    for j in range(nv - 1):
        for i in range(nu):
            a, b = j * nu + i, j * nu + (i + 1) % nu
            faces.append((a, a + nu, b + nu, b))
    # 两端封口：各加一个中心点
    n0 = len(verts)
    verts.append(C[0] - T[0] * 0.01); zones.append(zones[0]); su.append(0.0); sv.append(0.0)
    verts.append(C[-1] + T[-1] * 0.01); zones.append(zones[-1]); su.append(1.0); sv.append(0.0)
    for i in range(nu):
        faces.append((n0, i, (i + 1) % nu)[::-1])
        b0 = (nv - 1) * nu
        faces.append((n0 + 1, b0 + (i + 1) % nu, b0 + i)[::-1])
    return np.asarray(verts), faces, {"zone": zones, "su": su, "sv": sv}


def clumps_build(roots, dirs, lens, widths, flat=0.45, segs=6):
    """一组毛簇（尖叶形的锥）：每簇从 root 沿 dir 伸出 len，根宽 width，扁度 flat。合成一个网格。"""
    def build(bm):
        for r, d, ln, w in zip(roots, dirs, lens, widths):
            r, d = Vector(r), Vector(d).normalized()
            a = d.cross(Vector((0, 0, 1)))
            if a.length < 1e-3:
                a = d.cross(Vector((1, 0, 0)))
            a.normalize()
            b = d.cross(a).normalized()
            rings = []
            for k, (t, sc) in enumerate(((0.0, 1.0), (0.35, 0.85), (0.7, 0.45))):
                ring = []
                for i in range(segs):
                    th = 2 * math.pi * i / segs
                    ring.append(bm.verts.new(r + d * ln * t + (a * math.cos(th) + b * math.sin(th) * flat) * w * sc))
                rings.append(ring)
            tip = bm.verts.new(r + d * ln * 1.08)
            for ra, rb in zip(rings, rings[1:]):
                for i in range(segs):
                    bm.faces.new((ra[i], ra[(i + 1) % segs], rb[(i + 1) % segs], rb[i]))
            for i in range(segs):
                bm.faces.new((rings[-1][i], rings[-1][(i + 1) % segs], tip))
            bm.faces.new(list(reversed(rings[0])))
        import bmesh
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


# ================================================================ 部件
def build_torso(parent, mat):
    """躯干 + 颈（模型坐标，静止姿态）。"""
    spine = [d2m(-15.4, 18.2), d2m(-11.0, 18.6), d2m(-4.0, 19.0), d2m(4.0, 18.4), d2m(10.0, 18.6), d2m(12.6, 21.4),
             d2m(13.4, 25.0), d2m(13.6, 27.6)]

    def prof(t):  # (左右半宽, 上半高, 下半高, 中心偏移)
        key = [(0.0, 0.05, 0.05, 0.05, 0.0), (0.06, 0.15, 0.15, 0.17, 0.0), (0.18, 0.17, 0.18, 0.21, 0.01),
               (0.42, 0.12, 0.14, 0.12, 0.02), (0.62, 0.16, 0.20, 0.24, -0.01), (0.76, 0.15, 0.17, 0.22, -0.02),
               (0.86, 0.11, 0.12, 0.13, 0.0), (0.95, 0.09, 0.09, 0.10, 0.0), (1.0, 0.04, 0.04, 0.04, 0.0)]
        ts = [k[0] for k in key]
        return tuple(float(np.interp(t, ts, [k[i] for k in key])) for i in range(1, 5))

    def zone(t, sn, c):  # 背脊往赭推；侧面下半截、腹、胸、喉往米白推（从斜上方也看得见）
        z = -0.34 * max(0.0, sn - 0.2) ** 1.2 + 0.62 * min(1.0, max(0.0, -sn + 0.12) * 1.6) ** 0.8
        if t > 0.6:
            z += 0.35 * max(0.0, -sn + 0.4) * min(1.0, (t - 0.6) / 0.2)  # 胸前、喉下更白
        return z

    P, F, A = ring_body(spine, prof, seed=2, zone_fn=zone)
    return V2.mesh_from_arrays("FoxTorso", P, F, mat, "outer", parent, attrs=A)


def _head_extent():
    """从二维稿的头部轮廓量出每个 x 处的上沿、下沿（单位）：三维的头在侧面上和设计稿的头一样大。"""
    c = DZ.curve_pts(DZ.FOX_HEAD, 600, closed=True)
    xs = c[:, 0]
    x0, x1 = xs.min(), xs.max()

    def at(x):
        ys = []
        for (ax, ay), (bx, by) in zip(c, np.roll(c, -1, axis=0)):
            if (ax - x) * (bx - x) <= 0 and abs(bx - ax) > 1e-9:
                ys.append(ay + (by - ay) * (x - ax) / (bx - ax))
        return (max(ys), min(ys)) if ys else (None, None)
    return x0, x1, at


def build_head(parent, mat):
    """头：沿吻轴车出来，截面的上下沿按二维稿的头部轮廓量（侧面剪影和设计稿一致），左右比上下窄、往吻尖收；
    下颌平一点。坐标在头的局部系（原点 = 颈根）。"""
    neck = d2m(*DZ.FOX_NECK)
    x0, x1, at = _head_extent()
    nose = DZ.FOX_NOSE
    nu, nv = 40, 48
    verts, zones, su, sv = [], [], [], []
    xs = np.linspace(x0 + 0.15, x1 - 0.05, nv)
    for j, x in enumerate(xs):
        t = j / (nv - 1)
        top, bot = at(x)
        if top is None:
            top = bot = nose[1]
        yc = (top + bot) / 2
        r_up = max((top - yc), 0.05) / VZ
        r_dn = max((yc - bot), 0.05) / VZ
        r_lat = (r_up + r_dn) / 2 * (0.95 - 0.35 * t) * (1.0 if t < 0.85 else (1 - t) / 0.15 * 0.9 + 0.1)
        c0 = d2m(x, yc) - neck
        for i in range(nu):
            th = 2 * math.pi * i / nu
            c, s_ = math.cos(th), math.sin(th)
            rz = r_up if s_ > 0 else r_dn
            p = c0 + Vector((r_lat * c, 0, rz * s_))
            verts.append(p)
            zz = 0.6 * max(0.0, -s_ + 0.2) ** 0.7 * (0.5 + 0.5 * min(1.0, t * 2.0)) - 0.3 * max(0.0, s_) ** 2 * (1 - t)
            zones.append(zz)
            su.append(t)
            sv.append(th / (2 * math.pi))
    faces = []
    for j in range(nv - 1):
        for i in range(nu):
            a, b = j * nu + i, j * nu + (i + 1) % nu
            faces.append((a, b, b + nu, a + nu))
    n0 = len(verts)
    verts.append(d2m(xs[0] - 0.3, (at(xs[0])[0] + at(xs[0])[1]) / 2) - neck); zones.append(0.0); su.append(0.0); sv.append(0.0)
    verts.append(d2m(xs[-1] + 0.2, at(xs[-1])[0] if at(xs[-1])[0] else nose[1]) - neck); zones.append(0.3); su.append(1.0); sv.append(0.0)
    for i in range(nu):
        faces.append((n0, (i + 1) % nu, i))
        b0 = (nv - 1) * nu
        faces.append((n0 + 1, b0 + i, b0 + (i + 1) % nu))
    ob = V2.mesh_from_arrays("FoxHead", verts, faces, mat, "outer", parent, attrs={"zone": zones, "su": su, "sv": sv})
    import bmesh
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data); bm.free()
    return ob


def build_ear(name, tri, parent, m_out, m_in, m_ink, neck):
    """耳：三棱锥样的大耳（前面略凹），外面淡赭、耳背和耳尖墨色、里面米白。tri 是设计稿上的（耳根后, 耳尖, 耳根前）。"""
    b0, tip, b1 = (d2m(*p) - neck for p in tri)
    mid0 = (b0 + b1) / 2
    b0, tip, b1 = b0 - mid0, tip - mid0, b1 - mid0  # 物体原点放在耳根（耳朵绕耳根转）
    mid = (b0 + b1) / 2
    depth = Vector((0.07, 0, 0))  # 耳的厚度方向（左右）
    hgt = (tip - mid)

    def build(bm):
        rows = []
        for k in range(7):
            t = k / 6
            w = (1 - t) ** 0.9
            c = mid + hgt * t
            ring = [c + (b0 - mid) * w, c + (b1 - mid) * w, c + depth * 0.5 * w + (b0 - mid) * 0.0,
                    c - depth * 0.5 * w]
            # 前面（-X，镜头这边）略凹：前棱往里收
            ring[3] = c - depth * 0.25 * w
            rows.append([bm.verts.new(tuple(v)) for v in ring])
        tp = bm.verts.new(tuple(mid + hgt * 1.04))
        order = [0, 3, 1, 2]
        for ra, rb in zip(rows, rows[1:]):
            for q in range(4):
                i0, i1 = order[q], order[(q + 1) % 4]
                bm.faces.new((ra[i0], ra[i1], rb[i1], rb[i0]))
        for q in range(4):
            i0, i1 = order[q], order[(q + 1) % 4]
            bm.faces.new((rows[-1][i0], rows[-1][i1], tp))
        bm.faces.new([rows[0][i] for i in order[::-1]])
        import bmesh
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = B.mesh_object(name, build, [m_out, m_ink], "outer", parent, sharp_deg=50)
    # 耳尖、耳背墨色：上 35% 和后棱用墨
    me = ob.data
    for poly in me.polygons:
        c = poly.center
        tt = (c - mid).dot(hgt.normalized()) / hgt.length
        if tt > 0.62:
            poly.material_index = 1
    inner = [mid + (b0 - mid) * 0.55 + hgt * 0.06 - depth * 0.3, mid + hgt * 0.78 - depth * 0.18,
             mid + (b1 - mid) * 0.55 + hgt * 0.06 - depth * 0.3]

    def build_in(bm):
        vs = [bm.verts.new(tuple(v)) for v in inner]
        bm.faces.new(vs)
    inn = B.mesh_object(name + "In", build_in, m_in, "none", ob, smooth=False)
    ob.location = mid0
    return ob


def leg_tube(name, pts, radii, mats, parent, zones=None):
    """一条腿：沿关节点的变径管（关节处圆），pts 是模型坐标点列。"""
    pts = [Vector(p) for p in pts]
    dense = []
    for a, b in zip(pts[:-1], pts[1:]):
        for t in np.linspace(0, 1, 6, endpoint=False):
            dense.append(a.lerp(b, t))
    dense.append(pts[-1])
    rr = np.interp(np.linspace(0, 1, len(dense)), np.linspace(0, 1, len(radii)), radii)

    def rf(t):
        return float(np.interp(t, np.linspace(0, 1, len(rr)), rr))
    ob = B.mesh_object(name, K.tube_build(dense, rf, 14, zones=zones), mats, "outer", parent, sharp_deg=0)
    return ob


# ================================================================ 组装
class FoxParts(dict):
    pass


def build_fox():
    root = B.empty("FoxRoot")
    body = B.empty("FoxBody", root)  # 身体（躯干 + 腿根）：每帧按 pose 的 body 移动、俯仰、伸缩
    M_fur = fur_material("FoxFur", 3.0)
    M_fur_leg = fur_material("FoxFurLeg", 5.0)
    M_head = fur_material("FoxFurHead", 7.0)
    M_tail = fur_material("FoxFurTail", 9.0, streak=0.25)
    M_ink = V2.paint_material("FoxInk", INK_STOPS, wash=0.2, seed=11.0, rim_hex=I["zhong"], rim=0.5, edge=0.1)
    M_paw = V2.paint_material("FoxPaw", [(0.0, I["jiao"]), (0.4, I["nong"]), (0.7, SHADOW), (1.0, DARK)], wash=0.2,
                              seed=12.0, edge=0.1)
    M_red = V2.paint_material("FoxRed", [(0.0, RED_DARK), (0.45, RED_DARK), (0.6, RED), (1.0, S.mix(RED, "#F06A4E", 0.4))],
                              wash=0.3, seed=13.0, edge=0.0)
    # 脸谱的红：平涂（只留一点明暗和水色），夜里在发光层里很淡地透出一层
    M_mask = V2.paint_material("FoxMask", [(0.0, RED_DARK), (0.30, S.mix(RED_DARK, RED, 0.6)), (0.50, RED),
                                           (1.0, S.mix(RED, "#F06A4E", 0.3))], wash=0.14, seed=15.0, edge=0.0,
                               value_var=0.03)
    V2.add_glow_const(M_mask, 0.18)
    M_window = V2.paint_material("FoxEyeWindow", [(0.0, S.mix(CREAM, MID, 0.5)), (0.5, CREAM), (1.0, "#FBF6EA")],
                                 wash=0.1, seed=16.0, edge=0.0)
    M_far = fur_material("FoxFurFar", 6.0)  # 远侧的腿：暗一档
    nodes = M_far.node_tree.nodes
    next(n for n in nodes if n.type == "MATH" and n.operation == "MULTIPLY_ADD").inputs[2].default_value -= 0.25
    M_cream = V2.paint_material("FoxCream", [(0.0, MID), (0.4, S.mix(MID, CREAM, 0.6)), (0.6, CREAM), (1.0, "#FBF6EA")],
                                wash=0.2, seed=14.0, edge=0.1)
    M_eye = B.emissive_material("FoxEye", EYE, 1.0)
    M_hot = B.emissive_material("FoxEyeHot", EYE_HOT, 1.0)
    M_jiao = B.flat_material("FoxJiao", I["jiao"])
    parts = FoxParts(root=root, body=body)
    build_torso(body, M_fur)
    # 胸前一蓬白毛、腹下一排毛簇（只进外轮廓）
    roots, dirs, lens, ws = [], [], [], []
    rng = np.random.default_rng(5)
    for k in range(16):
        a = rng.uniform(-0.9, 0.9)
        zc = rng.uniform(13.0, 22.0)
        roots.append(d2m(13.2 - 0.2 * abs(a) - 0.08 * (22 - zc), zc, 0.12 * a))
        dirs.append(Vector((0.3 * a, -0.55, -0.85)))
        lens.append(rng.uniform(0.10, 0.16)); ws.append(rng.uniform(0.035, 0.05))
    for k in range(14):  # 腹下一排往下的毛尖
        x = rng.uniform(-7.0, 7.0)
        roots.append(d2m(x, 14.6 + 0.10 * abs(x), rng.uniform(-0.12, 0.12)))
        dirs.append(Vector((0, 0.35, -1))); lens.append(rng.uniform(0.07, 0.11)); ws.append(0.035)
    # 腿：每条三段 + 掌；近侧（-X，镜头这边）、远侧（+X）
    parts["legs"] = {}
    for far in (False, True):
        lat = 0.11 if far else -0.11
        for name, rootp, segs, rad in (("front", DZ.FOX_SHOULDER, DZ.FOX_FRONT_LEG, LEG_R["front"]),
                                       ("hind", DZ.FOX_HIP, DZ.FOX_HIND_LEG, LEG_R["hind"])):
            nm = f"Fox{name.title()}{'Far' if far else 'Near'}"
            pts = [d2m(x, y, lat) for x, y in DZ.fox_leg(rootp, segs)]
            ob = leg_tube(nm, pts, rad, [M_far if far else M_fur_leg, M_paw], root, zones=lambda t: 1 if t > 0.86 else 0)
            paw = B.mesh_object(nm + "Paw", K.ellipsoid(PAW_R), M_paw, "outer", root)
            parts["legs"][(name, far)] = (ob, paw, lat, rad)
    # 头（转轴在颈根），略朝镜头转
    neck = d2m(*DZ.FOX_NECK)
    head_piv = B.empty("FoxHeadPivot", root, loc=neck)
    head_yaw = B.empty("FoxHeadYaw", head_piv, rot=(0, 0, math.radians(-12)))  # 略朝镜头转（太大二维稿就投不准）
    head = build_head(head_yaw, M_head)
    # 腮毛：颊后往后下方炸开的毛簇
    roots, dirs, lens, ws = [], [], [], []
    for k in range(12):
        a = rng.uniform(-1, 1)
        roots.append(d2m(12.4 + rng.uniform(-0.8, 1.6), 25.6 + rng.uniform(-1.0, 1.4), 0.13 * a) - neck)
        dirs.append(Vector((0.4 * a, 0.75, -0.55)))
        lens.append(rng.uniform(0.09, 0.14)); ws.append(rng.uniform(0.03, 0.045))
    B.mesh_object("FoxCheekFur", clumps_build(roots, dirs, lens, ws), M_cream, "none", head_yaw, sharp_deg=0)
    ear_n = build_ear("FoxEarNear", DZ.FOX_EAR_NEAR, head_yaw, M_head, M_cream, M_ink, neck)
    ear_f = build_ear("FoxEarFar", DZ.FOX_EAR_FAR, head_yaw, M_head, M_cream, M_ink, neck)
    ear_n.location.x -= 0.07
    ear_f.location.x += 0.09
    nose = B.mesh_object("FoxNose", K.ellipsoid((0.028, 0.022, 0.02)), M_jiao, "none", head_yaw,
                         loc=d2m(*DZ.FOX_NOSE) - neck + Vector((0, -0.005, 0.004)))
    # 红绳：颈根一圈 + 喉下的结 + 两截垂下来
    cord_c = d2m(12.6, 23.6)
    pts = []
    for k in range(25):
        th = 2 * math.pi * k / 24
        pts.append(cord_c + Vector((0.13 * math.cos(th), 0.11 * math.sin(th), 0.06 * math.sin(th) + 0.0)))
    B.mesh_object("FoxCord", K.tube_build(pts, lambda t: 0.014, 8), M_red, "inner", body, sharp_deg=0)
    knot = cord_c + Vector((0, -0.115, -0.07))
    B.mesh_object("FoxKnot", K.ellipsoid((0.028, 0.024, 0.024)), M_red, "inner", body, loc=knot)
    for sx in (-1, 1):
        tp = [knot, knot + Vector((0.012 * sx, -0.01, -0.05)), knot + Vector((0.02 * sx, -0.004, -0.10))]
        B.mesh_object(f"FoxCordEnd{sx:+d}", K.tube_build(tp, lambda t: 0.011 * (1 - 0.5 * t), 6), M_red, "inner", body,
                      sharp_deg=0)
    # 尾巴（每帧重建）
    tail = B.mesh_object("FoxTail", lambda bm: None, [M_tail, M_ink], "outer", root)
    tail_f = B.mesh_object("FoxTailFur", lambda bm: None, [M_tail, M_ink], "none", root)
    bpy.data.collections[B.CONTOUR_COLLECTION].objects.link(tail_f)
    parts.update(head_piv=head_piv, head_yaw=head_yaw, head=head, ear_n=ear_n, ear_f=ear_f, tail=tail, tail_f=tail_f,
                 neck=neck)
    # 脸上的贴片：先摆到 E 向静止姿态，按二维稿投影
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(head)
    inv = head_yaw.matrix_world.inverted()
    rot3 = inv.to_3x3()

    # 脸谱（第二批改）：整块朱砂（边缘清楚、勾一道深红边）、眼周米白、墨勾丹凤眼、发光的眼仁和竖瞳、浓眉。
    # 都是 E 向画面上的形状，按视线投到头上；抬起的高度决定前后（后画的抬得高）。
    M_mask_edge = B.flat_material("FoxMaskEdge", S.mix(RED_DARK, I["jiao"], 0.35))
    V2.design_patch("FoxMask", tree, closed_smooth(DZ.FOX_MASK, 90), M_mask, head_yaw, lift=0.004, spacing=0.45)
    V2.design_outline("FoxMaskEdge", tree, closed_smooth(DZ.FOX_MASK, 90), 0.30, M_mask_edge, head_yaw, lift=0.0045)
    V2.design_patch("FoxEyeWindow", tree, closed_smooth(DZ.FOX_EYE_WINDOW, 48), M_window, head_yaw, lift=0.006,
                    spacing=0.3)
    V2.design_patch("FoxEyeInk", tree, closed_smooth(DZ.FOX_EYE_INK, 60), M_jiao, head_yaw, lift=0.007, spacing=0.3)
    V2.design_patch("FoxEye", tree, closed_smooth(DZ.fox_eye_poly(1.0), 40), M_eye, head_yaw, lift=0.008, spacing=0.25)
    V2.design_patch("FoxEyeHot", tree, closed_smooth(DZ.fox_eye_poly(0.5), 28), M_hot, head_yaw, lift=0.009,
                    spacing=0.2)
    (ex, ey), hl, hh, tilt = DZ.FOX_EYE2
    a = math.radians(tilt)
    pupil = [(ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a))
             for x, y in ((0.10 * hl, 0.80 * hh), (-0.07 * hl, 0.0), (0.10 * hl, -0.78 * hh), (0.24 * hl, 0.0))]
    V2.design_patch("FoxPupil", tree, closed_smooth(pupil, 24), M_jiao, head_yaw, lift=0.010, spacing=0.2)
    V2.design_patch("FoxBrow", tree, DZ.FOX_BROW_POLY, M_jiao, head_yaw, lift=0.0075, spacing=0.3)
    (fx, fy), fl, fh, ft = DZ.FOX_EYE_FAR
    hits = V2.project_design(tree, [(fx, fy)])
    if hits[0][0] is not None:
        p_ = inv @ hits[0][0]
        n_ = (rot3 @ hits[0][1]).normalized()
        B.mesh_object("FoxEyeFar", K.ellipsoid((0.016, 0.016, 0.012)), M_eye, "none", head_yaw, loc=p_ + n_ * 0.004)
    sock = B.empty("FoxSocketEyes", head_yaw)
    hits = V2.project_design(tree, [(ex * 0.7 + fx * 0.3, ey * 0.7 + fy * 0.3)])
    if hits[0][0] is not None:
        sock.location = inv @ hits[0][0]
    B.set_direction(root, "S")
    parts["sockets"] = {"eyes": sock}
    parts["mats"] = (M_tail, M_ink)
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


def K_dense(line, k):
    out = []
    for a, b in zip(line[:-1], line[1:]):
        for t in np.linspace(0, 1, k, endpoint=False):
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(tuple(line[-1]))
    return out


def closed_smooth(poly, n):
    return V2.closed_smooth(poly, n)


# ================================================================ 姿态
def _tail_geom(curve_m, puff, seed=21):
    """尾巴：中轴管 + 一圈朝尖的毛簇；curve_m 是模型坐标点列。返回 (管 build, 毛簇 build)。"""
    pts = [Vector(p) for p in curve_m]
    ts = [t for t, _ in DZ.FOX_TAIL_W]
    ws = [w for _, w in DZ.FOX_TAIL_W]

    def rad(t):
        return float(np.interp(t, ts, ws)) / 25.0 * 0.80 * puff * (1.0 if t < 0.9 else max(0.0, (1 - t) / 0.1) ** 0.8)

    tube = K.tube_build(pts, rad, 16, zones=lambda t: 1 if t > DZ.FOX_TAIL_INK + 0.02 else 0, flat=0.85)
    rng = np.random.default_rng(seed)
    n = len(pts)
    roots, dirs, lens, wds, inks = [], [], [], [], []
    count = 70 if puff <= 1 else 64
    for k in range(count):
        t = rng.uniform(0.06, DZ.FOX_TAIL_INK + 0.08)  # 尾尖一段不长毛簇：管子自己收成笔尖
        i = min(int(t * (n - 1)), n - 2)
        f = t * (n - 1) - i
        c = pts[i].lerp(pts[i + 1], f)
        tan = (pts[i + 1] - pts[i]).normalized()
        a = tan.cross(Vector((1, 0, 0)))
        if a.length < 1e-3:
            a = tan.cross(Vector((0, 0, 1)))
        a.normalize()
        b = tan.cross(a).normalized()
        th = rng.uniform(0, 2 * math.pi)
        rdir = (a * math.cos(th) + b * math.sin(th))
        r = rad(t)
        out = (0.28 if puff <= 1 else 0.85) * (0.35 if t > DZ.FOX_TAIL_INK else 1.0)  # 平时贴伏；炸毛时往外张；尾尖收拢
        roots.append(c + rdir * r * 0.55)
        dirs.append((tan * (1.0 - 0.3 * out) + rdir * out * 0.7).normalized())
        lens.append(r * rng.uniform(1.1, 1.75) * (1.12 if puff > 1 else 1.0))
        wds.append(r * rng.uniform(0.55, 0.8))
        inks.append(t > DZ.FOX_TAIL_INK - 0.03)
    fur = clumps_build(roots, dirs, lens, wds, flat=0.35)

    def fur_build(bm):
        fur(bm)
        # 尾尖一段的毛簇换墨色材质：按每簇的面数分配
        per = (len(bm.faces)) // max(len(roots), 1)
        for qi, f in enumerate(bm.faces):
            f.material_index = 1 if inks[min(qi // max(per, 1), len(inks) - 1)] else 0
    return tube, fur_build


def _to2(v):
    """模型坐标 → 设计稿（单位）。"""
    return (-v.y * 25.0, v.z * VZ)


def pose_fox(parts, anim, frame, n):
    """按设计稿的二维骨架姿态：身体按 (dx, dy, rot, sx, sy) 移动、俯仰、伸缩；腿根、颈根、尾根跟着身体走，
    腿、头、尾本身只转不伸缩。"""
    pose = DZ.fox_move_pose(frame, n) if anim == "move" else DZ.fox_pounce_pose(frame)
    body = parts["body"]
    dx, dy, rot, sx, sy = pose["body"]
    piv = d2m(*DZ.FOX_PIVOT)
    R = Matrix.Rotation(math.radians(-rot), 4, "X")  # 设计稿逆时针（抬头）= 前端（-Y）往上
    Sc = Matrix.Diagonal((1.0, sx, sy, 1.0))
    T = Matrix.Translation(piv + Vector((0, -dx / 25.0, dy / VZ)))
    Mb = T @ R @ Sc @ Matrix.Translation(-piv)
    body.matrix_basis = Mb
    # 腿
    for (name, far), (ob, paw, lat, rad) in parts["legs"].items():
        segs = DZ.FOX_FRONT_LEG if name == "front" else DZ.FOX_HIND_LEG
        root2 = DZ.FOX_SHOULDER if name == "front" else DZ.FOX_HIP
        r3 = Mb @ d2m(*root2, lat)
        angs = [a + rot for a in pose["legs"][(name, far)]]
        if anim == "move":  # 一步一起伏：身子压低时站地的腿收短，脚不陷进地里
            angs = DZ.fox_leg_ground(_to2(r3), segs, angs, name)
        pts = [d2m(x, y, lat) for x, y in DZ.fox_leg(_to2(r3), segs, angs)]
        dense = []
        for a_, b_ in zip(pts[:-1], pts[1:]):
            for t in np.linspace(0, 1, 6, endpoint=False):
                dense.append(a_.lerp(b_, t))
        dense.append(pts[-1])
        rr = np.interp(np.linspace(0, 1, len(dense)), np.linspace(0, 1, len(rad)), rad)
        K.replace_mesh(ob, K.tube_build(dense, lambda t, rr=rr: float(np.interp(t, np.linspace(0, 1, len(rr)), rr)), 14,
                                        zones=lambda t: 1 if t > 0.86 else 0))
        # 腿的前侧（受光、朝前）一线米白，后侧略暗：按顶点法线写 zone
        zs = [0.42 * max(0.0, -v.normal.y) ** 1.5 - 0.18 * max(0.0, v.normal.y) for v in ob.data.vertices]
        B.set_point_attr(ob, "zone", zs)
        tipv = (pts[-1] - pts[-2]).normalized()
        paw.location = pts[-1] + Vector((0, -0.045, -0.012))
        paw.rotation_euler = (math.atan2(tipv.z, -tipv.y) * 0.4, 0, 0)
    # 头
    hrot, hdx, hdy = pose["head"]
    hp = parts["head_piv"]
    hp.location = Mb @ parts["neck"] + Vector((0, -hdx / 25.0, hdy / VZ))
    hp.rotation_euler = (math.radians(-(hrot + rot)), 0, 0)
    e = math.radians(-pose["ears"])
    for ear in (parts["ear_n"], parts["ear_f"]):
        ear.rotation_euler = (e, 0, 0)
    # 尾巴：二维中线 → 三维（略偏到远侧，压在身子后面）
    ang, curl, wave, ph, puff = pose["tail"]
    root_t = _to2(Mb @ d2m(*DZ.FOX_TAIL_ROOT))
    c2 = DZ.fox_tail_curve(root_t, angle=ang + rot, curl=curl, wave=wave, ph=ph, n=20)
    back = c2[0] - (c2[1] - c2[0]) / np.linalg.norm(c2[1] - c2[0]) * 1.4
    c2 = np.vstack([back, c2])
    cm = [d2m(x, y, 0.05 + 0.02 * k / len(c2)) for k, (x, y) in enumerate(c2)]
    tube, fur = _tail_geom(cm, 1.32 if puff else 1.0)
    K.replace_mesh(parts["tail"], tube)
    K.replace_mesh(parts["tail_f"], fur)
    bpy.context.view_layer.update()
