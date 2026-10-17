"""燃灯刻度暗格提亮前后对比：头像章 + 十二格（8 亮 4 暗），1080p（1:1）和 720p（×2/3），各放大 3 倍看。"""
import math, sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, "art/post")
import ui_lacquer as LQ

SKIN = Path("assets/atlas/skin")
OUT = Path(sys.argv[1])
old_off = Image.open(SKIN / "hud_ult_tick.png").convert("RGBA")
new_off = LQ.make_ult_tick("off")
new_off.save(OUT.parent / "hud_ult_tick_new.png")
on = Image.open(SKIN / "hud_ult_tick_on.png").convert("RGBA")
seal = Image.open(SKIN / "hud_portrait.png").convert("RGBA")
hero = Image.open("/home/user/mygame/art/out/assets@2x/portrait/portrait_hero.png").convert("RGBA")

def disc(off, k):
    """逻辑尺寸 × k 的头像章（k=1 → 1080p，k=2/3 → 720p），先按 4 倍画再缩。"""
    S = 4 * k
    N = round(104 * S)
    im = Image.new("RGBA", (N + 40, N + 40), (14, 16, 22, 255))
    h = round(92 * S)
    im.alpha_composite(hero.resize((h, h), Image.LANCZOS), (20 + (N - h) // 2, 20 + (N - h) // 2))
    im.alpha_composite(seal.resize((N, N), Image.LANCZOS), (20, 20))
    r = (52 - 5 - 3.5) * S
    for i in range(12):
        a = 2 * math.pi * i / 12
        t = (on if i < 8 else off).resize((round(17 * S), round(10 * S)), Image.LANCZOS).rotate(-math.degrees(a), resample=Image.BICUBIC, expand=True)
        cx, cy = 20 + N / 2 + r * math.sin(a), 20 + N / 2 - r * math.cos(a)
        im.alpha_composite(t, (round(cx - t.width / 2), round(cy - t.height / 2)))
    return im.resize((round(im.width / 4), round(im.height / 4)), Image.LANCZOS)

tiles = []
for k in (1.0, 2 / 3):
    for off in (old_off, new_off):
        d = disc(off, k)
        tiles.append(d.resize((d.width * 3, d.height * 3), Image.NEAREST))
W = sum(t.width for t in tiles) + 50
H = max(t.height for t in tiles) + 40
sheet = Image.new("RGB", (W, H), (30, 32, 40))
x = 10
dr = ImageDraw.Draw(sheet)
for t, lab in zip(tiles, ("1080p 旧", "1080p 新", "720p 旧", "720p 新")):
    sheet.paste(t.convert("RGB"), (x, 30))
    x += t.width + 10
sheet.save(OUT)
print(OUT)
