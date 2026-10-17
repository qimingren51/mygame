"""快速试姿态：主角 + 红纸灯一遍渲（不拆层），写到 scratchpad/iter/<tag>/hero。
用法：python iter_hero.py <tag> anim:dir[:frames] ...   例如 walk:S walk:N:0,2 dash:S"""
import functools
import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    sys.path.insert(0, str(p))
from pipeline import render_asset  # noqa: E402
from style import style as S  # noqa: E402
import hero as HERO  # noqa: E402

N = {"idle": 6, "walk": 8, "dash": 4, "hurt": 2, "death": 6}
tag = sys.argv[1]
jobs = []
for spec in sys.argv[2:]:
    bits = spec.split(":")
    an, d = bits[0], bits[1]
    fr = [int(x) for x in bits[2].split(",")] if len(bits) > 2 else range(N[an])
    jobs += [(an, d, i, N[an]) for i in fr]
out = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/iter") / tag
render_asset("hero", S.FRAME["hero"], functools.partial(HERO.build_hero, lamps=(__import__("os").environ.get("LAMP", "red"),)), jobs, out,
             pose=HERO.pose_hero, sockets_wanted=("lantern",), scope=None,
             meta_extra={"category": "hero", "layers": []})
