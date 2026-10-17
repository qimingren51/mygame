#!/usr/bin/env python3
"""提灯夜行 · “月夜”改版的候选贴图与模拟画面（只用 Pillow + numpy，不用 Blender）。

第 1 轮试玩：“地图感觉有一层雾一样看不清”，用户选了“整体调亮，像月夜，暗处也能看清”（docs/PLAYTEST.md 第 2 项）。
质感会话去掉全屏薄雾、把夜色基调提到月光蓝；美术出下面这些候选。**不替换正式产物**（assets/、art/out/assets@2x/ 都不动）。

  1. 灯光池 vfx/light 的候选 light_a / light_b / light_c：中间一大片平的亮区，外圈平滑收到 0。
     白色、alpha 是形状；尺寸（2 倍 256²）、锚点（中心）、蓝噪声抖动、“半径处恰为 0”都和 vfx_textures.make_light() 一样。
       a：质感会话给的参数：r ≤ 0.4 平的 1.0，0.4–1.0 半个余弦收到 0，最外 3% 再羽化
       b：平台更宽、边收得更快：r ≤ 0.5 平，0.5–0.95 五次平滑（膝部二阶导也连续，不出马赫带）
       c：亮区略小，外面拖一圈很淡的晕：0.85 ×（0.40–0.82 五次平滑）+ 0.15 ×（0.45–1.0 五次平滑）
  2. 宣纸 paper.png 的候选 paper_a / paper_b：1024² RGB，四边无缝；亮度标准差 0.035–0.045（现在约 0.013）；
     三档层次：细纤维（2–6 像素，方向随机）与长丝；淡墨晕斑（直径 40–120 像素）与发灰的洇痕；一两处折痕、水渍。
     整体均值和现在的 assets/atlas/paper.png 逐通道相同（差不到 0.05/255），地面亮度不漂。
  3. 地面装饰调浓：草、落叶、卵石、青丘的落竹叶、苔点、狐爪印，目标是对纸面的 L* 反差 +12%
     （按游戏里平铺装饰的平均 alpha 0.725 算：先加 alpha，满了再按比例压暗颜色，最多压到线性亮度的 70%，色相不变）。
     近焦墨的笔画在游戏里 alpha ≤ 0.9 时已经到顶，所以实际 +6%–11%；报告里另算了“不换贴图、把 ground.rs 的 alpha 区间
     整体放大”的效果。墨晕（wash、qq_wash）只评估，不出候选。
  4. 1920×1080 的模拟游戏画面（view_height 420，1 世界单位 = 2.571 像素）：纸纹平铺 + 地面装饰 + 图集里裁出的主角、妖物 +
     光照。全部在线性空间：光照图 = 环境色 + 灯光（半分辨率、8 位 sRGB 存），乘到画面上；自发光（×1.5）叠在上面。
     没有模拟辉光、暗角、粒子、萤火。

固定 2 倍密度（桌面版）。贴图的随机数都是固定种子，重复运行逐字节相同；约 1 分钟。

输出：
  art/out/moon/        light_{a,b,c}.png + light_{a,b,c}_curve.png、paper_{a,b}.png + paper_{a,b}_tile2x2.png、
                       ground/<帧名>.png（调浓的候选）+ ground_compare.png、preview_<组合>.png（1920×1080）、
                       moon_report.json（曲线采样、标准差、反差等数值）
  art/out/review@2x/   moon_compare.png（现状 vs 新组合）、moon_light_curves.png（新旧衰减曲线）

用法（仓库根目录）：
  art/.venv/bin/python art/post/moon_textures.py
  art/.venv/bin/python art/post/test_moon_textures.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"  # 桌面版图集的密度：4 像素 / 世界单位

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402

S = V.S
assert V.D == 2, "moon_textures 只出 2 倍（桌面版）的候选"
ROOT = V.ART.parent
ATLAS = ROOT / "assets" / "atlas"
OUT = V.OUT / "moon"
OUT_GROUND = OUT / "ground"
REVIEW = V.REVIEW_DIR  # art/out/review@2x
PPU = float(S.PX_PER_UNIT)  # 4 像素 / 世界单位
smoothstep = V.smoothstep


# ============================================================== 颜色


def to_lin(c):
    """sRGB（0..1）→ 线性。"""
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def lin(h: str) -> np.ndarray:
    return to_lin(V.col(h))


LUMA = np.array([0.299, 0.587, 0.114])  # sRGB 值上的亮度（和 test_vfx_textures.lum 一样）；宣纸的标准差按它、按 0..1 算
Y709 = np.array([0.2126, 0.7152, 0.0722])  # 线性光的亮度 Y


def lstar(Y):
    Y = np.asarray(Y, dtype=np.float64)
    return np.where(Y > 216 / 24389, 116 * np.cbrt(Y) - 16, Y * 24389 / 27)


def save(img: Image.Image, path: Path) -> None:
    """所有 PNG 都从这里写（测试会包住 V.save_png，核对只写了自己的目录）。"""
    V.save_png(img, path)


@lru_cache(maxsize=32)
def font(size: int):
    """检查图的字：先找无衬线的中文字体，没有就用美术管线缓存的思源宋体，再没有就用默认字体（中文会缺字）。"""
    for p in (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), V.OUT / "fonts" / "NotoSerifSC-VF.ttf"):
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                pass
    return V.font(size)


# ============================================================== 1. 灯光池

LIGHT_SIZE = V.dpx(128)  # 256²，和现在的 vfx/light 一样
LIGHT_R = 200.0  # 主角灯光的半径（世界单位，actors.rs LANTERN_LIGHT）


def raised_cos(r, r0, r1):
    """r ≤ r0 为 1，r ≥ r1 为 0，中间半个余弦：两端一阶导为 0（C1）。"""
    t = np.clip((r - r0) / (r1 - r0), 0.0, 1.0)
    return 0.5 + 0.5 * np.cos(np.pi * t)


def smoother(r, r0, r1):
    """r ≤ r0 为 1，r ≥ r1 为 0，中间五次 smootherstep：两端一阶、二阶导都为 0（C2，膝部不出马赫带）。"""
    t = np.clip((r - r0) / (r1 - r0), 0.0, 1.0)
    return 1.0 - t * t * t * (t * (6.0 * t - 15.0) + 10.0)


def curve_old(r):
    """现在的 vfx/light（vfx_textures.make_light）：(1-d²)² × 中心亮斑。"""
    return V.bump_window(r) * (0.62 + 0.38 * np.exp(-((r / 0.30) ** 2)))


def curve_a(r):
    return raised_cos(r, 0.40, 1.00) * smoothstep(1.0, 0.97, r)


def curve_b(r):
    return smoother(r, 0.50, 0.95)


def curve_c(r):
    return 0.85 * smoother(r, 0.40, 0.82) + 0.15 * smoother(r, 0.45, 1.00)


CURVES = {"old": curve_old, "a": curve_a, "b": curve_b, "c": curve_c}
LIGHTS = {
    # 名字: (抖动种子, 说明)
    "a": (7101, "质感会话的参数：r ≤ 0.4 平的 1.0，0.4–1.0 半个余弦，最外 3% 再羽化"),
    "b": (7102, "平台更宽、边收得更快：r ≤ 0.5 平，0.5–0.95 五次平滑"),
    "c": (7103, "亮区略小，外面拖一圈很淡的晕：0.85×(0.40–0.82) + 0.15×(0.45–1.0)"),
}


def make_light(key: str) -> tuple[Image.Image, np.ndarray]:
    """一张候选灯光池：白色 RGB，alpha = 曲线，±0.5 LSB 蓝噪声抖动；半径处（含最外一圈像素）严格为 0。"""
    seed, _ = LIGHTS[key]
    d = V.radial_d(LIGHT_SIZE)
    f = CURVES[key](d)
    a8 = V.dither_alpha(f, np.random.default_rng(seed))
    a8[d >= 1.0 - 0.5 / (LIGHT_SIZE / 2)] = 0
    return V.to_rgba8(V.WHITE, None, a8), f


def level_radius(curve, level: float) -> float:
    """曲线第一次降到 level 以下的半径（r/R）。"""
    r = np.linspace(0.0, 1.0, 20001)
    below = np.nonzero(curve(r) < level)[0]
    return float(r[below[0]]) if len(below) else 1.0


def ring_profile(a8: np.ndarray) -> np.ndarray:
    """按 1 像素宽的环取 alpha 的平均（0..255），下标是半径像素。"""
    n = a8.shape[0]
    d = V.radial_d(n)
    r_px = np.floor(d * n / 2).astype(int)
    return np.array([a8[r_px == r].mean() for r in range(n // 2)])


def light_info(key: str, a8: np.ndarray | None = None) -> dict:
    c = CURVES[key]
    samples = {f"{r:.2f}": round(float(c(np.array(r))), 4) for r in np.round(np.arange(0.0, 1.0001, 0.05), 2)}
    info = {
        "samples_r_over_R": samples,
        "r_at_0.9": round(level_radius(c, 0.9), 3),
        "r_at_0.5": round(level_radius(c, 0.5), 3),
        "r_at_0.1": round(level_radius(c, 0.1), 3),
    }
    info["units_at_0.9_0.5_0.1"] = [round(info[k] * LIGHT_R, 1) for k in ("r_at_0.9", "r_at_0.5", "r_at_0.1")]
    info["edge_width_0.9_to_0.1"] = round(info["r_at_0.1"] - info["r_at_0.9"], 3)
    r = np.linspace(0, 1, 4001)
    info["max_slope_per_R"] = round(float(np.abs(np.diff(c(r))).max() / (r[1] - r[0])), 3)
    if a8 is not None:
        prof = ring_profile(a8)
        info["max_ring_rise_lsb"] = round(float(np.diff(prof).max()), 3)
    if key in LIGHTS:
        info["seed"], info["note"] = LIGHTS[key]
    return info


# ============================================================== 2. 宣纸

PAPER_SIZE = V.dpx(512)  # 1024²
LIGHT_PAPER = "#F8F2E4"  # 纸上亮的纤维（vfx_textures.make_paper 的亮纸色）


def current_paper() -> np.ndarray:
    """现在游戏里的宣纸（只读）。"""
    return np.asarray(Image.open(ATLAS / "paper.png").convert("RGB"), dtype=np.float64)


def unit_dir(target: str) -> np.ndarray:
    """从 PAPER 指向 target 的颜色方向，归一到“亮度变化 1”（0..1 sRGB，LUMA）。正值朝 target 走。"""
    d = V.col(target) - V.col(S.PAPER)
    return d / abs(float(d @ LUMA))


DIR_SHADE = unit_dir(S.PAPER_SHADOW)  # 纸纹暗部、纸浆厚处、潮线（偏暖黄）
DIR_LIGHT = unit_dir(LIGHT_PAPER)  # 半透明的白丝、水洗过的纸
DIR_INK = unit_dir(S.INK["dan"])  # 淡墨晕、洇痕（发灰）


def torus_window(n: int, cx: float, cy: float, half: int):
    """周期画布上以 (cx, cy) 为中心、边长 2·half 的窗口：返回 (行下标, 列下标, X, Y)。X、Y 不取模，和 cx、cy 同一坐标系。"""
    ys = np.arange(int(cy) - half, int(cy) + half)
    xs = np.arange(int(cx) - half, int(cx) + half)
    X, Y = np.meshgrid(xs + 0.5, ys + 0.5)
    return ys % n, xs % n, X, Y


def cloud_noise(rng, n: int, sigmas, weights, cut: float, warp=(16.0, 12.0)) -> np.ndarray:
    """纸浆的云絮：几层尺度相接的周期噪声（宽频，不会只剩一种大小的斑，看着像迷彩），坐标轻轻扭一下（絮状），
    再去掉比 cut 更大的起伏（一张纸里有很多小团、没有一眼记得住的大块，平铺 256 单位一格时看不出重复），
    最后只压尾巴（超过约 2.2σ 的才收，没有一块特别亮或特别暗的）。标准差归一为 1。"""
    wx = warp[1] * V.noise(rng, (n, n), warp[0])
    wy = warp[1] * V.noise(rng, (n, n), warp[0])
    f = sum(w * V.noise(rng, (n, n), s) for s, w in zip(sigmas, weights))
    f = V.wrap_sample(f, wx, wy)
    f = f - V.fft_blur(f, cut, wrap=True)
    f = f / f.std()
    f = f / np.sqrt(1.0 + (f / 2.2) ** 2)
    return f / f.std()


def strands(rng, n: int, count: int, length, amp, width: float, curl: float) -> np.ndarray:
    """一批纤维（向量化，几万根也快）：长 length 像素、方向随机、带一点弯（curl：每像素转角，弧度），两端渐隐，
    线芯强度≈amp。双线性撒点到周期画布上再按 width 模糊，四边接得上。"""
    L = rng.uniform(*length, count)
    th0 = rng.uniform(0, 2 * math.pi, count)
    k1 = rng.normal(0, curl, count)
    k2 = rng.normal(0, curl * 0.02, count)  # 弯度沿纤维再变一点（长丝不是正圆弧）
    x0, y0 = rng.uniform(0, n, count), rng.uniform(0, n, count)
    a = rng.uniform(*amp, count)
    freq, phase = rng.uniform(3, 9, count), rng.uniform(0, 2 * math.pi, count)
    m = max(12, int(math.ceil(length[1] / 0.5)) + 1)  # 采样间距不超过半个像素
    s = np.linspace(-0.5, 0.5, m)[None, :] * L[:, None]
    th = th0[:, None] + k1[:, None] * s + k2[:, None] * s * s
    ds = (L / (m - 1))[:, None]
    dx, dy = np.cos(th) * ds, np.sin(th) * ds
    xs = x0[:, None] + np.cumsum(dx, 1) - 0.5 * dx.sum(1, keepdims=True)
    ys = y0[:, None] + np.cumsum(dy, 1) - 0.5 * dy.sum(1, keepdims=True)
    t = np.linspace(0, 1, m)[None, :]
    prof = np.sin(np.pi * t) ** 0.6 * (0.75 + 0.25 * np.cos(t * freq[:, None] + phase[:, None]))
    w = a[:, None] * prof * math.sqrt(2 * math.pi) * width * ds
    acc = np.zeros((n, n))
    V.splat_lines(acc, xs.ravel() - 0.5, ys.ravel() - 0.5, w.ravel())
    return V.fft_blur(acc, width, wrap=True)


def blotches(rng, n: int, count: int, dia, amp, rim_frac: float, rim_amp) -> np.ndarray:
    """淡墨晕斑：count 团，直径 dia 像素，形状不规则、中间略浓、边柔；一部分边上带一圈干后的洇痕（细的深边，断断续续）。
    位置按抖动网格撒开，四个象限都有，平铺时不会一团独大。周期边界。"""
    out = np.zeros((n, n))
    wx = 5.0 * V.noise(rng, (n, n), 9.0)  # 边缘扭曲（像素）
    wy = 5.0 * V.noise(rng, (n, n), 9.0)
    tex = V.noise(rng, (n, n), 5.0)  # 晕里的浓淡
    brk = V.noise(rng, (n, n), 7.0)  # 洇痕的断续
    k = int(math.ceil(math.sqrt(count)))
    for c in rng.permutation(k * k)[:count]:
        cx = (c % k + rng.uniform(0.15, 0.85)) * n / k
        cy = (c // k + rng.uniform(0.15, 0.85)) * n / k
        R = 0.5 * rng.uniform(*dia)
        ex, ang = rng.uniform(0.72, 1.3), rng.uniform(0, math.pi)
        a0, rim, ra = rng.uniform(*amp), rng.random() < rim_frac, rng.uniform(*rim_amp)
        iy, ix, X, Y = torus_window(n, cx, cy, int(R * 1.6) + 8)
        sub = np.ix_(iy, ix)
        dx, dy = X + wx[sub] - cx, Y + wy[sub] - cy
        ca, sa = math.cos(ang), math.sin(ang)
        u, v = (dx * ca + dy * sa) / (R * ex), (-dx * sa + dy * ca) / (R / ex)
        rr = np.hypot(u, v)
        rr = rr / (1.0 + V.angular_noise(rng, np.arctan2(v, u), harmonics=(2, 3, 4, 6), amp=0.14))
        val = a0 * smoothstep(1.0, 0.15, rr) ** 1.4 * (0.8 + 0.2 * tex[sub])
        if rim:
            val += ra * np.exp(-((((rr - 0.96) * R) / 2.0) ** 2)) * smoothstep(-0.9, 0.6, brk[sub])
        out[sub] += val
    return out


def stain(rng, n: int, cx: float, cy: float, R: float, inner: float) -> tuple[np.ndarray, np.ndarray]:
    """水渍：一圈不规则、时断时续的潮线（干后积下的细深边），里侧再一道更淡的；里面略亮（inner>0）或略暗（inner<0）。
    返回 (暗场, 亮场)，峰值约 1。周期边界。"""
    dark, light = np.zeros((n, n)), np.zeros((n, n))
    iy, ix, X, Y = torus_window(n, cx, cy, int(R * 1.5) + 10)
    sub = np.ix_(iy, ix)
    dx, dy = X - cx, Y - cy
    th = np.arctan2(dy, dx)
    rr = np.hypot(dx, dy * rng.uniform(1.1, 1.35)) / R
    rr = rr / (1.0 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 5, 7, 9), amp=0.16))
    w = 2.0 / R  # 潮线宽约 2 像素
    brk = smoothstep(-0.2, 0.9, 0.6 + V.angular_noise(rng, th, harmonics=(1, 2, 3, 5), amp=0.9))  # 断续
    brk2 = smoothstep(0.0, 1.0, 0.4 + V.angular_noise(rng, th, harmonics=(1, 2, 4), amp=1.0))
    line = np.exp(-(((rr - 1.0) / w) ** 2)) * (0.25 + 0.75 * brk)
    line += 0.4 * np.exp(-(((rr - 0.84) / (1.2 * w)) ** 2)) * brk2
    body = smoothstep(1.0, 0.9, rr)
    dark[sub] += line
    if inner >= 0:
        light[sub] += inner * body
    else:
        dark[sub] += -inner * body
    return dark, light


def crease(rng, n: int, p0, p1, bend: float) -> tuple[np.ndarray, np.ndarray]:
    """折痕：一道微弯的线，一侧细深（谷里的影）、一侧细亮（脊上的光），沿线时断时续，两端渐隐。返回 (暗场, 亮场)，峰值约 1。"""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    t_dir = (p1 - p0) / np.linalg.norm(p1 - p0)
    mid = 0.5 * (p0 + p1) + np.array([-t_dir[1], t_dir[0]]) * bend
    pts = V.bezier([p0, mid, p1], 800)
    pts = V.arc_resample(pts, int(np.hypot(*np.diff(pts, axis=0).T).sum() / 0.5))
    tan = np.gradient(pts, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    t = np.linspace(0, 1, len(pts))
    wob = V.fft_blur(rng.standard_normal(len(pts))[None, :], (40, 0), wrap=True)[0]
    prof = np.sin(np.pi * t) ** 0.7 * (0.35 + 0.65 * smoothstep(-0.6, 0.8, wob / wob.std()))
    step, sig = 0.5, 0.8
    out = []
    for off, s, wgt in ((0.9, sig, 1.0), (-1.0, sig, 1.0), (3.5, 3.0, 0.22)):
        acc = np.zeros((n, n))
        p = pts + nrm * off
        V.splat_lines(acc, p[:, 0] - 0.5, p[:, 1] - 0.5, prof * wgt * math.sqrt(2 * math.pi) * s * step)
        out.append(V.fft_blur(acc, s, wrap=True))
    return out[0] + out[2], out[1]


def specks(rng, n: int, count: int) -> np.ndarray:
    """零星杂质：小深点和短草屑（峰值约 1）。"""
    acc = np.zeros((n, n))
    xs, ys = rng.uniform(0, n, count), rng.uniform(0, n, count)
    V.splat_lines(acc, xs, ys, rng.uniform(0.6, 1.0, count) * 2 * math.pi * 1.0**2)
    dots = V.fft_blur(acc, 1.0, wrap=True)
    bits = strands(rng, n, max(count // 2, 1), (5, 12), (0.6, 1.0), 0.9, 0.08)
    return dots + bits


# 纤维档内部的配比：(层名, 根数, 长度 px, 线芯强度, 粗细 σ px, 弯度 rad/px, 颜色方向)。整档最后归一到 PAPERS 的 fibre
FIBRE_MIX = [
    ("fuzz_dark", 120000, (2, 6), (0.010, 0.024), 0.75, 0.05, DIR_SHADE),  # 2–6 px 的毛，铺满纸面
    ("fuzz_light", 100000, (2, 6), (0.010, 0.022), 0.8, 0.05, DIR_LIGHT),
    ("fibre_dark", 14000, (8, 28), (0.010, 0.022), 0.8, 0.03, DIR_SHADE),  # 中等纤维
    ("fibre_light", 9000, (8, 28), (0.008, 0.018), 0.85, 0.03, DIR_LIGHT),
    ("silk_light", 420, (40, 150), (0.012, 0.024), 0.85, 0.006, DIR_LIGHT),  # 略带长丝
    ("silk_dark", 200, (30, 120), (0.012, 0.026), 0.8, 0.007, DIR_SHADE),
]
GRAIN = 0.006  # 纸粒（σ 1 px）在纤维档里的份量

PAPERS = {
    # fibre、cloud：这两档最后的亮度标准差（0..1 sRGB）；稀疏的东西（墨晕斑、水渍、折痕、杂质）直接给峰值强度。
    # blot = (团数, 直径 px, 浓度, 带洇痕的比例, 洇痕浓度)；stains = (中心 x, y（占纸宽）, 半径 px, 里面亮(+)/暗(-))；
    # creases = (起点, 终点（占纸宽）, 弯 px)。最后整体再微调到 std（只差几个百分点），均值对齐现在的纸
    "a": dict(
        seed=7201, std=0.040, note="生宣：纤维为主，云絮淡，墨晕少；一处水渍、一道短折痕",
        fibre=0.030, cloud=0.020, cloud_sigmas=(3.5, 8.0, 16.0, 28.0), cloud_cut=70.0,
        blot=(10, (40, 120), (0.014, 0.030), 0.4, (0.012, 0.024)),
        stains=[(0.27, 0.66, 70.0, 0.25)], creases=[((0.52, 0.10), (0.80, 0.40), 26.0)],
        stain_amp=0.045, crease_amp=0.040, specks=(10, 0.06),
    ),
    "b": dict(
        seed=7202, std=0.044, note="旧纸：云絮浓、墨晕与洇痕多；两处水渍、一道长折痕",
        fibre=0.027, cloud=0.028, cloud_sigmas=(4.0, 9.0, 18.0, 30.0), cloud_cut=74.0,
        blot=(16, (40, 120), (0.018, 0.038), 0.6, (0.014, 0.030)),
        stains=[(0.70, 0.24, 62.0, -0.3), (0.18, 0.72, 84.0, 0.3)], creases=[((0.08, 0.30), (0.62, 0.52), -40.0)],
        stain_amp=0.050, crease_amp=0.040, specks=(14, 0.07),
    ),
}
TIERS = {  # 报告里的分档
    "fibre": "细纤维与长丝（2–6 px 的毛、8–28 px 纤维、40–150 px 长丝、纸粒）",
    "cloud": "云絮（纸浆厚薄，约 20–150 px）",
    "blotch": "淡墨晕斑与洇痕（直径 40–120 px，发灰）",
    "marks": "水渍、折痕、杂质",
}


def paper_layers(key: str) -> dict[str, np.ndarray]:
    """候选宣纸的四档，各是一个 RGB 偏移场（0..1 sRGB，叠在纸色上）。"""
    P = PAPERS[key]
    rng = np.random.default_rng(P["seed"])
    n = PAPER_SIZE
    sh = (n, n)
    # ---- 细纤维与长丝：方向随机，暗的（纸浆厚、纤维重叠）和亮的（半透明的白丝）都有
    fib = sum(strands(rng, n, cnt, ln, amp, wd, cu)[..., None] * d for _, cnt, ln, amp, wd, cu, d in FIBRE_MIX)
    fib = fib + (GRAIN * V.noise(rng, sh, 1.0))[..., None] * DIR_SHADE
    fib = fib - fib.reshape(-1, 3).mean(0)
    fib *= P["fibre"] / float((fib @ LUMA).std())
    # ---- 云絮：宽频、絮状，加一层 3–8 px 的细絮（tanh 压成一小团一小团）
    c = cloud_noise(rng, n, P["cloud_sigmas"], (0.2, 0.35, 0.5, 0.5), P["cloud_cut"])
    fl = V.wrap_sample(V.noise(rng, sh, 2.5) + 0.8 * V.noise(rng, sh, 5.0) + 0.5 * V.noise(rng, sh, 9.0),
                       4.0 * V.noise(rng, sh, 8.0), 4.0 * V.noise(rng, sh, 8.0))
    cl = c + 0.45 * np.tanh(1.2 * fl / fl.std())
    cloud = (cl / cl.std())[..., None] * DIR_SHADE
    cloud *= P["cloud"] / float((cloud @ LUMA).std())
    # ---- 淡墨晕斑与洇痕（几处，发灰）
    cnt, dia, ba, rf, rim = P["blot"]
    blot = blotches(rng, n, cnt, dia, ba, rf, rim)[..., None] * DIR_INK
    # ---- 水渍、折痕、杂质
    marks = np.zeros((n, n, 3))
    for fx, fy, R, inner in P["stains"]:
        d_, l_ = stain(rng, n, fx * n, fy * n, R, inner)
        marks += P["stain_amp"] * (d_[..., None] * DIR_SHADE + l_[..., None] * DIR_LIGHT)
    for p0, p1, bend in P["creases"]:
        d_, l_ = crease(rng, n, np.array(p0) * n, np.array(p1) * n, bend)
        marks += P["crease_amp"] * (d_[..., None] * DIR_SHADE + 0.8 * l_[..., None] * DIR_LIGHT)
    cnt, a = P["specks"]
    marks += (a * specks(rng, n, cnt))[..., None] * DIR_SHADE
    return {"fibre": fib, "cloud": cloud, "blotch": blot, "marks": marks}


def shoulder(v, knee: float = 248.0, top: float = 255.45):
    """亮部软肩：超过 knee 的平滑压到 top 以下（纸色离白只有十几级，亮纤维不能顶到 255 被削平）。knee 处一阶导连续。"""
    return np.where(v > knee, knee + (top - knee) * np.tanh((v - knee) / (top - knee)), v)


def make_paper(key: str) -> tuple[Image.Image, dict]:
    """候选宣纸：四档叠到纸色上，过亮部软肩；整体增益和偏移迭代几次，使取整后的亮度标准差 = 目标、
    逐通道均值 = 现在的 paper.png。"""
    P = PAPERS[key]
    L = paper_layers(key)
    dev = sum(L.values())
    dev = dev - dev.reshape(-1, 3).mean(0)
    target = current_paper().reshape(-1, 3).mean(0)
    gain, off = P["std"] / float((dev @ LUMA).std()), np.zeros(3)
    for _ in range(8):
        q = np.clip(np.round(shoulder(target + off + 255.0 * gain * dev)), 0, 255)
        gain *= P["std"] / float((q @ LUMA).std() / 255.0)
        off += target - q.reshape(-1, 3).mean(0)
    rgb8 = np.clip(np.round(shoulder(target + off + 255.0 * gain * dev)), 0, 255).astype(np.uint8)
    tiers = {TIERS[k]: round(float((gain * v @ LUMA).std()), 4) for k, v in L.items()}
    info = {"seed": P["seed"], "note": P["note"], "gain": round(gain, 3), "tier_luma_std": tiers}
    return Image.fromarray(rgb8, "RGB"), info


def paper_stats(rgb8: np.ndarray) -> dict:
    a = rgb8.astype(np.float64)
    luma = a @ LUMA / 255.0
    ylin = to_lin(a / 255.0) @ Y709
    n = a.shape[0]
    F = np.abs(np.fft.fft2(luma - luma.mean())) ** 2
    k = np.fft.fftfreq(n) * n
    kk = np.hypot(k[:, None], k[None, :])
    h = n // 2
    quads = [luma[:h, :h].mean(), luma[:h, h:].mean(), luma[h:, :h].mean(), luma[h:, h:].mean()]
    lp = V.fft_blur(luma - luma.mean(), 24.0, wrap=True)
    return {
        "mean_rgb": [round(float(x), 3) for x in a.reshape(-1, 3).mean(0)],
        "luma_std": round(float(luma.std()), 4),
        "lstar_std_over_100": round(float(lstar(ylin).std() / 100.0), 4),
        "linear_Y_rel_std": round(float(ylin.std() / ylin.mean()), 4),
        "per_channel_std": [round(float(x), 4) for x in (a / 255.0).reshape(-1, 3).std(0)],
        "lowfreq_share_lambda_ge_256px": round(float(F[(kk > 0) & (kk <= n / 256)].sum() / F.sum()), 4),
        "quadrant_luma_spread": round(float(max(quads) - min(quads)), 4),
        "max_blob_over_std_sigma24": round(float(np.abs(lp).max() / lp.std()), 2),
        "luma_p0_5_p99_5": [round(float(np.percentile(luma, 0.5)), 4), round(float(np.percentile(luma, 99.5)), 4)],
    }


# ============================================================== 3. 地面装饰调浓

DECOR_BOOST = 0.12
DECOR_ALPHA_MEAN = 0.725  # ground.rs：平铺装饰的 alpha 在 0.55–0.9 之间随机
DECOR_DARK_MIN = 0.7  # 颜色最多压到原来线性亮度的 70%（sRGB 约暗 14%）：本来就近焦墨的笔画不再往黑里压
BOOST_FRAMES = [*(f"grass_{i}" for i in range(4)), "leaves_0", "leaves_1", "pebbles_0", "pebbles_1",
                *(f"qq_bamboo_leaves_{i}" for i in range(3)), "qq_moss_0", "qq_moss_1", "qq_fox_tracks"]
WASH_FRAMES = ["wash_0", "wash_1", "wash_2", "qq_wash_0", "qq_wash_1"]


@lru_cache(maxsize=8)
def atlas(name: str) -> tuple[dict, np.ndarray]:
    j = json.loads((ATLAS / f"{name}.json").read_text(encoding="utf-8"))
    page = np.asarray(Image.open(ATLAS / j["meta"]["image"]).convert("RGBA"))
    return j, page


def atlas_frame(name: str, key: str) -> tuple[Image.Image, tuple[float, float]]:
    """从图集裁出一帧，按 spriteSourceSize 还原到原画布（裁掉的边补全透明）。返回 (图, 锚点 0..1)。"""
    j, page = atlas(name)
    f = j["frames"][key]
    r, s, src = f["frame"], f["spriteSourceSize"], f["sourceSize"]
    can = np.zeros((src["h"], src["w"], 4), np.uint8)
    can[s["y"] : s["y"] + s["h"], s["x"] : s["x"] + s["w"]] = page[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]]
    return Image.fromarray(can, "RGBA"), (f["anchor"]["x"], f["anchor"]["y"])


def paper_ref_lin() -> np.ndarray:
    return to_lin(current_paper().reshape(-1, 3).mean(0) / 255.0)


def decor_dl(c_lin, a, p_lin, m=DECOR_ALPHA_MEAN):
    """装饰（线性色 c、alpha a × 游戏里的 m）叠在纸色 p 上，与纸的 L* 差（正 = 比纸暗）。"""
    comp = (a * m)[..., None] * c_lin + (1.0 - a * m)[..., None] * p_lin
    return lstar(p_lin @ Y709) - lstar(comp @ Y709)


def bisect(fn, lo, hi, it=26):
    """逐像素二分：fn(x) 随 x 单调增，找 fn(x)=0。lo、hi 是数组。"""
    for _ in range(it):
        mid = 0.5 * (lo + hi)
        up = fn(mid) > 0
        hi = np.where(up, mid, hi)
        lo = np.where(up, lo, mid)
    return 0.5 * (lo + hi)


def boost_decor(img: Image.Image, k: float = DECOR_BOOST) -> Image.Image:
    """把装饰对纸面的 L* 反差放大 1+k 倍：先加 alpha（墨更多），alpha 满了再按比例压暗颜色（线性光里等比，色相不变），
    最多压到 DECOR_DARK_MIN（近焦墨的笔画在游戏里 alpha ≤ 0.9 时本来就到顶了，够不着就停在那儿）。
    全透明的像素（含往外扩的颜色）不动。"""
    arr = np.asarray(img.convert("RGBA"))
    a = arr[..., 3].astype(np.float64) / 255.0
    c = to_lin(arr[..., :3] / 255.0)
    p = paper_ref_lin()
    m = a > 0
    cm, am = c[m], a[m]
    dl0 = decor_dl(cm, am, p)
    goal = (1.0 + k) * np.abs(dl0)
    # 1) 只加 alpha
    a1 = bisect(lambda x: np.abs(decor_dl(cm, x, p)) - goal, am.copy(), np.ones_like(am))
    reach = np.abs(decor_dl(cm, np.ones_like(am), p)) >= goal
    a1 = np.where(reach, a1, 1.0)
    # 2) alpha 满了还不够（只对比纸暗的颜色）：颜色按比例压暗
    need = ~reach & (dl0 > 0)
    s = np.ones_like(am)
    if need.any():
        cn, gn = cm[need], goal[need]
        s[need] = bisect(lambda x: gn - decor_dl(cn * x[:, None], np.ones(len(cn)), p), np.full(len(cn), DECOR_DARK_MIN), np.ones(len(cn)))
    out = arr.copy()
    a8 = np.maximum(np.round(a1 * 255.0), arr[..., 3][m]).astype(np.uint8)
    out[..., 3][m] = a8
    dark = s < 1.0
    rgb = out[..., :3][m]
    rgb[dark] = np.clip(np.round(to_srgb(cm[dark] * s[dark, None]) * 255.0), 0, 255).astype(np.uint8)
    out[..., :3][m] = rgb
    return Image.fromarray(out, "RGBA")


def decor_contrast(img: Image.Image, ambient: str | None = None, m: float = DECOR_ALPHA_MEAN) -> dict:
    """装饰在纸上的 L* 反差（按 alpha 加权的平均、第 90 百分位）。ambient 给出时整片乘环境色（月下、灯照不到的地方）；
    m 是游戏里乘上的 alpha。"""
    arr = np.asarray(img.convert("RGBA"))
    a = arr[..., 3].astype(np.float64) / 255.0
    sel = a > 0.03
    c = to_lin(arr[..., :3][sel] / 255.0)
    p = paper_ref_lin()
    k = lin(ambient) if ambient else np.ones(3)
    w = np.minimum(a[sel] * m, 1.0)
    comp = w[:, None] * c + (1.0 - w[:, None]) * p
    dl = lstar((p * k) @ Y709) - lstar((comp * k) @ Y709)
    return {"mean": round(float((dl * a[sel]).sum() / a[sel].sum()), 2), "p90": round(float(np.percentile(dl, 90)), 2)}


# ============================================================== 4. 模拟画面

VIEW_H = 420.0  # assets/data/run.ron 的 view_height
SW, SH = 1920, 1080
K = SH / VIEW_H  # 2.571 像素 / 世界单位
EMIT_HDR = 1.5  # lighting.rs
AMB_NOW = S.NIGHT_AMBIENT  # #161B2C
AMB_MOON = ("#4A5578", "#5A6688")
TINT_NOW = S.mix(S.LANTERN_LIGHT, "#FF9A4A", 0.45)  # 现在：红纸灯的光色按 45% 混进 LANTERN_LIGHT → #FFB064（actors.rs）
TINT_NEW = "#FFE0B0"
FOG_NOW = ("#DDD9CF", 0.05)  # 现在的全屏薄雾（近白，正常混合，画在暗层之上）
PAPER_ORIGIN = (311.0, 187.0)  # 预览里宣纸平铺的起点（纹素），接缝不压在主角身上

# 模拟坐标（x 向右、y 向下，世界单位，镜头中心为原点；主角站在镜头中心）
HERO_POS = (0.0, 12.0)
ENEMIES = [  # (帧, x, y, 说明)
    ("shade/float_E_00", 62.0, -82.0, "灯下"),
    ("shade/float_E_03", 125.0, 72.0, "灯边"),
    ("shade/float_E_05", -168.0, -100.0, "灯边"),
    ("golem/move_E_00", -238.0, 58.0, "月下"),
    ("fox/move_E_00", 250.0, 128.0, "月下"),
    ("shade/float_E_06", 288.0, -128.0, "月下"),
    ("shade/float_E_02", -322.0, -46.0, "月下"),
]
UPRIGHT = [("actors", "rock_b/idle_S_00", -300.0, -168.0), ("ground", "ground/bamboo_0", 335.0, -8.0),
           ("ground", "ground/qq_shoots_0", -120.0, 182.0), ("ground", "ground/reed_1", 180.0, -182.0)]
FLAT_COUNTS = {  # 一屏（约 1.2 个 512 单位的块）里的数量，按 ground.rs 的密度
    "grass": 12, "wash": 1, "qq_wash": 1, "leaves": 1, "pebbles": 1, "qq_bamboo_leaves": 5, "qq_moss": 2, "qq_fox_tracks": 1,
}
FLAT_FRAMES = {
    "grass": [f"grass_{i}" for i in range(4)], "wash": ["wash_0", "wash_2"], "qq_wash": ["qq_wash_0", "qq_wash_1"],
    "leaves": ["leaves_0", "leaves_1"], "pebbles": ["pebbles_0", "pebbles_1"], "qq_bamboo_leaves": [f"qq_bamboo_leaves_{i}" for i in range(3)],
    "qq_moss": ["qq_moss_0", "qq_moss_1"], "qq_fox_tracks": ["qq_fox_tracks"],
}


def flat_layout() -> list[tuple[str, float, float, float, bool]]:
    """地面装饰的摆放（固定种子）：(帧名, x, y, alpha, 镜像)。墨晕铺在最底下。"""
    rng = np.random.default_rng(7301)
    items = []
    for kind, n in FLAT_COUNTS.items():
        frames = FLAT_FRAMES[kind]
        for i in range(n):
            x, y = rng.uniform(-360, 360), rng.uniform(-200, 200)
            items.append((frames[i % len(frames)], float(x), float(y), float(rng.uniform(0.55, 0.9)), bool(rng.random() < 0.5)))
    items.sort(key=lambda t: 0 if "wash" in t[0] else 1)
    return items


def premul(img: Image.Image, tint=None) -> np.ndarray:
    """RGBA8（sRGB、直通 alpha）→ 线性、预乘 alpha 的 float32（GPU 读 sRGB 贴图先解码再插值）。"""
    arr = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    rgb = to_lin(arr[..., :3]) * (np.asarray(tint) if tint is not None else 1.0)
    return np.dstack([rgb * arr[..., 3:4], arr[..., 3:4]]).astype(np.float32)


def blit(canvas: np.ndarray, pm: np.ndarray, x: float, y: float, anchor, scale: float, *, flip=False, mode="over", gain=1.0, mask=None):
    """像 GPU 那样双线性采样（不做 mip）把精灵画到画布上：(x, y) 是锚点的画面像素，scale = 画面像素 / 贴图像素。
    over 是预乘 alpha 的正常混合，add 是叠加（乘 gain）。mask 给出时记下这张精灵的 alpha（量妖物的反差用）。"""
    h, w = pm.shape[:2]
    x0, y0 = x - anchor[0] * w * scale, y - anchor[1] * h * scale
    ix0, ix1 = max(int(math.floor(x0)), 0), min(int(math.ceil(x0 + w * scale)), canvas.shape[1])
    iy0, iy1 = max(int(math.floor(y0)), 0), min(int(math.ceil(y0 + h * scale)), canvas.shape[0])
    if ix0 >= ix1 or iy0 >= iy1:
        return
    u = (np.arange(ix0, ix1) + 0.5 - x0) / scale - 0.5
    v = (np.arange(iy0, iy1) + 0.5 - y0) / scale - 0.5
    if flip:
        u = (w - 1) - u
    pmp = np.pad(pm, ((1, 1), (1, 1), (0, 0)))
    u, v = np.clip(u + 1, 0, w + 0.999), np.clip(v + 1, 0, h + 0.999)
    j0, i0 = np.floor(u).astype(int), np.floor(v).astype(int)
    j1, i1 = np.minimum(j0 + 1, w + 1), np.minimum(i0 + 1, h + 1)
    fu, fv = (u - j0)[None, :, None], (v - i0)[:, None, None]
    A, B = pmp[i0], pmp[i1]
    s = (A[:, j0] * (1 - fu) + A[:, j1] * fu) * (1 - fv) + (B[:, j0] * (1 - fu) + B[:, j1] * fu) * fv
    reg = canvas[iy0:iy1, ix0:ix1]
    if mode == "add":
        reg += s[..., :3] * gain
    else:
        reg[:] = s[..., :3] + reg * (1.0 - s[..., 3:4])
    if mask is not None:
        mask[iy0:iy1, ix0:ix1] = np.maximum(mask[iy0:iy1, ix0:ix1], s[..., 3])


def to_screen(x: float, y: float) -> tuple[float, float]:
    return SW / 2 + x * K, SH / 2 + y * K


def paper_layer(paper: np.ndarray) -> np.ndarray:
    """平铺的宣纸（双线性、环绕），1 纹素 = 0.25 世界单位。"""
    tex = to_lin(paper.astype(np.float64) / 255.0).astype(np.float32)
    n = tex.shape[0]
    tx = ((np.arange(SW) + 0.5 - SW / 2) / K) * PPU + PAPER_ORIGIN[0] - 0.5
    ty = ((np.arange(SH) + 0.5 - SH / 2) / K) * PPU + PAPER_ORIGIN[1] - 0.5
    j0, i0 = np.floor(tx).astype(int), np.floor(ty).astype(int)
    fu, fv = (tx - j0)[None, :, None], (ty - i0)[:, None, None]
    j0, j1, i0, i1 = j0 % n, (j0 + 1) % n, i0 % n, (i0 + 1) % n
    A, B = tex[i0], tex[i1]
    return ((A[:, j0] * (1 - fu) + A[:, j1] * fu) * (1 - fv) + (B[:, j0] * (1 - fu) + B[:, j1] * fu) * fv).astype(np.float32)


def asset_meta(asset: str) -> dict:
    j, _ = atlas("actors")
    return j["meta"]["lantern"]["assets"][asset]


@lru_cache(maxsize=1)
def scene_sprites() -> dict:
    """预览里要用的图集帧（只读）。"""
    sp = {}
    keys = {("actors", "hero/idle_S_00"), ("lanterns", "lantern_red/idle_S_00"), ("lanterns", "lantern_red/idle_S_00_emit"),
            ("vfx", "vfx/shadow"), ("vfx", "vfx/light")}
    for f, *_ in ENEMIES:
        keys |= {("actors", f), ("actors", f + "_emit")}
    for a, f, *_ in UPRIGHT:
        keys.add((a, f))
    for a, f in keys:
        sp[f] = atlas_frame(a, f)
    for name in {n for v in FLAT_FRAMES.values() for n in v} | set(WASH_FRAMES) | set(BOOST_FRAMES):
        sp[f"ground/{name}"] = atlas_frame("ground", f"ground/{name}")
    return sp


def render(paper: np.ndarray, light: Image.Image, ambient: str, tint: str, decor: dict[str, Image.Image] | None = None,
           fog=None, want_masks: bool = False):
    """合成一帧 1920×1080 的近似游戏画面，返回 (sRGB8 图, 辅助数据)。decor：要替换的地面装饰帧（调浓的候选）。"""
    sp = scene_sprites()
    decor = decor or {}
    sc = K / PPU  # 画面像素 / 图集像素
    img = paper_layer(paper)
    # 影子（图层 SHADOW=9，在地面装饰 GROUND=10 下面）
    shadow, s_anc = sp["vfx/shadow"]
    spm = premul(shadow)
    hero_r = asset_meta("hero").get("shadow_radius_px", 24)
    shadows = [(HERO_POS, hero_r, 0.8)]
    for f, x, y, _ in ENEMIES:
        m = asset_meta(f.split("/")[0])
        shadows.append(((x, y), m.get("shadow_radius_px", 24), 0.42 if m.get("floating") else 0.62))
    for (x, y), r_px, al in shadows:
        blit(img, spm * al, *to_screen(x, y), s_anc, sc * (2 * r_px) / shadow.width)
    for _, f, x, y in UPRIGHT:  # ground.rs ground_shadows：脚底半径 = 宽 × 0.3（5–24 单位），alpha 0.55
        foot = min(max(sp[f][0].width / PPU * 0.3, 5.0), 24.0)
        blit(img, spm * 0.55, *to_screen(x, y), s_anc, 2 * foot * K / shadow.width)
    # 地面装饰（平铺，alpha 0.55–0.9）
    for name, x, y, al, flip in flat_layout():
        im, anc = sp[f"ground/{name}"]
        im = decor.get(name, im)
        blit(img, premul(im) * al, *to_screen(x, y), anc, sc, flip=flip)
    # 立着的东西、妖物、主角：按脚底 y 排序
    masks = {}
    items = [(y, "up", (a, f, x, y)) for a, f, x, y in UPRIGHT]
    items += [(y, "enemy", (f, x, y, note)) for f, x, y, note in ENEMIES]
    items.append((HERO_POS[1], "hero", None))
    for _, kind, it in sorted(items, key=lambda t: t[0]):
        if kind == "up":
            _, f, x, y = it
            im, anc = sp[f]
            blit(img, premul(im), *to_screen(x, y), anc, sc)
        elif kind == "enemy":
            f, x, y, note = it
            im, anc = sp[f]
            mk = np.zeros((SH, SW), np.float32) if want_masks else None
            blit(img, premul(im), *to_screen(x, y), anc, sc, flip=x > HERO_POS[0], mask=mk)
            if want_masks:
                masks[(f, x, y, note)] = mk
        else:
            for f in ("hero/idle_S_00", "lantern_red/idle_S_00"):
                im, anc = sp[f]
                blit(img, premul(im), *to_screen(*HERO_POS), anc, sc)
    # 光照图：半分辨率，底色 = 环境色，灯光叠加（线性），存成 8 位 sRGB；再双线性放大乘到画面上
    sx, sy = asset_meta("hero")["sockets"]["lantern"]["idle"]["S"][0]
    lamp = (HERO_POS[0] + sx / PPU, HERO_POS[1] + sy / PPU)
    lm = np.broadcast_to(lin(ambient).astype(np.float32), (SH // 2, SW // 2, 3)).copy()
    lpm = premul(light, tint=lin(tint))
    lx, ly = to_screen(*lamp)
    blit(lm, lpm, lx / 2, ly / 2, (0.5, 0.5), (2 * LIGHT_R * K / 2) / light.width, mode="add")
    lm8 = np.round(to_srgb(np.clip(lm, 0, 1)) * 255.0)
    lmq = to_lin(lm8 / 255.0).astype(np.float32)
    gx = np.clip((np.arange(SW) + 0.5) / 2 - 0.5, 0, SW // 2 - 1)
    gy = np.clip((np.arange(SH) + 0.5) / 2 - 0.5, 0, SH // 2 - 1)
    j0, i0 = np.floor(gx).astype(int), np.floor(gy).astype(int)
    j1, i1 = np.minimum(j0 + 1, SW // 2 - 1), np.minimum(i0 + 1, SH // 2 - 1)
    fu, fv = (gx - j0)[None, :, None], (gy - i0)[:, None, None]
    lm_full = (lmq[i0][:, j0] * (1 - fu) + lmq[i0][:, j1] * fu) * (1 - fv) + (lmq[i1][:, j0] * (1 - fu) + lmq[i1][:, j1] * fu) * fv
    img *= lm_full
    # 现在的全屏薄雾（画在暗层之上、正常混合）
    if fog is not None:
        img = img * (1.0 - fog[1]) + lin(fog[0]).astype(np.float32) * fog[1]
    # 自发光：妖眼、灯笼窗（叠加 × EMIT_HDR），灯笼周围一小团暖光晕（仍用旧 light，见报告）
    for f, x, y, _ in ENEMIES:
        im, anc = sp[f + "_emit"]
        blit(img, premul(im), *to_screen(x, y), anc, sc, flip=x > HERO_POS[0], mode="add", gain=EMIT_HDR)
    im, anc = sp["lantern_red/idle_S_00_emit"]
    blit(img, premul(im), *to_screen(*HERO_POS), anc, sc, mode="add", gain=EMIT_HDR)
    old_light, _ = sp["vfx/light"]
    blit(img, premul(old_light, tint=lin("#FFC773")) * 0.22, *to_screen(*lamp), (0.5, 0.5), (2 * 14.0 * K) / old_light.width, mode="add", gain=EMIT_HDR)
    out = np.round(to_srgb(np.clip(img, 0, 1)) * 255.0).astype(np.uint8)
    return out, {"lamp": lamp, "masks": masks, "lightmap8": lm8}


def scene_metrics(out: np.ndarray, aux: dict) -> dict:
    """画面上的几个数：灯下、灯边、月下的地面亮度（sRGB 亮度 0..255 的中位数），以及每只妖物和周围地面的 L* 差。"""
    Y = to_lin(out / 255.0) @ Y709
    L = lstar(Y)
    luma = out.astype(np.float64) @ LUMA
    lx, ly = to_screen(*aux["lamp"])
    yy, xx = np.mgrid[0:SH, 0:SW]
    r = np.hypot(xx + 0.5 - lx, yy + 0.5 - ly) / K
    occupied = np.zeros((SH, SW), bool)
    for mk in aux["masks"].values():
        occupied |= mk > 0.02
    ground = ~occupied
    zones = {"灯下 r<60": r < 60, "灯边 r=140–170": (r > 140) & (r < 170), "月下 r>260": r > 260}
    m = {"ground_luma_median": {k: round(float(np.median(luma[z & ground])), 1) for k, z in zones.items()}}
    foes = {}
    for (f, x, y, note), mk in aux["masks"].items():
        body = mk > 0.6
        ys, xs = np.nonzero(body)
        if len(ys) == 0:
            continue
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        pad = 12
        ring = np.zeros_like(body)
        ring[max(y0 - pad, 0) : y1 + pad, max(x0 - pad, 0) : x1 + pad] = True
        ring &= ground
        foes[f"{f.split('/')[0]}@({x:.0f},{y:.0f}) {note}"] = round(float(np.median(L[ring]) - np.median(L[body])), 1)
    m["enemy_vs_ground_dL"] = foes
    return m


# ============================================================== 检查图


def label_bar(w: int, h: int, text: str, sub: str = "", bg=(24, 24, 26)) -> Image.Image:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.text((12, 6), text, fill=(240, 239, 236), font=font(22))
    if sub:
        d.text((12, 6 + 26), sub, fill=(195, 194, 183), font=font(16))
    return im


def downsample2(rgb8: np.ndarray) -> np.ndarray:
    """2×2 平均（线性光里）缩小一半。"""
    l = to_lin(rgb8 / 255.0)
    h, w = l.shape[0] // 2, l.shape[1] // 2
    l = l[: 2 * h, : 2 * w].reshape(h, 2, w, 2, 3).mean((1, 3))
    return np.round(to_srgb(l) * 255.0).astype(np.uint8)


# 画图：浅色底、细线、发丝网格（dataviz 规范；颜色按固定顺序：蓝、橙、青绿，旧的用灰）
C_SURF, C_INK, C_INK2, C_MUTED, C_GRID, C_AXIS = "#FCFCFB", "#0B0B0B", "#52514E", "#898781", "#E1E0D9", "#C3C2B7"
SERIES = {"old": C_MUTED, "a": "#2A78D6", "b": "#EB6834", "c": "#1BAF7A"}


class Plot:
    """在 PIL 画布上画折线图（先 3 倍大画、再缩小，线条抗锯齿）。"""

    SS = 3

    def __init__(self, w, h, box, xr, yr):
        self.w, self.h = w, h
        self.im = Image.new("RGB", (w * self.SS, h * self.SS), C_SURF)
        self.d = ImageDraw.Draw(self.im)
        self.box, self.xr, self.yr = box, xr, yr  # box = (左, 上, 右, 下)，画面像素

    def p(self, x, y):
        l, t, r, b = self.box
        X = l + (x - self.xr[0]) / (self.xr[1] - self.xr[0]) * (r - l)
        Y = b - (y - self.yr[0]) / (self.yr[1] - self.yr[0]) * (b - t)
        return X * self.SS, Y * self.SS

    def axes(self, xticks, yticks, xfmt="{:g}", yfmt="{:g}", xlabel="", ylabel=""):
        l, t, r, b = self.box
        f = font(15 * self.SS)
        for v in yticks:
            X0, Y = self.p(self.xr[0], v)
            X1, _ = self.p(self.xr[1], v)
            self.d.line([(X0, Y), (X1, Y)], fill=C_GRID, width=self.SS)
            s = yfmt.format(v)
            tw = self.d.textlength(s, font=f)
            self.d.text((X0 - tw - 8 * self.SS, Y - 9 * self.SS), s, fill=C_MUTED, font=f)
        for v in xticks:
            X, Y0 = self.p(v, self.yr[0])
            self.d.line([(X, Y0), (X, Y0 + 5 * self.SS)], fill=C_AXIS, width=self.SS)
            s = xfmt.format(v)
            tw = self.d.textlength(s, font=f)
            self.d.text((X - tw / 2, Y0 + 8 * self.SS), s, fill=C_MUTED, font=f)
        self.d.line([self.p(self.xr[0], self.yr[0]), self.p(self.xr[1], self.yr[0])], fill=C_AXIS, width=self.SS)
        if xlabel:
            tw = self.d.textlength(xlabel, font=f)
            self.d.text((((l + r) / 2) * self.SS - tw / 2, (b + 30) * self.SS), xlabel, fill=C_INK2, font=f)
        if ylabel:
            self.d.text((l * self.SS, (t - 26) * self.SS), ylabel, fill=C_INK2, font=f)

    def vline(self, x, text=""):
        X, Y0 = self.p(x, self.yr[0])
        _, Y1 = self.p(x, self.yr[1])
        self.d.line([(X, Y0), (X, Y1)], fill=C_AXIS, width=self.SS)
        if text:
            self.d.text((X + 6 * self.SS, Y1 + 2 * self.SS), text, fill=C_MUTED, font=font(14 * self.SS))

    def line(self, xs, ys, color, width=2.5, dash=None):
        pts = [self.p(x, y) for x, y in zip(xs, ys)]
        wpx = int(round(width * self.SS))
        if not dash:
            self.d.line(pts, fill=color, width=wpx, joint="curve")
            return
        on, off = dash[0] * self.SS, dash[1] * self.SS
        acc, draw, seg = 0.0, True, [pts[0]]
        for a, b in zip(pts, pts[1:]):
            seg.append(b)
            acc += math.dist(a, b)
            if acc >= (on if draw else off):
                if draw:
                    self.d.line(seg, fill=color, width=wpx, joint="curve")
                seg, acc, draw = [b], 0.0, not draw
        if draw and len(seg) > 1:
            self.d.line(seg, fill=color, width=wpx, joint="curve")

    def dot(self, x, y, color, r=4.5):
        X, Y = self.p(x, y)
        R = r * self.SS
        self.d.ellipse([X - R - 2 * self.SS, Y - R - 2 * self.SS, X + R + 2 * self.SS, Y + R + 2 * self.SS], fill=C_SURF)
        self.d.ellipse([X - R, Y - R, X + R, Y + R], fill=color)

    def text(self, x, y, s, color=C_INK2, size=15, px=False):
        X, Y = (x * self.SS, y * self.SS) if px else self.p(x, y)
        self.d.text((X, Y), s, fill=color, font=font(size * self.SS))

    def swatch(self, x, y, color, dash=False):
        """图例的小线段（画面像素坐标）。"""
        X, Y = x * self.SS, y * self.SS
        if dash:
            for k in range(3):
                self.d.line([(X + k * 10 * self.SS, Y), (X + (k * 10 + 6) * self.SS, Y)], fill=color, width=int(2.5 * self.SS))
        else:
            self.d.line([(X, Y), (X + 26 * self.SS, Y)], fill=color, width=int(2.5 * self.SS))

    def image(self) -> Image.Image:
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def lit_luma_profile(curve, ambient: str, tint: str, fog=None, dist=None) -> np.ndarray:
    """纸面（现在的平均纸色）离灯 dist 世界单位处的屏幕亮度（sRGB 亮度 0..255）：环境色 + 灯光 × 曲线，乘纸色，可加雾。"""
    p = paper_ref_lin()
    f = curve(np.clip(dist / LIGHT_R, 0, 1.2))
    lm = np.clip(lin(ambient)[None, :] + lin(tint)[None, :] * f[:, None], 0, 1)
    lm = to_lin(np.round(to_srgb(lm) * 255) / 255)
    c = p[None, :] * lm
    if fog is not None:
        c = c * (1 - fog[1]) + lin(fog[0]) * fog[1]
    return to_srgb(c) @ LUMA * 255.0


def curve_chart(keys, title: str, table: bool = True) -> Image.Image:
    """衰减曲线：alpha 对 r/R；右边一张关键半径的表（文字，曲线也有直接标注）。"""
    W_, H_ = 1500, 760
    pl = Plot(W_, H_, (90, 90, 980, 650), (0.0, 1.0), (0.0, 1.05))
    pl.axes([0, 0.2, 0.4, 0.6, 0.8, 1.0], [0, 0.25, 0.5, 0.75, 0.9, 1.0], xfmt="{:.1f}", yfmt="{:.2f}",
            xlabel="到灯心的距离 r / 光半径 R（主角 R = 200 世界单位，屏幕半高 210）", ylabel="灯光贴图的 alpha（光照图里 = 灯光强度）")
    r = np.linspace(0, 1, 801)
    for k in keys:
        pl.line(r, CURVES[k](r), SERIES[k], width=2.0 if k == "old" else 3.0, dash=(10, 7) if k == "old" else None)
    slot = {"old": 0.97, "a": 0.89, "b": 0.81, "c": 0.73}
    for k in keys:  # 直接标注：曲线降到 0.5 的点；几条在 0.6–0.8R 交叉，文字放到右上的空白处，细引线连过去
        r5 = level_radius(CURVES[k], 0.5)
        pl.d.line([pl.p(r5, 0.5), pl.p(0.685, slot[k] - 0.022)], fill=C_AXIS, width=pl.SS)
        pl.dot(r5, 0.5, SERIES[k])
        pl.dot(0.69, slot[k] - 0.022, SERIES[k], r=4.0)
        pl.text(0.705, slot[k], f"{'现在' if k == 'old' else 'light_' + k}：0.5 在 {r5:.2f}R（{r5 * LIGHT_R:.0f} 单位）", C_INK2, 15)
    for v in (0.25, 0.5, 0.75):
        if "old" in keys:
            pl.dot(v, float(curve_old(np.array(v))), SERIES["old"], r=3.5)
    pl.text(90, 24, title, C_INK, 22, px=True)
    # 图例
    lx, ly = 700, 64
    for i, k in enumerate(keys):
        pl.swatch(lx + i * 120, ly, SERIES[k], dash=(k == "old"))
        pl.text(lx + i * 120 + 32, ly - 10, "现在" if k == "old" else f"light_{k}", C_INK2, 15, px=True)
    if table:
        x0, y0 = 1020, 110
        pl.text(x0, y0 - 30, "左三列：降到该值的半径 r/R；右三列：该半径处的 alpha", C_INK, 15, px=True)
        rows = [("", ["≥0.9 到", "0.5 处", "0.1 处", "0.25R", "0.5R", "0.75R"])]
        for k in keys:
            c = CURVES[k]
            rows.append(("现在" if k == "old" else k, [f"{level_radius(c, 0.9):.2f}", f"{level_radius(c, 0.5):.2f}", f"{level_radius(c, 0.1):.2f}",
                                                     f"{float(c(np.array(0.25))):.2f}", f"{float(c(np.array(0.5))):.2f}", f"{float(c(np.array(0.75))):.2f}"]))
        for j, (name, cells) in enumerate(rows):
            yy = y0 + j * 34
            pl.text(x0, yy, name, C_INK2, 15, px=True)
            for i, cell in enumerate(cells):
                pl.text(x0 + 60 + i * 66, yy, cell, C_INK if j else C_MUTED, 15 if j else 13, px=True)
        yy = y0 + len(rows) * 34 + 18
        for k in keys:
            if k == "old":
                continue
            c = CURVES[k]
            u = [round(level_radius(c, v) * LIGHT_R) for v in (0.9, 0.5, 0.1)]
            pl.text(x0, yy, f"{k}：亮区 {u[0]}、半亮 {u[1]}、收尽 {u[2]} 单位", C_INK2, 14, px=True)
            yy += 26
        for k in keys:
            if k in LIGHTS:
                pl.text(x0, yy + 6, f"{k}：{LIGHTS[k][1]}"[:34], C_MUTED, 13, px=True)
                yy += 22
    return pl.image()


def small_lights_strip(lights: dict[str, Image.Image], paper: np.ndarray, ambient: str) -> Image.Image:
    """vfx/light 也是所有小光源的形状（魂火 24–36、火焰 64、狐灯 70 世界单位…）：同一张贴图画小光源时的样子。"""
    cell_w, cell_h = 330, 230
    keys = ["old", *lights]
    out = np.zeros((cell_h * 2 + 70, cell_w * len(keys), 3), np.uint8)
    tex = to_lin(paper[:cell_h, :cell_w] / 255.0)
    olds = scene_sprites()["vfx/light"][0]
    srcs = {"old": olds, **lights}
    for i, k in enumerate(keys):
        for j, (radius, tint, al) in enumerate(((30.0, "#BFEFFF", 0.5), (64.0, "#FFA860", 0.75))):
            lm = np.broadcast_to(lin(ambient), (cell_h, cell_w, 3)).copy()
            blit(lm, premul(srcs[k], tint=lin(tint)) * al, cell_w / 2, cell_h / 2, (0.5, 0.5), 2 * radius * K / srcs[k].width, mode="add")
            lm = to_lin(np.round(to_srgb(np.clip(lm, 0, 1)) * 255) / 255)
            px = np.round(to_srgb(tex * lm) * 255).astype(np.uint8)
            out[70 + j * cell_h : 70 + (j + 1) * cell_h, i * cell_w : (i + 1) * cell_w] = px
    im = Image.fromarray(out, "RGB")
    d = ImageDraw.Draw(im)
    d.text((10, 6), f"副作用：vfx/light 也是所有小光源的形状。上：魂火光（半径 30，#BFEFFF ×0.5），下：火焰光（半径 64，#FFA860 ×0.75），环境 {ambient}，1080p 原大", fill=(235, 235, 230), font=font(17))
    for i, k in enumerate(keys):
        d.text((i * cell_w + 10, 40), "现在的 light" if k == "old" else f"light_{k}", fill=(235, 235, 230), font=font(17))
    return im


def curves_review(lights: dict[str, Image.Image], paper: np.ndarray, path: Path) -> None:
    """moon_light_curves.png：上左 alpha 曲线（新旧），上右 地面亮度随离灯距离（各环境色），下 小光源的样子。"""
    a = curve_chart(["old", "a", "b", "c"], "灯光池 vfx/light：现在 vs 候选 a / b / c")
    b = profile_chart_image()
    strip = small_lights_strip(lights, paper, AMB_MOON[0])
    W_ = a.width + b.width
    out = Image.new("RGB", (W_, a.height + strip.height + 10), C_SURF)
    out.paste(a, (0, 0))
    out.paste(b, (a.width, 0))
    out.paste(strip, ((W_ - strip.width) // 2, a.height + 10))
    save(out, path)


def profile_chart_image() -> Image.Image:
    """地面亮度（屏幕 sRGB 亮度，现在的平均纸色）随离灯距离：现在（#161B2C、#FFB064、旧光、α0.05 雾）vs 候选。"""
    W_, H_ = 1100, 760
    pl = Plot(W_, H_, (90, 90, 1060, 650), (0.0, 400.0), (0.0, 255.0))
    pl.axes([0, 50, 100, 150, 200, 250, 300, 350, 400], [0, 50, 100, 150, 200, 250], xlabel="离灯心的距离（世界单位；屏幕半高 210、半宽 373）",
            ylabel="地面的屏幕亮度（sRGB 亮度 0–255）")
    pl.vline(210, "屏幕半高")
    pl.vline(373, "半宽")
    dist = np.linspace(0, 400, 801)
    pl.line(dist, lit_luma_profile(curve_old, AMB_NOW, TINT_NOW, FOG_NOW, dist), SERIES["old"], 2.5, dash=(10, 7))
    for k in ("a", "b", "c"):
        for amb, dash in zip(AMB_MOON, (None, (12, 6))):
            pl.line(dist, lit_luma_profile(CURVES[k], amb, TINT_NEW, None, dist), SERIES[k], 2.5, dash=dash)
    y_now = lit_luma_profile(curve_old, AMB_NOW, TINT_NOW, FOG_NOW, np.array([300.0]))[0]
    pl.text(300, y_now + 16, f"现在 {y_now:.0f}", C_INK2, 15)
    for amb in AMB_MOON:
        v = lit_luma_profile(curve_a, amb, TINT_NEW, None, np.array([300.0]))[0]
        pl.text(300, v + 16, f"{amb} 月下 {v:.0f}", C_INK2, 15)
    pl.text(90, 24, f"地面亮度：现在 vs 候选（灯色 {TINT_NEW}，实线 {AMB_MOON[0]}、虚线 {AMB_MOON[1]}）", C_INK, 22, px=True)
    lx, ly = 560, 64
    for i, k in enumerate(("old", "a", "b", "c")):
        pl.swatch(lx + i * 120, ly, SERIES[k], dash=(k == "old"))
        pl.text(lx + i * 120 + 32, ly - 10, "现在" if k == "old" else f"light_{k}", C_INK2, 15, px=True)
    return pl.image()


