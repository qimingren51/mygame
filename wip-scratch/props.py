import sys
from pathlib import Path
ART = Path("/home/user/mygame/art")
for p in (ART, ART/"models", ART/"post", ART/"render"):
    sys.path.insert(0, str(p))
import produce as PR
t = {}
for n in sys.argv[2:]:
    PR.produce(n, t, out_root=Path(sys.argv[1]))
print(t)
