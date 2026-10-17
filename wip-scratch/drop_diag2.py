import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    sys.path.insert(0, str(p))
import pipeline  # noqa: F401
from mathutils import Vector
from style import bstyle as B
from style import style as S
import hero as HERO
B.reset_scene(); B.setup_render(S.FRAME["hero"]); B.setup_camera(S.FRAME["hero"]); B.setup_freestyle()
root, parts, socks = HERO.build_hero(lamps=("red", "mirror", "frost"))
for f in (3, 4, 5):
    parts["dir"] = "S"; B.set_direction(root, "S")
    HERO.pose_hero(parts, "death", f, 6)
    sock = socks["lantern"].matrix_world.translation
    for lid, h in parts["lamps"].items():
        lows = sorted(((min((o.matrix_world @ v.co).z for v in o.data.vertices), o.name) for o in h.objects()))[:3]
        core = [o for o in h.objects() if "Core" in o.name][0].matrix_world.translation
        print(f, lid, " ".join(f"{n}:{z*100:+.1f}" for z, n in lows), f"core z {core.z*100:.1f}cm, core-socket {(core-sock).length*100:.1f}cm")
