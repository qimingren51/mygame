#!/usr/bin/env python3
"""提灯夜行 · 青丘开场卷轴（只出桌面版；Pillow + numpy，不用 Blender）。

第一次进入青丘时展开的一幅水墨长卷，游戏在左上角写三四句旁白（文字由游戏画，不在图里）。
两张是同一幅画（同一个随机序列、同一套笔触），只是颜色和天光不同（docs/LORE.md 第 8 节：长夜里的画只有墨色，
天明时那个地区的颜色回到画里）：

  art/out/screens/scroll_qingqiu.png        长夜：只有墨（灰阶 + 宣纸），只有一方小朱砂印是彩色的。
                                            夜空上浓下淡、月亮留白（烘云托月）；远山三层隐进雾里；竹海由远到近
                                            淡墨、重墨、焦墨三层，一节一笔写竿、“个”“介”字写叶；右边狐村几座飞檐，
                                            檐下挂着灯（留白 + 一圈淡开的亮，是用墨“烘”出来的光）；竹林里游着几团狐火。
  art/out/screens/scroll_qingqiu_dawn.png   天明：同一幅画上了颜色——竹子、山上石绿花青，狐村暖光，
                                            屋檐下的青火灯成了一团柔和的青光，东边（右）天上一抹晨光，夜空淡成晓色。

两张都是 2400×800 不透明 RGB。左上约 x 60–950、y 40–390 是安静的天空，留给旁白（长夜里用纸色字，天明用墨色字）；
左下角一方朱砂印“青丘”（title_screen.make_seal，字体来自 ui_fonts）。

审图：art/out/review@2x/scroll_qingqiu_review.png（两张缩到 1280 宽，配思源宋体的模拟旁白，看排版）。

画法尽量复用 title_screen.py（只 import）：Painting（罩染 glaze / 覆盖 over / 笔触 stroke / 苔点 dot）、
ridge_line、mountain_layer、mountain_texture、wash_blob、curve_pts、make_seal。那些函数按模块里的 W、H 取画布大小，
这里画的时候用 canvas_size() 临时换成 2400×800，画完还原。

运行（在仓库根目录下）：
    art/.venv/bin/python art/post/scroll_qingqiu.py
固定随机种子，重复运行结果逐字节相同。
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 只有桌面版：先定密度，再导入 style / vfx_textures

import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

HERE = Path(__file__).resolve().parent
ART = HERE.parent
sys.path.insert(0, str(HERE))
import title_screen as T  # noqa: E402
import vfx_textures as V  # noqa: E402
from ui_fonts import font  # noqa: E402

S = V.S
OUT = ART / "out" / "screens"
REVIEW = ART / "out" / "review@2x"
W, H = 2400, 800
SEED = 1515  # 青丘

col, smoothstep, mixc, blur, noise = V.col, V.smoothstep, T.mixc, T.blur, T.noise
PAPER, PAPER_SH = T.PAPER, T.PAPER_SH
JIAO, NONG, ZHONG, DAN, QING = T.JIAO, T.NONG, T.ZHONG, T.DAN, T.QING
WHITE = np.ones(3)
LIGHT = mixc(PAPER, WHITE, 0.55)  # 留白处“烘”出来的亮（比纸还白一点）
NIGHT_AMB = 0.8  # 长夜光照图的底（灰阶）
# 天明的颜色（style.py 的国画颜料）
SHILV, HUAQING = col(S.ACCENT["shilv"]), col(S.ACCENT["huaqing"])
TENG, ZHESHI, ZHUSHA = col(S.ACCENT["tenghuang"]), col(S.ACCENT["zheshi"]), col(S.ACCENT["zhusha"])
QINGHUO = mixc(col(S.SOUL_LIGHT), SHILV, 0.35)  # 青火：偏绿的青
DAWN_WARM = mixc(TENG, col(S.LANTERN_LIGHT), 0.5)

# ---- 构图（画面像素）
TEXT_BOX = (60, 40, 950, 390)  # 留给旁白的左上角：x0, y0, x1, y1
MOON = (1745.0, 118.0, 34.0)
SEAL_AT = (70, 690)  # 朱砂印左上角
SEAL_PX = 64
# 前景竹：(根 x, 竿半宽, 顶端 x 偏移)；都伸出画面上沿
FORE_BAMBOO = [(1072.0, 9.5, -30.0), (1150.0, 7.0, 25.0), (1318.0, 10.5, -12.0), (1452.0, 6.5, 40.0), (1590.0, 8.5, -20.0)]
# 狐村的房子：(中心 x, 墙脚 y, 宽, 墙高, 屋顶高)，由远到近
HOUSES = [(2300.0, 404.0, 150.0, 34.0, 40.0), (2085.0, 452.0, 196.0, 44.0, 50.0), (1958.0, 540.0, 120.0, 32.0, 36.0),
          (2245.0, 548.0, 236.0, 54.0, 62.0)]
# 狐火：(x, y, 大小)
WISPS = [(1188.0, 468.0, 1.0), (1362.0, 372.0, 0.8), (1530.0, 520.0, 0.95), (1706.0, 430.0, 0.72), (1846.0, 352.0, 0.6),
         (1012.0, 566.0, 0.7), (1622.0, 296.0, 0.55)]

NARRATION = ["青丘在东，竹海万顷，狐族世代住在这里。", "长夜以后，狐村的屋檐下挂起一团青火，", "那是九尾接住的烛火。",
             "竹林里游着狐火，像灯，又不是灯。"]  # docs/LORE.md 6.1 的卷轴旁白（审图用）


@contextmanager
def canvas_size():
    """title_screen 的画法函数按模块里的 W、H 取画布大小：画卷轴时临时换成 2400×800，画完还原。"""
    old = (T.W, T.H)
    T.W, T.H = W, H
    try:
        yield
    finally:
        T.W, T.H = old


def paper_wide(rng) -> np.ndarray:
    """2400×800 的宣纸：vfx_textures 的可平铺纸（2 倍，1024²）镜像拼成 3×1，再叠一层画布尺度的云状浓淡。"""
    tile = np.asarray(V.make_paper(), np.float64) / 255.0
    row = np.concatenate([tile, tile[:, ::-1], tile], 1)
    out = row[37:37 + H, 61:61 + W].copy()
    cloud = T.fbm(rng, (H, W), (260.0, 90.0, 30.0), (0.5, 0.35, 0.15))
    return mixc(out, out * (PAPER_SH / PAPER), np.clip(0.18 + 0.16 * cloud, 0, 1) * 0.6)


class Scroll(T.Painting):
    """一幅卷轴：title_screen.Painting 的笔墨工具 + 天明 / 长夜两种上色 + 各部分的遮罩（天明上色用）。
    两种都用同一个 rng、同样的顺序调用，所以笔触完全一样；天明专用的随机数取自 drng。"""

    def __init__(self, rng, dawn: bool, paper: np.ndarray):
        self.rng = rng
        self.drng = np.random.default_rng(SEED + 7)
        self.dawn = dawn
        self.X, self.Y = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
        self.rgb = paper.copy()
        self.emit = np.zeros((H, W, 3))
        self.near = np.zeros((H, W))
        self.mist = np.zeros((H, W))
        self.masks = {k: np.zeros((H, W)) for k in ("far_hill", "mid_hill", "bamboo_far", "bamboo_mid", "bamboo_fore", "village", "ground")}
        # 长夜的光照（灰阶，乘在画上）：夜色底 + 月光 + 灯和狐火的光圈。“灯照见画”：只有灯边的画是亮的
        self.light = np.full((H, W), NIGHT_AMB)

    def add_light(self, x, y, r, gain, flat=1.0):
        rr = int(2.2 * r) + 4
        sl = (slice(max(0, int(y) - rr), min(H, int(y) + rr)), slice(max(0, int(x) - rr), min(W, int(x) + rr)))
        d = np.hypot(self.X[sl] - x, (self.Y[sl] - y) / flat)
        self.light[sl] += gain * np.exp(-((d / r) ** 2))

    def tone(self, ink, dawn_color=None, k: float = 0.0):
        """长夜里就是墨色；天明时兑上颜色。"""
        if not self.dawn or dawn_color is None:
            return ink
        return mixc(ink, dawn_color, k)

    def mark(self, key, a, sl=None):
        m = self.masks[key]
        if sl is None:
            np.maximum(m, np.clip(a, 0, 1), out=m)
        else:
            m[sl] = np.maximum(m[sl], np.clip(a, 0, 1))

    def stroke_m(self, pts, halfw, color, alpha=1.0, *, key=None, **kw):
        """一笔，同时记进遮罩 key。"""
        sl, cov = T.stroke_cover(self.X, self.Y, pts, halfw, self.rng, dry=kw.pop("dry", 0.0), dry_start=kw.pop("dry_start", 0.5),
                                 jitter=kw.pop("jitter", 0.16))
        if cov.size == 0:
            return
        mode = kw.pop("mode", "over")
        (self.glaze if mode == "glaze" else self.over)(cov * alpha, color, sl)
        if key:
            self.mark(key, cov, sl)


# ============================================================== 天、山、雾


def text_quiet(P: Scroll) -> np.ndarray:
    """旁白区的遮罩：1 = 留给文字的安静区域，边缘柔和地过渡。"""
    x0, y0, x1, y1 = TEXT_BOX
    return smoothstep(x1 + 160, x1 - 40, P.X) * smoothstep(y1 + 80, y1 - 40, P.Y)


def paint_sky(P: Scroll, rng):
    """夜空：上浓下淡的墨（纯墨，不兑颜色），横向的云气；月亮留白、四周一圈圈淡开（烘云托月），两缕薄云横过月下。
    旁白区的天要匀净：那里的云气压得很平。天明时同一层墨淡成晓色，顶上一层极淡的花青，东边（右）低处一抹晨光。"""
    mx, my, mr = MOON
    yn = P.Y / H
    quiet = text_quiet(P)
    cloud = noise(rng, (H, W), (260.0, 30.0), angle=-0.04)
    cloud2 = noise(rng, (H, W), (90.0, 12.0), angle=-0.02)
    tex = 1.0 + (0.26 * cloud + 0.10 * cloud2) * (1.0 - 0.8 * quiet)
    if P.dawn:
        base = 0.20 - 0.14 * smoothstep(0.0, 0.62, yn)
        sky = mixc(DAN, HUAQING, 0.45)
    else:
        base = 0.86 - 0.52 * smoothstep(0.0, 0.68, yn) + 0.1 * quiet  # 旁白区再沉一点，纸色字看得清
        sky = mixc(NONG, ZHONG, 0.45)
    a = base * tex
    d = np.hypot(P.X - mx, P.Y - my)
    halo = smoothstep(mr * 0.95, mr * 6.0, d)
    a = a * (0.10 + 0.90 * halo ** 0.75)
    if not P.dawn:
        P.add_light(mx, my, 420.0, 0.16)
        P.add_light(mx, my, 120.0, 0.12)
    a = a * smoothstep(mr - 0.5, mr + 2.0, d + 1.5 * noise(rng, (H, W), 1.5))  # 月轮留白
    P.glaze(np.clip(a, 0, 0.92), sky)
    # 横过月亮的薄云
    for cy, amp, wid, sx in ((my + 0.35 * mr, 0.5, 9.0, 1.0), (my + 0.85 * mr, 0.38, 7.0, 1.3), (my - 1.6 * mr, 0.14, 12.0, 2.0)):
        band = np.exp(-((P.Y - cy - 6 * noise(rng, (H, W), (140.0, 10.0))) / wid) ** 2)
        span = smoothstep(mx - 300 * sx, mx - 80, P.X) * smoothstep(mx + 340 * sx, mx + 110, P.X)
        t2 = 0.55 + 0.45 * V.rank01(noise(rng, (H, W), (70.0, 1.6), angle=-0.03))
        P.glaze(np.clip(amp * band * span * t2 * (0.5 if P.dawn else 1.0), 0, 1), sky)
    # 右半边天上几片云：淡墨染开，边上一圈干了的水痕（旁白区不画）
    for cx, cy, rx, ry, al in ((1320, 70, 300, 34, 0.16), (2100, 150, 260, 36, 0.18), (1980, 300, 200, 22, 0.10), (2350, 60, 160, 26, 0.12)):
        T.wash_blob(P, cx, cy, rx, ry, sky, al * (0.6 if P.dawn else 1.0), rng, ang=-0.03, rough=0.5, edge=0.6)
    if P.dawn:
        # 晨光：东边（右）低处暖，往上、往左淡；月亮成了一弯淡淡的晓月
        east = smoothstep(700.0, 2400.0, P.X) ** 1.4 * np.exp(-(((P.Y - 430.0) / 190.0) ** 2))
        P.over(np.clip(0.42 * east, 0, 1), mixc(DAWN_WARM, WHITE, 0.35))
        P.glaze(np.clip(0.10 * smoothstep(0.4, 0.0, yn) * (1 - 0.6 * east), 0, 1), mixc(HUAQING, PAPER, 0.3))


def paint_hills(P: Scroll, rng):
    """三层远山，一层比一层近、墨一层比一层重，山脚隐进雾里；层与层之间铺一道雾。旁白区底下的山压得很低。"""
    xs = np.arange(W) + 0.5
    layers = [
        # 基线, 山峰 (中心 x, 高, 左半宽, 右半宽, 尖度), 颜色, 天明兑的颜色, 浓度, 渐淡长度, 雾起处, 遮罩
        (440, [(1180, 205, 260, 220, 1.3), (1520, 250, 210, 240, 1.25), (1880, 190, 230, 260, 1.2), (2260, 225, 240, 200, 1.3),
               (720, 70, 260, 260, 1.0), (330, 50, 300, 300, 1.0)], QING, mixc(HUAQING, QING, 0.45), 0.34, 130.0, 480, "far_hill"),
        (515, [(980, 150, 240, 200, 1.35), (1370, 120, 200, 230, 1.2), (1720, 165, 220, 210, 1.3), (2120, 150, 240, 230, 1.25),
               (480, 60, 280, 260, 1.0)], mixc(QING, DAN, 0.5), mixc(mixc(SHILV, HUAQING, 0.5), DAN, 0.35), 0.40, 100.0, 555, "mid_hill"),
    ]
    for li, (base, peaks, c, cd, a, fade, mist_from, key) in enumerate(layers):
        r = T.ridge_line(xs, peaks, base, rng, rough=5.0)
        color = P.tone(c, cd, 0.55)
        T.mountain_layer(P, r, color, a, fade, rng, mist_from=mist_from, mist_len=70.0)
        P.mark(key, smoothstep(-1.0, 1.4, P.Y - r[None, :]) * smoothstep(mist_from + 70, mist_from, P.Y))
        if li >= 1:
            T.mountain_texture(P, r, color, rng, mist_from, n=80, strength=0.28, edge_k=1.2)
        paint_fog_band(P, rng, base, 0.34)
    # 山谷里的一道大雾：竹海从这里长出来
    paint_fog_band(P, rng, 600, 0.6, span=(560, 700))


def paint_fog_band(P: Scroll, rng, base: float, strength: float, span=None):
    """一道横雾：纸色（比纸略亮）罩上去，高低随 x 起伏，浓淡成片。"""
    wav = blur(rng.standard_normal((1, W)), (110.0, 0))[0]
    wav = 30.0 * wav / (wav.std() + 1e-9)
    yb = P.Y + wav[None, :]
    if span is None:
        fog = smoothstep(base - 150, base - 30, yb) * smoothstep(base + 90, base, yb)
    else:
        lo, hi = span
        fog = smoothstep(lo - 60, lo + 40, yb) * smoothstep(hi + 70, hi - 20, yb)
    fog = fog * np.clip(0.35 + 0.65 * smoothstep(-1.2, 1.2, noise(rng, (H, W), (150.0, 22.0))), 0, 1)
    color = P.tone(mixc(PAPER, WHITE, 0.22), mixc(DAWN_WARM, WHITE, 0.6), 0.25 * smoothstep(800, 2400, P.X))
    P.over(np.clip(fog * strength, 0, 1), color)
    P.mist = np.maximum(P.mist, np.clip(fog * strength * 1.6, 0, 1))


# ============================================================== 竹


def leaf(P: Scroll, base, ang, L, hw, color, alpha, key, *, droop=0.25, dry=0.2):
    """一片竹叶：起笔细、很快按到最宽（约三成处），再长长地收成尖；叶尖往下垂一点（droop）。"""
    d = np.array([math.cos(ang), math.sin(ang)])
    n = np.array([-d[1], d[0]])
    # 往下垂：叶尖朝 +y 偏，偏的方向取法线里朝下的那一侧
    sgn = 1.0 if n[1] >= 0 else -1.0
    b = np.asarray(base, np.float64)
    bend = droop * (1.0 - abs(d[1])) + 0.08
    pts = T.V.bezier([b, b + d * L * 0.5 + n * sgn * bend * L * 0.12, b + d * L * 0.97 + n * sgn * bend * L * 0.32], 30)
    prof = np.interp(np.linspace(0, 1, 30), [0, 0.08, 0.3, 0.72, 1.0], [0.2, 0.75, 1.0, 0.5, 0.02])
    P.stroke_m(pts, hw * prof, color, alpha, key=key, dry=dry, dry_start=0.6, jitter=0.12)


# “个”“介”“分”等字形：(相对中线的角度, 相对长度)
LEAF_GROUPS = (
    ((0.0, 1.0), (-0.55, 0.8), (0.5, 0.82)),  # 个
    ((-0.12, 1.0), (0.3, 0.9), (-0.6, 0.72), (0.72, 0.7)),  # 介
    ((-0.2, 1.0), (0.28, 0.85)),  # 分
    ((0.05, 1.0), (-0.38, 0.88), (0.42, 0.78), (-0.8, 0.6), (0.85, 0.55)),  # 个 + 两片小的
    ((0.0, 1.0), (0.42, 0.75), (0.85, 0.6)),  # 偏向一侧的“个”
)


def leaf_cluster(P: Scroll, x, y, scale, color, alpha, key, rng, *, n=None, droop=1.0, spread=1.0, aim=None):
    """一组竹叶：按“个”“介”“分”的字形从一点散开；整组的朝向 aim（默认斜向下），叶尖下垂。"""
    if n is not None:
        groups = [g for g in LEAF_GROUPS if len(g) <= n] or [LEAF_GROUPS[2]]
        g = groups[int(rng.integers(len(groups)))]
    else:
        g = LEAF_GROUPS[int(rng.integers(len(LEAF_GROUPS)))]
    if aim is None:
        aim = math.pi / 2 + rng.choice([-1.0, 1.0]) * rng.uniform(0.15, 0.85) * droop
    flip = rng.choice([-1.0, 1.0])
    for (off, rl) in g:
        ang = aim + flip * off * spread * rng.uniform(0.85, 1.15)
        L = scale * rl * rng.uniform(0.88, 1.12)
        hw = scale * rng.uniform(0.065, 0.085)
        leaf(P, (x + rng.normal(0, 0.03 * scale), y + rng.normal(0, 0.03 * scale)), ang, L, hw, color, alpha, key,
             droop=0.25 + 0.3 * rng.random())


def culm(P: Scroll, x0, y_bot, y_top, hw, color, alpha, rng, key, *, lean=0.0, node_color=None, mode="glaze",
         twigs: int = 0, leaf_color=None, leaf_scale=60.0, leaf_alpha=1.0, leaf_n=(1, 3), dry=0.25):
    """一竿竹：从下往上一节一笔，节与节之间留一线空，节处一笔“乙”字形的节；竿两边略深（侧锋）。
    twigs>0 时从上半的节上抽出小枝，枝头一组组竹叶。返回各节的位置。"""
    L = y_bot - y_top

    def cx(y):
        f = np.clip((y_bot - y) / L, 0, 1)
        return x0 + lean * f ** 1.6

    # 节距：根部短、中段长、梢头又短
    seg = []
    y = y_bot
    k = 0
    while y > y_top:
        f = (y_bot - y) / L
        step = hw * rng.uniform(11.0, 15.0) * (0.6 + 0.6 * math.sin(math.pi * min(f + 0.15, 1.0)))
        seg.append((y, max(y - step, y_top)))
        y -= step
        k += 1
    nodes = []
    gap = max(1.2, 0.28 * hw)
    for (ya, yb) in seg:
        ys = np.linspace(ya - gap, yb + gap, 16)
        if ys[0] <= ys[-1]:
            continue
        pts = np.stack([cx(ys), ys], -1)
        t = np.linspace(0, 1, 16)
        prof = hw * (0.94 + 0.10 * (np.exp(-(t / 0.08) ** 2) + np.exp(-((1 - t) / 0.08) ** 2)))
        P.stroke_m(pts, prof, color, alpha, key=key, dry=dry, dry_start=0.0, jitter=0.06, mode=mode)
        # 侧锋：两边各一道略深
        for sgn in (-1.0, 1.0):
            P.stroke_m(pts + [sgn * 0.72 * hw, 0.0], 0.22 * hw, color, 0.35 * alpha, dry=0.3, dry_start=0.0, jitter=0.1, mode="glaze")
        nodes.append((float(cx(yb)), yb))
    nc = node_color if node_color is not None else color
    for (nx, ny) in nodes[:-1]:
        p = T.V.bezier([(nx - 1.15 * hw, ny + 0.25 * hw), (nx, ny - 0.35 * hw), (nx + 1.2 * hw, ny + 0.1 * hw)], 16)
        P.stroke_m(p, max(0.9, 0.3 * hw) * np.interp(np.linspace(0, 1, 16), [0, 0.3, 1], [1.0, 0.8, 0.4]), nc, min(1.0, alpha * 1.1), key=key)
    if twigs:
        cand = [nd for nd in nodes[:-1] if 0 < nd[1] < y_bot - 0.3 * L]
        if cand:
            pick = rng.choice(len(cand), size=min(twigs, len(cand)), replace=False)
            lc = leaf_color if leaf_color is not None else color
            for i in sorted(pick):
                nx, ny = cand[i]
                side = rng.choice([-1.0, 1.0])
                tl = leaf_scale * rng.uniform(0.9, 1.5)
                a = math.radians(rng.uniform(28, 60))
                end = np.array([nx + side * tl * math.cos(a), ny - tl * math.sin(a)])
                mid = np.array([nx + side * tl * 0.45 * math.cos(a), ny - tl * 0.6 * math.sin(a)])
                twig = T.V.bezier([(nx, ny), mid, end], 24)
                P.stroke_m(twig, max(0.7, 0.2 * hw) * np.linspace(1.0, 0.45, 24), nc, alpha, key=key)
                # 枝头一组、枝上再抽一两根小枝，各一组；叶朝枝的一侧斜垂
                spots = [end]
                for j in range(int(rng.integers(1, 3))):
                    p0 = twig[int(rng.uniform(0.35, 0.8) * 23)]
                    q = p0 + np.array([side * rng.uniform(0.2, 0.5), -rng.uniform(0.1, 0.45)]) * tl * 0.6
                    P.stroke_m(T.V.bezier([p0, (p0 + q) / 2 + [0, -2], q], 12), max(0.6, 0.12 * hw), nc, alpha, key=key)
                    spots.append(q)
                for p_ in spots:
                    aim = math.pi / 2 - side * rng.uniform(0.2, 1.0)
                    leaf_cluster(P, p_[0], p_[1], leaf_scale * rng.uniform(0.85, 1.1), lc, leaf_alpha, key, rng,
                                 n=int(rng.integers(*leaf_n)) + 2, aim=aim)
    return nodes


def paint_far_bamboo(P: Scroll, rng):
    """远竹：雾里一片淡淡的竹林，细竿、小叶，根隐在雾里。"""
    quiet = TEXT_BOX
    xs = np.sort(rng.uniform(560, 2060, 64))
    for x in xs:
        top = rng.uniform(330, 440)
        if x < quiet[2] + 40:
            top = max(top, quiet[3] + rng.uniform(20, 60))
        hw = rng.uniform(1.4, 2.4)
        c = P.tone(mixc(QING, DAN, rng.uniform(0.1, 0.45)), mixc(mixc(SHILV, HUAQING, 0.4), QING, 0.4), 0.5)
        culm(P, x, 640.0, top, hw, c, rng.uniform(0.45, 0.7), rng, "bamboo_far", lean=rng.normal(0, 8), dry=0.3)
        for _ in range(int(rng.integers(1, 4))):
            leaf_cluster(P, x + rng.normal(0, 10), top + rng.uniform(0, 70), rng.uniform(16, 24), c, rng.uniform(0.4, 0.65),
                         "bamboo_far", rng, droop=0.8)
    paint_fog_band(P, rng, 0, 0.55, span=(560, 680))


def paint_mid_bamboo(P: Scroll, rng, xs_range=(860, 2060), n=20):
    """中景竹：重墨的竿、成组的叶，梢头的叶淡（后面）、近的浓。"""
    x0, x1 = xs_range
    xs = np.sort(rng.uniform(x0, x1, n))
    for x in xs:
        top = rng.uniform(150, 330)
        if x < TEXT_BOX[2] + 60:
            top = max(top, TEXT_BOX[3] + rng.uniform(0, 40))
        hw = rng.uniform(2.8, 4.6)
        depth = rng.uniform(0, 1)
        c = P.tone(mixc(DAN, ZHONG, 0.3 + 0.5 * depth), mixc(SHILV, PAPER, 0.25), 0.45)
        lc = P.tone(mixc(DAN, NONG, 0.25 + 0.55 * depth), mixc(SHILV, HUAQING, 0.2), 0.45)
        culm(P, x, 700.0, top, hw, c, rng.uniform(0.7, 0.9), rng, "bamboo_mid", lean=rng.normal(0, 14), twigs=int(rng.integers(2, 5)),
             leaf_color=lc, leaf_scale=rng.uniform(30, 42), leaf_alpha=0.85, dry=0.3)
        for _ in range(int(rng.integers(2, 4))):  # 梢头几组
            leaf_cluster(P, x + rng.normal(0, 8), top + rng.uniform(5, 40), rng.uniform(28, 38), lc, 0.8, "bamboo_mid", rng, droop=0.9)


def paint_fore_bamboo(P: Scroll, rng):
    """前景竹：焦墨粗竿伸出画面上沿，节上抽枝，叶大而浓，前浓后淡两遍。"""
    for (x, hw, lean) in FORE_BAMBOO:
        c = P.tone(mixc(NONG, ZHONG, 0.25), mixc(SHILV, PAPER, 0.15), 0.4)
        # 第一遍：后面一层淡叶
        for _ in range(int(rng.integers(5, 9))):
            leaf_cluster(P, x + rng.uniform(-110, 110), rng.uniform(20, 360), rng.uniform(56, 80),
                         P.tone(mixc(DAN, ZHONG, 0.3), mixc(mixc(SHILV, HUAQING, 0.3), PAPER, 0.2), 0.45), 0.55, "bamboo_fore", rng, droop=0.9)
        culm(P, x, 812.0, -12.0, hw, c, 0.95, rng, "bamboo_fore", lean=lean, node_color=JIAO, mode="over", twigs=int(rng.integers(4, 7)),
             leaf_color=P.tone(mixc(JIAO, NONG, 0.3), mixc(SHILV, NONG, 0.25), 0.45), leaf_scale=rng.uniform(64, 84), leaf_alpha=0.92, dry=0.35)


# ============================================================== 狐村


def roof_poly(cx, ye, w, rh):
    """歇山顶的简化：屋面下宽上窄、两坡略凹，檐口中间微垂、两角起翘。返回 (屋面多边形, 檐口线, 屋脊线)。"""
    oh = 0.14 * w
    lift = 0.32 * rh
    rw = 0.56 * w
    eave = T.curve_pts([(cx - w / 2 - oh, ye - lift), (cx - w / 2 + 0.05 * w, ye - 0.02 * rh), (cx, ye + 0.05 * rh),
                        (cx + w / 2 - 0.05 * w, ye - 0.02 * rh), (cx + w / 2 + oh, ye - lift)], 80)
    yr = ye - rh
    right = T.curve_pts([(cx + w / 2 + oh, ye - lift), (cx + 0.40 * w, ye - 0.45 * rh), (cx + rw / 2, yr)], 30)
    left = T.curve_pts([(cx - rw / 2, yr), (cx - 0.40 * w, ye - 0.45 * rh), (cx - w / 2 - oh, ye - lift)], 30)
    ridge = T.curve_pts([(cx - rw / 2 - 0.06 * w, yr - 0.16 * rh), (cx - rw / 2, yr), (cx + rw / 2, yr), (cx + rw / 2 + 0.06 * w, yr - 0.16 * rh)], 40)
    poly = np.vstack([eave, right[1:], left[1:-1]])
    return poly, eave, ridge


def paint_house(P: Scroll, rng, cx, yb, w, wh, rh, lanterns: list):
    """一座屋：纸色留白的墙（淡墨勾柱、门窗），重墨的屋面（瓦垄），焦墨的檐口和屋脊，檐下一道暗。
    檐下两角各挂一盏灯（位置记进 lanterns，最后统一画光）。"""
    ye = yb - wh
    wl, wr = cx - w / 2 + 0.06 * w, cx + w / 2 - 0.06 * w
    # 墙：盖住后面的竹和山
    wall = [(wl, ye), (wr, ye), (wr, yb), (wl, yb)]
    wm = poly_cover(P, wall)
    # 长夜里墙在暗处（灰），只有灯边亮；天明时是晨光照着的暖白
    wall_c = P.tone(mixc(PAPER, ZHONG, 0.5), mixc(mixc(PAPER, DAWN_WARM, 0.14), WHITE, 0.22), 1.0)
    P.over(0.94 * wm, wall_c)
    P.mark("village", wm)
    # 柱、门、窗
    for xx in (wl + 2, cx - 0.18 * w, cx + 0.18 * w, wr - 2):
        P.stroke_m(np.array([(xx, ye + 2), (xx, yb)]), 1.3, mixc(DAN, ZHONG, 0.4), 0.85, key="village", jitter=0.2)
    door_w = 0.16 * w
    door = [(cx - door_w / 2, yb - 0.72 * wh), (cx + door_w / 2, yb - 0.72 * wh), (cx + door_w / 2, yb), (cx - door_w / 2, yb)]
    P.over(0.85 * poly_cover(P, door), P.tone(mixc(NONG, ZHONG, 0.3), mixc(ZHESHI, NONG, 0.6), 0.6))
    for sx in (-1, 1):
        wx = cx + sx * 0.33 * w
        win = [(wx - 0.07 * w, ye + 0.3 * wh), (wx + 0.07 * w, ye + 0.3 * wh), (wx + 0.07 * w, ye + 0.68 * wh), (wx - 0.07 * w, ye + 0.68 * wh)]
        P.over(0.55 * poly_cover(P, win), mixc(ZHONG, DAN, 0.3))
        for k in range(1, 3):
            P.stroke_m(np.array([(wx - 0.07 * w + k * 0.0467 * w, ye + 0.3 * wh), (wx - 0.07 * w + k * 0.0467 * w, ye + 0.68 * wh)]), 0.7, LIGHT, 0.6)
    # 墙脚一线、台基
    P.stroke_m(np.array([(wl - 6, yb + 1), (wr + 6, yb + 1)]), 1.8, NONG, 0.8, key="village", dry=0.3, jitter=0.25)
    # 檐下的暗
    P.glaze(0.55 * poly_cover(P, wall) * smoothstep(ye + 0.3 * wh, ye, P.Y), ZHONG)
    # 屋面
    poly, eave, ridge = roof_poly(cx, ye, w, rh)
    rm = poly_cover(P, [tuple(p) for p in poly])
    k = smoothstep(ye - rh, ye, P.Y)
    roof_c = P.tone(mixc(ZHONG, NONG, 0.4), mixc(mixc(HUAQING, NONG, 0.55), ZHONG, 0.2), 0.55)
    P.over(0.92 * rm, mixc(mixc(roof_c, DAN, 0.35), roof_c, k))
    P.mark("village", rm)
    # 瓦垄：从屋脊往檐口的细线，略向两边张开
    n_t = int(w / 9)
    for i in range(n_t):
        f = (i + 0.5) / n_t - 0.5
        top = (cx + f * 0.56 * w, ye - rh + 2)
        bot = (cx + f * (w + 0.22 * w), ye - 0.1 * rh + 0.25 * rh * (2 * f) ** 2 * -1)
        P.stroke_m(np.array([top, bot]), 0.8, mixc(NONG, JIAO, 0.4), 0.55 * rm.max(), mode="glaze")
    # 檐口、屋脊
    P.stroke_m(eave, np.interp(np.linspace(0, 1, len(eave)), [0, 0.1, 0.9, 1], [1.2, 3.0, 3.0, 1.2]), JIAO, 0.95, key="village", dry=0.3, jitter=0.2)
    P.stroke_m(ridge, np.interp(np.linspace(0, 1, len(ridge)), [0, 0.15, 0.85, 1], [1.4, 3.2, 3.2, 1.4]), JIAO, 0.95, key="village", dry=0.25, jitter=0.2)
    for e in (eave[0], eave[-1]):  # 翘角一点
        P.dot(e[0], e[1] - 1.0, 2.2, 1.6, JIAO, 0.9)
    lanterns.extend(lantern_spots(cx, yb, w, wh, rh))


def lantern_spots(cx, yb, w, wh, rh) -> list:
    """一座屋檐下的两盏灯：挂在檐下两角稍里。返回 [(x, y, 大小, 挂绳上端 y)]（测试也用它找灯的位置）。"""
    ye = yb - wh
    return [(cx + sx * (w / 2 - 0.02 * w), ye + 0.28 * wh + 8, 0.75 + 0.25 * min(w / 236, 1.0), ye - 0.1 * rh) for sx in (-1, 1)]


def poly_cover(P: Scroll, poly, ss: int = 2) -> np.ndarray:
    """多边形 → 本画布的覆盖度（超采样抗锯齿）。"""
    pts = np.asarray(poly, np.float64)
    x0, y0 = max(0, int(pts[:, 0].min()) - 2), max(0, int(pts[:, 1].min()) - 2)
    x1, y1 = min(W, int(pts[:, 0].max()) + 3), min(H, int(pts[:, 1].max()) + 3)
    out = np.zeros((H, W))
    if x1 <= x0 or y1 <= y0:
        return out
    im = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
    ImageDraw.Draw(im).polygon([((x - x0) * ss, (y - y0) * ss) for x, y in pts], fill=255)
    out[y0:y1, x0:x1] = V.downsample(np.asarray(im, np.float64) / 255.0, ss)
    return out


def paint_village(P: Scroll, rng) -> list:
    """狐村：右边山坡上几座屋，坡从雾里升起；屋后几竿竹，门前几级石阶。返回灯的位置。"""
    # 山坡
    xs = np.arange(W) + 0.5
    slope = np.interp(xs, [1760, 1900, 2050, 2200, 2400], [640, 560, 500, 455, 430])
    slope = slope + 6 * blur(rng.standard_normal((1, W)), (25.0, 0))[0] / 0.2
    depth = P.Y - slope[None, :]
    inside = smoothstep(-1.0, 1.5, depth) * smoothstep(1700, 1820, P.X)
    texg = V.rank01(noise(rng, (H, W), (60.0, 2.0), angle=-0.2))
    a = (0.16 + 0.32 * smoothstep(0, 220, depth)) * (0.7 + 0.5 * texg) * inside
    P.glaze(np.clip(a, 0, 0.8), P.tone(mixc(DAN, ZHONG, 0.3), mixc(mixc(SHILV, ZHESHI, 0.4), DAN, 0.4), 0.5))
    P.mark("ground", inside)
    # 坡顶一道枯笔
    for xa, xb in ((1880, 1990), (2010, 2160), (2230, 2400)):
        xx = np.linspace(xa, xb, 30)
        P.stroke_m(np.stack([xx, np.interp(xx, xs, slope) + 1.5], -1), np.interp(np.linspace(0, 1, 30), [0, 0.15, 0.8, 1], [0.8, 2.4, 2.0, 0.6]),
                   NONG, 0.5, key="ground", dry=0.55, dry_start=0.2, jitter=0.3)
    # 屋后几竿竹
    for x in (2010.0, 2180.0, 2350.0, 1905.0):
        top = rng.uniform(230, 300)
        c = P.tone(mixc(DAN, ZHONG, 0.5), mixc(SHILV, DAN, 0.3), 0.55)
        culm(P, x, float(np.interp(x, xs, slope)) + 10, top, rng.uniform(2.6, 3.6), c, 0.8, rng, "bamboo_mid", lean=rng.normal(0, 10),
             twigs=1, leaf_color=c, leaf_scale=34.0, leaf_alpha=0.8)
    lanterns: list = []
    for (cx, yb, w, wh, rh) in HOUSES:
        paint_house(P, rng, cx, yb, w, wh, rh, lanterns)
    # 石阶：从坡下弯上来
    for k in range(7):  # 每级一块石板：顶面淡、前沿一笔重墨，两头略收
        y = 640 - k * 15
        x = 2140 - k * 6 + 10 * math.sin(k * 0.8)
        hw_ = 26 - k * 1.5
        slab = [(x - hw_ + 2, y - 5), (x + hw_ - 1, y - 6), (x + hw_ + 1, y), (x - hw_, y + 1)]
        P.glaze(0.35 * poly_cover(P, slab), mixc(DAN, QING, 0.5))
        P.stroke_m(np.array([(x - hw_, y + 0.5), (x + hw_ + 1, y - 0.5)]), np.array([1.0, 2.2]), mixc(ZHONG, NONG, 0.5), 0.75, key="ground", dry=0.35, jitter=0.3)
        P.mark("ground", poly_cover(P, slab))
    return lanterns


# ============================================================== 光：灯与狐火


def paint_lanterns(P: Scroll, lanterns, rng):
    """檐下的灯：长夜里是留白的灯身 + 一圈用墨“烘”出来的亮（周围压暗、灯边淡开）；天明时是一团柔和的青光。"""
    for (x, y, s, ye) in lanterns:
        r = 58.0 * s
        sl = (slice(max(0, int(y - 2 * r)), min(H, int(y + 2 * r))), slice(max(0, int(x - 2 * r)), min(W, int(x + 2 * r))))
        dx, dy = P.X[sl] - x, P.Y[sl] - y
        d = np.hypot(dx, dy * 1.1)
        glow = np.exp(-((d / r) ** 2)) * 0.7 + np.exp(-((d / (0.4 * r)) ** 2)) * 0.25
        glow_c = P.tone(LIGHT, mixc(QINGHUO, WHITE, 0.25), 0.85)
        P.over(np.clip(glow, 0, 1), glow_c, sl)
        if P.dawn:  # 青火自己发光：上色之后再加，不被暖色的墙带偏
            P.emit[sl] += (0.16 * np.exp(-((d / (1.2 * r)) ** 2)) + 0.12 * np.exp(-((d / (0.35 * r)) ** 2)))[..., None] * (QINGHUO - 0.25 * col(S.LANTERN_LIGHT))
        else:
            P.add_light(x, y, 2.4 * r, 0.32)
        # 挂绳、灯身、上下的箍
        P.stroke_m(np.array([(x, ye + 6), (x, y - 12 * s)]), 0.9, NONG, 0.8)
        body = smoothstep(1.05, 0.9, np.hypot(dx / (9.5 * s), dy / (12.0 * s)))
        P.over(0.97 * body, P.tone(mixc(LIGHT, WHITE, 0.5), mixc(QINGHUO, WHITE, 0.55), 1.0), sl)
        for yy in (y - 11.4 * s, y + 11.4 * s):
            P.stroke_m(np.array([(x - 5.2 * s, yy), (x + 5.2 * s, yy)]), 1.5 * s, JIAO, 0.9)
        for sx_ in (-1.0, 1.0):  # 灯笼骨：两笔淡墨的弧
            P.stroke_m(T.V.bezier([(x + sx_ * 5.0 * s, y - 9 * s), (x + sx_ * 8.6 * s, y), (x + sx_ * 5.0 * s, y + 9 * s)], 14), 0.6, DAN, 0.5)
        P.stroke_m(np.array([(x, y + 12 * s), (x, y + 21 * s)]), 1.0 * s, NONG, 0.7)  # 灯穗


def paint_wisps(P: Scroll, rng):
    """狐火：竹林里游着的几团火。留白的火苗（下圆上尖、尖头甩向一侧），淡墨勾两笔火舌，四周一圈淡开的亮，
    身后拖一缕淡淡的游迹。天明时淡成几点青白的微光。"""
    for (x, y, s) in WISPS:
        s = 1.7 * s
        if not P.dawn:
            P.add_light(x, y - 4 * s, 40 * s, 0.22)
        r = int(70 * s) + 8
        sl = (slice(max(0, int(y) - r), min(H, int(y) + r)), slice(max(0, int(x) - r), min(W, int(x) + r)))
        dx, dy = P.X[sl] - x, P.Y[sl] - y
        k = 0.35 if P.dawn else 1.0
        halo = np.exp(-((np.hypot(dx, dy + 6 * s) / (34 * s)) ** 2))
        P.over(np.clip(0.5 * k * halo, 0, 1), P.tone(LIGHT, mixc(QINGHUO, WHITE, 0.5), 0.6), sl)
        sway = 3.0 * s * np.sin(dy / (7.0 * s) + x * 0.01)
        u = (dx - sway * smoothstep(0, -24 * s, dy)) / (7.0 * s)
        v = dy / (12.0 * s)
        width = np.where(v < 0, np.clip(1 + v * 0.55, 0, 1) ** 1.4, np.sqrt(np.clip(1 - v * v, 0, 1)))
        body = smoothstep(1.05, 0.6, np.abs(u) / np.maximum(width, 1e-3)) * smoothstep(1.0, 0.8, v) * smoothstep(-1.85, -1.3, v)
        P.over(np.clip(0.96 * k * body, 0, 1), P.tone(mixc(LIGHT, WHITE, 0.6), mixc(QINGHUO, WHITE, 0.6), 0.5), sl)
        if P.dawn:
            P.emit[sl] += (0.08 * halo)[..., None] * QINGHUO
        # 淡墨勾的两笔火舌（尖头甩向一侧）
        lean = 1.0 if (x * 0.013) % 2 > 1 else -1.0
        for sgn in (-1.0, 1.0):
            pts = T.V.bezier([(x + sgn * 6.5 * s, y + 6 * s), (x + sgn * 7.5 * s, y - 6 * s), (x + lean * 4 * s + sgn * 2 * s, y - 15 * s),
                              (x + lean * 6 * s, y - 23 * s)], 24)
            P.stroke_m(pts, np.linspace(1.3, 0.3, 24) * s, mixc(DAN, ZHONG, 0.3), (0.45 if not P.dawn else 0.2), dry=0.3, dry_start=0.4)
        # 游迹：身后几点渐小的亮
        for j in range(1, 5):
            px, py = x - lean * j * 9 * s, y + 10 * s + j * 6 * s + 3 * math.sin(j * 1.7)
            P.dot(px, py, (3.2 - 0.6 * j) * s, (3.2 - 0.6 * j) * s, P.tone(LIGHT, mixc(QINGHUO, WHITE, 0.5), 0.5), 0.6 * k * (1 - 0.18 * j))


# ============================================================== 近处的坡


def paint_foreground(P: Scroll, rng):
    """最下面一道坡：淡墨铺地（右重左轻，左下角留给印），干笔擦、苔点、几丛草、两三个竹笋。"""
    xs = np.arange(W) + 0.5
    edge = 742 + 16 * blur(rng.standard_normal((1, W)), (60.0, 0))[0] / 0.1 - 30 * smoothstep(900, 2000, xs)
    depth = P.Y - edge[None, :]
    inside = smoothstep(-1.0, 1.5, depth)
    tex = V.rank01(noise(rng, (H, W), (80.0, 2.0), angle=-0.03))
    left_light = 0.35 + 0.65 * smoothstep(150, 1100, P.X)
    a = (0.28 + 0.5 * smoothstep(0, 60, depth)) * (0.7 + 0.5 * tex) * inside * left_light
    P.glaze(np.clip(a, 0, 0.85), P.tone(mixc(DAN, ZHONG, 0.4), mixc(mixc(SHILV, ZHESHI, 0.35), DAN, 0.45), 0.5))
    P.mark("ground", inside)
    # 坡沿：一段段长短不一、轻重不一的枯笔，中间断开
    xa = 260.0
    while xa < W - 20:
        ln = rng.uniform(70, 240)
        xb = min(xa + ln, W + 10)
        xx = np.linspace(xa, xb, 30)
        wgt = rng.uniform(0.5, 1.0) * (0.5 + 0.5 * smoothstep(250, 900, xa))
        P.stroke_m(np.stack([xx, np.interp(xx, xs, edge) + 2.0 + rng.uniform(-3, 3) * np.sin(np.linspace(0, math.pi, 30))], -1),
                   np.interp(np.linspace(0, 1, 30), [0, 0.12, 0.7, 1], [1.0, 2.0 + 2.6 * wgt, 1.6 + 2.0 * wgt, 0.6]),
                   JIAO, 0.6 + 0.35 * wgt, key="ground", dry=0.5, dry_start=0.25, jitter=0.3)
        xa = xb + rng.uniform(15, 70)
    for _ in range(80):  # 苔点
        x = rng.uniform(300, 2390)
        y = float(np.interp(x, xs, edge)) + rng.normal(0, 4) + 2
        r = rng.uniform(1.8, 4.4)
        P.dot(x, y, r * rng.uniform(1.0, 1.6), r, P.tone(JIAO, SHILV, 0.3), rng.uniform(0.75, 1.0), ang=rng.uniform(-0.4, 0.4))
    for x in (420.0, 760.0, 1240.0, 1700.0, 2050.0, 2330.0):  # 草
        y = float(np.interp(x, xs, edge)) + 3
        for _ in range(int(rng.integers(4, 8))):
            ln = rng.uniform(20, 44)
            lean = math.radians(rng.uniform(-30, 25))
            bx = x + rng.normal(0, 5)
            ts = np.linspace(0, 1, 12)
            xx = bx + np.sin(lean) * ln * ts - rng.uniform(0, 8) * ts ** 2
            yy = y - np.cos(lean) * ln * ts
            P.stroke_m(np.stack([xx, yy], -1), np.interp(ts, [0, 0.25, 1], [1.5, 1.7, 0.25]), P.tone(JIAO, SHILV, 0.35), rng.uniform(0.75, 0.95),
                       key="ground", jitter=0.1)
    for (x, h_, b_) in ((1395.0, 46.0, 11.0), (1425.0, 28.0, 8.0), (2010.0, 34.0, 9.0)):  # 竹笋
        y0 = float(np.interp(x, xs, edge)) + 8
        pts = [(x - b_, y0), (x - 0.7 * b_, y0 - 0.45 * h_), (x + 0.15 * b_, y0 - h_), (x + 0.6 * b_, y0 - 0.5 * h_), (x + b_, y0)]
        c = T.curve_pts(pts, 60)
        m = poly_cover(P, [tuple(p) for p in c])
        P.glaze(0.85 * m, P.tone(mixc(ZHONG, DAN, 0.4), mixc(ZHESHI, DAN, 0.4), 0.6))
        P.stroke_m(c, 1.6, JIAO, 0.9, key="ground", dry=0.25)
        for k in range(3):
            yk = y0 - (0.25 + 0.22 * k) * h_
            P.stroke_m(T.V.bezier([(x - 0.7 * b_ + k * 1.5, yk + 4), (x, yk - 2), (x + 0.6 * b_ - k, yk - 6)], 12), 1.0, NONG, 0.8)


# ============================================================== 收尾与总装


# 天明上色：(遮罩, 颜色, 浓度)。淡彩罩在墨上：保留墨的浓淡，只把色相推过去（颜色回到画里）
DAWN_COLORS = (
    ("far_hill", mixc(HUAQING, DAN, 0.35), 0.32),
    ("mid_hill", mixc(mixc(SHILV, HUAQING, 0.5), DAN, 0.3), 0.32),
    ("bamboo_far", mixc(mixc(HUAQING, SHILV, 0.55), DAN, 0.25), 0.35),
    ("bamboo_mid", mixc(SHILV, HUAQING, 0.2), 0.5),
    ("bamboo_fore", SHILV, 0.6),
    ("ground", mixc(mixc(SHILV, ZHESHI, 0.45), DAN, 0.2), 0.32),
    ("village", DAWN_WARM, 0.14),
)


def colorize(rgb: np.ndarray, mask: np.ndarray, color, k: float) -> np.ndarray:
    """在遮罩里把颜色推向 color 的色相，亮度不变（淡彩：墨的浓淡还在）。"""
    lum = rgb.mean(-1, keepdims=True)
    target = lum * (np.asarray(color) / np.mean(color))
    a = (k * np.clip(mask, 0, 1))[..., None]
    return rgb * (1 - a) + np.clip(target, 0, 1) * a


def finish(P: Scroll, paper0: np.ndarray) -> np.ndarray:
    """长夜：画 × 灰阶光照（灯边、狐火边、月下亮，其余沉下去）。天明：淡彩上色 + 东边暖光 + 青火的辉光。
    最后纸纹在暗处也看得见，四边微微压暗（老纸的边）。"""
    out = P.rgb.copy()
    if P.dawn:
        for key, color, k in DAWN_COLORS:
            out = colorize(out, blur(P.masks[key], 1.5), color, k)
        warm = smoothstep(700, 2400, P.X) ** 1.3
        out = out * (1.0 + 0.10 * warm[..., None] * (mixc(DAWN_WARM, WHITE, 0.4) / np.mean(mixc(DAWN_WARM, WHITE, 0.4)) - 1.0) + 0.04 * warm[..., None])
        out = out + P.emit + 0.6 * T.bloom(P.emit, 18.0)
    else:
        out = out * np.clip(P.light, 0, 1.04)[..., None]
    rel = paper0.mean(-1) / paper0.mean()
    rel = rel - blur(rel, 40.0) / blur(np.ones_like(rel), 40.0) + 1.0
    lum = out.mean(-1, keepdims=True)
    gain = 1.2 + 1.6 * (1 - smoothstep(0.08, 0.6, lum))
    out = out * (1 + gain * (rel[..., None] - 1))
    rx = (P.X - W / 2) / (W / 2)
    ry = (P.Y - H / 2) / (H / 2)
    vig = 1 - 0.10 * smoothstep(0.75, 1.05, np.maximum(np.abs(rx) * 0.92, np.abs(ry)))
    return np.clip(out * vig[..., None], 0, 1)


def put_seal(img: Image.Image) -> Image.Image:
    """左下角一方朱砂印“青丘”（白文，title_screen.make_seal）。"""
    seal = T.make_seal("青丘", SEAL_PX, np.random.default_rng(SEED + 99))
    im = img.convert("RGBA")
    im.alpha_composite(seal, SEAL_AT)
    return im.convert("RGB")


def paint(dawn: bool, paper: np.ndarray) -> Image.Image:
    rng = np.random.default_rng(SEED)
    P = Scroll(rng, dawn, paper)
    with canvas_size():
        paint_sky(P, rng)
        paint_hills(P, rng)
        paint_far_bamboo(P, rng)
        lanterns = paint_village(P, rng)
        paint_mid_bamboo(P, rng)
        paint_fog_band(P, rng, 0, 0.45, span=(640, 720))
        paint_fore_bamboo(P, rng)
        paint_lanterns(P, lanterns, rng)
        paint_wisps(P, rng)
        paint_foreground(P, rng)
    out = finish(P, paper)
    img = Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB")
    return put_seal(img)


# ============================================================== 审图


def review(night: Image.Image, dawn: Image.Image, path: Path) -> None:
    """两张缩到 1280 宽，左上角按游戏的样子写模拟旁白（思源宋体 500）：长夜纸色字 + 淡淡的暗影，天明墨色字。"""
    k = 1280 / W
    rows = []
    fsz = 22
    f = font("serif", fsz, weight=500)
    lab = font("serif", 15, weight=500)
    for img, is_dawn in ((night, False), (dawn, True)):
        im = img.resize((1280, round(H * k)), Image.LANCZOS).convert("RGBA")
        txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(txt)
        x0, y0 = round(TEXT_BOX[0] * k) + 30, round(TEXT_BOX[1] * k) + 26
        fill = S.hex_to_rgb(S.INK["jiao"]) + (235,) if is_dawn else S.hex_to_rgb(S.PAPER) + (245,)
        for i, line in enumerate(NARRATION):
            dr.text((x0, y0 + i * round(fsz * 1.75)), line, font=f, fill=fill)
        if not is_dawn:
            sh = txt.split()[3].filter(ImageFilter.GaussianBlur(3))
            shadow = Image.new("RGBA", im.size, (8, 9, 14, 0))
            shadow.putalpha(sh.point(lambda v: int(v * 0.7)))
            im.alpha_composite(shadow)
        im.alpha_composite(txt)
        # 旁白区的框（虚线，只在审图上）
        box = [round(v * k) for v in TEXT_BOX]
        bd = ImageDraw.Draw(im)
        for xx in range(box[0], box[2], 12):
            bd.line([(xx, box[1]), (xx + 5, box[1])], fill=(200, 60, 60, 160))
            bd.line([(xx, box[3]), (xx + 5, box[3])], fill=(200, 60, 60, 160))
        for yy in range(box[1], box[3], 12):
            bd.line([(box[0], yy), (box[0], yy + 5)], fill=(200, 60, 60, 160))
            bd.line([(box[2], yy), (box[2], yy + 5)], fill=(200, 60, 60, 160))
        rows.append((im.convert("RGB"), "长夜（只有墨）" if not is_dawn else "天明（颜色回来）"))
    gap, top = 14, 30
    out = Image.new("RGB", (1280, sum(r.height + top for r, _ in rows) + gap), (26, 26, 28))
    y = 0
    d = ImageDraw.Draw(out)
    for im, t in rows:
        d.text((8, y + 6), f"scroll_qingqiu — {t}，1280 宽（原图 2400×800），红虚线框 = 旁白区", font=lab, fill=(220, 220, 220))
        out.paste(im, (0, y + top))
        y += im.height + top + gap // 2
    out.save(path, optimize=True)


def main() -> int:
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    paper = paper_wide(np.random.default_rng(SEED - 1))
    night = paint(False, paper)
    t1 = time.perf_counter()
    dawn = paint(True, paper)
    t2 = time.perf_counter()
    night.save(OUT / "scroll_qingqiu.png", optimize=True)
    dawn.save(OUT / "scroll_qingqiu_dawn.png", optimize=True)
    review(night, dawn, REVIEW / "scroll_qingqiu_review.png")
    print(f"[scroll] 长夜 {t1 - t0:.1f}s，天明 {t2 - t1:.1f}s → {OUT / 'scroll_qingqiu.png'}、{OUT / 'scroll_qingqiu_dawn.png'}")
    print(f"[review] → {REVIEW / 'scroll_qingqiu_review.png'}，共 {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
