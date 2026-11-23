# legs.py: leg passes on retargeted clips (any role: Eve, Adam, Tachy). Hips never move, so contacts stay where they are.
#   plant_feet(o, rest_ankle_z)  planted feet (slow + near their lowest height) stop sliding: each plant is locked to one spot,
#                                and a plant within FLOOR_CM of the floor sits at the skeleton's real ankle height (no float/sink)
#   spread_legs(o, others)       a knee / mid-thigh inside another body is pushed out by moving the knee (hip + foot fixed)
# check: python tools/legs.py <clip.json>   (foot slide + float before/after)
import sys, json
import numpy as np
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import retarget as rt, contact as ct

SLIDE_CM = 0.6      # per-frame foot speed below this (and low) = planted
LOW_CM = 4.0        # planted only within this of the foot's lowest height in the clip
FLOOR_CM = 4.0      # a plant this close to the rest ankle height is ON the floor: snap to it
MIN_PLANT = 4       # frames
EASE = 3            # frames of blend in/out at each plant's ends


def leg_ik(o, f, side, foot, knee_pole=None):
    """foot ankle to `foot` (world), knee bends toward knee_pole (default: its current position); foot keeps world rotation"""
    n, par, fr = o["names"], o["parents"], o["frames"][f]
    th, ca, fo = (n.index("Bip001-%s-%s" % (side, x)) for x in ("Thigh", "Calf", "Foot"))
    R0, P0 = rt.world_mats(par, fr)
    l1, l2 = np.linalg.norm(P0[ca] - P0[th]), np.linalg.norm(P0[fo] - P0[ca])
    toe = n.index("Bip001-%s-Toe0" % side) if "Bip001-%s-Toe0" % side in n else fo
    kn = ct.two_bone(P0[th], P0[ca] if knee_pole is None else knee_pole, foot, l1, l2, fallback=P0[toe] - P0[fo])   # knee follows the toes
    Rth = rt.align(P0[ca] - P0[th], kn - P0[th]) @ R0[th]
    # knee hinge: the smallest thigh turn left the knee's hinge axis off the new hip-knee-foot plane, so a pushed knee bent
    # sideways. Twist the thigh about its own axis until its hinge (measured on the original leg) is square to that plane.
    h0 = np.cross(P0[ca] - P0[th], P0[fo] - P0[ca]); h1 = np.cross(kn - P0[th], foot - kn)
    if np.linalg.norm(h0) > 1e-3 and np.linalg.norm(h1) > 1e-3:
        ax = (kn - P0[th]) / np.linalg.norm(kn - P0[th]); hl = R0[th].T @ (h0 / np.linalg.norm(h0))     # hinge in thigh space
        cur = Rth @ hl; cur -= np.dot(cur, ax) * ax; want = h1 / np.linalg.norm(h1); want -= np.dot(want, ax) * ax
        if np.linalg.norm(cur) > 1e-6 and np.linalg.norm(want) > 1e-6:
            Rth = rt.align(cur, want) @ Rth                     # both are perpendicular to ax: a pure twist about the thigh
    fr[th] = [fr[th][0], list(rt.m2q(R0[par[th]].T @ Rth))]
    R1, P1 = rt.world_mats(par, fr)
    fr[ca] = [fr[ca][0], list(rt.m2q(R1[par[ca]].T @ rt.align(P1[fo] - P1[ca], foot - P1[ca]) @ R1[ca]))]
    R2, _ = rt.world_mats(par, fr)
    fr[fo] = [fr[fo][0], list(rt.m2q(R2[par[fo]].T @ R0[fo]))]


def ankles(o, side):
    i = o["names"].index("Bip001-%s-Foot" % side)
    return np.array([rt.world_mats(o["parents"], fr)[1][i] for fr in o["frames"]])


def plants(P):
    """planted frame runs [(a, b)] from an ankle track"""
    F = len(P); v = np.r_[0, np.linalg.norm(np.diff(P, axis=0), axis=1)]; low = P[:, 2] < P[:, 2].min() + LOW_CM
    on = (v < SLIDE_CM) & low; out, a = [], None
    for f in range(F + 1):
        if f < F and on[f]: a = f if a is None else a
        elif a is not None:
            if f - a >= MIN_PLANT: out.append((a, f - 1))
            a = None
    return out


