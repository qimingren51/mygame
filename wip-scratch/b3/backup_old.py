"""从图集还原现版素材文件夹 → art/out/assets@2x_old/<名>（审图“现版”列用）。用法：backup_old.py 图集目录 图集名 素材...
帧尺寸、meta 从图集 meta.lantern.assets 取；_emit/_flash 一起还原。"""
import json, sys
from pathlib import Path
sys.path.insert(0, "/home/user/mygame/art/post")
import atlas_swap as AS
atlas, name, assets = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
frames, lan, anims = AS.load_pages(atlas, name)
for a in assets:
    dst = Path("/home/user/mygame/art/out/assets@2x_old") / a
    if dst.exists():
        print("已有，跳过", dst); continue
    AS.rebuild_folder(a, frames, lan["assets"][a], dst)
    print("还原", a, len(list(dst.glob("*.png"))), "张")
