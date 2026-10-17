"""快速试妖物：python iter_enemy.py <tag> <素材> anim:frames ...（只渲 E）"""
import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    sys.path.insert(0, str(p))
import produce as PR  # noqa: E402
tag, name = sys.argv[1], sys.argv[2]
sel = {}
for spec in sys.argv[3:]:
    an, fr = spec.split(":")
    sel[an] = [int(x) for x in fr.split(",")]
out = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/iter") / tag
PR.produce(f"{name}:{'+'.join(sel)}", {}, out_root=out, only_frames=sel)
