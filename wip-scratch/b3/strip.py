"""素材文件夹 → 每个动画一行的帧条（纸色底，锚点画一个小十字）。用法：strip.py 输出.png 文件夹 [缩放]"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw
out, folder = sys.argv[1], Path(sys.argv[2])
k = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
m = json.loads((folder / "meta.json").read_text())
W, H = m["size"]; ax, ay = m["anchor"][0] * W, m["anchor"][1] * H
rows = []
for an, info in m["anims"].items():
    tiles = []
    for i in range(info["frames"]):
        im = Image.open(folder / f"{an}_E_{i:02d}.png").convert("RGBA")
        bg = Image.new("RGBA", im.size, (236, 228, 207, 255))
        bg.alpha_composite(im)
        d = ImageDraw.Draw(bg)
        d.line([ax - 6, ay, ax + 6, ay], fill=(200, 0, 0, 255)); d.line([ax, ay - 6, ax, ay + 6], fill=(200, 0, 0, 255))
        for s, by in m.get("sockets", {}).items():
            pts = by.get(an, {}).get("E", [])
            if i < len(pts):
                x, y = ax + pts[i][0], ay + pts[i][1]
                d.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(0, 0, 255, 255))
        tiles.append(bg.convert("RGB"))
    row = Image.new("RGB", (W * len(tiles), H), (200, 200, 200))
    for i, t in enumerate(tiles):
        row.paste(t, (i * W, 0))
    rows.append(row)
big = Image.new("RGB", (max(r.width for r in rows), H * len(rows)), (180, 180, 180))
for j, r in enumerate(rows):
    big.paste(r, (0, j * H))
big = big.resize((round(big.width * k), round(big.height * k)), Image.LANCZOS)
big.save(out)
print(big.size)
