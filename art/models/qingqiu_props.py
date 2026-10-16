"""青丘（竹海、狐村）的场景道具。道具锚点 PROP_ANCHOR，只画 idle 的 S 向一帧。

竹丛 bamboo_clump：小土丘上八竿墨竹，高低错落（叶尖约 2.9 米，约主角的 1.3 倍高）。分浓淡两层：
  前排竹竿是浓墨带一点石绿、竹叶浓墨焦墨，后排竹竿和竹叶是淡彩石绿（墨竹“前浓后淡”的画法），节处一圈浓墨，竹竿只描细线；
  竹叶是一片片披针形的“笔触”（中脉折起，一片叶两档墨色，不描线），四五片一簇按“个”“介”字攒在枝头，
  竿顶的叶向上挑。脚下一只竹笋。帧 320²（2 倍）。
竹丛（砍倒）bamboo_clump_broken：同一个土丘、同一个画布和锚点（游戏里直接换图），八根斜劈的竹桩
  （切口淡藤黄、中间空心浓墨，口沿翘着竹刺），四竿倒在地上的断竹（梢头带枝叶），满地落叶（有几片枯黄）。
狐仙祠 fox_shrine：两级石台上的小石龛，朱砂立柱，四坡翘角瓦顶（淡墨瓦、细檐边，翼角轻挑）；龛里坐一只白石狐
  （朱砂围嘴），台阶上供一碟白团子、一碗果子；檐角挂一盏小青灯（发光）。约 1.3 米（当地标用：和石灯笼差不多高，宽得多）。挂点 glow（青灯灯芯）。
石狐 stone_fox：方石座上蹲坐的石狐，侧身朝左前（尖嘴、竖耳看得出是狐），大尾巴绕到前爪、尾尖白；
  风化的石头带苔，脖子上一块褪色的红围嘴，不发光。约 1.2 米。
狐灯 fox_lanterns：两根木柱、一根竹梁撑起一段四坡翘角瓦檐，檐下拉一根绳，挂三盏青纸灯（青火，发光；
  窗开得小，看得见青纸和竹篾），左柱贴一条朱砂纸符，
  狐村的光源。约 1.5 米。挂点 glow（三盏灯的中心，放一盏大光用）、glow_0..2（每盏灯芯，放小光用）。
狐祠庭院（每局一处，crates/view/src/ground.rs）：
  大狐仙祠 fox_shrine_grand：庭院正殿，按自己的尺寸建（约 3.4 米高），原样摆。帧 512²（2 倍）。挂点 glow、eave_lamp。
  石牌坊 fox_gate：冲天柱式一间两柱一楼的石牌坊，庭院入口。帧 384²（2 倍）。
  檐下留灯 fox_eave_lamp / fox_eave_lamp_lit：挂在大狐仙祠 eave_lamp 上的小圆纸灯笼（没点 / 点着），同画布同锚点；
    锚点 HANGING_ANCHOR 是挂钩顶端（meta anchor_kind: hanging）。帧 160²（2 倍）。挂点 flame。

青火的颜色 QING_GLOW 不在 style 调色板里，写进素材 meta 的 palette_extra 和 light_color；留灯的光色 EAVE_LAMP_GLOW 只写 light_color。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
from stone_lantern import _box, _prism, moss_material  # noqa: E402
from event_props import _paper_lantern  # noqa: E402

QING_GLOW = "#8FE3C8"  # 青火：狐村的灯（灯芯颜色 = 建议的光色）
PALETTE_EXTRA = [QING_GLOW]
BAMBOO_FRAME_1X = 160  # 竹丛比主角高一大截，道具帧 96 放不下，用 160（2 倍 320²，和主角帧一样大）
BAMBOO_K = 1.3  # 竹丛整体放大（土丘、竹竿、竹叶一起），砍倒的那张同样放大，比例不变

I, A, W = S.INK, S.ACCENT, S.WASH
SH = S.shade_ramp(A["shilv"])  # 石绿三档
SHW = S.shade_ramp(W["shilv"])  # 淡彩石绿三档


# ================================================================ 材质
def _mats():
    return {
        # 墨竹分浓淡：前排暗、后排淡
        "culm": K.toon("QqCulm", ramp=[SH[2], I["zhong"], I["nong"]], wash=0.25, edge=0.3, seed=301.0),
        "culm_far": K.toon("QqCulmFar", ramp=SHW, wash=0.25, edge=0.3, seed=331.0),
        "leaf": K.toon("QqLeaf", ramp=[I["nong"], I["jiao"], I["jiao"]], wash=0.35, edge=0.2, seed=302.0),
        "leaf_far": K.toon("QqLeafFar", ramp=[SHW[1], SHW[2], I["zhong"]], wash=0.35, edge=0.2, seed=332.0),
        "leaf_dry": K.toon("QqLeafDry", A["zheshi"], wash=0.3, edge=0.2, seed=303.0),
        "node": B.flat_material("QqNode", I["jiao"]),
        "node_far": B.flat_material("QqNodeFar", I["zhong"]),
        "twig": B.flat_material("QqTwig", I["nong"]),
        "earth": K.toon("QqEarth", ramp=[S.PAPER_SHADOW, I["qing"], I["dan"]], wash=0.4, wash_scale=3.0, edge=0.5,
                        seed=304.0),
        "moss": moss_material("QqMoss", coverage=0.5, up=0.5, seed=305.0),
        "moss_thin": moss_material("QqMossThin", coverage=0.64, up=0.5, seed=306.0),
        "shoot": K.toon("QqShoot", A["zheshi"], wash=0.25, edge=0.3, seed=306.0),
        "cut": K.toon("QqCut", W["tenghuang"], wash=0.2, edge=0.15, seed=307.0),
        "hollow": B.flat_material("QqHollow", I["nong"]),
        "stone": K.toon("QqStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.4, wash_scale=3.0, edge=0.5,
                        seed=308.0),
        "white": K.toon("QqWhiteStone", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], wash=0.25, edge=0.35, seed=309.0),
        "tile": K.toon("QqTile", ramp=[I["zhong"], I["nong"], I["jiao"]], wash=0.3, edge=0.25, seed=310.0),
        "fascia": B.flat_material("QqFascia", I["jiao"]),
        "tile_light": K.toon("QqTileLight", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.3, edge=0.25, seed=318.0),
        "fascia_light": B.flat_material("QqFasciaLight", I["nong"]),
        "ridge": K.toon("QqRidge", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.2, edge=0.2, seed=311.0),
        "wood": K.toon("QqWood", A["zheshi"], wash=0.3, edge=0.4, seed=317.0),
        "red": K.toon("QqRed", A["zhusha"], wash=0.2, edge=0.25, seed=312.0),
        "bib_faded": K.toon("QqBibFaded", W["zhusha"], wash=0.3, edge=0.25, seed=313.0),
        "dark": B.flat_material("QqDark", I["nong"]),
        "eye": B.flat_material("QqEye", I["jiao"]),
        "bun": K.toon("QqBun", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], edge=0.2, seed=314.0),
        "fruit": K.toon("QqFruit", A["zhusha"], edge=0.2, seed=315.0),
        "bowl": K.toon("QqBowl", ramp=[I["dan"], I["zhong"], I["nong"]], edge=0.25, seed=316.0),
        "rope": B.flat_material("QqRope", I["nong"]),
    }


def _lantern_mats(prefix: str, open_facing: float = 0.27) -> dict:
    shell = K.toon(f"{prefix}Shell", A["shilv"], edge=0.25, seed=320.0)
    return {"window": B.window_material(f"{prefix}Window", shell, open_facing=open_facing),
            "rib": B.flat_material(f"{prefix}Rib", SH[2]),
            "core": B.emissive_material(f"{prefix}Core", QING_GLOW, 1.0),
            "cap": K.toon(f"{prefix}Cap", I["jiao"], seed=321.0),
            "tassel": K.toon(f"{prefix}Tassel", A["zhusha"], seed=322.0)}


def _qing_lantern(prefix, parent, center, r, h, mats, ribs=8):
    """青纸灯笼：event_props 的纸灯笼（纸壳开窗露出发光芯）+ 贴着纸壳的竹篾（ribs 根，压在灯光上是细细的暗线）。"""
    sock = _paper_lantern(prefix, parent, center, r, h, mats)
    prof = [(0.6 * r, -0.92 * h), (0.9 * r, -0.62 * h), (r, -0.2 * h), (r, 0.2 * h), (0.9 * r, 0.62 * h), (0.6 * r, 0.92 * h)]
    c = Vector(center)

    def build(bm):
        for k in range(ribs):
            th = math.pi / 8 + 2 * math.pi * k / ribs  # 落在纸壳的棱上（_paper_lantern 的 radial 起伏最高处）
            pts = [c + Vector((rr * 1.05 * math.cos(th), rr * 1.05 * math.sin(th), z)) for rr, z in prof]
            K.tube_build(pts, lambda t: 0.0045, 4)(bm)
    B.mesh_object(f"{prefix}Ribs", build, mats["rib"], "none", parent, sharp_deg=0)
    return sock


# ================================================================ 几何小工具
def _frame(d, roll=0.0) -> Matrix:
    """局部 +X 指向 d、+Z 尽量朝上的旋转矩阵（3×3），再绕 d 转 roll 弧度。"""
    x = Vector(d).normalized()
    up = Vector((0, 0, 1)) if abs(x.z) < 0.95 else Vector((0, 1, 0))
    y = up.cross(x).normalized()
    z = x.cross(y).normalized()
    M = Matrix((x, y, z)).transposed()
    return Matrix.Rotation(roll, 3, x) @ M


def _add_leaf(bm, origin, d, length, width, droop=0.25, fold=0.35, roll=0.0, n=8):
    """一片竹叶（披针形）：从 origin 沿 d 方向长出，基部窄、前三分之一最宽、尖端收尖；
    中脉折起（两半朝向不同，渲出来是两档墨色，像一笔撇出来的），叶尖往下垂。"""
    R = _frame(d, roll)
    o = Vector(origin)
    rows = []
    for i in range(n + 1):
        t = i / n
        if t < 0.32:
            w = width * (0.18 + 0.82 * (t / 0.32) ** 0.6)
        else:
            w = width * ((1 - t) / 0.68) ** 0.85
        x, z = length * t, -droop * length * t * t
        if i == n:
            rows.append([bm.verts.new(o + R @ Vector((x, 0, z)))])
            continue
        rows.append([bm.verts.new(o + R @ Vector((x, sy * w / 2, z + (fold * w / 2 if sy == 0 else 0.0))))
                     for sy in (1, 0, -1)])
    for a, b in zip(rows, rows[1:]):
        if len(b) == 1:
            bm.faces.new((a[0], a[1], b[0]))
            bm.faces.new((a[1], a[2], b[0]))
        else:
            bm.faces.new((a[0], a[1], b[1], b[0]))
            bm.faces.new((a[1], a[2], b[2], b[1]))


def _add_ring(bm, center, d, r, h, seg=10):
    """竹节：沿 d 方向的一小段扁圆柱（略粗于竹竿）。"""
    M = Matrix.Translation(Vector(center)) @ _frame(d).to_4x4() @ Matrix.Rotation(math.radians(90), 4, "Y")
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r, depth=h, matrix=M)


def _rings_build(rings):
    def build(bm):
        for p, d, r, hh in rings:
            _add_ring(bm, p, d, r, hh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _culm_path(base, height, lean, n=14, bow=0.0):
    """竹竿中心线：从 base 向上，顶端偏 lean（x, y），中段略弓（bow，朝 lean 方向）。"""
    bx, by, bz = base
    lx, ly = lean
    pts = []
    for i in range(n):
        t = i / (n - 1)
        k = t ** 1.35 + bow * math.sin(math.pi * t)
        pts.append(Vector((bx + lx * k, by + ly * k, bz + height * t)))
    return pts


def _path_at(pts, t):
    """折线上按长度比例 t 取点和切线。"""
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    s = t * sum(seg)
    for i, l in enumerate(seg):
        if s <= l or i == len(seg) - 1:
            u = min(max(s / max(l, 1e-9), 0.0), 1.0)
            return pts[i].lerp(pts[i + 1], u), (pts[i + 1] - pts[i]).normalized()
        s -= l
    return pts[-1], (pts[-1] - pts[-2]).normalized()


def _mound_build(rx, ry, h, seed=3.0):
    """小土丘：压扁的噪声球，下半截压平在地面上。"""
    base = K.boulder_build((rx, ry, h), seed=seed, big=0.16, small=0.06, subdiv=3)

    def build(bm):
        base(bm)
        for v in bm.verts:
            v.co.z = max(v.co.z, 0.0)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


MOUND = (0.52, 0.40, 0.15)


def mound_height(x, y):
    rx, ry, h = MOUND
    return h * math.sqrt(max(0.0, 1 - (x / rx) ** 2 - (y / ry) ** 2))


# ================================================================ 竹丛
# (根部 x, y, 高, 根部半径, 顶端偏移 x, y)；根部 y ≥ FAR_Y 的是后排（淡）
CULMS = [  # 乘 BAMBOO_K 才是实际尺寸：最高一竿约 2.55 米，竿顶的叶尖约 2.9 米（2 倍下离画布顶 4 像素）
    (-0.05, 0.04, 1.97, 0.034, -0.15, 0.03),
    (0.12, 0.14, 1.84, 0.032, 0.24, 0.03),
    (-0.22, -0.04, 1.53, 0.031, -0.36, -0.03),
    (0.25, -0.07, 1.35, 0.030, 0.38, -0.06),
    (0.04, -0.15, 1.09, 0.028, 0.12, -0.07),
    (-0.14, 0.20, 1.75, 0.030, -0.12, 0.08),
    (0.30, 0.20, 0.98, 0.027, 0.30, 0.07),
    (-0.33, 0.14, 1.23, 0.028, -0.48, 0.05),
]
FAR_Y = 0.13


def _scaled(parent, name):
    """竹丛的几何都挂在这个放大 BAMBOO_K 倍的空物体下（挂点 feet 仍挂在根上）。"""
    sc = B.empty(name, parent)
    sc.scale = (BAMBOO_K,) * 3
    return sc


def _clump_base(root, m, leaves_bm_builds: list):
    """土丘 + 竹笋 + 丘上几片落叶（完整和砍倒的竹丛共用，随机数单独一路，两张图里一模一样）。"""
    obj = B.mesh_object
    rng = np.random.default_rng(5)
    obj("QqMound", _mound_build(*MOUND), m["earth"], "thin", root, sharp_deg=0)  # 土丘只描细线，像一笔淡墨晕开
    # 竹笋：尖锥，斜插在丘边，两道墨色的壳边
    sx, sy = 0.38, -0.21
    sz = mound_height(sx, sy) - 0.01
    tilt = (math.radians(-8), math.radians(10), 0)
    prof = [(0.050, 0.0), (0.048, 0.03), (0.040, 0.07), (0.028, 0.11), (0.014, 0.15), (0.0, 0.18)]
    obj("QqShoot", B.lathe(prof, 12), m["shoot"], "inner", root, loc=(sx, sy, sz), rot=tilt)
    for k, (r, z) in enumerate(((0.045, 0.05), (0.032, 0.10))):
        obj(f"QqShootBand{k}", B.cylinder(r * 1.06, r * 0.86, 0.012, 12), m["dark"], "none", root,
            loc=(sx + 0.002, sy - 0.005, sz + z), rot=tilt)
    params = []
    for _i in range(8):
        ang = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.2, 0.55)
        x, y = rr * math.cos(ang) * 1.0, rr * math.sin(ang) * 0.75
        z = mound_height(x, y) + 0.012
        d = Vector((math.cos(ang + rng.uniform(-1, 1)), math.sin(ang + rng.uniform(-1, 1)), 0.0))
        params.append(((x, y, z), d, rng.uniform(0.17, 0.24), rng.uniform(0.036, 0.046), rng.uniform(-0.2, 0.2)))

    def ground_leaves(bm):
        for o, d, L, Wd, roll in params:
            _add_leaf(bm, o, d, L, Wd, droop=0.0, fold=0.2, roll=roll)
    leaves_bm_builds.append(ground_leaves)


def _leaf_cluster(bm, rng, origin, out_dir, n, up=False, size=1.0, spread=0.9, droop_range=(-0.95, -0.3)):
    """一簇竹叶（“个”“介”字）：从 origin 向 out_dir 两侧扇开 n 片；up=True 时叶尖朝上（竿顶）。"""
    od = Vector(out_dir).normalized()
    base_yaw = math.atan2(od.y, od.x)
    for k in range(n):
        f = (k - (n - 1) / 2) / max((n - 1) / 2, 1)
        yaw = base_yaw + f * spread + rng.uniform(-0.15, 0.15)
        pitch = rng.uniform(0.35, 0.9) + 0.25 * (1 - abs(f)) if up else rng.uniform(*droop_range)
        # 朝镜头（-Y）或背向镜头的叶子会缩成一条，往屏幕左右压一点
        d = Vector((math.cos(yaw) * math.cos(pitch), 0.55 * math.sin(yaw) * math.cos(pitch), math.sin(pitch)))
        L = size * rng.uniform(0.22, 0.32)
        _add_leaf(bm, origin, d, L, size * rng.uniform(0.042, 0.058),
                  droop=rng.uniform(0.15, 0.45) * (0.3 if up else 1), fold=rng.uniform(0.25, 0.5),
                  roll=rng.uniform(-0.5, 0.5))


def build_bamboo_clump():
    m = _mats()
    rng = np.random.default_rng(11)
    clump = B.empty("BambooClump")
    root = _scaled(clump, "BambooClumpScale")
    obj = B.mesh_object
    leaves = {"near": [], "far": []}
    _clump_base(root, m, leaves["near"])
    rings = {"near": [], "far": []}
    twigs: list = []
    for ci, (bx, by, h, r0, lx, ly) in enumerate(CULMS):
        layer = "far" if by >= FAR_Y else "near"
        bz = max(mound_height(bx, by) - 0.03, 0.0)
        pts = _culm_path((bx, by, bz), h - bz, (lx, ly), bow=0.10 * (1 if ci % 2 else -1))
        rk = 0.55
        obj(f"QqCulm{ci}", K.tube_build(pts, lambda t, r0=r0: r0 * (1 - (1 - rk) * t), 10),
            m["culm" if layer == "near" else "culm_far"], "thin", root, sharp_deg=0)
        # 节：下密上疏再略密
        nodes, t = [], 0.06
        while t < 0.95:
            nodes.append(t)
            t += 0.09 + 0.07 * math.sin(math.pi * t)
        for t in nodes:
            p, d = _path_at(pts, t)
            rings[layer].append((p, d, r0 * (1 - (1 - rk) * t) * 1.16, 0.02))
        side = 1 if lx >= 0 else -1
        # 枝叶：竿子中上段的节上，左右交替伸出细枝，枝头一簇叶
        k = 0
        for t in nodes:
            if t < 0.28 or rng.random() < 0.08:
                continue
            p, d = _path_at(pts, t)
            s = side * (1 if k % 2 == 0 else -1)
            k += 1
            out = Vector((s * rng.uniform(0.75, 1.0), rng.uniform(-0.45, 0.25), 0.0))
            tl = rng.uniform(0.10, 0.22) * (0.6 + 0.5 * t)
            tip = p + out.normalized() * tl + Vector((0, 0, tl * rng.uniform(0.2, 0.6)))
            twigs.append(K.curve_points(p, tip, bend=Vector((0, 0, 0.02)), n=4))
            n_leaf = int(rng.integers(4, 8))
            leaves[layer].append(lambda bm, tip=tip, out=out, n_leaf=n_leaf:
                                 _leaf_cluster(bm, rng, tip, out, n_leaf, size=1.0, spread=0.9))
        top, d = _path_at(pts, 1.0)
        leaves[layer].append(lambda bm, top=top, side=side: _leaf_cluster(bm, rng, top, (side * 0.6, -0.1, 0), 3, up=True,
                                                                           size=0.9, spread=1.1))
    for layer in ("near", "far"):
        suf = "" if layer == "near" else "_far"
        obj(f"QqNodes{suf}", _rings_build(rings[layer]), m["node" + suf], "none", root, smooth=False)
        obj(f"QqLeaves{suf}", lambda bm, L=leaves[layer]: [f(bm) for f in L], m["leaf" + suf], "none", root, smooth=False)
    obj("QqTwigs", lambda bm: [K.tube_build(tp, lambda t: 0.0075 * (1 - 0.5 * t), 5)(bm) for tp in twigs],
        m["twig"], "none", root, sharp_deg=0)
    sockets = {"feet": B.empty("BambooFeet", clump)}
    bpy.context.view_layer.update()
    return clump, {"root": clump}, sockets


def _stump_build(r0, h, slant_dir, slant, rng, seg=12):
    """斜劈的竹桩：圆管顶端沿 slant_dir 斜切（高边比低边高 slant），口沿参差，顶口敞开。
    返回 (build, 顶口点列)；顶口点列给切口面和空心用。"""
    rim = []
    sd = Vector(slant_dir).normalized()
    jag = rng.uniform(0.0, 0.03, seg)
    for j in range(seg):
        th = 2 * math.pi * j / seg
        x, y = r0 * math.cos(th), r0 * math.sin(th)
        k = (x * sd.x + y * sd.y) / r0  # -1..1，切口高边在 sd 方向
        rim.append(Vector((x, y, h + 0.5 * slant * k + jag[j] * (0.5 + 0.5 * k))))

    def build(bm):
        bot = [bm.verts.new((r0 * 1.05 * math.cos(2 * math.pi * j / seg), r0 * 1.05 * math.sin(2 * math.pi * j / seg), 0.0))
               for j in range(seg)]
        mid = [bm.verts.new((p.x, p.y, 0.5 * p.z)) for p in rim]
        top = [bm.verts.new(p) for p in rim]
        for a, b in ((bot, mid), (mid, top)):
            for j in range(seg):
                bm.faces.new((a[j], a[(j + 1) % seg], b[(j + 1) % seg], b[j]))
        bm.faces.new(list(reversed(bot)))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build, rim


def build_bamboo_clump_broken():
    """砍倒的竹丛：同一个土丘（同样的随机种子），竹桩 + 倒地的断竹 + 落叶。"""
    m = _mats()
    clump = B.empty("BambooClumpBroken")
    root = _scaled(clump, "BambooClumpBrokenScale")
    obj = B.mesh_object
    leaves = {"near": [], "far": [], "dry": []}
    _clump_base(root, m, leaves["near"])
    rng = np.random.default_rng(29)  # 竹桩、断竹、落叶另一路随机数
    rings = {"near": [], "far": []}
    twigs: list = []
    stump_h = [0.34, 0.24, 0.40, 0.20, 0.28, 0.30, 0.18, 0.22]
    for ci, (bx, by, h, r0, lx, ly) in enumerate(CULMS):
        layer = "far" if by >= FAR_Y else "near"
        mat = m["culm" if layer == "near" else "culm_far"]
        bz = max(mound_height(bx, by) - 0.03, 0.0)
        ang = rng.uniform(0, 2 * math.pi)
        sd = (math.cos(ang), math.sin(ang) * 0.5 - 0.5)  # 切口多朝镜头一侧，看得见断面
        build, rim = _stump_build(r0 * 1.05, stump_h[ci] * 0.75 + 0.05, sd, 0.10, rng)
        obj(f"QqStump{ci}", build, mat, "thin", root, loc=(bx, by, bz), sharp_deg=0)
        # 断面：外圈淡藤黄的竹肉，中间空心（浓墨），都不描线（口沿已经有细线）
        c = sum(rim, Vector()) / len(rim)
        inner = [c + (p - c) * 0.6 for p in rim]

        def cut_build(bm, rim=rim, inner=inner):
            vo = [bm.verts.new(p + Vector((0, 0, 0.002))) for p in rim]
            vi = [bm.verts.new(p + Vector((0, 0, 0.002))) for p in inner]
            n = len(vo)
            for j in range(n):
                bm.faces.new((vo[j], vo[(j + 1) % n], vi[(j + 1) % n], vi[j]))

        obj(f"QqStumpCut{ci}", cut_build, m["cut"], "none", root, loc=(bx, by, bz), smooth=False)
        obj(f"QqStumpHollow{ci}", lambda bm, inner=inner: bm.faces.new([bm.verts.new(p - Vector((0, 0, 0.004)))
                                                                        for p in inner]),
            m["hollow"], "none", root, loc=(bx, by, bz), smooth=False)
        # 竹刺：切口高边上翘起的一两根尖片
        for s in range(int(rng.integers(1, 3))):
            j = int(np.argmax([p.z for p in rim])) + int(rng.integers(-2, 3))
            p = rim[j % len(rim)]
            out = Vector((p.x, p.y, 0)).normalized()
            tip = p + Vector((0, 0, rng.uniform(0.05, 0.10))) + out * rng.uniform(0.0, 0.015)
            K.limb(f"QqSplinter{ci}{s}", (bx + p.x, by + p.y, bz + p.z - 0.01), (bx + tip.x, by + tip.y, bz + tip.z),
                   0.009, 0.0015, mat, "thin", root, segs=4)
        rings[layer].append((Vector((bx, by, bz + 0.07)), Vector((0, 0, 1)), r0 * 1.2, 0.02))
    # 倒在地上的断竹：(起点 x, y, 终点 x, y, 根部半径)，从丘上斜躺到地面，梢头带两簇叶
    fallen = [(-0.28, -0.07, -0.98, -0.40, 0.032), (0.27, 0.02, 1.02, 0.30, 0.031),
              (0.06, -0.16, 0.56, -0.70, 0.029), (-0.13, 0.22, -0.80, 0.82, 0.029)]
    for fi, (x0, y0, x1, y1, r0) in enumerate(fallen):
        layer = "far" if fi == 3 else "near"
        z0 = mound_height(x0, y0) + r0
        p0, p1 = Vector((x0, y0, z0)), Vector((x1, y1, r0 * 0.9))
        pts = K.curve_points(p0, p1, bend=Vector((0, 0, 0.03)), n=10)
        obj(f"QqFallen{fi}", K.tube_build(pts, lambda t, r0=r0: r0 * (1 - 0.35 * t), 10),
            m["culm" if layer == "near" else "culm_far"], "thin", root, sharp_deg=0)
        for t in (0.10, 0.30, 0.50, 0.70, 0.88):
            p, d = _path_at(pts, t)
            rings[layer].append((p, d, r0 * (1 - 0.35 * t) * 1.16, 0.02))
        d = (p1 - p0).normalized()
        side = Vector((-d.y, d.x, 0))
        for t in (0.66, 0.90):
            p, _ = _path_at(pts, t)
            out = (d * 0.5 + side * (1 if t > 0.8 else -1)).normalized()
            tip = p + out * 0.12 + Vector((0, 0, 0.03))
            twigs.append(K.curve_points(p, tip, n=4))
            leaves[layer].append(lambda bm, tip=tip, out=out: _leaf_cluster(
                bm, rng, tip, out, 5, size=0.95, spread=0.9, droop_range=(-0.25, 0.0)))
    # 满地落叶：一圈散开，少数枯黄
    for k in range(30):
        ang = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.35, 1.0)
        x, y = rr * math.cos(ang) * 1.0, rr * math.sin(ang) * 0.62
        z = mound_height(x, y) + 0.008
        d = Vector((math.cos(ang + rng.uniform(-1.2, 1.2)), math.sin(ang + rng.uniform(-1.2, 1.2)), 0.0))
        L, Wd, roll = rng.uniform(0.17, 0.25), rng.uniform(0.036, 0.048), rng.uniform(-0.3, 0.3)
        target = leaves["dry"] if rng.random() < 0.3 else leaves["near"]
        target.append(lambda bm, x=x, y=y, z=z, d=d, L=L, Wd=Wd, roll=roll:
                      _add_leaf(bm, (x, y, z), d, L, Wd, droop=0.0, fold=0.2, roll=roll))
    for layer in ("near", "far"):
        suf = "" if layer == "near" else "_far"
        obj(f"QqNodes{suf}", _rings_build(rings[layer]), m["node" + suf], "none", root, smooth=False)
        obj(f"QqLeaves{suf}", lambda bm, L=leaves[layer]: [f(bm) for f in L], m["leaf" + suf], "none", root, smooth=False)
    obj("QqLeavesDry", lambda bm: [f(bm) for f in leaves["dry"]], m["leaf_dry"], "none", root, smooth=False)
    obj("QqTwigs", lambda bm: [K.tube_build(tp, lambda t: 0.0075 * (1 - 0.5 * t), 5)(bm) for tp in twigs],
        m["twig"], "none", root, sharp_deg=0)
    sockets = {"feet": B.empty("BambooBrokenFeet", clump)}
    bpy.context.view_layer.update()
    return clump, {"root": clump}, sockets


# ================================================================ 石狐（石狐、狐仙祠里的小狐共用）
def _stone_fox(prefix, parent, mats, bib, moss=None, loc=(0, 0, 0), scale=1.0, yaw_deg=-40.0, head_yaw_deg=-16.0,
               line="outer"):
    """蹲坐的狐：后胯着地、前腿直立、昂头竖耳、尖嘴，大尾巴从身后绕到身体左侧（+X）盖住前爪，尾尖白；
    脖子上一块三角围嘴。scale=1 时耳尖约 0.53 米，建模面朝 -Y，pivot 在脚下；yaw 让身体侧过来露出尖嘴。
    mats 要有 stone、tip（尾尖）、eye、dark。"""
    piv = B.empty(f"{prefix}Pivot", parent, loc=loc, rot=(0, 0, math.radians(yaw_deg)))
    piv.scale = (scale, scale, scale)
    obj = B.mesh_object
    st = mats["stone"]
    parts = []
    parts.append(obj(f"{prefix}Haunch", K.boulder_build((0.12, 0.15, 0.10), seed=1.0, big=0.06, small=0.03), st, line, piv,
                     loc=(0, 0.05, 0.095)))
    parts.append(obj(f"{prefix}Chest", K.boulder_build((0.08, 0.085, 0.165), seed=2.0, big=0.05, small=0.03), st, line,
                     piv, loc=(0, -0.035, 0.225), rot=(math.radians(-12), 0, 0)))
    head = B.empty(f"{prefix}HeadPivot", piv, loc=(0, -0.055, 0.375), rot=(0, 0, math.radians(head_yaw_deg)))
    parts.append(obj(f"{prefix}Head", K.boulder_build((0.068, 0.072, 0.06), seed=3.0, big=0.04, small=0.02), st, line,
                     head))
    K.limb(f"{prefix}Snout", (0, -0.045, -0.008), (0, -0.155, -0.03), 0.044, 0.013, st, "inner", head, segs=10)
    obj(f"{prefix}Nose", B.uv_sphere(0.015, 8, 6), mats["eye"], "none", head, loc=(0, -0.16, -0.029))
    for sx in (-1, 1):
        K.limb(f"{prefix}Ear{sx:+d}", (0.038 * sx, 0.005, 0.035), (0.06 * sx, 0.02, 0.15), 0.036, 0.003, st, "inner", head,
               segs=6)
        # 刻出来的眼：斜挑的一道浓墨
        obj(f"{prefix}Eye{sx:+d}", K.ellipsoid((0.02, 0.007, 0.007), 10, 6), mats["eye"], "none", head,
            loc=(0.035 * sx, -0.058, 0.014), rot=(0, math.radians(-22 * sx), math.radians(-25 * sx)))
        # 前腿 + 爪，后脚
        K.limb(f"{prefix}Leg{sx:+d}", (0.045 * sx, -0.075, 0.17), (0.045 * sx, -0.09, 0.02), 0.024, 0.019, st, "inner",
               piv, segs=8)
        obj(f"{prefix}Paw{sx:+d}", K.ellipsoid((0.026, 0.038, 0.017), 10, 6), st, "inner", piv,
            loc=(0.045 * sx, -0.11, 0.017))
        obj(f"{prefix}Hind{sx:+d}", K.ellipsoid((0.032, 0.065, 0.022), 10, 6), st, "inner", piv,
            loc=(0.11 * sx, -0.025, 0.022))
    # 尾巴：从身后绕到身体左侧（+X），尾尖（白）盖在前爪上
    tail = [Vector(p) for p in ((0.02, 0.18, 0.055), (0.13, 0.15, 0.06), (0.185, 0.03, 0.06), (0.165, -0.08, 0.055),
                                (0.11, -0.145, 0.05), (0.06, -0.17, 0.045))]
    parts.append(obj(f"{prefix}Tail", K.tube_build(tail, K.bushy(0.068, peak=0.45, tip=0.012), 12, flat=0.78,
                                                   zones=lambda t: 1 if t > 0.80 else 0),
                     [st, mats["tip"]], line, piv, sharp_deg=0))
    # 围嘴：脖子前面半圈 → 胸前一个尖
    zc, rows = 0.315, []
    tip = Vector((0, -0.125, 0.20))
    for v in range(4):
        f = v / 3
        row = []
        for u in range(7):
            th = math.radians(200 + 140 * u / 6)
            c = Vector((0.076 * math.cos(th), -0.045 + 0.078 * math.sin(th), zc))
            p = c.lerp(tip, f)
            p += Vector((0, -0.012 * math.sin(math.pi * u / 6), 0)) * (1 - f)
            row.append(p)
        rows.append(row)
    obj(f"{prefix}Bib", K.grid_build(rows, outward_from=Vector((0, 0.05, 0))), bib, "inner", piv)
    if moss is not None:
        for p in parts:
            obj(p.name + "Moss", lambda bm, src=p: bm.from_mesh(src.data), moss, "none", p.parent,
                loc=p.location, rot=p.rotation_euler, scale=(1.03, 1.03, 1.03), sharp_deg=0, contour=True)
    return piv


STONE_FOX_K = 1.5  # 整体放大（石座 + 石狐，比例不变）：原来在灯光里只有石子大


def build_stone_fox():
    m = _mats()
    root = B.empty("StoneFox")
    sc = B.empty("StoneFoxScale", root)  # 几何都挂在放大的空物体下，挂点 feet 仍挂在根上
    sc.scale = (STONE_FOX_K,) * 3
    obj = B.mesh_object
    # 方石座：两层，略转一点角度，露出两个侧面
    seat = B.empty("StoneFoxSeat", sc, rot=(0, 0, math.radians(-14)))
    for nm, build in (("StoneFoxBase", _prism(0.31, 0.30, 0.0, 0.07, seg=4, rot=math.radians(45))),
                      ("StoneFoxBase2", _prism(0.27, 0.26, 0.07, 0.14, seg=4, rot=math.radians(45)))):
        obj(nm, build, m["stone"], "outer", seat, smooth=False, scale=(1.0, 0.8, 1.0))
        obj(nm + "Moss", build, m["moss_thin"], "none", seat, smooth=False, scale=(1.015, 0.81, 1.02), contour=True)
    _stone_fox("Fox", sc, {"stone": m["stone"], "tip": m["white"], "eye": m["eye"], "dark": m["dark"]},
               m["bib_faded"], moss=m["moss"], loc=(0.0, 0.02, 0.14), scale=1.22)
    sockets = {"feet": B.empty("StoneFoxFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


# ================================================================ 四坡翘角瓦顶（狐仙祠、狐灯共用）
def _hip_roof_build(hx, hy, z_eave, rise, curl, nf=16, ns=6, nlev=6, fascia=0.035, flare=0.07, s_top=0.93,
                    edge_pow=2.5, edge_w=0.45):
    """四坡顶（庑殿）：一圈一圈往上收的矩形环，四坡同坡度（屋脊半长 = hx - hy），坡面下凹（近檐平、近脊陡）；
    檐口整条往两端翘起，四个翼角最高（curl），翼角还往外挑一点（flare）。最下面再往下折一道 fascia 高的檐边
    （材质槽 1，浓墨，渲出来是一道弯弯的墨线）。顶上留一条窄缝封平，屋脊管盖住。
    返回 build；build.grid = (每环点数, 环数)，build.cols = {前檐的列号, 四个角的列号}，给 _mark_tiles 标瓦垄。"""
    per = []
    for i in range(nf):
        per.append((-1 + 2 * i / nf, -1.0))
    for i in range(ns):
        per.append((1.0, -1 + 2 * i / ns))
    for i in range(nf):
        per.append((1 - 2 * i / nf, 1.0))
    for i in range(ns):
        per.append((-1.0, 1 - 2 * i / ns))
    P = len(per)
    corners = {0, nf, nf + ns, 2 * nf + ns}

    def ring(s, dz=0.0):
        hys = hy * (1 - s)
        hxs = hx - hy * s
        z0 = z_eave + rise * s ** 1.6 + dz
        out = []
        for ex, ey in per:
            c = (abs(ex) ** 3) * (abs(ey) ** 3)  # 角上 1，坡面中间 0
            edge = abs(ex) ** edge_pow if abs(ey) == 1.0 else abs(ey) ** edge_pow  # 檐口沿边往两端翘
            lift = curl * (edge_w * edge + (1 - edge_w) * c) * (1 - s) ** 2
            k = 1 + flare * c * (1 - s)
            out.append(Vector((ex * hxs * k, ey * hys * k, z0 + lift)))
        return out

    def build(bm):
        rings = [ring(0.0, -fascia)] + [ring(s_top * j / (nlev - 1)) for j in range(nlev)]
        vs = [[bm.verts.new(p) for p in r] for r in rings]
        for j in range(len(vs) - 1):
            for i in range(P):
                f = bm.faces.new((vs[j][i], vs[j][(i + 1) % P], vs[j + 1][(i + 1) % P], vs[j + 1][i]))
                f.material_index = 1 if j == 0 else 0
        bm.faces.new(vs[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    build.grid = (P, nlev + 1)
    build.cols = {"front": set(range(1, nf)), "corners": corners}
    return build


def _mark_tiles(ob, P, nrings, cols):
    """瓦垄：前坡每隔一列、沿坡向的边标成 freestyle_edge（Freestyle 画内线）；四条戗脊（角上的列）也标上。
    顶点按环依次建：编号 = 环 × P + 列。不含檐边那一折。"""
    me = ob.data
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        a, b = e.vertices
        ja, ia = divmod(a, P)
        jb, ib = divmod(b, P)
        ok = ia == ib and ja != jb and min(ja, jb) >= 1 and max(ja, jb) < nrings
        ok = ok and ((ia in cols["front"] and ia % 2 == 0) or ia in cols["corners"])
        vals.append(ok)
    attr.data.foreach_set("value", vals)


def _roof(prefix, parent, m, hx, hy, y_c, z_eave, rise, curl, nf=16, tile="tile", fascia_mat="fascia", ridge_r=0.028,
          line="outer", contour=None, **kw):
    """line/contour：瓦顶的描线档（狐仙祠用 inner 且不进粗外轮廓，瓦顶显得轻）。"""
    build = _hip_roof_build(hx, hy, z_eave, rise, curl, nf=nf, **kw)
    roof = B.mesh_object(f"{prefix}Roof", build, [m[tile], m[fascia_mat]], line, parent, loc=(0, y_c, 0), smooth=False,
                         contour=contour)
    _mark_tiles(roof, *build.grid, build.cols)
    # 正脊：两端上卷（鸱尾）
    xr = hx - hy * 0.93
    zr = z_eave + rise * 0.93 ** 1.6 + 0.02
    ridge = [Vector(p) for p in ((-xr - 0.045, y_c, zr + 0.055), (-xr - 0.02, y_c, zr + 0.025), (-xr * 0.6, y_c, zr + 0.008),
                                 (0, y_c, zr + 0.004), (xr * 0.6, y_c, zr + 0.008), (xr + 0.02, y_c, zr + 0.025),
                                 (xr + 0.045, y_c, zr + 0.055))]
    B.mesh_object(f"{prefix}Ridge", K.tube_build(ridge, lambda t: ridge_r * (1 - 0.5 * abs(2 * t - 1) ** 3), 8), m["ridge"],
                  line, parent, sharp_deg=0, contour=contour)
    return roof


# ================================================================ 狐仙祠
SHRINE_GROW = 1.3  # 进游戏后再放大：灯光外只剩青灯和屋顶时也要像个地标（比石灯笼大）
SHRINE_K = 1.12 * SHRINE_GROW  # 整体放大（按 1 米左右建的；1.12 是原来的，好认一点）


def build_fox_shrine():
    m = _mats()
    lm = _lantern_mats("QqShrineLantern")
    root = B.empty("FoxShrine")
    sc = B.empty("FoxShrineScale", root)
    sc.scale = (SHRINE_K,) * 3
    obj = B.mesh_object
    st = m["stone"]
    # 两级石台
    for nm, (w, d, yc, z0, z1) in (("ShrineStep1", (0.72, 0.68, -0.02, 0.0, 0.10)),
                                   ("ShrineStep2", (0.60, 0.49, 0.025, 0.10, 0.18))):
        build = _box(w, z1 - z0, d)
        obj(nm, build, st, "outer", sc, loc=(0, yc, (z0 + z1) / 2), smooth=False)  # 有人照看，不长苔
    # 石龛：后墙 + 两侧墙 + 门楣，正面开龛（龛里浓墨）
    zb, zt = 0.18, 0.66
    obj("ShrineBack", _box(0.50, zt - zb, 0.07), st, "outer", sc, loc=(0, 0.175, (zb + zt) / 2), smooth=False)
    for sx in (-1, 1):
        obj(f"ShrineSide{sx:+d}", _box(0.11, zt - zb, 0.34), st, "outer", sc, loc=(0.195 * sx, 0.04, (zb + zt) / 2),
            smooth=False)
    obj("ShrineLintel", _box(0.30, 0.07, 0.34), st, "outer", sc, loc=(0, 0.04, zt - 0.035), smooth=False)
    obj("ShrineNiche", _box(0.28, zt - zb - 0.07, 0.01), m["dark"], "none", sc, loc=(0, 0.135, (zb + zt - 0.07) / 2),
        smooth=False)
    obj("ShrineNicheFloor", _box(0.28, 0.006, 0.30), m["dark"], "none", sc, loc=(0, 0.0, zb + 0.003), smooth=False)
    # 朱砂立柱
    for sx in (-1, 1):
        K.limb(f"ShrinePillar{sx:+d}", (0.152 * sx, -0.145, zb), (0.152 * sx, -0.145, zt), 0.027, 0.025, m["red"], "inner",
               sc, segs=10)
    # 四坡翘角瓦顶
    # 轻一点的瓦顶：淡墨瓦、细檐边、坡缓、出檐浅，檐口一条匀匀的弧线往翼角挑起；只描细线，不进粗外轮廓
    _roof("Shrine", sc, m, hx=0.35, hy=0.26, y_c=0.04, z_eave=zt + 0.03, rise=0.12, curl=0.075, nf=14, tile="tile_light",
          fascia_mat="fascia_light", ridge_r=0.017, fascia=0.016, flare=0.06, edge_pow=3.0, edge_w=0.55,
          line="inner", contour=False)
    # 龛里的白石狐（朱砂围嘴，有人照看，是新的）
    _stone_fox("ShrineFox", sc, {"stone": m["white"], "tip": m["white"], "eye": m["eye"], "dark": m["dark"]}, m["red"],
               loc=(0.0, 0.0, zb + 0.006), scale=0.68, yaw_deg=-26.0, head_yaw_deg=-6.0)
    # 供品（摆在下一级台阶上）：一碟白团子、一碗果子
    oy, oz = -0.29, 0.10
    obj("ShrinePlate", B.cylinder(0.055, 0.045, 0.014, 16), m["bowl"], "inner", sc, loc=(-0.10, oy, oz + 0.007))
    for k, (dx, dy, dz) in enumerate(((-0.022, 0.0, 0.0), (0.022, 0.0, 0.0), (0.0, -0.018, 0.0), (0.0, 0.0, 0.032))):
        obj(f"ShrineBun{k}", B.uv_sphere(0.022, 10, 6), m["bun"], "inner", sc, loc=(-0.10 + dx, oy + dy, oz + 0.032 + dz))
    obj("ShrineBowl", B.lathe([(0.0, 0.0), (0.03, 0.0), (0.05, 0.03), (0.052, 0.045)], 14, cap_top=False), m["bowl"],
        "inner", sc, loc=(0.10, oy, oz))
    for k, (dx, dy, dz) in enumerate(((-0.018, 0.0, 0.0), (0.018, 0.005, 0.0), (0.0, -0.012, 0.022))):
        obj(f"ShrineFruit{k}", B.uv_sphere(0.022, 10, 6, scale=(1, 1, 0.9)), m["fruit"], "inner", sc,
            loc=(0.10 + dx, oy + dy, oz + 0.05 + dz))
    # 檐角下挂一盏小青灯
    hook = Vector((0.29, -0.22, zt + 0.04))
    lr, lh = 0.058, 0.068
    lc = hook - Vector((0, 0, 0.10 + lh))
    K.limb("ShrineLampCord", hook, lc + Vector((0, 0, lh)), 0.004, 0.004, m["rope"], "none", sc, segs=4)
    sock = _paper_lantern("ShrineLantern", sc, lc, lr, lh, lm)
    sockets = {"glow": sock, "feet": B.empty("ShrineFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


# ================================================================ 狐灯
def build_fox_lanterns():
    """两根木柱、一根竹梁撑一段四坡翘角瓦檐，檐下一根绳挂三盏青纸灯。"""
    m = _mats()
    lm = _lantern_mats("QqFoxLantern", open_facing=0.17)  # 窗开小一点，多露出青纸和竹篾
    root = B.empty("FoxLanterns")
    obj = B.mesh_object
    px, zt = 0.52, 1.16
    for sx in (-1, 1):
        obj(f"FoxPostFoot{sx:+d}", _prism(0.08, 0.065, 0.0, 0.08, seg=6), m["stone"], "outer", root, loc=(px * sx, 0.02, 0),
            smooth=False)
        K.limb(f"FoxPost{sx:+d}", (px * sx, 0.02, 0.06), (px * sx, 0.02, zt + 0.02), 0.036, 0.032, m["wood"], "inner", root,
               segs=10)
    # 横梁（竹，带两个节）
    beam = [Vector((-px - 0.10, 0.02, zt - 0.03)), Vector((px + 0.10, 0.02, zt - 0.03))]
    obj("FoxBeam", K.tube_build(beam, lambda t: 0.032, 10), m["culm"], "inner", root, sharp_deg=0)
    rings = [(Vector((x, 0.02, zt - 0.03)), Vector((1, 0, 0)), 0.032 * 1.16, 0.02) for x in (-0.26, 0.26)]
    obj("FoxNodes", _rings_build(rings), m["node"], "none", root, smooth=False)
    # 左柱上贴一条朱砂纸符，上面几笔墨
    fx, fy, fz = -px, 0.02 - 0.036 - 0.004, 0.80
    obj("FoxCharm", _box(0.066, 0.21, 0.005), m["red"], "thin", root, loc=(fx, fy, fz), rot=(0, math.radians(3), 0),
        smooth=False)
    for k, (dx, dz, w, h) in enumerate(((0.0, 0.065, 0.034, 0.010), (0.0, 0.02, 0.010, 0.07), (-0.012, -0.035, 0.026, 0.010),
                                        (0.008, -0.07, 0.022, 0.009))):
        obj(f"FoxCharmInk{k}", _box(w, h, 0.003), m["eye"], "none", root, loc=(fx + dx, fy - 0.004, fz + dz),
            rot=(0, math.radians(3), 0), smooth=False)
    _roof("Fox", root, m, hx=0.74, hy=0.27, y_c=0.03, z_eave=zt + 0.05, rise=0.21, curl=0.11, nf=18)
    # 檐下的绳：两柱之间下垂
    zr, sag = zt - 0.08, 0.10
    rope = [Vector((x, -0.02, zr - sag * (1 - (x / px) ** 2))) for x in np.linspace(-px, px, 13)]
    obj("FoxRope", K.tube_build(rope, lambda t: 0.007, 5), m["rope"], "none", root, sharp_deg=0)
    socks = {}
    lr, lh = 0.092, 0.108
    centers = []
    for k, (x, drop) in enumerate(((-0.29, 0.07), (0.0, 0.12), (0.29, 0.06))):
        top = Vector((x, -0.02, zr - sag * (1 - (x / px) ** 2)))
        lc = top - Vector((0, 0, drop + lh))
        K.limb(f"FoxLampCord{k}", top, lc + Vector((0, 0, lh)), 0.004, 0.004, m["rope"], "none", root, segs=4)
        socks[f"glow_{k}"] = _qing_lantern(f"FoxLantern{k}", root, lc, lr, lh, lm)
        centers.append(lc)
    socks["glow"] = B.empty("FoxLanternsGlow", root, loc=sum(centers, Vector()) / len(centers))
    socks["feet"] = B.empty("FoxLanternsFeet", root)
    bpy.context.view_layer.update()
    return root, {"root": root}, socks


# ================================================================ 狐祠庭院：大狐仙祠、石牌坊、檐下留灯
GRAND_FRAME_1X = 256  # 大狐仙祠（2 倍 512²）
GATE_FRAME_1X = 192  # 石牌坊（2 倍 384²）
HANGING_ANCHOR = (0.5, 0.1)  # 挂着的道具（檐下留灯）：锚点是挂钩顶端，灯挂在它下面
EAVE_LAMP_GLOW = "#FF9A4A"  # 留灯的光色：主角红纸灯的火（assets/data/lamps.ron 的 red）


def _roof_k(prefix, parent, m, k, **kw):
    """放大 k 倍的 _roof：几何挂在放大的空物体下，鸱尾、檐边、屋脊一起变粗；尺寸参数照实际米数给。"""
    sc = B.empty(f"{prefix}RoofScale", parent)
    sc.scale = (k,) * 3
    for key in ("hx", "hy", "y_c", "z_eave", "rise", "curl", "ridge_r", "fascia"):
        if key in kw:
            kw[key] = kw[key] / k
    return _roof(prefix, sc, m, **kw)


def _skirt(prefix, parent, m, hx, hy, y_c, z_eave, rise, curl, s_top=0.55, nf=18, **kw):
    """重檐的下檐：一圈四坡瓦檐，只做到 s_top（顶上封平，被上层墙身盖住），不做屋脊。"""
    build = _hip_roof_build(hx, hy, z_eave, rise, curl, nf=nf, s_top=s_top, **kw)
    ob = B.mesh_object(f"{prefix}Skirt", build, [m["tile_light"], m["fascia_light"]], "inner", parent, loc=(0, y_c, 0),
                       smooth=False, contour=False)
    _mark_tiles(ob, *build.grid, build.cols)
    return ob


def _plate_build(poly_xz, depth):
    """xz 平面上的多边形（逆时针）沿 y 挤出 depth（居中）：雀替这类薄石板。"""
    def build(bm):
        f = [bm.verts.new((x, -depth / 2, z)) for x, z in poly_xz]
        b = [bm.verts.new((x, depth / 2, z)) for x, z in poly_xz]
        n = len(f)
        bm.faces.new(f)
        bm.faces.new(list(reversed(b)))
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((f[j], f[i], b[i], b[j]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _banner_build(top, width, length, sway=0.03, phase=0.0):
    """布幡：从 top 垂下的一条布，微微飘（下半截往前、往一侧摆），下缘燕尾。"""
    t0 = Vector(top)

    def build(bm):
        rows = []
        nv = 8
        for j in range(nv + 1):
            t = j / nv
            off = Vector((sway * math.sin(math.pi * t + phase) * t, -0.6 * sway * t * t, -length * t))
            row = []
            for u in (-0.5, 0.0, 0.5):
                notch = 0.18 * length * t ** 8 * (1 - 2 * abs(u))  # 燕尾：中间往上缩
                row.append(t0 + off + Vector((u * width * (1 - 0.08 * t), 0, notch)))
            rows.append(row)
        vs = [[bm.verts.new(p) for p in r] for r in rows]
        for j in range(nv):
            for i in range(2):
                bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
        for f in bm.faces:
            if f.normal.y > 0:
                f.normal_flip()
    return build


def build_fox_shrine_grand():
    """大狐仙祠（狐祠庭院的正殿）：按自己的尺寸建（约 3.4 米高、3.5 米宽），不是把小祠放大。
    两层石台基，正面四级台阶；三开间：明间是龛（白石狐坐在石座上），
    两次间是石墙，各开一个小龛供一颗白石狐珠，墙前额枋下各垂一条褪色朱砂布幡；四根朱砂柱、一道淡墨额枋；
    重檐四坡顶（淡墨瓦、翼角起翘，正脊中间一个葫芦宝顶）。台阶上方一张石供桌：一碟白团子、三足香炉插三炷香、一碗果子。
    右前檐角挂一盏小青灯（发光，挂点 glow）；左次间檐下一个小铁钩（挂点 eave_lamp = 钩子下端，挂檐下留灯）。"""
    m = _mats()
    lm = _lantern_mats("QqGrandLantern")
    banner = K.toon("QqGrandBanner", W["zhusha"], wash=0.35, edge=0.3, seed=341.0)
    beam = K.toon("QqGrandBeam", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.25, edge=0.3, seed=342.0)
    root = B.empty("FoxShrineGrand")
    obj = B.mesh_object
    st = m["stone"]
    # 两层台基 + 台阶（四级，每级高 0.1、深 0.2）
    obj("GrandBase1", _box(3.5, 0.2, 2.3), st, "outer", root, loc=(0, -0.05, 0.1), smooth=False)
    obj("GrandBase2", _box(3.0, 0.2, 1.75), st, "outer", root, loc=(0, 0.08, 0.3), smooth=False)
    for k, (y0, y1, z0, z1) in enumerate(((-1.6, -1.2, 0.0, 0.1), (-1.4, -1.2, 0.1, 0.2), (-1.2, -0.795, 0.2, 0.3),
                                          (-1.0, -0.795, 0.3, 0.4))):
        obj(f"GrandStep{k}", _box(1.1, z1 - z0, y1 - y0), st, "outer", root, loc=(0, (y0 + y1) / 2, (z0 + z1) / 2),
            smooth=False)
    # 殿身：两次间是实心石墙块（前脸就是墙），明间后墙；明间里面浓墨
    zb, zt = 0.4, 1.84
    yf, yb = -0.38, 0.72
    for sx in (-1, 1):
        obj(f"GrandWing{sx:+d}", _box(0.8, zt - zb, yb - yf), st, "outer", root, loc=(0.85 * sx, (yf + yb) / 2, (zb + zt) / 2),
            smooth=False)
        # 次间小龛：浓墨龛口、石台沿，上面供一颗白石狐珠
        obj(f"GrandSideNiche{sx:+d}", _box(0.30, 0.34, 0.01), m["dark"], "none", root, loc=(0.85 * sx, yf - 0.006, 0.79),
            smooth=False)
        obj(f"GrandSideSill{sx:+d}", _box(0.40, 0.04, 0.08), st, "inner", root, loc=(0.85 * sx, yf - 0.035, 0.60),
            smooth=False)
        obj(f"GrandPearlStand{sx:+d}", B.cylinder(0.05, 0.04, 0.035, 12), st, "inner", root,
            loc=(0.85 * sx, yf - 0.05, 0.6375))
        obj(f"GrandPearl{sx:+d}", B.uv_sphere(0.072, 14, 8), m["white"], "inner", root, loc=(0.85 * sx, yf - 0.05, 0.725))
    obj("GrandBack", _box(0.9, zt - zb, 0.1), st, "outer", root, loc=(0, 0.67, (zb + zt) / 2), smooth=False)
    obj("GrandNiche", _box(0.9, zt - zb, 0.01), m["dark"], "none", root, loc=(0, 0.614, (zb + zt) / 2), smooth=False)
    obj("GrandNicheFloor", _box(0.9, 0.006, 1.0), m["dark"], "none", root, loc=(0, 0.12, zb + 0.003), smooth=False)
    # 龛里：石座 + 白石狐（朱砂围嘴，有人照看）
    obj("GrandFoxSeat", _box(0.56, 0.16, 0.40), st, "inner", root, loc=(0, 0.30, zb + 0.08), smooth=False)
    _stone_fox("GrandFox", root, {"stone": m["white"], "tip": m["white"], "eye": m["eye"], "dark": m["dark"]}, m["red"],
               loc=(0.0, 0.30, zb + 0.16), scale=1.2, yaw_deg=-26.0, head_yaw_deg=-6.0)
    # 朱砂柱（石柱础）+ 额枋
    yp = -0.45
    for k, x in enumerate((-1.15, -0.42, 0.42, 1.15)):
        obj(f"GrandPillarBase{k}", B.cylinder(0.105, 0.115, 0.06, 12), st, "inner", root, loc=(x, yp, zb + 0.03))
        K.limb(f"GrandPillar{k}", (x, yp, zb + 0.06), (x, yp, zt - 0.13), 0.068, 0.062, m["red"], "inner", root, segs=12)
    obj("GrandBeam", _box(2.64, 0.14, 0.14), beam, "inner", root, loc=(0, yp, zt - 0.07), smooth=False)
    # 次间墙前、额枋下各垂一条布幡（顶上一根墨色挑杆）
    for sx in (-1, 1):
        bx = 0.62 * sx
        obj(f"GrandBanner{sx:+d}", _banner_build((bx, yp - 0.09, zt - 0.16), 0.16, 0.58, sway=0.025 * sx,
                                                 phase=0.4 * sx), banner, "inner", root, smooth=False)
        K.limb(f"GrandBannerRod{sx:+d}", (bx - 0.105, yp - 0.09, zt - 0.155), (bx + 0.105, yp - 0.09, zt - 0.155), 0.011,
               0.011, m["rope"], "none", root, segs=6)
    # 供桌：石板 + 两条腿；白团子、三足香炉（三炷香）、果子
    ty, tz = -0.62, zb + 0.30
    obj("GrandTableTop", _box(0.74, 0.05, 0.26), st, "inner", root, loc=(0, ty, tz - 0.025), smooth=False)
    for sx in (-1, 1):
        obj(f"GrandTableLeg{sx:+d}", _box(0.08, 0.25, 0.20), st, "inner", root, loc=(0.27 * sx, ty, zb + 0.125), smooth=False)
    obj("GrandPlate", B.cylinder(0.075, 0.062, 0.016, 16), m["bowl"], "inner", root, loc=(-0.22, ty, tz + 0.008))
    for k, (dx, dy, dz) in enumerate(((-0.03, 0.0, 0.0), (0.03, 0.0, 0.0), (0.0, -0.025, 0.0), (0.0, 0.0, 0.045))):
        obj(f"GrandBun{k}", B.uv_sphere(0.031, 10, 6), m["bun"], "inner", root, loc=(-0.22 + dx, ty + dy, tz + 0.045 + dz))
    obj("GrandBurner", B.lathe([(0.0, 0.0), (0.05, 0.0), (0.072, 0.03), (0.075, 0.06), (0.068, 0.075)], 16, cap_top=True),
        m["bowl"], "inner", root, loc=(0, ty, tz + 0.03))
    for k in range(3):
        th = math.radians(90 + 120 * k)
        K.limb(f"GrandBurnerLeg{k}", (0.045 * math.cos(th), ty + 0.045 * math.sin(th), tz + 0.035),
               (0.05 * math.cos(th), ty + 0.05 * math.sin(th), tz), 0.009, 0.007, m["bowl"], "none", root, segs=6)
        sx = (k - 1) * 0.022
        K.limb(f"GrandIncense{k}", (sx, ty, tz + 0.09), (sx * 1.6, ty - 0.006, tz + 0.25), 0.004, 0.004, m["rope"], "none",
               root, segs=4)
        obj(f"GrandIncenseTip{k}", B.uv_sphere(0.007, 6, 4), m["red"], "none", root, loc=(sx * 1.6, ty - 0.006, tz + 0.252))
    obj("GrandBowl", B.lathe([(0.0, 0.0), (0.04, 0.0), (0.068, 0.04), (0.07, 0.06)], 14, cap_top=False), m["bowl"],
        "inner", root, loc=(0.22, ty, tz))
    for k, (dx, dy, dz) in enumerate(((-0.024, 0.0, 0.0), (0.024, 0.006, 0.0), (0.0, -0.016, 0.03))):
        obj(f"GrandFruit{k}", B.uv_sphere(0.03, 10, 6, scale=(1, 1, 0.9)), m["fruit"], "inner", root,
            loc=(0.22 + dx, ty + dy, tz + 0.066 + dz))
    # 重檐：下檐（只做一圈）+ 上层墙身 + 上檐（带正脊、鸱尾）
    yc = 0.17
    z1, hx1, hy1 = 2.05, 1.56, 0.92
    _skirt("Grand", root, m, hx=hx1, hy=hy1, y_c=yc, z_eave=z1, rise=0.34, curl=0.13, fascia=0.035, flare=0.06,
           edge_pow=3.0, edge_w=0.55)
    obj("GrandUpperWall", _box(2.16, 0.40, 0.88), st, "inner", root, loc=(0, yc, 2.30), smooth=False)
    z2, rise2 = 2.50, 0.72
    _roof_k("GrandUpper", root, m, 1.5, hx=1.30, hy=0.62, y_c=yc, z_eave=z2, rise=rise2, curl=0.17, nf=18,
            tile="tile_light", fascia_mat="fascia_light", ridge_r=0.03, fascia=0.04, flare=0.06, edge_pow=3.0, edge_w=0.55,
            line="inner", contour=False)
    zr = z2 + rise2 * 0.93 ** 1.6 + 0.02 * 1.5  # 正脊高（同 _roof 的算法）
    # 正脊中间的宝顶：葫芦形（墨色）
    obj("GrandFinialBase", B.cylinder(0.06, 0.045, 0.05, 12), m["ridge"], "inner", root, loc=(0, yc, zr + 0.035))
    obj("GrandFinial", B.lathe([(0.0, 0.0), (0.05, 0.02), (0.058, 0.06), (0.03, 0.105), (0.036, 0.135), (0.03, 0.165),
                                (0.0, 0.19)], 14), m["ridge"], "inner", root, loc=(0, yc, zr + 0.055))
    # 右前檐角的小青灯
    hook = Vector((1.50, -0.70, 2.07))
    lr, lh = 0.085, 0.10
    lc = hook - Vector((0, 0, 0.16 + lh))
    K.limb("GrandLampCord", hook, lc + Vector((0, 0, lh)), 0.005, 0.005, m["rope"], "none", root, segs=4)
    glow = _paper_lantern("GrandLantern", root, lc, lr, lh, lm)
    # 左次间檐下的小铁钩：钩子下端就是 eave_lamp（檐下留灯的挂绳顶端对准这里）
    ex, ey = -0.90, yc - hy1 + 0.025
    ez = z1 - 0.035 + 0.13 * 0.55 * (abs(ex) / hx1) ** 3.0 - 0.05  # 檐口下沿往下 5 厘米
    K.limb("GrandEaveHook", (ex, ey, ez + 0.09), (ex, ey, ez + 0.012), 0.007, 0.006, m["rope"], "none", root, segs=6)
    obj("GrandEaveHookTip", B.uv_sphere(0.012, 8, 6), m["rope"], "none", root, loc=(ex, ey, ez + 0.006))
    sockets = {"glow": glow, "eave_lamp": B.empty("GrandEaveLamp", root, loc=(ex, ey, ez)),
               "feet": B.empty("GrandFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


def build_fox_gate():
    """石牌坊（狐祠庭院的入口，冲天柱式一间两柱一楼，中式，不是鸟居）：两根方石柱各夹一对方墩（夹杆石），
    柱子穿过屋顶往上冲，柱头一个石雕的宝珠头；两柱之间小额枋、花板、大额枋三层（花板两边各刻一块浅浮雕方框，
    额枋两头出头），正中一块空白石匾（浓墨边框，只盖一方朱砂小印，没有字），柱和小额枋之间一对雀替；
    大额枋上一段夹在两柱之间的四坡翘角瓦顶（淡墨瓦、瓦垄、正脊两端鸱尾）。石头风化，墩、额枋、柱头有苔，
    左柱上系一条褪色的红布。约 3 米宽、3.2 米高，门洞净宽约 1.8 米、净高 2.4 米。"""
    m = _mats()
    st = m["stone"]
    moss = m["moss_thin"]
    carve = K.toon("QqGateCarve", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.3, edge=0.3, seed=362.0)
    root = B.empty("FoxGate")
    obj = B.mesh_object
    px = 1.15
    z_lo, z_pa, z_hi, z_top = 2.40, 2.51, 2.65, 2.78  # 小额枋底、花板底、大额枋底、大额枋顶
    Z_PILLAR = 2.98  # 冲天柱顶（柱头另算）

    def mossy(name, build, loc=(0, 0, 0), k=1.02, mat=moss):
        obj(name + "Moss", build, mat, "none", root, loc=loc, smooth=False, scale=(k, k, 1.0 + (k - 1) / 2), contour=True)

    for sx in (-1, 1):
        x = px * sx
        pl = _prism(0.36, 0.33, 0.0, 0.52, seg=4, rot=math.radians(45))
        obj(f"GatePlinth{sx:+d}", pl, st, "outer", root, loc=(x, 0, 0), smooth=False)
        mossy(f"GatePlinth{sx:+d}", pl, loc=(x, 0, 0), mat=m["moss"])
        cap = _prism(0.33, 0.25, 0.52, 0.60, seg=4, rot=math.radians(45))
        obj(f"GatePlinthCap{sx:+d}", cap, st, "outer", root, loc=(x, 0, 0), smooth=False)
        mossy(f"GatePlinthCap{sx:+d}", cap, loc=(x, 0, 0), mat=m["moss"])
        obj(f"GatePillar{sx:+d}", _prism(0.172, 0.158, 0.0, Z_PILLAR, seg=4, rot=math.radians(45)), st, "outer", root,
            loc=(x, 0, 0), smooth=False)
        # 冲天柱头：一块方帽石 + 宝珠头
        hat = _prism(0.2, 0.19, Z_PILLAR, Z_PILLAR + 0.05, seg=4, rot=math.radians(45))
        obj(f"GatePillarHat{sx:+d}", hat, st, "outer", root, loc=(x, 0, 0), smooth=False)
        bud = B.lathe([(0.0, 0.0), (0.10, 0.0), (0.115, 0.025), (0.085, 0.05), (0.10, 0.07), (0.07, 0.10), (0.0, 0.125)], 16)
        obj(f"GatePillarBud{sx:+d}", bud, st, "outer", root, loc=(x, 0, Z_PILLAR + 0.05))
        mossy(f"GatePillarBud{sx:+d}", bud, loc=(x, 0, Z_PILLAR + 0.05), k=1.03, mat=m["moss"])
        # 雀替：柱子内侧、小额枋下面的一块弯石板
        xi = x - 0.115 * sx
        poly = [(xi, z_lo), (xi, z_lo - 0.27), (xi - 0.05 * sx, z_lo - 0.17), (xi - 0.15 * sx, z_lo - 0.08),
                (xi - 0.26 * sx, z_lo - 0.03), (xi - 0.36 * sx, z_lo)]
        if sx < 0:
            poly = poly[::-1]
        obj(f"GateBracket{sx:+d}", _plate_build(poly, 0.12), st, "inner", root, smooth=False)
    # 三层额枋：小额枋、花板（缩进一点，两边各一块浅浮雕方框）、大额枋
    lo = _box(2.62, z_pa - z_lo, 0.20)
    obj("GateBeamLow", lo, st, "outer", root, loc=(0, 0, (z_lo + z_pa) / 2), smooth=False)
    mossy("GateBeamLow", lo, loc=(0, 0, (z_lo + z_pa) / 2), k=1.01)
    obj("GatePanel", _box(2.30, z_hi - z_pa, 0.10), st, "inner", root, loc=(0, 0.02, (z_pa + z_hi) / 2), smooth=False)
    for sx in (-1, 1):
        obj(f"GatePanelCarve{sx:+d}", _box(0.50, 0.075, 0.01), carve, "inner", root, loc=(0.70 * sx, -0.034, (z_pa + z_hi) / 2),
            smooth=False)
    hi = _box(2.86, z_top - z_hi, 0.24)
    obj("GateBeamHigh", hi, st, "outer", root, loc=(0, 0, (z_hi + z_top) / 2), smooth=False)
    mossy("GateBeamHigh", hi, loc=(0, 0, (z_hi + z_top) / 2), k=1.01)
    # 石匾：浓墨边框、石面空白，正中一方朱砂小印（压在三层额枋前面）
    zc = (z_pa + z_hi) / 2
    obj("GatePlaqueFrame", _box(0.74, 0.28, 0.05), m["dark"], "inner", root, loc=(0, -0.125, zc), smooth=False)
    obj("GatePlaque", _box(0.62, 0.18, 0.02), m["white"], "none", root, loc=(0, -0.155, zc), smooth=False)
    obj("GatePlaqueSeal", _box(0.065, 0.065, 0.006), m["red"], "none", root, loc=(0, -0.167, zc), smooth=False)
    # 两柱之间的四坡翘角瓦顶：淡墨瓦、浓墨檐边、瓦垄、正脊两端鸱尾；出檐浅，露得出大额枋
    # （瓦上不罩苔：罩一层苔会挡住瓦垄的描线）
    _roof_k("Gate", root, m, 1.2, hx=1.02, hy=0.26, y_c=0.03, z_eave=2.86, rise=0.25, curl=0.12, nf=14,
            tile="tile_light", ridge_r=0.032, fascia=0.04, flare=0.07)
    # 左柱上系的红布：一圈布带 + 垂下的两条布尾
    cz = 1.32
    obj("GateCloth", _prism(0.19, 0.188, cz - 0.04, cz + 0.04, seg=4, rot=math.radians(45)), m["bib_faded"], "inner", root,
        loc=(-px, 0, 0), smooth=False)
    for k, (dx, L, ph) in enumerate(((-0.025, 0.40, 0.0), (0.03, 0.32, 1.3))):
        pts = [Vector((-px + dx + 0.03 * math.sin(2.2 * t + ph) * t, -0.14 - 0.03 * t, cz - 0.02 - L * t))
               for t in np.linspace(0, 1, 7)]
        obj(f"GateClothTail{k}", K.strip_build(pts, 0.05, 0.006, taper=(1.0, 0.7)), m["bib_faded"], "inner", root,
            smooth=False)
    sockets = {"feet": B.empty("FoxGateFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


def _eave_lamp(lit: bool):
    """檐下留灯：小圆纸灯笼（扁圆、十二根竹篾），木顶盖、木底托、朱砂穗，挂绳顶上一个小铁钩。
    原点 = 铁钩顶端（锚点），灯挂在下面：灯身直径约 0.35 米，从钩到穗尖约 0.78 米（石灯笼的一半高都不到）。
    lit=False：素白纸、墨线，不发光；lit=True：纸壳开窗露出暖色灯芯（发光），纸边一圈藤黄、赭石。挂点 flame 是灯芯。"""
    m = _mats()
    root = B.empty("FoxEaveLamp")
    obj = B.mesh_object
    if lit:
        shell = K.toon("QqEaveLampPaperLit", ramp=[W["tenghuang"], A["tenghuang"], A["zheshi"]], wash=0.2, edge=0.25,
                       seed=351.0)
        paper = B.window_material("QqEaveLampWindow", shell, open_facing=0.42)
        rib = B.flat_material("QqEaveLampRibLit", S.shade_ramp(A["zheshi"])[1])
    else:
        paper = K.toon("QqEaveLampPaper", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], wash=0.25, edge=0.3, seed=352.0)
        rib = B.flat_material("QqEaveLampRib", I["dan"])
    wood = K.toon("QqEaveLampWood", A["zheshi"], wash=0.3, edge=0.35, seed=353.0)
    # 铁钩（C 形）+ 挂绳
    ring = [Vector((0.016 * math.sin(a), 0.0, -0.016 + 0.016 * math.cos(a))) for a in np.linspace(0.0, math.radians(300), 9)]
    obj("EaveLampHook", K.tube_build(ring, lambda t: 0.0045, 6), m["rope"], "none", root, sharp_deg=0)
    r, h = 0.172, 0.152
    z_knob = -0.032 - 0.14
    cz = z_knob - 0.03 - 0.035 - h
    K.limb("EaveLampCord", (0, 0, -0.03), (0, 0, z_knob), 0.004, 0.004, m["rope"], "none", root, segs=4)
    obj("EaveLampKnob", B.cylinder(0.018, 0.024, 0.03, 10), wood, "inner", root, loc=(0, 0, z_knob - 0.015))
    obj("EaveLampCapTop", B.cylinder(0.075, 0.062, 0.035, 14), wood, "inner", root, loc=(0, 0, cz + h + 0.0175))
    # 扁圆纸壳：十二道竹篾处略鼓
    prof = [(0.066, -h), (0.62 * r, -0.86 * h), (0.86 * r, -0.58 * h), (r, -0.18 * h), (r, 0.18 * h), (0.86 * r, 0.58 * h),
            (0.62 * r, 0.86 * h), (0.066, h)]
    obj("EaveLampShell", B.lathe(prof, 24, radial=lambda th, z: 1 + 0.03 * abs(math.cos(6 * th))), paper, "outer", root,
        loc=(0, 0, cz), sharp_deg=0)

    def ribs(bm):
        for k in range(12):
            th = math.pi / 12 * 2 * k
            pts = [Vector((rr * 1.035 * math.cos(th), rr * 1.035 * math.sin(th), cz + z)) for rr, z in prof]
            K.tube_build(pts, lambda t: 0.0035, 4)(bm)
    obj("EaveLampRibs", ribs, rib, "none", root, sharp_deg=0)
    if lit:
        obj("EaveLampCore", B.uv_sphere(1.0, 16, 10, scale=(0.86 * r, 0.86 * r, 0.84 * h)), B.emissive_material(
            "QqEaveLampCore", S.LANTERN_LIGHT, 1.0), "none", root, loc=(0, 0, cz))
    obj("EaveLampCapBot", B.cylinder(0.062, 0.072, 0.03, 14), wood, "inner", root, loc=(0, 0, cz - h - 0.015))
    obj("EaveLampDrop", B.cylinder(0.022, 0.012, 0.03, 10), wood, "inner", root, loc=(0, 0, cz - h - 0.045))
    zk = cz - h - 0.075
    obj("EaveLampKnot", B.uv_sphere(0.017, 8, 6), m["red"], "none", root, loc=(0, 0, zk))
    K.limb("EaveLampTassel", (0, 0, zk - 0.01), (0, 0, zk - 0.13), 0.008, 0.026, m["red"], "thin", root, segs=10)
    sockets = {"flame": B.empty("EaveLampFlame", root, loc=(0, 0, cz)), "feet": B.empty("EaveLampTop", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


def build_fox_eave_lamp():
    return _eave_lamp(lit=False)


def build_fox_eave_lamp_lit():
    return _eave_lamp(lit=True)


BUILDERS = {
    "bamboo_clump": build_bamboo_clump,
    "bamboo_clump_broken": build_bamboo_clump_broken,
    "fox_shrine": build_fox_shrine,
    "stone_fox": build_stone_fox,
    "fox_lanterns": build_fox_lanterns,
    "fox_shrine_grand": build_fox_shrine_grand,
    "fox_gate": build_fox_gate,
    "fox_eave_lamp": build_fox_eave_lamp,
    "fox_eave_lamp_lit": build_fox_eave_lamp_lit,
}
