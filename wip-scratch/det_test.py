import sys, os
os.environ["LANTERN_ART_DENSITY"]="2"
sys.path.insert(0,'/home/user/mygame/art/render')
import title_hero as T
from style import bstyle as B
orig = B.setup_render
mode = sys.argv[1]
def sr(px, samples=16, threads=None):
    return orig(px, samples, threads=1 if mode == "1" else None)
B.setup_render = sr
from PIL import Image
R, pts, size = T._render("hero_back", *T.HERO_FRAME_M, (0.0, 0.0, 1.15), T.build_hero_back)
Image.fromarray(R["rgba"]).save(sys.argv[2])
print(R["time_s"])
