# props.py: Skyrim AnimObjects (dildos, toys...) -> a Stellar Blade prop actor driven by its own clip.
#   stage_objects(root)        FNIS list "-o" entries: stage hkx id -> AnimObject editor ids
#   resolve(editorid, root)    AnimObject -> nif path (work/anio.json, exported once from the load order with houseCARL)
#   prop_mesh(nif_path, scale) verts/tris in the prop bone's UE space (cm) + the Skyrim bone it rides on ('Prn')
#   prop_clip(sky_world, bone, scale)  clip json on the 2-bone prop skeleton (Root, Bip001-Toy), UE space
#   align(toy, eve, mesh, target)      shift the toy so its axis runs through Eve's entry point (depth kept from the source)
#   skeleton_json(path)                FModel-style skeleton json for make_fbx.py
# check: python tools/props.py  (Leito dildo resolves, mesh reads, a clip builds)
import os, re, glob, json, sys
import numpy as np
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import retarget as rt, nif, ue, contact as ct, cfg

R0 = __file__.replace("\\", "/").rsplit("/", 2)[0]
MODS = cfg.SKYRIM_MODS
NAMES, PARENTS = ["Root", "Bip001-Toy"], [-1, 0]
GATE_CM = 20.0      # toy axis further than this from the entry (median) = not inserted in this stage: leave it


def stage_objects(root):
    out = {}
    for f in glob.glob(root + "/meshes/actors/character/animations/**/FNIS_*_List.txt", recursive=True):
        for ln in open(f, encoding="utf-8", errors="replace"):
            p = ln.split()                         # <type> -<options incl. o> <event> <file.hkx> <AnimObject...>
            if len(p) >= 5 and p[1].startswith("-") and "o" in p[1][1:].split(","):
                out[p[2].lower()] = p[4:]
    return out


def resolve(editorid, root):
    rel = json.load(open(R0 + "/work/anio.json")).get(editorid.lower())
    if not rel: return None
    for d in [root] + glob.glob(MODS + "/*"):
        p = os.path.join(d, rel)
        if os.path.exists(p): return p.replace("\\", "/")
    return None                                   # BSA-packed: not supported yet


SMOOTH = {"dildoanimobject01"}   # ponytail: props whose Skyrim mesh is a poor stand-in (Leito's "gem dildo" is a 58-tri soul gem)
#   get a procedural dildo fitted to the same axis; add names here when another prop looks wrong in game.


def smooth_dildo(v, segs=24):
    """procedural dildo along the source mesh's long (local z) axis: flared base at z-min, where the Skyrim hand grips it
    (AnimObjectR is parented to the right hand, palm at local z ~ -1.4), tip at z-max (the inserted end)"""
    c = (v[:, :2].max(0) + v[:, :2].min(0)) / 2; z0, z1 = v[:, 2].min(), v[:, 2].max(); L = z1 - z0
    prof = [(0.0, 0.0), (0.02, 0.55), (0.05, 0.95), (0.09, 1.2), (0.13, 1.32), (0.16, 1.12), (0.22, 1.08), (0.5, 1.12),
            (0.8, 1.18), (0.9, 1.35), (0.95, 1.9), (0.99, 1.9), (1.0, 0.0)]          # (t along the axis, radius in Skyrim units)
    verts, tris = [], []
    for t, r in prof:
        for k in range(segs):
            a = 2 * np.pi * k / segs; verts.append([c[0] + r * np.cos(a), c[1] + r * np.sin(a), z1 - t * L])
    for i in range(len(prof) - 1):
        for k in range(segs):
            a, b = i * segs + k, i * segs + (k + 1) % segs; tris += [[a, a + segs, b], [b, a + segs, b + segs]]
    return np.array(verts), np.array(tris)


def prop_mesh(path, scale):
    v, t, prn = nif.static_mesh(path)
    if re.sub(r"\W", "", os.path.basename(path)[:-4]) in SMOOTH: v, t = smooth_dildo(v)
    vu = scale * (v @ rt.MC.T)                     # MC mirrors: flip the winding back
    name = re.sub(r"\W", "", os.path.basename(path)[:-4])
    return dict(verts=vu.round(4).tolist(), tris=t[:, [0, 2, 1]].tolist(), bone="Bip001-Toy", skyrim_bone=prn or "AnimObjectR",
                name=name + ("_smooth" if name in SMOOTH else ""))


