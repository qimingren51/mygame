"""逐帧统计（审图辅助）：每组每帧的 alpha 峰值、总量、包围盒、质心、二阶矩纵横比、RGB 种类、四边。"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

D = Path(sys.argv[1])
only = set(sys.argv[2:])
meta = json.loads((D / "meta.json").read_text())
groups = {}
for f, info in meta["files"].items():
    groups.setdefault(info["anim"], []).append((info["frame"], f, info))
for g, lst in groups.items():
    if only and g not in only:
        continue
    lst.sort()
    i0 = lst[0][2]
    print("==", g, len(lst), i0["size"], i0["anchor"], i0["blend"], i0["tint"])
    for i, f, info in lst:
        a = np.asarray(Image.open(D / f).convert("RGBA")).astype(float)
        al = a[..., 3]
        h, w = al.shape
        tot = al.sum()
        if tot == 0:
            print(f"  {i}: 空帧")
            continue
        ys, xs = np.nonzero(al)
        cx = (al.sum(0) * np.arange(w)).sum() / tot
        cy = (al.sum(1) * np.arange(h)).sum() / tot
        vx = (al.sum(0) * (np.arange(w) - cx) ** 2).sum() / tot
        vy = (al.sum(1) * (np.arange(h) - cy) ** 2).sum() / tot
        rgb = np.unique(a[..., :3][al > 0], axis=0)
        border = al[0].max() + al[-1].max() + al[:, 0].max() + al[:, -1].max()
        print(f"  {i}: max {al.max():.0f} sum {tot / 255:.0f} bbox x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()} "
              f"c=({cx:.1f},{cy:.1f}) sd_ratio {np.sqrt(vy / vx):.2f} bbox_ratio {(ys.max() - ys.min() + 1) / (xs.max() - xs.min() + 1):.2f} "
              f"rgb {len(rgb)}:{rgb[0].astype(int).tolist()} border {border:.0f}")
