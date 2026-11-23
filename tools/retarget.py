# retarget.py <sky_skeleton.hkx> <sky_anim.hkx(xml)> <ue_skeleton.json> <out.json> [--preview preview.json]
# Skyrim (Z-up, Y-forward, X-right, units) -> UE (Z-up, X-forward, Y-right, cm).
# Per mapped bone: R_tgt(t) = D(t) @ A @ R_tgt_rest, D = source world delta from its rest, A = rest bone-direction alignment.
# Bip001 (COM) position = s * source COM position, s = target COM rest height / source COM rest height (floor stays at 0).
# ponytail: per-actor uniform scale; partners drift ~1 cm at the hips. Add contact solving if scenes need it.
import sys, json, re
import numpy as np
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import hkx, ue

SIDE = {"L": "L", "R": "R"}
def bone_map():
    m = {"NPC COM [COM ]": "Bip001", "NPC Pelvis [Pelv]": "Bip001-Pelvis", "NPC Spine [Spn0]": "Bip001-Spine",
         "NPC Spine1 [Spn1]": "Bip001-Spine1", "NPC Spine2 [Spn2]": "Bip001-Spine2", "NPC Neck [Neck]": "Bip001-Neck",
         "NPC Head [Head]": "Bip001-Head"}
    for s in "LR":
        m.update({f"NPC {s} Clavicle [{s}Clv]": f"Bip001-{s}-Clavicle", f"NPC {s} UpperArm [{s}Uar]": f"Bip001-{s}-UpperArm",
                  f"NPC {s} Forearm [{s}Lar]": f"Bip001-{s}-Forearm", f"NPC {s} Hand [{s}Hnd]": f"Bip001-{s}-Hand",
                  f"NPC {s} Thigh [{s}Thg]": f"Bip001-{s}-Thigh", f"NPC {s} Calf [{s}Clf]": f"Bip001-{s}-Calf",
                  f"NPC {s} Foot [{s}ft ]": f"Bip001-{s}-Foot", f"NPC {s} Toe0 [{s}Toe]": f"Bip001-{s}-Toe0"})
        for f in range(5):
            for j in range(3):
                m[f"NPC {s} Finger{f}{j} [{s}F{f}{j}]"] = f"Bip001-{s}-Finger{f}" + ("" if j == 0 else str(j))
    return m

def align_child(t):
    """target bone -> target child used for rest direction alignment (must also be mapped)."""
    m = re.match(r"Bip001-([LR])-(\w+)$", t)
    chain = {"Bip001-Spine": "Bip001-Spine1", "Bip001-Spine1": "Bip001-Spine2", "Bip001-Spine2": "Bip001-Neck", "Bip001-Neck": "Bip001-Head"}
    if t in chain: return chain[t]
    if not m: return None
    s, n = m.groups()
    nxt = {"Clavicle": "UpperArm", "UpperArm": "Forearm", "Forearm": "Hand", "Hand": "Finger2", "Thigh": "Calf", "Calf": "Foot", "Foot": "Toe0"}
    if n in nxt: return f"Bip001-{s}-{nxt[n]}"
    fm = re.match(r"Finger(\d)(\d?)$", n)
    if fm and fm.group(2) in ("", "1"): return f"Bip001-{s}-Finger{fm.group(1)}{'1' if fm.group(2) == '' else '2'}"
    return None

def q2m(q):
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
def m2q(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1) * 2; return (0.25*s, (R[2,1]-R[1,2])/s, (R[0,2]-R[2,0])/s, (R[1,0]-R[0,1])/s)
    i = int(np.argmax(np.diag(R)))
    if i == 0:
        s = np.sqrt(1 + R[0,0] - R[1,1] - R[2,2]) * 2; return ((R[2,1]-R[1,2])/s, 0.25*s, (R[0,1]+R[1,0])/s, (R[0,2]+R[2,0])/s)
    if i == 1:
        s = np.sqrt(1 + R[1,1] - R[0,0] - R[2,2]) * 2; return ((R[0,2]-R[2,0])/s, (R[0,1]+R[1,0])/s, 0.25*s, (R[1,2]+R[2,1])/s)
    s = np.sqrt(1 + R[2,2] - R[0,0] - R[1,1]) * 2; return ((R[1,0]-R[0,1])/s, (R[0,2]+R[2,0])/s, (R[1,2]+R[2,1])/s, 0.25*s)
def align(a, b):
    """rotation matrix taking unit vector a onto b"""
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b); v = np.cross(a, b); c = float(np.dot(a, b))
    if c < -0.9999: # opposite: rotate 180 about any perpendicular
        p = np.cross(a, [1, 0, 0]); p = p if np.linalg.norm(p) > 1e-6 else np.cross(a, [0, 1, 0]); p /= np.linalg.norm(p)
        return 2 * np.outer(p, p) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)

MC = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]], float)   # Skyrim (x right, y fwd) <-> UE (x fwd, y right)

