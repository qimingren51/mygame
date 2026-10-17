"""竹魅的二维草图：骨架（竹竿按半径画粗线）、头上竹叶、空、眼。看构图用。用法：bw_sketch.py 输出.png idle:0 move:0 ..."""
import math
import sys

sys.path[:0] = ["art", "art/models", "art/post"]
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import bamboo_v2 as BW  # noqa: E402

out = sys.argv[1]
specs = [(a.split(":")[0], int(a.split(":")[1])) for a in sys.argv[2:]]
K = 6.0  # 像素 / 单位
W, H = int(80 * K), int(80 * K)
AX, AY = W / 2, H * 0.875


def P(x, y):
    return (AX + x * K, AY - y * K)


def poly_leaf(c, w):
    c = np.asarray(c)
    tan = np.gradient(c, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    L = c + nrm * (w / 2)[:, None]
    R = c - nrm * (w / 2)[:, None]
    return [P(*q) for q in np.vstack([L, R[::-1]])]


tiles = []
for an, i in specs:
    n = {a: nn for a, nn, *_ in [("idle", 4), ("move", 6), ("shoot", 5)]}[an]
    p = BW.pose_params(an, i, n)
    sk = BW.skeleton(p)
    im = Image.new("RGB", (W, H), (236, 228, 207))
    d = ImageDraw.Draw(im)
    d.line([P(-40, 0), P(40, 0)], fill=(180, 170, 150))
    lay, rot, a = BW.head_layout(sk["neck"], sk["head_ang"], p["ph"], p["gust"])

    def culm_line(pts, r, col):
        for q0, q1 in zip(pts[:-1], pts[1:]):
            d.line([P(*q0), P(*q1)], fill=col, width=max(1, int(2 * r * K)))
    # 远的先画
    for _, _, lat, tone in []:
        pass
    for c, w, lat, tone in lay:
        if lat > 0.0:
            d.polygon(poly_leaf(c, w), fill=(60, 90, 66) if tone == "mid" else (30, 40, 32))
    culm_line(sk["legs"][True][:3], BW.R_THIGH, (60, 90, 60))
    culm_line(sk["arms"][True][:3], BW.R_UPPER, (60, 90, 60))
    hip, waist, sh, neck = (np.asarray(sk[k]) for k in ("hip", "waist", "shoulder", "neck"))
    culm_line([hip, waist, sh, neck], BW.R_MAIN, (90, 140, 80))
    hc = rot(*BW.HOLLOW_C)
    rx, ry = BW.HOLLOW_R
    d.ellipse([P(hc[0] - rx, hc[1] + ry)[0], P(hc[0] - rx, hc[1] + ry)[1], P(hc[0] + rx, hc[1] - ry)[0],
               P(hc[0] + rx, hc[1] - ry)[1]], fill=(20, 20, 16))
    for (ex, ey), hl, hh, tilt, lat in BW.EYES:
        q = rot(ex, ey)
        ang = math.radians(tilt)
        pts = [P(q[0] + hl * math.cos(t) * math.cos(ang) - hh * math.sin(t) * math.sin(ang),
                 q[1] + hl * math.cos(t) * math.sin(ang) + hh * math.sin(t) * math.cos(ang)) for t in np.linspace(0, 6.28, 20)]
        d.polygon(pts, fill=(155, 245, 201))
    for c, w, lat, tone in lay:
        if lat <= 0.0:
            d.polygon(poly_leaf(c, w), fill=(80, 115, 82) if tone == "mid" else (24, 32, 26))
    culm_line(sk["legs"][False][:3], BW.R_THIGH, (110, 160, 95))
    culm_line(sk["arms"][False][:3], BW.R_UPPER, (110, 160, 95))
    d.text((6, 6), f"{an}{i}", fill=(0, 0, 0))
    tiles.append(im)
big = Image.new("RGB", (W * len(tiles), H), (200, 200, 200))
for k, t in enumerate(tiles):
    big.paste(t, (k * W, 0))
big.save(out)
small = big.resize((round(big.width * 2.57 / K), round(big.height * 2.57 / K)), Image.LANCZOS)
small.save(out.replace(".png", "_1080.png"))
print(big.size)
