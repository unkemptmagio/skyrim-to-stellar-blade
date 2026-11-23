# contact.py <eve.json> <adam.json> <mg.json> <out_adam.json> <out_mg.json> [--target anal|vaginal] [--report]
# Per frame: shift Adam + genital rig so the genital base sits on Eve's entry axis (keeping the source thrust rhythm,
# depth clamped), then aim NPC-GenitalsBase so the shaft runs along the axis through the entry point.
# Entry points measured on CH_P_EVE_InnerSuit (rest pose, UE cm), expressed in Eve's Bip001-Pelvis frame.
# Adam's hips move (Bip001) and his legs are re-solved with 2-bone IK, so knees/feet stay planted.
import sys, json
import numpy as np
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import retarget as rt, ue

R0 = __file__.replace("\\", "/").rsplit("/", 2)[0] + "/skeletons/"
ENTRY = {  # rest-pose world points (UE cm): entry on the skin, and a point inside along the canal
    "anal":    (np.array([-5.0, 0.0, 87.5]), np.array([1.5, 0.0, 99.0])),
    "vaginal": (np.array([-0.5, 0.0, 87.5]), np.array([2.5, 0.0, 100.0])),
    "oral":    (np.array([9.0, 0.0, 155.1]), np.array([1.0, 0.0, 154.5])),   # lips measured on the in-game head (CH_P_EVE_Head/1110a)
}
BONE = {"anal": "Bip001-Pelvis", "vaginal": "Bip001-Pelvis", "oral": "Bip001-Head"}
DEPTH = {"anal": (0.30, 0.85), "vaginal": (0.30, 0.85), "oral": (0.55, 0.95)}   # base-to-entry distance / shaft length, deepest / shallowest
ADAM_MOUTH = np.array([11.2, 0.0, 162.3])   # lips measured on CH_NPC_Adam_01_Face_Jali, rest UE cm


def two_bone(h, k, f, l1, l2, fallback=None):
    """new knee position for hip h and foot f, bending in the plane of the original knee k"""
    d = f - h; dl = np.linalg.norm(d); dl = min(max(dl, abs(l1 - l2) + 0.5), (l1 + l2) * 0.999); dn = d / np.linalg.norm(d)   # too close: x blew up
    pole = (k - h) - np.dot(k - h, dn) * dn
    if np.linalg.norm(pole) < 1e-3:              # straight limb: no bend plane -> the caller's knee direction (foot->toe), else UE +X
        for ax in ([fallback] if fallback is not None else []) + [np.array([1.0, 0, 0]), np.array([0, 1.0, 0])]:
            pole = np.asarray(ax, float) - np.dot(ax, dn) * dn
            if np.linalg.norm(pole) > 1e-3: break
    pole = pole / np.linalg.norm(pole)
    x = (l1 * l1 - l2 * l2 + dl * dl) / (2 * dl); y = np.sqrt(max(l1 * l1 - x * x, 0.0))
    return h + dn * x + pole * y


def shift_hips_keep_feet(o, f, delta):  # also keeps hands
    names, par = o["names"], o["parents"]; fr = o["frames"][f]
    R0w, P0w = rt.world_mats(par, fr)                                   # before
    hb = names.index("Bip001"); pr = par[hb]
    p, q = fr[hb]; fr[hb] = [list(np.array(p) + R0w[pr].T @ delta), q]
    # legs keep the feet planted, arms keep the hands where the source put them (e.g. on her hips)
    for sd, chain in [(s_, c_) for s_ in "LR" for c_ in (("Thigh", "Calf", "Foot"), ("UpperArm", "Forearm", "Hand"))]:
        th, ca, fo = (names.index("Bip001-%s-%s" % (sd, n)) for n in chain)
        R1w, P1w = rt.world_mats(par, fr)                               # hips moved, legs not yet fixed
        h, k, ft = P1w[th], P0w[ca], P0w[fo]
        if chain[0] == "UpperArm": k = k + (h - P0w[th])   # bend plane from the elbow carried with the shoulder: the old elbow
        #   against the shifted shoulder lay near the arm line and swung the elbow ~8 cm/frame (Aggressive Missionary, 2026-11-23)
        l1, l2 = np.linalg.norm(P0w[ca] - P0w[th]), np.linalg.norm(P0w[fo] - P0w[ca])
        kn = two_bone(h, k, ft, l1, l2)
        Rth = rt.align(P1w[ca] - h, kn - h) @ R1w[th]                    # thigh aims at the new knee
        fr[th] = [fr[th][0], list(rt.m2q(R1w[par[th]].T @ Rth))]
        R2w, P2w = rt.world_mats(par, fr)
        Rca = rt.align(P2w[fo] - P2w[ca], ft - P2w[ca]) @ R2w[ca]        # calf aims at the original foot
        fr[ca] = [fr[ca][0], list(rt.m2q(R2w[par[ca]].T @ Rca))]
        R3w, P3w = rt.world_mats(par, fr)
        fr[fo] = [fr[fo][0], list(rt.m2q(R3w[par[fo]].T @ R0w[fo]))]     # foot keeps its world rotation