_LEVELS = {}
def _levels(parents):
    """bone indices grouped by depth (parents before children), cached per skeleton"""
    key = tuple(parents)
    if key not in _LEVELS:
        depth = []
        for i, pi in enumerate(parents): depth.append(0 if pi < 0 else depth[pi] + 1)
        d = np.array(depth); par = np.array(parents)
        _LEVELS[key] = (par, [np.nonzero(d == k)[0] for k in range(d.max() + 1)])
    return _LEVELS[key]

def q2m_batch(Q):
    w, x, y, z = Q[:, 0], Q[:, 1], Q[:, 2], Q[:, 3]
    return np.stack([np.stack([1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], -1),
                     np.stack([2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], -1),
                     np.stack([2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)], -1)], 1)

def world_mats(parents, local):
    """FK for every bone at once, one depth level per numpy step -> (Rw[n,3,3], Pw[n,3])"""
    par, levels = _levels(parents)
    P = np.array([l[0] for l in local], float); R = q2m_batch(np.array([l[1] for l in local], float))
    Rw, Pw = np.empty_like(R), np.empty_like(P)
    for k, idx in enumerate(levels):
        if k == 0: Rw[idx], Pw[idx] = R[idx], P[idx]; continue
        pi = par[idx]; Rw[idx] = Rw[pi] @ R[idx]; Pw[idx] = Pw[pi] + np.einsum("nij,nj->ni", Rw[pi], P[idx])
    return Rw, Pw

def world_mats_slow(parents, local):    # reference for the self-check
    Rw, Pw = [None] * len(parents), [None] * len(parents)
    for i, (p, q) in enumerate(local):
        R = q2m(q); p = np.array(p, float); pi = parents[i]
        if pi < 0: Rw[i], Pw[i] = R, p
        else: Rw[i], Pw[i] = Rw[pi] @ R, Pw[pi] + Rw[pi] @ p
    return Rw, Pw

def run(sky_skel, sky_anim, ue_skel, keep=None):
    """keep: bone names to output (their ancestors are added); None = the whole target rig. Only kept bones are computed,
    so a long clip no longer costs ~1.6 MB per frame on Eve's 3765-bone rig."""
    S = hkx.skeleton(hkx.Pack(open(sky_skel, "rb").read())); A = hkx.animation(sky_anim)
    T = ue.load_skeleton(ue_skel)
    sidx = {n: i for i, n in enumerate(S["bones"])}; tidx = {n: i for i, n in enumerate(T["names"])}
    bmap = {s: t for s, t in bone_map().items() if s in sidx and t in tidx}
    inv = {t: s for s, t in bmap.items()}
    s_rest = [(p, q) for p, q, _ in S["ref"]]
    sRr, sPr = world_mats(S["parents"], s_rest)
    sRr = [MC @ R @ MC for R in sRr]; sPr = [MC @ p for p in sPr]
    tRr, tPr = world_mats(T["parents"], T["pose"])
    # rest alignment per mapped target bone
    Aal = {}
    for t, s in inv.items():
        c = align_child(t)
        if c and c in inv:
            dt = tPr[tidx[c]] - tPr[tidx[t]]; ds = sPr[sidx[inv[c]]] - sPr[sidx[s]]
            Aal[t] = align(dt, ds) if np.linalg.norm(dt) > 1e-4 and np.linalg.norm(ds) > 1e-4 else np.eye(3)
        else:
            Aal[t] = np.eye(3)
    com_s, com_t = sidx["NPC COM [COM ]"], tidx["Bip001"]
    scale = float(tPr[com_t][2] / sPr[com_s][2])
    track = {n: t for t, n in enumerate(A["names"]) if n in sidx}
    kidx = set(range(len(T["names"]))) if keep is None else {i for i, n in enumerate(T["names"]) if n in keep}
    for i in list(kidx):
        p = T["parents"][i]
        while p >= 0: kidx.add(p); p = T["parents"][p]
    kidx = sorted(kidx); knew = {o: k for k, o in enumerate(kidx)}       # UE ref skeletons list parents before children
    out = []
    for fr in A["frames"]:
        loc = list(s_rest)
        for n, t in track.items():
            i = sidx[n]; rp, rq = s_rest[i]; tr = fr[t]
            pos = [r if (tr["pos"] is None or tr["pos"][k] is None) else tr["pos"][k] for k, r in enumerate(rp)]
            loc[i] = (pos, tr["rot"] or rq)
        sRw, sPw = world_mats(S["parents"], loc)
        # target world for mapped bones
        Rw, Pw = {}, {}
        local = []
        for i in kidx:
            n = T["names"][i]; pi = T["parents"][i]; rp, rq = T["pose"][i]
            PR = np.eye(3) if pi < 0 else Rw[pi]; PP = np.zeros(3) if pi < 0 else Pw[pi]
            if n in inv:
                si = sidx[inv[n]]
                D = (MC @ sRw[si] @ MC) @ sRr[si].T
                Rw[i] = D @ Aal[n] @ tRr[i]
            else:
                Rw[i] = PR @ q2m(rq)
            if i == com_t:
                Pw[i] = scale * (MC @ sPw[com_s])
            else:
                Pw[i] = PP + PR @ np.array(rp, float)
            lp = PR.T @ (Pw[i] - PP); lq = m2q(PR.T @ Rw[i])
            local.append((lp.tolist(), list(lq)))
        out.append(local)
    return dict(names=[T["names"][i] for i in kidx], parents=[knew.get(T["parents"][i], -1) for i in kidx],
                rest=[T["pose"][i] for i in kidx], fps=round(1 / A["frameDur"]), frames=out, scale=scale,
                mapped=sorted(inv))

