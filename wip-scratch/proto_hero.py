"""原型：水墨主角背影和石灯笼（之后并进 title_screen.py）。"""
from __future__ import annotations

import math
import sys

sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np  # noqa: E402

import title_screen as T  # noqa: E402
import ink_figure as F  # noqa: E402

V, S = T.V, T.S
col, smoothstep, mixc, blur, noise = V.col, V.smoothstep, T.mixc, T.blur, T.noise
PAPER, JIAO, NONG, ZHONG, DAN, QING = T.PAPER, T.JIAO, T.NONG, T.ZHONG, T.DAN, T.QING
ZHUSHA, TENG = T.ZHUSHA, T.TENG
ZHESHI = col(S.ACCENT["zheshi"])
WHITE = np.ones(3)
LAMP_LIGHT, FLAME_LIGHT = col(S.LANTERN_LIGHT), col(S.FLAME_LIGHT)
WASH_L, WASH_M, WASH_D = mixc(QING, DAN, 0.5), mixc(DAN, ZHONG, 0.35), mixc(ZHONG, NONG, 0.3)
SKIN = mixc(PAPER, ZHESHI, 0.10)
HAIR = mixc(JIAO, NONG, 0.15)
HERO_FEET = T.HERO_FEET
LANTERN_AT = (168.2, -240.2)  # 灯笼中心（主角局部坐标）= 旧版渲染件的光心 (1353.2, 665.8)


def ribbon(P, pts, hw0, color, alpha, *, twists=2.0, phase=0.0, edge=0.55):
    """一条飘带：一笔，宽窄随扭转起伏（扭到侧面时变窄），尾端出锋；扭到侧面处一道细墨边。"""
    c = T.curve_pts(pts, 90)
    t = np.linspace(0, 1, len(c))
    tw = 0.35 + 0.65 * np.abs(np.cos(math.pi * twists * t + phase))
    hw = hw0 * tw * (0.25 + 0.75 * np.clip((1 - t) / 0.35, 0, 1) ** 0.6) * np.clip(t / 0.05, 0.4, 1)
    P.stroke(c, hw, color, alpha, jitter=0.08, near=True)
    if edge:
        P.stroke(c + np.array([0.0, 0.6]), np.maximum(hw * 0.25, 0.35) * (1 - tw) + 0.2, NONG, edge * alpha, jitter=0.0, near=True)


def hand(f, x, y, r=3.2):
    """一只手：纸色里一丝赭，两笔勾出指节。"""
    pts = [(x - r, y - r * 0.8), (x + r, y - r), (x + r * 1.1, y + r * 0.6), (x - r * 0.6, y + r)]
    f.knock(pts)
    f.wash(pts, SKIN, 0.4, soft=1.0)
    f.brush([(x - r * 0.9, y - r * 0.6), (x + r * 0.2, y - r * 1.05), (x + r * 1.05, y - r * 0.2)], 0.55, color=NONG, nail=0.2, tail=0.3)
    f.brush([(x + r * 0.9, y + r * 0.1), (x + r * 0.3, y + r * 0.95), (x - r * 0.7, y + r * 0.7)], 0.55, color=NONG, nail=0.2, tail=0.3)


def drape(f, left, right, n, color, alpha, rng, *, shade=0.35, dry=0.55, dry_start=0.72, fill=1.1, hw_min=1.5, skip=()):
    """用几笔侧锋把一片衣服铺出来：left、right 是两边的轮廓（上 → 下），笔顺着衣服往下走，
    笔与笔之间留一线淡处（读作衣褶），收笔处干、起飞白。shade：左（背光）边的笔更重。"""
    m = 80
    L = T.curve_pts(f.pts(left), m)
    R = T.curve_pts(f.pts(right), m)
    for k, u in enumerate(np.linspace(0.5 / n, 1 - 0.5 / n, n)):
        if k in skip:
            continue
        uu = np.clip(u + rng.normal(0, 0.12 / n), 0.02, 0.98)
        c = L + (R - L) * uu
        width = np.linalg.norm(R - L, axis=1) / n
        t = np.linspace(0, 1, m)
        hw = np.maximum(0.5 * width * fill * rng.uniform(0.9, 1.08), hw_min) * np.clip(t / 0.06, 0.5, 1)
        a = alpha * (1 + shade * (0.5 - u) * 2) * rng.uniform(0.88, 1.06)
        f.P.stroke(c, hw, color, float(np.clip(a, 0, 1)), dry=dry * rng.uniform(0.8, 1.15), dry_start=dry_start + rng.uniform(-0.08, 0.1),
                   jitter=0.14, mode="glaze", near=True)


