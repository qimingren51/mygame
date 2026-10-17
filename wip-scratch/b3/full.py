"""整只渲到测试文件夹（含 meta、contact_radius），再出帧条和每个动画的动图。
用法（仓库根目录）：LANTERN_ART_DENSITY=2 art/.venv/bin/python <本文件> 素材 [输出目录]"""
import os
import sys
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path[:0] = ["art", "art/models", "art/post", "art/render"]
import enemies_v2 as EV  # noqa: E402
import contact_sheet as CS  # noqa: E402

name = sys.argv[1]
root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "test"
out = EV.render(name, root)
A = CS.load_asset(out)
for an, info in A["meta"]["anims"].items():
    frames = [f["rgba"] for f in A["frames"] if f["anim"] == an]
    wu = info.get("windup_frames", 0)
    if info.get("loop") is False:
        frames = frames[:wu] + [frames[max(wu - 1, 0)]] * 5 + frames[wu:] + [frames[-1]] * 4
    CS.gif(frames, root / f"{name}_{an}.gif", info["fps"], zoom_k=1)
os.system(f"art/.venv/bin/python {Path(__file__).parent / 'strip.py'} {root / (name + '_strip.png')} {out} 0.6")
