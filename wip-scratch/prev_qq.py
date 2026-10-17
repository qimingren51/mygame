"""临时预览：只画青丘地面装饰，铺在纸色上放大看。"""
import sys
import time

sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np
from PIL import Image

import ground_decor as G

SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
t0 = time.time()
items = G.build_qq()
print("build", time.time() - t0)
names = [k for k in items if not k.startswith("qq_wash")] if "--nowash" in sys.argv else list(items)
ims = [items[k][0] for k in names]
pad = 12
Wt = sum(i.width for i in ims) + pad * (len(ims) + 1)
Ht = max(i.height for i in ims) + 2 * pad
bg = Image.new("RGBA", (Wt, Ht), (237, 228, 207, 255))
x = pad
for i in ims:
    bg.alpha_composite(i, (x, pad))
    x += i.width + pad
z = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0].isdigit() else 2
bg = bg.resize((int(Wt * z), int(Ht * z)), Image.LANCZOS)
bg.convert("RGB").save(SP + "prev_qq.png")
for k in names:
    a = np.asarray(items[k][0])
    print(k, items[k][0].size, "max a", a[..., 3].max())