def ground_compare(boosted: dict[str, Image.Image], paper: np.ndarray, path: Path) -> None:
    """地面装饰调浓前后：每帧在纸上（alpha 0.725）原大摆两遍——灯下（环境 + 灯心）和月下（#4A5578）；左原图、右调浓。"""
    sp = scene_sprites()
    names = BOOST_FRAMES + WASH_FRAMES
    lamp = np.clip(lin(AMB_MOON[0]) + lin(TINT_NEW), 0, 1)
    moon = lin(AMB_MOON[0])
    cell_w, ch, pad = 330, 145, 10
    # 每行一帧，四格：灯下原、灯下调浓、月下原、月下调浓
    out = np.zeros((60 + len(names) * ch, 4 * cell_w + 3 * pad, 3), np.uint8)
    tex = to_lin(paper[:ch, :cell_w] / 255.0).astype(np.float32)
    for r_, name in enumerate(names):
        im0, _ = sp[f"ground/{name}"]
        im1 = boosted.get(name, im0)
        for j, (im, lm) in enumerate(((im0, lamp), (im1, lamp), (im0, moon), (im1, moon))):
            can = tex.copy()
            sc = min(1.0, 0.92 * cell_w / im.width, 0.85 * ch / im.height)
            blit(can, premul(im) * DECOR_ALPHA_MEAN, cell_w / 2, ch / 2, (0.5, 0.5), sc)
            px = np.round(to_srgb(can * lm.astype(np.float32)) * 255).astype(np.uint8)
            x0 = j * (cell_w + pad)
            out[60 + r_ * ch : 60 + (r_ + 1) * ch, x0 : x0 + cell_w] = px
    im = Image.fromarray(out, "RGB")
    d = ImageDraw.Draw(im)
    d.text((10, 8), f"地面装饰调浓（目标 L* 反差 +{DECOR_BOOST:.0%}，实际 +6%–11%；alpha {DECOR_ALPHA_MEAN}，原大 2 倍图集像素）：灯下原 | 灯下调浓 | 月下 {AMB_MOON[0]} 原 | 月下调浓。墨晕不调。",
           fill=(235, 235, 230), font=font(18))
    f = font(15)
    for r_, name in enumerate(names):
        tag = name + ("" if name in boosted else "（不调，左右相同）")
        x0, y0 = 6, 60 + r_ * ch + 4
        d.rectangle([x0 - 4, y0 - 2, x0 + d.textlength(tag, font=f) + 4, y0 + 19], fill=(24, 24, 26))
        d.text((x0, y0), tag, fill=(250, 250, 245), font=f)
    save(im, path)


