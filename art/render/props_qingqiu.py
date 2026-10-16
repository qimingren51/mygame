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
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from style import style as S  # noqa: E402
import check_asset as C  # noqa: E402
import contact_sheet as CS  # noqa: E402

D = S.DENSITY
OUT = ART / "out"
ASSETS = OUT / S.ASSETS_DIR_NAME
SAMPLE = OUT / f"qq_props_sample@{D:g}x"
REVIEW = OUT / f"review@{D:g}x"
TMP = OUT / "_tmp_qq"
PROPS = ["bamboo_clump", "bamboo_clump_broken", "fox_shrine", "stone_fox", "fox_lanterns"]  # 审图 qq_props_sample
COURTYARD = ["fox_shrine_grand", "fox_gate", "fox_eave_lamp", "fox_eave_lamp_lit"]  # 狐祠庭院，审图 qq_courtyard_sample
ALL = PROPS + COURTYARD
QING_GLOW = "#8FE3C8"  # 与 models/qingqiu_props.QING_GLOW 相同（这里不 import 模型，免得审图也要 bpy）
# 建议的光半径（世界单位，写进 meta.light_radius_units；游戏里石灯笼的光是 120）
LIGHT_RADIUS_UNITS = {"fox_lanterns": 140, "fox_shrine": 90,  # 狐仙祠放大 1.3 倍后光也跟着大一点
                      "fox_shrine_grand": 115, "fox_eave_lamp_lit": 50}  # 大祠的青光 150 会把整个庭院照亮，收到 115
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
    grand = int(round(Q.GRAND_FRAME_1X * D))
    gate = int(round(Q.GATE_FRAME_1X * D))
    lamp_note = "挂着的道具：锚点是挂钩顶端（anchor_kind: hanging），对准 fox_shrine_grand 的 eave_lamp 挂点，灯垂在下面"

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
        "fox_shrine_grand": {**_common("fox_shrine_grand", grand, 85, {
            **glow("fox_shrine_grand"), "required_sockets": ["glow", "eave_lamp"], "eave_lamp_asset": "fox_eave_lamp",
            "note": "大狐仙祠（狐祠庭院的正殿）：按这个尺寸画的，原样摆，不要再放大；帧 256²×密度（2 倍 512²）。"
                    "右前檐角一盏小青灯，glow 是灯芯（光色 light_color、建议光半径 light_radius_units，世界单位）；"
                    "eave_lamp 是左次间檐下小铁钩的下端，fox_eave_lamp / fox_eave_lamp_lit 的锚点对准这里"}),
            "sockets": ("glow", "eave_lamp"), "grain": None},
        "fox_gate": {**_common("fox_gate", gate, 60, {
            "note": "石牌坊（狐祠庭院的入口）：帧 192²×密度（2 倍 384²），锚点在两根柱子之间的地面中点；"
                    "冲天柱式（柱子穿过屋顶），门洞净宽约 1.8 米、净高约 2.4 米，主角从中间走过；不发光"}),
            "sockets": (), "grain": None},
        "fox_eave_lamp": {**_common("fox_eave_lamp", S.FRAME["small"], 0, {
            "anchor_kind": "hanging", "lit_variant": "fox_eave_lamp_lit", "required_sockets": ["flame"],
            "note": f"檐下留灯（没点着）：{lamp_note}；点灯时换成 fox_eave_lamp_lit（同画布、同锚点、同纸纹）；"
                    "flame 是灯芯；不落地，没有影子"}),
            "sockets": ("flame",), "grain": None, "anchor": Q.HANGING_ANCHOR},
        "fox_eave_lamp_lit": {**_common("fox_eave_lamp_lit", S.FRAME["small"], 0, {
            "layers": ["emit"], "light_color": Q.EAVE_LAMP_GLOW, "light_radius_units": LIGHT_RADIUS_UNITS["fox_eave_lamp_lit"],
            "anchor_kind": "hanging", "unlit_variant": "fox_eave_lamp", "required_sockets": ["flame"],
            # 灯芯占了大半个灯，纸纹压暗的灯芯、灯芯和竹篾之间的过渡色吸附不上，列进调色板（同 lanterns.palette_extra）
            "palette_extra": [S.mix(S.LANTERN_LIGHT, "#000000", 0.12), S.shade_ramp(S.LANTERN_LIGHT)[1],
                              S.mix(S.LANTERN_LIGHT, S.shade_ramp(S.ACCENT["zheshi"])[1], 0.5)],
            "note": f"檐下留灯（点着，主角留下自己的火）：{lamp_note}；光放在 flame（灯芯），光色 light_color、"
                    "建议光半径 light_radius_units（世界单位）；和 fox_eave_lamp 同画布、同锚点、同纸纹，直接换图"}),
            "sockets": ("flame",), "grain": "fox_eave_lamp", "anchor": Q.HANGING_ANCHOR},
    }


