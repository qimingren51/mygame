"""把 new.py 里的顶层块（def/常量）按名字替换进目标文件。"""
import re, sys
from pathlib import Path
target, newsrc = Path(sys.argv[1]), Path(sys.argv[2]).read_text()

def blocks(text):
    lines = text.splitlines(keepends=True)
    starts = []
    for i, ln in enumerate(lines):
        m = re.match(r"(def|class) (\w+)|([A-Z_][A-Z0-9_]*)\s*(:[^=]*)?=", ln)
        if m and not ln.startswith(" "):
            starts.append((i, m.group(2) or m.group(3)))
    out = {}
    for k, (i, name) in enumerate(starts):
        j = len(lines)
        for jj in range(i + 1, len(lines)):
            l = lines[jj]
            if l.strip() and not l.startswith((" ", "\t", ")", "]", "}")):
                j = jj
                break
        # 去掉块尾的空行
        while j > i and not lines[j - 1].strip():
            j -= 1
        out[name] = (i, j)
    return lines, out

new_lines, new_blocks = blocks(newsrc)
text = target.read_text()
for name, (i, j) in new_blocks.items():
    lines, tb = blocks(text)
    chunk = "".join(new_lines[i:j])
    if name in tb:
        a, b = tb[name]
        text = "".join(lines[:a]) + chunk + "".join(lines[b:])
        print("replaced", name)
    else:
        print("NOT FOUND (skipped):", name)
target.write_text(text)
