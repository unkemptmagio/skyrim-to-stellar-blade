# hkx2json.py <skeleton.hkx> <anim.hkx (tagfile XML)> <out.json>
# Writes skeleton (bones, parents, local rest) + per-frame LOCAL transforms for every animated bone.
import sys, json
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import hkx

skel_p, anim_p, out_p = sys.argv[1:4]
s = hkx.skeleton(hkx.Pack(open(skel_p, "rb").read()))
a = hkx.animation_xml(anim_p)
idx = {n: i for i, n in enumerate(s["bones"])}
tracks = [(t, idx[n]) for t, n in enumerate(a["names"]) if n in idx]
frames = []
for fr in a["frames"]:
    row = {}
    for t, bi in tracks:
        rp, rq, rs = s["ref"][bi]
        tr = fr[t]
        pos = [r if (tr["pos"] is None or tr["pos"][k] is None) else tr["pos"][k] for k, r in enumerate(rp)]
        rot = list(tr["rot"]) if tr["rot"] else list(rq)
        row[bi] = [pos, rot]
    frames.append(row)
json.dump(dict(bones=s["bones"], parents=s["parents"], ref=[[list(p), list(q)] for p, q, _ in s["ref"]],
               fps=round(1 / a["frameDur"]), frames=frames), open(out_p, "w"))
print("wrote", out_p, len(frames), "frames,", len(tracks), "tracks")
