"""第一轮审图后：只重渲 walk S、dash S（+ walk SE/SW 第 2 帧），并进 kfix_sample@2x，出 kfix_sample_r2.png 和 S 向动图。"""
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad")
import kfix as KF  # noqa: E402
from PIL import Image  # noqa: E402
import contact_sheet as CS  # noqa: E402
import lantern_review as LR  # noqa: E402
from style import style as S  # noqa: E402

R2 = KF.OUT / "kfix_sample_r2@2x"
JOBS = [("walk", "S", i, 8) for i in range(8)] + [("dash", "S", i, 4) for i in range(4)] + \
       [("walk", "SE", 2, 8), ("walk", "SW", 2, 8)]
FOLDERS = ["hero"] + [f"lantern_{l}" for l in KF.LAMPS]


def render():
    import produce as PR
    PR.render_hero(JOBS, R2, timings={}, lamps=KF.LAMPS)


def merge():
    """walk S、dash S 的新帧（含 _emit）拷进 kfix_sample@2x，主角 meta 里这两组的 lantern 挂点一并换掉。"""
    for f in FOLDERS:
        for p in (R2 / f).glob("*.png"):
            if p.name.startswith(("walk_S_", "dash_S_")):
                shutil.copy2(p, KF.SAMPLE / f / p.name)
    m2 = json.loads((R2 / "hero" / "meta.json").read_text(encoding="utf-8"))
    mp = KF.SAMPLE / "hero" / "meta.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    for an in ("walk", "dash"):
        m["sockets"]["lantern"][an]["S"] = m2["sockets"]["lantern"][an]["S"]
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")


def sheet():
    blocks = [("第二轮：walk S、dash S（新 = kfix_sample_r2@2x），walk SE / SW 第 2 帧", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))]
    blocks += KF.hero_block("主角 walk S（8 帧，红纸灯）", [f"walk_S_{i:02d}" for i in range(8)], [0, 1, 2, 3])
    blocks += KF.hero_block("主角 dash S（4 帧）", [f"dash_S_{i:02d}" for i in range(4)], [0, 1, 2, 3])
    olds = [KF.hero_frame(KF.OLD, f"walk_{d}_02")[0] for d in ("SE", "SW")]
    news = [KF.hero_frame(R2, f"walk_{d}_00")[0] for d in ("SE", "SW")]
    box = KF.union_box(olds + news)
    blocks += [("■ walk SE、SW 第 2 帧（斜向按约 0.6 的量）", Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))]
    blocks += KF.pair_rows(olds, news, box, [0, 1])
    im = LR.stack(blocks)
    im.save(KF.REVIEW / "kfix_sample_r2.png")
    print("写出", KF.REVIEW / "kfix_sample_r2.png", im.size)


if __name__ == "__main__":
    if "render" in sys.argv:
        render()
    merge()
    sheet()
    KF.review()  # 重出 kfix_sample.png 和 8 张动图（S 向的是新帧）
