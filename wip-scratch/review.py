"""审图：100% 裁切（原像素）与 50% 缩小。"""
import sys
from PIL import Image
src, tag = sys.argv[1], sys.argv[2]
sc = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
im = Image.open(src).convert("RGB")
im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(sc + f"{tag}_50.png")
boxes = [tuple(map(int, b.split(","))) for b in sys.argv[3:]]
for i, b in enumerate(boxes):
    im.crop(b).save(sc + f"{tag}_100_{i}.png")
print("ok")
