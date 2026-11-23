# nif.py: minimal Skyrim SE (20.2.0.7, BS 100) skinned-body reader -- just what contact detection needs.
#   body(path) -> {bone name: Nx3 vertex positions in that bone's space}  (each vertex rigidly on its dominant bone)
# Reads BSTriShape -> BSDismemberSkinInstance/NiSkinInstance -> NiSkinData (skin->bone transforms) + NiSkinPartition
# (SSE global vertex buffer + per-partition weights). Not a general NIF library.
# check: python tools/nif.py <body.nif>
import struct, sys
import numpy as np


class R:
    def __init__(s, b, o=0): s.b, s.o = b, o
    def u(s, f):
        v = struct.unpack_from("<" + f, s.b, s.o); s.o += struct.calcsize("<" + f); return v if len(v) > 1 else v[0]
    def s32(s): n = s.u("I"); v = s.b[s.o:s.o + n].decode("latin1"); s.o += n; return v
    def s8(s): n = s.u("B"); v = s.b[s.o:s.o + n].rstrip(b"\0").decode("latin1"); s.o += n; return v


def read(path):
    b = open(path, "rb").read(); r = R(b); r.o = b.index(b"\n") + 1
    ver, endian, user, nblk = r.u("IBII"); bsver = r.u("I")
    assert ver == 0x14020007 and bsver == 100, "not a Skyrim SE nif (ver %x bs %d)" % (ver, bsver)
    r.s8(); r.s8(); r.s8()                                   # author, process script, export script
    types = [r.s32() for _ in range(r.u("H"))]
    tix = [r.u("H") for _ in range(nblk)]; sizes = [r.u("I") for _ in range(nblk)]
    nstr = r.u("I"); r.u("I"); strings = [r.s32() for _ in range(nstr)]
    ng = r.u("I"); r.o += 4 * ng                             # groups
    blocks, o = [], r.o
    for i in range(nblk): blocks.append((types[tix[i]], o, sizes[i])); o += sizes[i]
    return b, blocks, strings


def tf(r):  # NiTransform: rotation 3x3, translation, scale
    m = np.array(r.u("9f")).reshape(3, 3); t = np.array(r.u("3f")); s = r.u("f"); return m, t, s


def body(path):
    b, blocks, strings = read(path)
    name_of = lambda i: strings[struct.unpack_from("<i", b, blocks[i][1])[0]]
    out = {}
    for typ, o, _ in blocks:
        if typ != "BSTriShape": continue
        r = R(b, o); r.u("i"); ne = r.u("I"); r.o += 4 * ne; r.u("i")  # NiObjectNET: name, extra data, controller
        r.u("I"); r.u("3f"); r.u("9f"); r.u("f"); r.u("i")      # NiAVObject: flags, translation, rotation, scale, collision
        r.u("4f"); skin = r.u("i"); r.u("i"); r.u("i"); r.u("Q"); r.u("H"); nv = r.u("H"); dsize = r.u("I")
        if skin < 0: continue
        # skin instance: data, partition, skeleton root, bones
        s = R(b, blocks[skin][1]); data, part, _root = s.u("iii"); bones = [name_of(s.u("i")) for _ in range(s.u("I"))]
        # skin data: overall transform, per-bone skin->bone transforms
        d = R(b, blocks[data][1]); tf(d); nb = d.u("I"); hasw = d.u("B"); B = []
        for _ in range(nb):
            B.append(tf(d)); d.u("4f")
            if hasw: nw = d.u("H"); d.o += 6 * nw
        # skin partition (SSE): global vertex buffer, then partitions with vertex maps / weights / bone indices
        p = R(b, blocks[part][1]); npart = p.u("I"); dsz, vsz = p.u("II"); desc = p.u("Q")
        # SSE (BS 100) vertex positions are always 3 floats + bitangent X
        vb = p.o; nvb = dsz // vsz; p.o += dsz
        pos = np.array([struct.unpack_from("<3f", b, vb + i * vsz) for i in range(nvb)])
        best_w = np.zeros(nvb); best_b = np.full(nvb, -1)
        for _ in range(npart):
            pnv, ptri, pnb, pns, pnw = p.u("5H"); pb = [p.u("H") for _ in range(pnb)]
            vmap = [p.u("H") for _ in range(pnv)] if p.u("B") else list(range(pnv))
            W = np.array(p.u("%df" % (pnv * pnw))).reshape(pnv, pnw) if p.u("B") else np.ones((pnv, 1))
            sl = [p.u("H") for _ in range(pns)]
            if p.u("B"):
                p.o += 2 * (sum(sl) if pns else 3 * ptri)
            if p.u("B"): BI = np.frombuffer(b, np.uint8, pnv * pnw, p.o).reshape(pnv, pnw); p.o += pnv * pnw
            else: BI = np.zeros((pnv, pnw), np.uint8)
            p.u("B"); p.u("B"); p.u("Q"); p.o += 6 * ptri           # LOD level, global VB, vertex desc, triangles copy
            for k in range(pnv):
                j = int(np.argmax(W[k])); g = vmap[k]
                if W[k, j] > best_w[g]: best_w[g] = W[k, j]; best_b[g] = pb[BI[k, j]]
        for g in range(nvb):
            if best_b[g] < 0: continue
            m, t, sc = B[best_b[g]]
            out.setdefault(bones[best_b[g]], []).append((m @ pos[g] * sc + t, pos[g]))
    return {k: (np.array([a for a, _ in v]), np.array([c for _, c in v])) for k, v in out.items()}   # bone -> (bone-space, bind-space)


