"""检视模型的公共件（规格见 docs/DESIGN.md 第 15 节“检视模型”）。

- 零件：每个零件是一个 Blender 物体，用 part() 登记属于哪个节点、描边粗细倍数、贴图密度倍数。
- 材质：只用一个 Principled BSDF（PMat），烘焙时把它的各个输入分别接到自发光上烘出来。
  细节靠凹凸、AO、倒角边（Bevel 节点）、程序噪声；底色另乘一层低频的“笔触”。
- 坐标：建模用米，Blender 里 +Z 朝上、正面朝 -Y；导出后是 glTF 的 +Y 朝上、+Z 朝前。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parents[1]
for _p in (ART, ART / "render", ART / "post", ART / "inspect"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import card_art as K  # noqa: E402

REPO = ART.parent
OUT_DIR = REPO / "assets" / "models" / "inspect"
TMP = ART / "out" / "_inspect_tmp"
REVIEW = ART / "out" / "review@2x"
FONT_FULL = ART / "out" / "fonts" / "MaShanZheng-Regular.ttf"  # post/ui_fonts.py 下载的完整字体（贴图用）


def font_path():
    """贴图上的字：有完整字体用完整的，没有退回游戏里的子集。"""
    return FONT_FULL if FONT_FULL.exists() else K.FONT_BRUSH


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


# ====================================================================== 零件登记


def part(ob, node, *, outline=1.0, density=1.0):
    """登记零件：node = 合并到哪个节点；outline = 描边粗细倍数（0 不描边）；density = 贴图密度倍数。"""
    ob["inspect_node"] = node
    ob["inspect_outline"] = float(outline)
    ob["inspect_density"] = float(density)
    return ob


def obj(name, build, mat, node, *, outline=1.0, density=1.0, smooth=True, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1),
        subsurf=0, sharp_deg=None, bevel=None):
    """建一个零件（card_art.make_obj）并登记。"""
    ob = K.make_obj(name, build, mat, smooth=smooth, loc=loc, rot=rot, scale=scale, subsurf=subsurf, sharp_deg=sharp_deg,
                    bevel=bevel)
    return part(ob, node, outline=outline, density=density)


def apply_transform(ob):
    """把物体的位移、旋转、缩放写进网格数据，物体变回单位变换。"""
    me = ob.data
    me.transform(ob.matrix_basis)
    ob.matrix_basis.identity()


# ====================================================================== 网格属性


def set_attr(me, name, values, domain="FACE"):
    """写一层浮点属性（FACE 或 POINT），材质里用 Attribute 节点读。"""
    if name in me.attributes:
        me.attributes.remove(me.attributes[name])
    at = me.attributes.new(name, "FLOAT", domain)
    at.data.foreach_set("value", np.asarray(values, np.float32).ravel())


def bm_face_attr(bm, name):
    """bmesh 里的面浮点层（to_mesh 后成为 FACE 属性）。"""
    lay = bm.faces.layers.float.get(name)
    return lay if lay is not None else bm.faces.layers.float.new(name)


def bm_vert_attr(bm, name):
    lay = bm.verts.layers.float.get(name)
    return lay if lay is not None else bm.verts.layers.float.new(name)


# ====================================================================== 材质


class PMat(K.Mat):
    """单个 Principled BSDF 的材质。co 是程序纹理用的坐标（默认物体坐标，风火轮用周期坐标）。"""

    def __init__(self, name, co=None, w=None):
        super().__init__(name)
        self.P = self.n("ShaderNodeBsdfPrincipled")
        self.l(self.P.outputs[0], self.out.inputs["Surface"])
        self.co = co(self) if callable(co) else (co if co is not None else self.coord("Object"))
        self.w = w(self) if callable(w) else w
        self.m.use_backface_culling = True  # glTF 单面
        self._bump = None

    # ---- 取值
    def uv(self, name="UVMap"):
        nd = self.n("ShaderNodeUVMap")
        nd.uv_map = name
        return nd.outputs["UV"]

    def attr(self, name, out="Fac"):
        nd = self.n("ShaderNodeAttribute")
        nd.attribute_type = "GEOMETRY"
        nd.attribute_name = name
        return nd.outputs[out]

    def sep(self, vec):
        s = self.n("ShaderNodeSeparateXYZ")
        self.l(vec, s.inputs[0])
        return s.outputs["X"], s.outputs["Y"], s.outputs["Z"]

    def comb(self, x, y, z):
        c = self.n("ShaderNodeCombineXYZ")
        for sock, v in zip(c.inputs, (x, y, z)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            else:
                self.l(v, sock)
        return c.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        nd = self.n("ShaderNodeVectorMath", _operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, tuple):
                nd.inputs[i].default_value = v
            else:
                self.l(v, nd.inputs[i])
        if scale is not None:
            nd.inputs["Scale"].default_value = scale
        return nd.outputs[1] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else nd.outputs[0]

    def vscale(self, vec, f):
        """向量 × 标量插口。"""
        nd = self.n("ShaderNodeVectorMath", _operation="SCALE")
        self.l(vec, nd.inputs[0])
        if isinstance(f, (int, float)):
            nd.inputs["Scale"].default_value = f
        else:
            self.l(f, nd.inputs["Scale"])
        return nd.outputs[0]

    def nz(self, scale, detail=4.0, rough=0.55, stretch=(1.0, 1.0, 1.0), seed=0.0, co=None, dist=0.0):
        """程序噪声 Fac（0..1，均值约 0.5）。stretch 拉伸坐标（大于 1 的轴上噪声更密）。有周期坐标的 W 时用 4D。"""
        v = co if co is not None else self.co
        if stretch != (1.0, 1.0, 1.0):
            v = self.vmath("MULTIPLY", v, tuple(stretch))
        if seed:
            v = self.vmath("ADD", v, (seed * 7.31, seed * 3.17, seed * 5.53))
        if self.w is not None and co is None:
            nd = self.n("ShaderNodeTexNoise", _noise_dimensions="4D")
            self.l(v, nd.inputs["Vector"])
            self.l(self.math("ADD", self.w, seed * 1.37), nd.inputs["W"])
        else:
            nd = self.n("ShaderNodeTexNoise", _noise_dimensions="3D")
            self.l(v, nd.inputs["Vector"])
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = dist
        return nd.outputs["Fac"]

    def voronoi(self, scale, feature="F1", out="Distance", co=None, rand=1.0):
        nd = self.n("ShaderNodeTexVoronoi", _voronoi_dimensions="3D", _feature=feature)
        self.l(co if co is not None else self.co, nd.inputs["Vector"])
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Randomness"].default_value = rand
        return nd.outputs[out]

    def image(self, img, vec, extension="REPEAT", out="Color", interp="Cubic"):
        t = self.n("ShaderNodeTexImage", _interpolation=interp, _extension=extension)
        t.image = img
        self.l(vec, t.inputs["Vector"])
        return t.outputs[out]

    def cavity(self, dist=0.004, samples=16):
        """凹处（0..1，越凹越大）：本物体内的局部 AO。"""
        ao = self.n("ShaderNodeAmbientOcclusion", Distance=dist, _samples=samples, _only_local=True)
        return self.math("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)

    def edge(self, radius=0.0006, lo=0.0, hi=0.10, samples=16):
        """棱边（0..1）：Bevel 节点的圆角法线和原法线差得越多越接近 1。凸棱、凹棱都算，凹的再乘 1 - cavity 分开。"""
        bv = self.n("ShaderNodeBevel", Radius=radius, _samples=samples)
        g = self.n("ShaderNodeNewGeometry")
        d = self.vmath("DOT_PRODUCT", bv.outputs["Normal"], g.outputs["Normal"])
        return self.maprange(self.math("SUBTRACT", 1.0, d), lo, hi)

    def bevel_normal(self, radius=0.0005, samples=16):
        """圆角法线：硬边在法线贴图里倒一点圆，边上接住高光。"""
        bv = self.n("ShaderNodeBevel", Radius=radius, _samples=samples)
        return bv.outputs["Normal"]

    def stroke(self, col, amount=0.07, scale=60.0, stretch=(1.0, 1.0, 1.0), warm=0.03, seed=0.0):
        """手绘笔触：低频、拉长的两层噪声把底色提亮压暗一点，亮处偏暖、暗处偏冷。col 是颜色插口或元组。"""
        n1 = self.nz(scale, detail=2.0, rough=0.45, stretch=stretch, seed=seed + 11.0)
        n2 = self.nz(scale * 2.7, detail=1.0, rough=0.4, stretch=stretch, seed=seed + 23.0)
        v = self.math("ADD", self.math("MULTIPLY", self.maprange(n1, 0.3, 0.7, -1.0, 1.0), 0.7),
                      self.math("MULTIPLY", self.maprange(n2, 0.3, 0.7, -1.0, 1.0), 0.3))
        k = self.math("ADD", 1.0, self.math("MULTIPLY", v, amount))
        tint = self.comb(self.math("ADD", k, self.math("MULTIPLY", v, warm)), k,
                         self.math("SUBTRACT", k, self.math("MULTIPLY", v, warm)))
        mul = self.n("ShaderNodeMix", _data_type="RGBA", _blend_type="MULTIPLY", _clamp_result=True)
        ins = {s.identifier: s for s in mul.inputs}
        ins["Factor_Float"].default_value = 1.0
        if isinstance(col, tuple):
            ins["A_Color"].default_value = col if len(col) == 4 else (*col, 1.0)
        else:
            self.l(col, ins["A_Color"])
        self.l(tint, ins["B_Color"])
        return next(s for s in mul.outputs if s.identifier == "Result_Color")

    def bump_add(self, height, strength=0.3, distance=0.0005):
        """叠一层凹凸（链式：上一层的法线作为这一层的输入）。"""
        nd = self.n("ShaderNodeBump", Strength=strength, Distance=distance)
        self.l(height, nd.inputs["Height"])
        if self._bump is not None:
            self.l(self._bump, nd.inputs["Normal"])
        self._bump = nd.outputs["Normal"]
        return self._bump

    def normal_base(self, sock):
        """凹凸链的起点（比如圆角法线）。"""
        self._bump = sock

    def set(self, base=None, rough=None, metal=None, emit=None, emit_strength=None, alpha=None, coat=None):
        P = self.P
        for key, v in (("Base Color", base), ("Roughness", rough), ("Metallic", metal), ("Emission Color", emit),
                       ("Emission Strength", emit_strength), ("Alpha", alpha), ("Coat Weight", coat)):
            if v is None:
                continue
            sock = P.inputs[key]
            if isinstance(v, (int, float)):
                sock.default_value = v
            elif isinstance(v, tuple):
                sock.default_value = v if len(v) == 4 else (*v, 1.0)
            else:
                self.l(v, sock)
        if self._bump is not None:
            self.l(self._bump, P.inputs["Normal"])
        return self.m


def lerp_col(M, fac, a, b):
    return M.mix(fac, a, b)


def periodic_coords(n):
    """风火轮用的周期坐标（轮轴是物体的 Y 轴）：r、θ 映射成 (r/n·cos nθ, y, r/n·sin nθ)，W = r。
    任何 3D/4D 噪声在 θ 上都以 2π/n 为周期，沿切向、轴向等距，径向的变化由 W 给出。
    返回 (co 工厂, w 工厂)，给 PMat(co=..., w=...)。"""
    cache = {}

    def _base(M):
        key = id(M)
        if key not in cache:
            x, y, z = M.sep(M.coord("Object"))
            r = M.math("SQRT", M.math("ADD", M.math("MULTIPLY", x, x), M.math("MULTIPLY", z, z)))
            th = M.math("MULTIPLY", M.math("ARCTAN2", z, x), float(n))
            rho = M.math("DIVIDE", r, float(n))
            co = M.comb(M.math("MULTIPLY", rho, M.math("COSINE", th)), y, M.math("MULTIPLY", rho, M.math("SINE", th)))
            cache[key] = (co, r)
        return cache[key]

    return (lambda M: _base(M)[0]), (lambda M: _base(M)[1])


def polar(M, n=1):
    """物体坐标 → (r, 角度比例 u = θ·n/2π 取小数, 轴向 y)。轮轴是 Y。"""
    x, y, z = M.sep(M.coord("Object"))
    r = M.math("SQRT", M.math("ADD", M.math("MULTIPLY", x, x), M.math("MULTIPLY", z, z)))
    u = M.math("FRACT", M.math("DIVIDE", M.math("MULTIPLY", M.math("ARCTAN2", z, x), float(n)), 2 * math.pi))
    return r, u, y


# ====================================================================== 贴图（numpy → PNG → Blender 图像）


def np_image(name, arr, alpha=None, colorspace="Non-Color"):
    """numpy (h, w[, 3]) 0..1（第 0 行在上）→ PNG（灰度 16 位）→ Blender 图像。"""
    bpy = _bpy()
    from PIL import Image  # noqa: PLC0415

    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"src_{name}.png"
    a = np.clip(arr, 0, 1)
    if a.ndim == 2:
        Image.fromarray(np.round(a * 65535).astype(np.uint16)).save(path)
    else:
        rgb = np.round(a * 255).astype(np.uint8)
        if alpha is not None:
            rgb = np.dstack([rgb, np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8)])
        Image.fromarray(rgb).save(path)
    img = bpy.data.images.load(str(path), check_existing=False)
    img.colorspace_settings.name = colorspace
    return img


def blur(a, sigma, wrap=False):
    return K.vfx().fft_blur(a, sigma, wrap=wrap)


def smooth_noise(rng, shape, sigma, wrap=True):
    return K.vfx().noise(rng, shape, sigma)


def draw_lines(size, polylines, width, *, closed=False, supersample=2):
    """在 (h, w) 画布上画折线（坐标是像素，(x, y)），返回 0..1 的浮点遮罩。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    h, w = size
    s = supersample
    im = Image.new("L", (w * s, h * s), 0)
    dr = ImageDraw.Draw(im)
    for pl in polylines:
        pts = [(float(x) * s, float(y) * s) for x, y in pl]
        if closed:
            pts = pts + [pts[0]]
        wd = width(pl) if callable(width) else width
        dr.line(pts, fill=255, width=max(1, int(round(wd * s))), joint="curve")
        r = wd * s / 2
        for x, y in (pts[0], pts[-1]):
            dr.ellipse((x - r, y - r, x + r, y + r), fill=255)
    im = im.resize((w, h), Image.LANCZOS)
    return np.asarray(im, np.float64) / 255.0


