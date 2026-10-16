"""vfx_frames.py 的审图（只读产物，不写 assets）：

  strip_sheet：每组特效一条帧条，纸色底（宣纸）和夜色底（宣纸 × 月夜底色 NIGHT_AMBIENT）各一遍；
               按游戏的混合方式合成：叠加帧乘染色（五行色或建议色）× 1.5（EMIT_HDR）加上去，普通混合的墨画在纸上、再受光照。
  ingame：     1920×1080 的近似游戏画面（月夜底色 + 主角灯笼的光照池），特效按实际大小摆在妖物身上 / 地上，
               叠加特效画在暗层之上，墨花画在地上（受光照）。合成方法同 moon_textures.py（线性空间、双线性采样）。
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

import moon_textures as M
import vfx_frames as F

V, S = F.V, F.S
EMIT_HDR = 1.5
NIGHT = S.NIGHT_AMBIENT  # 月夜底色（质感会话定的 #46557F）


def tint_of(name: str, spec) -> np.ndarray:
    """审图里用的颜色：五行命中按元素色，冲击波按建议色，其余（白色可染）按金色；不染色的帧用自带颜色。"""
    _, _, _, _, tint, _, extra = spec
    if not tint:
        return np.ones(3)
    if "element" in extra:
        return M.lin(F.ELEMENT[extra["element"]])
    if "tint_hint" in extra:
        return M.lin(extra["tint_hint"])
    return M.lin(F.ELEMENT["metal"])


def composite(bg_lin: np.ndarray, img: Image.Image, blend: str, tint: np.ndarray, light: np.ndarray | None = None) -> np.ndarray:
    """把一帧按游戏的方式合到底图上（线性光）。light 给出时，普通混合的帧先画在纸上、再整体乘光照（墨受光照）。"""
    arr = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    a = arr[..., 3:4]
    rgb = M.to_lin(arr[..., :3])
    if blend == "add":
        return bg_lin + rgb * tint * a * EMIT_HDR
    base = bg_lin / light if light is not None else bg_lin
    over = rgb * a + base * (1 - a)
    return over * light if light is not None else over


def strip_sheet(key: str, batch: dict, frames: dict, path) -> None:
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"), dtype=np.float64) / 255.0
    paper_lin = M.to_lin(paper)
    night = M.lin(NIGHT)
    pad, gap, label_w, max_w = 14, 6, 230, 2200
    rows = []
    for name, spec in batch.items():
        imgs = frames[name]
        fw, fh = imgs[0].size
        sc = min(1.0, (max_w - label_w) / (len(imgs) * (fw + gap)))
        cw, ch = int(round(fw * sc)), int(round(fh * sc))
        strips = []
        for band in ("paper", "night"):
            strip = np.zeros((ch, len(imgs) * (cw + gap) - gap, 3))
            for i, img in enumerate(imgs):
                im = img if sc == 1.0 else img.resize((cw, ch), Image.LANCZOS)
                x0 = i * (cw + gap)
                bg = paper_lin[(i * 37) % 300 : (i * 37) % 300 + ch, (i * 53) % 300 : (i * 53) % 300 + cw]
                bg = np.tile(bg, (math.ceil(ch / bg.shape[0]), math.ceil(cw / bg.shape[1]), 1))[:ch, :cw]
                light = None
                if band == "night":
                    light = np.broadcast_to(night, bg.shape)
                    bg = bg * night
                strip[:, x0 : x0 + cw] = composite(bg, im, spec[3], tint_of(name, spec), light)
            strips.append(np.round(M.to_srgb(np.clip(strip, 0, 1)) * 255).astype(np.uint8))
        rows.append((name, spec, imgs, sc, strips))
    width = label_w + max(r[4][0].shape[1] for r in rows) + 2 * pad
    height = sum(2 * r[4][0].shape[0] + 3 * gap + 12 for r in rows) + 70
    out = Image.new("RGB", (width, height), (24, 24, 26))
    d = ImageDraw.Draw(out)
    d.text((pad, 10), f"逐帧特效 {key}：每组上一条纸色底（宣纸）、下一条夜色底（宣纸 × 月夜 {NIGHT}）；叠加帧按染色 × 1.5 加上去，墨花受光照。2 倍原大（1080p 游戏里是 0.64 倍）",
           fill=(240, 239, 236), font=M.font(19))
    d.text((pad, 38), "叠加帧审图染色：五行命中按元素色（金 #E9D9A6 木 #6FD6A0 水 #6FB8FF 火 #FF8A3D 土 #C9925A），冲击波 #FFE2A8，刀光按金；暴击自带白金、不染",
           fill=(195, 194, 183), font=M.font(15))
    y = 70
    for name, spec, imgs, sc, strips in rows:
        _, size, anc, blend, tint, _, extra = spec
        d.text((pad, y + 4), name, fill=(250, 250, 245), font=M.font(20))
        sub = f"{len(imgs)} 帧 {size[0]}×{size[1]}  {blend}{' 可染' if tint else ''}"
        d.text((pad, y + 30), sub, fill=(195, 194, 183), font=M.font(14))
        if sc < 1:
            d.text((pad, y + 50), f"（审图缩到 {sc:.2f}）", fill=(160, 160, 150), font=M.font(13))
        for k, s in enumerate(strips):
            out.paste(Image.fromarray(s, "RGB"), (label_w, y + k * (s.shape[0] + gap)))
        y += 2 * strips[0].shape[0] + 3 * gap + 12
    V.save_png(out, path)


# 1080p 合成：(特效, 帧, 世界坐标 x, y（模拟坐标，y 向下）, 摆法)
INGAME_B1 = [
    ("slash", 2, (0.0, 12.0), "hero"),
    ("hit_metal", 1, (62.0, -82.0), "body"),
    ("hit_fire", 2, (125.0, 72.0), "body"),
    ("hit_water", 1, (-168.0, -100.0), "body"),
    ("hit_earth", 2, (-238.0, 58.0), "body"),
    ("crit", 0, (250.0, 128.0), "body"),
    ("hit_wood", 1, (288.0, -128.0), "body"),
    ("kill_ink", 5, (-322.0, -46.0), "ground"),
    ("shockwave", 2, (-90.0, 150.0), "ground"),
]


def ingame(key: str, batch: dict, frames: dict, path) -> None:
    sp = M.scene_sprites()
    sc = M.K / M.PPU
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"))
    img = M.paper_layer(paper)
    # 地上的墨花（画在暗层之下，受光照）
    for name, fi, (x, y), how in INGAME_B1:
        if name in frames and how == "ground" and batch[name][3] == "normal":
            anc = batch[name][2]
            M.blit(img, M.premul(frames[name][fi]), *M.to_screen(x, y), anc, sc)
    # 角色（死掉的那只不画，只留墨花）
    dead = {(x, y) for name, _, (x, y), how in INGAME_B1 if name == "kill_ink"}
    items = [(y, f, x) for f, x, y, _ in M.ENEMIES if (x, y) not in dead] + [(M.HERO_POS[1], "hero", M.HERO_POS[0])]
    for y, f, x in sorted(items):
        if f == "hero":
            for k in ("hero/idle_S_00", "lantern_red/idle_S_00"):
                im, anc = sp[k]
                M.blit(img, M.premul(im), *M.to_screen(*M.HERO_POS), anc, sc)
        else:
            im, anc = sp[f]
            M.blit(img, M.premul(im), *M.to_screen(x, y), anc, sc, flip=x > M.HERO_POS[0])
    # 光照图：月夜底色 + 主角灯笼的光照池
    sx, sy = M.asset_meta("hero")["sockets"]["lantern"]["idle"]["S"][0]
    lamp = (M.HERO_POS[0] + sx / M.PPU, M.HERO_POS[1] + sy / M.PPU)
    pool, _ = M.atlas_frame("vfx", "vfx/light_pool")
    lm = np.broadcast_to(M.lin(NIGHT).astype(np.float32), (M.SH // 2, M.SW // 2, 3)).copy()
    lx, ly = M.to_screen(*lamp)
    M.blit(lm, M.premul(pool, tint=M.lin(M.TINT_NOW)), lx / 2, ly / 2, (0.5, 0.5), (2 * M.LIGHT_R * M.K / 2) / pool.width, mode="add")
    lmq = M.to_lin(np.round(M.to_srgb(np.clip(lm, 0, 1)) * 255.0) / 255.0).astype(np.float32)
    big = np.asarray(Image.fromarray(np.round(M.to_srgb(lmq) * 255).astype(np.uint8)).resize((M.SW, M.SH), Image.BILINEAR), dtype=np.float64) / 255.0
    img = img * M.to_lin(big).astype(np.float32)
    # 叠加特效（暗层之上，× 1.5）
    for name, fi, (x, y), how in INGAME_B1:
        if name not in frames or batch[name][3] != "add":
            continue
        spec = batch[name]
        im, anc = frames[name][fi], spec[2]
        px, py = M.to_screen(x, y)
        scale = sc
        if how == "body":
            py -= 22 * M.K  # 打在身上：脚底往上约 22 世界单位
        if how == "hero":  # 刀光：弧心放在主角，按铜钱剑 Lv8 半径 85 缩放，朝 +X（右边那只）
            scale = 85 * M.PPU / F.SLASH_R * sc
            py -= 10 * M.K
        M.blit(img, M.premul(im, tint=tint_of(name, spec)), px, py, anc, scale, mode="add", gain=EMIT_HDR)
    out = Image.fromarray(np.round(M.to_srgb(np.clip(img, 0, 1)) * 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(out)
    d.text((16, 12), f"逐帧特效 {key}：1080p 游戏大小（1 世界单位 = 2.57 像素），月夜底色 {NIGHT} + 灯笼光照池；叠加特效画在暗层之上 × 1.5，墨花画在地上",
           fill=(240, 239, 236), font=M.font(20))
    for name, fi, (x, y), how in INGAME_B1:
        if name not in frames:
            continue
        px, py = M.to_screen(x, y)
        d.text((px - 40, py + 14), f"{name}_{fi}", fill=(230, 230, 225), font=M.font(15))
    V.save_png(out, path)
