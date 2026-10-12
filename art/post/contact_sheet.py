"""拼图预览：把若干素材文件夹拼成审图用的大图（纯 Pillow / numpy）。

用法：
    art/.venv/bin/python art/post/contact_sheet.py <输出目录> <素材文件夹> [更多素材文件夹...]
输出：
    sheet_day.png    1 倍，宣纸底，每个素材一行（按 动画/朝向/帧 排列）
    sheet_zoom.png   上图的 3 倍最近邻放大
    sheet_night.png  夜景：整张乘 NIGHT_AMBIENT；有 lantern 挂点的帧在挂点处加半径约 100px 的暖光；
                     再叠加发光层（_emit.png）和一点辉光
    game_size.png    游戏里的实际大小：1 倍和 0.75 倍各一排（白天、夜里）

函数也给 render/style_frame.py 复用（ground / place / night_composite 等）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import style as S  # noqa: E402

LIGHT_RADIUS_PX = 100
SOCKET_LIGHTS = {"lantern": (LIGHT_RADIUS_PX, S.LANTERN_LIGHT), "flame": (70, S.FLAME_LIGHT)}  # 挂点 → 夜景光源
ZOOM = 3


def rgb(h: str) -> tuple[int, int, int]:
    return S.hex_to_rgb(h)


# ================================================================ 读素材
def load_asset(asset_dir) -> dict:
    """返回 {meta, frames: [{key, anim, dir, idx, rgba, emit, sockets{name: (x,y)}}]}，帧按 anims 顺序。"""
    asset_dir = Path(asset_dir)
    meta = json.loads((asset_dir / "meta.json").read_text(encoding="utf-8"))
    frames = []
    for an, a in meta["anims"].items():
        for d in a["dirs"]:
            for i in range(a["frames"]):
                base = f"{an}_{d}_{i:02d}"
                p = asset_dir / f"{base}.png"
                if not p.exists():
                    continue
                ep = asset_dir / f"{base}_emit.png"
                socks = {}
                for sn, by in meta.get("sockets", {}).items():
                    try:
                        socks[sn] = tuple(by[an][d][i])
                    except (KeyError, IndexError, TypeError):
                        pass
                frames.append({"key": base, "anim": an, "dir": d, "idx": i,
                               "rgba": Image.open(p).convert("RGBA"),
                               "emit": Image.open(ep).convert("RGBA") if ep.exists() else None,
                               "sockets": socks})
    return {"meta": meta, "frames": frames, "dir": asset_dir}


# ================================================================ 底图与摆放
def paper(w: int, h: int, seed: int = 0, blotches: int = 0) -> Image.Image:
    """宣纸底：纸色 + 纸纹；blotches>0 时加几块淡墨晕染（地面上的水墨斑）。"""
    sys.path.insert(0, str(ART / "post"))
    import postprocess as P  # noqa: E402

    base = np.ones((h, w, 3), np.float32) * np.array(rgb(S.PAPER), np.float32)
    rng = np.random.default_rng(seed)
    for _ in range(blotches):
        cx, cy = rng.uniform(0.1, 0.9) * w, rng.uniform(0.15, 0.95) * h
        rx, ry = rng.uniform(30, 90), rng.uniform(12, 30)
        m = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(m)
        for _k in range(7):  # 几个叠在一起的椭圆 → 不规则的一团
            ox, oy = rng.normal(0, rx * 0.35), rng.normal(0, ry * 0.35)
            sx, sy = rx * rng.uniform(0.4, 0.8), ry * rng.uniform(0.4, 0.8)
            dr.ellipse([cx + ox - sx, cy + oy - sy, cx + ox + sx, cy + oy + sy], fill=255)
        m = np.asarray(m.filter(ImageFilter.GaussianBlur(rng.uniform(4, 9))), np.float32) / 255.0
        tone = np.array(rgb(rng.choice([S.INK["qing"], S.INK["dan"], S.PAPER_SHADOW])), np.float32)
        k = (m * rng.uniform(0.25, 0.45))[..., None]
        base = base * (1 - k) + tone * k
        edge = np.clip(m * (1 - m) * 4, 0, 1)[..., None] * 0.10  # 晕染边缘略深（水痕）
        base = base * (1 - edge) + np.array(rgb(S.INK["dan"]), np.float32) * edge
    base *= P.paper_grain(h, w, f"ground{seed}")[..., None]
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def anchor_px(meta: dict) -> tuple[float, float]:
    W, H = meta["size"]
    a = meta.get("anchor", S.ANCHOR)
    return a[0] * W, a[1] * H


def place(canvas: Image.Image, frame: dict, meta: dict, at: tuple[float, float], shadow: bool = True,
          scale: float = 1.0) -> tuple[int, int]:
    """把一帧按锚点贴到画布上的 at（世界脚底位置）。返回贴图左上角。"""
    im = frame["rgba"]
    ax, ay = anchor_px(meta)
    if scale != 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        ax, ay = ax * scale, ay * scale
    x0, y0 = round(at[0] - ax), round(at[1] - ay)
    if shadow:
        r = meta.get("shadow_radius_px", 14) * scale
        sh = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(sh).ellipse([at[0] - r, at[1] - r * 0.38, at[0] + r, at[1] + r * 0.38], fill=70)
        sh = sh.filter(ImageFilter.GaussianBlur(2.0 * scale))
        ink = Image.new("RGBA", canvas.size, rgb(S.INK["zhong"]) + (255,))
        canvas.paste(ink, (0, 0), sh)
    canvas.alpha_composite(im, (x0, y0))
    return x0, y0


def place_emit(layer: np.ndarray, frame: dict, meta: dict, at, scale: float = 1.0):
    """把发光层累加到 layer（h,w,3 float，0..1，已乘 alpha）。"""
    if frame.get("emit") is None:
        return
    im = frame["emit"]
    ax, ay = anchor_px(meta)
    if scale != 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        ax, ay = ax * scale, ay * scale
    x0, y0 = round(at[0] - ax), round(at[1] - ay)
    e = np.asarray(im, np.float32) / 255.0
    H, W = layer.shape[:2]
    xs0, ys0 = max(0, x0), max(0, y0)
    xs1, ys1 = min(W, x0 + im.width), min(H, y0 + im.height)
    if xs1 <= xs0 or ys1 <= ys0:
        return
    sub = e[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
    layer[ys0:ys1, xs0:xs1] += sub[..., :3] * sub[..., 3:4]


# ================================================================ 夜景
def light_map(h: int, w: int, lights: list[tuple[float, float, float, str]]) -> np.ndarray:
    """环境光 NIGHT_AMBIENT + 若干暖光（x, y, 半径, 颜色），衰减 (1-(r/R)^2)^2，结果截到 0..1。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lm = np.ones((h, w, 3), np.float32) * (np.array(rgb(S.NIGHT_AMBIENT), np.float32) / 255.0)
    for x, y, R, col in lights:
        f = np.clip(1 - ((xx - x) ** 2 + (yy - y) ** 2) / (R * R), 0, 1) ** 2
        lm += f[..., None] * (np.array(rgb(col), np.float32) / 255.0)
    return np.clip(lm, 0, 1)


