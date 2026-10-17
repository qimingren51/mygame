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
    rgb = M.to_lin(arr[..., :3]) * tint
    if blend == "add":
        return bg_lin + rgb * a * EMIT_HDR
    base = bg_lin / light if light is not None else bg_lin
    over = rgb * a + base * (1 - a)
    return over * light if light is not None else over


def strip_sheet(key: str, batch: dict, frames: dict, path, title: str | None = None, note: str | None = None) -> None:
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"), dtype=np.float64) / 255.0
    paper_lin = M.to_lin(paper)
    night = M.lin(NIGHT)
    pad, gap, label_w, max_w = 14, 6, 230, 2200
    rows = []
    for name, spec in batch.items():
        imgs = frames[name]
        fw, fh = imgs[0].size
        sc = min(max(1.0, 128.0 // fw), (max_w - label_w) / (len(imgs) * (fw + gap)))  # 小粒子放大看
        cw, ch = int(round(fw * sc)), int(round(fh * sc))
        strips = []
        for band in ("paper", "night"):
            strip = np.zeros((ch, len(imgs) * (cw + gap) - gap, 3))
            for i, img in enumerate(imgs):
                im = img if sc == 1.0 else img.resize((cw, ch), Image.NEAREST if sc > 1 else Image.LANCZOS)
                x0 = i * (cw + gap)
                bg = paper_lin[(i * 37) % 300 : (i * 37) % 300 + ch, (i * 53) % 300 : (i * 53) % 300 + cw]
                bg = np.tile(bg, (math.ceil(ch / bg.shape[0]), math.ceil(cw / bg.shape[1]), 1))[:ch, :cw]
                light = None
                tint = tint_of(name, spec)
                if band == "night":
                    bg = bg * night
                    if not (spec[3] == "normal" and spec[4]):  # 可染的普通混合小粒子（羽毛、纸屑）画在暗层之上看形状
                        light = np.broadcast_to(night, bg.shape)
                elif spec[3] == "normal" and spec[4]:
                    tint = M.lin(S.INK["jiao"])  # 纸色底上白的看不见，染焦墨看剪影
                strip[:, x0 : x0 + cw] = composite(bg, im, spec[3], tint, light)
            strips.append(np.round(M.to_srgb(np.clip(strip, 0, 1)) * 255).astype(np.uint8))
        rows.append((name, spec, imgs, sc, strips))
    width = label_w + max(r[4][0].shape[1] for r in rows) + 2 * pad
    height = sum(2 * r[4][0].shape[0] + 3 * gap + 12 for r in rows) + 70
    out = Image.new("RGB", (width, height), (24, 24, 26))
    d = ImageDraw.Draw(out)
    head = title or f"逐帧特效 {key}"
    d.text((pad, 10), f"{head}：每组上一条纸色底（宣纸）、下一条夜色底（宣纸 × 月夜 {NIGHT}）；叠加帧按染色 × 1.5 加上去，墨花受光照。帧条按贴图像素画（大图缩小、小粒子放大，见左边）；1080p 游戏里的大小看 _ingame 合成",
           fill=(240, 239, 236), font=M.font(19))
    d.text((pad, 38), note or "叠加帧审图染色：五行命中按元素色（金 #E9D9A6 木 #6FD6A0 水 #6FB8FF 火 #FF8A3D 土 #C9925A），冲击波 #FFE2A8，刀光按金；暴击自带白金、不染",
           fill=(195, 194, 183), font=M.font(15))
    y = 70
    for name, spec, imgs, sc, strips in rows:
        _, size, anc, blend, tint, _, extra = spec
        d.text((pad, y + 4), name, fill=(250, 250, 245), font=M.font(20))
        sub = f"{len(imgs)} 帧 {size[0]}×{size[1]}  {blend}{' 可染' if tint else ''}"
        d.text((pad, y + 30), sub, fill=(195, 194, 183), font=M.font(14))
        if sc != 1:
            d.text((pad, y + 50), f"（审图{'放大' if sc > 1 else '缩'}到 {sc:.2f}）", fill=(160, 160, 150), font=M.font(13))
        for k, s in enumerate(strips):
            out.paste(Image.fromarray(s, "RGB"), (label_w, y + k * (s.shape[0] + gap)))
        y += 2 * strips[0].shape[0] + 3 * gap + 12
    V.save_png(out, path)


# 1080p 合成：(特效, 帧, 世界坐标 x, y（模拟坐标，y 向下）, 摆法, 想要的半径（世界单位，按 meta 的 radius_px 缩放；None 是原大）)
# 摆法：hero 放在主角腰上（刀光、旋风的弧心），body 打在妖物身上（脚底往上约 22），ground / feet 在脚底，over 在脚底但画在角色之上。
# 普通混合的帧：ground / feet 画在角色之下（贴地），hero / body 画在角色之上（空中的烟、碎纸）；都受光照。
INGAME_B1 = [
    ("slash", 2, (0.0, 12.0), "hero", 85.0),  # 铜钱剑 Lv8 的扫击半径，朝 +X（右边那只）
    ("hit_metal", 1, (62.0, -82.0), "body", None),
    ("hit_fire", 2, (125.0, 72.0), "body", None),
    ("hit_water", 1, (-168.0, -100.0), "body", None),
    ("hit_earth", 2, (-238.0, 58.0), "body", None),
    ("crit", 0, (250.0, 128.0), "body", None),
    ("hit_wood", 1, (288.0, -128.0), "body", None),
    ("kill_ink", 5, (-322.0, -46.0), "ground", None),
    ("shockwave", 2, (-90.0, 150.0), "ground", None),
]
LIFT = {"hero": 10.0, "body": 22.0, "ground": 0.0, "feet": 0.0, "over": 0.0, "air": 54.0, "low": 26.0}
# 往上抬多少世界单位；over 是脚底、但画在角色之上（烟）；air / low 是飘在半空的（孔明灯飘着 / 快落地）
INGAME = {
    "b1": INGAME_B1,
    "b2": [
        ("evolve", 3, (0.0, 12.0), "hero", None),
        ("evolve_pillar", 2, (0.0, 12.0), "feet", None),
        ("fire_burst", 2, (125.0, 72.0), "feet", 56.0),  # 孔明灯 Lv6–8 的爆燃半径
        ("fire_burst", 5, (-238.0, 58.0), "feet", 46.0),  # 火的死亡爆炸
        ("fire_burst_smoke", 0, (-238.0, 58.0), "over", 46.0),
        ("ice_shatter", 2, (-168.0, -100.0), "body", None),
        ("ice_shatter", 4, (288.0, -128.0), "body", None),
    ],  # 羽毛纸屑是染色的粒子，纸白在纸上看不出来，只看帧条
    "b3": {  # 十种反应一张摆不下：叠加的六种一张，普通混合的四种一张；半径按 BALANCE 7.2 的反应范围
        "": [
            ("react_liaoyuan", 3, (125.0, 72.0), "body", 60.0),
            ("react_rongyan", 3, (-238.0, 58.0), "ground", 50.0),
            ("react_zhubing", 2, (62.0, -82.0), "body", None),
            ("react_ningshuang", 3, (-168.0, -100.0), "ground", 50.0),
            ("react_rongjin", 0, (288.0, -128.0), "body", 12.0),  # 按妖物的身体半径（约 12）
            ("react_duanmu", 2, (250.0, 128.0), "body", None),
        ],
        "2": [
            ("react_zisheng", 4, (125.0, 72.0), "feet", 50.0),
            ("react_zhengteng", 3, (-238.0, 58.0), "over", 70.0),
            ("react_lietu", 3, (-168.0, -100.0), "over", 60.0),
            ("react_yuni", 5, (250.0, 128.0), "ground", 70.0),
        ],
    },
}
NOTES = {
    "b3": "第三批十种反应都自带颜色、不染：叠加的（燎原、赤地、铸兵、凝霜、熔金、断木）× 1.5 加上去；普通混合的（滋生、蒸腾、裂土、淤泥）"
          "画在纸上、受光照。熔金是循环的（6 帧、10 帧/秒）。1080p 合成分两张：_ingame 是叠加的六种，_ingame2 是普通混合的四种",
    "b2": "叠加帧审图染色：冰碎按建议色 #CDEBFF，火爆、进化自带颜色；墨烟是焦墨、普通混合；"
          "羽毛纸屑（普通混合、可染）纸色底上染焦墨看剪影，夜色底上染纸白 #EDE6D6、画在暗层之上",
}


def ingame(key: str, batch: dict, frames: dict, path, placements: list | None = None, title: str | None = None) -> None:
    sp = M.scene_sprites()
    sc = M.K / M.PPU
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"))
    img = M.paper_layer(paper)
    placements = INGAME_B1 if placements is None else placements

    def place(name, fi, x, y, how, want_r, opt=None, mode="over", gain=1.0):
        """opt（可选）：
        size_units = (宽, 高)：整张画布拉成这么大（世界单位，可以不等比；泡沫痕用）；
        to = (x, y), h_units：锚点在右端、沿 X 拉到这一点（藤），整张高 h_units；
        face = (x, y)：转过去让 +X 朝着这一点（流回主角的绿光）。目标点和锚点用同一个摆法抬高。"""
        spec = batch[name]
        im, anc = frames[name][fi], spec[2]
        px, py = M.to_screen(x, y)
        py -= LIFT[how] * M.K
        opt = opt or {}
        if "size_units" in opt:
            wu, hu = opt["size_units"]
            im = im.resize((max(1, round(wu * M.K)), max(1, round(hu * M.K))), Image.LANCZOS)
            scale = 1.0
        elif "to" in opt:
            tx, ty = M.to_screen(*opt["to"])
            ty -= LIFT[how] * M.K
            im = im.resize((max(1, round(math.hypot(px - tx, py - ty))), max(1, round(opt["h_units"] * M.K))), Image.LANCZOS)
            scale = 1.0
        elif want_r is None:
            scale = sc
        else:
            r_px = spec[6].get("radius_px") or spec[6]["half_width_px"]
            scale = want_r * M.PPU / r_px * sc
        rot = None
        if "to" in opt:
            rot = math.atan2(py - ty, px - tx)  # +X 从目标指向锚点
        elif "face" in opt:
            fx, fy = M.to_screen(*opt["face"])
            rot = math.atan2(fy - LIFT[how] * M.K - py, fx - px)
        if rot is not None:  # 绕锚点转：先把锚点放到一张大方图的正中，转完锚点还在正中
            if scale != 1.0:
                im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
                scale = 1.0
            side = 2 * math.ceil(math.hypot(im.width, im.height)) + 4
            big = Image.new("RGBA", (side, side), (255, 255, 255, 0))
            big.paste(im, (round(side / 2 - anc[0] * im.width), round(side / 2 - anc[1] * im.height)))
            im, anc = big.rotate(-math.degrees(rot), resample=Image.BICUBIC, center=(side / 2, side / 2)), (0.5, 0.5)
        M.blit(img, M.premul(im, tint=tint_of(name, spec)), px, py, anc, scale, mode=mode, gain=gain)

    def normal_layer(on_ground: bool):
        for name, fi, (x, y), how, want_r, *opt in placements:
            if name in frames and batch[name][3] == "normal" and (how in ("ground", "feet")) == on_ground:
                place(name, fi, x, y, how, want_r, *opt)

    # 地上的墨花、落羽（画在角色之下，受光照）
    normal_layer(True)
    # 角色（死掉的那只不画，只留墨花）
    dead = {(x, y) for name, _, (x, y), how, _r, *_o in placements if name == "kill_ink"}
    items = [(y, f, x) for f, x, y, _ in M.ENEMIES if (x, y) not in dead] + [(M.HERO_POS[1], "hero", M.HERO_POS[0])]
    for y, f, x in sorted(items):
        if f == "hero":
            for k in ("hero/idle_S_00", "lantern_red/idle_S_00"):
                im, anc = sp[k]
                M.blit(img, M.premul(im), *M.to_screen(*M.HERO_POS), anc, sc)
        else:
            im, anc = sp[f]
            M.blit(img, M.premul(im), *M.to_screen(x, y), anc, sc, flip=x > M.HERO_POS[0])
    # 空中普通混合的（墨烟等，画在角色之上，同样受光照）
    normal_layer(False)
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
    for name, fi, (x, y), how, want_r, *opt in placements:
        if name in frames and batch[name][3] == "add":
            place(name, fi, x, y, how, want_r, *opt, mode="add", gain=EMIT_HDR)
    out = Image.fromarray(np.round(M.to_srgb(np.clip(img, 0, 1)) * 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(out)
    head = title or f"逐帧特效 {key}"
    d.text((16, 12), f"{head}：1080p 游戏大小（1 世界单位 = 2.57 像素），月夜底色 {NIGHT} + 灯笼光照池；叠加特效画在暗层之上 × 1.5，墨花画在地上",
           fill=(240, 239, 236), font=M.font(20))
    labelled = set()
    for name, fi, (x, y), how, _r, *_o in placements:
        if name not in frames or (x, y) in labelled:
            continue
        labelled.add((x, y))
        px, py = M.to_screen(x, y)
        d.text((px - 40, py + 14), f"{name}_{fi}", fill=(230, 230, 225), font=M.font(15))
    V.save_png(out, path)