# ============================================================== 主流程

PANELS = [
    # (键, 标题, 环境色, 灯光, 宣纸, 装饰调浓, 灯色, 雾)
    ("now", "现状", AMB_NOW, "old", "old", False, TINT_NOW, FOG_NOW),
    ("light_only", "只换光：#4A5578 + light_a（旧纸、旧装饰）", AMB_MOON[0], "a", "old", False, TINT_NEW, None),
    ("a_4A", "A：#4A5578 + light_a + paper_a + 装饰调浓", AMB_MOON[0], "a", "a", True, TINT_NEW, None),
    ("a_5A", "B：#5A6688 + light_a + paper_a + 装饰调浓", AMB_MOON[1], "a", "a", True, TINT_NEW, None),
    ("b_4A", "C：#4A5578 + light_b + paper_b + 装饰调浓", AMB_MOON[0], "b", "b", True, TINT_NEW, None),
    ("c_5A", "D：#5A6688 + light_c + paper_b + 装饰调浓", AMB_MOON[1], "c", "b", True, TINT_NEW, None),
]


def main() -> dict:
    t0 = time.perf_counter()
    for d in (OUT, OUT_GROUND, REVIEW):
        d.mkdir(parents=True, exist_ok=True)
    report: dict = {"generator": "art/post/moon_textures.py", "density": V.D, "px_per_unit": PPU}

    # 1. 灯光
    lights = {}
    report["lights"] = {"old": light_info("old")}
    for k in LIGHTS:
        img, _ = make_light(k)
        save(img, OUT / f"light_{k}.png")
        lights[k] = img
        report["lights"][k] = light_info(k, np.asarray(img)[..., 3].astype(np.float64))
        save(curve_chart(["old", k], f"light_{k} 的径向曲线（灰色虚线是现在的 vfx/light）"), OUT / f"light_{k}_curve.png")
    print(f"灯光候选 {list(lights)}  {time.perf_counter() - t0:.1f}s")

    # 2. 宣纸
    papers = {"old": current_paper().astype(np.uint8)}
    report["papers"] = {"old": paper_stats(papers["old"])}
    for k in PAPERS:
        img, info = make_paper(k)
        save(img, OUT / f"paper_{k}.png")
        arr = np.asarray(img)
        papers[k] = arr
        info.update(paper_stats(arr))
        info["png_kb"] = round((OUT / f"paper_{k}.png").stat().st_size / 1024, 1)
        report["papers"][k] = info
        n = arr.shape[0]
        tile = Image.new("RGB", (2 * n, 2 * n))
        for ox in (0, n):
            for oy in (0, n):
                tile.paste(img, (ox, oy))
        save(tile, OUT / f"paper_{k}_tile2x2.png")
        print(f"宣纸 paper_{k}：亮度标准差 {info['luma_std']:.4f}  均值 {info['mean_rgb']}  {time.perf_counter() - t0:.1f}s")
    report["papers"]["old"]["png_kb"] = round((ATLAS / "paper.png").stat().st_size / 1024, 1)

    # 3. 地面装饰
    sp = scene_sprites()
    boosted = {}
    report["decor"] = {"boost": DECOR_BOOST, "alpha_mean_in_game": DECOR_ALPHA_MEAN, "frames": {}}
    for name in BOOST_FRAMES + WASH_FRAMES:
        im0, _ = sp[f"ground/{name}"]
        entry = {"lit": decor_contrast(im0), "moon_4A5578": decor_contrast(im0, AMB_MOON[0]),
                 "moon_5A6688": decor_contrast(im0, AMB_MOON[1]), "now_161B2C": decor_contrast(im0, AMB_NOW)}
        if name in BOOST_FRAMES:
            im1 = boost_decor(im0)
            boosted[name] = im1
            save(im1, OUT_GROUND / f"{name}.png")
            entry["boosted"] = {"lit": decor_contrast(im1), "moon_4A5578": decor_contrast(im1, AMB_MOON[0]),
                                "moon_5A6688": decor_contrast(im1, AMB_MOON[1])}
            entry["boosted"]["ratio_mean"] = round(entry["boosted"]["lit"]["mean"] / max(entry["lit"]["mean"], 1e-6), 3)
        report["decor"]["frames"][name] = entry
    ground_compare(boosted, papers["a"], OUT / "ground_compare.png")
    # 另一条路：不换贴图，把 ground.rs 里平铺装饰的随机 alpha（0.55–0.9）整体乘 s，各帧反差变成几倍
    alt = {}
    for s in (1.04, 1.06, 1.08, 1.10):
        rs = [decor_contrast(sp[f"ground/{n}"][0], m=DECOR_ALPHA_MEAN * s)["mean"] / decor_contrast(sp[f"ground/{n}"][0])["mean"] for n in BOOST_FRAMES]
        alt[f"x{s:.2f}"] = {"alpha_range": [round(0.55 * s, 3), round(min(0.9 * s, 1.0), 3)],
                            "ratio_min_median_max": [round(min(rs), 3), round(float(np.median(rs)), 3), round(max(rs), 3)]}
    report["decor"]["in_game_alpha_scale"] = alt
    print(f"地面装饰调浓 {len(boosted)} 帧  {time.perf_counter() - t0:.1f}s")

    # 4. 模拟画面
    old_light = sp["vfx/light"][0]
    panels = {}
    report["previews"] = {}
    for key, title, amb, lk, pk, boost, tint, fog in PANELS:
        light = old_light if lk == "old" else lights[lk]
        out, aux = render(papers[pk], light, amb, tint, boosted if boost else None, fog, want_masks=True)
        save(Image.fromarray(out, "RGB"), OUT / f"preview_{key}.png")
        panels[key] = out
        report["previews"][key] = {"title": title, "ambient": amb, "light": lk, "paper": pk, "decor_boost": boost, "tint": tint,
                                   "fog": fog, **scene_metrics(out, aux)}
        print(f"预览 {key}  {time.perf_counter() - t0:.1f}s")
    compare_sheet(panels, REVIEW / "moon_compare.png")
    curves_review(lights, papers["a"], REVIEW / "moon_light_curves.png")

    (OUT / "moon_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成，用时 {time.perf_counter() - t0:.1f}s")
    return report


