import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad")
import numpy as np
from PIL import Image
import proto_hero as PH
T = PH.T
rng = np.random.default_rng(1)
P = T.Painting(rng)
P.paper0 = P.rgb.copy()
P.glaze(np.ones((T.H, T.W)) * 0.5, T.DAN)  # 中灰底，看留白
stages = []
orig_stroke = P.stroke
PH.paint_hero_ink(P, np.random.default_rng(77), [])
img = Image.fromarray((np.clip(P.rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
img.crop((1180, 640, 1260, 880)).resize((320, 960), Image.NEAREST).save(sys.argv[1])