def on_skeleton(path, bones, rest, fallback="NPC Spine2 [Spn2]"):
    """body verts per skeleton bone index: {i: Nx3 bone-local}. Bones the skeleton lacks (breast physics...) go onto
    fallback using their bind-space position and the skeleton rest pose."""
    idx = {n: i for i, n in enumerate(bones)}; R, P = rest; out = {}
    for k, (loc, bind) in body(path).items():
        if k in idx: i = idx[k]; v = loc
        else: i = idx[fallback]; v = (bind - P[i]) @ R[i]
        out[i] = np.vstack([out[i], v]) if i in out else v
    return out


if __name__ == "__main__":
    bd = body(sys.argv[1])
    print(len(bd), "bones,", sum(len(v[0]) for v in bd.values()), "verts")
    for k in sorted(bd, key=lambda k: -len(bd[k][0]))[:12]: print("  %-32s %5d" % (k, len(bd[k][0])))


def static_mesh(path):
    """LE/SE prop nif with NiTriShape(s) -> (verts Nx3 in the prop's root space, tris Mx3, parent bone from 'Prn' extra data)"""
    b = open(path, "rb").read(); r = R(b); r.o = b.index(b"\n") + 1
    ver, endian, user, nblk = r.u("IBII"); bsver = r.u("I"); r.s8(); r.s8(); r.s8()
    types = [r.s32() for _ in range(r.u("H"))]
    tix = [r.u("H") for _ in range(nblk)]; sizes = [r.u("I") for _ in range(nblk)]
    nstr = r.u("I"); r.u("I"); strings = [r.s32() for _ in range(nstr)]
    ng = r.u("I"); r.o += 4 * ng
    blocks, o = [], r.o
    for i in range(nblk): blocks.append((types[tix[i]], o)); o += sizes[i]
    prn, V, T = None, [], []
    for typ, o in blocks:
        if typ == "NiStringExtraData":
            nm, val = struct.unpack_from("<ii", b, o)
            if 0 <= nm < nstr and strings[nm] == "Prn": prn = strings[val]
        if typ != "NiTriShape": continue
        s = R(b, o); s.u("i"); ne = s.u("I"); s.o += 4 * ne; s.u("i"); s.u("I")
        t = np.array(s.u("3f")); m = np.array(s.u("9f")).reshape(3, 3); sc = s.u("f"); s.u("i")
        data = s.u("i")
        d = R(b, blocks[data][1]); d.u("i"); nv = d.u("H"); d.u("B"); d.u("B")
        v = np.array(d.u("%df" % (3 * nv))).reshape(nv, 3) if d.u("B") else np.zeros((nv, 3))
        flags = d.u("H"); d.u("I")                             # BS vector flags, material CRC
        if d.u("B"):
            d.o += 12 * nv
            if flags & 4096: d.o += 24 * nv                    # tangents + bitangents
        d.u("4f")                                               # center, radius
        if d.u("B"): d.o += 16 * nv                             # vertex colors
        d.o += 8 * nv * (flags & 63)                            # UV sets
        d.u("H"); d.u("i"); ntri = d.u("H"); d.u("I")
        tri = np.array(d.u("%dH" % (3 * ntri))).reshape(ntri, 3) if d.u("B") else np.zeros((0, 3), int)
        base = sum(len(x) for x in V); V.append((v * sc) @ m.T + t); T.append(tri + base)
    return np.vstack(V), np.vstack(T), prn


