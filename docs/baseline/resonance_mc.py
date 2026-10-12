"""共鸣计点规则的蒙特卡洛模拟（BALANCE.md 第 7.1 节）。

专精机器人只挑一系（有 2 次重抽）；兼修机器人优先补点数最少的一系。
等级时间按“击杀≈刷怪、晚 8 秒”的节奏模型算出（BALANCE.md 第 4.3 节），宝箱在 2:50、5:00、6:40、8:00。

用法：
  python3 resonance_mc.py               # 1.0 内容：每系 3 件法器 + 4 门心法，新旧规则对比
  python3 resonance_mc.py --content p0  # P0 内容：每系 1 件法器 + 3 门心法，只算新规则
"""

import argparse
import random
import statistics as st

ELEMENTS = 5
RULES = {
    # 名字：(计点方式, 一阶/二阶/三阶/极境的阈值)
    "old": ("每件 1 点、满级 2 点", (2, 4, 6, 10)),
    "new": ("按投入计点", (3, 7, 12, 20)),
}


def xp_need(n):
    return 4 + 5 * n + 0.6 * n * n


def level_times(lag=8.0):
    """按刷怪曲线、击杀晚 lag 秒、魂火价值 1（石妖 3）算每次升级的时间。"""
    spawn = lambda m: 2 + 1.6 * m + 0.45 * m * m
    packs = lambda m: (8 + 5 * m) / 25 if m >= 40 / 60 else 0
    golem_share = lambda m: 0 if m < 2.5 else 0.125 * (1.6 if m >= 5 else 1)
    dt = 1 / 60
    t, xp, lv, times, queue = 0.0, 0.0, 1, [], []
    while t <= 600:
        m = t / 60
        rate = spawn(m) + packs(m)
        if 480 <= t < 510:  # 妖潮
            rate += 2 * spawn(m)
        n = rate * dt
        if abs(t - 240) < dt / 2:  # 合围
            n += 80
        if abs(t - 420) < dt / 2:
            n += 110
        queue.append((t + lag, n, m))
        while queue and queue[0][0] <= t:
            _, c, ms = queue.pop(0)
            xp += c * (1 + 2 * golem_share(ms))
        for te, v in ((170, 20), (300, 40), (400, 30), (480, 30)):  # 精英、小头目
            if abs(t - te) < dt / 2:
                xp += v
        while xp >= xp_need(lv):
            xp -= xp_need(lv)
            lv += 1
            times.append(t)
        t += dt
    return times


class Content:
    def __init__(self, weapons_per_el, passives_per_el):
        self.W = [(e, j) for e in range(ELEMENTS) for j in range(weapons_per_el)]
        self.P = [(e, j) for e in range(ELEMENTS) for j in range(passives_per_el)] + [(-1, 0), (-1, 1)]
        self.wpe = weapons_per_el


def weapon_points(lv, evo, rule):
    if rule == "new":
        return 4 if evo else 3 if lv >= 8 else 2 if lv >= 4 else 1
    return 2 if (lv >= 8 or evo) else 1


def passive_points(lv, rule):
    if rule == "new":
        return 3 if lv >= 5 else 2 if lv >= 3 else 1
    return 2 if lv >= 5 else 1


def points(c, s, rule):
    pts = [0] * ELEMENTS
    for w, (lv, evo) in s["w"].items():
        pts[c.W[w][0]] += weapon_points(lv, evo, rule)
    for p, lv in s["p"].items():
        e = c.P[p][0]
        if e >= 0:
            pts[e] += passive_points(lv, rule)
    return pts


def options(c, s, t, rule, th):
    tier1 = [p >= th[0] for p in points(c, s, rule)]
    opts = []
    for w, (lv, evo) in s["w"].items():
        e, j = c.W[w]
        key = c.P.index((e, j)) if (e, j) in c.P else -1
        if lv >= 8 and not evo and key in s["p"]:
            opts.append(("evo", w, 1000.0))
        elif lv < 8:
            opts.append(("wup", w, 10.0))
    if len(s["w"]) < 6:
        opts += [("wnew", w, 9.0 if t < 180 else 5.0) for w in range(len(c.W)) if w not in s["w"]]
    opts += [("pup", p, 7.0) for p, lv in s["p"].items() if lv < 5]
    if len(s["p"]) < 6:
        opts += [("pnew", p, 5.0) for p in range(len(c.P)) if p not in s["p"]]
    out = []
    for typ, i, wt in opts:
        if typ != "evo":
            e = c.W[i][0] if typ in ("wup", "wnew") else c.P[i][0]
            if e >= 0 and tier1[e]:
                wt *= 1.5
            if e == s["home"]:
                wt *= 1.2
        out.append((typ, i, wt))
    return out


def draw(opts, n, rng):
    pool, res = opts[:], []
    while pool and len(res) < n:
        r = rng.random() * sum(o[2] for o in pool)
        for k, o in enumerate(pool):
            r -= o[2]
            if r <= 0:
                break
        res.append(pool.pop(k))
    return res


