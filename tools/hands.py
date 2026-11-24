# hands.py: body models + contact passes (run after contact.py, on retargeted clip jsons).
#   source_contacts(sky_f, sky_o, kind) -> what each hand touches in the ORIGINAL Skyrim animation, per frame
#        (own body / partner body / shaft), measured with the Skyrim BodySlide bodies (tools/nif.py)
#   enforce(clips, contacts, mg)        -> the same touches in Stellar Blade: hand onto that body's skin / around the shaft
#   unclip(o, others)                   -> hands out of every body they sink into
#   lint(clips, contacts)               -> problems left after the passes (contact lost, hand inside, bodies overlapping)
# Bodies are rigid per dominant bone with a radial inside test per body part. Hands move by 2-bone arm IK (elbow keeps
# its bend plane, hand keeps its world rotation); deltas are dilated + smoothed over the looping clip.
# check: python tools/hands.py  (body models load + rest-pose sanity)
import sys, json
import numpy as np
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import retarget as rt, ue, contact as ct, nif, hkx, cfg

EXP = cfg.FMODEL
SB_BODY = {   # role -> (mesh exported with FModel, skeleton json). Tachy uses Eve's skeleton.
    "eve":   (EXP + "Art/Character/PC/CH_P_EVE_InnerSuit/CH_P_EVE_InnerSuit.psk", "CH_P_EVE_01_Skeleton.json"),
    "tachy": (EXP + "Art/Character/NPC/CH_NPC_TachyNPC/CH_NPC_TachyNPC_Body.pskx", "CH_P_EVE_01_Skeleton.json"),
    "adam":  (EXP + "CNSRepacked/5f46f011d0a6043f/Art/Character/NPC/CH_NPC_Adam_01/CH_NPC_Adam_01_Body.pskx", "CH_NPC_Adam_01_Skeleton.json"),
}
SB_HEAD = {    # real head meshes (Bip001-Head verts only): Adam holding her head, mouth on skin, ...
    "eve":   EXP + "Art/Character/PC/CH_P_EVE_Head/1110a.psk",
    "tachy": EXP + "Art/Character/NPC/CH_NPC_TachyNPC/CH_NPC_TachyNPC_Face_Jali.psk",
    "adam":  EXP + "Art/Character/NPC/CH_NPC_Adam_01/CH_NPC_Adam_01_Face_Jali.pskx",
}
SKY_HEAD = (np.array([0.0, 1.5, 124.5]), np.array([6.0, 7.0, 9.0]))   # ponytail: Skyrim heads are not in the body nif; ellipsoid
#   around the rest head (head bone z 120.3, magic node in front of the face), Skyrim units. Read femalehead.nif if it matters.
SKY = cfg.BODYSLIDE
SKY_BODY = {"f": (SKY + "femalebody_1.nif", ct.R0 + "xpmsse_skeleton_female.hkx"), "m": (SKY + "malebody_1.nif", ct.R0 + "xpmsse_skeleton.hkx")}
NOT_BODY = ("arm", "hand", "finger", "neck", "clavicle", "foot", "toe", "elbow", "brochi", "deltoid", "shoulder", "trape", "weapon", "shield", "magic")
MAXV = 400        # verts kept per body part (speed)
SKIN = 1.5        # cm kept between a hand and the skin it rests on
GRIP_R = 2.5      # palm distance from the shaft axis
TOUCH_SKY = 3.0   # Skyrim units: palm point this close to skin (or inside) = touching in the source
SHAFT_SKY = 14.0  # Skyrim units: her palm this close to the male crotch, not on her own body = on the shaft
SHAFT_REACH = (24.0, 7.0, -3.0)   # ... or up to 24 units out along a stroke, if within 7 of his midline and in front of him:
                                  # 14 alone dropped the grip near the tip ("hand doesn't stay on the penis going up", QA)
VULVA_SKY = 7.0   # Skyrim units: palm this close to a female crotch point = on her vulva (fingering, fisting, cupping)
VULVA_OUT = 1.5   # cm: the palm sits this far out of the SB vaginal entry
VULVA_PULL = 25.0 # cm: a vulva pull is a known point, not a skin pick, so it may be longer than MAX_PULL
MAX_PULL = 15.0  # cm: a touch pull longer than this is a wrong skin pick (one frame), dropped
UNCLIP_MAX = 4.0 # cm per unclip round: a hand deep inside (Skyrim pose in a thicker SB body) was shoved 15 cm x 3 rounds
                 # toward the shoulder, elbow swinging 35 cm/frame (Aggressive Blowjob). Slightly inside beats a flailing arm.
LOST_CM = 3.0     # lint: a source touch that ends further than this in SB is "lost"
_cache = {}


ALL_BODY_SKIP = ("weapon", "shield", "magic")   # full=True: arms, hands, neck and feet too (prop fit in score.py)


