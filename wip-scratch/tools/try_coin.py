"""草稿：只画铜钱剑的挥击 / 旋风，存到 scratchpad/coin2，拼一张纸色底 + 夜色底的帧条看（不写产物）。"""
import sys
import time
from pathlib import Path

WT = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/wt-moon")
sys.path.insert(0, str(WT / "art/post"))
import weapon_textures_ea as E  # noqa: E402
import vfx_frames_review as R  # noqa: E402

OUTD = Path("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/coin2")
names = sys.argv[1:] or ["coin_slash", "coin_whirl"]
frames = {}
for n in names:
    t0 = time.perf_counter()
    frames[n] = E.COIN[n][0]()
    print(n, f"{time.perf_counter() - t0:.1f}s")
    for i, im in enumerate(frames[n]):
        im.save(OUTD / f"{n}_{i}.png")
batch = {n: E.COIN[n] for n in names}
R.strip_sheet("coin", batch, frames, OUTD / ("strip_" + "_".join(names) + ".png"), title="草稿", note="草稿")
for suffix, pl in E.INGAME["coin"].items():
    pl2 = [p for p in pl if p[0] in frames]
    if pl2:
        R.ingame("coin", batch, frames, OUTD / f"ingame{suffix}.png", placements=pl2, title="草稿")
