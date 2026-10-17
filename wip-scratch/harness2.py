"""候选标题画：软纸纹、新远山、写意主角和石灯笼；其他照旧。出 title_candidate 到 scratchpad。"""
import sys
import time

SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
sys.path.insert(0, SP)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import proto_hero as PH  # noqa: E402
import proto_mtn as PM  # noqa: E402

T = PH.T
V, S, col, smoothstep, mixc, blur = T.V, T.S, T.col, T.smoothstep, T.mixc, T.blur
W, H = T.W, T.H
GAIN = (1.6, 2.0)
if "--gain" in sys.argv:
    i = sys.argv.index("--gain")
    GAIN = (float(sys.argv[i + 1]), float(sys.argv[i + 2]))


def paint_title_v2(rng_seed=2026, only_bg=False):
    t0 = time.perf_counter()
    rng = np.random.default_rng(rng_seed)
    P = T.Painting(rng)
    P.rgb = PM.soft_paper_canvas(np.random.default_rng(rng_seed + 1))
    paper0 = P.rgb.copy()
    P.paper0 = paper0
    T.paint_sky(P, rng)
    PM.paint_ranges(P, np.random.default_rng(rng_seed + 2))
    T.paint_ground(P, rng)
    T.paint_ground_detail(P, rng)
    T.paint_rock(P, rng, [(1588, 846), (1622, 806), (1668, 778), (1730, 758), (1800, 742), (1880, 728), (1960, 724)],
                 [(1588, 846), (1572, 920), (1582, 1000), (1566, 1095)],
                 [(1600, 850), (1660, 826), (1740, 808), (1830, 790), (1960, 770)])
    T.paint_pine(P, rng)
    T.paint_grass(P, rng)
    lights = []
    srng = np.random.default_rng(rng_seed + 3)
    for x, y, s in sorted(T.STONE_LANTERNS, key=lambda t: t[1]):
        PH.paint_stone_lantern_ink(P, srng, x, y, s, lights)
    lx, ly = PH.paint_hero_ink(P, np.random.default_rng(rng_seed + 4), lights)
    body, emit, (ex, ey) = T.eyes_layer()
    for x, y, s, flip in T.EYES:
        b, e_ = (body.transpose(Image.FLIP_LEFT_RIGHT), emit.transpose(Image.FLIP_LEFT_RIGHT)) if flip else (body, emit)
        ax = (body.width - ex) if flip else ex
        T.place(P, b, (ax, ey), (x, y), s, e_, emit_gain=2.2, dim=0.3)
    for x, y, s in T.WISPS:
        T.paint_wisp(P, x, y, s, rng, lights)
    mx, my, mr = T.MOON
    dm = np.hypot(P.X - mx, P.Y - my)
    disc = smoothstep(mr + 1.3, mr - 1.3, dm)
    trans = np.clip(P.rgb.mean(-1) / paper0.mean(-1), 0, 1)
    moon_rgb = mixc(col(S.PAPER), np.ones(3), 0.35)
    P.emit += (disc * trans * 0.36)[..., None] * moon_rgb
    P.emit += (np.exp(-np.maximum(dm - mr, 0) / 26.0) * (1 - disc) * 0.10)[..., None] * col("#C8D3E6")
    day = P.rgb.copy()
    lm = T.light_map(P, lights, rng)
    out = P.rgb * np.clip(lm, 0, 1.08)
    e = P.emit
    out = out * (1 - np.clip(e.max(-1, keepdims=True), 0, 1) * 0.6) + e + 0.55 * T.bloom(e, 5.0) + 0.45 * T.bloom(e, 22.0)
    dl = np.hypot(P.X - lx, P.Y - ly)
    out += (np.exp(-(dl / 90.0) ** 2) * 0.12 + np.exp(-(dl / 260.0) ** 2) * 0.05)[..., None] * col(S.LANTERN_LIGHT)
    rel = paper0.mean(-1) / paper0.mean()
    rel = rel - blur(rel, 40.0) / blur(np.ones_like(rel), 40.0) + 1.0
    lum = out.mean(-1, keepdims=True)
    gain = GAIN[0] + GAIN[1] * (1 - smoothstep(0.05, 0.5, lum))
    out = out * (1 + gain * (rel[..., None] - 1)) + 0.02 * (rel[..., None] - 1)
    rx = (P.X - W * 0.62) / (W * 0.62)
    ry = (P.Y - H * 0.48) / (H * 0.62)
    vig = 1 - 0.42 * smoothstep(0.55, 1.35, np.hypot(rx, ry))
    vig *= 1 - 0.22 * smoothstep(0.45, 0.0, P.X / W)
    out = out * vig[..., None]
    img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    dimg = Image.fromarray((np.clip(day, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    print(f"lantern {lx:.1f},{ly:.1f}  {time.perf_counter() - t0:.1f}s")
    return img, dimg


if __name__ == "__main__":
    img, dimg = paint_title_v2()
    img.save(SP + "cand.png")
    dimg.save(SP + "cand_day.png")
