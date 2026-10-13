"""青丘道具出图：竹丛（完整 / 砍倒）、狐仙祠、石狐、狐灯（模型在 models/qingqiu_props.py）。

渲法和 produce.py 的道具完全一样（pipeline.render_asset、PROP_ANCHOR、idle_S_00 一帧、_emit、挂点、meta），
只出桌面版密度：
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/props_qingqiu.py            # 全部 → out/assets@2x/<道具>/
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/props_qingqiu.py --sample   # 样张 → out/qq_props_sample@2x/
    ... --only fox_shrine,stone_fox   只重渲部分      ... --review   不渲染，只自检 + 重拼审图
审图 out/review@2x/qq_props_sample.png（每件道具在游戏大小和 3 倍下的白天、夜里，旁边放主角和石灯笼比大小；
夜里各自按挂点放自己的光），自检报告 out/review@2x/qq_check_report.json。
渲染时拿 bstyle 的渲染锁（render_asset 里），和其它出图脚本不会同时渲；EXR 中间文件放自己的 out/_tmp_qq/。
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from style import style as S  # noqa: E402
import check_asset as C  # noqa: E402
import contact_sheet as CS  # noqa: E402

D = S.DENSITY
OUT = ART / "out"
ASSETS = OUT / S.ASSETS_DIR_NAME
SAMPLE = OUT / f"qq_props_sample@{D:g}x"
REVIEW = OUT / f"review@{D:g}x"
TMP = OUT / "_tmp_qq"
ALL = ["bamboo_clump", "bamboo_clump_broken", "fox_shrine", "stone_fox", "fox_lanterns"]
QING_GLOW = "#8FE3C8"  # 与 models/qingqiu_props.QING_GLOW 相同（这里不 import 模型，免得审图也要 bpy）
# 建议的光半径（世界单位，写进 meta.light_radius_units；游戏里石灯笼的光是 120）
LIGHT_RADIUS_UNITS = {"fox_lanterns": 140, "fox_shrine": 90}  # 狐仙祠放大 1.3 倍后光也跟着大一点
STONE_LANTERN_UNITS = 120  # 审图按“石灯笼的火光半径 × 本道具 / 120”换算，和石灯笼放在一起比例对


def _common(name: str, frame_px: int, shadow_1x: float, extra: dict) -> dict:
    return {"name": name, "frame_px": frame_px,
            "meta": {"category": "prop", "region": "qingqiu", "shadow_radius_px": round(shadow_1x * D),
                     "anim_extra": {"idle": {"fps": 1}}, **extra}}


def specs() -> dict:
    """每件道具的渲染参数：帧尺寸、挂点、meta（同 produce.py 的道具写法）。"""
    import pipeline  # noqa: F401 - 先 import bpy，模型模块才 import 得到 bmesh
    import qingqiu_props as Q

    big = int(round(Q.BAMBOO_FRAME_1X * D))
    def glow(name):
        return {"layers": ["emit"], "light_color": QING_GLOW, "light_radius_units": LIGHT_RADIUS_UNITS[name],
                "palette_extra": list(Q.PALETTE_EXTRA)}
    return {
        "bamboo_clump": {**_common("bamboo_clump", big, 34, {
            "broken_variant": "bamboo_clump_broken",
            "note": "竹丛（软障碍，可打碎）：帧 160²×密度（2 倍 320²），比道具帧大；打碎后换成 bamboo_clump_broken（同画布同锚点）"}),
            "sockets": (), "grain": None},
        "bamboo_clump_broken": {**_common("bamboo_clump_broken", big, 34, {
            "intact_variant": "bamboo_clump",
            "note": "砍倒的竹丛：和 bamboo_clump 同画布、同锚点、同纸纹，直接换图"}),
            "sockets": (), "grain": "bamboo_clump"},
        "fox_shrine": {**_common("fox_shrine", S.FRAME["prop"], 22 * Q.SHRINE_GROW, {
            **glow("fox_shrine"), "required_sockets": ["glow"],
            "note": "狐仙祠：檐角一盏小青灯，glow 挂点是灯芯；光色 light_color、建议光半径 light_radius_units（世界单位）"}),
            "sockets": ("glow",), "grain": None},
        "stone_fox": {**_common("stone_fox", S.FRAME["prop"], 13 * Q.STONE_FOX_K, {"note": "石狐：不发光"}),
                      "sockets": (), "grain": None},
        "fox_lanterns": {**_common("fox_lanterns", S.FRAME["prop"], 30, {
            **glow("fox_lanterns"), "required_sockets": ["glow", "glow_0", "glow_1", "glow_2"],
            "note": "狐灯（狐村的光源）：glow 是三盏灯的中心，放一盏大光（光色 light_color、建议半径 light_radius_units，"
                    "世界单位）；或者在 glow_0..2 各放一盏小光"}),
            "sockets": ("glow", "glow_0", "glow_1", "glow_2"), "grain": None},
    }


def produce(name: str, out_root: Path, timings: dict) -> None:
    from pipeline import render_asset  # 先 import bpy
    import qingqiu_props as Q

    sp = specs()[name]
    meta = dict(sp["meta"])
    pe = meta.pop("palette_extra", [])
    render_asset(name, sp["frame_px"], Q.BUILDERS[name], [("idle", "S", 0, 1)], out_root, anchor=S.PROP_ANCHOR,
                 sockets_wanted=sp["sockets"], timings=timings, grain=sp["grain"], tmp_dir=TMP,
                 meta_extra=meta, palette_extra=pe)


# ================================================================ 审图
def _font(size: int):
    try:
        from ui_fonts import font
        return font("serif", size, weight=500)
    except Exception:  # noqa: BLE001
        from PIL import ImageFont
        return ImageFont.load_default()


def _label(im: Image.Image, xy, text: str, size: int = int(11 * D), color=S.INK["nong"]):
    ImageDraw.Draw(im).text(xy, text, fill=CS.rgb(color) + (255,), font=_font(size))


def _stack(blocks, pad: int = int(6 * D), title_h: int = int(16 * D)) -> Image.Image:
    w = max(b.width for _, b in blocks) + 2 * pad
    h = sum(b.height + (title_h if t else 0) + pad for t, b in blocks) + pad
    out = Image.new("RGB", (w, h), CS.rgb(S.PAPER))
    y = pad
    for t, b in blocks:
        if t:
            _label(out, (pad, y), t)
            y += title_h
        out.paste(b, (pad, y))
        y += b.height + pad
    return out


def _with_overlay(A: dict, O: dict) -> dict:
    """主角底图 + 灯笼叠层（游戏里也是这样叠）。"""
    ov = {f["key"]: f for f in O["frames"]}
    frames = []
    for f in A["frames"]:
        o = ov.get(f["key"])
        if o is None:
            frames.append(f)
            continue
        rgba = f["rgba"].copy()
        rgba.alpha_composite(o["rgba"])
        frames.append(dict(f, rgba=rgba, emit=o["emit"]))
    return dict(A, frames=frames)


def _lights_for(name: str, meta: dict, f: dict, at, scale: float = 1.0) -> list:
    out = []
    if name == "hero":
        sx, sy = f["sockets"]["lantern"]
        out.append((at[0] + sx * scale, at[1] + sy * scale, CS.LIGHT_RADIUS_PX * scale, S.LANTERN_LIGHT))
    elif "light_color" in meta and "glow" in f["sockets"]:
        sx, sy = f["sockets"]["glow"]
        rad = CS.SOCKET_LIGHTS["flame"][0] * meta.get("light_radius_units", STONE_LANTERN_UNITS) / STONE_LANTERN_UNITS
        out.append((at[0] + sx * scale, at[1] + sy * scale, rad * scale, meta["light_color"]))
    elif "flame" in f["sockets"] and f.get("emit") is not None:
        sx, sy = f["sockets"]["flame"]
        rad, col = CS.SOCKET_LIGHTS["flame"]
        out.append((at[0] + sx * scale, at[1] + sy * scale, rad * scale, col))
    return out


def _lineup(A: dict, names: list, scale: float = 1.0, hh: float = 162, gap_1x: float = 8):
    """一排摆在宣纸地面上：白天图、夜景（各自的光）。"""
    gap = int(gap_1x * D)
    widths = []
    for n in names:
        f = A[n]["frames"][0]
        a = np.asarray(f["rgba"])[..., 3]
        xs = np.where(a.any(0))[0]
        ax = A[n]["meta"]["anchor"][0] * A[n]["meta"]["size"][0]
        widths.append((ax - xs[0], xs[-1] + 1 - ax))  # 锚点左右的实际宽度
    W = int(sum((l_ + r_) * scale for l_, r_ in widths) + gap * (len(names) + 1))
    Hh = int(hh * D * scale)
    day = CS.paper(W, Hh, seed=17)
    emit = np.zeros((Hh, W, 3), np.float32)
    lights = []
    x = gap
    for n, (l_, r_) in zip(names, widths):
        f = A[n]["frames"][0]
        at = (x + l_ * scale, Hh - 24 * D * scale)
        CS.place(day, f, A[n]["meta"], at, scale=scale)
        CS.place_emit(emit, f, A[n]["meta"], at, scale=scale)
        lights += _lights_for(n, A[n]["meta"], f, at, scale)
        x += (l_ + r_) * scale + gap
    return day.convert("RGB"), CS.night_composite(day, emit, lights)


def _zoom_tiles(A: dict, names: list, k: int = 3):
    """每件道具裁到不透明范围（留一点边），宣纸底，白天和夜里（自己的光）各一张，再最近邻放大 k 倍。"""
    m = int(10 * D)
    days, nights = [], []
    for n in names:
        f = A[n]["frames"][0]
        meta = A[n]["meta"]
        Wf, Hf = meta["size"]
        a = np.asarray(f["rgba"])[..., 3]
        ys, xs = np.where(a > 0)
        x0, x1 = max(0, xs.min() - m), min(Wf, xs.max() + 1 + m)
        y0, y1 = max(0, ys.min() - m), min(Hf, ys.max() + 1 + m)
        day = CS.paper(Wf, Hf, seed=2)
        emit = np.zeros((Hf, Wf, 3), np.float32)
        at = CS.anchor_px(meta)
        CS.place(day, f, meta, at)
        CS.place_emit(emit, f, meta, at)
        lights = _lights_for(n, meta, f, at)
        nt = CS.night_composite(day, emit, lights)
        days.append(CS.zoom(day.convert("RGB").crop((x0, y0, x1, y1)), k))
        nights.append(CS.zoom(nt.crop((x0, y0, x1, y1)), k))

    def row(ims):  # noqa: E306
        g = int(4 * D)
        H = max(i.height for i in ims)
        out = Image.new("RGB", (sum(i.width for i in ims) + g * (len(ims) - 1), H), CS.rgb(S.PAPER))
        x = 0
        for i in ims:
            out.paste(i, (x, H - i.height))
            x += i.width + g
        return out
    return row(days), row(nights)


def build_review(src: Path) -> Path:
    REVIEW.mkdir(parents=True, exist_ok=True)
    A = {n: CS.load_asset(src / n) for n in ALL}
    A["hero"] = CS.load_asset(ASSETS / "hero")
    if (ASSETS / "lantern_red" / "meta.json").exists():
        A["hero"] = _with_overlay(A["hero"], CS.load_asset(ASSETS / "lantern_red"))
    A["hero"] = dict(A["hero"], frames=[f for f in A["hero"]["frames"] if f["key"] == "idle_S_00"])
    A["stone_lantern"] = CS.load_asset(ASSETS / "stone_lantern")
    line = ["hero", "stone_lantern", *ALL]
    d1, n1 = _lineup(A, line)
    z_day, z_night = _zoom_tiles(A, ALL[:2])
    z_day2, z_night2 = _zoom_tiles(A, ALL[2:])
    blocks = [("游戏大小（2 倍原大）：主角、石灯笼、竹丛、砍倒的竹丛、狐仙祠、石狐、狐灯 —— 白天", d1),
              ("夜里（主角灯笼暖光、石灯笼火光；青丘道具在 glow 挂点放 light_color 的青光，半径按 light_radius_units）", n1),
              ("3 倍：竹丛 / 砍倒的竹丛 —— 白天", z_day), ("夜里（竹丛不发光，只有夜色）", z_night),
              ("3 倍：狐仙祠 / 石狐 / 狐灯 —— 白天", z_day2), ("夜里", z_night2)]
    out = REVIEW / "qq_props_sample.png"
    _stack(blocks).save(out)
    return out


def run_checks(src: Path) -> list:
    res = [C.check_asset(src / n) for n in ALL if (src / n / "meta.json").exists()]
    print("\n==== check_asset ====")
    for r in res:
        print(C.report(r))
    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "qq_check_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main(argv) -> int:
    if D != 2:
        raise SystemExit("青丘道具只出桌面版密度：请设 LANTERN_ART_DENSITY=2")
    t0 = time.perf_counter()
    src = SAMPLE if "--sample" in argv else ASSETS
    only = None
    for a in argv:
        if a.startswith("--only"):
            only = (a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1]).split(",")
    timings: dict = {}
    if "--review" not in argv:
        for n in only or ALL:
            produce(n, src, timings)
    res = run_checks(src)
    if all((src / n / "meta.json").exists() for n in ALL):
        print("审图：", build_review(src))
    print(json.dumps(timings, ensure_ascii=False))
    print(f"共 {time.perf_counter() - t0:.1f}s")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