def apply(s, o):
    typ, i, _ = o
    if typ == "evo":
        s["w"][i] = (8, True)
    elif typ == "wup":
        lv, evo = s["w"][i]
        s["w"][i] = (lv + 1, evo)
    elif typ == "wnew":
        s["w"][i] = (1, False)
    elif typ == "pup":
        s["p"][i] += 1
    else:
        s["p"][i] = 1


def score_mono(c, s, o, home):
    typ, i, _ = o
    if typ == "evo":
        return 1000
    if typ in ("wup", "wnew"):
        if c.W[i][0] == home:
            return 100 + (s["w"][i][0] if typ == "wup" else -10)
        return 30 if typ == "wup" else (25 if len(s["w"]) < 3 else 5)
    e, j = c.P[i]
    if e == home:
        key_for_held = j < c.wpe and any(c.W[w] == (home, j) for w in s["w"])
        if typ == "pnew":
            return 95 if key_for_held else 60
        return 75 if key_for_held else 70
    return 20 if e < 0 else 10


def score_balanced(c, s, o, rule, th):
    typ, i, _ = o
    if typ == "evo":
        return 1000
    e = c.W[i][0] if typ in ("wup", "wnew") else c.P[i][0]
    if e < 0:
        return 5
    pts = points(c, s, rule)
    need = max(0, th[0] - pts[e])
    return {"wup": 40, "wnew": 50, "pup": 30, "pnew": 45}[typ] + 30 * need - 2 * pts[e]


def simulate(c, rule, th, mode, rng, ltimes, home=0):
    s = {"w": {home * c.wpe: (1, False)}, "p": {}, "home": home}
    events = sorted([(t, "lv", 0) for t in ltimes] + [(t, "chest", n) for t, n in ((170, 1), (300, 3), (400, 1), (480, 1))])
    reach, rerolls = {}, 2
    for t, kind, n in events:
        if t > 570:
            break
        if kind == "lv":
            opts = options(c, s, t, rule, th)
            if not opts:
                continue
            k = 4 if rng.random() < 0.1 else 3
            choice = draw(opts, k, rng)
            sc = (lambda o: score_mono(c, s, o, home)) if mode == "mono" else (lambda o: score_balanced(c, s, o, rule, th))
            best = max(choice, key=sc)
            if mode == "mono" and sc(best) < 50 and rerolls > 0:
                rerolls -= 1
                best = max(draw(opts, k, rng), key=sc)
            apply(s, best)
        else:
            r = rng.random()
            for _ in range(max(n, 5 if r > 0.93 else 3 if r > 0.68 else 1)):
                ups = [o for o in options(c, s, t, rule, th) if o[0] in ("evo", "wup", "pup")]
                if not ups:
                    break
                apply(s, draw(ups, 1, rng)[0])
        pts = points(c, s, rule)
        if mode == "mono":
            for k, thr in enumerate(th):
                if pts[home] >= thr and k not in reach:
                    reach[k] = t
        else:
            if all(p >= th[0] for p in pts) and "taiji" not in reach:
                reach["taiji"] = t
            if all(p >= th[1] for p in pts) and "hunyuan" not in reach:
                reach["hunyuan"] = t
    return reach


def fmt(times, n):
    if not times:
        return "达不到"
    times = sorted(times)
    mmss = lambda x: f"{int(x // 60)}:{int(x % 60):02d}"
    q1, q3 = times[len(times) // 4], times[3 * len(times) // 4]
    return f"中位 {mmss(st.median(times))}（四分位 {mmss(q1)}–{mmss(q3)}），9:30 前达成 {100 * len(times) / n:.0f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", choices=["full", "p0"], default="full")
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    c = Content(3, 4) if a.content == "full" else Content(1, 3)
    lt = level_times()
    print(f"等级：3 分 Lv{1 + sum(t <= 180 for t in lt)}，6 分 Lv{1 + sum(t <= 360 for t in lt)}，9 分 Lv{1 + sum(t <= 540 for t in lt)}")
    for rule in (["old", "new"] if a.content == "full" else ["new"]):
        label, th = RULES[rule]
        rng = random.Random(a.seed)
        print(f"\n== {label}，阈值 {th}")
        res = [simulate(c, rule, th, "mono", rng, lt) for _ in range(a.runs)]
        for k, name in enumerate(["一阶", "二阶", "三阶", "极境"]):
            print(f"专精 {name}：", fmt([r[k] for r in res if k in r], a.runs))
        res = [simulate(c, rule, th, "balanced", rng, lt) for _ in range(a.runs)]
        print("兼修 太极：", fmt([r["taiji"] for r in res if "taiji" in r], a.runs))
        print("兼修 混元：", fmt([r["hunyuan"] for r in res if "hunyuan" in r], a.runs))


if __name__ == "__main__":
    main()