def night_composite(day: Image.Image, emit: np.ndarray, lights, glow_sigma: float = 2.5) -> Image.Image:
    """夜景 = 白天图 × 光照图 + 发光层 + 发光层的辉光。"""
    d = np.asarray(day.convert("RGB"), np.float32) / 255.0
    lm = light_map(d.shape[0], d.shape[1], lights)
    out = d * lm
    out = out * (1 - np.clip(emit.max(-1, keepdims=True), 0, 1)) + emit
    glow = np.stack([np.asarray(Image.fromarray((np.clip(emit[..., c], 0, 1) * 255).astype(np.uint8))
                                .filter(ImageFilter.GaussianBlur(glow_sigma)), np.float32) / 255.0 for c in range(3)], -1)
    out = out + glow * 0.9
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


# ================================================================ 拼图
def _label(im: Image.Image, xy, text: str):
    ImageDraw.Draw(im).text(xy, text, fill=rgb(S.INK["dan"]) + (255,))


def sheet(assets: list[dict], night: bool = False, pad: int = 6, label: bool = True) -> Image.Image:
    rows = []
    for A in assets:
        W, H = A["meta"]["size"]
        n = len(A["frames"])
        lab = 12 if label else 0
        row = paper(n * (W + pad) + pad, H + lab + pad, seed=1)
        emit = np.zeros((row.height, row.width, 3), np.float32)
        lights = []
        for k, f in enumerate(A["frames"]):
            ax, ay = anchor_px(A["meta"])
            at = (pad + k * (W + pad) + ax, lab + ay)
            place(row, f, A["meta"], at, shadow=False)
            if label:
                _label(row, (pad + k * (W + pad), 1), f["key"])
            if night:
                place_emit(emit, f, A["meta"], at)
                for sn, (rad, col) in SOCKET_LIGHTS.items():
                    if sn in f["sockets"]:
                        sx, sy = f["sockets"][sn]
                        lights.append((at[0] + sx, at[1] + sy, rad, col))
        rows.append(night_composite(row, emit, lights) if night else row.convert("RGB"))
    Wt = max(r.width for r in rows)
    out = Image.new("RGB", (Wt, sum(r.height for r in rows)), rgb(S.PAPER))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height
    return out