def produce(name: str, out_root: Path, timings: dict) -> None:
    from pipeline import render_asset  # 先 import bpy
    import qingqiu_props as Q

    sp = specs()[name]
    meta = dict(sp["meta"])
    pe = meta.pop("palette_extra", [])
    render_asset(name, sp["frame_px"], Q.BUILDERS[name], [("idle", "S", 0, 1)], out_root,
                 anchor=sp.get("anchor", S.PROP_ANCHOR),
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
    A = {n: CS.load_asset(src / n) for n in PROPS}
    A["hero"] = CS.load_asset(ASSETS / "hero")
    if (ASSETS / "lantern_red" / "meta.json").exists():
        A["hero"] = _with_overlay(A["hero"], CS.load_asset(ASSETS / "lantern_red"))
    A["hero"] = dict(A["hero"], frames=[f for f in A["hero"]["frames"] if f["key"] == "idle_S_00"])
    A["stone_lantern"] = CS.load_asset(ASSETS / "stone_lantern")
    line = ["hero", "stone_lantern", *PROPS]
    d1, n1 = _lineup(A, line)
    z_day, z_night = _zoom_tiles(A, PROPS[:2])
    z_day2, z_night2 = _zoom_tiles(A, PROPS[2:])
    blocks = [("游戏大小（2 倍原大）：主角、石灯笼、竹丛、砍倒的竹丛、狐仙祠、石狐、狐灯 —— 白天", d1),
              ("夜里（主角灯笼暖光、石灯笼火光；青丘道具在 glow 挂点放 light_color 的青光，半径按 light_radius_units）", n1),
              ("3 倍：竹丛 / 砍倒的竹丛 —— 白天", z_day), ("夜里（竹丛不发光，只有夜色）", z_night),
              ("3 倍：狐仙祠 / 石狐 / 狐灯 —— 白天", z_day2), ("夜里", z_night2)]
    out = REVIEW / "qq_props_sample.png"
    _stack(blocks).save(out)
    return out


# ================================================================ 狐祠庭院审图（qq_courtyard_sample.png）
PPU = S.PX_PER_UNIT
HERO_LIGHT_UNITS = 200  # 游戏里主角手灯的光半径（crates/view/src/actors.rs 的 LANTERN_LIGHT）
PROP_LIGHT_ALPHA = 0.85  # 游戏里道具光的不透明度（ground.rs 的 glowing_prop）
HERO_LIGHT_ALPHA = 0.85
# 庭院摆法（世界单位，y 朝下 = 朝镜头）：照 crates/view/src/ground.rs 的 shrine_layout，小狐仙祠 2.5 倍换成大狐仙祠
# 原样摆，正前方中轴上加石牌坊，不摆熄着的石灯笼。(素材, x, y, 缩放, 镜像)
COURTYARD_GATE_Y = 100.0
COURTYARD_LAYOUT = [
    ("fox_shrine_grand", 0.0, 0.0, 1.0, False),
    ("fox_gate", 0.0, COURTYARD_GATE_Y, 1.0, False),
    ("stone_fox", -65.0, 40.0, 1.25, False),
    ("stone_fox", 65.0, 40.0, 1.25, True),
    ("fox_lanterns", -103.0, 5.0, 1.25, False),
    ("rock_b", 112.0, -20.0, 1.5, True),
    ("ground/bamboo_0", -123.0, -32.0, 1.6, False),
    ("ground/bamboo_1", 133.0, -42.0, 1.8, True),
]


def _path_flats() -> list:
    """引向祠顶的卵石、落叶、狐爪印（地面平铺，游戏里 alpha 0.65；卵石大小随机，这里取 1）。"""
    out = []
    for k in range(7):
        y = 65.0 + k * 23.0
        bend = math.sin(k * 0.43) * 25.0
        for side in (-1.0, 1.0):
            x = bend + side * (42.0 + k * 5.0)
            out.append(("ground/pebbles_0", x, y, 1.0, side < 0))
            out.append(("ground/qq_bamboo_leaves_1", x + side * 23.0, y - 8.0, 1.1, side > 0))
        if k % 2 == 0:
            out.append(("ground/qq_fox_tracks", bend - 8.0, y, 0.8, False))
    return out


def _load_ground() -> dict:
    """地面装饰（files 格式的 meta）读成和 load_asset 一样的结构：{"ground/<名>": 素材}。"""
    gdir = ASSETS / "ground"
    gm = json.loads((gdir / "meta.json").read_text(encoding="utf-8"))
    out = {}
    for fn, info in gm["files"].items():
        if not fn.endswith(".png") or fn.endswith("_emit.png"):
            continue
        meta = {"size": info["size"], "anchor": info["anchor"], "shadow_radius_px": 0}
        out[f"ground/{fn[:-4]}"] = {"meta": meta, "frames": [{"key": fn[:-4], "rgba": Image.open(gdir / fn).convert("RGBA"),
                                                              "emit": None, "sockets": {}}]}
    return out


def _variant(A: dict, scale: float = 1.0, flip: bool = False, alpha: float = 1.0) -> dict:
    """缩放（双线性，同游戏里 GPU 采样）、镜像、整体透明度；锚点、挂点、影子半径跟着变。"""
    meta = dict(A["meta"])
    W0, H0 = meta["size"]
    W1, H1 = max(1, round(W0 * scale)), max(1, round(H0 * scale))
    meta["size"] = [W1, H1]
    meta["shadow_radius_px"] = meta.get("shadow_radius_px", 14 * D) * scale
    if flip:
        meta["anchor"] = [1 - meta["anchor"][0], meta["anchor"][1]]

    def tf(im):
        if im is None:
            return None
        if scale != 1.0:
            im = im.resize((W1, H1), Image.BILINEAR)
        if flip:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        if alpha != 1.0:
            a = np.asarray(im).copy()
            a[..., 3] = (a[..., 3] * alpha).astype(np.uint8)
            im = Image.fromarray(a, "RGBA")
        return im
    frames = [dict(f, rgba=tf(f["rgba"]), emit=tf(f["emit"]),
                   sockets={k: ((-x if flip else x) * scale, y * scale) for k, (x, y) in f["sockets"].items()})
              for f in A["frames"]]
    return dict(A, meta=meta, frames=frames, scale=scale)


def _game_lights(name: str, A: dict, at) -> list:
    """游戏里的光（半径按世界单位，衰减同审图 (1-(r/R)^2)^2）：主角手灯 200；发光道具在 glow（没有就 flame）放
    light_color、半径 light_radius_units × √缩放（effects.rs）。"""
    f, meta, k = A["frames"][0], A["meta"], A.get("scale", 1.0)
    if name == "hero":
        sx, sy = f["sockets"]["lantern"]
        return [(at[0] + sx, at[1] + sy, HERO_LIGHT_UNITS * PPU, S.LANTERN_LIGHT, HERO_LIGHT_ALPHA)]
    if "light_color" not in meta:
        return []
    sock = "glow" if "glow" in f["sockets"] else "flame"
    if sock not in f["sockets"]:
        return []
    sx, sy = f["sockets"][sock]
    return [(at[0] + sx, at[1] + sy, meta.get("light_radius_units", 80) * PPU * math.sqrt(k), meta["light_color"],
             PROP_LIGHT_ALPHA)]


def _night_game(day: Image.Image, emit: np.ndarray, lights) -> Image.Image:
    """夜景：白天图 × 光照图（夜色 + 各盏光 × 不透明度）+ 发光层 + 辉光（同 contact_sheet.night_composite）。"""
    d = np.asarray(day.convert("RGB"), np.float32) / 255.0
    h, w = d.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lm = np.ones((h, w, 3), np.float32) * (np.array(CS.rgb(S.NIGHT_AMBIENT), np.float32) / 255.0)
    for x, y, R, col, k in lights:
        f = np.clip(1 - ((xx - x) ** 2 + (yy - y) ** 2) / (R * R), 0, 1) ** 2
        lm += f[..., None] * (np.array(CS.rgb(col), np.float32) / 255.0 * k)
    out = d * np.clip(lm, 0, 1)
    out = out * (1 - np.clip(emit.max(-1, keepdims=True), 0, 1)) + emit
    sig = 2.5 * D
    glow = np.stack([np.asarray(Image.fromarray((np.clip(emit[..., c], 0, 1) * 255).astype(np.uint8))
                                .filter(ImageFilter.GaussianBlur(sig)), np.float32) / 255.0 for c in range(3)], -1)
    return Image.fromarray((np.clip(out + glow * 0.9, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


class _Scene:
    """一张宣纸地面，按世界单位摆素材（origin = 世界原点的像素位置），记下发光层和光。"""

    def __init__(self, W: int, H: int, origin, seed: int = 17):
        self.day = CS.paper(W, H, seed=seed)
        self.emit = np.zeros((H, W, 3), np.float32)
        self.lights: list = []
        self.origin = origin

    def px(self, x_u: float, y_u: float):
        return self.origin[0] + x_u * PPU, self.origin[1] + y_u * PPU

    def put(self, name: str, A: dict, at, shadow: bool = True, light: bool = True):
        f = A["frames"][0]
        CS.place(self.day, f, A["meta"], at, shadow=shadow)
        CS.place_emit(self.emit, f, A["meta"], at)
        if light:
            self.lights += _game_lights(name, A, at)
        return at

    def hang_lamp(self, shrine: dict, at, lamp_name: str, lamp: dict):
        """把檐下留灯的锚点对准大狐仙祠的 eave_lamp 挂点。"""
        sx, sy = shrine["frames"][0]["sockets"]["eave_lamp"]
        return self.put(lamp_name, lamp, (at[0] + sx, at[1] + sy), shadow=False)

    def night(self, extra=()) -> Image.Image:
        return _night_game(self.day, self.emit, self.lights + list(extra))


def _extent(A: dict):
    """锚点左、右、上、下的不透明范围（像素）。"""
    a = np.asarray(A["frames"][0]["rgba"])[..., 3]
    ys, xs = np.where(a > 0)
    ax, ay = CS.anchor_px(A["meta"])
    return ax - xs.min(), xs.max() + 1 - ax, ay - ys.min(), ys.max() + 1 - ay


def _size_text(A: dict) -> str:
    l_, r_, up, dn = _extent(A)
    return f"高 {(up + dn) / PPU:.1f} × 宽 {(l_ + r_) / PPU:.1f} 单位"


def _row(ims, gap: int = int(6 * D), bg=None) -> Image.Image:
    H = max(i.height for i in ims)
    out = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), H), bg or CS.rgb(S.PAPER))
    x = 0
    for i in ims:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def _labelled(im: Image.Image, text: str) -> Image.Image:
    fsz = int(10 * D)
    out = Image.new("RGB", (im.width, im.height + fsz + int(6 * D)), CS.rgb(S.PAPER))
    out.paste(im, (0, fsz + int(6 * D)))
    _label(out, (int(2 * D), int(2 * D)), text, size=fsz)
    return out


def _courtyard_lineup(A: dict) -> Image.Image:
    """(a) 游戏大小：主角、石灯笼、现在游戏里的小狐仙祠 ×2.5、大狐仙祠 ×1、石牌坊（主角站在两柱之间）。"""
    cols = [("主角", ["hero"]), ("石灯笼", ["stone_lantern"]), ("狐仙祠 ×2.5（现在游戏里放大）", ["fox_shrine_x25"]),
            ("大狐仙祠 ×1（新）", ["fox_shrine_grand"]), ("石牌坊（新），主角站在两柱之间", ["fox_gate", "hero"])]
    fsz = int(10 * D)
    font = _font(fsz)
    gap = int(16 * D)
    ext = []
    for lab, names in cols:
        e = [_extent(A[n]) for n in names]
        l_, r_ = max(x[0] for x in e), max(x[1] for x in e)
        lw = max(font.getlength(lab), font.getlength(_size_text(A[names[0]]))) / 2 + int(4 * D)
        ext.append((max(l_, lw), max(r_, lw), max(x[2] for x in e), max(x[3] for x in e)))
    top = max(e[2] for e in ext)
    foot = int(top + 14 * D)
    H = int(foot + max(e[3] for e in ext) + 10 * D)
    tag_w = int(font.getlength("石灯笼顶") + 8 * D)
    W = int(sum(e[0] + e[1] for e in ext) + gap * (len(cols) + 1) + tag_w)
    sc = _Scene(W, H, (0, foot), seed=17)
    dr = ImageDraw.Draw(sc.day)
    for k, txt in ((0, "主角头顶"), (1, "石灯笼顶")):  # 两条淡虚线
        y = foot - _extent(A[cols[k][1][0]])[2]
        for x0 in range(0, W, int(6 * D)):
            dr.line([(x0, y), (x0 + int(3 * D), y)], fill=CS.rgb(S.INK["qing"]) + (255,), width=1)
        dr.text((W - tag_w + int(4 * D), y - fsz - 2), txt, fill=CS.rgb(S.INK["dan"]) + (255,), font=font)
    xs, x = [], gap
    for (lab, names), (l_, r_, _, _) in zip(cols, ext):
        at = (x + l_, foot)
        for n in names:
            sc.put(n, A[n], at)
        xs.append(at[0])
        x += l_ + r_ + gap
    day = sc.day.convert("RGB")
    strip = Image.new("RGB", (W, 2 * fsz + int(8 * D)), CS.rgb(S.PAPER))
    ds = ImageDraw.Draw(strip)
    for (lab, names), cx in zip(cols, xs):
        size = _size_text(A[names[0]])
        for j, t in enumerate((lab, size)):
            ds.text((cx - font.getlength(t) / 2, int(2 * D) + j * (fsz + int(2 * D))), t,
                    fill=CS.rgb(S.INK["nong"] if j == 0 else S.INK["dan"]) + (255,), font=font)
    out = Image.new("RGB", (W, H + strip.height), CS.rgb(S.PAPER))
    out.paste(day, (0, 0))
    out.paste(strip, (0, H))
    return out


def _courtyard_lamp_tiles(A: dict):
    """(b) 大狐仙祠挂上檐下留灯（没点 / 点着）：宣纸上；夜里在主角灯光里；夜里灯光外（只有青灯和点着的留灯亮）。
    另外把留灯那一块放大 3 倍。"""
    x0_u, x1_u, y0_u, y1_u = -96.0, 58.0, -86.0, 40.0  # 画面范围（相对祠的锚点，世界单位）
    W, H = int((x1_u - x0_u) * PPU), int((y1_u - y0_u) * PPU)
    hero_at_u = (-66.0, 30.0)
    tiles, crops = {}, {}
    for lamp in ("fox_eave_lamp", "fox_eave_lamp_lit"):
        for mode in ("day", "in", "out"):
            sc = _Scene(W, H, (-x0_u * PPU, -y0_u * PPU), seed=23)
            at = sc.put("fox_shrine_grand", A["fox_shrine_grand"], sc.px(0, 0))
            lamp_at = sc.hang_lamp(A["fox_shrine_grand"], at, lamp, A[lamp])
            if mode != "out":
                sc.put("hero", A["hero"], sc.px(*hero_at_u), light=(mode == "in"))
            im = sc.day.convert("RGB") if mode == "day" else sc.night()
            tiles[(lamp, mode)] = im
            bx = (int(lamp_at[0] - 30 * D), int(lamp_at[1] - 22 * D), int(lamp_at[0] + 30 * D), int(lamp_at[1] + 48 * D))
            crops[(lamp, mode)] = CS.zoom(im.crop(bx), 3)
    order = (("fox_eave_lamp", "day"), ("fox_eave_lamp_lit", "day"), ("fox_eave_lamp", "in"), ("fox_eave_lamp_lit", "out"))
    return tiles, [crops[k] for k in order]


def _courtyard_mock(A: dict, lamp: str, hero: bool, night: bool) -> Image.Image:
    """(c) 庭院（照 ground.rs 摆，世界单位 1:1）：地面平铺先画，立着的按脚底 y 排序；留灯挂在 eave_lamp 上。"""
    x0_u, x1_u, y0_u, y1_u = -160.0, 160.0, -112.0, 172.0
    W, H = int((x1_u - x0_u) * PPU), int((y1_u - y0_u) * PPU)
    sc = _Scene(W, H, (-x0_u * PPU, -y0_u * PPU), seed=31)
    for n, x, y, s, fl in _path_flats():
        sc.put(n, _variant(A[n], s, fl, alpha=0.65), sc.px(x, y), shadow=False, light=False)
    upright = list(COURTYARD_LAYOUT) + ([("hero", 0.0, COURTYARD_GATE_Y + 38.0, 1.0, False)] if hero else [])
    for n, x, y, s, fl in sorted(upright, key=lambda p: p[2]):
        V = A[n] if (s == 1.0 and not fl) else _variant(A[n], s, fl)
        at = sc.put(n, V, sc.px(x, y), shadow=not n.startswith("ground/"))
        if n == "fox_shrine_grand":
            sc.hang_lamp(V, at, lamp, A[lamp])
    return sc.night() if night else sc.day.convert("RGB")


def build_courtyard_review(src: Path) -> Path:
    REVIEW.mkdir(parents=True, exist_ok=True)
    A = {n: CS.load_asset(src / n) for n in COURTYARD}
    hero = CS.load_asset(ASSETS / "hero")
    if (ASSETS / "lantern_red" / "meta.json").exists():
        hero = _with_overlay(hero, CS.load_asset(ASSETS / "lantern_red"))
    A["hero"] = dict(hero, frames=[f for f in hero["frames"] if f["key"] == "idle_S_00"])
    for n in ("stone_lantern", "fox_shrine", "stone_fox", "fox_lanterns", "rock_b"):
        A[n] = CS.load_asset(ASSETS / n)
    A["fox_shrine_x25"] = _variant(A["fox_shrine"], 2.5)
    A.update(_load_ground())
    tiles, zooms = _courtyard_lamp_tiles(A)
    rows = {mode: _row([tiles[("fox_eave_lamp", mode)], tiles[("fox_eave_lamp_lit", mode)]]) for mode in ("day", "in", "out")}
    blocks = [
        ("(a) 游戏大小（2 倍原大，1 像素 = 1 像素）：主角、石灯笼、狐仙祠 ×2.5（现在游戏里的做法，双线性放大）、"
         "大狐仙祠 ×1、石牌坊 —— 高、宽按 px_per_unit 4 换成世界单位", _courtyard_lineup(A)),
        ("(b) 大狐仙祠 + 檐下留灯（锚点对准 eave_lamp）：左 没点着，右 点着 —— 宣纸上", rows["day"]),
        ("夜里，在主角灯光里（光半径按游戏，世界单位：手灯 200、青灯 light_radius_units、留灯 50）", rows["in"]),
        ("夜里，主角灯光外：只有檐角青灯和点着的留灯亮", rows["out"]),
        ("留灯放大 3 倍：没点（宣纸）、点着（宣纸）、没点（主角灯光里）、点着（灯光外）", _row(zooms)),
        ("(c) 庭院（照 ground.rs 摆，1:1；牌坊在中轴 y=+100，石狐 ×1.25 在小径两侧，狐灯 ×1.25 在左边）："
         "左 宣纸上（留灯没点），右 夜里主角走到牌坊前（留灯没点）",
         _row([_courtyard_mock(A, "fox_eave_lamp", True, False), _courtyard_mock(A, "fox_eave_lamp", True, True)])),
        ("夜里，主角还在远处（灯光外）：左 留灯没点，右 留灯点着（主角留下的火）",
         _row([_courtyard_mock(A, "fox_eave_lamp", False, True), _courtyard_mock(A, "fox_eave_lamp_lit", False, True)])),
    ]
    out = REVIEW / "qq_courtyard_sample.png"
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
    if all((src / n / "meta.json").exists() for n in PROPS):
        print("审图：", build_review(src))
    if all((src / n / "meta.json").exists() for n in COURTYARD):
        print("庭院审图：", build_courtyard_review(src))
    print(json.dumps(timings, ensure_ascii=False))
    print(f"共 {time.perf_counter() - t0:.1f}s")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
