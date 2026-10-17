import json, sys, numpy as np
from PIL import Image
from pathlib import Path
d = Path(sys.argv[1])
m = json.loads((d/"meta.json").read_text())
W,H = m["size"]; ax,ay = m["anchor"][0]*W, m["anchor"][1]*H
res=[]
for an,a in m["anims"].items():
    for di in a["dirs"]:
        for i in range(a["frames"]):
            p = d/f"{an}_{di}_{i:02d}_emit.png"
            if not p.exists(): res.append((an,di,i,None,0)); continue
            e = np.asarray(Image.open(p))[...,3]/255.
            s = e.sum()
            if s<1e-6: res.append((an,di,i,None,0)); continue
            ys,xs = np.mgrid[0:H,0:W]
            cx,cy = (e*(xs+.5)).sum()/s-ax, (e*(ys+.5)).sum()/s-ay
            sx,sy = m["sockets"]["lantern"][an][di][i]
            res.append((an,di,i,float(np.hypot(cx-sx,cy-sy)),float(s)))
bad=[r for r in res if r[3] is None or r[3]>2]
print("n",len(res),"over2",len(bad))
for r in sorted(res,key=lambda r:-(r[3] or 99))[:25]: print(r)
import collections
print("max by anim", {an: round(max((r[3] or 0) for r in res if r[0]==an),2) for an in m["anims"]})
ref = np.median([r[4] for r in res if r[0]=="idle"])
print("ref idle median area", ref)
for r in sorted(res,key=lambda r:-(r[3] or 99)):
    if r[0]!="death" and r[3] and r[3]>1.0: print(r[:3], round(r[3],2), "area%", round(r[4]/ref*100))