def spiral(cx, cy, r0, r1, turns, a0=0.0, n=120, sign=1.0, squash=1.0):
    """阿基米德螺线（像素坐标），从外 r0 卷到里 r1。"""
    t = np.linspace(0, 1, n)
    a = a0 + sign * 2 * math.pi * turns * t
    r = r0 + (r1 - r0) * t
    return list(zip(cx + r * np.cos(a), cy + r * np.sin(a) * squash))


def height_from_mask(mask, round_px=1.5):
    """线条遮罩 → 圆润的浮雕高度（模糊后取平方根，线心最高）。"""
    hgt = blur(mask, round_px)
    return np.sqrt(np.clip(hgt / (hgt.max() + 1e-9), 0, 1))


# ====================================================================== 几何


def slab_strip(pts, ups, width_fn, thick, *, segs_w=8, edge_l=None, edge_r=None, end_jag=None, lift=None, uv_len=None):
    """有厚度的纸条 / 绸带（bmesh build）。沿 pts 走，横向沿 ups（每点一个方向），厚度方向 = 切线 × 横向。
    - width_fn(t) → 宽度（米）；edge_l(t)、edge_r(t) → 两条长边的毛边（米，正 = 往外长）；
    - end_jag(s) → 末端（t = 1）横向第 s 处往回缩的长度（米，撕口）；
    - lift(t, s) → 整条沿厚度方向的起伏（米：折痕的棱、中线对折的 V），正反两面一起动；
    - UV：u = 弧长（米；给了 uv_len 就按比例缩到 0..uv_len），v = 0..1 横跨。
    面属性 side：0 正面（厚度方向的正侧）、1 背面、2 侧边；点属性 edge_d：到最近的边或撕口的距离（米）。"""
    from mathutils import Vector  # noqa: PLC0415

    P, T, N, Bn = K.frames_along(pts)
    n = len(P)
    lens = [0.0]
    for i in range(1, n):
        lens.append(lens[-1] + (P[i] - P[i - 1]).length)
    total = lens[-1]

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        side = bm_face_attr(bm, "side")
        ed = bm_vert_attr(bm, "edge_d")
        F, B, UV = [], [], []
        for i in range(n):
            t = i / (n - 1)
            sd = Vector(ups[i]).normalized()
            sd = (sd - T[i] * sd.dot(T[i])).normalized()
            nrm = T[i].cross(sd).normalized()
            wdt = width_fn(t)
            el = edge_l(t) if edge_l else 0.0
            er = edge_r(t) if edge_r else 0.0
            rf, rb, ru = [], [], []
            for j in range(segs_w + 1):
                s = j / segs_w
                off = -wdt / 2 - el + (wdt + el + er) * s
                back = end_jag(s) if (end_jag and i == n - 1) else 0.0
                base = P[i] + sd * off - T[i] * back
                d = lift(t, s) if lift else 0.0
                vf = bm.verts.new(base + nrm * (thick / 2 + d))
                vb = bm.verts.new(base + nrm * (-thick / 2 + d))
                d_edge = min(off + wdt / 2 + el, wdt / 2 + er - off)
                d_end = total - lens[i] - back
                vf[ed] = vb[ed] = max(0.0, min(d_edge, d_end))
                rf.append(vf)
                rb.append(vb)
                u = lens[i] - back
                ru.append((u if uv_len is None else u / total * uv_len, s))
            F.append(rf)
            B.append(rb)
            UV.append(ru)

        def face(vs, uv4, sv):
            try:
                f = bm.faces.new(vs)
            except ValueError:
                return None
            for lp, uv in zip(f.loops, uv4):
                lp[uvl].uv = uv
            f[side] = sv
            return f

        for i in range(n - 1):
            for j in range(segs_w):
                uv4 = (UV[i][j], UV[i + 1][j], UV[i + 1][j + 1], UV[i][j + 1])
                face((F[i][j], F[i + 1][j], F[i + 1][j + 1], F[i][j + 1]), uv4, 0.0)
                face((B[i][j + 1], B[i + 1][j + 1], B[i + 1][j], B[i][j]), uv4[::-1], 1.0)
            for j in (0, segs_w):
                u0, u1 = UV[i][j][0], UV[i + 1][j][0]
                face((F[i][j], B[i][j], B[i + 1][j], F[i + 1][j]), ((u0, 0.0), (u0, 0.02), (u1, 0.02), (u1, 0.0)), 2.0)
        for i in (0, n - 1):
            for j in range(segs_w):
                u = UV[i][j][0]
                face((F[i][j], F[i][j + 1], B[i][j + 1], B[i][j]), ((u, 0.0), (u, 0.0), (u, 0.02), (u, 0.02)), 2.0)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def torus_knot(p=2, q=3, R=0.004, r=0.0018, tube=0.0011, n=220, sides=8):
    """环面纽结（中国结的小结）：p、q 互质。返回 tube_uv 的 build。"""
    pts = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        rr = R + r * math.cos(q * t)
        pts.append((rr * math.cos(p * t), rr * math.sin(p * t), r * math.sin(q * t) * 1.3))
    return K.tube_uv(pts, tube, sides=sides, caps=False)


