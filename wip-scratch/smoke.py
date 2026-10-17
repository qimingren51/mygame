import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART/"models", ART/"post", ART/"render"):
    sys.path.insert(0, str(p))
from style import bstyle as B
from style import style as S
import hero as HERO, portrait as PT
B.reset_scene(); B.setup_render(S.FRAME["hero"]); B.setup_camera(S.FRAME["hero"]); B.setup_freestyle()
root, parts, socks = HERO.build_hero()
print("default lamps", list(parts["lamps"]), parts["lantern"].name)
PT.place_lantern(parts, (-0.4, -0.3, 1.2), scale=0.7)
B.reset_scene(); B.setup_render(S.FRAME["hero"]); B.setup_camera(S.FRAME["hero"]); B.setup_freestyle()
root, parts, socks = HERO.build_hero(lamps=("red", "mirror", "frost"))
parts["dir"] = "S"
HERO.pose_hero(parts, "death", 4, 6)
for lid, h in parts["lamps"].items():
    core = next(o for o in h.objects() if "Core" in o.name)
    print(lid, [round(v, 3) for v in core.matrix_world.translation], "socket", [round(v, 3) for v in socks["lantern"].matrix_world.translation],
          "strength", h.core_mat.node_tree.nodes["Emission"].inputs["Strength"].default_value)
