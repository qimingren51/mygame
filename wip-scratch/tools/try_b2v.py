"""草稿：只画第二批的某几组，存到 scratchpad/b2v，拼帧条和 1080p 合成看（不写产物）。用法：try_b2v.py 组名…"""
import sys
import time
from pathlib import Path

WT = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/wt-moon")
sys.path.insert(0, str(WT / "art/post"))
import vfx_frames as F  # noqa: E402
import vfx_frames_review as R  # noqa: E402

OUTD = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/b2v")
names = sys.argv[1:] or list(F.BATCH2)
frames = {}
for n in names:
    t0 = time.perf_counter()
    frames[n] = F.BATCH2[n][0]()
    print(n, f"{time.perf_counter() - t0:.1f}s")
    for i, im in enumerate(frames[n]):
        im.save(OUTD / f"{n}_{i}.png")
batch = {n: F.BATCH2[n] for n in names}
R.strip_sheet("b2", batch, frames, OUTD / ("strip_" + "_".join(names) + ".png"), note=R.NOTES.get("b2"))
pl = [p for p in R.INGAME["b2"] if p[0] in frames]
if pl:
    R.ingame("b2", batch, frames, OUTD / ("ingame_" + "_".join(names) + ".png"), placements=pl)
