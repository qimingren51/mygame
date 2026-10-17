p='/home/user/mygame/lantern-next/art/render/smoke_test.py'; s=open(p).read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
rep('''    src = Image.open(OUT / "combined.png").convert("RGBA")
    paper = Image.new("RGBA", src.size, hex_rgb_255(PAPER_BG))
    # 4x''', '''    src = Image.open(OUT / "combined.png").convert("RGBA")
    # 4x''')
rep('''    prev.resize((small.width * 3, small.height * 3), Image.NEAREST).save(OUT / "preview_zoom.png")
    del paper
''', '''    prev.resize((small.width * 3, small.height * 3), Image.NEAREST).save(OUT / "preview_zoom.png")
''')
rep('''

def hex_rgb_255(h, a=255):
    return tuple(int(c * 255 + 0.5) for c in hex_rgb(h)) + (a,)
''', '')
rep('''def srgb_to_linear(c):''', '''def hex_rgb_255(h, a=255):
    return tuple(int(c * 255 + 0.5) for c in hex_rgb(h)) + (a,)


def srgb_to_linear(c):''')
open(p,'w').write(s)
