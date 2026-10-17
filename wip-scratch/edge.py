"""dash/death 全朝向的包围盒余量（1 倍密度快速检查）。"""
import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, hero, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
F = S.FRAME["hero"]
B.reset_scene(); B.setup_render(F, samples=4); B.setup_camera(F); B.setup_freestyle()
root, parts, socks = hero.build_hero()
worst = []
tiles = []
for anim, n in (("dash", 4), ("death", 6)):
    for d in S.DIRS:
        for fr in range(n):
            parts["dir"] = d
            B.set_direction(root, d)
            hero.pose_hero(parts, anim, fr, n)
            L = B.render_layers(OUT + "/edge")
            r = P.process_layers(L, "hero")
            a = r["rgba"][..., 3]
            ys, xs = np.where(a > 8)
            m = min(xs.min(), F - 1 - xs.max(), ys.min(), F - 1 - ys.max())
            worst.append((m, f"{anim}_{d}_{fr:02d}", xs.min(), xs.max(), ys.min(), ys.max()))
            if anim == "death" and d in ("S", "E", "N") or (anim == "dash" and d in ("E", "S") and fr < 2):
                tiles.append(r["rgba"])
worst.sort()
for w in worst[:10]:
    print("margin %d px  %s  x[%d,%d] y[%d,%d]" % w)
sheet = Image.new("RGBA", (F * len(tiles), F), tuple(S.hex_to_rgb(S.PAPER)) + (255,))
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (F * i, 0))
sheet.convert("RGB").save(OUT + "/edge_sheet.png")