def run(eve, adam, mg, target="anal"):
    E = ue.load_skeleton(R0 + "CH_P_EVE_01_Skeleton.json")
    ip = E["names"].index(BONE[target]); ipc = eve["names"].index(BONE[target])      # skeleton index (rest) / clip index
    Rr, Pr = rt.world_mats(E["parents"], E["pose"])
    ent, inner = ENTRY[target]; DEEP, SHALLOW = DEPTH[target]
    ent_l = Rr[ip].T @ (ent - Pr[ip]); in_l = Rr[ip].T @ (inner - Pr[ip])
    gn = mg["names"]; gb, gt = gn.index("NPC-GenitalsBase"), gn.index("NPC-Genitals06")
    frames = len(eve["frames"])
    T, A, B, U, L = [], [], [], [], []
    for f in range(frames):
        R, P = rt.world_mats(eve["parents"], eve["frames"][f])
        t = P[ipc] + R[ipc] @ ent_l; a = R[ipc] @ (in_l - ent_l); a /= np.linalg.norm(a)
        Rg, Pg = rt.world_mats(mg["parents"], mg["frames"][f])
        T.append(t); A.append(a); B.append(Pg[gb]); L.append(np.linalg.norm(Pg[gt] - Pg[gb]))
    L = float(np.mean(L))
    s = np.array([np.dot(B[f] - T[f], A[f]) for f in range(frames)])      # < 0: base is outside, behind the entry
    d = -s                                                               # source base-to-entry distance per frame
    lo, hi = DEEP * L, SHALLOW * L
    amp = d.max() - d.min()
    k = min(1.0, (hi - lo) / amp) if amp > 1e-6 else 1.0                 # keep the rhythm, clamp the range
    dn = lo + (d - d.min()) * k
    out_a = json.loads(json.dumps(adam)); out_g = json.loads(json.dumps(mg))
    deltas = []
    for f in range(frames):
        Bn = T[f] - A[f] * dn[f]; delta = Bn - B[f]; deltas.append(delta)
        # genital rig: shift its root (it only follows the pelvis)
        p, q = out_g["frames"][f][0]; out_g["frames"][f][0] = [list(np.array(p) + delta), q]
        # Adam: shift the hips (Bip001), then 2-bone IK so knees/feet stay where the source put them
        shift_hips_keep_feet(out_a, f, delta)
        # aim the shaft along the axis
        Rg, Pg = rt.world_mats(out_g["parents"], out_g["frames"][f])
        u = Pg[gt] - Pg[gb]; Rw = rt.align(u, A[f]) @ Rg[gb]
        par = out_g["parents"][gb]
        lq = rt.m2q(Rg[par].T @ Rw)
        out_g["frames"][f][gb] = [out_g["frames"][f][gb][0], list(lq)]
    deltas = np.array(deltas)
    rep = dict(shaft_cm=round(L, 1), depth_cm=(round(L - dn.max(), 1), round(L - dn.min(), 1)), rhythm_scale=round(k, 2),
               shift_mean_cm=np.round(deltas.mean(0), 1).tolist(), knee_slide_cm=round(float(np.linalg.norm(deltas - deltas.mean(0), axis=1).max()), 1))
    return out_a, out_g, rep


def aim(eve, mg, target, frames):
    """re-aim the shaft through the entry (or mouth) on the given frames, base where it is: stage blends mix two stages'
    hips and rotations, so the shaft drifted out of / through the body for 0.3-1.2 s at every stage change"""
    E = ue.load_skeleton(R0 + "CH_P_EVE_01_Skeleton.json"); ip = E["names"].index(BONE[target]); ipc = eve["names"].index(BONE[target])
    Rr, Pr = rt.world_mats(E["parents"], E["pose"]); _, inner = ENTRY[target]; in_l = Rr[ip].T @ (inner - Pr[ip])
    gb, gt = mg["names"].index("NPC-GenitalsBase"), mg["names"].index("NPC-Genitals06"); par = mg["parents"][gb]
    for f in frames:
        R, P = rt.world_mats(eve["parents"], eve["frames"][f]); goal = P[ipc] + R[ipc] @ in_l
        Rg, Pg = rt.world_mats(mg["parents"], mg["frames"][f])
        Rw = rt.align(Pg[gt] - Pg[gb], goal - Pg[gb]) @ Rg[gb]
        mg["frames"][f][gb] = [mg["frames"][f][gb][0], list(rt.m2q(Rg[par].T @ Rw))]


