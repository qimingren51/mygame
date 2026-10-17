#!/usr/bin/env python3
"""提灯夜行 · “月夜”改版的候选、对比与模拟画面（只用 Pillow + numpy，不用 Blender）。

第 1 轮试玩：“地图感觉有一层雾一样看不清”，用户选了“整体调亮，像月夜，暗处也能看清”（docs/PLAYTEST.md 第 2 项）。
采用的方案已经接进管线（vfx_textures.py 的“月夜”一节，只在 2 倍）：灯光池 vfx/light_pool（这里的 light_a）、
月夜版宣纸（paper_a）、地面装饰调浓。这个脚本只读管线的函数，不写 assets/、art/out/assets@2x/：

  1. 灯光池候选 light_a / light_b / light_c（白色、alpha 是形状，尺寸、锚点同 vfx/light）：
       a：采用（= vfx/light_pool）：r ≤ 0.4 平的 1.0，0.4–1.0 半个余弦，最外 3% 再羽化
       b：平台更宽、边收得更快：r ≤ 0.5 平，0.5–0.95 五次平滑（膝部二阶导也连续）
       c：亮区略小，外面拖一圈很淡的晕：0.85 ×（0.40–0.82 五次平滑）+ 0.15 ×（0.45–1.0 五次平滑）
  2. 宣纸候选 paper_a（采用 = 2 倍的 ground/paper）/ paper_b（云絮浓、墨晕多）：1024² RGB，四边无缝；
     亮度标准差 0.040 / 0.044（第一版约 0.013），逐通道均值和第一版相同。
  3. 地面装饰调浓的前后对比：原图从生成函数现画（不从图集读，图集里已经是调浓的），调浓 = vfx_textures.boost_decor。
  4. 1920×1080 的模拟游戏画面（view_height 420，1 世界单位 = 2.571 像素）：纸纹平铺 + 地面装饰 + 图集里裁出的主角、妖物 +
     光照。全部在线性空间：光照图 = 环境色 + 灯光（半分辨率、8 位 sRGB 存），乘到画面上；自发光（×1.5）叠在上面。
     “现状”= 夜色 #161B2C + vfx/light + 第一版宣纸 + 原样的装饰 + α0.05 的近白雾。没有模拟辉光、暗角、粒子、萤火。

固定 2 倍密度（桌面版）。贴图的随机数都是固定种子，重复运行逐字节相同；约 3 分钟。

输出：
  art/out/moon/        light_{a,b,c}.png + light_{a,b,c}_curve.png、paper_{a,b}.png + paper_{a,b}_tile2x2.png、
                       ground_compare.png、preview_<组合>.png（1920×1080）、moon_report.json（曲线采样、标准差、反差等数值）
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
import ground_decor as G  # noqa: E402

S = V.S
assert V.D == 2 and V.MOON, "moon_textures 只出 2 倍（桌面版）"
ROOT = V.ART.parent
ATLAS = ROOT / "assets" / "atlas"
OUT = V.OUT / "moon"
REVIEW = V.REVIEW_DIR  # art/out/review@2x
PPU = float(S.PX_PER_UNIT)  # 4 像素 / 世界单位
smoothstep = V.smoothstep
to_lin, to_srgb, lstar = V.srgb_to_lin, V.lin_to_srgb, V.lstar
LUMA, Y709 = V.LUMA, V.Y709


def lin(h: str) -> np.ndarray:
    return to_lin(V.col(h))


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

LIGHT_SIZE = V.dpx(128)  # 256²，和 vfx/light 一样
LIGHT_R = 200.0  # 主角灯光的半径（世界单位，actors.rs LANTERN_LIGHT）


def smoother(r, r0, r1):
    """r ≤ r0 为 1，r ≥ r1 为 0，中间五次 smootherstep：两端一阶、二阶导都为 0（C2，膝部不出马赫带）。"""
    t = np.clip((r - r0) / (r1 - r0), 0.0, 1.0)
    return 1.0 - t * t * t * (t * (6.0 * t - 15.0) + 10.0)


def curve_old(r):
    """vfx/light（vfx_textures.make_light，其余光源仍用它）：(1-d²)² × 中心亮斑。"""
    return V.bump_window(r) * (0.62 + 0.38 * np.exp(-((r / 0.30) ** 2)))


def curve_b(r):
    return smoother(r, 0.50, 0.95)


def curve_c(r):
    return 0.85 * smoother(r, 0.40, 0.82) + 0.15 * smoother(r, 0.45, 1.00)


curve_a = V.curve_light_pool  # 采用：vfx/light_pool
CURVES = {"old": curve_old, "a": curve_a, "b": curve_b, "c": curve_c}
LIGHTS = {
    # 名字: (抖动种子, 说明)
    "a": (V.LIGHT_POOL_SEED, "采用（vfx/light_pool）：r ≤ 0.4 平的 1.0，0.4–1.0 半个余弦，最外 3% 再羽化"),
    "b": (7102, "平台更宽、边收得更快：r ≤ 0.5 平，0.5–0.95 五次平滑"),
    "c": (7103, "亮区略小，外面拖一圈很淡的晕：0.85×(0.40–0.82) + 0.15×(0.45–1.0)"),
}


def make_light(key: str) -> tuple[Image.Image, np.ndarray]:
    """一张候选灯光池（light_a 和管线里的 vfx/light_pool 逐字节相同）。"""
    seed, _ = LIGHTS[key]
    return V.light_texture(CURVES[key], seed)


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
PAPERS = {
    "a": V.MOON_PAPER,  # 采用：2 倍的 ground/paper
    "b": dict(
        seed=7202, std=0.044, note="旧纸：云絮浓、墨晕与洇痕多；两处水渍、一道长折痕",
        fibre=0.027, cloud=0.028, cloud_sigmas=(4.0, 9.0, 18.0, 30.0), cloud_cut=74.0,
        blot=(16, (40, 120), (0.018, 0.038), 0.6, (0.014, 0.030)),
        stains=[(0.70, 0.24, 62.0, -0.3), (0.18, 0.72, 84.0, 0.3)], creases=[((0.08, 0.30), (0.62, 0.52), -40.0)],
        stain_amp=0.050, crease_amp=0.040, specks=(14, 0.07),
    ),
}
TIERS = {  # 报告里的分档（V.make_paper_moon 返回的键）
    "fibre": "细纤维与长丝（2–6 px 的毛、8–28 px 纤维、40–150 px 长丝、纸粒）",
    "cloud": "云絮（纸浆厚薄，约 20–150 px）",
    "blotch": "淡墨晕斑与洇痕（直径 40–120 px，发灰）",
    "marks": "水渍、折痕、杂质",
}


@lru_cache(maxsize=1)
def legacy_paper() -> np.ndarray:
    """第一版宣纸（2 倍，“现状”用）：V.make_paper_v1() 现画，不从图集读（图集里已经是月夜版）。"""
    return np.asarray(V.make_paper_v1().convert("RGB"), dtype=np.float64)


def make_paper(key: str) -> tuple[Image.Image, dict]:
    img, info = V.make_paper_moon(PAPERS[key])
    info["tier_luma_std"] = {TIERS[k]: v for k, v in info["tier_luma_std"].items()}
    return img, info


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

DECOR_BOOST, DECOR_ALPHA_MEAN, DECOR_DARK_MIN = V.DECOR_BOOST, V.DECOR_ALPHA_MEAN, V.DECOR_DARK_MIN
BOOST_FRAMES = list(V.MOON_BOOST_FRAMES)
WASH_FRAMES = ["wash_0", "wash_1", "wash_2", "qq_wash_0", "qq_wash_1"]
paper_ref_lin, boost_decor = V.paper_ref_lin, V.boost_decor


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


@lru_cache(maxsize=1)
def decor_before() -> dict[str, Image.Image]:
    """平铺地面装饰的原图（没调浓的，2 倍）：从生成函数现画，不从图集读（图集里的已经调浓）。约 1 分钟。"""
    out = {f"grass_{i}": V.make_grass(*spec) for i, spec in enumerate(V.GRASS_SPECS)}
    out.update({f"wash_{i}": V.make_wash(seed, lobes, ba, **kw) for i, (seed, lobes, ba, kw) in enumerate(V.WASHES)})
    out.update({f"leaves_{i}": G.make_leaves(s) for i, s in enumerate(G.LEAVES_SEEDS)})
    out.update({f"pebbles_{i}": G.make_pebbles(s) for i, s in enumerate(G.PEBBLES_SEEDS)})
    out.update({k: img for k, (img, _, _) in G.build_qq(boost=False).items()})
    return out


@lru_cache(maxsize=1)
def decor_after() -> dict[str, Image.Image]:
    """调浓后（和管线 2 倍产物逐字节相同），墨晕等不调的帧原样。"""
    before = decor_before()
    return {k: (boost_decor(v) if k in V.MOON_BOOST_FRAMES else v) for k, v in before.items()}


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


