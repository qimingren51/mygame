import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, hero, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
d = sys.argv[1] if len(sys.argv) > 1 else "S"
B.reset_scene(); B.setup_render(128); B.setup_camera(128); B.setup_freestyle()
root, parts, sockets = hero.build_hero()
hero.pose_hero(parts, sys.argv[2], int(sys.argv[3]), 8) if len(sys.argv) > 2 else None
B.set_direction(root, d)
L = B.render_layers(OUT + "/th")
f = L["fill"]; rgb, a = P.unpremultiply(f)
fill = P.linear_to_srgb(rgb) * 255
la = L["lines"][..., 3]
paper = P.hex_rgb(S.PAPER)
img = paper * (1 - a[..., None]) + fill * a[..., None]
img = img * (1 - la[..., None]) + P.hex_rgb(S.LINE_COLOR) * la[..., None]
fillonly = paper * (1 - a[..., None]) + fill * a[..., None]
both = np.concatenate([fillonly, img], 1)[100:470, :]
Image.fromarray(both.astype(np.uint8)).save(OUT + "/hero_hi.png")
