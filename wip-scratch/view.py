import sys
from PIL import Image
raw = '/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/raw'
out = sys.argv[1]; names = sys.argv[2:]
scale = 1
if names and names[0].startswith('x'):
    scale = int(names[0][1:]); names = names[1:]
ims = [Image.open(f'{raw}/{n}.png') for n in names]
ims = [im.resize((im.width*scale, im.height*scale), Image.NEAREST) for im in ims]
pad = 12
W = sum(im.width for im in ims) + pad*(len(ims)+1)
H = max(im.height for im in ims) + 2*pad
sheet = Image.new('RGBA', (W, H*2))
for row, bg in enumerate(('#161B2C', '#EDE4CF')):
    sheet.paste(Image.new('RGBA', (W, H), bg), (0, row*H))
    x = pad
    for im in ims:
        sheet.alpha_composite(im, (x, row*H+pad)); x += im.width + pad
sheet.convert('RGB').save(out)
