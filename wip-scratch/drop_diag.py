"""诊断：死亡帧里三盏灯笼的最低点（世界 z，米），各朝向。"""
import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    sys.path.insert(0, str(p))
import pipeline  # noqa: F401  先导入 bpy
import bpy
from mathutils import Vector
from style import bstyle as B
from style import style as S
import hero as HERO

B.reset_scene(); B.setup_render(S.FRAME["hero"]); B.setup_camera(S.FRAME["hero"]); B.setup_freestyle()
root, parts, socks = HERO.build_hero(lamps=("red", "mirror", "frost"))
dg = bpy.context.evaluated_depsgraph_get()
for d in ("S", "E", "N"):
    for f in range(3, 6):
        parts["dir"] = d
        B.set_direction(root, d)
        HERO.pose_hero(parts, "death", f, 6)
        out = []
        for lid, h in parts["lamps"].items():
            zs = []
            for o in h.objects():
                mw = o.matrix_world
                zs += [(mw @ v.co).z for v in o.data.vertices]
            core = h.pivot.matrix_world @ Vector((0, 0, -0.276))
            out.append(f"{lid}: min z {min(zs)*100:+.1f}cm")
        print(d, f, " | ".join(out))
