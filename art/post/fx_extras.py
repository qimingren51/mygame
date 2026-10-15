#!/usr/bin/env python3
"""提灯夜行 · 质感会话要的三样小素材（只出桌面版 2 倍；Pillow + numpy，不用 Blender）。

  art/out/assets@2x/ui_wash/     ink_wash（1024×320）、ink_wash_1（768×256）+ meta.json（name: ui → 帧名 ui/ink_wash）
                                 横着的一笔淡墨：题字（夜主名牌、结算标题）后面衬的底。干笔飞白、浓淡不匀、
                                 湿处往纸里洇一圈，四边都淡到全透明。白色，墨的浓淡在 alpha 里；游戏染色（墨色或纸色）、调不透明度。
  art/out/assets@2x/vfx_leaves/  bamboo_leaf_0..3（32×12）+ meta.json（name: vfx → 帧名 vfx/bamboo_leaf_N）
                                 打碎竹丛时飞出的竹叶粒子：披针形、微弯、一片撕断的；叶尖朝 +X，锚点居中；
                                 白色可染色，叶脉是 alpha 里浅一线。
  art/out/screens/scroll_roller.png + scroll_roller.json
                                 开场卷轴的轴：深色漆木轴杆 + 上下轴头，左边一条卷起的纸边。跟着展开的边走。
  art/out/review@2x/fx_extras_review.png   审图

都是直通（非预乘）alpha。固定随机种子，重复运行逐字节相同（约 10 秒）。笔刷、噪声、抖动等工具复用 vfx_textures.py（只 import）。

用法（在仓库根目录下）：
    art/.venv/bin/python art/post/fx_extras.py
    art/.venv/bin/python art/post/test_fx_extras.py
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 只有桌面版：先定密度，再导入 style / vfx_textures

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402

S = V.S
ART = HERE.parent
OUT = ART / "out"
WASH_DIR = OUT / "assets@2x" / "ui_wash"
LEAF_DIR = OUT / "assets@2x" / "vfx_leaves"
SCREENS = OUT / "screens"
REVIEW = OUT / "review@2x"
GENERATOR = "art/post/fx_extras.py"
PPU = 4  # 与 ui、vfx 图集一致（打包时密度要相同）

col, smoothstep = V.col, V.smoothstep
PAPER, PAPER_SH = col(S.PAPER), col(S.PAPER_SHADOW)
JIAO, NONG, ZHONG, DAN, QING = (col(S.INK[k]) for k in ("jiao", "nong", "zhong", "dan", "qing"))
ZHUSHA, ZHESHI, SHILV = col(S.ACCENT["zhusha"]), col(S.ACCENT["zheshi"]), col(S.ACCENT["shilv"])


def mixc(a, b, t):
    t = np.asarray(t, dtype=np.float64)
    if t.ndim:
        t = t[..., None]
    return np.asarray(a) * (1.0 - t) + np.asarray(b) * t


# ============================================================== 小工具


def n1d(rng, n: int, sigma: float) -> np.ndarray:
    """一维平滑噪声，标准差归一为 1。"""
    x = V.fft_blur(rng.standard_normal(n)[None, :], (sigma, 0.0))[0]
    return (x - x.mean()) / (x.std() + 1e-12)


def interp1(arr: np.ndarray, t: np.ndarray, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """按 t∈[lo, hi] 线性插值取一维数组。"""
    return np.interp(t, np.linspace(lo, hi, len(arr)), arr)


def bilinear(tex: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    """双线性采样，fi / fj 是行 / 列的浮点下标（越界夹到边上）。"""
    h, w = tex.shape
    fi = np.clip(fi, 0.0, h - 1.000001)
    fj = np.clip(fj, 0.0, w - 1.000001)
    i0, j0 = fi.astype(np.int64), fj.astype(np.int64)
    di, dj = fi - i0, fj - j0
    return (tex[i0, j0] * (1 - di) * (1 - dj) + tex[i0 + 1, j0] * di * (1 - dj)
            + tex[i0, j0 + 1] * (1 - di) * dj + tex[i0 + 1, j0 + 1] * di * dj)


def white_rgba(a: np.ndarray, rng) -> Image.Image:
    """白色、只有 alpha 有形状的贴图（tint: true）。alpha 用蓝噪声抖动量化，拉伸后不出色带。"""
    a8 = V.dither_alpha(np.clip(a, 0.0, 1.0), rng)
    a8[a < 0.5 / 255.0] = 0  # 真正空的地方保持 0（抖动不往透明处撒点）
    rgb = np.full(a8.shape + (3,), 255, np.uint8)
    return Image.fromarray(np.dstack([rgb, a8]), "RGBA")


def border_window(h: int, w: int, ss: int, margin: float) -> np.ndarray:
    """离四边 margin 像素内平滑降到 0：保证贴图边上一圈全透明。"""
    X, Y = V.grid(h, w, ss)
    d = np.minimum(np.minimum(X, w - X), np.minimum(Y, h - Y))
    return smoothstep(1.0, margin, d)


# ============================================================== 1. 淡墨刷底 ui/ink_wash

# 每张一笔：画布、起收笔位置、中线（左端 y、右端 y、中段拱起）、最大半宽、收笔变细、飞白程度、起笔圆钝、斜切、
# 收笔参差的长度（占笔长）、收笔处的墨量
WASHES = {
    "ink_wash": dict(seed=3101, w=1024, h=320, x0=64.0, x1=972.0, y0=170.0, y1=150.0, sag=14.0, hw=90.0,
                     taper=0.34, dry=0.66, head_r=84.0, slant=-0.1, tail=0.16, load_end=0.66),
    "ink_wash_1": dict(seed=3117, w=768, h=256, x0=50.0, x1=726.0, y0=134.0, y1=118.0, sag=10.0, hw=68.0,
                       taper=0.38, dry=0.72, head_r=64.0, slant=-0.12, tail=0.2, load_end=0.6),
}
WASH_ALPHA_HINT = 0.6  # 建议的整体不透明度（墨色衬亮字）；纸色衬墨字可到 0.85


def make_ink_wash(seed, w, h, x0, x1, y0, y1, sag, hw, taper, dry, head_r, slant, tail, load_end) -> tuple[Image.Image, np.ndarray]:
    """一笔横扫的淡墨。返回 (贴图, 未量化的 alpha)。

    坐标：u 沿笔 0..1（起笔在左），s 横向 -1..1（按该处半宽归一）。笔毛纹理在 (u, s) 里生成，
    所以飞白的丝顺着笔走；越往收笔、越靠两边越干。起笔饱墨、圆钝，水边积一点墨，湿处往纸里洇。"""
    rng = np.random.default_rng(seed)
    ss = 2
    X, Y = V.grid(h, w, ss)
    L = x1 - x0
    u = (X - x0) / L
    uc = np.clip(u, 0.0, 1.0)

    def bump(c, r):
        return np.exp(-(((uc - c) / r) ** 2))

    # 中线（左低右高、中段微拱、慢慢起伏）与半宽（起笔按下去鼓、中段略收、收笔变细）
    yc = y0 + (y1 - y0) * uc - sag * 4.0 * uc * (1.0 - uc) + 5.0 * interp1(n1d(rng, 256, 12.0), uc)
    hwv = (hw * (1.0 + 0.10 * bump(0.1, 0.09) - 0.06 * bump(0.5, 0.2)) * (1.0 - taper * smoothstep(0.58, 1.0, uc))
           * (1.0 + 0.06 * interp1(n1d(rng, 256, 10.0), uc)))
    s = (Y - yc) / hwv
    a_s = np.abs(s)

    # 两侧的边：慢的起伏 + 一点细碎（毛边主要靠下面的飞白出来）
    def edge_noise():
        return (0.05 * interp1(n1d(rng, 512, 20.0), uc) + 0.014 * interp1(n1d(rng, 2048, 8.0), uc)
                + 0.004 * interp1(n1d(rng, 4096, 1.5), uc))
    edge = np.where(s < 0, 1.0 + edge_noise(), 1.0 + edge_noise())
    soft = 1.0 / hwv
    side = smoothstep(edge + soft, edge - soft, a_s)

    # 起笔：圆钝、略斜（逆锋落笔）
    head_j = interp1(n1d(rng, 256, 9.0), np.clip(s, -1.5, 1.5), -1.5, 1.5)
    hx = x0 + head_r * (1.0 - np.sqrt(np.clip(1.0 - np.minimum(a_s, 1.0) ** 2, 0.0, 1.0))) + slant * s * hw + 2.5 * head_j
    head = smoothstep(hx - 1.2, hx + 1.2, X)

    # 笔毛纹理（在 u、s 平面里）：细丝 + 成簇的粗丝，按名次归一到 0..1；另一张是笔毛间的浓淡
    NT, NS = 1400, 520
    fi = (np.clip(s, -1.4, 1.4) + 1.4) / 2.8 * (NS - 1)
    fj = (np.clip(u, -0.05, 1.05) + 0.05) / 1.1 * (NT - 1)
    fine = V.fft_blur(rng.standard_normal((NS, NT)), (70.0, 1.5))
    clump = V.fft_blur(rng.standard_normal((NS, NT)), (240.0, 9.0))
    B = bilinear(V.rank01(0.62 * fine / fine.std() + 0.38 * clump / clump.std()), fi, fj)
    T = bilinear(V.rank01(V.fft_blur(rng.standard_normal((NS, NT)), (120.0, 12.0))), fi, fj)

    # 收笔：每根笔毛停在不同的地方（中间的长、两边的短），拖出参差的丝
    ends = V.rank01(V.fft_blur(rng.standard_normal((NS, 1)), (0.0, 2.0)))[:, 0]
    endu = 1.0 - tail * (0.5 * np.minimum(a_s, 1.3) ** 1.6 + 0.5 * interp1(ends, np.clip(s, -1.4, 1.4), -1.4, 1.4))
    tail_f = smoothstep(endu + 0.004, endu - 0.03, u)

    # 飞白：越往收笔越干，边上先干；笔毛纹理低于“干度”的地方露白
    d = (dry * smoothstep(0.5, 1.0, u) ** 1.3
         + 0.34 * smoothstep(0.76, 1.1, a_s) * (0.1 + 0.9 * smoothstep(0.3, 0.9, u))
         + 0.03 * smoothstep(0.25, 0.45, u))
    ink = smoothstep(d - 0.035, d + 0.035, B)

    # 墨量：起笔饱、往后渐淡；笔毛间一点浓淡；整片再有慢的、云一样的不匀（湿墨里的深浅）
    load = 1.0 - (1.0 - load_end) * smoothstep(0.15, 1.0, u)
    lo = V.fft_blur(rng.standard_normal(X.shape), 22.0 * ss)
    mid = V.fft_blur(rng.standard_normal(X.shape), 6.0 * ss)
    uneven = 1.0 + 0.11 * lo / (lo.std() + 1e-12) + 0.025 * mid / (mid.std() + 1e-12)
    dens = (0.86 + 0.14 * T) * np.clip(uneven, 0.7, 1.25)
    shape = side * head * tail_f
    core = shape * ink * load * dens

    # 湿处的水边积墨（水干时墨往边上走）
    wet = 1.0 - smoothstep(0.12, 0.6, u)
    dist_px = np.maximum(edge - a_s, 0.0) * hwv
    core = core + 0.10 * wet * shape * np.exp(-((dist_px / 4.0) ** 2))

    # 洇：湿墨顺着纸纤维往外渗（只在笔外看得到），起笔一带再晕开一层更淡的水痕
    fib = V.rank01(sum(V.fft_blur(rng.standard_normal(X.shape), (7.0 * ss, 0.6 * ss), angle=a) for a in (0.3, 1.4, 2.4)))
    halo = V.fft_blur(core * (0.3 + 0.7 * wet), 4.0 * ss) * (0.4 + 0.75 * fib)
    tide = V.fft_blur(core * wet, 14.0 * ss)
    tide = smoothstep(0.08, 0.35, tide + 0.06 * lo / (lo.std() + 1e-12)) * 0.12 * (0.6 + 0.8 * fib)
    a = 1.0 - (1.0 - np.clip(core, 0, 1)) * (1.0 - 0.5 * halo) * (1.0 - tide)
    a = np.clip(a, 0.0, 1.0) * border_window(h, w, ss, 18.0)
    a = V.downsample(a, ss)
    return white_rgba(a, rng), a


# ============================================================== 2. 竹叶粒子 vfx/bamboo_leaf_N

LEAF_W, LEAF_H = 32, 12
# 长、最宽、弯（正值往下拱）、叶尖下垂、翻面（一半淡）、撕断处（沿叶长的比例；None 是整叶）
LEAVES = [
    dict(length=28.5, width=6.2, bend=0.8, droop=0.7, under=0.0, tear=None, seed=41),  # 整叶，微弯
    dict(length=27.5, width=5.4, bend=-1.4, droop=-0.9, under=0.0, tear=None, seed=42),  # 窄长，反向弯
    dict(length=24.0, width=6.8, bend=1.2, droop=1.0, under=0.2, tear=None, seed=43),  # 短宽，翻过来一半淡
    dict(length=29.0, width=6.4, bend=0.5, droop=0.4, under=0.0, tear=0.55, seed=44),  # 撕断的半片
]


def make_leaf(length, width, bend, droop, under, tear, seed) -> tuple[Image.Image, np.ndarray]:
    """一片竹叶：叶柄端圆钝、最宽处靠后三成、长长地收成尖；中脉是 alpha 里浅一线。叶尖朝 +X，叶片在画布里居中。"""
    rng = np.random.default_rng(seed)
    ss = 8
    X, Y = V.grid(LEAF_H, LEAF_W, ss)
    keep = length * (tear if tear else 1.0) + 1.2  # 留下的长度（含叶柄）
    xb = LEAF_W / 2 - keep / 2 + 1.2  # 叶身起点（左边留叶柄）
    sx = (X - xb) / length  # 沿叶 0..1
    sc = np.clip(sx, 0.0, 1.0)
    prof = 0.5 * width * np.sin(np.pi * sc**0.55) ** 0.8 * (1.0 - 0.3 * sc)
    yc = LEAF_H / 2 + bend * (4.0 * (sc - 0.5) ** 2 - 0.45) + droop * (sc**3 - 0.3)
    perp = Y - yc
    blade = smoothstep(prof + 0.12, prof - 0.12, np.abs(perp)) * (sx >= 0) * (sx <= 1)
    # 叶柄：一小截
    stalk = smoothstep(0.5, 0.28, np.abs(perp)) * smoothstep(-1.3 / length, -0.9 / length, sx) * (sx < 0.02)
    cover = np.maximum(blade, stalk)
    if tear:
        # 撕口：斜着的一道锯齿，靠下的一边撕得更深
        yy = np.linspace(0, LEAF_H, 9)
        jag = xb + tear * length + 0.45 * (yy - LEAF_H / 2) + rng.uniform(-1.2, 1.2, len(yy)) * np.array([0, 1, 1, 1, 1, 1, 1, 1, 0])
        cut = np.interp(Y, yy, jag)
        cover = cover * smoothstep(cut + 0.15, cut - 0.15, X)
    # 叶面浓淡：叶柄端略浓、叶尖略淡；翻面的一半更淡；中脉浅一线（往叶尖渐隐）
    mot = V.fft_blur(rng.standard_normal(X.shape), 3.0 * ss)
    dens = 0.94 - 0.12 * sc + 0.03 * mot / (mot.std() + 1e-12)
    dens = dens - under * (perp < 0)
    rib = 0.36 * np.exp(-((perp / 0.4) ** 2)) * smoothstep(0.0, 0.08, sx) * smoothstep(0.95, 0.6, sx)
    a = cover * np.clip(dens - rib * blade, 0.0, 1.0)
    a = V.downsample(a, ss)
    a[0, :] = a[-1, :] = 0.0
    a[:, 0] = a[:, -1] = 0.0
    a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)  # 小图不抖动：边缘干净
    rgb = np.full(a8.shape + (3,), 255, np.uint8)
    return Image.fromarray(np.dstack([rgb, a8]), "RGBA"), a


# ============================================================== 3. 卷轴的轴 screens/scroll_roller.png

SCROLL_H = 800  # 卷轴画的高
ROLL_EXT = 16  # 轴头伸出卷轴上下沿的像素
ROLL_W, ROLL_H = 60, SCROLL_H + 2 * ROLL_EXT
PAPER_EDGE_X = 10  # 卷轴画裁到这一列：把它对准展开到的位置。左边 0..10 是压在画上的半透明卷曲阴影
ROD_CX, ROD_R = 35.0, 12.0  # 轴杆中心与半径（杆在 23..47）
KNOB_R = 18.0  # 轴头半宽（17..53）
LACQUER = mixc(JIAO, ZHUSHA, 0.11)  # 黑里透红的漆
LAC_HI = mixc(mixc(LACQUER, ZHESHI, 0.55), PAPER, 0.42)  # 漆面的高光
BONE = mixc(PAPER, QING, 0.3)  # 轴头里侧的一道骨圈
ROLL_PAPER = mixc(PAPER_SH, ZHONG, 0.22)  # 卷起来的纸（比画上的纸暗一点，夜里也不刺眼）


def make_roller() -> Image.Image:
    """深色漆木轴：轴杆在前，上下各一个车出来的轴头（比杆宽、端头圆），里侧一道骨圈；
    轴杆左边一条卷起的纸（亮的卷脊、往轴后转过去变暗、几道层叠的纸边），最左边一抹淡影压在画上。"""
    rng = np.random.default_rng(2207)
    ss = 4
    h, w = ROLL_H, ROLL_W
    X, Y = V.grid(h, w, ss)
    lay = V.Layer(*X.shape)
    py0, py1 = ROLL_EXT, ROLL_EXT + SCROLL_H  # 纸的上下沿
    in_paper_y = ((Y >= py0) & (Y < py1)).astype(np.float64)  # 和卷轴画的上下沿逐像素对齐
    grain = V.fft_blur(rng.standard_normal(X.shape), (0.8 * ss, 50.0 * ss))  # 竖向长的纹理（木纹、纸纹）
    grain = grain / (grain.std() + 1e-12)
    ys = np.linspace(0, h, 600)

    def along_y(sigma):
        """沿 y 变化的一维噪声，铺成整张（干笔的断续）。"""
        return np.interp(Y, ys, n1d(rng, 600, sigma))

    # 压在画上的卷曲阴影：纸开始翘起，0..PAPER_EDGE_X 由 0 渐到约 0.16
    t_sh = np.clip(X / PAPER_EDGE_X, 0.0, 1.0)
    lay.over(JIAO, 0.16 * t_sh**2.2 * in_paper_y * (X < PAPER_EDGE_X + 1))

    # 卷起的纸：PAPER_EDGE_X 到轴杆左缘看得见，再往右压在轴杆后面
    rod_l = ROD_CX - ROD_R
    t = np.clip((X - PAPER_EDGE_X) / (rod_l - PAPER_EDGE_X), 0.0, 1.2)
    shade = 0.9 + 0.2 * np.exp(-(((t - 0.22) / 0.13) ** 2)) - 0.55 * smoothstep(0.3, 1.0, t) ** 1.1
    shade = shade * (1.0 + 0.03 * grain)
    paper_a = smoothstep(PAPER_EDGE_X - 2.0, PAPER_EDGE_X, X) * (X < ROD_CX) * in_paper_y  # paper_edge_x 这一列起全不透明
    lay.over(ROLL_PAPER * shade[..., None], paper_a)
    # 层叠的纸边：几道细的淡墨竖线，略抖、时断时续（越靠轴越密）
    for tx, aa in ((0.5, 0.22), (0.66, 0.3), (0.79, 0.32), (0.9, 0.28)):
        lx = PAPER_EDGE_X + tx * (rod_l - PAPER_EDGE_X) + 0.3 * along_y(3.0)
        brk = smoothstep(-0.8, 0.3, along_y(5.0))
        lay.over(mixc(ZHONG, JIAO, 0.4), aa * brk * smoothstep(0.6, 0.15, np.abs(X - lx)) * paper_a)
    # 纸的上下沿：一线淡墨；卷脊上一线亮
    for yy in (py0 + 0.6, py1 - 0.6):
        lay.over(ZHONG, 0.4 * smoothstep(0.9, 0.2, np.abs(Y - yy)) * smoothstep(PAPER_EDGE_X - 1, PAPER_EDGE_X + 3, X) * paper_a)
    crest = PAPER_EDGE_X + 0.22 * (rod_l - PAPER_EDGE_X)
    lay.over(mixc(PAPER, np.ones(3), 0.3), 0.35 * np.exp(-(((X - crest) / 0.9) ** 2)) * paper_a * smoothstep(-1.0, 0.5, along_y(8.0)))
    # 轴杆在纸上的接触影
    lay.over(JIAO, 0.4 * smoothstep(rod_l - 3.5, rod_l, X) * paper_a)

    def cylinder(nx, base, hi, spec_at=-0.45, spec_w=0.12, spec_k=0.8, brk=None):
        """圆柱的明暗：左上来光、两边压暗，一道断续的漆面高光（干笔）、右边一线反光。nx ∈ [-1, 1]。"""
        nz = np.sqrt(np.clip(1.0 - nx**2, 0.0, 1.0))
        lam = np.clip(0.4 + 0.6 * (-0.45 * nx + 0.89 * nz), 0.0, 1.0)
        rgb = base * (0.6 + 0.55 * lam[..., None]) * (1.0 + 0.06 * grain[..., None])
        rgb = mixc(rgb, JIAO, 0.5 * smoothstep(0.6, 1.0, np.abs(nx)))
        spec = spec_k * np.exp(-(((nx - spec_at) / spec_w) ** 2)) * (1.0 if brk is None else brk)
        rgb = mixc(rgb, hi, np.clip(spec, 0, 1))
        return mixc(rgb, hi, 0.2 * np.exp(-(((nx - 0.8) / 0.08) ** 2)))

    def outline(dd, width=0.75, k=0.9):
        """沿轮廓的焦墨线（dd 是有符号距离，里面为负），略带干笔。"""
        return k * (0.7 + 0.3 * smoothstep(-1.0, 1.0, grain)) * smoothstep(width + 0.5, width - 0.5, np.abs(dd + 0.5))

    def rrect(cx, cy, hx, hy, r):
        """圆角矩形的有符号距离。"""
        qx, qy = np.abs(X - cx) - (hx - r), np.abs(Y - cy) - (hy - r)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r

    # 轴杆：贯穿上下，两头伸进轴头
    rod_d = rrect(ROD_CX, h / 2, ROD_R, h / 2 - 2.0, 1.0)
    rod_a = smoothstep(0.5, -0.5, rod_d)
    hi_brk = smoothstep(-0.9, 0.6, along_y(4.0)) * (0.6 + 0.4 * smoothstep(-1, 1, grain))
    lay.over(cylinder((X - ROD_CX) / ROD_R, LACQUER, LAC_HI, brk=hi_brk), rod_a)
    for yy in rng.uniform(py0 + 80, py1 - 80, 4):  # 漆下隐约的竹木节
        lay.over(JIAO, 0.16 * np.exp(-(((Y - yy) / 1.3) ** 2)) * rod_a)
    lay.over(JIAO, outline(rod_d))

    # 轴头：车出来的圆柱头（端头倒圆、近端头一道细车纹），靠纸一侧一道骨圈
    kh = ROLL_EXT - 2.5  # 轴头高（留 2.5 像素给伸进纸里的杆）
    for top in (True, False):
        cy = 0.6 + kh / 2 if top else h - 0.6 - kh / 2
        kd = rrect(ROD_CX, cy, KNOB_R, kh / 2, 4.0)
        ka = smoothstep(0.5, -0.5, kd)
        knx = np.clip((X - ROD_CX) / KNOB_R, -1, 1)
        kbrk = 0.7 + 0.3 * smoothstep(-1, 1, grain)
        krgb = cylinder(knx, mixc(LACQUER, ZHESHI, 0.1), LAC_HI, spec_w=0.1, spec_k=0.85, brk=kbrk)
        outer = cy - kh / 2 if top else cy + kh / 2  # 端头那一侧
        inner = cy + kh / 2 if top else cy - kh / 2
        krgb = mixc(krgb, LAC_HI, 0.3 * np.exp(-(((Y - outer) / 1.6) ** 2)))  # 倒圆的端头受一点光
        lay.over(krgb, ka)
        groove = outer + (3.6 if top else -3.6)
        lay.over(JIAO, 0.55 * smoothstep(0.75, 0.2, np.abs(Y - groove)) * ka)
        ring_y = inner + (-1.3 if top else 1.3)
        ring = smoothstep(1.2, 0.6, np.abs(Y - ring_y)) * ka
        lay.over(cylinder(knx, BONE, mixc(BONE, np.ones(3), 0.6), spec_k=0.5), 0.95 * ring)
        lay.over(JIAO, outline(kd))

    out = lay.down(ss)
    rgb, a = out.straight()
    return V.to_rgba8(rgb, a)


def roller_info() -> dict:
    return {
        "file": "scroll_roller.png",
        "size": [ROLL_W, ROLL_H],
        "paper_edge_x": PAPER_EDGE_X,
        "paper_top_y": ROLL_EXT,
        "paper_height": SCROLL_H,
        "rod_center_x": ROD_CX,
        "rod_radius": ROD_R,
        "knob_radius": KNOB_R,
        "scroll_size": [2400, SCROLL_H],
        "blend": "normal",
        "tint": False,
        "generator": GENERATOR,
        "note": (
            "卷轴展开到 x（卷轴画的像素）时：画只画 [0, x)，轴的左上角放在 (x - paper_edge_x, -paper_top_y)，"
            "和卷轴画同样缩放、画在画上面。左边 0..paper_edge_x 是压在画上的半透明卷曲阴影；"
            "paper_edge_x 往右是卷起的纸（不透明）和轴杆；轴头上下各伸出卷轴 paper_top_y 像素。长夜版、天明版共用。"
        ),
    }


# ============================================================== 审图


def tint_over(bg: np.ndarray, img: Image.Image, x: int, y: int, color, opacity: float = 1.0, scale: int = 1) -> None:
    """白色贴图按游戏的方式染色后普通混合到 bg（0..1 RGB）上；scale>1 时最近邻放大。"""
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    a = np.asarray(img, np.float64) / 255.0
    rgb = a[..., :3] * np.asarray(color)
    al = a[..., 3:4] * opacity
    h, w = a.shape[:2]
    sub = bg[y : y + h, x : x + w]
    sub[:] = sub * (1 - al) + rgb * al


def draw_text(bg: np.ndarray, xy, text: str, fnt, color, anchor: str = "mm") -> None:
    im = Image.new("L", (bg.shape[1], bg.shape[0]), 0)
    ImageDraw.Draw(im).text(xy, text, font=fnt, fill=255, anchor=anchor)
    a = np.asarray(im, np.float64)[..., None] / 255.0
    bg[:] = bg * (1 - a) + np.asarray(color) * a


def fire_bg(h: int, w: int, rng) -> np.ndarray:
    """火光映照的夜：底下一团橙红、往上渐暗，带一点烟和火星。"""
    X, Y = V.grid(h, w, 1)
    n = V.fft_blur(rng.standard_normal((h, w)), 40.0)
    n = n / n.std()
    glow = np.exp(-(((X - 0.55 * w) / (0.6 * w)) ** 2 + ((Y - 1.15 * h) / (0.75 * h)) ** 2)) * (1 + 0.18 * n)
    base = col("#1C1012")
    fire = mixc(col("#B8401E"), col("#FF9A4D"), np.clip(glow, 0, 1))
    out = mixc(base, fire, np.clip(glow * 1.15, 0, 1))
    for _ in range(70):
        ex, ey = rng.uniform(0, w), rng.uniform(0.3 * h, h)
        r = rng.uniform(0.8, 2.2)
        d = np.hypot(X - ex, Y - ey)
        out = mixc(out, col("#FFD08A"), 0.8 * np.exp(-((d / r) ** 2)))
    return np.clip(out, 0, 1)


def paper_bg(h: int, w: int, rng) -> np.ndarray:
    n = V.fft_blur(rng.standard_normal((h, w)), 30.0)
    return mixc(PAPER, PAPER_SH, np.clip(0.35 + 0.25 * n / n.std(), 0, 1))


def make_review(washes: dict, leaves: list, roller: Image.Image, path: Path) -> None:
    """审图：淡墨染墨色衬亮字（火光底）、染纸色衬墨字（夜色底）；竹叶原大与 4 倍；轴在三个展开进度上，另附原大局部。"""
    from ui_fonts import font

    rng = np.random.default_rng(99)
    W = 1880
    night = col(S.NIGHT_AMBIENT)
    label_c = col("#CFC6B3")
    small = font("serif", 22)
    panels = []
    wash, w1 = washes["ink_wash"], washes["ink_wash_1"]
    xa, xb = 28, W - w1.width - 28

    # 1）墨色衬亮字：火光里的夜主名牌（左），短一号的衬结算标题（右）
    h1 = 400
    p = fire_bg(h1, W, rng)
    tint_over(p, wash, xa, 30, JIAO, 0.62)
    cx, cy = xa + wash.width // 2, 30 + wash.height // 2
    draw_text(p, (cx, cy - 96), "夜 主", font("serif", 34, weight=600), col(S.EYE["boss"]))
    draw_text(p, (cx, cy + 8), "九 尾", font("brush", 150), PAPER)
    draw_text(p, (cx, cy + 108), "击败它，迎来天明", font("serif", 26), mixc(PAPER, JIAO, 0.12))
    tint_over(p, w1, xb, 60, JIAO, 0.62)
    draw_text(p, (xb + w1.width // 2, 60 + w1.height // 2 + 2), "夜 尽", font("brush", 118), PAPER)
    draw_text(p, (16, h1 - 14), "ui/ink_wash（1024×320）、ui/ink_wash_1（768×256）：染墨 #17140F、不透明度 0.62，火光底 + 亮字", small, label_c, "ls")
    panels.append(p)

    # 2）纸色衬墨字：夜色底
    p = np.broadcast_to(night, (h1, W, 3)).copy()
    tint_over(p, wash, xa, 30, PAPER, 0.85)
    draw_text(p, (xa + wash.width // 2, 30 + wash.height // 2 + 4), "天 明", font("brush", 150), JIAO)
    tint_over(p, w1, xb, 60, PAPER, 0.85)
    draw_text(p, (xb + w1.width // 2, 60 + w1.height // 2 + 2), "青 丘", font("brush", 118), JIAO)
    draw_text(p, (16, h1 - 14), "染纸色 #EDE4CF、不透明度 0.85，夜色底 + 墨字", small, label_c, "ls")
    panels.append(p)

    # 3）竹叶：4 倍与原大，纸上和夜里；再撒一把随机旋转的
    h3 = 300
    p = np.zeros((h3, W, 3))
    half = W // 2
    p[:, :half] = paper_bg(h3, half, rng)
    p[:, half:] = night
    greens = (mixc(SHILV, JIAO, 0.25), mixc(SHILV, PAPER, 0.15))
    for x0, gcol in ((0, greens[0]), (half, greens[1])):
        for i, lf in enumerate(leaves):
            tint_over(p, lf, x0 + 40 + i * 225, 30, gcol, 1.0, scale=4)
            tint_over(p, lf, x0 + 40 + i * 225 + 48, 100, gcol, 1.0)
        for _ in range(34):
            lf = leaves[int(rng.integers(len(leaves)))]
            rot = lf.rotate(float(rng.uniform(0, 360)), resample=Image.BICUBIC, expand=True)
            tint_over(p, rot, x0 + int(rng.uniform(30, half - 70)), int(rng.uniform(140, h3 - 70)), gcol, float(rng.uniform(0.75, 1.0)))
    draw_text(p, (16, h3 - 12), "vfx/bamboo_leaf_0..3（32×12）：4 倍与原大，纸上染深石绿", small, JIAO, "ls")
    draw_text(p, (half + 16, h3 - 12), "夜里染浅石绿；下面是随机旋转的一把（原大）", small, label_c, "ls")
    panels.append(p)

    # 4）卷轴的轴：三个展开进度（卷轴缩到 1/2），右边是原大的局部（长夜、天明）
    night_scroll = Image.open(SCREENS / "scroll_qingqiu.png").convert("RGB")
    dawn_scroll = Image.open(SCREENS / "scroll_qingqiu_dawn.png").convert("RGB")
    info = roller_info()
    table = mixc(night, JIAO, 0.4)

    def place(bg, scroll, prog, ox, oy, k):
        """把展开到 prog 的卷轴 + 轴画到 bg 的 (ox, oy)，缩放 1/k（轴按同样比例缩）。"""
        x = round(prog * scroll.width)
        if x > 0:
            sub = scroll.crop((0, 0, x, scroll.height))
            if k != 1:
                sub = sub.resize((x // k, scroll.height // k), Image.LANCZOS)
            sa = np.asarray(sub, np.float64) / 255.0
            bg[oy : oy + sa.shape[0], ox : ox + sa.shape[1]] = sa
        r = roller if k == 1 else roller.resize((roller.width // k, roller.height // k), Image.LANCZOS)
        ra = np.asarray(r, np.float64) / 255.0
        rx = ox + (x - info["paper_edge_x"]) // k
        ry = oy - info["paper_top_y"] // k
        al = ra[..., 3:4]
        sl = bg[ry : ry + ra.shape[0], rx : rx + ra.shape[1]]
        sl[:] = sl * (1 - al) + ra[..., :3] * al

    row = 450
    h4 = 3 * row + 20
    p = np.broadcast_to(table, (h4, W, 3)).copy()
    for i, prog in enumerate((0.22, 0.6, 1.0)):
        place(p, night_scroll, prog, 40, 30 + i * row, 2)
        draw_text(p, (40, 30 + i * row + 432), f"展开 {prog:.0%}（卷轴与轴都缩到 1/2）", small, label_c, "ls")
    # 原大局部：从卷轴 x=1300 处展开到一半的样子
    for j, sc in enumerate((night_scroll, dawn_scroll)):
        tmp = np.broadcast_to(table, (ROLL_H + 40, 296, 3)).copy()
        place(tmp, sc.crop((1300 - 230, 0, 1300, sc.height)), 1.0, 0, 20, 1)
        p[30 : 30 + tmp.shape[0], 1284 + j * 296 : 1284 + (j + 1) * 296] = tmp
    draw_text(p, (1290, 30 + ROLL_H + 64), "原大：长夜 / 天明", small, label_c, "ls")
    # 轴头放大 3 倍
    zoom = np.broadcast_to(table, (ROLL_H + 40, 296, 3)).copy()
    place(zoom, night_scroll.crop((1300 - 230, 0, 1300, night_scroll.height)), 1.0, 0, 20, 1)
    z = Image.fromarray((zoom * 255).astype(np.uint8)).crop((166, 0, 296, 110)).resize((390, 330), Image.NEAREST)
    p[h4 - 350 : h4 - 20, W - 410 : W - 20] = np.asarray(z, np.float64) / 255.0
    draw_text(p, (W - 420, h4 - 24), "上轴头 3 倍", small, label_c, "rs")
    panels.append(p)

    sheet = np.concatenate(panels, 0)
    REVIEW.mkdir(parents=True, exist_ok=True)
    V.save_png(Image.fromarray(np.clip(np.round(sheet * 255), 0, 255).astype(np.uint8), "RGB"), path)


# ============================================================== 输出


def wash_meta(images: dict) -> dict:
    files = {}
    for name, img in images.items():
        files[f"{name}.png"] = {
            "size": list(img.size),
            "anchor": [0.5, 0.5],
            "color": "white",
            "blend": "normal",
            "tint": True,
            "kind": "backdrop",
            "id": name,
            "alpha_hint": WASH_ALPHA_HINT,
            "note": "横着的一笔淡墨，衬在大字后面（夜主名牌、结算标题）。白色：染墨色衬亮字、染纸色衬墨字，"
                    "不透明度游戏定（建议墨色 0.55–0.65、纸色 0.8）。起笔在左（饱墨），收笔在右（飞白），四边全透明"
                    + ("；短一号的" if name.endswith("_1") else ""),
        }
    return {"name": "ui", "generator": GENERATOR, "format": "PNG RGBA，直通（非预乘）alpha；白色，墨的浓淡在 alpha 里，游戏染色",
            "px_per_unit": PPU, "files": files}


def leaf_meta(images: list) -> dict:
    files = {}
    for i, img in enumerate(images):
        files[f"bamboo_leaf_{i}.png"] = {
            "size": list(img.size),
            "anchor": [0.5, 0.5],
            "color": "white",
            "blend": "normal",
            "tint": True,
            "kind": "fx",
            "points": "+x",
            "region": "qingqiu",
            "note": "打碎竹丛飞出的竹叶粒子：叶尖朝 +X，锚点居中，白色可染色（建议石绿 #5E8E72 上下浮动、夜里压暗）"
                    + ("；撕断的半片" if LEAVES[i]["tear"] else ""),
        }
    return {"name": "vfx", "generator": GENERATOR, "format": "PNG RGBA，直通（非预乘）alpha；白色可染色",
            "px_per_unit": PPU, "files": files}


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build() -> dict:
    """生成全部贴图（不写盘）。"""
    washes = {k: make_ink_wash(**p)[0] for k, p in WASHES.items()}
    leaves = [make_leaf(**p)[0] for p in LEAVES]
    roller = make_roller()
    return {"washes": washes, "leaves": leaves, "roller": roller}


def main(review: bool = True) -> dict:
    t0 = time.perf_counter()
    r = build()
    for name, img in r["washes"].items():
        V.save_png(img, WASH_DIR / f"{name}.png")
    write_json(WASH_DIR / "meta.json", wash_meta(r["washes"]))
    for i, img in enumerate(r["leaves"]):
        V.save_png(img, LEAF_DIR / f"bamboo_leaf_{i}.png")
    write_json(LEAF_DIR / "meta.json", leaf_meta(r["leaves"]))
    V.save_png(r["roller"], SCREENS / "scroll_roller.png")
    write_json(SCREENS / "scroll_roller.json", roller_info())
    if review:
        make_review(r["washes"], r["leaves"], r["roller"], REVIEW / "fx_extras_review.png")
    print(f"fx_extras：写出 {len(r['washes'])} 张淡墨、{len(r['leaves'])} 片竹叶、1 根轴，用时 {time.perf_counter() - t0:.1f} s")
    return r


if __name__ == "__main__":
    main(review="--no-review" not in sys.argv[1:])
