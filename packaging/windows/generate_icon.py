#!/usr/bin/env python3
"""从仓库现有灯笼图标生成 Windows ICO，不依赖美术中间文件。

安装依赖：python3 -m pip install Pillow
重新生成：python3 packaging/windows/generate_icon.py
生成的 lantern.ico 随仓库保存，普通 Rust 构建不需要 Python 或 Pillow。
"""

from pathlib import Path

from PIL import Image


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "web/lantern/icons/icon-512.png"
    output = root / "packaging/windows/lantern.ico"
    sizes = [(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]
    with Image.open(source) as image:
        # Pillow 的 ICO 编码器用 LANCZOS 从原图逐一缩小，避免连续缩放损失细节。
        image.convert("RGBA").save(output, format="ICO", sizes=sizes)
    print(f"已生成 {output.relative_to(root)}：{', '.join(str(w) for w, _ in sizes)}")


if __name__ == "__main__":
    main()
