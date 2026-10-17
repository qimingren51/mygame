"""快速看图：渲几帧（不写素材文件夹）→ 一张对比图：主角 + 这几帧；白天纸面、月夜灯下、1080p 实际大小（×2 最近邻）。
用法（仓库根目录）：
  LANTERN_ART_DENSITY=2 art/.venv/bin/python <本文件> 素材 输出.png move:0,2,4 shoot:1,2 [--keep 目录]
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path[:0] = ["art", "art/models", "art/post", "art/render"]
import importlib  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import enemies_v2 as EV  # noqa: E402
from style import style as S  # noqa: E402

name, out = sys.argv[1], Path(sys.argv[2])
keep = None
specs = []
args = sys.argv[3:]
while args:
    a = args.pop(0)
    if a == "--keep":
        keep = Path(args.pop(0))
    else:
        an, fr = a.split(":")
        specs.append((an, [int(x) for x in fr.split(",")]))

PAPER = np.array(S.hex_to_rgb(S.PAPER)) / 255.0
NIGHT = np.array([0x52, 0x5E, 0x80]) / 255.0
LAMP = np.array([0xFF, 0xC2, 0x7A]) / 255.0


def s2l(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def l2s(c):
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)


def render_frames():
    from style import bstyle as B
    import v2kit as V2K
    cfg = EV.V2[name]
    F = EV._setup(name)
    M = importlib.import_module(cfg["module"])
    root, parts, socks = getattr(M, cfg["build"])()
    pose = getattr(M, cfg["pose"])
    nmap = {an: n for an, n, *_ in cfg["anims"]}
    res = []
    with B.render_lock():
        for an, frs in specs:
            for i in frs:
                B.set_direction(root, "E")
                pose(parts, an, i, nmap[an])
                L = V2K.render(EV.TMP / f"look_{name}_{an}_{i}")
                rgba, emit, flash = V2K.post(L, name, cfg["glow"], seed=i + 7)
                sk = {s: B.project_point(socks[s].matrix_world.translation, F) for s in socks}
                res.append((f"{an}{i}", rgba, emit, sk))
                if keep:
                    keep.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(rgba).save(keep / f"{an}_E_{i:02d}.png")
                    Image.fromarray(emit).save(keep / f"{an}_E_{i:02d}_emit.png")
    for p in EV.TMP.glob("*.exr"):
        p.unlink()
    return res, F, cfg["anchor"]


def hero():
    A = Path("art/out/assets@2x")
    h = Image.open(A / "hero/idle_E_00.png").convert("RGBA")
    h.alpha_composite(Image.open(A / "lantern_red/idle_E_00.png").convert("RGBA"))
    e = Image.open(A / "lantern_red/idle_E_00_emit.png").convert("RGBA")
    return np.asarray(h), np.asarray(e), (0.5, 0.875)


def comp(rgba, emit, mode):
    im = rgba.astype(np.float64) / 255.0
    em = emit.astype(np.float64) / 255.0
    a = im[..., 3:4]
    if mode == "day":
        return im[..., :3] * a + PAPER * (1 - a)
    lin = s2l(im[..., :3])
    ground = s2l(PAPER) * (1 - a)
    base = lin * a + ground
    light = s2l(NIGHT) + (s2l(LAMP) * 0.55 if mode == "lit" else 0.0)
    out_ = base * light + s2l(em[..., :3]) * em[..., 3:4] * 1.5
    return l2s(np.clip(out_, 0, 1))


res, F, anc = render_frames()
H_rgba, H_emit, H_anc = hero()
tiles = [("hero", H_rgba, H_emit, H_anc, {})] + [(k, r, e, anc, sk) for k, r, e, sk in res]
# 统一按锚点对齐到同一条地平线
top = max(int(round(t[3][1] * t[1].shape[0])) for t in tiles)
bot = max(t[1].shape[0] - int(round(t[3][1] * t[1].shape[0])) for t in tiles)
rows = []
for mode in ("day", "lit", "dark"):
    row = []
    for k, r, e, an, sk in tiles:
        img = comp(r, e, mode)
        h, w = img.shape[:2]
        ay = int(round(an[1] * h))
        canvas = np.ones((top + bot, w, 3)) * (PAPER if mode == "day" else l2s(s2l(PAPER) * s2l(NIGHT)))
        canvas[top - ay: top - ay + h] = img
        if mode == "day" and sk:  # 挂点：小十字
            for s, (x, y) in sk.items():
                cx, cy = int(w * an[0] + x), int(top + y)
                c = np.array([0.9, 0.1, 0.1]) if s == "eyes" else np.array([0.1, 0.2, 0.9])
                canvas[max(cy - 4, 0):cy + 5, cx] = c
                canvas[cy, max(cx - 4, 0):cx + 5] = c
        row.append(canvas)
    rows.append(np.concatenate(row, 1))
big = np.concatenate(rows, 0)
img = Image.fromarray((np.clip(big, 0, 1) * 255).astype(np.uint8))
# 1080p 实际大小（2.57 像素 / 单位）：白天、灯下两排，×1 和 ×2 两张
img.save(out)
small = img.crop((0, 0, img.width, (top + bot) * 2))
small = small.resize((round(small.width * 2.57 / 4), round(small.height * 2.57 / 4)), Image.LANCZOS)
small.save(str(out).replace(".png", "_1080.png"))
small.resize((small.width * 2, small.height * 2), Image.NEAREST).save(str(out).replace(".png", "_1080x2.png"))
print(out, img.size, {k: {s: (round(x, 1), round(y, 1)) for s, (x, y) in sk.items()} for k, _, _, _, sk in tiles[1:]})
