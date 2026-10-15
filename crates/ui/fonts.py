#!/usr/bin/env python3
"""裁剪界面字体子集，输出到 assets/fonts/。

完整的中文字体有十几 MB，这里只保留：GB2312 一级字库的 3755 个常用汉字，加上界面实际用到的字
（扫描 crates/ui/src/ 里 Rust 字符串字面量中的字，注释不算；assets/data/ 里内容数据的字符串；
assets/i18n/ 里的文字），再加上 ASCII 和常用标点。
常用字预先放进去，新增界面文字大多不用重新生成，各个分支也就不会老在这几个二进制文件上冲突。
用到常用字以外的字时（--check 会报缺字），重新运行一次。

用法（在仓库根目录）：
    pip install fonttools
    python3 crates/ui/fonts.py           # 重新生成子集
    python3 crates/ui/fonts.py --check   # 只检查现有子集是否缺字（CI 用，不下载）

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

# 「•」：标题字体没有间隔号「·」，界面用它代替
EXTRA = "·•：、，。！？（）《》“”‘’—…【】「」％＋－／　●○★→←↑↓×"
CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯“”‘’·—…]")
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def non_ascii(literal: str) -> set[str]:
    """字符串字面量里的全部非 ASCII 字（汉字、全角标点、箭头、圆点……）。"""
    return {c for c in literal if ord(c) > 0x7E and not c.isspace() or c == "　"}


def common_chars() -> set[str]:
    """GB2312 一级字库（按拼音排的 3755 个常用汉字）。"""
    chars = set()
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return chars


def used_chars() -> str:
    chars = {chr(c) for c in range(0x20, 0x7F)} | set(EXTRA)
    for path in (ROOT / "crates" / "ui" / "src").rglob("*.rs"):
        text = path.read_text(encoding="utf-8")
        for literal in STRING.findall(text):
            chars |= non_ascii(literal)
        # 字符字面量，例如 '●'
        for ch in re.findall(r"'([^'\\])'", text):
            chars |= non_ascii(ch)
    for path in (ROOT / "assets" / "data").glob("*.ron"):
        for literal in STRING.findall(path.read_text(encoding="utf-8")):
            chars |= non_ascii(literal)
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


MANIFEST = OUT / "subset-chars.txt"


def check(text: str) -> int:
    """检查界面用到的字是否都在上次生成子集时的字符清单里（原字体本身没有的字形不算）。"""
    have = set(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else set()
    lack = "".join(c for c in text if c not in have)
    if lack:
        print(f"字体子集缺字：{lack}")
        print("新增了界面文字？运行 python3 crates/ui/fonts.py 重新生成字体子集。")
        return 1
    print(f"字体子集覆盖全部 {len(text)} 个字符")
    return 0


def main() -> int:
    text = used_chars()
    if "--check" in sys.argv:
        return check(text)
    text = "".join(sorted(set(text) | common_chars()))
    print(f"共 {len(text)} 个字符（含常用字）")
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
        # 不写当前时间：字没变时输出逐字节相同，免得每次都改出二进制差异（合并时还会冲突）
        font.recalcTimestamp = False
        font["head"].modified = font["head"].created
        font.save(OUT / name)
        print(f"{name}: {(OUT / name).stat().st_size / 1024:.0f} KB")
    MANIFEST.write_text(text, encoding="utf-8")
    for name, rel in LICENSES.items():
        (OUT / name).write_bytes(fetch(rel).read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
