"""手的试渲：几个姿势并排，看形状（不进仓库）。"""
import math, sys
sys.path.insert(0, "art/render")
import card_art as K
K.load_scenes()
import card_props as P
from card_art import scene, lin

POSES = {"open": P.HAND_OPEN, "fist": P.HAND_FIST}

@scene("zz_hand", name="手", samples=32)
def build(draft):
    import card_weapons as CW
    CW.sky_gradient(lin("#05080F"), lin("#33496C"), 0.9)
    skin = P.mat_skin("Skin")
    P.hand("HandA", skin, P.HAND_OPEN, loc=(-0.13, 0, 0), rot=(0, 0, 0))
    P.hand("HandB", skin, P.HAND_OPEN, loc=(0.0, 0, 0), rot=(0, 0, math.radians(90)))
    P.hand("HandC", skin, P.HAND_FIST, loc=(0.13, 0, 0), rot=(0, 0, 0))
    K.area_light("Key", (-0.6, -0.8, 0.8), (0, 0, 0.08), 30.0, 0.6, color=(1.0, 0.95, 0.9))
    K.area_light("Rim", (0.6, 0.8, 0.5), (0, 0, 0.08), 20.0, 0.6, color=(0.7, 0.8, 1.0))
    K.camera((0.0, -0.75, 0.10), (0.0, 0.0, 0.08), lens=50.0)

if __name__ == "__main__":
    K.render_one("zz_hand", True, 32)
    K.finish("zz_hand", draft=True)
