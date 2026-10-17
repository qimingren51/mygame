import sys, time
sys.path.insert(0, "/home/user/mygame/art/post")
import enemy_2d as E
t=time.time()
E.preview(sys.argv[1], sys.argv[2])
print("ok", time.time()-t)
