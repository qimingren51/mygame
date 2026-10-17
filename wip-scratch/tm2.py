# 渲染 boss 全部 8 帧，按 check_asset.measure 打印每帧身高 / 顶 / 配准 x
import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, check_asset as C, numpy as np, fox
F = S.FRAME["boss"]
B.reset_scene(); B.setup_render(F); B.setup_camera(F, anchor=S.BIG_ENEMY_ANCHOR); B.setup_freestyle()
root, parts, socks = fox.build_boss()
ax, ay = S.BIG_ENEMY_ANCHOR[0] * F, S.BIG_ENEMY_ANCHOR[1] * F
for fr in range(8):
    B.set_direction(root, "E"); fox.pose_boss(parts, "move", fr, 8)
    L = B.render_layers("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t/tm2")
    r = P.process_layers(L, "boss"); a = r["rgba"][..., 3] / 255.0
    m = C.measure(a, ax, ay); ys, xs = np.where(a > 0.5)
    print("F", fr, {k: round(v, 1) for k, v in m.items()}, "bbox x", xs.min(), xs.max(), "y", ys.min(), ys.max(), "emit", r["stats"]["emit_px"])
