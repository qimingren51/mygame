import os, sys
from pathlib import Path
os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path[:0] = ["art", "art/models", "art/post", "art/render"]
import enemies_v2 as EV
out = Path(sys.argv[1])
for nm in sys.argv[2:]:
    EV.render(nm, out)
