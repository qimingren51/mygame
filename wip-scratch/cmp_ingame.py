"""第二版审图：旧版（old_v1 里备份的帧）和新版用同一套摆法各出一张 1080p 合成，上下拼在一起（上旧下新）。"""
import os, sys
os.environ["LANTERN_ART_DENSITY"] = "2"
sys.path.insert(0, "wt-moon/art/post")
from pathlib import Path
from PIL import Image, ImageDraw
import weapon_textures_ea as E
import vfx_frames as F
import vfx_frames_review as R

OLD = Path("old_v1")
REV = F.REVIEW


def load(dirp, name, n):
    return [Image.open(dirp / f"{name}_{i}.png").convert("RGBA") for i in range(n)]


def count(dirp, name):
    n = 0
    while (dirp / f"{name}_{n}.png").exists():
        n += 1
    return n


def both(key, batch, new_dir, placements, old_fix, out_name, title):
    new_frames = {n: load(new_dir, n, count(new_dir, n)) for n in batch if count(new_dir, n)}
    old_frames = {n: load(OLD, n, count(OLD, n)) for n in batch if count(OLD, n)}
    paths = []
    for tag, frames, pl in (("旧版", old_frames, [old_fix(p) for p in placements if p[0] in old_frames]), ("第二版", new_frames, placements)):
        p = Path(f"b3_try/_cmp_{key}_{tag}.png")
        R.ingame(key, batch, frames, p, placements=pl, title=f"{title}（{tag}）")
        paths.append(p)
    a, b = (Image.open(p) for p in paths)
    s = Image.new("RGB", (a.width, a.height * 2 + 8), (0, 0, 0))
    s.paste(a, (0, 0)); s.paste(b, (0, a.height + 8))
    s.save(REV / out_name)
    s.resize((s.width // 3, s.height // 3), Image.LANCZOS).save(f"b3_try/{out_name}")
    print(REV / out_name)


def same(p):
    return p


def vine_old(p):  # 第一版的藤整张高 10 单位
    if len(p) > 5 and "h_units" in p[5]:
        return (*p[:5], {**p[5], "h_units": 10.0})
    return p


which = sys.argv[1:] or ["wave", "vine", "react"]
if "wave" in which:
    both("wave", E.WAVE, E.OUT, E.INGAME["wave"][""], same, "weapons_ea_wave_cmp.png", "新法器 · 沧浪 旧版 / 第二版")
if "vine" in which:
    both("vine", E.VINE, E.OUT, E.INGAME["vine"][""], vine_old, "weapons_ea_vine_cmp.png", "新法器 · 青藤 旧版 / 第二版")
if "react" in which:
    pl = [("react_rongyan", 3, (60.0, 90.0), "ground", 50.0), ("react_lietu", 3, (60.0, 90.0), "over", 60.0),
          ("react_liaoyuan", 3, (-90.0, -40.0), "body", 60.0), ("react_liaoyuan", 3, (288.0, -128.0), "body", 60.0),
          ("react_lietu", 3, (-238.0, 58.0), "over", 60.0)]
    batch = {k: F.BATCH3[k] for k in ("react_rongyan", "react_lietu", "react_liaoyuan")}
    import shutil
    for i in range(6):  # 赤地没改：旧版也用现在的
        shutil.copy(F.OUT / f"react_rongyan_{i}.png", OLD / f"react_rongyan_{i}.png")
    both("react", batch, F.OUT, pl, same, "vfx_frames_b3_lietu_liaoyuan_cmp.png", "反应 · 裂土、燎原 旧版 / 第二版（灯下的裂土挨着赤地）")
