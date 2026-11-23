# UE-side helpers: FModel skeleton JSON + ActorX .psa reader, forward kinematics in UE space (cm, Z-up, X-forward).
# psa -> UE conversion verified against the skeleton rest pose (280/334 unanimated Adam bones match exactly).
import json, struct, math

def load_skeleton(path):
    d = json.load(open(path))
    s = next(e for e in d if e.get("Type") == "Skeleton")
    rs = s["ReferenceSkeleton"]
    names = [b["Name"] for b in rs["FinalRefBoneInfo"]]
    parents = [b["ParentIndex"] for b in rs["FinalRefBoneInfo"]]
    pose = []
    for t in rs["FinalRefBonePose"]:
        r, p = t["Rotation"], t["Translation"]
        pose.append(((p["X"], p["Y"], p["Z"]), (r["W"], r["X"], r["Y"], r["Z"])))
    return dict(names=names, parents=parents, pose=pose)

def read_psa(path):
    b = open(path, "rb").read(); o = 0; ch = {}
    while o < len(b):
        cid = b[o:o + 20].split(b"\0")[0].decode(); _flag, size, count = struct.unpack_from("<3i", b, o + 20); o += 32
        ch[cid] = (o, size, count); o += size * count
    o, size, n = ch["BONENAMES"]
    bones = [b[o + i * size:o + i * size + 64].split(b"\0")[0].decode() for i in range(n)]
    o, size, na = ch["ANIMINFO"]
    info = []
    for i in range(na):
        p = o + i * size
        name = b[p:p + 64].split(b"\0")[0].decode()
        totalBones, rootInc, keyStyle, keyQ, keyR, trackTime, fps, startBone, firstRaw, numRaw = struct.unpack_from("<iiiifffiii", b, p + 128)
        info.append(dict(name=name, fps=fps, first=firstRaw, frames=numRaw))
    o, size, nk = ch["ANIMKEYS"]
    nb = len(bones); a = info[0]; frames = []
    for f in range(a["frames"]):
        row = []
        for bi in range(nb):
            px, py, pz, qx, qy, qz, qw, _t = struct.unpack_from("<8f", b, o + ((a["first"] + f) * nb + bi) * size)
            # FModel ActorX -> UE: Y-flip; non-root quats negate Y, the root quat is also conjugated (matches rest pose)
            q = (qw, qx, -qy, qz) if bi else (qw, -qx, qy, -qz)
            row.append(((px, -py, pz), q))
        frames.append(row)
    return dict(bones=bones, fps=a["fps"], frames=frames)

def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return (aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw)
def qconj(q): return (q[0], -q[1], -q[2], -q[3])
def qrot(q, v): return qmul(qmul(q, (0.0, *v)), qconj(q))[1:]

def fk(parents, local):
    """local[i] = (pos, quat w-first) -> world list"""
    W = [None] * len(parents)
    for i, (p, q) in enumerate(local):
        pi = parents[i]
        if pi < 0: W[i] = (tuple(p), q)
        else:
            pp, pq = W[pi]; W[i] = (tuple(a + b for a, b in zip(pp, qrot(pq, p))), qmul(pq, q))
    return W


def read_psk_points(path):
    """psk/pskx points in UE space (Y flipped back), plus per-point dominant bone name."""
    b = open(path, "rb").read(); o = 0; ch = {}
    while o + 32 <= len(b):
        cid = b[o:o + 20].split(b"\0")[0].decode(); _f, size, count = struct.unpack_from("<3i", b, o + 20); o += 32
        ch[cid] = (o, size, count); o += size * count
    o, size, n = ch["PNTS0000"]
    pts = [struct.unpack_from("<3f", b, o + i * size) for i in range(n)]
    pts = [(x, -y, z) for x, y, z in pts]
    bo, bsize, bn = ch["REFSKELT"] if "REFSKELT" in ch else ch["REFSKEL0"]
    bones = [b[bo + i * bsize:bo + i * bsize + 64].split(b"\0")[0].decode() for i in range(bn)]
    wo, wsize, wn = ch.get("RAWWEIGHTS") or ch["RAWW0000"]
    best = {}
    for i in range(wn):
        w, pi, bi = struct.unpack_from("<fii", b, wo + i * wsize)
        if w > best.get(pi, (0, None))[0]: best[pi] = (w, bones[bi])
    return pts, [best.get(i, (0, None))[1] for i in range(n)], list(ch)
