import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART/"models", ART/"post", ART/"render"):
    sys.path.insert(0, str(p))
import produce as PR
out = Path(sys.argv[1])
jobs = [tuple(j.split(":")[0:2]) + (int(j.split(":")[2]), int(j.split(":")[3])) for j in sys.argv[2:]]
t = {}
import os; PR.render_hero(jobs, out, timings=t, lamps=tuple(os.environ.get("LAMPS","red,mirror,frost").split(",")))
print(t)
