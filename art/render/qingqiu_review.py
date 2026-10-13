"""青丘妖物的样张与审图（狐火 fox_wisp、竹魅 bamboo_wraith、讨封狐 taofeng_fox；赤面狐扑击、青面鬼冲撞、九尾扫与召唤）。

运行（仓库根目录，只出 2 倍）：
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py sample   # 样张：渲几帧到 out/qq_sample@2x/，拼审图
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py review   # 正式素材（out/assets@2x/）的审图、动图
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py sample --review  # 不渲染，只重拼样张审图
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/qingqiu_review.py sample --only=fox_wisp,boss  # 只重渲这几个
输出（out/review@2x/）：
    （文件名都以 qq_enemies_ 开头，和别的会话的 qq_* 审图分开）
    sample：qq_enemies_sample.png（游戏 1 倍大小：比例图白天 / 夜里，每个素材宣纸底一排、夜里一排），
            qq_enemies_sample_lineup_day/night.png、qq_enemies_sample_zoom3_<素材>.png（裁到内容、3 倍放大）、
            qq_enemies_sample_check.json
    review：qq_enemies_<素材>_<动画>.gif（每个新动画一张）、qq_enemies_lineup_day/night.png、
            qq_enemies_night_scene.png / qq_enemies_day_scene.png、qq_enemies_frames_<素材>.png（全部新帧 1 倍：宣纸底 + 夜里）
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
SAMPLE = OUT / f"qq_sample@{D:g}x"
REVIEW = OUT / ("review" if D == 1 else f"review@{D:g}x")
NEW = ["fox_wisp", "bamboo_wraith", "taofeng_fox"]
# 样张：素材 → {动画: [姿态帧号]}；已有妖物只渲新动作
SAMPLE_FRAMES = {
    "fox_wisp": {"float": [0], "pounce": [0, 1, 2, 3]},
    "bamboo_wraith": {"idle": [0], "move": [0], "shoot": [0, 1, 2, 3, 4]},
    "taofeng_fox": {"disguise": [0], "move": [0], "reveal": [0, 1, 2, 3]},
    "fox": {"pounce": list(range(6))},
    "ghoul": {"charge": list(range(6))},
    "boss": {"sweep": list(range(6)), "summon": list(range(4))},
}
ACTIONS = {"fox": ["pounce"], "ghoul": ["charge"], "boss": ["sweep", "summon"]}


# ================================================================ 小工具
def _font(size=11):
    """标签字体：有 post/ui_fonts.py 缓存的思源宋体就用它（中文），没有就用 Pillow 自带的。"""
    from PIL import ImageFont
    p = OUT / "fonts" / "NotoSerifSC-VF.ttf"
    try:
        return ImageFont.truetype(str(p), int(size * D)) if p.exists() else ImageFont.load_default(size=int(size * D))
    except OSError:
        return ImageFont.load_default(size=int(size * D))


def _text(im, xy, s, fill=None, size=11):
    ImageDraw.Draw(im).text(xy, s, fill=fill or CS.rgb(S.INK["dan"]) + (255,), font=_font(size))


def _night_tile(f, meta, light_at=None, radius=None):
    """一帧的夜景：宣纸底 × 光照（light_at 相对锚点；None = 完全在暗处，只剩发光层）+ 发光层。"""
    W, H = meta["size"]
    ax, ay = CS.anchor_px(meta)
    day = CS.paper(W, H, seed=2)
    CS.place(day, f, meta, (ax, ay))
    emit = np.zeros((H, W, 3), np.float32)
    CS.place_emit(emit, f, meta, (ax, ay))
    lights = [] if light_at is None else [(ax + light_at[0], ay + light_at[1], radius or CS.LIGHT_RADIUS_PX, S.LANTERN_LIGHT)]
    return CS.night_composite(day, emit, lights)


def _day_tile(f, meta, shadow=True):
    W, H = meta["size"]
    bg = CS.paper(W, H, seed=2)
    CS.place(bg, f, meta, CS.anchor_px(meta), shadow=shadow)
    return bg.convert("RGB")


def _crop_box(frames, pad):
    """一组帧合起来的不透明范围（同一组用同一个框，放大后帧与帧对得齐）。"""
    x0 = y0 = 10 ** 9
    x1 = y1 = 0
    for f in frames:
        bb = f["rgba"].getchannel("A").getbbox()
        if bb:
            x0, y0, x1, y1 = min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])
    W, H = frames[0]["rgba"].size
    return max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)


def _row(tiles, gap, bg=None):
    W = sum(t.width for t in tiles) + gap * (len(tiles) + 1)
    H = max(t.height for t in tiles) + 2 * gap
    out = Image.new("RGB", (W, H), bg or CS.rgb(S.PAPER))
    x = gap
    for t in tiles:
        out.paste(t, (x, gap + (H - 2 * gap - t.height)))
        x += t.width + gap
    return out


def _stack(rows, gap=0, bg=None):
    W = max(r.width for r in rows)
    out = Image.new("RGB", (W, sum(r.height for r in rows) + gap * (len(rows) - 1)), bg or CS.rgb(S.PAPER))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + gap
    return out


def _frames(A, anims):
    return [f for f in A["frames"] if f["anim"] in anims]


# ================================================================ 比例图（白天 / 夜里）
def lineup(A: dict, picks, path_day, path_night, height=330):
    """一排站在同一条地面线上：主角居中提灯，光圈半径同游戏（LIGHT_RADIUS_PX）。
    picks = [(素材, 帧 key, 是否镜像)]，主角放在中间那个位置。夜里：光圈里的照亮，外面只剩发光层。"""
    gap = int(14 * D)
    ws = [A[n]["meta"]["size"][0] * (0.62 if A[n]["meta"]["size"][0] > 400 else 0.72) for n, _, _ in picks]
    W = int(sum(ws) + gap * (len(picks) + 1))
    H = int(height * D)
    day = CS.paper(W, H, seed=11, blotches=4)
    emit = np.zeros((H, W, 3), np.float32)
    ground = H - 26 * D
    x = gap
    light = None
    placed: list = []
    for (n, key, mir), w in zip(picks, ws):
        f = next(fr for fr in A[n]["frames"] if fr["key"] == key)
        if mir:
            f = dict(f, rgba=f["rgba"].transpose(Image.FLIP_LEFT_RIGHT),
                     emit=f["emit"].transpose(Image.FLIP_LEFT_RIGHT) if f["emit"] else None)
        at = (x + w / 2, ground)
        CS.place(day, f, A[n]["meta"], at)
        CS.place_emit(emit, f, A[n]["meta"], at)
        _text(day, (int(x), int((4 + 13 * (len(placed) % 2)) * D)), f"{n}/{key}", size=9)
        placed.append(n)
        if n == "hero":
            lx, ly = f["sockets"]["lantern"]
            light = (at[0] + lx, at[1] + ly, CS.LIGHT_RADIUS_PX, S.LANTERN_LIGHT)
        x += w + gap
    day.convert("RGB").save(path_day)
    night = CS.night_composite(day, emit, [light] if light else [])
    night.save(path_night)
    return day.convert("RGB"), night


# ================================================================ 样张
def render_sample(only=None):
    import produce as PR
    timings: dict = {}
    for name, sel in SAMPLE_FRAMES.items():
        if only and name not in only:
            continue
        spec = f"{name}:{'+'.join(sel)}"
        PR.produce(spec, timings, out_root=SAMPLE, only_frames=sel)
    (SAMPLE / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1), encoding="utf-8")


def sample_sheet():
    REVIEW.mkdir(parents=True, exist_ok=True)
    T = {n: CS.load_asset(SAMPLE / n) for n in SAMPLE_FRAMES}
    base = {n: CS.load_asset(ASSETS / n) for n in ("hero", "shade", "wisp", "fox")}
    import produce as PR
    hero = PR.load_assets(["hero"])["hero"]
    base["hero"] = hero
    gap = int(8 * D)
    blocks = []
    # 1) 比例：主角、影妖、疾影、赤面狐 + 新妖物（游戏 1 倍大小），白天 / 夜里
    A = {**base, **{f"qq_{k}": v for k, v in T.items()}}
    A2 = dict(base)
    for n in NEW:
        A2[n] = T[n]
    picks = [("taofeng_fox", "disguise_E_00", False), ("bamboo_wraith", "idle_E_00", False), ("fox_wisp", "float_E_00", False),
             ("shade", "float_E_00", False), ("wisp", "float_E_00", False), ("hero", "idle_S_00", False),
             ("fox_wisp", "float_E_00", True), ("fox", "move_E_00", True), ("bamboo_wraith", "move_E_00", True),
             ("taofeng_fox", "move_E_00", True)]
    d, nt = lineup(A2, picks, REVIEW / "qq_enemies_sample_lineup_day.png", REVIEW / "qq_enemies_sample_lineup_night.png")
    blocks += [d, nt]
    # 2) 每个素材一行：宣纸底 1 倍；下面同样的帧在夜里（光圈边缘：灯在左下方 0.9 个半径外）
    R = CS.LIGHT_RADIUS_PX
    for n in SAMPLE_FRAMES:
        AA = T[n]
        meta = AA["meta"]
        fr = AA["frames"]
        day_tiles = [_day_tile(f, meta) for f in fr]
        night_tiles = [_night_tile(f, meta, (-R * 0.75, R * 0.1)) for f in fr]
        dark_tiles = [_night_tile(f, meta, None) for f in fr[:1]]
        lab = Image.new("RGB", (day_tiles[0].width * 0 + int(150 * D), day_tiles[0].height), CS.rgb(S.PAPER))
        _text(lab, (gap, gap), n)
        _text(lab, (gap, gap + int(14 * D)), " ".join(sorted({f["anim"] for f in fr})))
        _text(lab, (gap, gap + int(28 * D)), "上：宣纸")
        _text(lab, (gap, gap + int(42 * D)), "下：光圈边缘，最后一格全暗")
        blocks.append(_row([lab] + day_tiles, gap))
        blocks.append(_row([Image.new("RGB", lab.size, CS.rgb(S.NIGHT_AMBIENT))] + night_tiles + dark_tiles, gap,
                           bg=CS.rgb(S.NIGHT_AMBIENT)))
    sheet = _stack(blocks, gap)
    sheet.save(REVIEW / "qq_enemies_sample.png")
    # 3) 3 倍放大：每个素材一张（同组同一个裁切框），宣纸底一排、夜里（光圈边缘）一排
    for n in SAMPLE_FRAMES:
        AA = T[n]
        meta = AA["meta"]
        fr = AA["frames"]
        box = _crop_box(fr, int(6 * D))
        k = 3
        day = [_day_tile(f, meta, shadow=False).crop(box) for f in fr]
        night = [_night_tile(f, meta, (-R * 0.75, R * 0.1)).crop(box) for f in fr]
        cols = len(fr) if box[2] - box[0] < 220 * D else min(len(fr), 3)
        rows = []
        for i in range(0, len(fr), cols):
            rows.append(_row(day[i:i + cols], gap // 2))
            rows.append(_row(night[i:i + cols], gap // 2, bg=CS.rgb(S.NIGHT_AMBIENT)))
        im = _stack(rows)
        im.resize((im.width * k, im.height * k), Image.NEAREST).save(REVIEW / f"qq_enemies_sample_zoom3_{n}.png")
    print("写出", REVIEW / "qq_enemies_sample.png", sheet.size)


def sample_checks():
    res = [C.check_asset(SAMPLE / n) for n in SAMPLE_FRAMES]
    for r in res:
        print(C.report(r))
    (REVIEW / "qq_enemies_sample_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ 正式审图
def build_review(timings: dict | None = None):
    t0 = time.perf_counter()
    REVIEW.mkdir(parents=True, exist_ok=True)
    import produce as PR
    A = PR.load_assets(["hero", "shade", "wisp", "fox", "ghoul", "boss", *NEW])
    gap = int(8 * D)
    R = CS.LIGHT_RADIUS_PX
    # 1) 动图：每个新动画一张（新妖物全部动画；已有妖物的新动作）。不循环的动画末帧多停一会儿看清
    todo = [(n, an) for n in NEW for an in A[n]["meta"]["anims"]] + [(n, an) for n, ans in ACTIONS.items() for an in ans]
    for n, an in todo:
        meta = A[n]["meta"]
        fr = [f for f in A[n]["frames"] if f["anim"] == an]
        if not fr:
            continue
        box = _crop_box(fr, int(6 * D))
        day = [_day_tile(f, meta).crop(box) for f in fr]
        night = [_night_tile(f, meta, (-R * 0.75, R * 0.1)).crop(box) for f in fr]
        tiles = [_row([d, nt], gap // 2) for d, nt in zip(day, night)]
        a = meta["anims"][an]
        if a.get("loop") is False:
            tiles = tiles + [tiles[-1]] * 3
        k = 1 if box[2] - box[0] > 300 * D else 2
        ims = [t.resize((t.width * k // int(D), t.height * k // int(D)), Image.LANCZOS) if D > 1 else t for t in tiles]
        ims = [im.quantize(colors=160, method=Image.Quantize.MEDIANCUT) for im in ims]
        ims[0].save(REVIEW / f"qq_enemies_{n}_{an}.gif", save_all=True, append_images=ims[1:], duration=round(1000 / a["fps"]),
                    loop=0, disposal=1)
    # 2) 逐帧总表（1 倍）：宣纸底 + 光圈边缘
    for n in NEW + list(ACTIONS):
        meta = A[n]["meta"]
        fr = A[n]["frames"] if n in NEW else _frames(A[n], ACTIONS[n])
        rows = []
        for an in dict.fromkeys(f["anim"] for f in fr):
            ff = [f for f in fr if f["anim"] == an]
            rows.append(_row([_day_tile(f, meta) for f in ff], gap // 2))
            rows.append(_row([_night_tile(f, meta, (-R * 0.75, R * 0.1)) for f in ff], gap // 2, bg=CS.rgb(S.NIGHT_AMBIENT)))
        _stack(rows).save(REVIEW / f"qq_enemies_frames_{n}.png")
    # 3) 比例图：白天 / 夜里
    picks = [("taofeng_fox", "disguise_E_00", False), ("bamboo_wraith", "idle_E_00", False), ("fox_wisp", "float_E_00", False),
             ("shade", "float_E_00", False), ("wisp", "float_E_00", False), ("hero", "idle_S_00", False),
             ("fox_wisp", "pounce_E_01", True), ("fox", "pounce_E_01", True), ("bamboo_wraith", "shoot_E_01", True),
             ("taofeng_fox", "move_E_00", True)]
    lineup(A, picks, REVIEW / "qq_enemies_lineup_day.png", REVIEW / "qq_enemies_lineup_night.png")
    # 4) 夜景：主角提灯居中；狐火绕圈（光里一只、暗处两只），竹魅藏在暗处的竹丛里，讨封狐在圈外扮人、圈边现形，
    #    赤面狐伏低蓄力、青面鬼低头蓄力、九尾在后方扫尾
    w, h = int(1100 * D), int(620 * D)
    day = CS.paper(w, h, seed=17, blotches=10)
    emit = np.zeros((h, w, 3), np.float32)
    hf = next(f for f in A["hero"]["frames"] if f["key"] == "idle_S_00")
    hero_at = (w * 0.48, h * 0.72)
    lx, ly = hf["sockets"]["lantern"]
    light = (hero_at[0] + lx, hero_at[1] + ly)

    def polar(ang, dist):
        a = math.radians(ang)
        return (light[0] + math.cos(a) * dist * R, light[1] + math.sin(a) * dist * R)

    def fr(n, key, mir=False):
        f = next(x for x in A[n]["frames"] if x["key"] == key)
        if mir:
            f = dict(f, rgba=f["rgba"].transpose(Image.FLIP_LEFT_RIGHT),
                     emit=f["emit"].transpose(Image.FLIP_LEFT_RIGHT) if f["emit"] else None)
        return f

    items = [
        ("boss", fr("boss", "sweep_E_03", True), (w * 0.80, h * 0.38)),
        ("bamboo_wraith", fr("bamboo_wraith", "idle_E_00"), (w * 0.10, h * 0.50)),
        ("bamboo_wraith", fr("bamboo_wraith", "shoot_E_01"), (w * 0.24, h * 0.36)),
        ("taofeng_fox", fr("taofeng_fox", "disguise_E_02"), (w * 0.16, h * 0.88)),
        ("taofeng_fox", fr("taofeng_fox", "reveal_E_02", True), polar(-12, 1.02)),
        ("fox_wisp", fr("fox_wisp", "float_E_03"), polar(200, 0.62)),
        ("fox_wisp", fr("fox_wisp", "float_E_05", True), (w * 0.70, h * 0.70)),
        ("fox_wisp", fr("fox_wisp", "pounce_E_01", True), (w * 0.92, h * 0.86)),
        ("fox", fr("fox", "pounce_E_01"), polar(160, 1.12)),
        ("ghoul", fr("ghoul", "charge_E_01", True), polar(40, 1.25)),
        ("shade", fr("shade", "float_E_00"), (w * 0.38, h * 0.95)),
        ("hero", hf, hero_at),
    ]
    for n, f, pos in sorted(items, key=lambda it: it[2][1]):
        CS.place(day, f, A[n]["meta"], pos, shadow=n != "fox_wisp" or True)
        CS.place_emit(emit, f, A[n]["meta"], pos)
    CS.night_composite(day, emit, [(light[0], light[1], R, S.LANTERN_LIGHT)]).save(REVIEW / "qq_enemies_night_scene.png")
    day.convert("RGB").save(REVIEW / "qq_enemies_day_scene.png")
    if timings is not None:
        timings["qq_review_s"] = round(time.perf_counter() - t0, 2)


def main(argv):
    mode = argv[0] if argv else "sample"
    if mode == "sample":
        only = next((a.split("=", 1)[1].split(",") for a in argv if a.startswith("--only=")), None)
        if "--review" not in argv:
            render_sample(only)
        sample_checks()
        sample_sheet()
    elif mode == "review":
        build_review()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
