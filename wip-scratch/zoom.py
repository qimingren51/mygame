"""zoom.py k name... : 把 imgs/ 里的图按 k 倍最近邻放大，纸色底和夜色底各一行。"""
import os, sys
from PIL import Image
SP = os.path.dirname(os.path.abspath(__file__))
k = int(sys.argv[1]); names = sys.argv[2:]
ims = [Image.open(os.path.join(SP, "imgs", n + ".png")).convert("RGBA") for n in names]
ims = [im.resize((im.width * k, im.height * k), Image.NEAREST) for im in ims]
W = sum(im.width for im in ims) + 10 * (len(ims) + 1); H = max(im.height for im in ims)
out = Image.new("RGB", (W, 2 * H + 30), "#EDE4CF")
out.paste((22, 27, 44), (0, H + 20, W, 2 * H + 30))
x = 10
for im in ims:
    out.paste(im, (x, 5), im); out.paste(im, (x, H + 25), im); x += im.width + 10
out.save(os.path.join(SP, "zoom.png")); print(out.size)
