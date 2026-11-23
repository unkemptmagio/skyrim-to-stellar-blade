# Minimal Havok 2010 packfile reader (Skyrim SE 64-bit and LE 32-bit): skeleton, binding, spline-compressed animation.
# ponytail: only the classes Skyrim anims/skeletons need; layouts hardcoded for hk_2010.2.0-r1.
import struct, math, sys

class Pack:
    def __init__(self, b):
        self.b = b
        self.ps = b[16]                      # pointer size 4 / 8
        nsec = struct.unpack_from("<i", b, 20)[0]
        self.secs = []
        o = 64
        for _ in range(nsec):
            tag = b[o:o + 19].split(b"\0")[0].decode()
            start, lf, gf, vf, ex, im, end = struct.unpack_from("<7i", b, o + 20)
            self.secs.append(dict(tag=tag, start=start, lf=lf, gf=gf, vf=vf, ex=ex, im=im, end=end))
            o += 48
        self.ptr = {}                         # absolute src -> absolute dst
        self.objs = []                        # (abs offset, class name)
        for i, s in enumerate(self.secs):
            st = s["start"]
            for p in range(st + s["lf"], min(st + s["gf"], len(b)) - 7, 8):
                src, dst = struct.unpack_from("<ii", b, p)
                if src != -1: self.ptr[st + src] = st + dst
            for p in range(st + s["gf"], min(st + s["vf"], len(b)) - 11, 12):
                src, sec, dst = struct.unpack_from("<iii", b, p)
                if src != -1: self.ptr[st + src] = self.secs[sec]["start"] + dst
            for p in range(st + s["vf"], min(st + s["ex"], len(b)) - 11, 12):   # tables are 0xFF-padded; the file may end mid-pad
                src, sec, dst = struct.unpack_from("<iii", b, p)
                if src == -1: continue
                cs = self.secs[sec]["start"] + dst
                name = b[cs:b.index(b"\0", cs)].decode()
                self.objs.append((st + src, name))

    def p(self, at): return self.ptr.get(at)
    def cstr(self, at):
        d = self.p(at)
        return None if d is None else self.b[d:self.b.index(b"\0", d)].decode("latin-1")
    def arr(self, at):                        # hkArray: ptr, int size, int cap
        return self.p(at), struct.unpack_from("<i", self.b, at + self.ps)[0]
    def find(self, cls): return [o for o, n in self.objs if n == cls]

def skeleton(pk):
    P = pk.ps; base = pk.find("hkaSkeleton")[0]; b = pk.b
    ro = 2 * P                                # hkReferencedObject = vtable + 4 bytes (+pad on 64)
    name = pk.cstr(base + ro)
    pa, n = pk.arr(base + ro + P)
    parents = list(struct.unpack_from("<%dh" % n, b, pa))
    asz = P + 8
    ba, nb = pk.arr(base + ro + P + asz)
    bones = [pk.cstr(ba + i * 2 * P) for i in range(nb)]
    ra, nr = pk.arr(base + ro + P + 2 * asz)
    ref = []
    for i in range(nr):
        t = struct.unpack_from("<12f", b, ra + 48 * i)
        ref.append((t[0:3], (t[7], t[4], t[5], t[6]), t[8:11]))   # pos, quat (w,x,y,z), scale
    return dict(name=name, parents=parents, bones=bones, ref=ref)

def binding(pk):
    P = pk.ps; base = pk.find("hkaAnimationBinding")[0]; b = pk.b
    ro = 2 * P; asz = P + 8
    # originalSkeletonName ptr, animation ptr, transformTrackToBoneIndices, floatTrack..., blendHint
    t2b_at = base + ro + 2 * P
    a, n = pk.arr(t2b_at)
    return list(struct.unpack_from("<%dh" % n, b, a)) if n else None

# ---------------------------------------------------------------- spline decompression
ROT_SIZE = {0: 4, 1: 5, 2: 6, 3: 3, 4: 2, 5: 16}
ROT_ALIGN = {0: 4, 1: 1, 2: 2, 3: 1, 4: 2, 5: 4}
FRACT40 = 0.000345436

def _align(o, a): return (o + a - 1) // a * a

