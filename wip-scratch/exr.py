import struct, numpy as np, sys

def read_exr_uncompressed(path):
    """极简 EXR 读取：只支持无压缩(NONE)扫描线，单/多 part。返回 {通道名: float32 HxW}"""
    b = open(path, 'rb').read()
    magic, ver = struct.unpack_from('<II', b, 0)
    assert magic == 20000630, 'not exr'
    multipart = bool(ver & 0x1000)
    assert not (ver & 0x200), 'tiled not supported'
    pos = 8
    headers = []
    while True:
        h = {}
        while b[pos] != 0:
            e = b.index(b'\0', pos); name = b[pos:e].decode(); pos = e + 1
            e = b.index(b'\0', pos); typ = b[pos:e].decode(); pos = e + 1
            size, = struct.unpack_from('<i', b, pos); pos += 4
            h[name] = (typ, b[pos:pos + size]); pos += size
        pos += 1
        headers.append(h)
        if not multipart or b[pos] == 0:
            if multipart: pos += 1
            break
    return headers, pos, multipart

h, pos, mp = read_exr_uncompressed(sys.argv[1])
print('multipart', mp, 'nparts', len(h))
for hh in h:
    print({k: (v[0], v[1][:60] if v[0] != 'chlist' else None) for k, v in hh.items() if k in ('compression','dataWindow','name','type','chunkCount')})
    cl = hh['channels'][1]; p=0; names=[]
    while cl[p] != 0:
        e = cl.index(b'\0', p); names.append((cl[p:e].decode(), struct.unpack_from('<i', cl, e+1)[0])); p = e + 1 + 16
    print(names)

def read_all(path):
    b = open(path, 'rb').read()
    headers, pos, mp = read_exr_uncompressed(path)
    out = {}
    parts = []
    for hh in headers:
        cl = hh['channels'][1]; p = 0; chans = []
        while cl[p] != 0:
            e = cl.index(b'\0', p); chans.append((cl[p:e].decode(), struct.unpack_from('<i', cl, e + 1)[0])); p = e + 17
        x0, y0, x1, y1 = struct.unpack('<4i', hh['dataWindow'][1])
        assert hh['compression'][1] == b'\0'
        W, H = x1 - x0 + 1, y1 - y0 + 1
        parts.append((chans, W, H, y0))
        for c, _ in chans: out[c] = np.zeros((H, W), np.float32)
    nchunks = [struct.unpack('<i', hh['chunkCount'][1])[0] if 'chunkCount' in hh else parts[i][2] for i, hh in enumerate(headers)]
    offs = []
    for n in nchunks:
        offs.append(np.frombuffer(b, '<u8', n, pos)); pos += 8 * n
    for pi, (chans, W, H, y0) in enumerate(parts):
        for o in offs[pi]:
            o = int(o)
            if mp:
                part, = struct.unpack_from('<i', b, o); o += 4; assert part == pi
            y, size = struct.unpack_from('<ii', b, o); o += 8
            for c, t in chans:
                dt = {1: '<f2', 2: '<f4', 0: '<u4'}[t]
                n = W
                out[c][y - y0] = np.frombuffer(b, dt, n, o).astype(np.float32); o += n * np.dtype(dt).itemsize
    return out

if __name__ == '__main__':
    d = read_all(sys.argv[1])
    for k, v in d.items(): print(k, v.shape, float(v.min()), float(v.max()), int((v > 0.5).sum()))
