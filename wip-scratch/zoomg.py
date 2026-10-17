import sys, io
import numpy as np
from PIL import Image
sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
import ground_decor as G
items = G.build()
names = sys.argv[2].split(","); scale = int(sys.argv[3])
ims = [items[n][0] for n in names]
Wt = sum(im.width*scale+10 for im in ims)+10; Ht = max(im.height for im in ims)*scale*2+30
out = Image.new("RGB", (Wt, Ht), (120,120,120)); x = 10
for im in ims:
    big = im.resize((im.width*scale, im.height*scale), Image.NEAREST)
    for k, bg in enumerate([(237,228,207),(22,27,44)]):
        t = Image.new("RGB", big.size, bg); t.paste(big,(0,0),big); out.paste(t,(x, 10+k*(max(i.height for i in ims)*scale+10)))
    x += big.width+10
out.save(sys.argv[1])
