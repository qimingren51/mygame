"""主角与三只 P0 妖物的修补：样张渲染 + 新旧对比审图。

    LANTERN_ART_DENSITY=2 art/.venv/bin/python kfix.py render   # 渲样张到 art/out/kfix_sample@2x/（不动 assets@2x）
    LANTERN_ART_DENSITY=2 art/.venv/bin/python kfix.py review   # 审图 review@2x/kfix_sample.png + 动图 kfix_gif_hero_*
旧帧取 art/out/assets@2x/（第二阶段之后取 art/out/_kfix_old/，见 OLD 的选择）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ART = Path("/home/user/mygame/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from style import style as S  # noqa: E402
import contact_sheet as CS  # noqa: E402
import lantern_review as LR  # noqa: E402

D = S.DENSITY
OUT = ART / "out"
SAMPLE = OUT / f"kfix_sample@{D:g}x"
OLD = Path(os.environ.get("KFIX_OLD", str(OUT / S.ASSETS_DIR_NAME)))
REVIEW = OUT / f"review@{D:g}x"
LAMPS = ("red", "mirror", "frost")

# 主角样张：(动画, 朝向, 姿态帧号, 动画总帧数)
HERO_JOBS = ([("walk", "S", i, 8) for i in range(8)] + [("walk", "N", i, 8) for i in range(8)]
             + [("dash", "S", i, 4) for i in range(4)] + [("dash", "N", i, 4) for i in range(4)]
             + [("idle", d, 0, 6) for d in ("N", "NE", "NW")] + [("walk", "E", 0, 8)]
             + [("death", "S", i, 6) for i in (3, 4, 5)] + [("death", "E", 5, 6)])
ENEMY = {"boss": {"move": [0, 3]}, "stonelord": {"move": [0]}, "fox": {"move": [0], "pounce": [2]}}


def key_map(jobs, single_dir=None):
    """样张文件名（同一动画同一朝向里第几张）→ 正式素材里的帧名（姿态帧号）。"""
    seen, out = {}, {}
    for an, d, i, _n in jobs:
        k = seen[(an, d)] = seen.get((an, d), -1) + 1
        out[f"{an}_{d}_{k:02d}"] = f"{an}_{d}_{i:02d}"
    return out


HERO_KEYS = key_map(HERO_JOBS)  # 新 → 旧
ENEMY_KEYS = {n: key_map([(an, "E", i, 0) for an, fr in sel.items() for i in fr]) for n, sel in ENEMY.items()}


# ================================================================ 渲染
def render():
    import produce as PR
    t0 = time.perf_counter()
    timings: dict = {}
    PR.render_hero(HERO_JOBS, SAMPLE, timings=timings, lamps=LAMPS)
    for n, sel in ENEMY.items():
        PR.produce(f"{n}:{'+'.join(sel)}", timings, out_root=SAMPLE, only_frames=sel)
    timings["total_s"] = round(time.perf_counter() - t0, 1)
    (SAMPLE / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ 读帧
def hero_frame(root: Path, key: str, lamp: str = "red"):
    """主角底图 + 叠层：(rgba, emit, lantern 挂点, 光色)。"""
    base = Image.open(root / "hero" / f"{key}.png").convert("RGBA")
    ov, em = LR.frame(root / f"lantern_{lamp}", key)
    base.alpha_composite(ov)
    meta = json.loads((root / "hero" / "meta.json").read_text(encoding="utf-8"))
    col = json.loads((root / f"lantern_{lamp}" / "meta.json").read_text(encoding="utf-8"))["light_color"]
    return base, em, LR.socket(meta, key), col


def enemy_frame(root: Path, name: str, key: str):
    im, em = LR.frame(root / name, key)
    return im, em


def union_box(ims, pad=int(6 * D)):
    x0 = y0 = 10 ** 9
    x1 = y1 = 0
    for im in ims:
        bb = im.getchannel("A").getbbox()
        if bb:
            x0, y0, x1, y1 = min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])
    W, H = ims[0].size
    return max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)


def on_paper(im):
    bg = CS.paper(im.width, im.height, seed=2)
    bg.alpha_composite(im)
    return bg


def night(im, em, light, meta_size, anchor):
    """一帧的夜景：light = (挂点 x, y, 光色) 相对锚点，或 None（光在左下方 0.75 个半径外，妖物站在光圈边上）。"""
    W, H = meta_size
    ax, ay = anchor[0] * W, anchor[1] * H
    day = on_paper(im)
    if light is None:
        R = CS.LIGHT_RADIUS_PX
        lights = [(ax - R * 0.75, ay + R * 0.1, R, S.LANTERN_LIGHT)]
    else:
        lights = [(ax + light[0], ay + light[1], CS.LIGHT_RADIUS_PX, light[2])]
    return LR.lit(day, [em], lights)


def pair_rows(olds, news, box, zoom_keys=None, night_old=None, night_new=None, zoom=3):
    """一组帧：旧 / 新（宣纸，1 倍）；旧 / 新（夜里，1 倍）；挑几帧 3 倍放大（旧、新交替）。"""
    crop = lambda ims: [im.convert("RGB").crop(box) for im in ims]  # noqa: E731
    blocks = [("旧 · 宣纸 · 1 倍（2 倍素材原大）", LR.strip(crop([on_paper(i) for i in olds]))),
              ("新 · 宣纸 · 1 倍", LR.strip(crop([on_paper(i) for i in news])))]
    if night_old is not None:
        blocks += [("旧 · 夜里", LR.strip(crop(night_old), bg=S.NIGHT_AMBIENT)),
                   ("新 · 夜里", LR.strip(crop(night_new), bg=S.NIGHT_AMBIENT))]
    if zoom_keys:
        tiles = []
        for k in zoom_keys:
            tiles += [CS.zoom(on_paper(olds[k]).convert("RGB").crop(box), zoom),
                      CS.zoom(on_paper(news[k]).convert("RGB").crop(box), zoom)]
        blocks.append((f"{zoom} 倍放大：每对左旧右新（帧 {', '.join(str(k) for k in zoom_keys)}）", LR.strip(tiles)))
    return blocks


# ================================================================ 审图
def hero_block(title, new_keys, zoom_idx, lamp="red"):
    hmeta = json.loads((SAMPLE / "hero" / "meta.json").read_text(encoding="utf-8"))
    size, anchor = hmeta["size"], hmeta["anchor"]
    olds, news, n_old, n_new = [], [], [], []
    for nk in new_keys:
        ok = HERO_KEYS[nk]
        im_o, em_o, so, col = hero_frame(OLD, ok, lamp)
        im_n, em_n, sn, _ = hero_frame(SAMPLE, nk, lamp)
        olds.append(im_o)
        news.append(im_n)
        n_old.append(night(im_o, em_o, (so[0], so[1], col), size, anchor))
        n_new.append(night(im_n, em_n, (sn[0], sn[1], col), size, anchor))
    box = union_box(olds + news)
    return [(f"■ {title}", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))] + pair_rows(olds, news, box, zoom_idx, n_old, n_new)


def lantern_block():
    """三盏灯的死亡落地帧（灯笼附近 3 倍，地面线 = 灯笼着地处）+ 霜瓷灯冰裂纹（游戏大小、4 倍）。"""
    hmeta = json.loads((SAMPLE / "hero" / "meta.json").read_text(encoding="utf-8"))
    W, H = hmeta["size"]
    ax, ay = hmeta["anchor"][0] * W, hmeta["anchor"][1] * H
    blocks = [("■ 灯笼叠层：死亡第 3–5 帧（S）、第 5 帧（E），灯笼附近 3 倍，每对左旧右新；三行依次是红纸灯、铜镜灯、霜瓷灯",
               Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))]
    death_keys = [k for k in HERO_KEYS if k.startswith("death")]
    for lamp in LAMPS:
        tiles = []
        for nk in death_keys:
            ok = HERO_KEYS[nk]
            im_o, _, so, _ = hero_frame(OLD, ok, lamp)
            im_n, _, sn, _ = hero_frame(SAMPLE, nk, lamp)
            box = LR.crop_box(ax + sn[0], ay + sn[1], W, H, r=int(30 * D))
            tiles += [CS.zoom(on_paper(im_o).convert("RGB").crop(box), 3), CS.zoom(on_paper(im_n).convert("RGB").crop(box), 3)]
        blocks.append((f"{lamp}  （{', '.join(HERO_KEYS[k] for k in death_keys)}）", LR.strip(tiles)))
    # 冰裂纹：walk_E_00 / walk_S_00 / idle_NE_00，游戏大小 1 倍和 4 倍，宣纸、夜里
    tiles1, tiles4 = [], []
    for nk in ("walk_E_00", "walk_S_00", "walk_S_04", "idle_NE_00"):
        for root in (OLD, SAMPLE):
            im, em, s_, col = hero_frame(root, HERO_KEYS[nk] if root == OLD else nk, "frost")
            box = LR.crop_box(ax + s_[0], ay + s_[1], W, H, r=int(26 * D))
            d = on_paper(im).convert("RGB").crop(box)
            n = LR.lit(on_paper(im), [em], []).crop(box)  # 只有夜色环境光 + 发光层（看灯芯里的裂纹）
            tiles1 += [d, n]
            tiles4 += [CS.zoom(d, 4), CS.zoom(n, 4)]
    blocks += [("霜瓷灯冰裂纹：每组 旧宣纸 / 旧暗处（环境光 + 发光层） / 新宣纸 / 新暗处（walk_E_00、walk_S_00、walk_S_04、idle_NE_00），1 倍",
                LR.strip(tiles1)),
               ("同上 4 倍", LR.strip(tiles4))]
    return blocks


def enemy_block():
    blocks = [("■ 妖物（E）：九尾 move 0、3；石将 move 0；赤面狐 move 0、pounce 2", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))]
    for n in ENEMY:
        meta = json.loads((SAMPLE / n / "meta.json").read_text(encoding="utf-8"))
        olds, news, n_old, n_new = [], [], [], []
        for nk, ok in ENEMY_KEYS[n].items():
            im_o, em_o = enemy_frame(OLD, n, ok)
            im_n, em_n = enemy_frame(SAMPLE, n, nk)
            olds.append(im_o)
            news.append(im_n)
            n_old.append(night(im_o, em_o, None, meta["size"], meta["anchor"]))
            n_new.append(night(im_n, em_n, None, meta["size"], meta["anchor"]))
        box = union_box(olds + news)
        rows = pair_rows(olds, news, box, None, n_old, n_new)
        tiles = []
        for o, nw in zip(olds, news):
            tiles += [CS.zoom(on_paper(o).convert("RGB").crop(box), 2 if n == "boss" else 3),
                      CS.zoom(on_paper(nw).convert("RGB").crop(box), 2 if n == "boss" else 3)]
        rows.append((f"{'2' if n == 'boss' else '3'} 倍放大：每对左旧右新", LR.strip(tiles)))
        blocks += [(f"{n}  （{', '.join(ENEMY_KEYS[n].values())}）", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))] + rows
    return blocks


def gifs():
    """kfix_gif_hero_{walk,dash}_{N,S}_{old,new}.gif：主角 + 红纸灯，宣纸底，同一裁切框，2 倍放大。"""
    out = []
    for an, n, fps in (("walk", 8, 12), ("dash", 4, 16)):
        for d in ("N", "S"):
            keys = [f"{an}_{d}_{i:02d}" for i in range(n)]
            olds = [hero_frame(OLD, k)[0] for k in keys]
            news = [hero_frame(SAMPLE, k)[0] for k in keys]
            box = union_box(olds + news)
            for tag, ims in (("old", olds), ("new", news)):
                tiles = [CS.zoom(on_paper(im).convert("RGB").crop(box), 2).quantize(colors=160, method=Image.Quantize.MEDIANCUT)
                         for im in ims]
                p = REVIEW / f"kfix_gif_hero_{an}_{d}_{tag}.gif"
                tiles[0].save(p, save_all=True, append_images=tiles[1:], duration=round(1000 / fps), loop=0, disposal=1)
                out.append(p)
    return out


def review():
    REVIEW.mkdir(parents=True, exist_ok=True)
    blocks = [("主角与三只 P0 妖物修补 · 样张（旧 = assets@2x 现有帧，新 = kfix_sample@2x）", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))]
    blocks += hero_block("主角 walk S（8 帧，红纸灯）", [f"walk_S_{i:02d}" for i in range(8)], [0, 2, 4, 6])
    blocks += hero_block("主角 walk N（8 帧）", [f"walk_N_{i:02d}" for i in range(8)], [0, 2, 4, 6])
    blocks += hero_block("主角 dash S、dash N（各 4 帧）", [f"dash_S_{i:02d}" for i in range(4)] + [f"dash_N_{i:02d}" for i in range(4)],
                         [0, 1, 4, 5])
    blocks += hero_block("主角背面墨氅：idle N / NE / NW 第 0 帧；walk E 第 0 帧（E 向动作不变，只有大氅晕染）",
                         ["idle_N_00", "idle_NE_00", "idle_NW_00", "walk_E_00"], [0, 1, 2, 3])
    blocks += lantern_block()
    blocks += enemy_block()
    sheet = LR.stack(blocks)
    sheet.save(REVIEW / "kfix_sample.png")
    print("写出", REVIEW / "kfix_sample.png", sheet.size)
    for p in gifs():
        print("写出", p)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "review"
    if mode == "render":
        render()
        review()
    elif mode == "review":
        review()
    else:
        print(__doc__)
