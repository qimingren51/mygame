"""快速看图：每张插画并排放 1 倍（268×201）和 2 倍（536×402），带五行印和品阶签。

在仓库根目录：art/.venv/bin/python <本文件> [--draft] [--out 路径] id ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cardrev as C  # noqa: E402

TMP = Path("art/out/_card_tmp")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "look.png"))
    a = ap.parse_args()
    tiles = []
    for cid in a.ids:
        if a.draft:
            src = TMP / f"draft_card_art_{cid}.png"
            tmpdir = Path(__file__).resolve().parent / "_look"
            tmpdir.mkdir(exist_ok=True)
            Image.open(src).save(tmpdir / f"card_art_{cid}.png")
            d = tmpdir
        else:
            d = C.REVIEW
        one = C.art_block(cid, 1, d)
        two = C.art_block(cid, 2, d)
        t = Image.new("RGBA", (one.width + two.width + 30, two.height + 10), (24, 26, 34, 255))
        t.alpha_composite(one, (5, 5))
        t.alpha_composite(two, (one.width + 20, 5))
        tiles.append(t)
    W = max(t.width for t in tiles)
    H = sum(t.height for t in tiles)
    out = Image.new("RGBA", (W, H), (24, 26, 34, 255))
    y = 0
    for t in tiles:
        out.alpha_composite(t, (0, y))
        y += t.height
    out.convert("RGB").save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