def check(eve, mg, target="anal"):
    """distance from the entry point to the shaft line, per frame (cm)"""
    E = ue.load_skeleton(R0 + "CH_P_EVE_01_Skeleton.json"); ip = E["names"].index(BONE[target])
    Rr, Pr = rt.world_mats(E["parents"], E["pose"]); ent, _ = ENTRY[target]; ent_l = Rr[ip].T @ (ent - Pr[ip])
    gb, gt = mg["names"].index("NPC-GenitalsBase"), mg["names"].index("NPC-Genitals06"); out = []
    for f in range(len(eve["frames"])):
        R, P = rt.world_mats(eve["parents"], eve["frames"][f]); Rg, Pg = rt.world_mats(mg["parents"], mg["frames"][f])
        ipc = eve["names"].index(BONE[target]); t = P[ipc] + R[ipc] @ ent_l; a, b = Pg[gb], Pg[gt]
        x = np.clip(np.dot(t - a, b - a) / np.dot(b - a, b - a), 0, 1); out.append(float(np.linalg.norm(t - (a + x * (b - a)))))
    return out


ORAL_DROP_MAX = 15.0   # cm: a standing Adam lowers his hips (bends his knees) at most this much toward a kneeling mouth
ORAL_BELOW_OK = 7.0    # cm: mouth this far below the shaft base is fine (shaft ~25 deg down)
ORAL_STANDING = 60.0   # cm: Adam's pelvis above the floor = standing (lying/sitting partners are never lowered)
ORAL_HEAD_MAX = 40.0   # deg: her head turns at most this much to face along the shaft


def oral(eve, mg, adam=None):
    """Blowjob: Eve slides along the floor by ONE horizontal offset so her mouth reaches the shaft, her head turns so her
    mouth faces along it, then the shaft is aimed through her mouth every frame.
    A kneeling SB Eve's mouth sat 15-20 cm below a standing Adam's crotch, so the shaft went into her mouth from above at
    ~90 deg (QA 2026-11-23, Bound/Aggressive Blowjob): a standing Adam now bends his knees to lower his hips (feet and
    hands stay), up to ORAL_DROP_MAX. -> (eve, mg, report) or (eve, mg, report, adam) when adam is given"""
    E = ue.load_skeleton(R0 + "CH_P_EVE_01_Skeleton.json"); n = E["names"]; ihs = n.index("Bip001-Head")
    Rr, Pr = rt.world_mats(E["parents"], E["pose"]); ml = Rr[ihs].T @ (ENTRY["oral"][0] - Pr[ihs])
    ih, hb = eve["names"].index("Bip001-Head"), eve["names"].index("Bip001")          # clip indices
    gb, gt = mg["names"].index("NPC-GenitalsBase"), mg["names"].index("NPC-Genitals06"); F = len(eve["frames"])
    mouth = lambda o, f: (lambda R, P: P[ih] + R[ih] @ ml)(*rt.world_mats(o["parents"], o["frames"][f]))
    drop = 0.0
    if adam is not None:
        ap = adam["names"].index("Bip001-Pelvis")
        if np.median([rt.world_mats(adam["parents"], fr)[1][ap][2] for fr in adam["frames"][::5]]) > ORAL_STANDING:
            v = np.median([mouth(eve, f)[2] - rt.world_mats(mg["parents"], mg["frames"][f])[1][gb][2] for f in range(0, F, 3)])
            drop = float(np.clip(-v - ORAL_BELOW_OK, 0.0, ORAL_DROP_MAX))
        if drop > 0.5:
            adam = json.loads(json.dumps(adam)); mg = json.loads(json.dumps(mg)); dv = np.array([0.0, 0.0, -drop])
            for f in range(F):
                shift_hips_keep_feet(adam, f, dv); p, q = mg["frames"][f][0]; mg["frames"][f][0] = [list(np.array(p) + dv), q]
    G = [rt.world_mats(mg["parents"], mg["frames"][f]) for f in range(F)]
    L = float(np.linalg.norm(G[0][1][gt] - G[0][1][gb])); want = 0.75 * L      # mouth this far from the base = tip 25% inside
    il = Rr[ihs].T @ (ENTRY["oral"][1] - Pr[ihs])                              # a point inside the mouth: the mouth axis
    D = []
    for f in range(F):                               # horizontal move that puts her mouth `want` from the base (height is kept)
        m = mouth(eve, f); a = G[f][1][gb]; h = m - a; v = h[2]; h[2] = 0.0; hd = np.linalg.norm(h)
        wh = np.sqrt(max(want * want - v * v, 0.0)); D.append(h / (hd or 1.0) * (wh - hd))
    c = np.median(D, axis=0); c[2] = 0.0                                  # her knees stay on the floor
    out_e = json.loads(json.dumps(eve)); out_g = json.loads(json.dumps(mg))
    R0w, _ = rt.world_mats(out_e["parents"], out_e["frames"][0]); pr = out_e["parents"][hb]
    short = []
    for f in range(F):
        p, q = out_e["frames"][f][hb]; Rw, _ = rt.world_mats(out_e["parents"], out_e["frames"][f])
        out_e["frames"][f][hb] = [list(np.array(p) + Rw[pr].T @ c), q]
        # head: turn the mouth axis toward the way the shaft comes in (base -> mouth), clamped
        Rh, Ph = rt.world_mats(out_e["parents"], out_e["frames"][f]); m = Ph[ih] + Rh[ih] @ ml
        into = Rh[ih] @ (il - ml); into /= np.linalg.norm(into); want_dir = m - G[f][1][gb]; want_dir /= np.linalg.norm(want_dir)
        ang = np.degrees(np.arccos(np.clip(into @ want_dir, -1, 1)))
        if ang > 1.0:
            ax = np.cross(into, want_dir); ax /= np.linalg.norm(ax); a = np.radians(min(ang, ORAL_HEAD_MAX))
            K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]]); Rd = np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K
            hp = out_e["parents"][ih]; out_e["frames"][f][ih] = [out_e["frames"][f][ih][0], list(rt.m2q(Rh[hp].T @ Rd @ Rh[ih]))]
        m = mouth(out_e, f); Rg, Pg = G[f]
        Rw2 = rt.align(Pg[gt] - Pg[gb], m - Pg[gb]) @ Rg[gb]
        out_g["frames"][f][gb] = [out_g["frames"][f][gb][0], list(rt.m2q(Rg[out_g["parents"][gb]].T @ Rw2))]
        short.append(max(0.0, np.linalg.norm(m - Pg[gb]) - L))
    rep = dict(eve_slide_cm=np.round(c, 1).tolist(), tip_short_cm=round(float(np.median(short)), 1), adam_drop_cm=round(drop, 1))
    return (out_e, out_g, rep) if adam is None else (out_e, out_g, rep, adam)


