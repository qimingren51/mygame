def make_wash(seed: int, lobes, base_alpha: float, *, tilt=(0.0, 0.0), sweep: float | None = None) -> Image.Image:
    """水墨晕染：淡墨大块。边缘有的地方墨干后积成一道深痕、带毛茸茸的洇边（硬边），
    有的地方是湿接湿的柔边；内部一侧浓一侧淡，带淡淡的水渍纹。sweep 给出时，沿该方向的尾端做干笔飞白。"""
    ss, w, h = 2, 240, 160
    rng = np.random.default_rng(seed)
    X, Y = grid(h, w, ss)
    sh = X.shape
    nx, ny = (X - w / 2) / (w / 2), (Y - h / 2) / (h / 2)
    wx = nx + 0.08 * noise(rng, sh, 30 * ss) + 0.05 * noise(rng, sh, 12 * ss) + 0.02 * noise(rng, sh, 5 * ss)
    wy = ny + 0.08 * noise(rng, sh, 30 * ss) + 0.05 * noise(rng, sh, 12 * ss) + 0.02 * noise(rng, sh, 5 * ss)
    F = np.zeros(sh)
    for cx, cy, rx, ry, wt in lobes:
        F += wt * np.exp(-(((wx - cx) / rx) ** 2 + ((wy - cy) / ry) ** 2))
    # 边缘的分形起伏：大弯里套小弯，纸纤维让边线再碎一点
    F += 0.06 * noise(rng, sh, 9 * ss) + 0.035 * noise(rng, sh, 3 * ss) + 0.012 * noise(rng, sh, 1.2 * ss)
    # 细噪声会在边上掐出几个像素的小洞，看着像瑕疵：取 max(F, 模糊F-余量)，相当于软的闭运算，
    # 只填窄缝和小洞，凸出去的毛边不受影响
    F = np.maximum(F, fft_blur(F, 2.0 * ss) - 0.02)
    gy, gx = np.gradient(F, 1.0 / ss)
    # 近似的到边缘距离（最终像素），内正外负。梯度模先平滑再设下限，避免鞍点处距离发散出小洞
    gm = np.maximum(fft_blur(np.hypot(gx, gy), 2.0 * ss), 0.006)
    sd = np.clip((F - 0.5) / gm, -40, 40)
    # 软硬边：soft=1 是湿接湿的柔边，0 是干后积墨的硬边
    soft = smoothstep(-0.1, 0.9, noise(rng, sh, 20 * ss))
    wtr = 0.6 + 10.0 * soft
    inside = smoothstep(-0.5 * wtr, 0.5 * wtr, sd)
    # 内部：一侧浓一侧淡 + 湿画法的起伏 + 细颗粒
    interior = base_alpha * (1.0 + 0.35 * (tilt[0] * nx + tilt[1] * ny))
    interior = interior + 0.03 * noise(rng, sh, 10 * ss) + 0.012 * noise(rng, sh, 4 * ss) + 0.008 * noise(rng, sh, 0.5 * ss)
    interior -= 0.025 * smoothstep(12.0, 2.0, sd) * (1.0 - soft)  # 硬边内侧被带走的一条淡带
    # 墨聚的地方（叶瓣中心）再深一层，柔边过渡，出浓淡层次
    interior += 0.07 * smoothstep(0.62, 0.95, F + 0.08 * noise(rng, sh, 6 * ss))
    # 积墨的边：宽度和浓度沿边变化
    pool_w = 1.4 + 1.0 * smoothstep(-1, 1, noise(rng, sh, 10 * ss))
    pool_k = smoothstep(-1.0, 1.2, noise(rng, sh, 7 * ss))
    pool = 0.22 * pool_k * (1.0 - soft) ** 1.5 * np.exp(-np.maximum(sd, 0) / pool_w)
    # 水渍纹（backrun）：内部另一个场的等值线，很淡
    G = noise(rng, sh, 8.0 * ss) + 0.4 * noise(rng, sh, 2.5 * ss)
    tide = 0.025 * np.exp(-(((G - 0.7) / 0.12) ** 2)) * (G < 0.75) * smoothstep(4, 12, sd)
    # 洇边：顺着纸纤维往外渗，长短不一；只在硬边处明显
    fib = rank01(np.maximum.reduce([noise(rng, sh, (3.0 * ss, 0.35 * ss), angle=a) for a in (0.2, 1.25, 2.3)]))
    reach = 0.6 + 3.4 * fib**2
    bleed = 0.10 * (0.4 + 0.6 * pool_k) * (1.0 - 0.8 * soft) * np.exp(np.minimum(sd, 0) / reach) * smoothstep(0.15, 0.75, fib)
    a = inside * (interior + pool + tide) + (1.0 - inside) * bleed
    if sweep is not None:
        # 侧锋扫过去，尾端墨尽，留下顺笔方向的飞白
        along = ((X - w / 2) * math.cos(sweep) + (Y - h / 2) * math.sin(sweep)) / 80.0
        st = rank01(noise(rng, sh, (16 * ss, 0.7 * ss), angle=sweep))
        a *= 1.0 - 0.75 * smoothstep(0.15, 0.85, along) * smoothstep(0.3, 0.7, st)
    a *= smoothstep(1.0, 0.86, np.maximum(np.abs(nx), np.abs(ny)))  # 保证贴图四边为 0
    a = downsample(np.clip(a, 0, 0.35), ss)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    return to_rgba8(col(S.INK["zhong"]), a)
