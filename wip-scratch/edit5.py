p='/home/user/mygame/lantern-next/art/render/smoke_test.py'; s=open(p).read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
rep('''report = {"warnings": [], "timings_s": {}}''', '''report = {"warnings": [], "timings_s": {}, "cpu_cores_used": {}}''')
rep('''class Timer:
    """with Timer("名字"): ...  把耗时写进 report["timings_s"]"""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.dt = time.perf_counter() - self.t0
        report["timings_s"][self.key] = round(self.dt, 3)
        print(f"[TIME] {self.key}: {self.dt:.2f}s")
        return False''', '''def _cpu():
    t = os.times()
    return t.user + t.system


class Timer:
    """with Timer("名字"): ...  墙钟耗时写进 report["timings_s"]，
    进程 CPU 时间 / 墙钟 写进 report["cpu_cores_used"]（≈1 说明单线程，≈4 说明吃满 4 核）。"""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        self.t0, self.c0 = time.perf_counter(), _cpu()
        return self

    def __exit__(self, *exc):
        self.dt = time.perf_counter() - self.t0
        report["timings_s"][self.key] = round(self.dt, 3)
        report["cpu_cores_used"][self.key] = round((_cpu() - self.c0) / max(self.dt, 1e-6), 2)
        print(f"[TIME] {self.key}: {self.dt:.2f}s")
        return False''')
rep('''    except Exception as e:
        report["fallback"]["inverted_hull_ok"] = False''', '''    except Exception:
        report["fallback"]["inverted_hull_ok"] = False''')
rep('''    # h. 8 方向 256px，开 Freestyle
    sc.render.resolution_x = sc.render.resolution_y = DIR_RES
    sc.cycles.samples = DIR_SAMPLES
    if freestyle_ok:
        setup_freestyle(sc, line_scale=DIR_RES / RES)
''', '''    # h. 8 方向 256px，开 Freestyle（Freestyle 不可用时退回反向外壳描边）
    sc.render.resolution_x = sc.render.resolution_y = DIR_RES
    sc.cycles.samples = DIR_SAMPLES
    if freestyle_ok:
        setup_freestyle(sc, line_scale=DIR_RES / RES)
        report["dir8_line_method"] = "freestyle"
    else:
        sc.render.use_freestyle = False
        add_inverted_hulls(root, thickness=0.02)
        report["dir8_line_method"] = "inverted_hull_fallback"
''')
rep('''    report["dir8_freestyle"] = freestyle_ok
''', '')
open(p,'w').write(s)
