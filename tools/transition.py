# transition.py <from.json> <to.json> <out.json> [seconds=0.5]
# Bakes a short clip that eases every bone from the LAST frame of <from> to the FIRST frame of <to>
# (local rotations slerped, local positions lerped, smoothstep timing). Same json format as retarget.py output.
# PELA/ATOOL swap clips with no blend, so playing this between two stages removes the one-frame jump.
import sys, json, math


def slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0: b, d = [-x for x in b], -d
    if d > 0.9995:
        r = [x + (y - x) * t for x, y in zip(a, b)]
    else:
        th = math.acos(d); s = math.sin(th)
        wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        r = [wa * x + wb * y for x, y in zip(a, b)]
    n = math.sqrt(sum(x * x for x in r)) or 1.0
    return [x / n for x in r]


def bake(src, dst, seconds=0.5):
    assert src["names"] == dst["names"], "clips are on different skeletons"
    fps = src.get("fps", 30); n = max(2, int(round(seconds * fps)) + 1)
    A, B = src["frames"][-1], dst["frames"][0]
    frames = []
    for i in range(n):
        u = i / (n - 1); t = u * u * (3 - 2 * u)                       # smoothstep: no velocity pop at either end
        frames.append([[[pa + (pb - pa) * t for pa, pb in zip(a[0], b[0])], slerp(a[1], b[1], t)] for a, b in zip(A, B)])
    out = {k: v for k, v in src.items() if k != "frames"}; out["frames"] = frames
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    r = bake(json.load(open(a[0])), json.load(open(a[1])), float(a[3]) if len(a) > 3 else 0.5)
    json.dump(r, open(a[2], "w")); print("transition", len(r["frames"]), "frames ->", a[2])


def seam_cm(c):
    """how far any bone jumps when a looping clip wraps from its last frame to its first (cm, world space)"""
    import retarget as rt, numpy as np
    _, A = rt.world_mats(c["parents"], c["frames"][-1]); _, B = rt.world_mats(c["parents"], c["frames"][0])
    return float(np.linalg.norm(np.asarray(A) - np.asarray(B), axis=1).max())


def _mix(A, B, t):
    """one frame: local positions lerped, local rotations slerped (numpy, all bones at once)"""
    import numpy as np
    pa, qa = np.array([x[0] for x in A], float), np.array([x[1] for x in A], float)
    pb, qb = np.array([x[0] for x in B], float), np.array([x[1] for x in B], float)
    d = np.sum(qa * qb, 1); qb[d < 0] *= -1; d = np.abs(d)
    th = np.arccos(np.clip(d, -1, 1)); s = np.sin(th); lin = s < 1e-4
    wa = np.where(lin, 1 - t, np.sin((1 - t) * th) / np.where(lin, 1, s)); wb = np.where(lin, t, np.sin(t * th) / np.where(lin, 1, s))
    q = wa[:, None] * qa + wb[:, None] * qb; q /= np.linalg.norm(q, axis=1, keepdims=True)
    p = pa + (pb - pa) * t
    return [[pp.tolist(), qq.tolist()] for pp, qq in zip(p, q)]


def pose_cm(a, b):
    """largest world-space bone distance between a's last frame and b's first (cm)"""
    import retarget as rt, numpy as np
    _, A = rt.world_mats(a["parents"], a["frames"][-1]); _, B = rt.world_mats(b["parents"], b["frames"][0])
    return float(np.linalg.norm(np.asarray(A) - np.asarray(B), axis=1).max())


def blend_seconds(a, b, lo=0.3, hi=1.2, cm_per_s=50.0):
    """small pose change -> short blend, big change -> up to 1.2 s"""
    return min(hi, max(lo, lo + pose_cm(a, b) / cm_per_s))


