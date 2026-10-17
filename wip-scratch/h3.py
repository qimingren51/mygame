import sys, time
sys.path.insert(0, "/home/user/mygame/art/post")
SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
from PIL import Image
import title_screen as T
img, info = T.paint_title()
print(info)
img.save(SP + "c3.png")
o = Image.open(SP + "old/title.png")
p1 = Image.open(SP + "cand_prev.png") if len(sys.argv) > 1 else None
box = (1040, 590, 1420, 920)
crops = [im.crop(box).resize((760, 660), Image.LANCZOS) for im in ([o, p1, img] if p1 else [o, img])]
c = Image.new("RGB", (770 * len(crops), 660), (255, 255, 255))
for i, cr in enumerate(crops):
    c.paste(cr, (770 * i, 0))
c.save(SP + "c3_hero.png")
