#!/usr/bin/env python3
"""裁剪界面字体子集，输出到 assets/fonts/。

完整的中文字体有十几 MB，这里只保留界面实际用到的字：扫描 crates/ui/src/ 里 Rust 字符串
字面量中的字（注释不算）和 assets/i18n/ 里的文字，再加上 ASCII 和常用标点。
新增界面文字后重新运行一次。

用法（在仓库根目录）：
    pip install fonttools
    python3 crates/ui/fonts.py

原始字体（OFL 协议）第一次运行时从 google/fonts 下载，缓存在 target/fonts-cache/，不提交。
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "fonts"
CACHE = ROOT / "target" / "fonts-cache"

GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = {
    # 输出文件名: (下载路径, 可变字体的字重；None 表示静态字体)
    "MaShanZheng-subset.ttf": ("mashanzheng/MaShanZheng-Regular.ttf", None),
    "NotoSerifSC-subset.ttf": ("notoserifsc/NotoSerifSC%5Bwght%5D.ttf", 500),
}
LICENSES = {
    "OFL-MaShanZheng.txt": "mashanzheng/OFL.txt",
    "OFL-NotoSerifSC.txt": "notoserifsc/OFL.txt",
}

EXTRA = "·：、，。！？（）《》“”‘’—…【】「」％＋－／　"
CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯“”‘’·—…]")
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def used_chars() -> str:
    chars = {chr(c) for c in range(0x20, 0x7F)} | set(EXTRA)
    for path in (ROOT / "crates" / "ui" / "src").rglob("*.rs"):
        for literal in STRING.findall(path.read_text(encoding="utf-8")):
            chars |= set(CJK.findall(literal))
    for path in (ROOT / "assets" / "i18n").glob("*.ron"):
        chars |= set(CJK.findall(path.read_text(encoding="utf-8")))
    return "".join(sorted(chars))


def fetch(rel: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / rel.replace("/", "_").replace("%5B", "[").replace("%5D", "]")
    if not dest.exists():
        print(f"下载 {rel}")
        urllib.request.urlretrieve(GOOGLE + rel, dest)
    return dest


def main() -> int:
    text = used_chars()
    print(f"共 {len(text)} 个字符")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (rel, weight) in FONTS.items():
        font = TTFont(fetch(rel))
        if weight is not None and "fvar" in font:
            font = instancer.instantiateVariableFont(font, {"wght": weight})
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(text=text)
        sub.subset(font)
        font.save(OUT / name)
        print(f"{name}: {(OUT / name).stat().st_size / 1024:.0f} KB")
    for name, rel in LICENSES.items():
        (OUT / name).write_bytes(fetch(rel).read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
