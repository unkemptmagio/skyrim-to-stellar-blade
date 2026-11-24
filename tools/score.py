# score.py: one misalignment score per built scene (lint issues + prop fit), ranked -> work/score.txt + work/score.json
#   python tools/score.py                    every built scene
#   python tools/score.py bench              only the benchmark set (work/bench.json)
#   python tools/score.py bench old.json     ... and the change against an earlier score.json (the per-phase check)
# Prop fit (props are not in lint): per stage, how deep a prop sinks into a body (pen) and, for restraints, how far it
# floats off the nearest body (gap). Toys are skipped: they are inserted on purpose and aligned by the entry pass.
import sys, os, re, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget as rt, hands as hd, props as pr

R0 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTRAINT = ("M_SkyrimMetal", "M_SkyrimRope")      # cuffs, ropes, yokes, binders: should hug the body
TOY = "M_SkyrimSilicone"
PEN_CM, GAP_CM = 4.0, 3.5                          # below this: fine. Hug (median prop-to-skin): well-fitted ropes
                                                   # read ~1.7, visibly loose ones 5-7. The capsule model reads points ON the skin
PEN_PCT = 10                                       # as ~2-3 cm inside (p10 over Eve's own mesh: -2.3), hence 4 cm
STEP, VERTS = 15, 400                              # every 15th frame (0.5 s), ~400 prop verts


def skin_many(R, P, pts, body):
    """hd.skin for many points at once: signed distance (cm, < 0 inside) of each point to the body"""
    best = np.full(len(pts), 1e9)
    for i, c, U, r in body:
        l = (pts - P[i]) @ R[i] - c; d = np.linalg.norm(l, axis=1); u = l / np.maximum(d, 1e-6)[:, None]
        rr = np.where(u @ U.T > 0.97, r[None, :], -np.inf).max(1)
        best = np.minimum(best, np.where(np.isfinite(rr), d - rr, 1e9))
    return best


def prop_fit(s):
    """-> ["S2 AO_BArmbinder 6 cm inside eve", "S3 AORopeWL floats 4 cm off the body", ...]"""
    roles = {"MF": ["eve", "adam"], "FF": ["eve", "tachy"], "F": ["eve"]}[s["kind"]]; issues = []
    for pt in s["parts"]:
        if pt["kind"] != "scene": continue
        built = pr.load_built(s["dir"], pt["slot"])
        if not built: continue
        clips = {r: json.load(open("%s/%d_%s.json" % (s["dir"], pt["slot"], r))) for r in roles}
        for si, (a0, a1, _) in enumerate(pt["stages"]):
            for m, clip, v in built:
                if m.get("material") == TOY: continue
                v = v[::max(1, len(v) // VERTS)]; pen = {r: [] for r in roles}; gap = []
                for f in range(a0, a1 + 1, STEP):
                    w = pr.world_verts(clip, v, f)
                    if w is None: continue
                    near = np.full(len(w), 1e9)
                    for r in roles:
                        c = clips[r]; Rb, Pb = rt.world_mats(c["parents"], c["frames"][min(f, len(c["frames"]) - 1)])
                        d = skin_many(Rb, Pb, w, hd.sb_body(r, c["names"], full=True)["body"])
                        pen[r].append(max(0.0, -np.percentile(d, PEN_PCT))); near = np.minimum(near, d)
                    gap.append(float(np.median(np.abs(near))))   # how closely the whole prop hugs the body: a cuff slid
                                                                  # or turned off the wrist still touches skin somewhere
                if not gap: continue                      # parked for the whole stage
                for r in roles:
                    p = float(np.percentile(pen[r], 90))
                    if p > PEN_CM: issues.append("S%d %s %.0f cm inside %s" % (si + 1, m["name"], p, r))
                g = float(np.median(gap))
                if m.get("material") in RESTRAINT and "yoke" not in m["name"].lower() and g > GAP_CM:   # a yoke's bar stands
                    issues.append("S%d %s sits %.0f cm off the body" % (si + 1, m["name"], g))              # off by design
    return issues


def weight(issue):
    """rough cm-equivalents so scenes rank by how bad they look; the absolute number means nothing"""
    n = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", issue.split(" ", 1)[1])] or [0]
    if "overlaps" in issue: return n[-1] / 10            # % of frames
    if "loses its touch" in issue: return n[-1] / 25     # % of frames
    if "wrist turns" in issue: return 1.0
    if "off the body" in issue: return n[-1] / 2
    if "inside" in issue: return n[-1] / (3 if re.search(r"S\d+ (AO|Yoke|M?Dildo|Chair|Shocky)\w* ", issue) else 5)
    return 1.0


def main(argv):
    sys.path.insert(0, R0); import port
    reg = port.reg(); only = None
    if argv and argv[0] == "bench": only = set(json.load(open(R0 + "/work/bench.json")))
    out = {}
    for sid, s in sorted(reg["scenes"].items()):
        if s["pack"] in port.DISABLED_PACKS or sid in port.DISABLED_SCENES or (only and sid not in only): continue
        issues = list(s.get("lint", [])) + prop_fit(s)
        out[sid] = dict(name=s["name"], slot=s["parts"][0]["slot"], score=round(sum(map(weight, issues)), 1), issues=issues)
        print("%-6.1f %s" % (out[sid]["score"], s["name"]), flush=True)
    name = "score_bench" if only else "score"
    json.dump(out, open(R0 + "/work/%s.json" % name, "w"), indent=1)
    old = json.load(open(argv[1])) if len(argv) > 1 else {}
    with open(R0 + "/work/%s.txt" % name, "w") as t:
        for sid, x in sorted(out.items(), key=lambda kv: -kv[1]["score"]):
            was = " (was %.1f)" % old[sid]["score"] if sid in old else ""
            t.write("%6.1f%s  %3d  %s\n" % (x["score"], was, x["slot"], x["name"]))
            for i in x["issues"]: t.write("              %s\n" % i)
    tot = sum(x["score"] for x in out.values())
    print("%d scenes, total %.0f%s -> work/%s.txt" % (len(out), tot, "" if not old else " (was %.0f)" % sum(old[k]["score"] for k in out if k in old), name))


if __name__ == "__main__":
    pts = np.array([[0.0, 0, 0], [0, 0, 100.0]]); E = hd.sb_body("eve")
    import ue, contact as ct
    S = ue.load_skeleton(ct.R0 + "CH_P_EVE_01_Skeleton.json"); Rr, Pr = rt.world_mats(S["parents"], S["pose"])
    p = Pr[S["names"].index("Bip001-Pelvis")]
    one = hd.skin(Rr, Pr, p, E["body"])[0]; many = skin_many(Rr, Pr, np.array([p]), E["body"])[0]
    assert abs(one - many) < 1e-6, (one, many)        # the vectorized skin must agree with hands.skin
    main(sys.argv[1:])