def static_mesh_any(path):
    """prop nif, LE (NiTriShape) or SE (BSTriShape, plain or skinned) -> (verts Nx3 in the prop's root space, tris Mx3, 'Prn').
    SE: positions are the first 3 floats of each vertex (SSE is full precision); a skinned shape keeps its vertices in the
    skin partition's global buffer (bind space) with triangle copies in global indices. (2026-11-23: Billyy's props are SE.)"""
    b = open(path, "rb").read(); r = R(b); r.o = b.index(b"\n") + 1
    ver, endian, user, nblk = r.u("IBII"); bsver = r.u("I")
    if bsver != 100: return static_mesh(path)
    r.s8(); r.s8(); r.s8()
    types = [r.s32() for _ in range(r.u("H"))]
    tix = [r.u("H") for _ in range(nblk)]; sizes = [r.u("I") for _ in range(nblk)]
    nstr = r.u("I"); r.u("I"); strings = [r.s32() for _ in range(nstr)]
    ng = r.u("I"); r.o += 4 * ng
    blocks, o = [], r.o
    for i in range(nblk): blocks.append((types[tix[i]], o)); o += sizes[i]
    prn, V, T = None, [], []
    for typ, o in blocks:
        if typ == "NiStringExtraData":
            nm, val = struct.unpack_from("<ii", b, o)
            if 0 <= nm < nstr and strings[nm] == "Prn": prn = strings[val]
        if typ not in ("BSTriShape", "BSDynamicTriShape"): continue
        s = R(b, o); s.u("i"); ne = s.u("I"); s.o += 4 * ne; s.u("i"); s.u("I")
        t = np.array(s.u("3f")); m = np.array(s.u("9f")).reshape(3, 3); sc = s.u("f"); s.u("i")
        s.u("4f"); skin = s.u("i"); s.u("i"); s.u("i"); desc = s.u("Q"); ntri = s.u("H"); nv = s.u("H"); dsize = s.u("I")
        vsz = (desc & 0xF) * 4
        if dsize > 0 and vsz >= 12:
            vb = s.o; v = np.array([struct.unpack_from("<3f", b, vb + i * vsz) for i in range(nv)]); s.o += nv * vsz
            tri = np.array(s.u("%dH" % (3 * ntri))).reshape(ntri, 3) if ntri else np.zeros((0, 3), int)
        elif skin >= 0:
            sk = R(b, blocks[skin][1]); _data, part = sk.u("ii")
            p = R(b, blocks[part][1]); npart = p.u("I"); dsz, pvs = p.u("II"); p.u("Q")
            if not pvs: continue
            vb = p.o; nvb = dsz // pvs; p.o += dsz
            v = np.array([struct.unpack_from("<3f", b, vb + i * pvs) for i in range(nvb)]); tri = []
            for _ in range(npart):
                pnv, ptri, pnb, pns, pnw = p.u("5H"); p.o += 2 * pnb
                if p.u("B"): p.o += 2 * pnv
                if p.u("B"): p.o += 4 * pnv * pnw
                sl = [p.u("H") for _ in range(pns)]
                if p.u("B"): p.o += 2 * (sum(sl) if pns else 3 * ptri)
                if p.u("B"): p.o += pnv * pnw
                p.u("B"); p.u("B"); p.u("Q"); tri += [p.u("3H") for _ in range(ptri)]
            tri = np.array(tri).reshape(-1, 3)
        else:
            continue
        if len(v) == 0 or len(tri) == 0: continue
        base = sum(len(x) for x in V); V.append((v * sc) @ m.T + t); T.append(tri + base)
    if not V: raise ValueError("no readable shapes in " + path)
    return np.vstack(V), np.vstack(T), prn