def hold(eve, toy, sky_world, bone, scale):
    """the hand that carries the prop in Skyrim (AnimObjectR -> right hand) keeps its grip on the toy after align():
    palm position and finger direction are taken in the toy's frame from the source and re-applied to the SB toy."""
    import hands as hd
    side = "L" if bone.endswith("L") else "R"; b = sky_world["bones"]; io = b.index(bone)
    h, f2 = b.index("NPC %s Hand [%sHnd]" % (side, side)), b.index("NPC %s Finger20 [%sF20]" % (side, side))
    eve = json.loads(json.dumps(eve)); n = eve["names"]; eh, ef = n.index("Bip001-%s-Hand" % side), n.index("Bip001-%s-Finger2" % side)
    F = min(len(eve["frames"]), len(toy["frames"]), len(sky_world["frames"])); D = []
    for f in range(F):
        R, P = sky_world["frames"][f]; lp = R[io].T @ ((P[h] + P[f2]) / 2 - P[io]); ld = R[io].T @ (P[f2] - P[h])
        Ru = rt.q2m(toy["frames"][f][1][1]); Pu = np.array(toy["frames"][f][1][0])
        want_p = Pu + Ru @ (scale * (rt.MC @ lp)); want_d = Ru @ (rt.MC @ ld); want_d /= np.linalg.norm(want_d)
        Rw, Pw = rt.world_mats(eve["parents"], eve["frames"][f]); d = Pw[ef] - Pw[eh]; d /= np.linalg.norm(d)
        fr = eve["frames"][f]; fr[eh] = [fr[eh][0], list(rt.m2q(Rw[eve["parents"][eh]].T @ rt.align(d, want_d) @ Rw[eh]))]
        _, Pw = rt.world_mats(eve["parents"], eve["frames"][f]); D.append(want_p - (Pw[eh] + Pw[ef]) / 2)
    D += [D[-1]] * (len(eve["frames"]) - F)
    hd.apply_hands(eve, {side: D})
    return eve


def prop_clip(sky_world, bone, scale, fps):
    i = sky_world["bones"].index(bone); frames = []
    for R, P in sky_world["frames"]:
        Ru = rt.MC @ R[i] @ rt.MC; Pu = scale * (rt.MC @ P[i])
        frames.append([([0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]), (Pu.tolist(), list(rt.m2q(Ru)))])
    return {"names": NAMES, "parents": PARENTS, "fps": fps, "frames": frames}


def axis_ends(toy, mesh, f):
    v = np.array(mesh["verts"]); Ru = rt.q2m(toy["frames"][f][1][1]); Pu = np.array(toy["frames"][f][1][0])
    lo, hi = v[np.argmin(v[:, 2])], v[np.argmax(v[:, 2])]
    return Pu + Ru @ lo, Pu + Ru @ hi


def align(toy, eve, mesh, target):
    """per frame: move the toy (no rotation) so its axis passes through the entry; the end that is nearer the entry in the
    source stays the inserted end, at the source depth. -> (toy, report) ; gated off when the source toy is nowhere near."""
    E = ue.load_skeleton(R0 + "/skeletons/CH_P_EVE_01_Skeleton.json"); ips = E["names"].index("Bip001-Pelvis")
    Rr, Pr = rt.world_mats(E["parents"], E["pose"]); el = Rr[ips].T @ (ct.ENTRY[target][0] - Pr[ips])
    ip = eve["names"].index("Bip001-Pelvis")                                       # clip index
    F = min(len(toy["frames"]), len(eve["frames"])); miss, D = [], []
    for f in range(F):
        R, P = rt.world_mats(eve["parents"], eve["frames"][f]); ent = P[ip] + R[ip] @ el
        a, b = axis_ends(toy, mesh, f); u = (b - a) / np.linalg.norm(b - a)
        q = a + np.dot(ent - a, u) * u; miss.append(float(np.linalg.norm(ent - q))); D.append(ent - q)
    rep = dict(axis_miss_cm=round(float(np.median(miss)), 1))
    if np.median(miss) > GATE_CM: rep["aligned"] = False; return toy, rep
    toy = json.loads(json.dumps(toy)); D = np.array(D)
    k = np.array([1, 2, 3, 2, 1.0]) / 9; D = np.array([sum(k[j] * D[(f + j - 2) % F] for j in range(5)) for f in range(F)])
    for f in range(F): toy["frames"][f][1] = [list(np.array(toy["frames"][f][1][0]) + D[f]), toy["frames"][f][1][1]]
    rep["aligned"] = True; return toy, rep