def _rot(b, o, q):
    if q == 1:                                 # THREECOMP40
        v = int.from_bytes(b[o:o + 5], "little")
        m = (1 << 12) - 1
        c = [((v >> s) & m) for s in (0, 12, 24)]
        shift = (v >> 36) & 3; neg = (v >> 38) & 1
        f = [(x - 2047) * FRACT40 for x in c]
        w = math.sqrt(max(0.0, 1 - sum(x * x for x in f)))
        if neg: w = -w
        f.insert(shift, w)
        return (f[3], f[0], f[1], f[2])        # -> (w,x,y,z); havok xyzw order
    if q == 5:
        x, y, z, w = struct.unpack_from("<4f", b, o); return (w, x, y, z)
    if q == 2:                                 # THREECOMP48
        x, y, z = struct.unpack_from("<3H", b, o)
        shift = ((y >> 14) & 2) | (x >> 15); neg = (z >> 15) & 1
        m = 0x7FFF; fr = 0.000043161
        f = [((c & m) - 16383) * fr for c in (x, y, z)]
        w = math.sqrt(max(0.0, 1 - sum(t * t for t in f))); w = -w if neg else w
        f.insert(shift, w); return (f[3], f[0], f[1], f[2])
    raise NotImplementedError("rotation quantization %d" % q)

def _bspline_find(knots, deg, n, t):
    if t >= knots[n + 1]: return n
    lo, hi = deg, n + 1
    for s in range(deg, n + 1):
        if knots[s] <= t < knots[s + 1]: return s
    return n

def _bspline(knots, ctrl, deg, t):
    n = len(ctrl) - 1
    s = _bspline_find(knots, deg, n, t)
    d = [list(ctrl[j]) if isinstance(ctrl[j], (list, tuple)) else [ctrl[j]] for j in range(s - deg, s + 1)]
    for r in range(1, deg + 1):
        for j in range(deg, r - 1, -1):
            i = s - deg + j
            den = knots[i + deg + 1 - r] - knots[i]
            a = 0.0 if den == 0 else (t - knots[i]) / den
            d[j] = [(1 - a) * d[j - 1][k] + a * d[j][k] for k in range(len(d[j]))]
    return d[deg]

def animation_xml(path):
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    objs = {o.get("id"): o for o in root.iter("object")}
    a = next(o for o in objs.values() if o.get("type") == "hkaSplineCompressedAnimation")
    def f(name, kind):
        e = a.find("%s[@name='%s']" % (kind, name))
        if e is None: return None
        t = e.text.strip()
        if kind == "real":
            return struct.unpack("<f", struct.pack("<I", int(t.split()[0][1:], 16)))[0]
        return int(t)
    def arr(name):
        e = a.find("array[@name='%s']" % name)
        return [int(x) for x in (e.text or "").split()]
    refs = [r.text for r in a.find("array[@name='annotationTracks']").findall("ref")]
    names = [objs[r].find("string[@name='trackName']").text for r in refs]
    return decode(bytes(arr("data")), f("numberOfTransformTracks", "int"), f("numFrames", "int"),
                  f("numBlocks", "int"), f("maxFramesPerBlock", "int"), arr("blockOffsets"),
                  f("frameDuration", "real"), f("blockInverseDuration", "real"), f("duration", "real"), names)

