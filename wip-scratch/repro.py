import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART/"models", ART/"post", ART/"render"):
    sys.path.insert(0, str(p))
from style import style as S
from pipeline import render_asset
import hero as HERO
out = Path(sys.argv[1])
jobs = [("idle","S",0,6),("walk","E",0,8)]
render_asset("hero", S.FRAME["hero"], HERO.build_hero, jobs, out, pose=HERO.pose_hero, sockets_wanted=("lantern",),
             meta_extra={"category":"hero","layers":["emit"]})
