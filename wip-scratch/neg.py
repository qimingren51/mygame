import sys, shutil, traceback
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, 'art/post')
import test_ui_skin as T
src = T.SKIN
tmp = Path('/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/skin_neg')

def fresh():
    if tmp.exists(): shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    T.SKIN = tmp

def run(label, fn, test):
    fresh(); fn()
    try:
        test(); print(f'NOT CAUGHT  {label}')
    except AssertionError as e:
        print(f'caught      {label}: {str(e)[:110]}')

def edit(name, f):
    im = np.asarray(Image.open(tmp/f'{name}.png').convert('RGBA')).copy()
    f(im); Image.fromarray(im, 'RGBA').save(tmp/f'{name}.png')

# 1 seam: roll the panel's centre region by 37 px (breaks periodicity)
def seam(im):
    c = im[176:432, 176:432].copy(); im[176:432, 176:432] = np.roll(c, 37, axis=1)
run('tile seam (panel centre rolled)', lambda: edit('panel', seam), T.test_tile_seams)
# 1b subtle: brightness ramp across card centre
def ramp(im):
    r = np.linspace(0, 10, 192)[None, :, None]; im[64:336, 64:256, :3] = np.clip(im[64:336, 64:256, :3] - r, 0, 255)
run('tile seam (card brightness ramp 10)', lambda: edit('card_ling', ramp), T.test_tile_seams)
# 2 stretch gradient in fill band
def grad(im):
    im[:, 20:76, :3] = np.clip(im[:, 20:76, :3].astype(int) + np.arange(56)[None, :, None] // 8, 0, 255)
run('stretch band gradient (hp fill)', lambda: edit('bar_fill_hp', grad), T.test_stretch_bands_uniform)
# 3 corner flourish crossing slice line of a stretch item (then band re-uniformed so only continuity can catch)
def spill(im):
    pil = Image.fromarray(im); d = ImageDraw.Draw(pil); d.ellipse((50, 20, 90, 60), fill=(242, 181, 68, 255)); a = np.asarray(pil).copy()
    a[:, 72:120] = a[:, 72:73]; im[:] = a
run('corner blob crossing slice (btn)', lambda: edit('btn', spill), T.test_slice_lines_continuous)
# 4 corner detail leaking into tiled side strip of a card
def leak(im):
    pil = Image.fromarray(im); d = ImageDraw.Draw(pil); d.ellipse((40, 22, 82, 44), fill=(194, 58, 43, 255)); im[:] = np.asarray(pil)
run('corner detail leaking into tile strip (card)', lambda: edit('card_fan', leak), T.test_no_corner_spill_into_tiles)
run("corner detail leaking (seam test)", lambda: edit("card_fan", leak), T.test_tile_seams)
# 5 premultiplied alpha
def pm(im):
    a = im[..., 3:4].astype(float) / 255; im[..., :3] = np.round(im[..., :3] * a).astype(np.uint8)
run('premultiplied (card_focus)', lambda: edit('card_focus', pm), T.test_straight_alpha_and_bleed)
run('premultiplied (btn_primary)', lambda: edit('btn_primary', pm), T.test_straight_alpha_and_bleed)
run("premultiplied card_focus (glow check)", lambda: edit("card_focus", pm), T.test_straight_alpha_and_bleed)
# 6 no bleed (black in transparent)
def nobleed(im):
    im[im[..., 3] == 0, :3] = 0
run('no colour bleed (chip)', lambda: edit('chip', nobleed), T.test_straight_alpha_and_bleed)
# 7 size mismatch
def crop(): Image.open(tmp/'pip.png').crop((0,0,38,40)).save(tmp/'pip.png')
run('size mismatch (pip)', crop, T.test_manifest)
T.SKIN = src