def decode(data, ntr, numFrames, numBlocks, maxFPB, blockOffsets, frameDur, blockInv, dur, names):
    frames = []                                # frames[f][track] = {pos, rot, scl}
    for blk in range(numBlocks):
        bo = blockOffsets[blk]
        masks = [data[bo + 4 * t: bo + 4 * t + 4] for t in range(ntr)]
        c = _align(bo + 4 * ntr, 4)
        tracks = []
        for t in range(ntr):
            qt, pt, rt, st = masks[t]
            pq, rq, sq = qt & 3, (qt >> 2) & 0xF, (qt >> 6) & 3
            tr = {}
            for kind, flags, q in (("pos", pt, pq), ("rot", rt, rq), ("scl", st, sq)):
                if kind == "rot":
                    if rt & 0xF0:
                        nItems, deg = struct.unpack_from("<HB", data, c); c += 3
                        knots = list(data[c:c + nItems + deg + 2]); c += nItems + deg + 2
                        c = _align(c, ROT_ALIGN[q])
                        ctrl = []
                        for _ in range(nItems + 1):
                            ctrl.append(_rot(data, c, q)); c += ROT_SIZE[q]
                        tr["rot"] = ("spline", knots, deg, ctrl)
                    elif rt & 0x0F:
                        c = _align(c, ROT_ALIGN[q])
                        tr["rot"] = ("static", _rot(data, c, q)); c += ROT_SIZE[q]
                    else:
                        tr["rot"] = None
                    c = _align(c, 4)
                    continue
                if flags & 0x70:
                    nItems, deg = struct.unpack_from("<HB", data, c); c += 3
                    knots = list(data[c:c + nItems + deg + 2]); c += nItems + deg + 2
                    c = _align(c, 4)
                    axes = []
                    for ax in range(3):
                        if flags & (0x10 << ax):
                            lo, hi = struct.unpack_from("<2f", data, c); c += 8; axes.append(("s", lo, hi))
                        elif flags & (1 << ax):
                            v = struct.unpack_from("<f", data, c)[0]; c += 4; axes.append(("c", v))
                        else:
                            axes.append(("d", None))
                    ctrl = []
                    for _ in range(nItems + 1):
                        row = []
                        for ax in axes:
                            if ax[0] == "s":
                                if q == 0: v = data[c] / 255.0; c += 1
                                else: v = struct.unpack_from("<H", data, c)[0] / 65535.0; c += 2
                                row.append(ax[1] + (ax[2] - ax[1]) * v)
                        ctrl.append(row)
                    c = _align(c, 4)
                    tr[kind] = ("spline", knots, deg, ctrl, axes)
                else:
                    axes = []
                    for ax in range(3):
                        if flags & (1 << ax):
                            axes.append(struct.unpack_from("<f", data, c)[0]); c += 4
                        else:
                            axes.append(None)
                    tr[kind] = ("static", axes) if flags & 7 else None
            tracks.append(tr)
        nf = min(maxFPB, numFrames - blk * (maxFPB - 1))
        for fi in range(nf):
            if blk > 0 and fi == 0: continue
            frames.append([{k: _eval(tr.get(k), k, fi) for k in ("pos", "rot", "scl")} for tr in tracks])
    return dict(duration=dur, numFrames=numFrames, frames=frames, names=names, frameDur=frameDur, end=c)

def _eval(tr, kind, fi):
    if tr is None: return None
    if tr[0] == "static":
        return tr[1]
    knots, deg, ctrl = tr[1], tr[2], tr[3]
    v = _bspline(knots, ctrl, deg, float(fi))
    if kind == "rot":
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return tuple(x / n for x in v)
    axes = tr[4]; out = []; i = 0
    for a in axes:
        if a[0] == "s": out.append(v[i]); i += 1
        elif a[0] == "c": out.append(a[1])
        else: out.append(None)
    return out

if __name__ == "__main__":
    a = animation_xml(sys.argv[1])
    print("frames", len(a["frames"]), "/", a["numFrames"], "tracks", len(a["names"]), "consumed", a["end"])


def animation_bin(path):
    """binary hk_2010.2.0-r1 packfile (Skyrim SE: 8-byte pointers; LE: 4) -> same result as animation_xml"""
    pk = Pack(open(path, "rb").read()); b = pk.b; P = pk.ps; asz = P + 8          # hkArray = ptr + size + capacity
    a = pk.find("hkaSplineCompressedAnimation")[0]
    o = a + 2 * P                                                                  # hkReferencedObject
    _typ, dur, ntr, _nft = struct.unpack_from("<ifii", b, o); o += 16
    o += P                                                                         # extractedMotion
    ta, nt = pk.arr(o); o += asz                                                   # annotationTracks (inline structs)
    names = [pk.cstr(ta + i * (P + asz)) for i in range(nt)]
    nF, nB, mFPB, _mqs, _bd, binv, fdur = struct.unpack_from("<4i3f", b, o); o = _align(o + 28, P)
    boa, nbo = pk.arr(o)                                                           # blockOffsets (uint32)
    da, nd = pk.arr(o + 4 * asz)                                                   # data (uint8), after float/transform/float offsets
    return decode(b[da:da + nd], ntr, nF, nB, mFPB, list(struct.unpack_from("<%dI" % nbo, b, boa)), fdur, binv, dur, names)


import functools
@functools.lru_cache(maxsize=32)       # each stage file was parsed 4-5 times per scene (eve, adam, mg, source_world x3)
def animation(path):
    """any Skyrim animation hkx: XML tagfile (Leito, Proxy) or binary packfile (most packs). Cached: treat as read-only."""
    return animation_xml(path) if open(path, "rb").read(5) == b"<?xml" else animation_bin(path)