def paint_hero_ink(P, rng, lights):
    """守灯人背影（白衣墨氅、背剑、右手持杖挑灯），往山路上走。返回灯笼中心（画面坐标）。"""
    f = F.Fig(P, *HERO_FEET)
    T.wash_blob(P, HERO_FEET[0] + 4, HERO_FEET[1] + 2, 54, 12, ZHONG, 0.55, rng)
    # ---- 白衣下摆：墨氅下面露出一截，走路时往左后摆
    robe = [(-48, -62), (-54, -38), (-60, -20), (-42, -13), (-20, -17), (2, -11), (24, -15), (44, -21), (44, -62)]
    f.knock(robe)
    f.wash(robe, WASH_L, 0.25, off=(-1.0, 0.8), soft=1.8)
    f.wash([(-54, -38), (-60, -20), (-42, -13), (-30, -16), (-36, -44)], WASH_M, 0.22, soft=1.6)
    f.brush([(-61, -20), (-42, -12), (-20, -17), (2, -10), (24, -14), (45, -21)], 1.2, color=JIAO, press=1.4, dry=0.3, dry_start=0.65)
    f.brush([(-50, -54), (-55, -36), (-61, -20)], 0.9, color=NONG, nail=0.4)
    f.brush([(43, -52), (45, -21)], 0.8, color=NONG, nail=0.4)
    for (a, b) in (((-32, -46), (-38, -15)), ((-8, -46), (-10, -15)), ((22, -48), (26, -14))):
        f.brush([a, b], 0.6, color=NONG, alpha=0.7, nail=0.3, tail=0.5)
    # ---- 靴：后脚跟抬起、露出鞋底；前脚在袍子底下露出一点
    f.fill([(6, -14), (6, -6), (11, -2), (22, -3), (21, -12)], mixc(JIAO, NONG, 0.3), 0.95, mode="over", rim=0.0)
    f.fill([(-25, -15), (-26, -4), (-21, 2), (-8, 2), (-6, -6), (-9, -15)], JIAO, 0.97, mode="over", rim=0.0)
    f.brush([(-24, 0), (-9, 1)], 1.0, color=mixc(DAN, ZHONG, 0.5), smooth=False, nail=0.2, tail=0.2, press=0.0)  # 鞋底
    # ---- 左袖：白色广袖垂在墨氅边上，袖口露出手
    lsl = [(-34, -216), (-46, -204), (-54, -180), (-60, -150), (-64, -124), (-56, -112), (-44, -114), (-40, -140), (-38, -180)]
    f.knock(lsl)
    f.wash(lsl, WASH_L, 0.28, off=(-1.2, 1.0), soft=1.6)
    f.wash([(-46, -200), (-54, -178), (-60, -150), (-63, -126), (-56, -130), (-50, -160)], WASH_M, 0.3, soft=1.5)
    f.brush([(-36, -217), (-46, -204), (-54, -180), (-60, -150), (-65, -123)], 1.4, color=JIAO, press=1.5, dry=0.25)
    f.brush([(-65, -123), (-56, -111), (-44, -113)], 1.0, color=JIAO, nail=0.3)
    f.brush([(-50, -170), (-53, -134)], 0.6, color=NONG, alpha=0.7)
    hand(f, -50, -106, 3.3)
    # ---- 墨氅：擦出留白，淡淡铺一层底，再用几笔侧锋顺着往下铺（笔间留出衣褶），收笔干、飞白
    left = [(-14, -238), (-28, -232), (-36, -220), (-41, -204), (-43, -180), (-45, -150), (-48, -118), (-53, -88), (-61, -64),
            (-71, -48), (-80, -40)]
    right = [(14, -238), (26, -232), (36, -222), (46, -210), (53, -196), (51, -176), (50, -150), (49, -116), (48, -82), (46, -50)]
    hem = [(-80, -40), (-60, -42), (-40, -38), (-18, -45), (4, -41), (26, -46), (46, -50)]
    cloak = left + hem[1:-1] + right[::-1]
    f.knock(cloak)
    f.wash(cloak, mixc(ZHONG, NONG, 0.3), 0.72, soft=1.8, tex=0.08)
    drape(f, left, [(0, -240)] + right[2:], 7, mixc(ZHONG, NONG, 0.5), 0.72, rng, shade=0.45, fill=1.12, dry=0.4, dry_start=0.8)
    f.shade(cloak, NONG, 0.4, side=-1.0)
    # 衣纹：几道焦墨顺着垂下来，起笔重、收笔出锋
    folds = [([(-4, -228), (-6, -170), (-10, -110), (-14, -50)], 1.1), ([(-30, -206), (-34, -150), (-41, -96), (-54, -50)], 1.0),
             ([(22, -214), (27, -150), (30, -96), (32, -50)], 0.9), ([(-22, -104), (-26, -72), (-32, -46)], 0.8),
             ([(10, -108), (12, -76), (15, -48)], 0.8), ([(44, -196), (32, -164), (24, -126)], 0.9)]
    for pts, w in folds:
        f.brush(pts, w, color=JIAO, alpha=0.75, press=1.4, nail=0.6, tail=0.45, dry=0.3, dry_start=0.7)
    # 受灯光的右边：两笔淡处（留白）
    for pts in ([(36, -200), (38, -150), (40, -100), (41, -60)], [(16, -180), (20, -130), (22, -80)]):
        f.brush(pts, 1.6, color=mixc(DAN, PAPER, 0.35), alpha=0.22, nail=0.2, tail=0.5, press=0.2, dry=0.5, dry_start=0.4)
    # 外轮廓：左边一笔长线，按重、后段飞白；下摆断续；右边略细
    f.brush(left[1:], 2.2, color=JIAO, press=1.6, dry=0.35, dry_start=0.68)
    f.brush(hem, 1.5, color=JIAO, press=1.6, dry=0.45, dry_start=0.3, gap=(0.42, 0.5))
    f.brush(right[1:][::-1], 1.7, color=JIAO, press=1.5, dry=0.3, dry_start=0.65)
    # 领口：白衣的交领露出一圈
    f.knock([(-13, -244), (13, -244), (14, -236), (0, -231), (-14, -236)])
    f.brush([(-14, -237), (0, -232), (14, -237)], 1.1, color=JIAO, nail=0.4)
    # ---- 右臂：抬起持杖，白色广袖从小臂上垂下来；墨氅搭在上臂上
    rsl = [(40, -216), (56, -210), (70, -207), (81, -208), (81, -199), (76, -186), (66, -176), (55, -178), (49, -192)]
    f.knock(rsl)
    f.wash(rsl, WASH_L, 0.28, off=(-1.0, 1.0), soft=1.6)
    f.wash([(50, -192), (56, -179), (66, -176), (74, -186), (62, -188)], WASH_M, 0.32, soft=1.4)
    f.brush([(42, -215), (56, -210), (70, -207), (82, -208)], 1.1, color=JIAO, press=1.2, nail=0.4)
    f.brush([(82, -199), (76, -185), (66, -175), (55, -177), (49, -190)], 1.3, color=JIAO, press=1.5, dry=0.25)
    f.brush([(68, -200), (63, -184)], 0.6, color=NONG, alpha=0.7)
    capl = [(24, -234), (38, -224), (52, -212), (58, -201), (46, -203), (32, -214)]
    f.wash(capl, mixc(ZHONG, NONG, 0.45), 0.75, soft=1.5)
    f.brush([(24, -234), (38, -224), (52, -212), (59, -200)], 1.7, color=JIAO, press=1.4, nail=0.5)
    # ---- 背上的剑：剑柄从左肩上探出，剑鞘斜过后背
    g0, g1 = np.array([-21.0, -241.0]), np.array([42.0, -122.0])
    u = (g1 - g0) / np.linalg.norm(g1 - g0)
    nrm = np.array([-u[1], u[0]])
    f.brush([tuple(g0), tuple(g1)], 3.2, color=JIAO, smooth=False, nail=0.2, tail=0.0, press=0.0, dry=0.2, dry_start=0.8)
    for tt in (0.08, 0.6):
        p = g0 + (g1 - g0) * tt
        f.brush([tuple(p - nrm * 3.6), tuple(p + nrm * 3.6)], 0.8, color=mixc(ZHONG, TENG, 0.18), alpha=0.7, smooth=False, nail=0.0,
                tail=0.0, press=0.0)
    f.brush([tuple(g0 - nrm * 7.5 - u), tuple(g0 + nrm * 7.5 - u)], 1.7, color=JIAO, smooth=False, nail=0.3, tail=0.2)  # 剑格
    pm = g0 - u * 26
    f.brush([tuple(g0 - u * 2), tuple(pm)], 2.2, color=mixc(NONG, ZHESHI, 0.2), smooth=False, nail=0.1, tail=0.0, press=0.0)  # 剑柄
    for k in range(4):  # 缠绳
        p = g0 - u * (6 + 5 * k)
        f.brush([tuple(p - nrm * 2.3 - u * 1.2), tuple(p + nrm * 2.3 + u * 1.2)], 0.55, color=JIAO, smooth=False, nail=0.0, tail=0.0,
                press=0.0)
    f.dot(pm[0] - u[0] * 1.5, pm[1] - u[1] * 1.5, 2.6, JIAO, 0.95)  # 剑首
    ribbon(P, f.pts([tuple(pm), (pm[0] - 7, pm[1] + 5), (pm[0] - 13, pm[1] + 14), (pm[0] - 16, pm[1] + 26)]), 1.5, ZHUSHA, 0.9,
           twists=1.0)  # 剑穗
    # ---- 头：后脑全是头发（焦墨），右边露一点耳朵；发髻、发冠、簪子
    hx, hy = 2.0, -258.0
    head = [(hx - 15, hy + 4), (hx - 14, hy - 10), (hx - 8, hy - 19), (hx + 4, hy - 21), (hx + 13, hy - 13), (hx + 16, hy + 2),
            (hx + 12, hy + 14), (hx + 4, hy + 19), (hx - 8, hy + 17), (hx - 13, hy + 11)]
    f.knock([(hx + 12, hy - 2), (hx + 18, hy - 1), (hx + 18, hy + 9), (hx + 13, hy + 11)])
    f.wash([(hx + 13, hy - 1), (hx + 17, hy), (hx + 17, hy + 8), (hx + 13, hy + 10)], SKIN, 0.45, soft=1.0)
    f.brush([(hx + 14, hy), (hx + 18, hy + 2), (hx + 17, hy + 8), (hx + 14, hy + 10)], 0.6, color=NONG, nail=0.3, tail=0.3)  # 耳
    f.fill(head, HAIR, 0.9, mode="over", rim=0.0, soft=0.5)
    f.wash([(hx + 4, hy - 19), (hx + 12, hy - 12), (hx + 15, hy + 2), (hx + 11, hy + 13), (hx + 6, hy + 4), (hx + 5, hy - 10)],
           mixc(ZHONG, DAN, 0.3), 0.5, mode="over", soft=1.4, ring=0.0)  # 受灯光的一侧略淡
    for k in range(6):  # 发丝：从发际往发髻梳上去
        x = hx - 11 + k * 4.4
        f.brush([(x + (k - 2.5) * 0.8, hy + 15 - abs(k - 2.5) * 1.6), (x + (k - 2.5) * 0.3, hy), (hx - 1 + (k - 2.5) * 1.2, hy - 19)],
                0.45, color=mixc(ZHONG, NONG, 0.3) if k >= 3 else JIAO, alpha=0.6, nail=0.0, tail=0.5, press=0.2)
    f.brush([(hx - 13, hy + 12), (hx - 15, hy), (hx - 13, hy - 11), (hx - 6, hy - 19), (hx + 4, hy - 21), (hx + 12, hy - 14)], 1.3,
            color=JIAO, press=1.4, nail=0.5, tail=0.35)
    f.brush([(hx + 13, hy - 12), (hx + 16, hy), (hx + 12, hy + 13)], 0.8, color=JIAO, nail=0.3, tail=0.4, gap=(0.35, 0.55))
    # 长发：从发髻垂到背中，被风带向左；发梢散开、飞白
    tail_c = T.curve_pts(f.pts([(hx - 1, hy - 18), (hx - 2, hy + 6), (hx - 5, hy + 34), (hx - 10, hy + 62), (hx - 17, hy + 86),
                                (hx - 25, hy + 102)]), 90)
    tt = np.linspace(0, 1, len(tail_c))
    P.stroke(tail_c, np.interp(tt, [0, 0.2, 0.55, 0.85, 1], [8.0, 9.0, 6.5, 3.6, 0.9]), HAIR, 0.96, dry=0.45, dry_start=0.7,
             jitter=0.12, near=True)
    for k in range(4):  # 发梢几缕
        d = (k - 1.5) * 2.4
        f.brush([(hx - 8 + d, hy + 58), (hx - 16 + d * 1.6, hy + 88), (hx - 27 + d * 2.4, hy + 108 + k * 3)], 0.75, color=JIAO,
                alpha=0.85, nail=0.0, tail=0.7, press=0.3, dry=0.4, dry_start=0.5)
    for k in range(3):  # 发上几道受光的淡丝
        f.brush([(hx + 1 + k * 1.5, hy + 4), (hx - 1 + k, hy + 34), (hx - 6 + k, hy + 62)], 0.45, color=mixc(DAN, ZHONG, 0.5),
                alpha=0.45, nail=0.0, tail=0.6, press=0.0)
    f.dot(hx - 1, hy - 24, 8.0, HAIR, 0.97)  # 发髻
    crown = [(hx - 7, hy - 29), (hx - 6, hy - 37), (hx - 1, hy - 40), (hx + 5, hy - 37), (hx + 6, hy - 29)]
    f.knock(crown)
    f.wash(crown, mixc(QING, PAPER, 0.4), 0.4, soft=0.8)
    f.brush(crown + [crown[0]], 0.7, color=JIAO, nail=0.2, tail=0.1, press=0.6)
    f.brush([(hx - 15, hy - 31), (hx + 16, hy - 34)], 0.85, color=mixc(NONG, ZHESHI, 0.2), smooth=False, nail=0.4, tail=0.3)  # 簪
    # 发带：两条朱砂，从发髻向左后方飘
    ribbon(P, f.pts([(hx - 6, hy - 27), (hx - 26, hy - 18), (hx - 48, hy + 4), (hx - 70, hy + 26), (hx - 94, hy + 42), (hx - 116, hy + 58)]),
           3.3, ZHUSHA, 0.92, twists=2.2, phase=0.3)
    ribbon(P, f.pts([(hx - 6, hy - 24), (hx - 20, hy - 6), (hx - 36, hy + 16), (hx - 54, hy + 36), (hx - 74, hy + 50)]),
           2.7, mixc(ZHUSHA, JIAO, 0.12), 0.9, twists=1.6, phase=1.4)
    # ---- 杖与灯笼
    tip = np.array([171.0, -276.0])
    hnd = np.array([84.0, -204.0])
    ud = (tip - hnd) / np.linalg.norm(tip - hnd)
    butt = hnd - ud * 22
    f.brush([tuple(butt), tuple((butt + tip) / 2 + np.array([0, -1.0])), tuple(tip)], 3.0, color=mixc(NONG, ZHESHI, 0.3), nail=0.4,
            tail=0.0, press=0.0, dry=0.15, dry_start=0.8)
    f.brush([tuple(butt + np.array([0.5, -1.5])), tuple(tip + np.array([0.5, -1.5]))], 0.55, color=mixc(DAN, ZHESHI, 0.4), alpha=0.6,
            smooth=False, nail=0.0, tail=0.3, press=0.0)
    f.dot(tip[0] + 1, tip[1] - 1, 3.0, mixc(TENG, ZHESHI, 0.4), 0.95)
    hand(f, *hnd, 3.5)
    lx, ly = LANTERN_AT
    f.brush([(tip[0] - 1, tip[1] + 2), (lx + 0.5, ly - 19)], 0.55, color=NONG, smooth=False, nail=0.0, tail=0.0, press=0.0)
    gx, gy = f.pt(lx, ly)
    rx, ry = 15.0, 18.0
    sl = (slice(int(gy - 32), int(gy + 32)), slice(int(gx - 28), int(gx + 28)))
    X, Y = P.X[sl], P.Y[sl]
    rho = np.hypot((X - gx) / rx, (Y - gy) / ry)
    body = smoothstep(1.06, 0.86, rho)
    P.over(body * 0.96, mixc(ZHUSHA, PAPER, 0.3), sl)
    P.mark_near(body, sl)
    glow = body * (0.34 + 0.5 * np.exp(-(rho / 0.6) ** 2))
    P.emit[sl] += glow[..., None] * mixc(ZHUSHA, FLAME_LIGHT, 0.5) + (np.exp(-(rho / 0.4) ** 2) * 0.8)[..., None] * mixc(
        FLAME_LIGHT, WHITE, 0.5)
    for k in (-0.62, 0.0, 0.62):  # 竹骨：几道淡墨弧
        th = np.linspace(-1.25, 1.25, 16)
        f.brush([(lx + k * rx * np.cos(a), ly + ry * np.sin(a) * 0.95) for a in th], 0.45, color=mixc(ZHUSHA, JIAO, 0.45), alpha=0.6,
                nail=0.0, tail=0.1, press=0.0)
    edge = body * (1 - smoothstep(0.35, 0.9, blur(body, 1.3)))
    P.over(np.clip(edge * 1.2, 0, 0.7), mixc(ZHUSHA, JIAO, 0.5), sl)
    f.brush([(lx - 7, ly - ry + 0.5), (lx + 7, ly - ry + 0.5)], 2.0, color=JIAO, smooth=False, nail=0.3, tail=0.1, press=0.0)
    f.brush([(lx - 7, ly + ry - 0.5), (lx + 7, ly + ry - 0.5)], 2.0, color=JIAO, smooth=False, nail=0.3, tail=0.1, press=0.0)
    ribbon(P, f.pts([(lx, ly + ry + 2), (lx - 1.5, ly + ry + 12), (lx - 4, ly + ry + 24)]), 1.4, ZHUSHA, 0.9, twists=0.5)  # 灯穗
    lights.append((gx, gy, 480.0, mixc(LAMP_LIGHT, WHITE, 0.22), 1.12, HERO_FEET[1] + 8))
    lights.append((gx, gy, 170.0, LAMP_LIGHT, 0.35, None))
    return gx, gy


