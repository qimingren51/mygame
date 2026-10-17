p='/home/user/mygame/lantern-next/art/render/smoke_test.py'; s=open(p).read()
start = s.index('    # b. Workbench / EEVEE（子进程）')
end = s.index('    # e. OIDN\n    with Timer("oidn_check")')
new = '''    # b. Workbench / EEVEE / 合成器+Freestyle（子进程，失败也不影响主流程）
    report["probes"] = {}
    for kind in ("BLENDER_WORKBENCH", "BLENDER_EEVEE", "COMP_FREESTYLE"):
        with Timer(f"probe_{kind.lower()}"):
            res = run_probe(kind)
        report["probes"][kind] = res
        print(f"probe {kind}: ok={res['ok']} rc={res['returncode']}")
        if res["error"]:
            print("   ", res["error"].replace("\\n", "\\n    "))

    # c. 场景搭建
    with Timer("scene_build"):
        sc = reset_scene()
        root, lantern = build_figure(sc)
        cam = setup_camera(sc)
    from bpy_extras.object_utils import world_to_camera_view
    lp = world_to_camera_view(sc, cam, lantern.matrix_world.translation)
    report["lantern_screen_uv"] = [round(lp.x, 4), round(lp.y, 4)]

    # c. 仅填色 512（先渲一张 64px 预热，排除首次加载内核/建 BVH 的时间）
    try:
        sc.render.use_freestyle = False
        sc.render.resolution_x = sc.render.resolution_y = 64
        with Timer("cycles_warmup_64"):
            render_to(sc, OUT / "_warmup.png")
        (OUT / "_warmup.png").unlink()
        sc.render.resolution_x = sc.render.resolution_y = RES
        with Timer("fill_512"):
            render_to(sc, OUT / "fill.png")
        report["cycles_ok"] = True
    except Exception as e:
        report["cycles_ok"] = False
        warn("Cycles 渲染失败: " + repr(e))
        raise

    # d. Freestyle：填色+线条合成
    vl = setup_freestyle(sc)
    report["freestyle"] = {}
    try:
        with Timer("freestyle_combined_512"):
            render_to(sc, OUT / "combined.png")
        report["freestyle"]["combined_ok"] = True
        report["timings_s"]["freestyle_overhead_512"] = round(
            report["timings_s"]["freestyle_combined_512"] - report["timings_s"]["fill_512"], 3)
    except Exception as e:
        report["freestyle"]["combined_ok"] = False
        warn("Freestyle 合成渲染失败: " + repr(e))

    # d(b). 仅线条，三种方法：
    #   1a 合成器取 Freestyle 通道 → 已在子进程 COMP_FREESTYLE 里测（无 GPU 时 abort）
    #   1b as_render_pass + 无压缩多层 EXR → numpy 解出 Freestyle 通道（一次渲染同时得到填色和线条）
    #   2  material_override=Holdout → 只剩线条
    comp = report["probes"]["COMP_FREESTYLE"]
    report["freestyle"]["pass_via_compositor_ok"] = comp["ok"]
    method = "freestyle_render_pass+compositor" if comp["ok"] else None
    if comp["ok"]:
        os.replace(OUT / "probe_comp_freestyle.png", OUT / "lines.png")
    try:
        vl.freestyle_settings.as_render_pass = True
        im = sc.render.image_settings
        im.media_type, im.exr_codec, im.color_depth = "MULTI_LAYER_IMAGE", "NONE", "16"
        exr = OUT / "passes.exr"
        with Timer("fill_plus_lines_pass_exr_512"):
            render_to(sc, exr)
        with Timer("exr_decode"):
            ch = read_exr_none(exr)
        report["freestyle"]["exr_channels"] = sorted(ch)
        if Image is not None and "ViewLayer.Freestyle.A" in ch:
            save_pass_png(ch, "ViewLayer.Freestyle", OUT / ("lines.png" if not method else "lines_exr.png"))
            save_pass_png(ch, "ViewLayer.Combined", OUT / "fill_from_exr.png")
            n = int((ch["ViewLayer.Freestyle.A"] > 0.5).sum())
            report["freestyle"]["exr_pass_line_pixels"] = n
            if n and not method:
                method = "freestyle_render_pass+multilayer_exr"
        exr.unlink()
    except Exception:
        warn("as_render_pass + EXR 失败: " + traceback.format_exc(limit=2))
    finally:
        vl.freestyle_settings.as_render_pass = False
        im = sc.render.image_settings
        im.media_type, im.color_depth = "IMAGE", "8"
        im.file_format, im.color_mode = "PNG", "RGBA"
    try:
        vl.material_override = holdout_material()
        target = OUT / ("lines_holdout.png" if method else "lines.png")
        with Timer("lines_holdout_512"):
            render_to(sc, target)
        n = alpha_count(target)
        report["freestyle"]["holdout_line_pixels"] = n
        if n and not method:
            method = "material_override_holdout"
    except Exception as e:
        warn("Holdout 覆盖渲染失败: " + repr(e))
    finally:
        vl.material_override = None
    report["freestyle"]["lines_method"] = method
    freestyle_ok = bool(method) and report["freestyle"].get("combined_ok")

'''
s = s[:start] + new + s[end:]
open(p,'w').write(s)