def plant_feet(o, rest_ankle_z, loop=True):
    """loop=False: a whole assembled scene, whose first and last plants are different spots"""
    o = json.loads(json.dumps(o)); rep = {}
    for side in "LR":
        P = ankles(o, side); F = len(P)
        # only plants near the floor (a slow foot wrapped around the partner must stay with the partner, not the world)
        runs = [(a, b) for a, b in plants(P) if np.median(P[a:b + 1, 2]) < rest_ankle_z + 2 * FLOOR_CM]
        locks = [np.median(P[a:b + 1], axis=0) for a, b in runs]
        if loop and len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == F - 1:      # the loop wraps through a plant: one spot for both
            both = np.median(np.r_[P[runs[0][0]:runs[0][1] + 1], P[runs[-1][0]:runs[-1][1] + 1]], axis=0)
            locks[0] = locks[-1] = both
        for (a, b), lock in zip(runs, locks):
            lock = lock.copy()
            if abs(lock[2] - rest_ankle_z) < FLOOR_CM: lock[2] = rest_ankle_z
            for f in range(max(0, a - EASE), min(len(P), b + EASE + 1)):
                w = 1.0 if a <= f <= b else 1 - (a - f if f < a else f - b) / (EASE + 1)
                w = w * w * (3 - 2 * w)
                leg_ik(o, f, side, P[f] + (lock - P[f]) * w)
        Q = ankles(o, side)
        slide = lambda X: max([float(np.linalg.norm(X[a:b + 1, :2] - X[a, :2], axis=1).max()) for a, b in runs] or [0])
        rep[side] = "plants %d, slide %.1f->%.1f cm" % (len(runs), slide(P), slide(Q))
    return o, rep


def spread_legs(o, others, skin_fn, skin=1.5, rest_ankle_z=None):
    """others = [(role, clip)] bodies; skin_fn(R, P, point, role) -> (signed dist, outward dir).
    rest_ankle_z given: raised feet / calves inside another body are moved out too"""
    o = json.loads(json.dumps(o)); n = o["names"]; pushed = 0
    for side in "LR":
        th, ca = n.index("Bip001-%s-Thigh" % side), n.index("Bip001-%s-Calf" % side)
        D = []
        for f in range(len(o["frames"])):
            _, P = rt.world_mats(o["parents"], o["frames"][f]); best = np.zeros(3)
            for role, c in others:
                Rb, Pb = rt.world_mats(c["parents"], c["frames"][f])
                for pt in (P[ca], (P[th] + P[ca]) / 2):              # knee, mid-thigh
                    d, u = skin_fn(Rb, Pb, pt, role)
                    if u is not None and d < skin and skin - d > np.linalg.norm(best): best = u * (skin - d)
            D.append(best)
        if max(np.linalg.norm(x) for x in D) >= 0.5:
            import hands as hd
            D = hd.settle(D)
            for f in range(len(o["frames"])):
                if np.linalg.norm(D[f]) < 0.3: continue
                _, P = rt.world_mats(o["parents"], o["frames"][f]); fo = n.index("Bip001-%s-Foot" % side)
                leg_ik(o, f, side, P[fo], knee_pole=P[ca] + 2 * D[f]); pushed += 1     # pole past the target: the knee swings out
        for _ in range(2): pushed += _feet_out(o, side, others, skin_fn, skin, rest_ankle_z)   # 2nd round: the median filter leaves ~half
    return o, pushed


FOOT_PUSH_MAX = 12.0   # cm


def _feet_out(o, side, others, skin_fn, skin, rest_ankle_z):
    """a raised foot / calf inside the partner (legs wrapped around him: Eve's feet 10 cm into Adam's back, a calf 18 cm deep
    in Bound Fisting, 2026-11-23) moves out onto his skin; the knee follows. Feet near the floor are never moved."""
    n = o["names"]; ca, fo = n.index("Bip001-%s-Calf" % side), n.index("Bip001-%s-Foot" % side); D = []
    for f in range(len(o["frames"])):
        _, P = rt.world_mats(o["parents"], o["frames"][f]); best = np.zeros(3)
        if rest_ankle_z is None or P[fo][2] > rest_ankle_z + 2 * FLOOR_CM:
            for role, c in others:
                Rb, Pb = rt.world_mats(c["parents"], c["frames"][f])
                for pt, gain in ((P[fo], 1.0), ((P[ca] + P[fo]) / 2, 2.0)):     # the foot moves twice as far as mid-calf
                    d, u = skin_fn(Rb, Pb, pt, role)
                    if u is not None and d < skin and gain * (skin - d) > np.linalg.norm(best): best = u * gain * (skin - d)
        nb = np.linalg.norm(best); D.append(best * min(1.0, FOOT_PUSH_MAX / nb) if nb > 0 else best)
    if max(np.linalg.norm(x) for x in D) < 0.5: return 0
    import hands as hd
    D = hd.settle(D, robust=True); k = 0
    for f in range(len(o["frames"])):
        if np.linalg.norm(D[f]) < 0.3: continue
        _, P = rt.world_mats(o["parents"], o["frames"][f]); leg_ik(o, f, side, P[fo] + D[f]); k += 1
    return k


if __name__ == "__main__":
    c = json.load(open(sys.argv[1]))
    i = c["names"].index("Bip001-L-Foot"); z0 = min(rt.world_mats(c["parents"], fr)[1][i][2] for fr in c["frames"])
    o, rep = plant_feet(c, z0); print(rep)
