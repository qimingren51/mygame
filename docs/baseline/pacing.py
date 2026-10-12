"""单局节奏模型（BALANCE.md 第 4.2、4.3 节）。

假设玩家跟得上刷怪：击杀速率等于刷怪速率，晚 8 秒；魂火价值固定为 1，石妖 3 点。
输出每分钟的等级、累计击杀，以及场上妖物数量的估计。

用法：python3 pacing.py
"""

XP_NEED = lambda n: 4 + 5 * n + 0.6 * n * n
SPAWN = lambda m: 2 + 1.6 * m + 0.45 * m * m      # 常规刷怪，每秒
PACKS = lambda m: (8 + 5 * m) / 25 if m >= 40 / 60 else 0  # 妖群折算到每秒
GOLEM_SHARE = lambda m: 0 if m < 2.5 else 0.125 * (1.6 if m >= 5 else 1)


def run(lag=8.0):
    dt = 1 / 60
    t, xp, lv, kills, queue, out = 0.0, 0.0, 1, 0.0, [], {}
    while t <= 600:
        m = t / 60
        rate = SPAWN(m) + PACKS(m)
        if 480 <= t < 510:  # 妖潮：刷怪 × 3
            rate += 2 * SPAWN(m)
        n = rate * dt
        if abs(t - 240) < dt / 2:  # 合围
            n += 40 + 10 * 4
        if abs(t - 420) < dt / 2:
            n += 40 + 10 * 7
        queue.append((t + lag, n, m))
        while queue and queue[0][0] <= t:
            _, c, ms = queue.pop(0)
            kills += c
            xp += c * (1 + 2 * GOLEM_SHARE(ms))
        for te, v in ((170, 20), (300, 40), (400, 30), (480, 30)):  # 精英、小头目的魂火
            if abs(t - te) < dt / 2:
                xp += v
        while xp >= XP_NEED(lv):
            xp -= XP_NEED(lv)
            lv += 1
        if abs(t - round(t)) < dt / 2 and round(t) % 60 == 0:
            out[round(t) // 60] = (lv, round(kills))
        t += dt
    return out


def main():
    print("分钟  等级  累计击杀")
    for m, (lv, k) in sorted(run().items()):
        print(f"{m:4d} {lv:5d} {k:9d}")
    print("\n场上妖物 ≈（刷怪 + 妖群）× 存活时间 8–12 秒")
    for m in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        r = SPAWN(m) + PACKS(m)
        print(f"{m:2d} 分：{r:5.1f}/秒，场上约 {r * 8:4.0f}–{r * 12:4.0f} 只")
    r = 3 * SPAWN(8.25) + PACKS(8.25)
    print(f"妖潮（8:15）：{r:5.1f}/秒，场上约 {r * 8:4.0f}–{r * 12:4.0f} 只")


if __name__ == "__main__":
    main()