def skeleton_json(path):
    bones = [{"Name": n, "ParentIndex": p} for n, p in zip(NAMES, PARENTS)]
    pose = [{"Rotation": {"X": 0, "Y": 0, "Z": 0, "W": 1}, "Translation": {"X": 0, "Y": 0, "Z": 0}, "Scale3D": {"X": 1, "Y": 1, "Z": 1}}] * 2
    tmp = "%s.%d.tmp" % (path, os.getpid())      # atomic: Blenders of other workers may be reading it
    json.dump([{"Type": "Skeleton", "Name": "SkyrimProp_Skeleton", "ReferenceSkeleton": {"FinalRefBoneInfo": bones, "FinalRefBonePose": pose}}], open(tmp, "w"))
    os.replace(tmp, path); return path


if __name__ == "__main__":
    root = MODS + "/SLAL Animations by Leito v1.6"
    objs = stage_objects(root); print("stages with objects:", len(objs), objs.get("leito_f_solo_dildo_vag_a1_s1"))
    p = resolve("AODildoGem", root); print(p); m = prop_mesh(p, 1.435); print(m["name"], m["skyrim_bone"], len(m["verts"]), len(m["tris"]))
    assert m["skyrim_bone"] == "AnimObjectR" and len(m["tris"]) > 0


# ------------------------------------------------------------------ general props: solo + duo, any number (2026-11-23)
# Every distinct (actor, AnimObject) of a scene becomes a prop actor with its own mesh + clip. The prop rides the SB bone
# that matches where it rides in Skyrim (its 'Prn' node, or the nearest body bone for root-parented restraints like the
# yoke / armbinder), so it stays on SB's arms even after the IK passes moved them. Big root props (poles, crosses,
# pillories) stay where Skyrim put them, moved with the actor when the port slides him/her. Absent in a stage = hidden.
HIDE = [0.0, 0.0, -10000.0]
NEAR_SKY = 15.0      # Skyrim units: a root-parented prop this close to a body bone rides that bone
MATERIALS = [        # (name keywords, material asset, rgb, roughness)
    (("rope",), "M_SkyrimRope", (0.55, 0.42, 0.26), 0.9),
    (("cuff", "yoke", "chain", "iron", "metal", "shack", "collar", "gag", "ball", "mc", "binder"), "M_SkyrimMetal", (0.18, 0.18, 0.2), 0.35),
    (("pole", "pillory", "cross", "wheel", "throne", "chair", "bench", "table", "stool", "haybale", "crop", "staff", "mug", "bed", "desk"),
     "M_SkyrimWood", (0.36, 0.24, 0.14), 0.8),
]


def material_for(name):
    n = name.lower()
    for keys, mat, rgb, rough in MATERIALS:
        if any(k in n for k in keys): return mat, rgb, rough
    return "M_SkyrimSilicone", (0.78, 0.22, 0.52), 0.35


def scene_props(a, root):
    """-> [(actor index, editor id, nif path)] distinct, in order; plus {(actor, stage): [editor ids]} and the unusable ones"""
    objs = stage_objects(root); out, per, bad = [], {}, []
    for ai, act in enumerate(a["actors"]):
        for si, st in enumerate(act["stages"]):
            ids = objs.get(st["id"].lower(), []); per[(ai, si)] = ids
            for o in ids:
                if any(x[0] == ai and x[1] == o for x in out) or o in bad: continue
                p = resolve(o, root)
                try:
                    if p:
                        v = nif.static_mesh_any(p)[0]
                        # effects, not objects: paper-flat decals (Billyy's "MC" discs) and magic / fx / cum meshes would show
                        # as solid slabs in SB (no glow or transparency here) -> dropped
                        if (v.max(0) - v.min(0)).min() < 0.5 or re.search(r"magic|mnode|mball|fx|effect|cum|glow", o + p, re.I): p = None
                except Exception: p = None
                if p: out.append((ai, o, p))
                else: bad.append(o)
    return out, per, bad


NODE_ALIAS = {"WEAPON": "NPC R Hand [RHnd]", "SHIELD": "NPC L Forearm [LLar]"}   # skeleton.nif nodes the hkx skeleton lacks


_rest = {}
def sky_rest(sky_skel):
    if sky_skel not in _rest:
        import hkx; S = hkx.skeleton(hkx.Pack(open(sky_skel, "rb").read()))
        _rest[sky_skel] = (S["bones"], rt.world_mats(S["parents"], [(p, q) for p, q, _ in S["ref"]]))
    return _rest[sky_skel]


