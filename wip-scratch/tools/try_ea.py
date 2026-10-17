"""草稿：画 weapon_textures_ea 的某一件（或其中几组），存到 scratchpad/ea_try/<件>，拼帧条和 1080p 合成看（不写产物）。
用法：try_ea.py <件> [组名…]"""
import sys
import time
from pathlib import Path

WT = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/wt-moon")
sys.path.insert(0, str(WT / "art/post"))
import weapon_textures_ea as E  # noqa: E402
import vfx_frames_review as R  # noqa: E402

key = sys.argv[1]
OUTD = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/ea_try") / key
OUTD.mkdir(parents=True, exist_ok=True)
batch_all = E.BATCHES[key]
names = sys.argv[2:] or list(batch_all)
batch = {n: batch_all[n] for n in names}
frames = {}
for n in names:
    t0 = time.perf_counter()
    frames[n] = batch[n][0]()
    print(n, len(frames[n]), f"{time.perf_counter() - t0:.1f}s")
    for i, im in enumerate(frames[n]):
        im.save(OUTD / f"{n}_{i}.png")
R.strip_sheet(key, batch, frames, OUTD / "strip.png", title="草稿", note=E.NOTES.get(key))
for suffix, pl in E.INGAME.get(key, {}).items():
    pl2 = [p for p in pl if p[0] in frames]
    if pl2:
        R.ingame(key, batch, frames, OUTD / f"ingame{suffix}.png", placements=pl2, title="草稿")
