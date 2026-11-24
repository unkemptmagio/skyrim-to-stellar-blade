# sheet.py <scene dir> <registry scene json key> -> <scene dir>/sheet.png
# Contact sheet: every stage at start / middle / end, side view (X-Z) and front view (Y-Z), stick figures in UE space.
# Eve = pink, partner = blue, genital rig = orange, entry target = red dot, props = grey dots. Lets a bad port be
# spotted without the game.
import sys, os, json, re
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget as rt, contact as ct, ue, props as pr
PROP_DOTS = 250

CORE = re.compile(r"^(Bip001(-Pelvis|-Spine\d?|-Neck|-Head|-[LR]-(Clavicle|UpperArm|Forearm|Hand|Thigh|Calf|Foot|Toe0))?|NPC-Genitals\w*|GenitalsLag\w*|GenitalsScrotumLag|Genitals|Schlong)$")
COL = {"eve": (235, 90, 140), "adam": (70, 130, 220), "tachy": (60, 170, 120), "mg": (240, 150, 40)}
CELL = 260


def segments(d, f):
    R, P = rt.world_mats(d["parents"], d["frames"][f]); out = []
    for i, n in enumerate(d["names"]):
        p = d["parents"][i]
        if p >= 0 and CORE.match(n) and CORE.match(d["names"][p]): out.append((P[p], P[i]))
    return out, R, P


def render(scene_dir, scene, target):
    roles = {"MF": ["eve", "adam", "mg"], "FF": ["eve", "tachy"], "F": ["eve"]}[scene["kind"]]
    E = ue.load_skeleton(ct.R0 + "CH_P_EVE_01_Skeleton.json"); bone = ct.BONE.get(target, "Bip001-Pelvis"); ip = E["names"].index(bone)
    Rr, Pr = rt.world_mats(E["parents"], E["pose"])
    ent_l = Rr[ip].T @ (ct.ENTRY[target][0] - Pr[ip]) if target else None
    # one-clip scenes: one json per role, stage ranges in the part; old layout: one json per stage slot
    rows = []
    for pt in scene["parts"]:
        if pt["kind"] == "scene":
            data = {r: json.load(open("%s/%d_%s.json" % (scene_dir, pt["slot"], r))) for r in roles}
            data["props"] = [(c, v[::max(1, len(v) // PROP_DOTS)]) for _, c, v in pr.load_built(scene_dir, pt["slot"])]
            rows += [(data, (a0, (a0 + a1) // 2, a1)) for a0, a1, _ in pt["stages"]]
        elif pt["kind"] == "stage":
            data = {r: json.load(open("%s/%d_%s.json" % (scene_dir, pt["slot"], r))) for r in roles}
            n = len(data["eve"]["frames"]); rows.append((data, (0, n // 2, n - 1)))
    img = Image.new("RGB", (CELL * 6, CELL * len(rows) + 24), (250, 250, 250)); dr = ImageDraw.Draw(img)
    dr.text((6, 6), "%s  (%s, target %s)" % (scene["name"], scene["kind"], target), fill=(0, 0, 0))
    for si, (data, fr3) in enumerate(rows):
        ipc = data["eve"]["names"].index(bone)
        for ci, f in enumerate(fr3):
            segs = {r: segments(data[r], f) for r in roles}
            pts = np.array([p for r in roles for a, b in segs[r][0] for p in (a, b)])
            c = (pts.max(0) + pts.min(0)) / 2; span = max(80.0, float((pts.max(0) - pts.min(0)).max()))
            sc = (CELL - 30) / span
            for vi, (ax, lab) in enumerate((((0, 2), "side"), ((1, 2), "front"))):
                ox, oy = (ci * 2 + vi) * CELL, 24 + si * CELL
                dr.rectangle([ox, oy, ox + CELL - 1, oy + CELL - 1], outline=(210, 210, 210))
                proj = lambda p: (ox + CELL / 2 + (p[ax[0]] - c[ax[0]]) * sc, oy + CELL / 2 - (p[ax[1]] - c[ax[1]]) * sc)
                for c_, v_ in data.get("props", []):      # under the bodies, so a prop sunk into one shows as hidden dots
                    w = pr.world_verts(c_, v_, f)
                    for p in (() if w is None else w):
                        x, y = proj(p); dr.point((x, y), fill=(120, 120, 120))
                for r in roles:
                    for a, b in segs[r][0]: dr.line([proj(a), proj(b)], fill=COL[r], width=3)
                if ent_l is not None:
                    _, R, P = segs["eve"]; t = P[ipc] + R[ipc] @ ent_l; x, y = proj(t)
                    dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(220, 0, 0))
                dr.text((ox + 4, oy + 3), "S%d f%d %s" % (si + 1, f, lab), fill=(60, 60, 60))
    out = scene_dir + "/sheet.png"; img.save(out); return out


if __name__ == "__main__":
    reg = json.load(open(sys.argv[1])); s = reg["scenes"][sys.argv[2]]
    print(render(s["dir"], s, s.get("target")))
