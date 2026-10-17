"""快速审图：一个素材文件夹 → 3 倍动图 + 游戏尺寸（主角旁边，白天 / 月夜）。"""
import sys, json
sys.path.insert(0, "/home/user/mygame/art"); sys.path.insert(0, "/home/user/mygame/art/post")
from PIL import Image
import numpy as np
import contact_sheet as CS
d = sys.argv[1]; out = sys.argv[2]; anim = sys.argv[3]
A = CS.load_asset(d)
fr = [f for f in A["frames"] if f["anim"] == anim]
fps = A["meta"]["anims"][anim]["fps"]
CS.gif([f["rgba"] for f in fr], out + f"_{anim}.gif", fps, zoom_k=2)
H = CS.load_asset("/home/user/mygame/art/out/assets@2x/hero")
L = CS.load_asset("/home/user/mygame/art/out/assets@2x/lantern_red")
hf = next(f for f in H["frames"] if f["key"] == "idle_E_00"); lf = next(f for f in L["frames"] if f["key"] == "idle_E_00")
hero = hf["rgba"].copy(); hero.alpha_composite(lf["rgba"])
sc = 2.57 / 4
W, Hh = 900, 260
day = CS.paper(W, Hh, seed=4)
emit = np.zeros((Hh, W, 3), np.float32)
def put(im, meta, at, s, em=None):
    ax, ay = meta["anchor"][0] * meta["size"][0], meta["anchor"][1] * meta["size"][1]
    im2 = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    day.alpha_composite(im2, (round(at[0] - ax * s), round(at[1] - ay * s)))
    if em is not None:
        CS.place_emit(emit, {"emit": em}, meta, at, scale=s)
put(hero, H["meta"], (120, 200), sc)
for k, f in enumerate(fr[:4]):
    put(f["rgba"], A["meta"], (260 + k * 90, 200), sc, f["emit"])
for k, f in enumerate(fr[:2]):
    put(f["rgba"], A["meta"], (650 + k * 130, 200), 1.0, f["emit"])
night = CS.night_composite(day, emit, [(120 + 26 * sc * 4, 200 - 110 * sc, 300 * sc, "#FFC27A")])
d_ = np.asarray(day.convert("RGB"), np.float32) / 255
amb = np.array([0x52, 0x5E, 0x80]) / 255
lin = lambda x: np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
srgb = lambda x: np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(np.clip(x, 0, 1), 1 / 2.4) - 0.055)
yy, xx = np.mgrid[0:Hh, 0:W]
lx, ly, R = 120 + 18, 200 - 70, 200
f = np.clip(1 - ((xx - lx) ** 2 + (yy - ly) ** 2) / R ** 2, 0, 1) ** 2
lm = lin(amb)[None, None] + f[..., None] * lin(np.array([0xFF, 0xC2, 0x7A]) / 255)[None, None] * 1.2
o = lin(d_) * lm + lin(np.clip(emit, 0, 1)) * 1.5
o = srgb(np.clip(o, 0, 1))
img = Image.new("RGB", (W, Hh * 2))
img.paste(day.convert("RGB"), (0, 0)); img.paste(Image.fromarray((o * 255).astype(np.uint8)), (0, Hh))
img.save(out + "_ingame.png")
print("ok")