def zoom(im: Image.Image, k: int = ZOOM) -> Image.Image:
    return im.resize((im.width * k, im.height * k), Image.NEAREST)


def game_size_row(assets: list[dict], scales=(1.0, 0.75), pad: int = 10) -> Image.Image:
    """每个素材取第一帧，在宣纸地面上按 1 倍、0.75 倍并排（模拟游戏缩放），白天一排、夜里一排。"""
    picks = [(A, A["frames"][0]) for A in assets if A["frames"]]
    blocks = []
    for sc in scales:
        w = int(sum(A["meta"]["size"][0] * sc * 0.8 for A, _ in picks) + pad * (len(picks) + 1))
        h = int(max(A["meta"]["size"][1] for A, _ in picks) * sc) + pad
        day = paper(w, h, seed=3)
        emit = np.zeros((h, w, 3), np.float32)
        lights = []
        x = pad
        for A, f in picks:
            W = A["meta"]["size"][0] * sc
            at = (x + W * 0.4, h - pad * 0.6 - (1 - A["meta"]["anchor"][1]) * A["meta"]["size"][1] * sc + 2)
            place(day, f, A["meta"], at, scale=sc)
            place_emit(emit, f, A["meta"], at, scale=sc)
            if "lantern" in f["sockets"]:
                sx, sy = f["sockets"]["lantern"]
                lights.append((at[0] + sx * sc, at[1] + sy * sc, LIGHT_RADIUS_PX * sc, S.LANTERN_LIGHT))
            x += W * 0.8 + pad
        blocks.append((day.convert("RGB"), night_composite(day, emit, lights)))
    Wt = sum(b[0].width for b in blocks) + pad
    Ht = max(b[0].height for b in blocks) * 2
    out = Image.new("RGB", (Wt, Ht), rgb(S.PAPER))
    x = 0
    for d, n in blocks:
        out.paste(d, (x, 0))
        out.paste(n, (x, Ht // 2))
        x += d.width + pad
    return out


def gif(frames: list[Image.Image], path, fps: float, zoom_k: int = 2) -> None:
    """动图（宣纸底，最近邻放大）。frames 是同尺寸 RGB/RGBA 图。"""
    ims = []
    for f in frames:
        bg = paper(f.width, f.height, seed=2)
        if f.mode == "RGBA":
            bg.alpha_composite(f)
        else:
            bg = f.convert("RGBA")
        ims.append(zoom(bg.convert("RGB"), zoom_k).quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=round(1000 / fps), loop=0, disposal=1)


def grid_frames(A: dict, anim: str, dirs: list[str], cols: int = 4, pad: int = 4) -> list[Image.Image]:
    """把多个朝向的同一动画拼成网格，逐帧返回（每帧一张大图），做“8 向走路”动图用。"""
    W, H = A["meta"]["size"]
    n = A["meta"]["anims"][anim]["frames"]
    rows = (len(dirs) + cols - 1) // cols
    out = []
    for i in range(n):
        im = Image.new("RGBA", (cols * (W + pad) + pad, rows * (H + pad + 10) + pad), (0, 0, 0, 0))
        for k, d in enumerate(dirs):
            if d is None:  # 空格（例如 3×3 方位图的中心）
                continue
            f = next(fr for fr in A["frames"] if fr["key"] == f"{anim}_{d}_{i:02d}")
            x, y = pad + (k % cols) * (W + pad), pad + (k // cols) * (H + pad + 10)
            im.alpha_composite(f["rgba"], (x, y + 10))
            ImageDraw.Draw(im).text((x + 2, y), d, fill=rgb(S.INK["dan"]) + (255,))
        out.append(im)
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    assets = [load_asset(a) for a in argv[1:]]
    day = sheet(assets)
    day.save(out / "sheet_day.png")
    zoom(day).save(out / "sheet_zoom.png")
    sheet(assets, night=True).save(out / "sheet_night.png")
    game_size_row(assets).save(out / "game_size.png")
    print("写出：", ", ".join(str(out / n) for n in ("sheet_day.png", "sheet_zoom.png", "sheet_night.png", "game_size.png")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
