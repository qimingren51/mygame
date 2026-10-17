def ingame_mock(items, path: Path) -> None:
    """游戏比例的模拟场景：1 贴图像素 = 1 画面像素 = 0.5 世界单位，主角用真实素材（160 像素帧）做比例参考。
    上左：夜里灯照下的宣纸（世界层 × 光照图，发光物最后叠加，与游戏同法）；
    上右：同一场景不打光，发光物改成染色后正常叠放，只为看清形状；
    下：涟漪环染冰蓝后按 30/60/120/240/480 像素直径缩放（双线性），以及 800 像素时的局部。"""
    Wm, Hm = 900, 600
    paper_img = load_optional(V.GROUND_DIR / "paper.png")
    if paper_img is not None:
        pt = np.asarray(paper_img.convert("RGB"), dtype=np.float64) / 255.0
        base = np.tile(pt, (2, 2, 1))[:Hm, :Wm].copy()
    else:
        base = np.broadcast_to(PAPER, (Hm, Wm, 3)).copy()
    hero = load_optional(V.OUT / "assets" / "hero" / "idle_SE_00.png")
    if hero is None:
        hero = hero_stand_in()
    hero_emit = load_optional(V.OUT / "assets" / "hero" / "idle_SE_00_emit.png")
    shadow = load_optional(V.VFX_DIR / "shadow.png")
    light = load_optional(V.VFX_DIR / "light.png")
    wash = load_optional(V.GROUND_DIR / "wash_0.png")
    T = {k: v[0] for k, v in items.items()}
    A = {k: v[1] for k, v in items.items()}
    hx, hy = 450.0, 330.0
    wx, wy = 640.0, 420.0  # 落印点
    ring_r = items["ring"][2]["radius_px"]
    swords = [(hx + 95, hy - 135, -0.55, "sword"), (hx + 175, hy - 70, -0.2, "sword"), (hx - 150, hy - 110, math.pi + 0.35, "sword"),
              (hx + 70, hy + 60, 0.5, "sword_evo"), (hx - 70, hy - 190, -2.1, "sword"), (hx - 120, hy + 40, math.pi - 0.3, "sword_evo")]

    def draw_world(world):
        if wash is not None:
            place(world, wash, 600, 480, scale=1.4, anchor=(0.5, 0.5))
        # 地面：镇岳留下的地裂和印迹、一个圆相墨痕
        place(world, T["crack"], 250, 450, scale=1.2, anchor=A["crack"], alpha=0.9)
        place(world, T["seal_mark"], 250, 450, angle=math.radians(8), scale=(0.9, 0.9 * 0.7), anchor=A["seal_mark"], alpha=0.85)
        place(world, T["ring_ink"], 360, 530, scale=(0.75, 0.75 * 0.6), anchor=A["ring_ink"], alpha=0.75)
        # 拾取物
        for name, px, py in (("chest", 560, 525), ("soulbell", 615, 545), ("lotus", 505, 550)):
            if shadow is not None:
                place(world, shadow, px, py, scale=(T[name].width / 64 * 0.95, 0.5), anchor=(0.5, 0.5), alpha=0.8)
            place(world, T[name], px, py, anchor=A[name])
        # 已经落地的镇岳
        if shadow is not None:
            place(world, shadow, 215, 300, scale=(0.75, 0.9), anchor=(0.5, 0.5))
        place(world, T["seal_evo"], 215, 300, anchor=A["seal_evo"])
        # 主角
        if shadow is not None:
            place(world, shadow, hx, hy, scale=1.0, anchor=(0.5, 0.5))
        place(world, hero, hx, hy, anchor=(0.5, 0.875))
        # 正在落下的山印：地上的影子，石印还在半空
        if shadow is not None:
            place(world, shadow, wx, wy, scale=(0.7, 0.85), anchor=(0.5, 0.5), alpha=0.6)
        place(world, T["seal"], wx, wy - 60, anchor=A["seal"])
        # 纸鹤三只
        for name, px, py, ang in (("crane_0", 300, 180, -0.15), ("crane_2", 640, 160, 0.1), ("crane_evo_1", 720, 270, 0.35)):
            place(world, T[name], px, py, angle=ang, anchor=A[name])
        for sx_, sy_, ang, name in swords:
            place(world, T[name], sx_, sy_, angle=ang, anchor=A[name])

    def draw_fx(canvas, mode, k_alpha=1.0):
        def fx(name, x, y, alpha=1.0, **kw):
            place(canvas, T[name], x, y, anchor=A[name], mode=mode, tint=col(TINTS[name]), alpha=alpha * k_alpha, **kw)

        fx("warn", wx, wy, 0.95, scale=(1.4, 1.4 * 0.62))
        fx("ring", hx, hy - 30, 0.6, scale=(140 / ring_r, 140 / ring_r * 0.62))
        fx("blast", 780, 500, 1.0, scale=1.3)
        for sx_, sy_, ang, _ in swords:
            fx("sword_trail", sx_, sy_, 0.8, angle=ang, scale=(1.6, 1.0))

    # 夜：世界层 × 光照图 + 发光物
    world = base.copy()
    draw_world(world)
    lm = np.broadcast_to(col(S.NIGHT_AMBIENT), world.shape).copy()
    if light is not None:
        place(lm, light, hx - 10, hy - 60, scale=900 / 128, anchor=(0.5, 0.5), mode="add", tint=col(S.LANTERN_LIGHT))
    else:
        lm[:] = 1.0
    lit = world * np.clip(lm, 0, 1)
    draw_fx(lit, "add")
    if hero_emit is not None:
        place(lit, hero_emit, hx, hy, anchor=(0.5, 0.875), mode="add")
    lit = np.clip(lit, 0, 1)
    # 白天：不打光，发光物染色后正常叠放
    day = base.copy()
    draw_world(day)
    draw_fx(day, "over", 0.85)
    day = np.clip(day, 0, 1)

    # 涟漪环缩放条
    strip_h = 520
    strip = np.broadcast_to(col(S.NIGHT_AMBIENT), (strip_h, Wm * 2 + 12, 3)).copy()
    x = 20
    for dia in (30, 60, 120, 240, 480):
        s = dia / (2 * ring_r)
        place(strip, T["ring"], x + dia / 2, 30 + 240, scale=s, anchor=(0.5, 0.5), mode="add", tint=col(TINTS["ring"]))
        x += dia + 30
    big = np.broadcast_to(col(S.NIGHT_AMBIENT), (900, 900, 3)).copy()
    place(big, T["ring"], 450, 450, scale=800 / (2 * ring_r), anchor=(0.5, 0.5), mode="add", tint=col(TINTS["ring"]))
    crop = big[50:500, 50:500]
    strip[40:40 + 450, x + 10:x + 10 + 450] = crop
    gap = 12
    out = np.ones((Hm + 34 + strip_h + 30, Wm * 2 + gap, 3)) * 0.1
    out[34:34 + Hm, :Wm] = lit
    out[34:34 + Hm, Wm + gap:] = day
    out[34 + Hm + 30:, :] = np.clip(strip, 0, 1)
    im = Image.fromarray(np.round(out * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    f = V.font(15)
    dr.text((8, 9), "night: world x lightmap + additive FX (1 texel = 1 px = 0.5 world unit; hero frame 160 px)", fill="#DDDDDD", font=f)
    dr.text((Wm + gap + 8, 9), "same scene unlit; FX drawn tinted with normal blend (shape check only)", fill="#DDDDDD", font=f)
    dr.text((8, 34 + Hm + 8), "ring.png tinted #6FB8FF, additive, bilinear: diameter 30 / 60 / 120 / 240 / 480 px, and a 450 px crop of the 800 px ring", fill="#DDDDDD", font=f)
    V.save_png(im, path)