def skinned_parts(path):
    """skinned SE prop (armbinder, yoke...) -> {skyrim bone: (verts Nx3 in that bone's space, tris Mx3)}: every vertex rigid
    on its dominant bone, every triangle on its first vertex's bone. None when the nif has no skinned BSTriShape."""
    b, blocks, strings = read(path)
    name_of = lambda i: strings[struct.unpack_from("<i", b, blocks[i][1])[0]]
    parts = {}
    for typ, o, _ in blocks:
        if typ != "BSTriShape": continue
        r = R(b, o); r.u("i"); ne = r.u("I"); r.o += 4 * ne; r.u("i"); r.u("I"); r.u("3f"); r.u("9f"); r.u("f"); r.u("i")
        r.u("4f"); skin = r.u("i"); r.u("i"); r.u("i"); desc = r.u("Q"); ntri = r.u("H"); nv = r.u("H"); dsize = r.u("I")
        if skin < 0: continue
        s = R(b, blocks[skin][1]); data, part, _root = s.u("iii"); bones = [name_of(s.u("i")) for _ in range(s.u("I"))]
        d = R(b, blocks[data][1]); tf(d); nb = d.u("I"); hasw = d.u("B"); B = []
        for _ in range(nb):
            B.append(tf(d)); d.u("4f")
            if hasw: nw = d.u("H"); d.o += 6 * nw
        if dsize > 0:   # vertices (+ per-vertex skin weights) in the shape itself (Billyy's rope cuffs), bind space
            vsz = (desc & 0xF) * 4; so = ((desc >> 28) & 0xF) * 4; vb = r.o
            pos = np.array([struct.unpack_from("<3f", b, vb + i * vsz) for i in range(nv)])
            wb = [struct.unpack_from("<4e4B", b, vb + i * vsz + so) for i in range(nv)] if so else [(1, 0, 0, 0, 0, 0, 0, 0)] * nv
            dom = np.array([w[4 + int(np.argmax(w[:4]))] for w in wb]); r.o = vb + nv * vsz
            tris = np.array(r.u("%dH" % (3 * ntri))).reshape(-1, 3) if ntri else np.zeros((0, 3), int)
            for bi in np.unique(dom):
                m, t_, sc = B[bi]; tl = tris[dom[tris[:, 0]] == bi]
                if not len(tl): continue
                used = np.unique(tl); remap = {int(u): k for k, u in enumerate(used)}
                v = np.array([m @ pos[u] * sc + t_ for u in used]); tt = np.vectorize(remap.get)(tl); bn = bones[bi]
                if bn in parts: base = len(parts[bn][0]); parts[bn] = (np.vstack([parts[bn][0], v]), np.vstack([parts[bn][1], tt + base]))
                else: parts[bn] = (v, tt)
            continue
        p = R(b, blocks[part][1]); npart = p.u("I"); dsz, vsz = p.u("II"); p.u("Q")
        if not vsz: continue
        vb = p.o; nvb = dsz // vsz; p.o += dsz
        pos = np.array([struct.unpack_from("<3f", b, vb + i * vsz) for i in range(nvb)])
        best_w = np.zeros(nvb); best_b = np.full(nvb, -1); tris = []
        for _ in range(npart):
            pnv, ptri, pnb, pns, pnw = p.u("5H"); pb = [p.u("H") for _ in range(pnb)]
            vmap = [p.u("H") for _ in range(pnv)] if p.u("B") else list(range(pnv))
            W = np.array(p.u("%df" % (pnv * pnw))).reshape(pnv, pnw) if p.u("B") else np.ones((pnv, 1))
            sl = [p.u("H") for _ in range(pns)]
            if p.u("B"): p.o += 2 * (sum(sl) if pns else 3 * ptri)
            if p.u("B"): BI = np.frombuffer(b, np.uint8, pnv * pnw, p.o).reshape(pnv, pnw); p.o += pnv * pnw
            else: BI = np.zeros((pnv, pnw), np.uint8)
            p.u("B"); p.u("B"); p.u("Q"); tris += [p.u("3H") for _ in range(ptri)]
            for k in range(pnv):
                j = int(np.argmax(W[k])); g = vmap[k]
                if W[k, j] > best_w[g]: best_w[g] = W[k, j]; best_b[g] = pb[BI[k, j]]
        loc = np.zeros_like(pos)
        for g in range(nvb):
            if best_b[g] >= 0: m, t, sc = B[best_b[g]]; loc[g] = m @ pos[g] * sc + t
        by = {}
        for tri in tris:
            bi = best_b[tri[0]]
            if bi >= 0: by.setdefault(bones[bi], []).append(tri)
        for bn, tl in by.items():
            tl = np.array(tl); used = np.unique(tl); remap = {int(u): k for k, u in enumerate(used)}
            v, t = loc[used], np.vectorize(remap.get)(tl)
            if bn in parts: base = len(parts[bn][0]); parts[bn] = (np.vstack([parts[bn][0], v]), np.vstack([parts[bn][1], t + base]))
            else: parts[bn] = (v, t)
    return parts or None