def prop_mesh_any(path, scale, suffix="", sky_skel=None):
    """skinned props (Billyy's armbinder / yoke: fully weighted to Spine2; poles: to the root) ride their dominant bone, in
    that bone's space; static ones ride their Prn node (WEAPON / SHIELD -> the hand / forearm they sit on)"""
    try: parts = nif.skinned_parts(path)          # SE only (LE nifs: bs 83 -> static reader)
    except AssertionError: parts = None
    if parts:
        prn, (v, t) = max(parts.items(), key=lambda kv: len(kv[1][0]))   # ponytail: the biggest part only; split if a prop needs it
    else:
        v, t, prn = nif.static_mesh_any(path)
        # a static prop on a BODY bone (Billyy's rope / metal cuffs) is modelled in the skeleton's bind-pose space, not the
        # bone's: into the bone's space with the rest pose (rope 78 units off -> 3 units around the wrist, 2026-11-23)
        if sky_skel and prn and prn in rt.bone_map():   # bind space or the bone's own: whichever hugs the bone (to its child)
            bones, (Rr, Pr) = sky_rest(sky_skel); k = bones.index(prn); vb = (v - Pr[k]) @ Rr[k]
            S = __import__("hkx").skeleton(__import__("hkx").Pack(open(sky_skel, "rb").read()))
            kids = [c for c, pk in enumerate(S["parents"]) if pk == k and bones[c] in rt.bone_map()]
            end = (Pr[kids[0]] - Pr[k]) @ Rr[k] if kids else np.zeros(3)
            def seg(x):
                L2 = float(end @ end); t_ = np.clip(x @ end / L2, 0, 1) if L2 > 1e-9 else np.zeros(len(x))
                return float(np.median(np.linalg.norm(x - t_[:, None] * end, axis=1)))
            if seg(vb) < seg(v): v = vb
    name = re.sub(r"\W", "", os.path.basename(path)[:-4]) + suffix
    vu = scale * (v @ rt.MC.T)
    mat = material_for(name)
    return dict(verts=vu.round(4).tolist(), tris=t[:, [0, 2, 1]].tolist(), bone="Bip001-Toy", skyrim_bone=prn or "AnimObjectA",
                name=name, material=mat[0], rgb=list(mat[1]), rough=mat[2])


BIG_SKY = 80.0       # Skyrim units: props bigger than this (poles, crosses, pillories, beds) stay world props
SEG_SKY = 20.0       # ... and so does a prop whose vertices sit further than this (median) from every body bone