CROP = (1060, 560, 480, 270)  # 1:1 局部：灯边那只影妖、纸纹、几簇草（x, y, 宽, 高，画面像素）


def compare_sheet(panels: dict[str, np.ndarray], path: Path) -> None:
    """moon_compare.png：2 列 × 3 行（每格 1080p 缩小一半），最下面一行是 1:1 的局部。"""
    pw, ph, bar = SW // 2, SH // 2, 64
    head = 74
    crops = ["now", "a_4A", "a_5A", "c_5A"]
    crop_h = CROP[3] + bar
    out = Image.new("RGB", (2 * pw, head + 3 * (ph + bar) + crop_h), (24, 24, 26))
    d = ImageDraw.Draw(out)
    d.text((14, 10), "月夜改版：现状 vs 新组合（1920×1080 模拟画面缩小一半；线性空间：光照图 = 环境色 + 灯光，乘到画面上；不含辉光、暗角、粒子）",
           fill=(240, 239, 236), font=font(22))
    d.text((14, 42), f"现状 = {AMB_NOW} + 旧 light（灯色 {TINT_NOW}，红纸灯混色）+ 旧纸 + α0.05 的近白雾；新组合灯色 {TINT_NEW}、无雾；灯光半径 200 单位",
           fill=(195, 194, 183), font=font(17))
    for i, (key, title, amb, lk, pk, boost, tint, fog) in enumerate(PANELS):
        r, c = divmod(i, 2)
        x, y = c * pw, head + r * (ph + bar)
        sub = {"now": "夜色、旧光、旧纸、雾"}.get(key, f"灯光 light_{lk}，宣纸 {'旧' if pk == 'old' else 'paper_' + pk}，{'装饰调浓' if boost else '装饰原样'}")
        out.paste(label_bar(pw, bar, title, sub), (x, y))
        out.paste(Image.fromarray(downsample2(panels[key]), "RGB"), (x, y + bar))
    y = head + 3 * (ph + bar)
    cx, cy, cw, chh = CROP
    for i, key in enumerate(crops):
        _, title, amb, lk, pk, *_ = next(p for p in PANELS if p[0] == key)
        sub = "旧光、旧纸、雾" if key == "now" else f"{amb} · light_{lk} · paper_{pk}"
        out.paste(label_bar(cw, bar, "1:1 局部 · " + title.split("：")[0], sub), (i * cw, y))
        out.paste(Image.fromarray(panels[key][cy : cy + chh, cx : cx + cw], "RGB"), (i * cw, y + bar))
    save(out, path)


if __name__ == "__main__":
    main()