def paint_stone_lantern_ink(P, rng, x, y, s, lights):
    """石灯笼（写意）：基座、竿、中台、火袋（窗里透火光）、翘角的笠、宝珠。先擦出留白、淡墨铺底，
    再用侧锋的宽笔一块块压出石头（左边背光更重），枯笔勾边、断续，苔点。局部坐标按旧渲染件的尺寸（缩放 s）。"""
    f = F.Fig(P, x, y, s)
    T.wash_blob(P, x + 4, y + 2, 46 * s * 1.4, 10 * s * 1.4, ZHONG, 0.5, rng)
    stone = mixc(DAN, ZHONG, 0.3)

    def jit(pts, a=1.2):
        return [(px + rng.normal(0, a), py + rng.normal(0, a * 0.6)) for px, py in pts]

    parts = {
        "base": jit([(-45, 7), (-47, -7), (-39, -14), (39, -14), (47, -7), (45, 7)]),
        "cap": jit([(-31, -14), (-27, -26), (27, -26), (31, -14)]),
        "shaft": jit([(-14, -26), (-13, -96), (13, -96), (14, -26)], 0.8),
        "mid": jit([(-24, -96), (-35, -103), (-35, -114), (35, -114), (35, -103), (24, -96)]),
        "box": jit([(-21, -114), (-22, -146), (22, -146), (21, -114)], 0.8),
    }
    for k, poly in parts.items():
        f.knock(poly, smooth=False)
        f.wash(poly, stone, 0.45, off=(-1.2, 0.8), smooth=False, soft=1.6, tex=0.25)
    # 侧锋压出石块：左（背光）重、右淡，干笔带飞白
    def slab(y0, y1, x0, x1, a, n=3, horiz=False):
        for k in range(n):
            if horiz:
                yy = y0 + (y1 - y0) * (k + 0.5) / n
                pts = [(x0 + rng.uniform(-1, 2), yy + rng.normal(0, 0.6)), (x1 + rng.uniform(-2, 1), yy + rng.normal(0, 0.6))]
                hw = (y1 - y0) / n * 0.75
            else:
                xx = x0 + (x1 - x0) * (k + 0.5) / n
                pts = [(xx + rng.normal(0, 0.6), y0 + rng.uniform(-1, 1)), (xx + rng.normal(0, 0.8), y1 + rng.uniform(-1, 1))]
                hw = (x1 - x0) / n * 0.7
            aa = a * (1.25 - 0.6 * k / max(n - 1, 1)) if not horiz else a
            f.brush(pts, hw, color=mixc(ZHONG, NONG, 0.3), alpha=float(np.clip(aa * rng.uniform(0.85, 1.1), 0, 1)), smooth=False,
                    dry=0.6, dry_start=0.25, nail=0.2, tail=0.15, press=0.0, mode="glaze")
    slab(-28, -94, -13, 2, 0.5, n=2)  # 竿：左半
    slab(-116, -144, -20, -4, 0.45, n=2)  # 火袋：左边
    slab(-114, -103, -34, 20, 0.4, n=1, horiz=True)  # 中台
    slab(-14, -2, -44, 18, 0.38, n=2, horiz=True)  # 基座
    # 笠：一笔重墨的宽笔铺出屋面，两头翘起；檐下一道焦墨
    roof = jit([(-9, -177), (-28, -162), (-46, -154), (-53, -160), (-47, -148), (47, -148), (53, -160), (46, -154), (28, -162),
                (9, -177)], 0.8)
    f.knock(roof)
    f.wash(roof, mixc(DAN, ZHONG, 0.5), 0.6, off=(-1, 0.8), soft=1.4, tex=0.3)
    for k, (yy, a) in enumerate(((-158, 0.62), (-165, 0.5), (-171, 0.42))):
        wdt = 42 - 13 * k
        f.brush([(-wdt, yy + 4 + k), (0, yy - 2), (wdt, yy + 4 + k)], 3.4 - 0.6 * k, color=NONG, alpha=a, dry=0.55, dry_start=0.4,
                nail=0.3, tail=0.3, press=0.3, mode="glaze")
    f.brush([(-52, -159), (-45, -149), (0, -148), (45, -149), (52, -159)], 1.9, color=JIAO, press=1.6, dry=0.3, dry_start=0.6,
            nail=0.5, tail=0.25)
    f.brush([(-9, -177), (-28, -162), (-46, -154), (-54, -161)], 1.4, color=JIAO, press=1.4, dry=0.4, dry_start=0.5, nail=0.6,
            tail=0.3)
    f.brush([(9, -177), (28, -162), (46, -154), (54, -161)], 1.2, color=JIAO, press=1.4, dry=0.45, dry_start=0.4, nail=0.6,
            tail=0.3, gap=(0.35, 0.5))
    # 宝珠
    jew = [(-6, -176), (-6, -185), (0, -194), (6, -185), (6, -176)]
    f.knock(jew)
    f.wash(jew, stone, 0.45, soft=1.1)
    f.brush([(-6, -176), (-6, -185), (0, -195), (6, -185)], 0.9, color=JIAO, nail=0.3, tail=0.4, press=1.2)
    # 窗：火光
    wx0, wx1, wy0, wy1 = -9.0, 9.0, -140.0, -121.0
    (gx0, gy0), (gx1, gy1) = f.pt(wx0, wy0), f.pt(wx1, wy1)
    sl = (slice(int(gy0) - 6, int(gy1) + 6), slice(int(gx0) - 6, int(gx1) + 6))
    Xw, Yw = P.X[sl], P.Y[sl]
    dd = np.minimum(np.minimum(Xw - gx0, gx1 - Xw), np.minimum(Yw - gy0, gy1 - Yw)) + 0.8 * noise(rng, Xw.shape, 1.2)
    win = smoothstep(-0.6, 0.8, dd)
    P.over(win * 0.97, mixc(PAPER, FLAME_LIGHT, 0.45), sl)
    P.mark_near(win, sl)
    cx_, cy_ = (gx0 + gx1) / 2, gy0 + (gy1 - gy0) * 0.62
    P.emit[sl] += (win * (0.42 + 0.5 * np.exp(-(((Xw - cx_) / (6 * s)) ** 2 + ((Yw - cy_) / (8 * s)) ** 2))))[..., None] * FLAME_LIGHT * 0.95
    k = dict(color=JIAO, press=1.5, dry=0.35, dry_start=0.55)
    f.brush([(wx0, wy0), (wx0 + 0.5, wy1)], 1.1, smooth=False, nail=0.3, tail=0.1, **k)
    f.brush([(wx1, wy0), (wx1 - 0.5, wy1)], 1.0, smooth=False, nail=0.3, tail=0.1, **k)
    f.brush([(0, wy0), (0, wy1)], 0.7, color=NONG, smooth=False, nail=0.0, tail=0.0, press=0.0)  # 窗棂
    # 轮廓：枯笔勾，断续，左边重
    f.brush([(-21, -146), (-22, -130), (-21, -114)], 1.4, smooth=False, nail=0.5, tail=0.2, **k)
    f.brush([(21, -146), (22, -130), (21, -114)], 1.0, smooth=False, nail=0.5, tail=0.2, gap=(0.4, 0.62), **k)
    f.brush([(-36, -114), (0, -115), (36, -114)], 1.3, nail=0.5, tail=0.2, **k)
    f.brush([(-36, -113), (-35, -104), (-24, -96), (24, -96), (35, -104)], 1.1, smooth=False, nail=0.4, tail=0.3, gap=(0.55, 0.7), **k)
    f.brush([(-14, -96), (-13, -60), (-14, -26)], 1.5, nail=0.6, tail=0.2, **k)
    f.brush([(14, -95), (13, -62), (14, -27)], 1.0, nail=0.5, tail=0.3, gap=(0.3, 0.45), **k)
    f.brush([(-31, -14), (-27, -26), (27, -26), (31, -14)], 1.1, smooth=False, nail=0.4, tail=0.3, **k)
    f.brush([(-47, -7), (-39, -14), (39, -14), (47, -7)], 1.2, smooth=False, nail=0.5, tail=0.2, gap=(0.6, 0.72), **k)
    f.brush([(-47, -7), (-45, 7), (45, 7)], 1.6, smooth=False, nail=0.5, tail=0.3, **k)
    for (dx, dy, r) in ((-38, -156, 2.6), (-22, -164, 2.0), (31, -157, 2.3), (-41, -9, 2.4), (-30, 3, 2.0), (38, 2, 2.2),
                        (-11, -28, 1.8), (-15, -99, 1.8), (6, -178, 1.6)):
        f.dot(dx + rng.normal(0, 2), dy + rng.normal(0, 1), r, JIAO, 0.9)
    fx, fy = f.pt(-4.0, -128.0)
    lights.append((fx, fy, 190 * s, FLAME_LIGHT, 0.55, y))
