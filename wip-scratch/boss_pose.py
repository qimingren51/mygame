def pose_boss(parts, anim, frame, n):
    """move：潜行——头前伸、略低于肩线；对角两腿同步交替（肩/髋绕横轴摆，向前摆的那条抬爪），
    身体微起伏，九尾依次波动。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["body"].location.z = 0.015 * math.cos(2 * ph)
    parts["head"].rotation_euler = (math.radians(6 + 2.0 * math.sin(2 * ph + 0.6)), 0, math.radians(-8))
    for nm, off in (("FL", 0.0), ("HR", 0.0), ("FR", math.pi), ("HL", math.pi)):
        leg = parts["legs"][nm]
        leg.rotation_euler.x = math.radians(-10 * math.sin(ph + off))  # 负角 = 爪向前
        rest_z = (FRONT_HIP if nm[0] == "F" else HIND_HIP)[2]
        leg.location.z = rest_z + 0.05 * max(0.0, math.cos(ph + off))  # 向前摆（腾空）时抬爪
    for ob, troot, i in parts["tails"]:
        fades: list = []
        build = K.tube_build(_boss_tail(troot, i, ph), _brush, 12, flat=0.62, fades=fades)
        K.replace_mesh(ob, build)
        B.set_point_attr(ob, "fade", fades)
    bpy.context.view_layer.update()