def anchor_of(sky_world, prn, mesh, scale):
    """the Skyrim bone the prop should ride (a retarget-mapped name), or None = world prop.
    Its Prn bone (or the nearest mapped ancestor) when that is a body bone; else (root-parented: yoke, armbinder, strap-on)
    the body bone whose whole length lies closest to the prop's vertices (median), unless the prop is big or far."""
    b = sky_world["bones"]; par = sky_world.get("parents"); bm = rt.bone_map()
    prn = prn if prn in b else NODE_ALIAS.get(prn, prn)   # WEAPON / SHIELD: an extra animated bone when the scene has the track
    i = b.index(prn) if prn in b else b.index("AnimObjectA")
    j = i
    while j is not None and j >= 0 and b[j] not in bm: j = par[j] if par else None
    if j is not None and j >= 0 and b[j] != "NPC COM [COM ]" and "Root" not in b[j]: return b[j]
    v = rt.MC.T @ (np.array(mesh["verts"]) / scale).T; v = v.T[::max(1, len(mesh["verts"]) // 300)]   # Skyrim units, prop space
    if (v.max(0) - v.min(0)).max() > BIG_SKY: return None
    R, P = sky_world["frames"][0]; w = v @ R[i].T + P[i]
    kids = {}
    for k, pk in enumerate(par or []):
        if pk >= 0 and b[k] in bm and b[pk] in bm: kids.setdefault(pk, k)
    best = (1e9, None)
    for n in bm:
        if n not in b or "Finger" in n or n == "NPC COM [COM ]": continue
        k = b.index(n); a0 = P[k]; a1 = P[kids[k]] if k in kids else P[k]; ab = a1 - a0; L2 = float(ab @ ab)
        t = np.clip((w - a0) @ ab / L2, 0, 1) if L2 > 1e-9 else np.zeros(len(w))
        d = float(np.median(np.linalg.norm(w - (a0 + t[:, None] * ab), axis=1)))
        if d < best[0]: best = (d, n)
    return best[1] if best[0] < SEG_SKY else None


def prop_track(sky_world, prn, anchor, raw, final, scale):
    """UE world (pos, quat) of the prop bone per frame. raw / final: the holder's SB clip right after retarget / after every
    pass. Anchored: the prop keeps its Skyrim offset from the anchor bone, applied to the SB bone (K = SB-vs-Skyrim bone
    frame, from the raw clip). World: Skyrim position x scale, moved with the holder's Bip001."""
    b = sky_world["bones"]; prn = prn if prn in b else NODE_ALIAS.get(prn, prn)
    i = b.index(prn) if prn in b else b.index("AnimObjectA"); F = min(len(final["frames"]), len(sky_world["frames"]))
    out = []
    if anchor:
        ia = b.index(anchor); t = rt.bone_map()[anchor]; it = final["names"].index(t)
        Rr0, _ = rt.world_mats(raw["parents"], raw["frames"][0]); Ra0 = rt.MC @ sky_world["frames"][0][0][ia] @ rt.MC
        K = Rr0[it].T @ Ra0
        for f in range(F):
            R, P = sky_world["frames"][f]; Ru = rt.MC @ R[i] @ rt.MC; Pu = scale * (rt.MC @ P[i])
            Rau = rt.MC @ R[ia] @ rt.MC; Pau = scale * (rt.MC @ P[ia]); Rs, Ps = rt.world_mats(final["parents"], final["frames"][f])
            V = Rs[it] @ K; out.append(((Ps[it] + V @ (Rau.T @ (Pu - Pau))).tolist(), list(rt.m2q(V @ Rau.T @ Ru))))
    else:
        ic = b.index("NPC COM [COM ]"); hb = final["names"].index("Bip001")
        off = np.median([rt.world_mats(final["parents"], final["frames"][f])[1][hb] - scale * (rt.MC @ sky_world["frames"][f][1][ic]) for f in range(0, F, 3)], axis=0)
        for f in range(F):
            R, P = sky_world["frames"][f]; out.append(((scale * (rt.MC @ P[i]) + off).tolist(), list(rt.m2q(rt.MC @ R[i] @ rt.MC))))
    out += [out[-1]] * (len(final["frames"]) - F)
    return out


def track_clip(track, fps, n=None):
    """clip json on the prop skeleton from a track; track None = hidden for n frames"""
    fr = [[([0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]), (p, q)] for p, q in track] if track else [[([0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]), (HIDE, [1.0, 0.0, 0.0, 0.0])]] * n
    return {"names": NAMES, "parents": PARENTS, "fps": fps, "frames": fr}


SWORD_LEN_CM = 140.0  # Eve's blade at its real 1.40 m. A 50 cm shrink via a root scale key came out paper-thin but still full
                      # length in game (each part scaled about its own bone, bone spacing not): don't scale this rig


def sword_clip(toy, mesh, sword_skel, pommel_z, full_len=140.0):
    """toy clip (prop skeleton) -> clip on Eve's sword skeleton: Weapon_Root follows the toy, flipped so the sword's pommel sits at
    the toy's inserted tip (max local z) and the blade runs back past the gripping hand; every other bone at rest; the whole rig
    scaled to SWORD_LEN_CM. The mesh is in component space and the root bone rests turned -90 deg about Y, so the root's world
    rotation is toy x flip x root rest (vertex world = root x inverse(root rest) x vertex)."""
    S = ue.load_skeleton(sword_skel); tip = max(v[2] for v in mesh["verts"]); k = SWORD_LEN_CM / full_len
    Rrest = rt.q2m(S["pose"][0][1]); flip = np.diag([1.0, -1.0, -1.0])
    off = np.array([0.0, 0.0, tip + k * pommel_z])     # scaled pommel (0,0,k*pz) -> flipped (0,0,-k*pz) + off = tip
    rest = [[list(p), list(q)] for p, q in S["pose"]]; frames = []
    for fr in toy["frames"]:
        p, q = fr[1]; Rt = rt.q2m(q); f = [list(x) for x in rest]
        f[0] = [list(np.array(p) + Rt @ off), list(rt.m2q(Rt @ flip @ Rrest))]; frames.append(f)
    out = {"names": S["names"], "parents": S["parents"], "fps": toy["fps"], "frames": frames}
    if abs(k - 1.0) > 1e-6: out["root_scale"] = k
    return out
