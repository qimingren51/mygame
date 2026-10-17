"""狐仙祠、石狐放大前后对比审图 → art/out/review@2x/qq_props_resize.png（一次性，仓库根目录运行）。
游戏大小（2 倍原大，1 像素 = 1 像素），旁边放主角和石灯笼比大小；白天、夜里在主角灯光里、夜里灯光外三排。
旧图在 art/out/_qq_props_old/。
    LANTERN_ART_DENSITY=2 art/.venv/bin/python <本文件>
"""

from __future__ import annotations

import sys
from pathlib import Path

ART = Path("art").resolve()
sys.path.insert(0, str(ART / "render"))
import props_qingqiu as PQ  # noqa: E402  （会把 art、post、render 加进 sys.path）
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

CS, S, D = PQ.CS, PQ.S, PQ.D
OLD = PQ.OUT / "_qq_props_old"


def extents(A):
    """锚点左右、上方、下方的实际像素范围。"""
    f = A["frames"][0]
    a = np.asarray(f["rgba"])[..., 3]
    ys, xs = np.where(a > 0)
    ax, ay = CS.anchor_px(A["meta"])
    return ax - xs.min(), xs.max() + 1 - ax, ay - ys.min(), ys.max() + 1 - ay


def light_reach(key, A):
    """这一列自己的光在水平方向能照到的范围（相对脚底）。"""
    lo, hi = 0.0, 0.0
    for x, _y, R, _c in PQ._lights_for(key, A["meta"], A["frames"][0], (0.0, 0.0)):
        lo, hi = min(lo, x - R), max(hi, x + R)
    return -lo, hi


def main() -> Path:
    assert D == 2, "请设 LANTERN_ART_DENSITY=2"
    hero = PQ.CS.load_asset(PQ.ASSETS / "hero")
    if (PQ.ASSETS / "lantern_red" / "meta.json").exists():
        hero = PQ._with_overlay(hero, CS.load_asset(PQ.ASSETS / "lantern_red"))
    hero = dict(hero, frames=[f for f in hero["frames"] if f["key"] == "idle_S_00"])
    cols = [  # (标签, _lights_for 用的名字, 素材)
        ("主角", "hero", hero),
        ("石灯笼", "stone_lantern", CS.load_asset(PQ.ASSETS / "stone_lantern")),
        ("狐仙祠 旧", "fox_shrine", CS.load_asset(OLD / "fox_shrine")),
        ("狐仙祠 新 ×1.3", "fox_shrine", CS.load_asset(PQ.ASSETS / "fox_shrine")),
        ("石狐 旧", "stone_fox", CS.load_asset(OLD / "stone_fox")),
        ("石狐 新 ×1.5", "stone_fox", CS.load_asset(PQ.ASSETS / "stone_fox")),
    ]
    ppu = S.PX_PER_UNIT
    fsz = int(10 * D)
    font = PQ._font(fsz)
    gap = int(14 * D)
    ex = [extents(A) for _, _, A in cols]
    labels = []
    for (lab, _, A), (l_, r_, up, dn) in zip(cols, ex):
        labels.append([lab, f"高 {(up + dn) / ppu:.1f} 单位（脚上 {up / ppu:.1f}）"])
    # 每列占的宽：剪影和标签取大；道具之间再拉开到彼此的光照不到邻列（灯光外那排才是真的“灯光外”）
    half = []
    for (l_, r_, _, _), lab in zip(ex, labels):
        lw = max(font.getlength(t) for t in lab) / 2
        half.append((max(l_, lw), max(r_, lw)))
    xs = [gap + half[0][0]]
    for i in range(1, len(cols)):
        need = half[i - 1][1] + half[i][0] + gap
        if i >= 2:  # 主角和石灯笼一组（同一片灯光里），道具各自隔开
            reach_prev = light_reach(cols[i - 1][1], cols[i - 1][2])[1] if i > 2 else 0
            reach_next = light_reach(cols[i][1], cols[i][2])[0]
            if i == 2:  # 离开主角灯光、石灯笼火光
                reach_prev = max(xs[0] + light_reach("hero", hero)[1],
                                 xs[1] + light_reach("stone_lantern", cols[1][2])[1]) - xs[1]
            need = max(need, reach_prev + half[i][0] + int(4 * D), half[i - 1][1] + reach_next + int(4 * D))
        xs.append(xs[-1] + need)
    W = int(xs[-1] + half[-1][1] + gap)
    top = max(up for _, _, up, _ in ex)
    foot = int(top + 12 * D)
    Hh = int(foot + max(dn for *_, dn in ex) + 10 * D)

    def row(extra_warm: bool, guides: bool):
        day = CS.paper(W, Hh, seed=17)
        if guides:  # 主角头顶、石灯笼顶两条淡线
            dr = ImageDraw.Draw(day)
            for k, txt in ((0, "主角头顶"), (1, "石灯笼顶")):
                y = foot - ex[k][2]
                for x0 in range(0, W, int(6 * D)):
                    dr.line([(x0, y), (x0 + int(3 * D), y)], fill=CS.rgb(S.INK["qing"]) + (255,), width=1)
                dr.text((W - gap - font.getlength(txt), y - fsz - 2), txt, fill=CS.rgb(S.INK["dan"]) + (255,), font=font)
        emit = np.zeros((Hh, W, 3), np.float32)
        lights = []
        for (_, key, A), x in zip(cols, xs):
            f = A["frames"][0]
            at = (x, foot)
            CS.place(day, f, A["meta"], at)
            CS.place_emit(emit, f, A["meta"], at)
            lights += PQ._lights_for(key, A["meta"], f, at)
            if extra_warm and key not in ("hero", "stone_lantern"):  # 主角站在左边一点：道具在他灯笼暖光的半径中段
                lights.append((x - 45 * D, foot - 30 * D, CS.LIGHT_RADIUS_PX, S.LANTERN_LIGHT))
        return day.convert("RGB"), CS.night_composite(day, emit, lights)

    d_row, _ = row(False, True)
    _, n_in = row(True, False)
    _, n_out = row(False, False)
    strip = Image.new("RGB", (W, int(2 * fsz + 8 * D)), CS.rgb(S.PAPER))
    dr = ImageDraw.Draw(strip)
    for lab, x in zip(labels, xs):
        for j, t in enumerate(lab):
            dr.text((x - font.getlength(t) / 2, int(2 * D) + j * (fsz + int(2 * D))), t,
                    fill=CS.rgb(S.INK["nong"] if j == 0 else S.INK["dan"]) + (255,), font=font)
    day_l = Image.new("RGB", (W, d_row.height + strip.height), CS.rgb(S.PAPER))
    day_l.paste(d_row, (0, 0))
    day_l.paste(strip, (0, d_row.height))
    blocks = [("狐仙祠 ×1.3、石狐 ×1.5 前后对比 —— 游戏大小（2 倍原大，1 像素 = 1 像素），白天；高度按 px_per_unit 4 换成世界单位", day_l),
              ("夜里·在主角灯光里（每件道具左边放一盏主角灯笼的暖光，道具在光圈中段；另加各自的光）", n_in),
              (f"夜里·灯光外（只有夜色 {S.NIGHT_AMBIENT}、发光层 _emit 和自己的光：狐仙祠青光半径按 light_radius_units 旧 70 / 新 90）", n_out)]
    out = PQ.REVIEW / "qq_props_resize.png"
    PQ._stack(blocks).save(out)
    return out


if __name__ == "__main__":
    print(main())
