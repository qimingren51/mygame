    # ---------------- 进阶属性（属性面板“输出、生存、灯与照见、构筑与收益”几组）
    elif key == "knockback":  # 一记往右推的箭头，撞开一个圆（妖物），圆后三道退开的弧
        fill([(8, 28.5), (27, 28.5), (27, 22), (38, 32), (27, 42), (27, 35.5), (8, 35.5)])
        arc(46, 32, 6.5, 0, 360, 3.0, 40)
        for k_, r_ in enumerate((11.5, 15.5)):
            arc(46, 32, r_, -38 + 6 * k_, 38 - 6 * k_, 2.6 - 0.4 * k_, 20)
    elif key == "burn":  # 一朵火苗（里面掏一朵小的）
        out = np.vstack([bez([(32, 54), (17, 52), (14, 38), (22, 28), (24, 34), (27, 30), (26, 20), (33, 9)]),
                         bez([(33, 9), (36, 20), (44, 22), (46, 32), (50, 40), (46, 52), (32, 54)])])
        fill(out)
        inner = np.vstack([bez([(32, 50), (25, 48), (24, 41), (29, 35), (31, 30)]), bez([(31, 30), (36, 37), (40, 41), (38, 48), (32, 50)])])
        dist, _ = W.poly_sdf(c.X, c.Y, inner, pad=2.0)
        m = m * (1 - smoothstep(c.aa, -c.aa, dist) * 0.85)
    elif key == "freeze":  # 六出冰花
        for k_ in range(6):
            a = math.radians(-90 + 60 * k_)
            ca, sa = math.cos(a), math.sin(a)
            line([(32, 32), (32 + 22 * ca, 32 + 22 * sa)], 3.0)
            for d_, L_ in ((10.0, 6.5), (16.0, 5.0)):
                bx, by = 32 + d_ * ca, 32 + d_ * sa
                for s_ in (-1, 1):
                    b = a + s_ * math.radians(55)
                    line([(bx, by), (bx + L_ * math.cos(b), by + L_ * math.sin(b))], 2.4)
        m = np.maximum(m, dot(c, 32, 32, 3.4))
    elif key == "slow":  # 蜗牛：一个盘起的壳 + 贴地的身子 + 两根触角
        line(spiral(34, 30, 2.0, 13.0, math.radians(200), 1.6, 60), 3.0)
        line(bez([(10, 46), (18, 45), (40, 46), (50, 45)]), 3.6)
        line(bez([(12, 46), (9, 40), (10, 34)]), 3.0)
        line([(10, 34), (6, 26)], 2.2)
        line([(11, 34), (14, 25)], 2.2)
        m = np.maximum(m, dot(c, 6, 25, 2.0))
        m = np.maximum(m, dot(c, 14, 24, 2.0))
    elif key == "proj_speed":  # 一支飞刃往右上疾飞，身后三道疾线
        fill([(52, 12), (44, 26), (40, 22)])
        line([(42, 24), (24, 42)], 3.4)
        line([(20, 38), (28, 46)], 3.0)
        for k_, (x0, y0, L_) in enumerate(((18, 30, 12), (24, 50, 12), (12, 44, 8))):
            line([(x0, y0), (x0 - L_ * 0.7, y0 + L_ * 0.7)], 2.6)
    elif key == "duration":  # 一道长长的弧线飞行轨迹（虚线），头上一枚箭头
        t = np.linspace(0, 1, 9)
        for i in range(8):
            if i % 2:
                continue
            seg = np.linspace(t[i], t[i + 1], 8)
            a = np.radians(200 + 130 * seg)
            line(np.stack([32 + 20 * np.cos(a), 44 + 20 * np.sin(a)], -1), 3.0)
        a1 = math.radians(330)
        tip = (32 + 20 * math.cos(a1), 44 + 20 * math.sin(a1))
        fill([(tip[0] + 6, tip[1] - 6), (tip[0] - 5, tip[1] - 3), (tip[0] + 2, tip[1] + 5)])
        m = np.maximum(m, dot(c, 32 + 20 * math.cos(math.radians(200)), 44 + 20 * math.sin(math.radians(200)), 3.0))
    elif key == "reaction":  # 两个相交的圈（两系相遇），交汇处迸一颗星
        arc(25, 32, 12, 0, 360, 3.0, 60)
        arc(39, 32, 12, 0, 360, 3.0, 60)
        pts = []
        for i in range(8):
            r = 9.0 if i % 2 == 0 else 3.0
            a = math.radians(-90 + 45 * i)
            pts.append((32 + r * math.cos(a), 32 + r * math.sin(a)))
        fill(pts)
    elif key == "stun":  # 一圈椭圆轨道，三颗小星绕着转（被打晕）
        t = np.linspace(0, 2 * math.pi, 80)
        line(np.stack([32 + 20 * np.cos(t), 34 + 8 * np.sin(t)], -1), 2.6)
        for (sx, sy, r_) in ((14, 30, 6.5), (37, 42, 7.5), (46, 26, 6.0)):
            pts = []
            for i in range(8):
                r = r_ if i % 2 == 0 else r_ * 0.38
                a = math.radians(-90 + 45 * i)
                pts.append((sx + r * math.cos(a), sy + r * math.sin(a)))
            fill(pts)
    elif key == "dash":  # 一道往右上甩的弧形箭头，身后两道残影
        for k_, (dx, w_) in enumerate(((0.0, 3.6), (-7.0, 2.4), (-13.0, 1.6))):
            line(bez([(14 + dx, 50), (18 + dx, 30), (34 + dx, 22), (46 + dx * 0.4, 20)]), w_)
        fill([(54, 18), (44, 12), (45, 27)])
    elif key == "shield":  # 一个罩子：半球的光罩扣在地上，罩里一点（人）
        arc(32, 44, 21, 180, 360, 3.4, 60)
        arc(32, 44, 14, 200, 340, 2.2, 40)
        line([(8, 45), (56, 45)], 3.2)
        m = np.maximum(m, dot(c, 32, 38, 3.4))
    elif key == "heal":  # 药葫芦：上小下大两节，腰上一道绳，葫芦嘴一片叶
        arc(32, 22, 7.5, 0, 360, 3.0, 40)
        arc(32, 40, 12.5, 0, 360, 3.2, 60)
        line([(24, 30), (40, 30)], 2.6)
        line([(32, 14.5), (32, 9)], 3.0)
        fill(np.vstack([bez([(33, 11), (38, 6), (45, 7), (46, 9)]), bez([(46, 9), (41, 13), (36, 13), (33, 11)])]))
        line([(32, 35), (32, 45)], 2.6)
        line([(27, 40), (37, 40)], 2.6)
    elif key == "reveal":  # 照见：一只眼，四周一圈光芒
        t = np.linspace(0, 1, 40)
        line(np.stack([14 + 36 * t, 32 - 10 * np.sin(np.pi * t)], -1), 3.0)
        line(np.stack([14 + 36 * t, 32 + 10 * np.sin(np.pi * t)], -1), 3.0)
        m = np.maximum(m, dot(c, 32, 32, 5.0))
        for a in (-90, -45, -135, 90, 45, 135):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            line([(32 + 17 * ca, 32 + 17 * sa), (32 + 23 * ca, 32 + 23 * sa)], 2.6)
    elif key == "reveal_vuln":  # 照见易伤：一只眼，眼上一道裂（破绽）
        t = np.linspace(0, 1, 40)
        line(np.stack([10 + 36 * t, 36 - 10 * np.sin(np.pi * t)], -1), 3.0)
        line(np.stack([10 + 36 * t, 36 + 10 * np.sin(np.pi * t)], -1), 3.0)
        m = np.maximum(m, dot(c, 28, 36, 5.0))
        line([(56, 8), (48, 18), (52, 20), (42, 32)], 3.0)
    elif key == "light":  # 灯光：一盏油灯（灯盏 + 火苗），上面三道光
        line(bez([(18, 44), (24, 52), (40, 52), (46, 44)]), 3.2)
        line([(16, 44), (48, 44)], 3.0)
        line([(32, 52), (32, 57)], 3.0)
        line([(24, 57), (40, 57)], 3.0)
        fill(np.vstack([bez([(32, 41), (25, 38), (27, 30), (32, 22)]), bez([(32, 22), (37, 30), (39, 38), (32, 41)])]))
        for a in (-90, -50, -130):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            line([(32 + 15 * ca, 30 + 15 * sa), (32 + 21 * ca, 30 + 21 * sa)], 2.6)
    elif key == "flame_band":  # 灯焰带：一圈火环（斜着的椭圆），环上三朵火苗
        t = np.linspace(0, 2 * math.pi, 90)
        line(np.stack([32 + 21 * np.cos(t), 36 + 10 * np.sin(t)], -1), 3.0)
        for (fx, fy, s_) in ((14, 32, 0.8), (32, 46, 1.0), (49, 31, 0.8)):
            fill(np.vstack([bez([(fx, fy + 3 * s_), (fx - 5 * s_, fy), (fx - 2 * s_, fy - 7 * s_), (fx + 1 * s_, fy - 12 * s_)]),
                            bez([(fx + 1 * s_, fy - 12 * s_), (fx + 5 * s_, fy - 6 * s_), (fx + 5 * s_, fy), (fx, fy + 3 * s_)])]))
        m = np.maximum(m, dot(c, 32, 30, 3.0))
    elif key == "ult":  # 燃灯充能：一圈刻度（亮的粗、没亮的细）围着一朵火
        for k_ in range(12):
            a = math.radians(-90 + 30 * k_)
            ca, sa = math.cos(a), math.sin(a)
            lit = k_ < 8
            line([(32 + 16 * ca, 32 + 16 * sa), (32 + 23 * ca, 32 + 23 * sa)], 3.4 if lit else 1.4)
        fill(np.vstack([bez([(32, 42), (24, 38), (26, 29), (32, 20)]), bez([(32, 20), (38, 29), (40, 38), (32, 42)])]))
    elif key == "soul":  # 魂火：圆头的鬼火，拖一条打卷的尾巴
        m = np.maximum(m, dot(c, 38, 24, 9.5))
        line(np.vstack([bez([(31, 30), (24, 40), (30, 48), (22, 54)]), spiral(19, 51, 3.0, 0.5, math.radians(0), 0.9, 16)]), 3.0)
        line(bez([(44, 31), (44, 42), (38, 48)]), 2.2)
        hole = np.hypot(c.X - 40, c.Y - 21) < 3.2
        m = np.where(hole, m * 0.2, m)
    elif key == "oil":  # 灯油：一滴油（水滴形），里面一道高光，下面一汪
        out = np.vstack([bez([(32, 8), (26, 20), (18, 30), (18, 38)]), bez([(18, 38), (18, 47), (25, 52), (32, 52)]),
                         bez([(32, 52), (39, 52), (46, 47), (46, 38)]), bez([(46, 38), (46, 30), (38, 20), (32, 8)])])
        fill(out)
        hi = np.vstack([bez([(25, 34), (25, 41), (28, 46), (31, 47)])])
        m = np.clip(m - stroke_mask(c, hi, 1.4) * 0.85, 0, 1)
        line(bez([(12, 57), (24, 54), (40, 54), (52, 57)]), 2.6)
    elif key == "coin":  # 铜钱：三枚摞着斜放（和“构筑与收益”的单枚钱分开）
        for (cx, cy) in ((24, 40), (33, 32), (42, 24)):
            m = np.where(np.hypot(c.X - cx, c.Y - cy) < 12.8, m * 0.0, m)
            arc(cx, cy, 11, 0, 360, 3.0, 60)
            line([(cx - 3.8, cy - 3.8), (cx + 3.8, cy - 3.8), (cx + 3.8, cy + 3.8), (cx - 3.8, cy + 3.8), (cx - 3.8, cy - 3.8)], 2.4)
    elif key == "chest":  # 宝箱：箱身 + 拱顶盖 + 一把锁
        line([(12, 30), (52, 30), (52, 52), (12, 52), (12, 30)], 3.2)
        line(bez([(12, 30), (14, 16), (50, 16), (52, 30)]), 3.2)
        line([(12, 36), (52, 36)], 2.4)
        fill([(28, 33), (36, 33), (36, 43), (28, 43)])
        m = np.where((np.abs(c.X - 32) < 1.2) & (c.Y > 37) & (c.Y < 41), m * 0.2, m)
