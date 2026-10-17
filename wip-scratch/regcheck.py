"""按 check_asset 的规则量配准漂移和身高（只对给定文件夹里有的帧）。"""
import sys, json, re
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, "/home/user/mygame/art/post"); sys.path.insert(0, "/home/user/mygame/art")
import check_asset as C
d = Path(sys.argv[1])
meta = json.loads((d / "meta.json").read_text())
W, H = meta["size"]; ax, ay = meta["anchor"][0] * W, meta["anchor"][1] * H
groups = {}
for p in sorted(d.glob("*.png")):
    m = re.match(r"^([a-z]+)_([A-Z]+)_(\d\d)\.png$", p.name)
    if m:
        groups.setdefault((m[1], m[2]), []).append(np.asarray(Image.open(p))[..., 3] / 255.0)
for (an, dr), fr in sorted(groups.items()):
    ms = [C.measure(a, ax, ay) for a in fr]
    gh = float(np.median([m["height"] for m in ms]))
    band = (ay - C.BAND[1] * gh, ay - C.BAND[0] * gh)
    xs = np.array([C.measure(a, ax, ay, band)["reg_x"] for a in fr]); ys = np.array([m["reg_y"] for m in ms])
    hs = np.array([m["height"] for m in ms]); bt = np.array([m["bottom"] for m in ms])
    dx, dy = np.abs(xs - np.median(xs)).max(), np.abs(ys - np.median(ys)).max()
    hd = np.abs(hs - gh).max() / gh
    flag = " <<<" if dx > 3 or dy > 3 or hd > 0.04 else ""
    print(f"{an}_{dr}: n={len(fr)} drift x {dx:.2f} y {dy:.2f}  height med {gh:.0f} dev {hd:.1%}  bottom {bt.min():.0f}..{bt.max():.0f}{flag}")
