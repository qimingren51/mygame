#!/usr/bin/env python3
"""一次生成全部 2D 贴图（两种密度）与检查图：
  vfx_textures.py（vfx/ + ground/，含 ground_decor.py）→ weapon_textures.py（weapons/）→ ui_icons.py（ui/）→ review_additions.py

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/make_2d.py            # 1 倍 + 2 倍
  art/.venv/bin/python art/post/make_2d.py 2          # 只出 2 倍
测试另跑：test_vfx_textures.py / test_weapon_textures.py / test_ui_icons.py（各自自动测两种密度）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["vfx_textures.py", "weapon_textures.py", "ui_icons.py", "review_additions.py"]


def main() -> int:
    densities = sys.argv[1:] or ["1", "2"]
    for d in densities:
        env = {**os.environ, "LANTERN_ART_DENSITY": d}
        for step in STEPS:
            t0 = time.perf_counter()
            r = subprocess.run([sys.executable, str(HERE / step)], env=env, stdout=subprocess.DEVNULL)
            print(f"[{d}x] {step:22s} {'OK' if r.returncode == 0 else 'FAILED'}  {time.perf_counter() - t0:5.1f} s", flush=True)
            if r.returncode:
                return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