def blend_into(src, dst, seconds):
    """crossfade with BOTH clips moving: frame i = mix(src keeps looping from its last frame, dst playing from frame 0, smoothstep).
    Loops wrap without their duplicated end frame, so a 1.2 s blend works on an 11-frame stage too.
    -> (frames, next_dst_frame): the caller continues dst from next_dst_frame."""
    fps = src.get("fps", 30); n = max(2, int(round(seconds * fps)))
    Ls, Ld = max(1, len(src["frames"]) - 1), max(1, len(dst["frames"]) - 1)        # effective loop lengths
    out = []
    for i in range(1, n):
        u = i / (n - 1); t = u * u * (3 - 2 * u)
        a = src["frames"][(len(src["frames"]) - 1 + i) % Ls] if i else src["frames"][-1]
        b = dst["frames"][i % Ld]
        out.append(b if i == n - 1 else _mix(a, b, t))
    return out, (n - 1) % Ld + 1


# ------------------------------------------------------------------ scene assembly helpers (2026-11-23)
XFADE_S = 0.2   # loop seam crossfade


def cycle(c, k):
    """one loop of a stage as a frame list (the duplicated end frame dropped). With k > 0 the seam is spread over the last k
    frames: each bone gets the gap between where its motion would go next and where the loop restarts, ramped in. Same
    length (roles stay in sync), a seamless role is left as is, nothing ever stops (the old seam fix inserted a 0.2 s
    static ease, for every role whenever one role had a seam)."""
    import numpy as np, retarget as rt
    F = c["frames"][:-1] if len(c["frames"]) > 2 else c["frames"]; L = len(F)
    if k <= 0 or L < 3 * k: return list(F)
    out = [list(fr) for fr in F]
    for b in range(len(F[0])):
        p1, p2, p0 = (np.array(F[i][b][0], float) for i in (L - 1, L - 2, 0))
        R1, R2, R0 = (rt.q2m(F[i][b][1]) for i in (L - 1, L - 2, 0))
        dp = p0 - (2 * p1 - p2); Rd = R0 @ (R1 @ R2.T @ R1).T          # first frame vs the predicted next one
        if np.linalg.norm(dp) < 1e-4 and np.trace(Rd) > 3 - 1e-6: continue
        qd = np.array(rt.m2q(Rd))
        for i in range(L - k, L):
            u = (i - (L - k) + 1) / (k + 1); w = u * u * (3 - 2 * u)
            q = _mix([[[0, 0, 0], [1.0, 0, 0, 0]]], [[[0, 0, 0], list(qd)]], w)[0][1]
            out[i] = list(out[i]); out[i][b] = [list(np.array(F[i][b][0], float) + w * dp), list(rt.m2q(rt.q2m(q) @ rt.q2m(F[i][b][1])))]
    return out


def _world(c, frames):
    import retarget as rt, numpy as np
    return np.array([rt.world_mats(c["parents"], fr)[1] for fr in frames])


def match_phase(src, dst, src_cycles, dst_cycles):
    """the (exit frame of src cycle, entry frame of dst cycle) whose poses are closest over all roles (largest bone gap)
    -> (e, j, gap_cm). src/dst: {role: clip} (for parents); *_cycles: {role: frame list}"""
    import numpy as np
    best = None
    roles = list(src_cycles)
    Ws = {r: _world(src[r], src_cycles[r]) for r in roles}; Wd = {r: _world(dst[r], dst_cycles[r]) for r in roles}
    Ls, Ld = len(src_cycles[roles[0]]), len(dst_cycles[roles[0]])
    gap = np.zeros((Ls, Ld))
    for r in roles:
        d = np.linalg.norm(Ws[r][:, None, :, :] - Wd[r][None, :, :, :], axis=3).max(axis=2); gap = np.maximum(gap, d)
    e, j = np.unravel_index(np.argmin(gap), gap.shape)
    return int(e), int(j), float(gap[e, j])


def blend_cycles(src_cyc, dst_cyc, e, j, n):
    """n crossfade frames: src keeps looping from its frame e, dst plays from its frame j (smoothstep)
    -> (frames, dst phase to continue from)"""
    Ls, Ld = len(src_cyc), len(dst_cyc); out = []
    for i in range(1, n + 1):
        u = i / (n + 1); t = u * u * (3 - 2 * u)
        out.append(_mix(src_cyc[(e + i) % Ls], dst_cyc[(j + i) % Ld], t))
    return out, (j + n + 1) % Ld
