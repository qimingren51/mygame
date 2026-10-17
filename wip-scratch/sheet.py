"""插画审图：一组 id 排成网格（每张缩到 w 宽），下面写 id。用法：python sheet.py out.png w id1 id2 ..."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out, W = sys.argv[1], int(sys.argv[2])
ids = sys.argv[3:]
src = Path("/home/user/mygame/art/out/assets@2x/ui_cards")
H = W * 3 // 4
cols = 5 if len(ids) > 4 else len(ids)
rows = (len(ids) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (W + 8) + 8, rows * (H + 26) + 8), (24, 24, 28))
f = ImageFont.truetype("/home/user/mygame/assets/fonts/NotoSerifSC-subset.ttf", 14)
d = ImageDraw.Draw(sheet)
for i, cid in enumerate(ids):
    p = src / f"card_{cid}.png"
    if not p.exists():
        p = Path("/home/user/mygame/art/out/_card_tmp") / f"draft_card_art_{cid}.png"
    im = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    x, y = 8 + (i % cols) * (W + 8), 8 + (i // cols) * (H + 26)
    sheet.paste(im, (x, y))
    d.text((x + 4, y + H + 4), cid, fill=(220, 220, 220), font=f)
sheet.save(out)
