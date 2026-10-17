import sys
sys.argv=[sys.argv[0]]
sys.path.insert(0,'/home/user/mygame/art/post')
import title_screen as T
from PIL import Image
title=Image.open('/home/user/mygame/art/out/screens/title.png').convert('RGBA')
variants=[(26.0,0.42,1.8,0.40),(34.0,0.50,1.4,0.30),(22.0,0.32,2.2,0.55),(40.0,0.58,0.0001,0.0)]
tiles=[]
for v in variants:
    T.HALO=v
    lg,_=T.make_logo()
    lg=lg.resize((round(lg.width*0.8),round(lg.height*0.8)),Image.LANCZOS)
    t=title.crop((0,0,960,380)).copy(); t.alpha_composite(lg,(24,18)); tiles.append(t)
    p=Image.new('RGBA',(960,380),(237,228,207,255)); p.alpha_composite(lg,(24,18)); tiles.append(p)
out=Image.new('RGB',(1920,380*len(variants)))
for i,t in enumerate(tiles): out.paste(t.convert('RGB'),((i%2)*960,(i//2)*380))
out.save(sys.argv[0].replace('halo_exp.py','halo_cmp.png'))
