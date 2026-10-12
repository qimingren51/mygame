"""界面美术用的字体（完整版，不是 assets/fonts 里的子集）。

assets/fonts 里的字体只收录了游戏界面代码里出现过的字，画印章、标题字、样张时会缺字，
所以这里从 google/fonts 下载完整版，缓存在 art/out/fonts/（不提交）。两款都是 SIL OFL 1.1，
和游戏里用的是同一款字体：
  - 马善政（MaShanZheng）：毛笔楷书，标题、印章、卡片名；
  - 思源宋体（Noto Serif SC）：可变字体，正文。游戏里固定 500 字重，样张也用 500。

用法：
    from ui_fonts import font
    f = font("brush", 96)            # 马善政
    g = font("serif", 28, weight=500)
"""

from __future__ import annotations

import urllib.request
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ART = Path(__file__).resolve().parents[1]
CACHE = ART / "out" / "fonts"
GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FILES = {
    # 名字: (缓存文件名, 下载路径)
    "brush": ("MaShanZheng-Regular.ttf", "mashanzheng/MaShanZheng-Regular.ttf"),
    "serif": ("NotoSerifSC-VF.ttf", "notoserifsc/NotoSerifSC%5Bwght%5D.ttf"),
}


def font_file(name: str) -> Path:
    """返回完整字体文件的路径；第一次调用时下载。"""
    fname, url = FILES[name]
    path = CACHE / fname
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(GOOGLE + url, timeout=120) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.rename(path)
    return path


@lru_cache(maxsize=64)
def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    """取一个 Pillow 字体对象。serif 是可变字体，weight 默认 500（与游戏一致）。"""
    f = ImageFont.truetype(str(font_file(name)), size)
    if name == "serif":
        f.set_variation_by_axes([weight or 500])
    return f


if __name__ == "__main__":
    for n in FILES:
        print(n, font_file(n), font(n, 32).getbbox("提灯夜行"))