def preview_json(r, path):
    """Blender-space (right-handed: flip UE Y) stick data for blend_preview.py, body bones only."""
    keep = [i for i, n in enumerate(r["names"]) if n in ("Root", "Base") or n.startswith("NPC-Genitals") or (n.startswith("Bip001") and not re.search(r"String|Prop|Footsteps|Xtra|Nub", n))]
    k2 = {i: j for j, i in enumerate(keep)}
    def par(i):
        p = r["parents"][i]
        while p >= 0 and p not in k2: p = r["parents"][p]
        return k2.get(p, -1)
    def fl(p, q): return [p[0], -p[1], p[2]], [q[0], -q[1], q[2], -q[3]]
    # collapse skipped parents: recompute locals from world for kept bones
    def kept_locals(local):
        Rw, Pw = world_mats(r["parents"], local); res = {}
        for j, i in enumerate(keep):
            pj = par(i)
            if pj < 0: lp, lq = Pw[i], m2q(Rw[i])
            else:
                pi = keep[pj]; lp = Rw[pi].T @ (Pw[i] - Pw[pi]); lq = m2q(Rw[pi].T @ Rw[i])
            res[str(j)] = list(fl(list(lp), list(lq)))
        return res
    rest = kept_locals(r["rest"])
    json.dump(dict(bones=[r["names"][i] for i in keep], parents=[par(i) for i in keep], ref=[rest[str(j)] for j in range(len(keep))],
                   fps=r["fps"], units="cm", frames=[kept_locals(f) for f in r["frames"]]), open(path, "w"))

if __name__ == "__main__":
    a = sys.argv[1:]
    r = run(a[0], a[1], a[2])
    json.dump(dict(names=r["names"], parents=r["parents"], fps=r["fps"], scale=r["scale"], mapped=r["mapped"], frames=r["frames"]), open(a[3], "w"))
    print("retargeted", len(r["frames"]), "frames, scale %.3f, %d mapped bones" % (r["scale"], len(r["mapped"])))
    if "--preview" in a: preview_json(r, a[a.index("--preview") + 1]); print("preview json written")


import functools
@functools.lru_cache(maxsize=16)
def source_world(sky_skel, sky_anim):
    """Skyrim-space bone world transforms (game units): rest and per frame -> dict(bones, rest=(R,P), frames=[(R,P)])"""
    S = hkx.skeleton(hkx.Pack(open(sky_skel, "rb").read())); A = hkx.animation(sky_anim)
    sidx = {n: i for i, n in enumerate(S["bones"])}; s_rest = [(p, q) for p, q, _ in S["ref"]]
    track = {n: t for t, n in enumerate(A["names"]) if n in sidx}; frames = []
    # skeleton.nif nodes the hkx skeleton lacks but scenes animate (Leito moves the double dildo with a WEAPON track):
    # extra bones under their skeleton.nif parent, local transform straight from the track (props ride them)
    extra = [(n, sidx[par], t) for n, par in SOURCE_EXTRA.items() for t, m in enumerate(A["names"]) if m == n and par in sidx]
    bones = S["bones"] + [n for n, _, _ in extra]; parents = list(S["parents"]) + [p for _, p, _ in extra]
    for fr in A["frames"]:
        loc = list(s_rest)
        for n, t in track.items():
            i = sidx[n]; rp, rq = s_rest[i]; tr = fr[t]
            loc[i] = ([r if (tr["pos"] is None or tr["pos"][k] is None) else tr["pos"][k] for k, r in enumerate(rp)], tr["rot"] or rq)
        for n, _, t in extra:
            tr = fr[t]; loc.append(([0.0 if (tr["pos"] is None or tr["pos"][k] is None) else tr["pos"][k] for k in range(3)], tr["rot"] or (1.0, 0.0, 0.0, 0.0)))
        frames.append(world_mats(parents, loc))
    rest = list(s_rest) + [([0.0, 0.0, 0.0], (1.0, 0.0, 0.0, 0.0))] * len(extra)
    return dict(bones=bones, parents=parents, rest=world_mats(parents, rest), frames=frames)


SOURCE_EXTRA = {"WEAPON": "NPC R Hand [RHnd]", "SHIELD": "NPC L Hand [LHnd]"}
