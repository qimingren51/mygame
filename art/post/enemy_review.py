#!/usr/bin/env python3
"""重做妖物（精修三维）的审图：读 art/out/assets@2x/ 里的新帧，和 art/out/assets@2x_old/ 里备份的现版对比。

    art/.venv/bin/python art/post/enemy_review.py b1 shade fox      # 第一批：影妖、赤面狐
    art/.venv/bin/python art/post/enemy_review.py b2 fox:b1 wisp    # “素材:批”：拿 out/assets@2x_<批>/ 里那一版对比（改过的）
输出到 art/out/review@2x/：
  redo_<批>_lineup.png   主角 + 每只妖物的现版、新版排成一排：白天纸面、月夜（灯下）、月夜（暗处）三排
  redo_<批>_ingame.png   1080p 游戏里的实际大小（1 单位 ≈ 2.57 像素）：月夜场景，主角提灯在中间，妖物围上来；下面一条白天
  redo_<批>_zoom3.png    每只新版一帧，3 倍放大（最近邻）
  redo_<素材>_<动画>.gif  新版每个动画的动图（宣纸底、2 倍；出手动作在蓄力帧多停一下）
月夜：游戏把画面乘上光照图（环境色 + 灯光），再把发光层叠在暗层之上（HDR 1.5 倍、辉光）。这里在线性空间照做，
环境色取月光蓝 #4A5578～#5A6688 的中间 #525E80，灯笼暖光 #FFC27A。悬浮的妖物照游戏抬高 4 单位。
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")
HERE = Path(__file__).resolve().parent
ART = HERE.parent
for p in (ART, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from style import style as S  # noqa: E402
import contact_sheet as CS  # noqa: E402
import postprocess as PP  # noqa: E402
from ui_fonts import font  # noqa: E402

A2 = ART / "out" / "assets@2x"
OLD = ART / "out" / "assets@2x_old"
REVIEW = ART / "out" / "review@2x"
AMBIENT = "#525E80"
LANTERN = S.LANTERN_LIGHT
EMIT_HDR = 1.5
INGAME = 2.57 / 4.0  # 1080p：1 单位约 2.57 像素；素材 4 像素 / 单位
FLOAT_LIFT = 4.0  # 游戏给悬浮妖物抬高的单位（crates/view/src/actors.rs）
CN = {"shade": "影妖", "wisp": "疾影", "golem": "石妖", "fox": "赤面狐", "fox_wisp": "狐火", "bamboo_wraith": "竹魅",
      "taofeng_fox": "讨封狐", "ghoul": "青面鬼", "stonelord": "石将", "toad": "金蟾", "boss": "九尾"}


def lin(x):
    x = np.asarray(x, np.float64)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def hexv(h):
    return np.array(S.hex_to_rgb(h), np.float64) / 255.0


def asset(path):
    A = CS.load_asset(path)
    dflt = A["meta"].get("default_anim") or next(iter(A["meta"]["anims"]))
    A["pick"] = next(f for f in A["frames"] if f["anim"] == dflt)
    return A


def hero_frame(key="idle_E_00"):
    H = CS.load_asset(A2 / "hero")
    Lr = CS.load_asset(A2 / "lantern_red")
    hf = next(f for f in H["frames"] if f["key"] == key)
    lf = next(f for f in Lr["frames"] if f["key"] == key)
    im = hf["rgba"].copy()
    im.alpha_composite(lf["rgba"])
    return {"meta": H["meta"], "pick": {"rgba": im, "emit": lf["emit"], "sockets": hf["sockets"], "key": key}}


class Scene:
    """一张画布：白天的颜色 + 发光层（线性，已乘 alpha）+ 灯。"""

    def __init__(self, w, h, seed=3, blotches=0):
        self.w, self.h = w, h
        self.day = CS.paper(w, h, seed=seed, blotches=blotches)
        self.emit = np.zeros((h, w, 3), np.float64)
        self.lights = []

    def put(self, A, at, scale=1.0, mirror=False, frame=None, shadow=True):
        f = frame or A["pick"]
        meta = A["meta"]
        im, em = f["rgba"], f.get("emit")
        W, H = meta["size"]
        ax, ay = meta["anchor"][0] * W, meta["anchor"][1] * H
        lift = FLOAT_LIFT * meta.get("px_per_unit", 4.0) * scale if meta.get("floating") else 0.0
        if mirror:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
            em = em.transpose(Image.FLIP_LEFT_RIGHT) if em is not None else None
            ax = W - ax
        if scale != 1.0:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            em = em.resize((round(em.width * scale), round(em.height * scale)), Image.LANCZOS) if em is not None else None
            ax, ay = ax * scale, ay * scale
        if shadow:
            r = meta.get("shadow_radius_px", 14 * S.DENSITY) * scale
            sh = Image.new("L", (self.w, self.h), 0)
            ImageDraw.Draw(sh).ellipse([at[0] - r, at[1] - r * 0.36, at[0] + r, at[1] + r * 0.36],
                                       fill=46 if meta.get("floating") else 64)
            sh = sh.filter(ImageFilter.GaussianBlur(2.0 * S.DENSITY * scale))
            self.day.paste(Image.new("RGBA", (self.w, self.h), S.hex_to_rgb(S.INK["zhong"]) + (255,)), (0, 0), sh)
        x0, y0 = round(at[0] - ax), round(at[1] - ay - lift)
        # 本体先盖住它后面的发光，再叠上自己的发光
        a = np.asarray(im, np.float64)[..., 3] / 255.0
        xs0, ys0 = max(0, x0), max(0, y0)
        xs1, ys1 = min(self.w, x0 + im.width), min(self.h, y0 + im.height)
        if xs1 > xs0 and ys1 > ys0:
            sub = a[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
            self.emit[ys0:ys1, xs0:xs1] *= (1 - sub[..., None])
        self.day.alpha_composite(im, (x0, y0))
        if em is not None and xs1 > xs0 and ys1 > ys0:
            e = np.asarray(em, np.float64) / 255.0
            sub = e[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
            self.emit[ys0:ys1, xs0:xs1] = self.emit[ys0:ys1, xs0:xs1] * (1 - sub[..., 3:4]) + lin(sub[..., :3]) * sub[..., 3:4]
        sock = f.get("sockets", {}).get("lantern")
        return (at[0] + (sock[0] * (-1 if mirror else 1)) * scale, at[1] + sock[1] * scale) if sock else None

    def light(self, x, y, r, color=LANTERN, gain=1.0):
        self.lights.append((x, y, r, color, gain))

    def night(self, ambient=AMBIENT, bloom=2.5):
        d = lin(np.asarray(self.day.convert("RGB"), np.float64) / 255.0)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float64)
        lm = np.ones((self.h, self.w, 3)) * lin(hexv(ambient))
        for x, y, r, c, g in self.lights:
            f = np.clip(1 - ((xx - x) ** 2 + (yy - y) ** 2) / (r * r), 0, 1) ** 2
            lm = lm + f[..., None] * lin(hexv(c)) * g
        out = d * lm
        e = self.emit * EMIT_HDR
        ea = np.clip(self.emit.max(-1, keepdims=True) * 1.6, 0, 1)
        out = out * (1 - ea * 0.6) + e
        glow = np.stack([PP.gaussian_blur(e[..., c], bloom * S.DENSITY) for c in range(3)], -1)
        out = out + glow * 0.6
        return Image.fromarray((srgb(out) * 255 + 0.5).astype(np.uint8), "RGB")


def label(img, xy, text, size=26, color=S.INK["nong"], anchor="ma"):
    ImageDraw.Draw(img).text(xy, text, font=font("serif", size), fill=S.hex_to_rgb(color), anchor=anchor)


def col_w(meta):
    return int(meta["size"][0] * 0.95) + 20


# ================================================================ 审图
def lineup(names, tag, olds=None):
    hero = hero_frame()
    cols = [("主角", hero)]
    for n in names:
        od, lab = (ART / "out" / f"assets@2x_{olds[n]}", f"{olds[n]} 版") if olds and olds.get(n) else (OLD, "现版")
        if (od / n / "meta.json").exists():
            cols.append((f"{CN.get(n, n)} · {lab}", asset(od / n)))
        cols.append((f"{CN.get(n, n)} · 新版", asset(A2 / n)))
    widths = [max(220, col_w(A["meta"])) for _, A in cols]
    Hrow = max(300, max(int(A["meta"]["size"][1] * A["meta"]["anchor"][1]) + 60 for _, A in cols))
    W = sum(widths) + 40
    rows = []
    for mode in ("day", "lit", "dark"):
        sc = Scene(W, Hrow, seed=5)
        x = 20
        for (name, A), w in zip(cols, widths):
            at = (x + w * 0.5, Hrow - 34)
            lp = sc.put(A, at)
            if mode == "lit":
                sc.light(*(lp if lp else (at[0] + 40, at[1] - 110)), 230)
            elif mode == "dark" and lp:
                sc.light(lp[0], lp[1], 120, gain=0.9)
            x += w
        rows.append((mode, sc.day.convert("RGB") if mode == "day" else sc.night()))
    out = Image.new("RGB", (W + 150, Hrow * 3 + 60), S.hex_to_rgb(S.PAPER))
    x = 150 + 20
    for (name, A), w in zip(cols, widths):
        label(out, (x + w * 0.5, 14), name, 22)
        x += w
    for k, (mode, img) in enumerate(rows):
        out.paste(img, (150, 50 + k * Hrow))
        label(out, (75, 50 + k * Hrow + Hrow // 2 - 14), {"day": "白天纸面", "lit": "月夜 · 灯下", "dark": "月夜 · 暗处"}[mode], 24)
    out.save(REVIEW / f"redo_{tag}_lineup.png")


def zoom3(names, tag):
    tiles = []
    for n in names:
        A = asset(A2 / n)
        im = A["pick"]["rgba"]
        bg = CS.paper(im.width, im.height, seed=2)
        bg.alpha_composite(im)
        tiles.append(bg.convert("RGB").resize((im.width * 3, im.height * 3), Image.NEAREST))
    W = sum(t.width for t in tiles) + 20 * (len(tiles) - 1)
    H = max(t.height for t in tiles)
    out = Image.new("RGB", (W, H), S.hex_to_rgb(S.PAPER))
    x = 0
    for t in tiles:
        out.paste(t, (x, H - t.height))
        x += t.width + 20
    out.save(REVIEW / f"redo_{tag}_zoom3.png")


def gifs(names):
    for n in names:
        A = CS.load_asset(A2 / n)
        for an, info in A["meta"]["anims"].items():
            frames = [f["rgba"] for f in A["frames"] if f["anim"] == an]
            wu = info.get("windup_frames", 0)
            if info.get("loop") is False:  # 出手动作：蓄力的最后一帧多停一会儿（游戏在预警期间停在这一帧），播完再停一下
                frames = frames[:wu] + [frames[max(wu - 1, 0)]] * 5 + frames[wu:] + [frames[-1]] * 4
            CS.gif(frames, REVIEW / f"redo_{n}_{an}.gif", info["fps"], zoom_k=1 if A["meta"]["size"][0] > 400 else 2)


def ingame(names, tag):
    """1080p 实际大小：月夜，主角提灯在中间，这一批的妖物围上来（小妖成群、精英两只、夜主一只）；下面一条白天。"""
    hero = hero_frame()
    out_w, out_h = 1920, 1080
    sc = Scene(out_w, out_h, seed=11, blotches=6)
    cx, cy = out_w * 0.5, out_h * 0.55
    rng = np.random.default_rng(4)
    spots = [(cy, "hero", cx, None, 0)]
    for n in names:
        A = CS.load_asset(A2 / n)
        cat = A["meta"].get("category")
        count = 9 if cat == "enemy" else (1 if cat == "boss" else 2)
        for k in range(count):
            ang = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(120, 520) if cat != "boss" else 560
            x, y = cx + r * math.cos(ang) * 1.3, cy + r * math.sin(ang) * 0.62
            spots.append((y, n, x, A, k))
    lp = None
    for y, n, x, A, k in sorted(spots, key=lambda s: s[0]):
        if n == "hero":
            lp = sc.put(hero, (x, y), INGAME)
            continue
        anims = list(A["meta"]["anims"])
        an = anims[k % len(anims)] if len(anims) > 1 and k % 3 == 2 else (A["meta"].get("default_anim") or anims[0])
        frs = [f for f in A["frames"] if f["anim"] == an]
        sc.put(A, (x, y), INGAME, mirror=x > cx, frame=frs[(k * 3) % len(frs)])
    sc.light(lp[0], lp[1], 200, gain=1.15)
    night = sc.night()
    label(night, (24, 18), "新版 · 1080p 实际大小 · 月夜（主角提灯；暗处的妖物靠月光和自发光）", 26, color="#E8E2D2", anchor="la")
    day_h = 300
    day = Scene(out_w, day_h, seed=13)
    x = 70
    day.put(hero, (x, day_h - 40), INGAME)
    x += 120
    for n in names:
        A = CS.load_asset(A2 / n)
        for an in A["meta"]["anims"]:
            frs = [f for f in A["frames"] if f["anim"] == an]
            for f in frs[:: max(1, len(frs) // 3)][:3]:
                w = A["meta"]["size"][0] * INGAME
                day.put(A, (x + w * 0.4, day_h - 40), INGAME, frame=f)
                x += max(w * 0.75, 70)
            x += 30
    dimg = day.day.convert("RGB")
    label(dimg, (20, 14), "白天纸面：各动作抽几帧（1080p 实际大小）", 24, anchor="la")
    out = Image.new("RGB", (out_w, out_h + day_h), (0, 0, 0))
    out.paste(night, (0, 0))
    out.paste(dimg, (0, out_h))
    out.save(REVIEW / f"redo_{tag}_ingame.png")


def main(argv):
    tag = argv[0]
    olds = {a.split(":")[0]: a.split(":")[1] for a in argv[1:] if ":" in a}
    names = [a.split(":")[0] for a in argv[1:]]
    REVIEW.mkdir(parents=True, exist_ok=True)
    lineup(names, tag, olds)
    zoom3(names, tag)
    gifs(names)
    ingame(names, tag)
    print("审图：", ", ".join(str(REVIEW / f"redo_{tag}_{k}.png") for k in ("lineup", "ingame", "zoom3")),
          "以及", ", ".join(f"redo_{n}_*.gif" for n in names))


if __name__ == "__main__":
    main(sys.argv[1:])