def make_body(local_by_bone, names, skip=NOT_BODY):
    body = []
    for i, v in local_by_bone.items():
        if len(v) < 30 or any(k in names[i].lower() for k in skip): continue
        v = np.asarray(v)[::max(1, len(v) // MAXV)]; c = v.mean(0); V = v - c; r = np.linalg.norm(V, axis=1); ok = r > 1e-6
        body.append((i, c, V[ok] / r[ok, None], r[ok]))
    return body


def sb_body(role, names=None, full=False):
    """body model of a role. names = the clip's bone list (slimmed clips): part indices are remapped to it by bone name.
    full=True keeps arms, hands, neck and feet (left out by default: the hand passes push hands out of the torso/legs)"""
    if names is not None:
        key = (role, tuple(names), full)
        if key not in _cache:
            whole = sb_body(role, full=full); at = {n: k for k, n in enumerate(names)}
            _cache[key] = dict(names=list(names), body=[(at[whole["names"][i]],) + tuple(rest) for i, *rest in whole["body"] if whole["names"][i] in at])
        return _cache[key]
    if full:
        if (role, "full") not in _cache:
            sb_body(role); _cache[(role, "full")] = dict(names=_cache[role]["names"], body=make_body(_cache[role + ":parts"], _cache[role]["names"], ALL_BODY_SKIP))
        return _cache[(role, "full")]
    if role not in _cache:
        mesh, sk = SB_BODY[role]; E = ue.load_skeleton(ct.R0 + sk); n = E["names"]; idx = {b: i for i, b in enumerate(n)}
        R, P = rt.world_mats(E["parents"], E["pose"]); pts, bn, _ = ue.read_psk_points(mesh); by = {}
        hp, hb, _ = ue.read_psk_points(SB_HEAD[role])
        pts = [p for p, b in zip(pts, bn) if b != "Bip001-Head"] + [p for p, b in zip(hp, hb) if b == "Bip001-Head"]
        bn = [b for b in bn if b != "Bip001-Head"] + [b for b in hb if b == "Bip001-Head"]
        main = [i for i, b in enumerate(n) if b.startswith("Bip001-") and "Finger" not in b and "Nub" not in b]
        for p, b in zip(pts, bn):      # verts on bones the skeleton json lacks (twist, hair...) -> nearest main joint
            i = idx.get(b)
            if i is None: i = main[int(np.argmin(np.linalg.norm(np.array([P[j] for j in main]) - np.array(p), axis=1)))]
            by.setdefault(i, []).append(p)
        _cache[role + ":parts"] = {i: (np.array(v) - P[i]) @ R[i] for i, v in by.items()}
        _cache[role] = dict(names=n, body=make_body(_cache[role + ":parts"], n))
    return _cache[role]


def sky_body(sex):
    if sex not in _cache:
        path, sk = SKY_BODY[sex]; S = hkx.skeleton(hkx.Pack(open(sk, "rb").read())); b = S["bones"]
        R, P = rt.world_mats(S["parents"], [(p, q) for p, q, _ in S["ref"]])
        loc = nif.on_skeleton(path, b, (R, P)); ih = b.index("NPC Head [Head]")
        g = np.arange(400) + 0.5; th = np.arccos(1 - 2 * g / 400); ph = np.pi * (1 + 5 ** 0.5) * g
        ell = SKY_HEAD[0] + SKY_HEAD[1] * np.c_[np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)]
        loc[ih] = (ell - P[ih]) @ R[ih]; d = dict(names=b, body=make_body(loc, b))
        # crotch point (front-low of the pelvis verts, midline) in pelvis space: where the schlong sits (m) / the vulva (f)
        ip = b.index("NPC Pelvis [Pelv]"); w = P[ip] + loc[ip] @ R[ip].T
        mid = w[np.abs(w[:, 0]) < 2.0]; low = mid[mid[:, 2] < np.percentile(mid[:, 2], 30)]
        front = low[low[:, 1] > np.percentile(low[:, 1], 90)].mean(0); d["crotch"] = (ip, R[ip].T @ (front - P[ip]))
        d["axes"] = (R[ip].T @ np.array([1.0, 0, 0]), R[ip].T @ np.array([0, 1.0, 0]))   # lateral, forward (pelvis space)
        _cache[sex] = d
    return _cache[sex]


def skin(R, P, p, body):
    """signed distance from world point p to the body's skin (< 0 inside) and the outward direction"""
    best = (1e9, None)
    for i, c, U, r in body:
        l = R[i].T @ (p - P[i]) - c; d = np.linalg.norm(l)
        if d < 1e-6: continue
        u = l / d; m = U @ u > 0.97
        if m.any() and d - r[m].max() < best[0]: best = (d - r[m].max(), R[i] @ u)
    return best


def hinge(o, side):
    """elbow hinge axis in upper-arm space, averaged over the clip weighted by bend (a near-straight arm has no plane)"""
    n = o["names"]; ua, fa, ha = (n.index("Bip001-%s-%s" % (side, x)) for x in ("UpperArm", "Forearm", "Hand")); acc = np.zeros(3)
    for fr in o["frames"]:
        R, P = rt.world_mats(o["parents"], fr); acc += R[ua].T @ np.cross(P[fa] - P[ua], P[ha] - P[fa])
    return acc / np.linalg.norm(acc) if np.linalg.norm(acc) > 1e-6 else None


def arm_ik(o, f, side, target, axis=None, elbow_push=None):
    """hand to target (world); elbow bends about its hinge axis (upper-arm space, see hinge) or else in its original
    plane, or toward elbow + elbow_push (out of a body); hand keeps its world rotation"""
    names, par, fr = o["names"], o["parents"], o["frames"][f]
    ua, fa, ha = (names.index("Bip001-%s-%s" % (side, x)) for x in ("UpperArm", "Forearm", "Hand"))
    R0, P0 = rt.world_mats(par, fr)
    l1, l2 = np.linalg.norm(P0[fa] - P0[ua]), np.linalg.norm(P0[ha] - P0[fa])
    k = P0[fa]
    dn = (target - P0[ua]) / max(np.linalg.norm(target - P0[ua]), 1e-6); bend = (k - P0[ua]) - np.dot(k - P0[ua], dn) * dn
    kp = None
    wb = float(np.clip((np.linalg.norm(bend) / l1 - 0.10) / 0.10, 0.0, 1.0))   # fades in 0.10-0.20 l1: an on/off threshold made the
    if elbow_push is not None and np.linalg.norm(elbow_push) > 0.05 and wb > 0:  # elbow hop ~5 cm/frame each loop (Missionary 3)
        # with the hand fixed the elbow can only swing about the shoulder-hand line: use just that sideways part of the push.
        # The whole push could cancel the bend and flip the elbow for a frame (69: 48 deg wrist jump)
        b = bend / np.linalg.norm(bend); side_ = np.cross(dn, b); kp = P0[fa] + side_ * np.dot(elbow_push, side_) * 3 * wb
    if kp is not None: k = kp
    elif axis is not None and np.linalg.norm(bend) < 0.15 * l1:
        # near-straight arm: its own elbow plane is noise, use the clip's average hinge. Not on bent arms: the average
        # can point the other way there and flipped the elbow ~100 deg/frame (Aggressive Blowjob, 2026-11-23)
        pole = np.cross(dn, R0[ua] @ axis)
        if np.linalg.norm(pole) > 1e-3: k = P0[ua] + pole
    el = ct.two_bone(P0[ua], k, target, l1, l2)
    fr[ua] = [fr[ua][0], list(rt.m2q(R0[par[ua]].T @ rt.align(P0[fa] - P0[ua], el - P0[ua]) @ R0[ua]))]
    R1, P1 = rt.world_mats(par, fr)
    fr[fa] = [fr[fa][0], list(rt.m2q(R1[par[fa]].T @ rt.align(P1[ha] - P1[fa], target - P1[fa]) @ R1[fa]))]
    R2, _ = rt.world_mats(par, fr)
    fr[ha] = [fr[ha][0], list(rt.m2q(R2[par[ha]].T @ R0[ha]))]


def settle(D, robust=False):
    """looping clip: keep each frame's biggest nearby correction (dilate), then smooth.
    robust (touch pulls): median over 7 frames instead of dilating, then smooth twice. Dilating spread a one-frame wrong
    skin pick (38 cm) over 5 frames: the arm swung out and back ("dancing arms", QA 2026-11-23)."""
    n = len(D); D = np.array(D); k = np.array([1, 2, 3, 2, 1.0]) / 9
    if robust:
        big = np.array([np.median([D[(f + j) % n] for j in range(-3, 4)], axis=0) for f in range(n)])
        big = np.array([sum(k[j] * big[(f + j - 2) % n] for j in range(5)) for f in range(n)])
    else:
        big = np.array([D[max(((f + j) % n for j in range(-2, 3)), key=lambda k: np.linalg.norm(D[k]))] for f in range(n)])
    return np.array([sum(k[j] * big[(f + j - 2) % n] for j in range(5)) for f in range(n)])


def apply_hands(o, deltas, robust=False, elbows=None):
    elbows = elbows or {}; F = len(o["frames"])
    for side in sorted(set(deltas) | set(elbows)):
        D = settle(deltas.get(side, np.zeros((F, 3))), robust); E = settle(elbows[side], robust) if side in elbows else None; ax = hinge(o, side)
        for f in range(F):
            e = None if E is None else E[f]
            if np.linalg.norm(D[f]) < 0.05 and (e is None or np.linalg.norm(e) < 0.05): continue
            _, P = rt.world_mats(o["parents"], o["frames"][f])
            arm_ik(o, f, side, P[o["names"].index("Bip001-%s-Hand" % side)] + D[f], ax, e)


def palm(o, P, side):
    n = o["names"]; return (P[n.index("Bip001-%s-Hand" % side)] + P[n.index("Bip001-%s-Finger2" % side)]) / 2


def shaft_target(p, mg, f):
    gb, gt = mg["names"].index("NPC-GenitalsBase"), mg["names"].index("NPC-Genitals06")
    _, Pg = rt.world_mats(mg["parents"], mg["frames"][f]); a, b = Pg[gb], Pg[gt]
    x = np.clip(np.dot(p - a, b - a) / np.dot(b - a, b - a), 0.15, 0.7); q = a + x * (b - a)
    ax = (b - a) / np.linalg.norm(b - a); rad = p - q; rad -= np.dot(rad, ax) * ax; rn = np.linalg.norm(rad)
    rad = rad / rn if rn > 1e-6 else np.cross(ax, [0, 0, 1.0])
    return q + rad * GRIP_R, rn


def body_of(t):
    """contact target -> the role whose body it is on (None for no touch / the shaft)"""
    return None if t in (None, "shaft") else t.split(":")[-1]


_vulva = {}
def vulva_target(c, f):
    """SB vaginal entry of clip c at frame f, VULVA_OUT cm out of the body (Tachy uses Eve's skeleton and entry)"""
    if "l" not in _vulva:
        E = ue.load_skeleton(ct.R0 + "CH_P_EVE_01_Skeleton.json"); ip = E["names"].index("Bip001-Pelvis")
        Rr, Pr = rt.world_mats(E["parents"], E["pose"]); ent, inner = ct.ENTRY["vaginal"]
        out = (ent - inner) / np.linalg.norm(ent - inner); _vulva["l"] = Rr[ip].T @ (ent + out * VULVA_OUT - Pr[ip])
    R, P = rt.world_mats(c["parents"], c["frames"][f]); ip = c["names"].index("Bip001-Pelvis")
    return P[ip] + R[ip] @ _vulva["l"]


# ------------------------------------------------------------------ source (Skyrim) contacts
def source_contacts(sky_f, sky_o, kind, free_shaft=False):
    """sky_*: retarget.source_world() of the female actor / the other actor -> {role: {side: [target|None per frame]}}
    free_shaft: no penetration in this scene (oral/none), so a hand may hold the shaft anywhere along a stroke"""
    actors = {"eve": ("f", sky_f)}
    if sky_o is not None: actors["adam" if kind == "MF" else "tachy"] = ("m" if kind == "MF" else "f", sky_o)
    F = min(len(w["frames"]) for _, w in actors.values()); out = {}
    for role, (_, w) in actors.items():
        b = w["bones"]; out[role] = {}
        for side in "LR":
            h, f2 = b.index("NPC %s Hand [%sHnd]" % (side, side)), b.index("NPC %s Finger20 [%sF20]" % (side, side)); tl = []
            for f in range(F):
                p = (w["frames"][f][1][h] + w["frames"][f][1][f2]) / 2; best = (TOUCH_SKY, None)
                for t, (sx, tw) in actors.items():
                    R, P = tw["frames"][f]; d, _ = skin(R, P, p, sky_body(sx)["body"])
                    if d < best[0]: best = (d, t)
                for t, (sx, tw) in actors.items():          # the specific spot beats "somewhere on her body"
                    if sx != "f": continue
                    ip, cl = sky_body("f")["crotch"]; R, P = tw["frames"][f]
                    if np.linalg.norm(p - (P[ip] + R[ip] @ cl)) < VULVA_SKY: best = (0, "vulva:" + t)
                if kind == "MF" and role == "eve" and best[1] != "eve" and not str(best[1]).startswith("vulva"):
                    ip, cl = sky_body("m")["crotch"]; lat, fwd = sky_body("m")["axes"]; R, P = sky_o["frames"][f]
                    l = R[ip].T @ (p - P[ip]) - cl; dist = np.linalg.norm(l)
                    if dist < SHAFT_SKY or (free_shaft and dist < SHAFT_REACH[0] and abs(l @ lat) < SHAFT_REACH[1] and l @ fwd > SHAFT_REACH[2]):
                        best = (0, "shaft")
                tl.append(best[1])
            out[role][side] = tl
    return out


def summary(contacts):
    s = []
    for role, sides in contacts.items():
        for side, tl in sides.items():
            c = {}
            for t in tl:
                if t: c[t] = c.get(t, 0) + 1
            if c: s.append("%s %s hand: %s" % (role, side, ", ".join("%s %d%%" % (t, 100 * k // len(tl)) for t, k in sorted(c.items(), key=lambda x: -x[1]))))
    return "; ".join(s) or "no hand contacts"


REACH_MIN, REACH_MAX = 3.0, 30.0   # cm: horizontal partner slide toward a vulva his hand can't reach


def reach_shift(clips, con, role, mg=None):
    """the partner's hand belongs on her vulva for much of a stage but his whole body stands too far away (Bound Fisting:
    shoulder 69 cm from it, arm 53 cm). Slide him (and the genital rig) horizontally by the median gap; only for stages
    without penetration, where nothing else places him. -> (clip, mg, cm moved)"""
    gaps = []
    for side, tl in con.get(role, {}).items():
        for f, t in enumerate(tl[:len(clips[role]["frames"])]):
            if t and t.startswith("vulva:"):
                _, P = rt.world_mats(clips[role]["parents"], clips[role]["frames"][f])
                gaps.append(vulva_target(clips[body_of(t)], f) - palm(clips[role], P, side))
    if len(gaps) < 0.3 * len(clips[role]["frames"]): return clips[role], mg, 0.0
    g = np.median(gaps, axis=0); g[2] = 0.0; n = np.linalg.norm(g)
    # ponytail: a standing partner whose shoulder is higher above her vulva than his arm is long (Bound Fisting S2/S3,
    # ~55 cm vs 53.5) still falls a few cm short: that needs a waist bend, not a slide. Add spine IK if QA still flags it.
    if n < REACH_MIN: return clips[role], mg, 0.0
    g *= min(1.0, REACH_MAX / n); hb = clips[role]["names"].index("Bip001"); pr = clips[role]["parents"][hb]
    def moved(k):
        o = json.loads(json.dumps(clips[role]))
        for fr in o["frames"]:
            R, _ = rt.world_mats(o["parents"], fr); fr[hb] = [list(np.array(fr[hb][0]) + (R[pr].T @ (k * g) if pr >= 0 else k * g)), fr[hb][1]]
        return o
    # never slide into her: the full gap put Eve's body inside Tachy's on every frame (Lesbian 2 S3, 24 cm)
    others = [(r, c) for r, c in clips.items() if r != role and r in SB_BODY]; base = sum(overlap(clips[role], role, c, r) for r, c in others)
    bdeep = max([overlap(clips[role], role, c, r, depth=True) for r, c in others] + [0.0])
    ok = lambda o2: sum(overlap(o2, role, c, r) for r, c in others) <= base + 0.05 and                     max([overlap(o2, role, c, r, depth=True) for r, c in others] + [0.0]) <= bdeep + 2.0   # nor deeper (Fisting S2 calf 18 cm)
    k = next((k for k in (1.0, 0.75, 0.5, 0.25) if ok(moved(k))), 0.0)
    if k * n < REACH_MIN: return clips[role], mg, 0.0
    g = g * k; o = moved(k)
    o = lean_to_reach(o, clips, con, role)
    if mg is not None:
        mg = json.loads(json.dumps(mg))
        for fr in mg["frames"]: fr[0] = [list(np.array(fr[0][0]) + g), fr[0][1]]
    return o, mg, float(np.linalg.norm(g))


LEAN_MAX = 25.0   # deg


def lean_to_reach(o, clips, con, role):
    """still too far after the slide (a standing Adam's shoulder higher above her vulva than his arm is long, Bound Fisting S3):
    lean his upper body forward at Spine1, one constant angle for the stage, until the shoulder is within 95% of the arm"""
    nm = o["names"]
    if "Bip001-Spine1" not in nm: return o
    sp = nm.index("Bip001-Spine1"); need = []
    for side, tl in con.get(role, {}).items():
        ua, fa, ha = (nm.index("Bip001-%s-%s" % (side, x)) for x in ("UpperArm", "Forearm", "Hand"))
        for f, t in enumerate(tl[:len(o["frames"])]):
            if not (t and t.startswith("vulva:")): continue
            _, P = rt.world_mats(o["parents"], o["frames"][f])
            v = vulva_target(clips[body_of(t)], f) - (palm(o, P, side) - P[ha])      # the IK places the WRIST: its target
            L = 0.97 * (np.linalg.norm(P[fa] - P[ua]) + np.linalg.norm(P[ha] - P[fa]))
            need.append((P[ua] - P[sp], v - P[sp], L))
    if not need: return o
    a = np.median([x[0] for x in need], axis=0); b = np.median([x[1] for x in need], axis=0); L = float(np.median([x[2] for x in need]))
    if np.linalg.norm(b - a) <= L: return o
    best = 0.0
    for deg in np.arange(1.0, LEAN_MAX + 0.1, 1.0):       # rotate the shoulder about the spine toward the vulva, smallest that reaches
        Rd = rt.align(a, a + (b - a) * 1e-3); ax = np.cross(a, b - a); ax /= np.linalg.norm(ax); th = np.radians(deg)
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]]); Rd = np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K
        best = deg
        if np.linalg.norm(b - Rd @ a) <= L: break
    o = json.loads(json.dumps(o))
    for fr in o["frames"]:
        R, _ = rt.world_mats(o["parents"], fr); fr[sp] = [fr[sp][0], list(rt.m2q(R[o["parents"][sp]].T @ Rd @ R[sp]))]
    return o


# ------------------------------------------------------------------ Stellar Blade passes
def enforce(clips, contacts, mg=None):
    """clips {role: clip}; contacts from source_contacts. Each touching frame pulls the hand onto that target."""
    clips = {r: json.loads(json.dumps(o)) for r, o in clips.items()}
    for role, sides in contacts.items():
        o = clips[role]; deltas = {}
        for side, tl in sides.items():
            flatten(o, side, tl, clips)            # turn first (about the wrist), then move the flat hand onto the skin
            D = []
            for f in range(len(o["frames"])):
                t = tl[f] if f < len(tl) else None
                if t is None or (t == "shaft" and mg is None): D.append(np.zeros(3)); continue
                _, P = rt.world_mats(o["parents"], o["frames"][f]); p = palm(o, P, side)
                if t == "shaft": D.append(shaft_target(p, mg, f)[0] - p); continue
                if t.startswith("vulva:"):
                    dv = vulva_target(clips[body_of(t)], f) - p; D.append(dv if np.linalg.norm(dv) <= VULVA_PULL else np.zeros(3)); continue
                Rt, Pt = rt.world_mats(clips[t]["parents"], clips[t]["frames"][f]); d, u = skin(Rt, Pt, p, sb_body(t, clips[t]["names"])["body"])
                dv = u * (SKIN - d) if u is not None else np.zeros(3)
                wr = P[o["names"].index("Bip001-%s-Hand" % side)]
                for _ in range(2):                 # curved skin: the wrist must end outside too, not just the palm
                    dw, uw = skin(Rt, Pt, wr + dv, sb_body(t, clips[t]["names"])["body"])
                    if uw is None or dw >= SKIN: break
                    dv = dv + uw * (SKIN - dw)
                D.append(dv if np.linalg.norm(dv) <= MAX_PULL else np.zeros(3))   # bigger = wrong body part picked
            if any(np.linalg.norm(x) > 0.05 for x in D): deltas[side] = D
        apply_hands(o, deltas, robust=True)
    return clips


def flatten(o, side, tl, clips):
    """lay the hand on the skin it touches: fingers turned into the skin's tangent plane (the source rotation pointed
    them into the thicker SB body). Weight is smoothed over the loop so touch on/off frames blend."""
    n = o["names"]; h, f2 = n.index("Bip001-%s-Hand" % side), n.index("Bip001-%s-Finger2" % side); F = len(o["frames"])
    on = [1.0 if f < len(tl) and tl[f] not in (None, "shaft") else 0.0 for f in range(F)]
    # touch on/off ramps over ~0.5 s: the old 5-frame ramp turned the hand ~20 deg/frame (2026-11-23)
    k = np.r_[np.arange(1, 9), np.arange(7, 0, -1)].astype(float); k /= k.sum(); r = len(k) // 2
    w = [sum(k[j] * on[(f + j - r) % F] for j in range(len(k))) for f in range(F)]
    U = [None] * F
    for f in range(F):
        if w[f] < 0.05: continue
        t = body_of(next((tl[(f + j) % F] for j in (0, 1, -1, 2, -2) if (f + j) % F < len(tl) and tl[(f + j) % F] not in (None, "shaft")), None))
        if t is None: continue
        _, P = rt.world_mats(o["parents"], o["frames"][f]); Rt, Pt = rt.world_mats(clips[t]["parents"], clips[t]["frames"][f])
        U[f] = skin(Rt, Pt, palm(o, P, side), sb_body(t, clips[t]["names"])["body"])[1]
    # the nearest body part can switch every frame (spine1 <-> spine2, breast <-> ribs) and its normal with it: a raw
    # per-frame normal made the wrist twitch ~17 deg/frame ("scratching" hands, QA 2026-11-23). Smooth it over the loop.
    SM, U0 = 7, list(U)
    for f in range(F):
        if U0[f] is None: continue
        acc = sum((U0[(f + j) % F] for j in range(-SM, SM + 1) if U0[(f + j) % F] is not None), np.zeros(3))
        U[f] = acc / np.linalg.norm(acc) if np.linalg.norm(acc) > 1e-6 else None
    # the full turn into the tangent plane, per frame, as a world quaternion
    Q, Rs = [None] * F, [None] * F
    for f in range(F):
        u = U[f]; Rs[f] = rt.world_mats(o["parents"], o["frames"][f])
        if u is None: continue
        R, P = Rs[f]; d = P[f2] - P[h]; d /= np.linalg.norm(d); tan = d - np.dot(d, u) * u
        if np.linalg.norm(tan) > 1e-6: Q[f] = np.array(rt.m2q(rt.align(d, tan / np.linalg.norm(tan))))
    # that turn follows the skin under the hand every frame (~80 deg, swinging +-20 deg per thrust = "scratching" hands,
    # QA 2026-11-23): average it over ~0.7 s, so the hand keeps its source motion plus a steady offset
    ref = next((q for q in Q if q is not None), None)
    for f in range(F):
        if w[f] < 0.05 or ref is None: continue
        acc = np.zeros(4)
        for j in range(-TURN_SM, TURN_SM + 1):
            q = Q[(f + j) % F]
            if q is not None: acc += q if np.dot(q, ref) >= 0 else -q
        if np.linalg.norm(acc) < 1e-6: continue
        q = acc / np.linalg.norm(acc); q = q if q[0] >= 0 else -q
        q = _slerp(np.array([1.0, 0, 0, 0]), q, w[f])
        R, _ = Rs[f]; fr = o["frames"][f]
        fr[h] = [fr[h][0], list(rt.m2q(R[o["parents"][h]].T @ rt.q2m(q) @ R[h]))]


TURN_SM = 10   # frames each side (30 fps)


def _slerp(a, b, t):
    c = float(np.clip(np.dot(a, b), -1, 1)); th = np.arccos(c)
    if th < 1e-4: return b
    return (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / np.sin(th)


def unclip(o, others, rounds=3, contacts=None):   # ponytail: 5 rounds jittered more and still left tied elbows in her back (Bound Doggy)
    """push o's hands out of every body in others = [(role, clip)] (include o itself as its own role).
    contacts = this role's {side: [target per frame]}: on a touching frame only the wrist is checked against the touched
    body, so fingers resting on it don't lift the whole hand off."""
    o = json.loads(json.dumps(o)); n = o["names"]
    cap = lambda v: v * min(1.0, UNCLIP_MAX / np.linalg.norm(v)) if np.linalg.norm(v) > 0 else v
    def push(p, Rb, Pb, role, c, best):
        d, u = skin(Rb, Pb, p, sb_body(role, c["names"])["body"])
        return u * (SKIN - d) if u is not None and d < SKIN and SKIN - d > np.linalg.norm(best) else best
    for _ in range(rounds):
        deltas, elbows = {}, {}
        for side in "LR":
            probes = [n.index("Bip001-%s-%s" % (side, x)) for x in ("Hand", "Finger2", "Finger21")]; D, E = [], []
            fa = n.index("Bip001-%s-Forearm" % side); tl = (contacts or {}).get(side, [])
            for f in range(len(o["frames"])):
                _, P = rt.world_mats(o["parents"], o["frames"][f]); best = np.zeros(3); eb = np.zeros(3)
                fore = (P[fa] + P[probes[0]]) / 2
                for role, c in others:
                    Rb, Pb = rt.world_mats(c["parents"], c["frames"][f])
                    eb = push(P[fa], Rb, Pb, role, c, eb)      # elbow: bend it out (forearms through her own body, QA 362/368/372)
                    t = tl[f] if f < len(tl) else None
                    # a hand on her vulva (fingering/fisting) or gripping the shaft at his crotch is SUPPOSED to be there:
                    # pushing it out undid the touch (QA 2026-11-23). On plain skin only the wrist may not sink.
                    if t is not None and ((t.startswith("vulva:") and body_of(t) == role) or (t == "shaft" and role == "adam")): continue
                    fb = push(fore, Rb, Pb, role, c, np.zeros(3))   # mid-forearm: moves hand and elbow together
                    if 2 * np.linalg.norm(fb) > np.linalg.norm(best): best = 2 * fb   # hand moves twice as far as mid-forearm
                    if np.linalg.norm(fb) > np.linalg.norm(eb): eb = fb
                    for i in (probes[:1] if t is not None and (body_of(t) == role or t == "shaft") else probes):
                        best = push(P[i], Rb, Pb, role, c, best)
                t = tl[f] if f < len(tl) else None
                if t is not None and (t == "shaft" or t.startswith("vulva:")): best = np.zeros(3)   # never pushed off that spot,
                D.append(cap(best)); E.append(cap(eb))                                            # not even by her own body
            if any(t is not None and (t == "shaft" or t.startswith("vulva:")) for t in tl):        # and neighbours don't bleed in
                D = [np.zeros(3) if f < len(tl) and tl[f] is not None and (tl[f] == "shaft" or tl[f].startswith("vulva:")) else d
                     for f, d in enumerate(settle(D, robust=True))]
            if max(np.linalg.norm(x) for x in D) > 0.05: deltas[side] = D
            if max(np.linalg.norm(x) for x in E) > 0.05: elbows[side] = E
        if not deltas and not elbows: break
        apply_hands(o, deltas, robust=True, elbows=elbows)   # robust: dilate spread one-frame deep picks (hand jumped ~12 cm/frame)
    return o


def overlap(a, ra, b, rb, step=4, depth=False):
    """share of sampled frames where a's core bones sit > 3 cm inside b's body, or b's inside a's (depth=True: the deepest cm)"""
    hit = n = 0; deep = 0.0
    for f in range(0, min(len(a["frames"]), len(b["frames"])), step):
        Ra, Pa = rt.world_mats(a["parents"], a["frames"][f]); Rb, Pb = rt.world_mats(b["parents"], b["frames"][f]); n += 1
        ds = [skin(Rb, Pb, Pa[a["names"].index(x)], sb_body(rb, b["names"])["body"])[0] for x in OVERLAP_BONES if x in a["names"]] +              [skin(Ra, Pa, Pb[b["names"].index(x)], sb_body(ra, a["names"])["body"])[0] for x in OVERLAP_BONES if x in b["names"]]
        hit += min(ds) < -3.0; deep = max(deep, -min(ds))
    return deep if depth else hit / max(n, 1)


OVERLAP_BONES = ("Bip001-Pelvis", "Bip001-Spine1", "Bip001-Spine2", "Bip001-Head", "Bip001-L-Thigh", "Bip001-R-Thigh", "Bip001-L-Calf", "Bip001-R-Calf")


LINT_INSIDE_CM = 9.0   # hand inside a body: QA (2026-11-23) marked scenes Ready with hands up to ~9 cm in
LINT_ARM_CM = 5.0      # elbow / mid-forearm inside a body (QA: "arms clipping through her body")
LINT_KNEE_CM = 5.0     # knee / mid-thigh inside another body
LINT_TWIST_DEG = 30.0  # wrist turning faster than this per frame (QA: "hand twisting", "weird wrist movement")


def lint(clips, contacts, mg=None, step=2):
    """-> list of problems still visible after all passes. Tuned against QA pass 1: plain "hand loses its touch on her
    body" fired at 100% in scenes marked Ready, so only vulva / shaft touches are linted; hands inside only from 9 cm."""
    issues = []; roles = list(clips)
    for role, sides in contacts.items():
        o = clips[role]
        for side, tl in sides.items():
            lost, n = 0, 0
            for f in range(0, min(len(tl), len(o["frames"])), step):
                t = tl[f]
                if t is None or (t == "shaft" and mg is None) or not (t == "shaft" or t.startswith("vulva:")): continue
                _, P = rt.world_mats(o["parents"], o["frames"][f]); p = palm(o, P, side); n += 1
                if t == "shaft": d = shaft_target(p, mg, f)[1] - GRIP_R
                elif t.startswith("vulva:"): d = np.linalg.norm(vulva_target(clips[body_of(t)], f) - p)
                else:   # wrist or palm on the skin both count as touching
                    Rt, Pt = rt.world_mats(clips[t]["parents"], clips[t]["frames"][f])
                    d = min(skin(Rt, Pt, x, sb_body(t, clips[t]["names"])["body"])[0] for x in (p, P[o["names"].index("Bip001-%s-Hand" % side)]))
                lost += d > LOST_CM
            if n and lost / n > 0.2: issues.append("%s %s hand loses its touch (%s) in %d%% of frames" % (role, side, max(set(t for t in tl if t), key=tl.count), 100 * lost // n))
    for a in roles:
        o = clips[a]; probes = [(s, o["names"].index("Bip001-%s-%s" % (s, x))) for s in "LR" for x in ("Hand", "Finger2")]
        for b in roles:
            deep = 0.0
            for f in range(0, len(o["frames"]), step * 2):
                _, P = rt.world_mats(o["parents"], o["frames"][f]); Rb, Pb = rt.world_mats(clips[b]["parents"], clips[b]["frames"][f])
                touch = {s: contacts.get(a, {}).get(s, [None] * (f + 1))[f] if f < len(contacts.get(a, {}).get(s, [])) else None for s in "LR"}
                use = [i for s, i in probes if not (body_of(touch[s]) == b and "Finger" in o["names"][i])]   # fingers resting on what they touch: fine
                deep = max([deep] + [-skin(Rb, Pb, P[i], sb_body(b, clips[b]["names"])["body"])[0] for i in use])
            if deep > LINT_INSIDE_CM: issues.append("%s hand %.0f cm inside %s" % (a, deep, "own body" if a == b else b))
            arm = knee = 0.0
            for f in range(0, len(o["frames"]), step * 2):
                _, P = rt.world_mats(o["parents"], o["frames"][f]); Rb, Pb = rt.world_mats(clips[b]["parents"], clips[b]["frames"][f]); nm = o["names"]
                for s_ in "LR":
                    fa, ha = nm.index("Bip001-%s-Forearm" % s_), nm.index("Bip001-%s-Hand" % s_)
                    arm = max([arm] + [-skin(Rb, Pb, x, sb_body(b, clips[b]["names"])["body"])[0] for x in (P[fa], (P[fa] + P[ha]) / 2)])
                    if a != b and "Bip001-%s-Calf" % s_ in nm:
                        th, ca = nm.index("Bip001-%s-Thigh" % s_), nm.index("Bip001-%s-Calf" % s_)
                        knee = max([knee] + [-skin(Rb, Pb, x, sb_body(b, clips[b]["names"])["body"])[0] for x in (P[ca], (P[th] + P[ca]) / 2)])
            if arm > LINT_ARM_CM: issues.append("%s arm %.0f cm inside %s" % (a, arm, "own body" if a == b else b))
            if knee > LINT_KNEE_CM: issues.append("%s knee %.0f cm inside %s" % (a, knee, b))
            if a == b: continue
            hit = 0; n = 0
            idx = [o["names"].index(x) for x in OVERLAP_BONES if x in o["names"]]
            for f in range(0, len(o["frames"]), step * 2):
                _, P = rt.world_mats(o["parents"], o["frames"][f]); Rb, Pb = rt.world_mats(clips[b]["parents"], clips[b]["frames"][f]); n += 1
                hit += any(skin(Rb, Pb, P[i], sb_body(b, clips[b]["names"])["body"])[0] < -3.0 for i in idx)
            if n and hit / n > 0.2: issues.append("%s body overlaps %s in %d%% of frames" % (a, b, 100 * hit // n))
    for a in roles:                                   # wrist turning too fast (frame to frame, forearm-relative)
        o = clips[a]; nm = o["names"]
        for s_ in "LR":
            fa, ha = nm.index("Bip001-%s-Forearm" % s_), nm.index("Bip001-%s-Hand" % s_); prev = None; worst = 0.0
            for fr in o["frames"]:
                R, _ = rt.world_mats(o["parents"], fr); loc = R[fa].T @ R[ha]
                if prev is not None: worst = max(worst, np.degrees(np.arccos(np.clip((np.trace(prev.T @ loc) - 1) / 2, -1, 1))))
                prev = loc
            if worst > LINT_TWIST_DEG: issues.append("%s %s wrist turns %.0f deg in one frame" % (a, s_, worst))
    return issues


if __name__ == "__main__":
    for r in SB_BODY: print(r, "parts", len(sb_body(r)["body"]))
    for s in SKY_BODY: print("skyrim", s, "parts", len(sky_body(s)["body"]), sky_body(s).get("crotch"))
    E = ue.load_skeleton(ct.R0 + "CH_P_EVE_01_Skeleton.json"); R, P = rt.world_mats(E["parents"], E["pose"])
    d, _ = skin(R, P, P[E["names"].index("Bip001-Pelvis")], sb_body("eve")["body"]); assert d < 0, "pelvis bone must be inside the body"
    print("ok: pelvis bone %.1f cm inside Eve's skin" % -d)


def body_bones(role):
    """bone names the role's body model hangs on: slimmed clips must keep them (they are rigid to their parents anyway)"""
    full = sb_body(role); return {full["names"][i] for i, *_ in full["body"]}