def lick(eve, adam, mg, gate=20.0):
    """cunnilingus: move Adam (hips, feet+hands kept) by ONE constant offset so his mouth reaches her vulva on average
    (his licking motion stays). -> (adam, mg, median gap before, after) or None when gated."""
    E = ue.load_skeleton(R0 + "CH_P_EVE_01_Skeleton.json"); A = ue.load_skeleton(R0 + "CH_NPC_Adam_01_Skeleton.json")
    ips, ihs = E["names"].index("Bip001-Pelvis"), A["names"].index("Bip001-Head")
    Rr, Pr = rt.world_mats(E["parents"], E["pose"]); Ra, Pa = rt.world_mats(A["parents"], A["pose"])
    ent, inner = ENTRY["vaginal"]; el, il = Rr[ips].T @ (ent - Pr[ips]), Rr[ips].T @ (inner - Pr[ips]); ml = Ra[ihs].T @ (ADAM_MOUTH - Pa[ihs])
    ip, ih = eve["names"].index("Bip001-Pelvis"), adam["names"].index("Bip001-Head")     # clip indices
    D = []
    for f in range(len(eve["frames"])):
        R, P = rt.world_mats(eve["parents"], eve["frames"][f]); Q, S = rt.world_mats(adam["parents"], adam["frames"][f])
        t = P[ip] + R[ip] @ el; out = R[ip] @ (el - il); out /= np.linalg.norm(out)
        D.append(t + out * 1.5 - (S[ih] + Q[ih] @ ml))            # 1.5 cm in front of the skin
    D = np.array(D); before = float(np.median(np.linalg.norm(D, axis=1)))
    if before > gate: return None
    delta = np.median(D, axis=0)
    out_a = json.loads(json.dumps(adam)); out_g = json.loads(json.dumps(mg))
    for f in range(len(eve["frames"])):
        p, q = out_g["frames"][f][0]; out_g["frames"][f][0] = [list(np.array(p) + delta), q]
        shift_hips_keep_feet(out_a, f, delta)
    return out_a, out_g, before, float(np.median(np.linalg.norm(D - delta, axis=1)))


if __name__ == "__main__":
    a = sys.argv[1:]; tgt = a[a.index("--target") + 1] if "--target" in a else "anal"
    eve, adam, mg = (json.load(open(p)) for p in a[:3])
    before = check(eve, mg, tgt)
    oa, og, rep = run(eve, adam, mg, tgt)
    after = check(eve, og, tgt)
    json.dump(oa, open(a[3], "w")); json.dump(og, open(a[4], "w"))
    print("contact %s: entry->shaft before max %.1f cm, after max %.1f cm | %s" % (tgt, max(before), max(after), rep))
