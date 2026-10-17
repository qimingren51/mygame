"""省额度的审图：只拼 1 倍（268×201，带五行印、品阶签）的缩略图，每行 cols 张。

在仓库根目录：art/.venv/bin/python <本文件> [--draft] [--cols 4] [--out 路径] id ...
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
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "thumbs.png"))
    a = ap.parse_args()
    tiles = []
    for cid in a.ids:
        d = C.REVIEW
        if a.draft:
            d = Path(__file__).resolve().parent / "_look"
            d.mkdir(exist_ok=True)
            Image.open(TMP / f"draft_card_art_{cid}.png").save(d / f"card_art_{cid}.png")
        tiles.append(C.art_block(cid, 1, d))
    tw, th = max(t.width for t in tiles), max(t.height for t in tiles)
    cols = min(a.cols, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGBA", (cols * (tw + 6) + 6, rows * (th + 6) + 6), (24, 26, 34, 255))
    for i, t in enumerate(tiles):
        out.alpha_composite(t, (6 + (i % cols) * (tw + 6), 6 + (i // cols) * (th + 6)))
    out.convert("RGB").save(a.out)
    print(a.out, out.size)


if __name__ == "__main__":
    main()