def adaptive_samples(x0, x1, base, features=(), fine=0.0006, reach=0.004):
    """沿一条轴取样：平时间距 base，在 features（位置列表）附近 ±reach 内加密到 fine。返回从小到大的数组。"""
    xs = list(np.arange(x0, x1, base)) + [x1]
    for f in features:
        xs += list(np.arange(max(x0, f - reach), min(x1, f + reach), fine))
    xs = np.unique(np.round(np.asarray(xs), 7))
    return xs[(xs >= x0) & (xs <= x1)]


def mark_sharp_edges(me, edge_pred):
    """按谓词（两个端点坐标 → bool）把边标成硬边（导出时法线在这里断开）。"""
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    ev = np.zeros(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    flags = np.array([bool(edge_pred(co[a], co[b], a, b)) for a, b in ev])
    if "sharp_edge" in me.attributes:
        me.attributes.remove(me.attributes["sharp_edge"])
    at = me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    at.data.foreach_set("value", flags)
    return int(flags.sum())


def tube_bake_uv(ob, radius, seg_len=0.20):
    """管子（tube_uv 建的绳、丝、结）的烘焙 UV：沿管的弧长（米）× 绕一圈的周长（米），每根管、每 seg_len 一段各成一个岛，
    只在绕圈的接缝和分段处断开（Smart UV 会把六棱的管拆成一面一个岛，顶点翻好几倍）。零件标成 premade，排 UV 时只参与排。"""
    import bmesh  # noqa: PLC0415

    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    src = bm.loops.layers.uv["UVMap"]
    dst = bm.loops.layers.uv.get("BakeUV") or bm.loops.layers.uv.new("BakeUV")
    circ = 2 * math.pi * radius
    seen = set()
    island = 0
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        comp, stack = [], [f0]
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        segs = {}
        for f in comp:
            uc = sum(lp[src].uv.x for lp in f.loops) / len(f.loops)
            segs.setdefault(int(uc // seg_len), []).append(f)
        for k, fs in sorted(segs.items()):
            for f in fs:
                for lp in f.loops:
                    u, v = lp[src].uv
                    lp[dst].uv = (u - k * seg_len + 20.0, v * circ + island * circ * 1.4)  # 挪到 0..1 外，不和 Smart UV 的岛重叠
            island += 1
    bm.to_mesh(me)
    bm.free()
    ob["inspect_uv"] = "premade"
    return ob


# ====================================================================== 合并、UV（export.py 和建模都用）


def select_only(objs, active=None):
    bpy = _bpy()
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


class plain_materials:
    """UV 操作（smart_project、pack_islands）会按材质里的图像贴图的宽高比把 UV 压扁：期间把材质槽临时换成一个没有贴图的。
    用法：with plain_materials(objs): ...（出来时换回去，面的材质编号不动）。"""

    def __init__(self, objs):
        self.objs = objs
        self.saved = []

    def __enter__(self):
        bpy = _bpy()
        self.tmp = bpy.data.materials.get("_uv_plain") or bpy.data.materials.new("_uv_plain")
        for o in self.objs:
            mats = list(o.data.materials)
            self.saved.append((o, mats))
            for i in range(len(mats)):
                o.data.materials[i] = self.tmp
        return self

    def __exit__(self, *exc):
        for o, mats in self.saved:
            for i, m in enumerate(mats):
                o.data.materials[i] = m
        return False


def _edit_select(objs, pred):
    """进编辑模式，按面谓词 pred(obj, 面属性 premade) 选面（bmesh 改选择，最稳）。"""
    bpy = _bpy()
    import bmesh  # noqa: PLC0415

    ts = bpy.context.scene.tool_settings
    ts.mesh_select_mode = (False, False, True)
    ts.use_uv_select_sync = True
    select_only(objs)
    bpy.ops.object.mode_set(mode="EDIT")
    for o in objs:
        bm = bmesh.from_edit_mesh(o.data)
        lay = bm.faces.layers.float.get("premade")
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = bool(pred(o, f[lay] if lay is not None else 0.0))
        bm.select_flush_mode()
        bmesh.update_edit_mesh(o.data)


def _islands(bm, uvl):
    """UV 岛：在边上 UV 一致的相连面。返回 [面列表]。"""
    bm.faces.ensure_lookup_table()
    parent = list(range(len(bm.faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in bm.edges:
        lf = e.link_loops
        if len(lf) != 2:
            continue
        l1, l2 = lf
        a1, b1 = l1[uvl].uv, l1.link_loop_next[uvl].uv
        a2, b2 = l2.link_loop_next[uvl].uv, l2[uvl].uv
        if (a1 - a2).length < 1e-6 and (b1 - b2).length < 1e-6:
            ra, rb = find(l1.face.index), find(l2.face.index)
            if ra != rb:
                parent[ra] = rb
    isl = {}
    for f in bm.faces:
        isl.setdefault(find(f.index), []).append(f)
    return list(isl.values())


_SLOT = [100.0]  # 全局的“停车位”：每次调用接着往后排，分几次展的岛也不会叠在一起
_FAR = [0.0]


def uv_islands_rescale(objs, fill=0.62, max_frac=0.34, skip_premade=False, split_len=None):
    """每个 UV 岛按三维面积统一纹素密度，再乘面属性 dens；太长的岛（排好后会超过图宽的 max_frac）沿长边切成几段，
    不然一根剑身那样的长条会把整张图的密度压下来。fill 是估计的排布利用率。"""
    import bmesh  # noqa: PLC0415

    bms = []
    a_tot = 0.0
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        dl = bm.faces.layers.float.get("dens")
        for f in bm.faces:
            a_tot += f.calc_area() * (f[dl] if dl is not None else 1.0) ** 2
        bms.append(bm)
    lmax = split_len if split_len else max_frac * math.sqrt(a_tot / fill)
    n_split = 0
    far = _FAR
    slot = _SLOT
    for o, bm in zip(objs, bms):
        uvl = bm.loops.layers.uv["BakeUV"]
        dl = bm.faces.layers.float.get("dens")
        pl = bm.faces.layers.float.get("premade")
        for fs in _islands(bm, uvl):
            premade = pl is not None and fs[0][pl] > 0.5
            if not (premade and skip_premade):
                a3 = sum(f.calc_area() for f in fs)
                auv = 0.0
                for f in fs:
                    uv = [lp[uvl].uv.copy() for lp in f.loops]
                    for i in range(1, len(uv) - 1):
                        auv += abs((uv[i] - uv[0]).cross(uv[i + 1] - uv[0])) / 2
                if auv > 1e-14 and a3 > 1e-14:
                    k = math.sqrt(a3 / auv) * (fs[0][dl] if dl is not None else 1.0)
                    for f in fs:
                        for lp in f.loops:
                            lp[uvl].uv = lp[uvl].uv * k
            pts = np.array([tuple(lp[uvl].uv) for f in fs for lp in f.loops])
            lo, hi = pts.min(0), pts.max(0)
            ext = hi - lo
            # 每个岛挪到自己的一格（x 方向一字排开，离 0..1 很远），缩放后互相不会压在一起；pack 再重排
            for f in fs:
                for lp in f.loops:
                    u = lp[uvl].uv.copy()
                    lp[uvl].uv = (u.x - lo[0] + slot[0], u.y - lo[1] - 600.0)
            lo = np.array([slot[0], -600.0])
            slot[0] += float(ext[0]) + 0.01
            ax = int(ext[1] > ext[0])
            E = float(ext[ax])
            if E <= lmax:
                continue
            n = int(math.ceil(E / lmax))
            step = E / n
            minor = float(ext[1 - ax])
            # 切下来的段挪到远处（各占一格，互不重叠；pack 会重新排），免得和别的岛重叠被 merge_overlap 并成一个
            for f in fs:
                c = sum(lp[uvl].uv[ax] for lp in f.loops) / len(f.loops)
                kk = min(int((c - lo[ax]) / step), n - 1)
                if kk == 0:
                    continue
                for lp in f.loops:
                    u = lp[uvl].uv.copy()
                    u[0 if ax == 0 else 1] = u[ax] - kk * step - lo[ax] + (40.0 if ax == 0 else -300.0)
                    u[1 - ax] = u[1 - ax] - lo[1 - ax] + far[0] + (kk - 1) * (minor * 1.3 + 1e-3) + (0.0 if ax == 0 else 200.0)
                    lp[uvl].uv = u
            far[0] += (n - 1) * (minor * 1.3 + 1e-3) + 1e-3
            n_split += n - 1
        bm.to_mesh(o.data)
        bm.free()
    print(f"[inspect]   UV：长岛切了 {n_split} 刀（单段最长 {lmax:.3f}）")




def join_objects(parts, name):
    """把零件合成一个网格物体（零件的变换写进顶点），三角化（烘焙和引擎用同一套三角形，切线才一致）。
    每个零件带上点属性 ol（描边倍数）、面属性 dens（贴图密度）、premade（已有烘焙 UV）；零件上已有的不覆盖。"""
    bpy = _bpy()
    import bmesh  # noqa: PLC0415

    for p in parts:
        me = p.data
        if "UVMap" not in me.uv_layers:
            me.uv_layers.new(name="UVMap")
        if "BakeUV" not in me.uv_layers:
            me.uv_layers.new(name="BakeUV")
        if "ol" not in me.attributes:
            set_attr(me, "ol", np.full(len(me.vertices), p.get("inspect_outline", 1.0)), "POINT")
        if "dens" not in me.attributes:
            set_attr(me, "dens", np.full(len(me.polygons), p.get("inspect_density", 1.0)), "FACE")
        if "premade" not in me.attributes:
            set_attr(me, "premade", np.full(len(me.polygons), 1.0 if p.get("inspect_uv") == "premade" else 0.0), "FACE")
    tgt = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    bpy.context.scene.collection.objects.link(tgt)
    tgt.data.uv_layers.new(name="UVMap")
    select_only(parts + [tgt], active=tgt)
    bpy.ops.object.join()
    me = tgt.data
    # 合并目标原来的空网格会留下一个空材质槽，烘焙时 Cycles 会因为它整个物体不烘：去掉空槽，面的材质编号跟着改
    mats = list(me.materials)
    if any(m is None for m in mats):
        keep = [m for m in mats if m is not None]
        remap = np.array([keep.index(m) if m is not None else 0 for m in mats], np.int64)
        mi = np.zeros(len(me.polygons), np.int64)
        me.polygons.foreach_get("material_index", mi)
        me.materials.clear()
        for m in keep:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", remap[mi])
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.to_mesh(me)
    bm.free()
    if "BakeUV" not in me.uv_layers:
        me.uv_layers.new(name="BakeUV")
    return tgt


def smart_unwrap_meters(ob, angle=58.0):
    """整个物体做 Smart UV（BakeUV 层，premade 的面不动），每个岛缩放到 1 UV = 1 米 × dens（不排、不切）。
    给要自己复制排布的件用（风火轮的一个扇区）。"""
    bpy = _bpy()
    me = ob.data
    me.uv_layers.active = me.uv_layers["BakeUV"]
    with plain_materials([ob]):
        _edit_select([ob], lambda o, pm: pm < 0.5)
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=0.0, area_weight=0.0, correct_aspect=False,
                                 scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    uv_islands_rescale([ob], max_frac=1e9)
