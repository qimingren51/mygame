"""影妖（精修三维）：造型按设计稿 post/enemy_design.py。

人那么高的一团焦墨，上宽下窄的倒泪滴，兜帽的帽尖往后挑；兜帽口里一团黑，只有两点暖金的垂眼；
墨壳一层层裹着——以脸为心往外套的层（层坐标 xi：第 k 道缝在 xi = k），几何上每道缝往外落一个台阶
（里层的边压在外层上），着色器按 xi 画缝里的影、层边的受光、缝里透出的魂光（AOV glow，夜里一圈圈淡金纹）；
两道裂缝（一道像泪痕）是贴在表面上的金色笔画条（发光）；下摆收细，接几缕往后拖的墨烟。
网格直接按参数生成（160×140 顶点），不靠细分低模；表面加一点布面似的噪声起伏。
眼睛、裂缝的位置从设计稿投到三维表面上（v2kit.project_design）。

    root, parts, sockets = build_shade()
    pose_shade(parts, "float", i, 8)
挂点：eyes（两眼之间，近眼权重 0.6）。建模面朝 -Y，只渲 E。
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
import v2kit as V2  # noqa: E402

I, A_ = S.INK, S.ACCENT
EYE = "#FFC46B"
EYE_HOT = "#FFF1C8"
CRACK = "#F7D58A"
SHEEN = S.mix(I["zhong"], A_["huaqing"], 0.30)
# 墨壳的多档颜色（d 从暗到亮）：焦墨 → 浓墨偏暖 → 重墨 → 冷灰（受光、略带花青）；暗部更暖、亮部更冷
SHELL_STOPS = [(0.00, I["jiao"]), (0.50, I["jiao"]), (0.60, S.mix(I["jiao"], I["nong"], 0.55)),
               (0.71, I["nong"]), (0.82, S.mix(I["nong"], SHEEN, 0.6)), (0.93, SHEEN),
               (1.00, S.mix(SHEEN, I["dan"], 0.25))]
RIM = S.mix(I["dan"], A_["huaqing"], 0.35)

# 外形（米）：(半径, 高)，自上而下
PROFILE = [(0.0, 2.11), (0.16, 2.09), (0.29, 2.04), (0.39, 1.97), (0.465, 1.88), (0.515, 1.78), (0.545, 1.66),
           (0.550, 1.54), (0.535, 1.42), (0.50, 1.29), (0.45, 1.15), (0.39, 1.00), (0.325, 0.86), (0.26, 0.72),
           (0.195, 0.59), (0.135, 0.47), (0.085, 0.37), (0.05, 0.31), (0.0, 0.29)]  # 下摆尖在 0.3 米收口（以下化进烟里，本来就透明）
LEAN = 0.055  # 往前倾（-Y），追着光
FACE_YAW = 60.0  # 脸朝镜头偏转（度）：E 向时两只眼都看得见
FACE_C = Vector((0.0, -0.10, 1.74))  # 层的中心（头里）
SEAMS = [27, 40, 53, 66, 80, 95, 111, 128, 146]  # 层与层之间的缝（离脸轴的角度，度）
HOLLOW = 21.0  # 兜帽口（离脸轴小于这个角度往里凹）
STEP = 0.020  # 每道缝往外落的台阶（米）
HOOD_BASE = Vector((0.0, 0.40, 1.98))
HOOD_TIP = Vector((0.0, 0.76, 1.86))
PIVOT_Z = 0.24
SCALE = 0.95  # 整体缩放（主角身高的约 0.88 倍）
BACK = 0.06  # 整体往后挪（米）：前沿（兜帽檐）压在碰撞半径 13 附近


def face_dir():
    a = math.radians(FACE_YAW)
    return Vector((-math.sin(a), -math.cos(a), 0.11)).normalized()  # 略仰头：望着光


def _profile(nv):
    """按弧长把外形插值成 nv 圈（顶点密度均匀）。"""
    p = np.asarray(PROFILE, np.float64)
    seg = np.hypot(*np.diff(p, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    u = np.linspace(0, s[-1], nv)
    return np.interp(u, s, p[:, 0]), np.interp(u, s, p[:, 1])


def _xi(psi_deg):
    """离脸轴的角度 → 层坐标：第 k 道缝在 xi = k+1（兜帽口里 xi < 0）。"""
    seams = np.asarray(SEAMS, np.float64)
    knots = np.concatenate([[HOLLOW], seams])
    vals = np.arange(len(knots), dtype=np.float64)  # HOLLOW → 0，第一道缝 → 1 …
    lo = (psi_deg - HOLLOW) / (seams[0] - HOLLOW)  # 兜帽口里为负
    last = np.interp(psi_deg, knots, vals)
    beyond = vals[-1] + (psi_deg - seams[-1]) / 18.0
    return np.where(psi_deg < HOLLOW, lo, np.where(psi_deg > seams[-1], beyond, last))


def body_arrays(nu=160, nv=140, seed=3):
    """影妖墨壳的顶点、面和属性（模型坐标，面朝 -Y）。"""
    r, z = _profile(nv)
    th = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    R, Z = r[:, None] * np.ones((1, nu)), z[:, None] * np.ones((1, nu))
    X = R * np.sin(th)[None, :]
    Y = -R * np.cos(th)[None, :] * 1.05
    P = np.stack([X, Y, Z], -1).reshape(-1, 3)
    # 帽尖：后上方一处往后拉出一个尖
    d = np.linalg.norm(P - np.asarray(HOOD_BASE), axis=1)
    w = np.clip(1 - d / 0.36, 0, 1) ** 2.0
    P = P + w[:, None] * (np.asarray(HOOD_TIP) - np.asarray(HOOD_BASE))[None, :]
    # 离脸轴的角度（加一点偏移：下面的层往下、往后扩）
    fd = np.asarray(face_dir())
    v = P - np.asarray(FACE_C)
    vn = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    phi = np.degrees(np.arccos(np.clip(vn @ fd, -1, 1)))
    far = np.clip((phi - 24.0) / 40.0, 0, 1)  # 离脸越远，层越往下、往后扩（层心不动）
    psi = phi - far * (np.degrees(0.30) * np.clip(FACE_C.z - P[:, 2], 0, None) + np.degrees(0.18) * np.clip(P[:, 1], 0, None))
    psi = psi + far * np.array([mnoise.noise(Vector(p) * 2.2 + Vector((seed, 0.5, 1.3))) * 3.2 for p in P])
    xi = _xi(psi)
    # 兜帽口往里凹，帽檐略往外鼓
    radial = P - np.stack([np.zeros(len(P)), np.zeros(len(P)), np.clip(P[:, 2], 0.45, 1.75)], -1)
    radial /= np.linalg.norm(radial, axis=1, keepdims=True) + 1e-9
    hollow = np.clip((HOLLOW + 2.0 - psi) / (HOLLOW + 2.0), 0, 1) ** 0.8
    P = P - fd[None, :] * (0.20 * hollow)[:, None]
    lip = np.exp(-((psi - (HOLLOW + 3.0)) / 3.5) ** 2)
    P = P + radial * (0.048 * lip)[:, None]  # 兜帽檐鼓出来
    # 层的台阶：每道缝往外落 STEP（里层的边压着外层），两道缝之间慢慢回到原来的面
    fr = np.mod(xi, 1.0)
    inside = xi >= 1.0
    terr = np.where(inside, -STEP * (1 - fr) ** 1.6 * np.clip(fr / 0.06, 0, 1) ** 2 * (3 - 2 * np.clip(fr / 0.06, 0, 1)),
                    0.0)
    P = P + radial * terr[:, None]
    # 布面似的噪声起伏
    off = Vector((seed * 1.7, seed * 2.3, seed * 0.9))
    nz = np.array([mnoise.noise(Vector(p) * 3.2 + off) * 0.010 + mnoise.noise(Vector(p) * 8.5 + off) * 0.004 for p in P])
    P = P + radial * nz[:, None]
    # 往前倾
    P[:, 1] -= LEAN * (P[:, 2] - PIVOT_Z)
    # 绕脸轴的方位（层的走向），给笔毛丝做坐标
    up = Vector((0, 0, 1))
    e1 = np.asarray(up.cross(face_dir()).normalized())
    e2 = np.cross(fd, e1)
    om = np.arctan2(vn @ e2, vn @ e1) / (2 * np.pi)
    # 两极：首尾两圈（半径 0）各并成一个点，用三角扇接上，不留退化面
    keep = np.r_[0, np.arange(nu, (nv - 1) * nu), (nv - 1) * nu]
    P2 = P[keep]
    attrs = {"xi": xi[keep], "su": om[keep], "sv": xi[keep] * 0.1}
    top, bot = 0, len(P2) - 1

    def vid(j, i):  # 第 j 圈（1..nv-2）第 i 个顶点在 P2 里的编号
        return 1 + (j - 1) * nu + (i % nu)

    faces = [(top, vid(1, i), vid(1, i + 1)) for i in range(nu)]  # 绕向：法线朝外
    for j in range(1, nv - 2):
        for i in range(nu):
            faces.append((vid(j, i), vid(j + 1, i), vid(j + 1, i + 1), vid(j, i + 1)))
    faces += [(vid(nv - 2, i + 1), vid(nv - 2, i), bot) for i in range(nu)]
    return P2, faces, attrs


def shell_material(seed=3.0):
    """墨壳：多档的绘画感渐变 + 按层坐标 xi 画缝影、层边受光、缝里魂光（AOV）。"""
    m = V2.paint_material("ShadeShell", SHELL_STOPS, wash=0.36, wash_scale=2.0, seed=seed, streak=0.22,
                          streak_scale=(70.0, 4.0),
                          rim_hex=RIM, rim=0.85, rim_power=2.2, value_var=0.06, edge=0.30, fade_z=(0.30, 0.62))
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    # 找到映射前的 d：MapRange 的输入
    mr = next(n for n in N if n.type == "MAP_RANGE")
    src = mr.inputs["Value"].links[0].from_socket
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "xi"
    fr = N.new("ShaderNodeMath"); fr.operation = "FRACT"
    L.new(at.outputs["Fac"], fr.inputs[0])

    def gauss(center, width, gain):
        sb = N.new("ShaderNodeMath"); sb.operation = "SUBTRACT"; sb.inputs[1].default_value = center
        L.new(fr.outputs["Value"], sb.inputs[0])
        dv = N.new("ShaderNodeMath"); dv.operation = "DIVIDE"; dv.inputs[1].default_value = width
        L.new(sb.outputs["Value"], dv.inputs[0])
        sq = N.new("ShaderNodeMath"); sq.operation = "MULTIPLY"
        L.new(dv.outputs["Value"], sq.inputs[0]); L.new(dv.outputs["Value"], sq.inputs[1])
        ex = N.new("ShaderNodeMath"); ex.operation = "MULTIPLY"; ex.inputs[1].default_value = -1.0
        L.new(sq.outputs["Value"], ex.inputs[0])
        e = N.new("ShaderNodeMath"); e.operation = "EXPONENT"
        L.new(ex.outputs["Value"], e.inputs[0])
        g = N.new("ShaderNodeMath"); g.operation = "MULTIPLY"; g.inputs[1].default_value = gain
        L.new(e.outputs["Value"], g.inputs[0])
        return g.outputs["Value"]

    # 只在 xi ≥ 1 的地方有缝（兜帽口里没有）
    gate = N.new("ShaderNodeMath"); gate.operation = "GREATER_THAN"; gate.inputs[1].default_value = 0.92
    L.new(at.outputs["Fac"], gate.inputs[0])
    shadow = gauss(0.07, 0.09, -0.45)  # 缝外侧：被里层的边压出的影
    lip = gauss(0.90, 0.07, 0.22)  # 缝内侧：里层的边翻起，受光
    terms = N.new("ShaderNodeMath"); terms.operation = "ADD"
    L.new(shadow, terms.inputs[0]); L.new(lip, terms.inputs[1])
    far = N.new("ShaderNodeMapRange")  # 外层（背后）的纹淡下去
    far.inputs["From Min"].default_value = 4.0; far.inputs["From Max"].default_value = 9.0
    far.inputs["To Min"].default_value = 1.0; far.inputs["To Max"].default_value = 0.35
    L.new(at.outputs["Fac"], far.inputs["Value"])
    gfar = N.new("ShaderNodeMath"); gfar.operation = "MULTIPLY"
    L.new(gate.outputs["Value"], gfar.inputs[0]); L.new(far.outputs["Result"], gfar.inputs[1])
    gt = N.new("ShaderNodeMath"); gt.operation = "MULTIPLY"
    L.new(terms.outputs["Value"], gt.inputs[0]); L.new(gfar.outputs["Value"], gt.inputs[1])
    # 兜帽口里：压到最暗
    hol = N.new("ShaderNodeMath"); hol.operation = "LESS_THAN"; hol.inputs[1].default_value = 0.15
    L.new(at.outputs["Fac"], hol.inputs[0])
    hk = N.new("ShaderNodeMath"); hk.operation = "MULTIPLY"; hk.inputs[1].default_value = -2.0
    L.new(hol.outputs["Value"], hk.inputs[0])
    # 兜帽檐（xi≈0.6）受光的一圈
    sb = N.new("ShaderNodeMath"); sb.operation = "SUBTRACT"; sb.inputs[1].default_value = 0.6
    L.new(at.outputs["Fac"], sb.inputs[0])
    dv = N.new("ShaderNodeMath"); dv.operation = "DIVIDE"; dv.inputs[1].default_value = 0.22
    L.new(sb.outputs["Value"], dv.inputs[0])
    sq = N.new("ShaderNodeMath"); sq.operation = "MULTIPLY"
    L.new(dv.outputs["Value"], sq.inputs[0]); L.new(dv.outputs["Value"], sq.inputs[1])
    ng = N.new("ShaderNodeMath"); ng.operation = "MULTIPLY"; ng.inputs[1].default_value = -1.0
    L.new(sq.outputs["Value"], ng.inputs[0])
    ex = N.new("ShaderNodeMath"); ex.operation = "EXPONENT"
    L.new(ng.outputs["Value"], ex.inputs[0])
    lipk = N.new("ShaderNodeMath"); lipk.operation = "MULTIPLY"; lipk.inputs[1].default_value = 0.55
    L.new(ex.outputs["Value"], lipk.inputs[0])
    hk2 = N.new("ShaderNodeMath"); hk2.operation = "ADD"
    L.new(hk.outputs["Value"], hk2.inputs[0]); L.new(lipk.outputs["Value"], hk2.inputs[1])
    hk = hk2
    s1 = N.new("ShaderNodeMath"); s1.operation = "ADD"
    L.new(src, s1.inputs[0]); L.new(gt.outputs["Value"], s1.inputs[1])
    s2 = N.new("ShaderNodeMath"); s2.operation = "ADD"
    L.new(s1.outputs["Value"], s2.inputs[0]); L.new(hk.outputs["Value"], s2.inputs[1])
    L.new(s2.outputs["Value"], mr.inputs["Value"])
    # 缝里的魂光 → AOV
    g1 = gauss(0.0, 0.035, 0.08)  # 缝里只是微光
    g2 = gauss(1.0, 0.035, 0.08)
    gs = N.new("ShaderNodeMath"); gs.operation = "ADD"
    L.new(g1, gs.inputs[0]); L.new(g2, gs.inputs[1])
    gg = N.new("ShaderNodeMath"); gg.operation = "MULTIPLY"
    L.new(gs.outputs["Value"], gg.inputs[0]); L.new(gfar.outputs["Value"], gg.inputs[1])
    ao = N.new("ShaderNodeOutputAOV"); ao.aov_name = V2.GLOW_AOV
    L.new(gg.outputs["Value"], ao.inputs["Value"])
    return m


# ---------------------------------------------------------------- 墨烟
# 模型坐标：+Y 是身后（E 向时朝西），x 是左右（-x 朝镜头）。贴地的扁带：(控制点, 根宽, 相位)
SMOKE = [([(0.00, 0.00, 0.46), (0.00, 0.05, 0.20), (0.01, 0.16, 0.06), (0.02, 0.32, 0.03), (0.02, 0.50, 0.035),
           (0.01, 0.66, 0.05), (-0.01, 0.80, 0.08)], 0.66, 0.0),  # 主烟：从下摆尖垂下，贴地往后拖（第二批拖长）
         ([(0.04, 0.10, 0.36), (0.07, 0.22, 0.26), (0.08, 0.34, 0.25), (0.07, 0.46, 0.30), (0.05, 0.56, 0.36)], 0.20,
          1.9),  # 背后往上飘的一缕
         ([(-0.04, -0.02, 0.30), (-0.09, 0.04, 0.10), (-0.13, 0.14, 0.02), (-0.15, 0.30, 0.01), (-0.15, 0.46, 0.015),
           (-0.13, 0.60, 0.03)], 0.26, 3.3)]  # 前面贴地的一缕


def _smoke_pts(ctrl, ph, bob, n=20):
    c = np.asarray(ctrl, np.float64).copy()
    m = len(c)
    for i in range(m):  # 烟根跟着本体浮，烟尾贴地
        c[i, 2] += bob * (1 - i / (m - 1)) ** 1.5
    seg = np.linalg.norm(np.diff(c, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    u = np.linspace(0, s[-1], n)
    pts = np.stack([np.interp(u, s, c[:, k]) for k in range(3)], -1)
    t = u / s[-1]
    wave = np.sin(2 * np.pi * 0.9 * t - ph) * 0.04 * t ** 1.3
    pts[:, 0] += wave  # 左右摆
    pts[:, 2] += 0.4 * np.abs(wave) * (1 - t)
    return pts, t


def _smoke_build(ctrl, w0, ph, bob):
    """一条贴地的扁带：宽度方向是水平的（躺在地上），根部竖起来接到下摆；属性 fade（沿长）、edge（横向 -1..1）。"""
    pts, t = _smoke_pts(ctrl, ph, bob)
    n = len(pts)
    verts, fades, edges = [], [], []
    k = 5  # 横向分 5 列，边上透明
    for i in range(n):
        tan = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        tan /= np.linalg.norm(tan) + 1e-9
        flat = np.cross(tan, [0, 0, 1.0])  # 贴地的一段：宽度水平（躺在地上）
        flat = flat / (np.linalg.norm(flat) + 1e-9) if np.linalg.norm(flat) > 1e-6 else np.array([1.0, 0, 0])
        horiz = np.clip((1 - abs(tan[2])) * 1.4, 0, 1)
        side = flat * horiz + np.array([0, 1.0, 0]) * (1 - horiz)  # 竖着的根：宽度前后展开（E 向时朝镜头）
        side /= np.linalg.norm(side) + 1e-9
        w = w0 * (1 - 0.82 * t[i] ** 0.9) * (1 + 0.18 * math.sin(9 * t[i] + ph))
        for j in range(k):
            e = -1 + 2 * j / (k - 1)
            verts.append(pts[i] + side * e * w / 2 + np.array([0, 0, 0.012 * (1 - e * e)]))
            fades.append(t[i])
            edges.append(e)
    faces = [(i * k + j, i * k + j + 1, (i + 1) * k + j + 1, (i + 1) * k + j) for i in range(n - 1) for j in range(k - 1)]

    def build(bm):
        vs = [bm.verts.new(tuple(v)) for v in verts]
        for f in faces:
            bm.faces.new([vs[q] for q in f])

    return build, {"fade": fades, "edge": edges}


# ---------------------------------------------------------------- 组装
def build_shade():
    import enemy_design as DZ  # 设计稿（眼、裂缝的位置），A、B 共用

    root = B.empty("ShadeRoot")
    body = B.empty("ShadeBody", root, loc=(0, 0, PIVOT_Z))  # 绕下摆尖弯腰、压扁
    inner = B.empty("ShadeInner", body, loc=(0, BACK, -PIVOT_Z))
    P, faces, attrs = body_arrays()
    shell = V2.mesh_from_arrays("ShadeShell", P, faces, shell_material(), "outer", inner, attrs=attrs)
    parts = {"root": root, "body": body, "shell": shell}
    # 先转到 E 向，把二维稿上的眼和裂缝投到表面上
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(shell)
    inv = inner.matrix_world.inverted()
    rot3 = inv.to_3x3()
    m_eye = B.emissive_material("ShadeEye", EYE, 1.0)
    m_hot = B.emissive_material("ShadeEyeHot", EYE_HOT, 1.0)
    m_crack = B.emissive_material("ShadeCrack", CRACK, 1.0)
    m_crack_edge = V2.glow_flat("ShadeCrackEdge", I["jiao"], 0.0)
    eye_pts = []
    for ei, wgt in ((0, 0.6), (1, 0.4)):
        c = DZ.SH_EYES[ei][0]
        for nm, mat, sc_, lift in (("Eye", m_eye, 1.0, 0.004), ("EyeHot", m_hot, 0.45, 0.007)):
            poly = DZ.shade_eye_poly(ei, sc_)
            if sc_ < 1:  # 眼心略往上
                poly = [(x, y + 0.05 * DZ.SH_EYES[ei][2]) for x, y in poly]
            ring = V2.closed_smooth(poly, 28)
            hits = V2.project_design(tree, [c] + ring)
            if any(h is None for h, _ in hits):
                continue
            pts = [inv @ h for h, _ in hits]
            nrms = [(rot3 @ nn).normalized() for _, nn in hits]
            verts = [p_ + n_ * lift for p_, n_ in zip(pts, nrms)]
            nr = len(ring)
            faces = [(0, 1 + i, 1 + (i + 1) % nr) for i in range(nr)]
            V2.mesh_from_arrays(f"Shade{nm}{ei}", verts, faces, mat, "none", inner, smooth=False)
            if sc_ == 1.0:
                eye_pts.append((pts[0], wgt))
    sock = B.empty("ShadeSocketEyes", inner)
    if eye_pts:
        sock.location = sum((p * w for p, w in eye_pts), Vector()) / sum(w for _, w in eye_pts)
    # 裂缝：二维稿的折线投到表面上，墨边一条、金芯一条（金芯发光）
    rng = np.random.default_rng(16)
    for ci, (cr, w) in enumerate(DZ.shade_cracks()):
        dense = []
        for a_, b_ in zip(cr[:-1], cr[1:]):
            for t in np.linspace(0, 1, 6, endpoint=False):
                dense.append((a_[0] + (b_[0] - a_[0]) * t, a_[1] + (b_[1] - a_[1]) * t))
        dense.append(cr[-1])
        hits = V2.project_design(tree, dense)
        pts = [(inv @ h, (rot3 @ nn).normalized()) for h, nn in hits if h is not None]
        if len(pts) < 3:
            continue
        n = len(pts)
        prof = np.interp(np.linspace(0, 1, n), [0, 0.3, 0.6, 1], [0.6, 1.1, 0.9, 0.3])
        wid = w / S.WORLD_UNITS_PER_M * 2 * prof
        V2.surface_strip(f"ShadeCrackEdge{ci}", [p for p, _ in pts], [q for _, q in pts], wid * 2.3, m_crack_edge, inner,
                         lift=0.003)
        V2.surface_strip(f"ShadeCrack{ci}", [p for p, _ in pts], [q for _, q in pts], wid, m_crack, inner, lift=0.005)
    B.set_direction(root, "S")
    # 墨烟
    m_smoke = V2.smoke_material("ShadeSmoke", [(0.0, I["jiao"]), (0.25, I["nong"]), (0.6, I["zhong"]),
                                               (1.0, S.mix(I["zhong"], I["dan"], 0.6))],
                                fade_start=0.12, fade_power=0.9, noise_amt=0.75, seed=4.0, edge_attr="edge")
    smokes = []
    for si, (ctrl, r0, ph0) in enumerate(SMOKE):
        build, attrs = _smoke_build(ctrl, r0, ph0, 0.0)
        ob = B.mesh_object(f"ShadeSmoke{si}", build, m_smoke, "none", root, sharp_deg=0)
        for kk, vv in attrs.items():
            B.set_point_attr(ob, kk, vv)
        smokes.append((ob, ctrl, r0, ph0))
    parts["smokes"] = smokes
    parts["sockets"] = {"eyes": sock}
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


def pose_shade(parts, anim, frame, n):
    """float：轻轻浮 0.5 单位（游戏还会给悬浮的妖物整体加 ±1.5 单位的起伏，帧里只留一点“呼吸”），
    往上时略拉长、到顶略压扁，上身前后点头（追着光），墨烟的波往后传。"""
    import kit as K
    ph = 2 * math.pi * (frame % n) / n
    bob = 0.5 / S.WORLD_UNITS_PER_M / math.cos(math.radians(S.CAMERA_PITCH_DEG)) * math.sin(ph)
    vel = math.cos(ph)
    sy = 1.0 + 0.02 * vel
    sx = 1.0 / math.sqrt(sy)
    body = parts["body"]
    body.location = (0, 0, PIVOT_Z + bob)
    body.rotation_euler = (math.radians(-3.0 * math.sin(ph - 0.9)), 0, 0)  # 绕 X：前后点头（-Y 是前）
    body.scale = (sx * SCALE, sx * SCALE, sy * SCALE)
    for ob, ctrl, r0, ph0 in parts["smokes"]:
        build, attrs = _smoke_build(ctrl, r0, ph + ph0, bob)
        K.replace_mesh(ob, build, attrs=attrs)
    bpy.context.view_layer.update()
