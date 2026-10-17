import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, hero, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
jobs = [tuple(j.split(":")) for j in sys.argv[1].split(",")]
F = S.FRAME["hero"]
B.reset_scene(); B.setup_render(F); B.setup_camera(F); B.setup_freestyle()
root, parts, socks = hero.build_hero()
tiles = []
for anim, d, fr in jobs:
    hero.pose_hero(parts, anim, int(fr), 8 if anim == "walk" else 6)
    B.set_direction(root, d)
    L = B.render_layers(OUT + "/th3")
    rgb, a = P.unpremultiply(L["fill"]); fill = P.linear_to_srgb(rgb) * 255
    la = L["lines"][..., 3]; paper = P.hex_rgb(S.PAPER)
    img = paper * (1 - a[..., None]) + fill * a[..., None]
    img = img * (1 - la[..., None]) + P.hex_rgb(S.LINE_COLOR) * la[..., None]
    tiles.append(img[100:600, 100:540])
Image.fromarray(np.concatenate(tiles, 1).astype(np.uint8)).save(OUT + "/hero_hi.png")
