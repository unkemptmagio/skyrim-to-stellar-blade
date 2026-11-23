"""Skyrim SexLab (SLAL) -> Stellar Blade ATOOL/PEFA/PELA, no manual steps.

  python port.py list [pack-filter]              show SLAL scenes and whether they can be ported
  python port.py scene <SLAL id> [...]           prepare scene(s): retarget, contact, transitions, FBX, slots (registry)
  python port.py pack <SLAL json name filter>    prepare every portable scene in matching SLAL json files
  python port.py build                           UE import/cook, bone remap, one pak per pack, install, PELA files, contact sheets
  python port.py install                         redo only the install step from the last staged build
  python port.py drop <SLAL id>                  remove a scene from the registry (its slots are freed at the next build)

Rules: MF -> Eve + Adam (+ genital rig), FF -> Eve + Tachy (Tachy uses Eve's skeleton). Creatures, 3+ actors, furniture
and AnimObject (props) scenes are skipped. Tags pick the contact target: Anal -> anal, Vaginal -> vaginal, else none.
Slots stay <= 1000 (ATOOL ignores higher ones) and avoid every slot another installed pack uses.
"""
import sys, os, json, glob, re, subprocess, shutil, statistics
from concurrent.futures import ThreadPoolExecutor
import numpy as np, struct, time

R = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, R + "/tools")
import retarget as rt, contact as ct, transition as tr, hands as hd, props, legs, sound, cfg

MODS = cfg.SKYRIM_MODS
GAME = cfg.SB_GAME
PEFA = GAME + "/Binaries/Win64/ue4ss/Mods/PEFA"
TEST = bool(os.environ.get("PORT_ONLY"))   # test build: own install folder + PELA file, the real port stays untouched
INSTALL = GAME + "/Content/Paks/~mods/_SkyrimPort" + ("Test" if TEST else "")
PELA_DIR = GAME + "/Content/Paks/~mods/PELA Patches"
BLENDER = cfg.BLENDER
UE = cfg.UE_ROOT + "/Engine/Binaries/Win64/UE4Editor-Cmd.exe"
UAT_DIR = cfg.UE_ROOT + "/Engine/Binaries/DotNET"
PROJ = cfg.MODKIT + "/SB.uproject"
PROJ_ANIM = cfg.MODKIT + "/Content/Mods/HD-ATOOL_P/anim"
COOK = cfg.MODKIT + "/Saved/Cooked/WindowsNoEditor/SB/Content/Mods/HD-ATOOL_P/anim"
STAGED = cfg.MODKIT + "/Saved/StagedBuilds/WindowsNoEditor/SB/Content/Paks"
REG = os.environ.get("PORT_REG") or R + "/work/registry.json"   # PORT_REG: a copy, so a test can run beside a batch
# a registry copy gets its own scene folders: test runs re-preparing a scene must never delete the real scene's files
SCENES_DIR = "scenes" if os.path.abspath(REG) == os.path.abspath(R + "/work/registry.json") else "scenes_" + os.path.basename(REG)[:-5]
SK = R + "/skeletons/"
XF, XM = SK + "xpmsse_skeleton_female.hkx", SK + "xpmsse_skeleton.hkx"
EVE_SK, ADAM_SK, MG_SK = SK + "CH_P_EVE_01_Skeleton.json", SK + "CH_NPC_Adam_01_Skeleton.json", SK + "CH_NPC_MaleGenitals_Skeleton.json"
UE_SKEL = {"eve": "/Game/Art/Character/PC/CH_P_EVE_01/CH_P_EVE_01_Skeleton",
           "adam": "/Game/Art/Character/NPC/CH_NPC_Adam_01/CH_NPC_Adam_01_Skeleton",
           "mg": "/Game/Mods/HD-ATOOL_P/Monster/CH_M_NA_55/CH_NPC_MaleGenitals_Skeleton"}
ADAM_BP = "/Game/Art/Character/NPC/CH_NPC_Adam_01/Blueprints/CH_NPC_Adam_01_Blueprint.CH_NPC_Adam_01_Blueprint_C"
TACHY_BP = "/Game/Art/Character/NPC/CH_NPC_TachyNPC/Blueprints/CH_NPC_TachyNPC_Blueprint.CH_NPC_TachyNPC_Blueprint_C"
MG_MESH = "/Game/Mods/HD-ATOOL_P/Monster/CH_M_NA_55/CH_NPC_MaleGenitals.CH_NPC_MaleGenitals"
PROP_DIR = "/Game/Mods/HD-ATOOL_P/Props/SkyrimPort"      # our prop meshes (+ <name>_Skeleton, M_SkyrimSilicone) ship in the pak
PROP_SK = R + "/work/prop_skeleton.json"
# Solo toy scenes: Eve's own sword instead of the Skyrim toy (user idea, 2026-11-23): the game's textured sword mesh, driven by a
# clip on its own skeleton (no mesh shipped), hilt where the toy's inserted tip was, blade out past her hand. PORT_SOLO_TOY=toy: old.
SOLO_TOY = os.environ.get("PORT_SOLO_TOY", "sword")
SWORD_SK = SK + "CH_W_Sword_01_Skeleton.json"
SWORD_UE = "/Game/Art/Character/Weapon/Sword/CH_W_Sword_01/CH_W_Sword_01"
SWORD_POMMEL_Z = -13.2      # cm, sword space: the pommel end (the blade runs to +126.8)
SLOT_RANGES = [(352, 699), (908, 1000)]
TRANSITION_S, STAGE_SECONDS, CONTACT_GATE_CM = 0.5, 7.0, 20.0
ANKLE_Z = {"eve": 15.0, "tachy": 15.0, "adam": 13.5}   # rest-pose ankle height above the floor (cm): planted feet sit here      # a stage whose last frame is > 1 cm from its first gets a 0.2 s blend between repeats
DISABLED_PACKS = {x for x in os.environ.get("PORT_DISABLED", "Billyy").split(",") if x}   # not built/installed; slots stay reserved
DISABLED_SCENES = {"Leito_Kissing_Female_Start"}   # QA 2026-11-23 "horrible, disable it": not built/installed, slot stays reserved
MAX_PAK_ASSETS = 400     # per container; 938 crashed the game at startup, 470 loads fine
PACK_CHUNK = {}          # pack name -> chunk id, assigned in build (1, 2, ...)
J = lambda p: json.load(open(p, encoding="utf-8-sig"))
def W(p, d):                      # atomic: a crash mid-write must never truncate registry.json
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = "%s.%d.tmp" % (p, os.getpid())
    open(tmp, "w").write(json.dumps(d, indent=1))
    for k in range(10):           # Windows: replace fails while anything (AV, indexer, a reader) has the target open
        try: os.replace(tmp, p); return
        except PermissionError:
            if k == 9: raise
            time.sleep(0.2)


# ------------------------------------------------------------------ SLAL lookup
def slal_files():
    """natural order (numbers as numbers): the last file wins in find_scene, so "Pack 10.10" must sort after "Pack 10.9" """
    nat = lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p)]
    return sorted(glob.glob(MODS + "/*/SLAnims/json/*.json"), key=nat)

def load_slal(f):
    t = re.sub(r",(\s*[\]}])", r"\1", open(f, encoding="utf-8-sig", errors="replace").read())
    return json.loads(t)

_hkx_index = {}
def hkx_index(mod_root):
    if mod_root not in _hkx_index:
        idx = {}
        for p in glob.glob(mod_root + "/meshes/actors/character/animations/**/*.hkx", recursive=True):
            idx[os.path.basename(p)[:-4].lower()] = p.replace("\\", "/")
        for lst in glob.glob(mod_root + "/meshes/actors/character/animations/**/FNIS_*_List.txt", recursive=True):
            for ln in open(lst, encoding="utf-8", errors="replace"):   # FNIS event name -> file (Billyy: "B_" events)
                t = ln.split()
                if len(t) >= 3:
                    i = 2 if t[1].startswith("-") else 1
                    if i + 1 < len(t) and t[i + 1].lower().endswith(".hkx"):
                        f = idx.get(t[i + 1][:-4].lower())
                        if f: idx.setdefault(t[i].lower(), f)
        _hkx_index[mod_root] = idx
    return _hkx_index[mod_root]

_scenes = {}
def find_scene(sid):
    if not _scenes:                       # one pass over every SLAL json, then lookups are free
        for f in slal_files():
            root = f.replace("\\", "/").rsplit("/SLAnims", 1)[0]
            for a in load_slal(f).get("animations", []): _scenes[a["id"].lower()] = (root, a, f)   # later (newer) pack wins
    if sid.lower() not in _scenes: raise SystemExit("SLAL scene not found: " + sid)
    return _scenes[sid.lower()]

def pack_name(root):
    n = os.path.basename(root)
    m = re.search(r"by\s+(\w+)", n, re.I) or re.search(r"(\w+)'s", n)
    return re.sub(r"\W", "", m.group(1) if m else n.split()[0])

def solo_toy(a, root):
    """the one toy a solo scene holds in EVERY stage (LE nif path) -> path, else None (then the general props take over)"""
    if "animobject" not in a.get("tags", "").lower(): return None
    objs = props.stage_objects(root); found = [objs.get(st["id"].lower(), []) for st in a["actors"][0]["stages"]]
    if not all(found) or len({f[0] for f in found}) != 1 or any(len(f) != 1 for f in found): return None
    p = props.resolve(found[0][0], root)
    try:
        v = props.nif.static_mesh(p)[0] if p else None
        return p if v is not None and (v.max(0) - v.min(0)).max() < 40 else None   # toy-sized only (a chair is ~100 units)
    except Exception: return None


def classify(a, root):
    """-> (kind 'MF'|'FF'|'F'|None, target 'anal'|'vaginal'|'oral'|None, reason). 'F' = solo Eve (+ AnimObject prop)."""
    types = [x["type"] for x in a["actors"]]
    tags = [t.strip().lower() for t in a.get("tags", "").split(",")]
    if types == ["Female"]: kind = "F"
    elif len(types) != 2: return None, None, "%d actors" % len(types)
    elif any("creature" in t.lower() for t in types): return None, None, "creature"
    else: kind = "MF" if types == ["Female", "Male"] else "FF" if types == ["Female", "Female"] else None
    if not kind: return None, None, "actor types %s" % types
    if "furniture" in tags: return None, None, "needs furniture"
    # props (AnimObjects, tagged or not): every scene gets them through props.scene_props (2026-11-23); unreadable ones are
    # dropped from the scene, not the scene itself. Solo scenes with one toy in every stage keep the inserted-toy path.
    idx = hkx_index(root)
    for act in a["actors"]:
        for st in act["stages"]:
            p = idx.get(st["id"].lower())
            if not p: return None, None, "missing hkx " + st["id"]
    if kind == "FF" or "fisting" in tags: target = None
    elif "anal" in tags: target = "anal"
    elif "vaginal" in tags: target = "vaginal"
    elif "blowjob" in tags: target = "oral"
    else: target = None
    return kind, target, "ok"


# ------------------------------------------------------------------ slots
def reg():
    return J(REG) if os.path.exists(REG) else {"scenes": {}}

def ours_in_project():
    return {int(os.path.basename(p)[:-7]) for p in glob.glob(PROJ_ANIM + "/*.uasset") if re.fullmatch(r"\d+\.uasset", os.path.basename(p))}

def used_slots(registry, exclude_scene=None, exclude=(), reserved=()):
    used = set()
    for ln in open(PEFA + "/packs_rows.txt", encoding="utf-8", errors="replace"):
        m = re.match(r"(\d+)\t", ln)
        if m: used.add(int(m.group(1)))
    for m in re.finditer(r"anim/(\d+)", open(PEFA + "/library.txt", encoding="utf-8", errors="replace").read()):
        used.add(int(m.group(1)))
    used -= ours_in_project()                                   # stale rows of our own earlier builds
    for sid, s in registry["scenes"].items():
        if sid != exclude_scene and sid not in exclude: used |= {p["slot"] for p in s.get("parts", [])}
    return used | set(reserved)          # last: the "stale project slots" subtraction above must never free a reservation

def allocate(n, used):
    for lo, hi in SLOT_RANGES:
        s = lo
        while s + n - 1 <= hi:
            block = range(s, s + n)
            bad = [x for x in block if x in used]
            if not bad: return list(block)
            s = bad[-1] + 1
    raise SystemExit("no free block of %d slots <= 1000 left" % n)


# ------------------------------------------------------------------ prepare one scene
def blender_fbx(args):
    skel, clip_json, out = args[:3]
    r = subprocess.run([BLENDER, "-b", "--python", R + "/tools/make_fbx.py", "--", skel, clip_json, out] + list(args[3:]),
                       capture_output=True, text=True, timeout=1800)          # a hung Blender must not stall a worker forever
    if "FBX DONE" not in r.stdout: raise RuntimeError("FBX failed for %s\n%s" % (clip_json, (r.stdout + r.stderr)[-1500:]))
    return out

def prepare(sid, registry, slots=None, save=True):
    """one scene -> registry entry (+ writes it when save). slots: pre-allocated by prepare_many (parallel workers)"""
    root, a, f = find_scene(sid)
    kind, target, why = classify(a, root)
    if not kind: print("SKIP", sid, "-", why); return False
    idx = hkx_index(root); pack = pack_name(root)
    D = R + "/work/" + SCENES_DIR + "/" + a["id"]; os.makedirs(D + "/fbx", exist_ok=True)
    n = len(a["actors"][0]["stages"])
    slots = slots or allocate(1, used_slots(registry, exclude_scene=a["id"]))     # ONE clip per scene (ATOOL: <= 1000 slots, shared)
    fem = [idx[s["id"].lower()] for s in a["actors"][0]["stages"]]
    oth = [idx[s["id"].lower()] for s in a["actors"][1]["stages"]] if kind != "F" else [None] * n
    partner = {"MF": "adam", "FF": "tachy", "F": None}[kind]
    prop = None
    toy = solo_toy(a, root) if kind == "F" and target in ("vaginal", "anal") else None
    if toy:   # solo, ONE inserted toy in every stage: aligned to her entry, her hand keeps the grip (props.align / hold)
        prop = props.prop_mesh(toy, rt.run(XF, fem[0], EVE_SK, keep={"Bip001"})["scale"])
        W(D + "/prop_mesh.json", prop)
        if not os.path.exists(PROP_SK): props.skeleton_json(PROP_SK)
    lick = kind == "MF" and target is None and "cunnilingus" in a.get("tags", "").lower()
    clips, report, lint_all, pen = [], [], [], []                # per stage: dict(role -> json), penetration target or None
    gprops, per_stage = [], {}                                   # general props: [(actor index, editor id, mesh, scale)]
    if prop is None:
        plist, per_stage, bad = props.scene_props(a, root)
        if plist:
            if not os.path.exists(PROP_SK): props.skeleton_json(PROP_SK)
            sc = {0: rt.run(XF, fem[0], EVE_SK, keep={"Bip001"})["scale"]}
            if kind != "F": sc[1] = rt.run(XM if kind == "MF" else XF, oth[0], ADAM_SK if kind == "MF" else EVE_SK, keep={"Bip001"})["scale"]
            for k, (ai, oid, path) in enumerate(plist):
                mesh = props.prop_mesh_any(path, sc[ai], "_m" if ai == 1 and kind == "MF" else "", XM if ai == 1 and kind == "MF" else XF)
                W(D + "/prop%d_mesh.json" % k, mesh); gprops.append((ai, oid, mesh, sc[ai]))
        if plist or bad:
            report.append("props: %s%s" % (", ".join("%s (%s)" % (m["name"], "eve" if ai == 0 else partner) for ai, _, m, _ in gprops),
                                           "; unusable: %s" % ", ".join(bad) if bad else ""))
    for i in range(n):
        e = rt.run(XF, fem[i], EVE_SK, keep=keep_for("eve", EVE_SK))
        if kind == "MF":
            ad = rt.run(XM, oth[i], ADAM_SK, keep=keep_for("adam", ADAM_SK)); mg = rt.run(XM, oth[i], MG_SK)
            st = {"eve": slim(e), "adam": slim(ad), "mg": slim(mg)}
            m = min(len(st[r]["frames"]) for r in st)     # partner hkx can be shorter than Eve's: trim before any pass
            for r in st: st[r]["frames"] = st[r]["frames"][:m]
            if target:
                before = ct.check(st["eve"], st["mg"], target)
                if statistics.median(before) <= CONTACT_GATE_CM + (5 if target == "oral" else 0):   # oral: Adam's knee bend closes ~10 cm
                    if target == "oral":
                        oe, og, rep, oa = ct.oral(st["eve"], st["mg"], st["adam"]); st["eve"], st["mg"], st["adam"] = oe, og, oa
                        rep["depth_cm"] = "slide %s, tip short %s cm, adam hips down %s cm" % (rep["eve_slide_cm"], rep["tip_short_cm"], rep["adam_drop_cm"])
                    else:
                        oa, og, rep = ct.run(st["eve"], st["adam"], st["mg"], target); st["adam"], st["mg"] = oa, og
                    after = ct.check(st["eve"], st["mg"], target)
                    report.append("S%d %s contact: miss %.1f -> %.1f cm, depth %s" % (i + 1, target, max(before), max(after), rep["depth_cm"]))
                else:
                    report.append("S%d no contact (median miss %.0f cm > %d: not penetrating)" % (i + 1, statistics.median(before), CONTACT_GATE_CM))
            if lick:
                r = ct.lick(st["eve"], st["adam"], st["mg"])
                if r: st["adam"], st["mg"] = r[0], r[1]; report.append("S%d lick: mouth gap %.1f -> %.1f cm" % (i + 1, r[2], r[3]))
        elif kind == "FF":
            st = {"eve": slim(e), "tachy": slim(rt.run(XF, oth[i], EVE_SK, keep=keep_for("tachy", EVE_SK)))}
        else:
            st = {"eve": slim(e)}
            if prop:
                toy = props.prop_clip(rt.source_world(XF, fem[i]), prop["skyrim_bone"], e["scale"], e["fps"])
                if target: toy, rep = props.align(toy, st["eve"], prop, target); report.append("S%d toy -> %s entry: %s" % (i + 1, target, rep))
                st["toy"] = toy
        m = min(len(st[r]["frames"]) for r in st)        # a partner hkx can differ in length from Eve's: one count per stage
        for r in st: st[r]["frames"] = st[r]["frames"][:m]
        raw = dict(st)                                     # props: SB-vs-Skyrim bone frames come from these (passes copy, never edit)
        # legs (hips untouched, so contacts stay): planted feet stop sliding and sit on the floor; knees out of the other body
        for r in [x for x in ("eve", partner) if x]:
            st[r], frep = legs.plant_feet(st[r], ANKLE_Z[r])
            st[r], npush = legs.spread_legs(st[r], [(o, st[o]) for o in ("eve", partner) if o and o != r],
                                            lambda R_, P_, p_, role: hd.skin(R_, P_, p_, hd.sb_body(role, st[role]["names"])["body"]),
                                            rest_ankle_z=ANKLE_Z[r])
            report.append("S%d %s feet %s, knees pushed out on %d frames" % (i + 1, r, frep, npush))
        # hands: touch what they touched in Skyrim (Skyrim bodies), then never sink into any body; lint what is left
        con = hd.source_contacts(rt.source_world(XF, fem[i]), rt.source_world(XM if kind == "MF" else XF, oth[i]) if oth[i] else None, kind,
                                free_shaft=target not in ("anal", "vaginal"))
        report.append("S%d source touches: %s" % (i + 1, hd.summary(con)))
        penetrating = kind == "MF" and target and statistics.median(before) <= CONTACT_GATE_CM + (5 if target == "oral" else 0)
        if penetrating and target == "vaginal":   # the shaft owns the entry: a hand there (rubbing above it) stays a plain body touch
            con = {r: {sd: [("eve" if t == "vulva:eve" else t) for t in tl] for sd, tl in sides.items()} for r, sides in con.items()}
        if partner and not penetrating:      # his hand belongs on her vulva but he stands too far away: slide him over
            st[partner], mgs, cm = hd.reach_shift(st, con, partner, st.get("mg"))
            if mgs is not None: st["mg"] = mgs
            if cm: report.append("S%d %s moved %.0f cm toward her so his hand reaches her vulva" % (i + 1, partner, cm))
        mg = st.get("mg"); people = {r: st[r] for r in ("eve", partner) if r}
        people = hd.enforce(people, con, mg)
        for r in people: people[r] = hd.unclip(people[r], list(people.items()), contacts=con.get(r))
        st.update(people)
        if prop:   # last: the hand that carries the toy in Skyrim keeps its grip on the (entry-aligned) toy
            st["eve"] = props.hold(st["eve"], st["toy"], rt.source_world(XF, fem[i]), prop["skyrim_bone"], e["scale"])
        if gprops:  # general props ride the FINAL SB bones (after every pass); absent in this stage = hidden
            sw = {0: rt.source_world(XF, fem[i])}
            if kind != "F": sw[1] = rt.source_world(XM if kind == "MF" else XF, oth[i])
            nfr, fps0 = len(st["eve"]["frames"]), st["eve"]["fps"]
            for k, (ai, oid, mesh, scl) in enumerate(gprops):
                holder = "eve" if ai == 0 else partner
                if oid in per_stage.get((ai, i), []):
                    anc = props.anchor_of(sw[ai], mesh["skyrim_bone"], mesh, scl)
                    st["prop%d" % k] = props.track_clip(props.prop_track(sw[ai], mesh["skyrim_bone"], anc, raw[holder], st[holder], scl)[:nfr], fps0)
                    report.append("S%d prop %s rides %s" % (i + 1, mesh["name"], rt.bone_map()[anc] if anc else "the floor"))
                else:
                    st["prop%d" % k] = props.track_clip(None, fps0, nfr)
        if target and kind == "MF":
            miss = statistics.median(ct.check(st["eve"], st["mg"], target)) if penetrating else 0
            if miss > hd.LOST_CM: lint_all.append("S%d %s contact misses by %.0f cm" % (i + 1, target, miss))
        lint_all += ["S%d %s" % (i + 1, x) for x in hd.lint(people, con, mg)]
        clips.append(st); pen.append(target if penetrating else None)
    # ONE clip per scene: each stage loops ~STAGE_SECONDS, then blends into the next stage while both move. 1 slot instead of
    # 2n-1, and no clip swaps for ATOOL/PEFA to pop on. (2026-11-23) Seams are spread over the loop's last 0.2 s per role
    # (no static ease), the blend starts at the best-matching frame pair of the two stages, the shaft is re-aimed through
    # the entry on blends between two penetrating stages, and feet are planted once more on the finished clip.
    fps = clips[0]["eve"]["fps"]; K = max(1, round(tr.XFADE_S * fps))
    cyc = [{r: tr.cycle(st[r], K) for r in st} for st in clips]
    scene, stages, blends, phase = {k: dict(clips[0][k], frames=[]) for k in clips[0]}, [], [], 0
    for i, st in enumerate(clips):
        C = cyc[i]; Lc = len(C["eve"]); loops = max(1, round(STAGE_SECONDS * fps / Lc)); total = loops * Lc
        if i < n - 1:
            e, j, gap = tr.match_phase(st, clips[i + 1], C, cyc[i + 1])
            total += (e - (phase + total - 1)) % Lc                       # play on until the exit frame
        a0 = len(scene["eve"]["frames"]) if i == 0 else blends[-1][0] + (blends[-1][1] - blends[-1][0]) // 2
        for r in scene: scene[r]["frames"] += [C[r][(phase + x) % Lc] for x in range(total)]
        stages.append([a0, len(scene["eve"]["frames"]) - 1, loops])
        if i < n - 1:
            nb = max(2, round(min(1.2, max(0.3, 0.3 + gap / 50.0)) * fps)); b0 = len(scene["eve"]["frames"])
            for r in scene:
                fr, ph = tr.blend_cycles(C[r], cyc[i + 1][r], e, j, nb)
                if r.startswith("prop"):   # a prop appearing / vanishing snaps at mid-blend instead of flying up from the hide spot
                    Ls_, Ld_ = len(C[r]), len(cyc[i + 1][r])
                    for x in range(nb):
                        a_, b_ = C[r][(e + x + 1) % Ls_], cyc[i + 1][r][(j + x + 1) % Ld_]
                        if a_[1][0][2] < -5000 or b_[1][0][2] < -5000: fr[x] = a_ if x < nb // 2 else b_
                scene[r]["frames"] += fr
            phase = ph; blends.append((b0, len(scene["eve"]["frames"]) - 1)); report.append("T%d blend %d frames, pose gap %.0f cm" % (i + 1, nb, gap))
            if pen[i] and pen[i] == pen[i + 1] and "mg" in scene: ct.aim(scene["eve"], scene["mg"], pen[i], range(b0, blends[-1][1] + 1))
    for r in [x for x in ("eve", partner) if x]:
        scene[r], frep = legs.plant_feet(scene[r], ANKLE_Z[r], loop=False); report.append("scene %s feet %s" % (r, frep))
    if prop and SOLO_TOY == "sword" and "toy" in scene:
        scene["sword"] = props.sword_clip(scene.pop("toy"), prop, SWORD_SK, SWORD_POMMEL_Z); report.append("solo toy: Eve's sword, hilt inserted")
    slot = slots[0]; names = {"adam": "Adam_%d", "mg": "Adam_MG_%d", "tachy": "Tachy_%d", "toy": "Toy_%d", "sword": "Sword_%d"}
    skel_of = {"eve": EVE_SK, "adam": ADAM_SK, "mg": MG_SK, "tachy": EVE_SK, "toy": PROP_SK, "sword": SWORD_SK}
    todo = []
    for role, data in scene.items():
        jp = D + "/%d_%s.json" % (slot, role); open(jp, "w").write(json.dumps(fbx_bones(data)))   # dumps = C encoder
        fbx = D + "/fbx/" + (str(slot) if role == "eve" else ("Prop%s_%d" % (role[4:], slot)) if role.startswith("prop") else names[role] % slot) + ".fbx"
        extra = (D + "/prop_mesh.json",) if role == "toy" else (D + "/%s_mesh.json" % role,) if role.startswith("prop") else ()
        todo.append((PROP_SK if role.startswith("prop") else skel_of[role], jp, fbx) + extra)
    length = (len(scene["eve"]["frames"]) - 1) / scene["eve"]["fps"]
    parts = [{"slot": slot, "kind": "scene", "len": round(length, 3), "stages": stages}]
    A = "/Game/Mods/HD-ATOOL_P/anim/%da/" % slot
    if kind == "MF":
        partners = [{"fbx": D + "/fbx/Adam_%d.fbx" % slot, "skeleton": UE_SKEL["adam"], "clip": "Adam_%d" % slot},
                    {"fbx": D + "/fbx/Adam_MG_%d.fbx" % slot, "skeleton": UE_SKEL["mg"], "clip": "Adam_MG_%d" % slot}]
        rows = [{"Name": "NewRow", "Tag": "None", "DevComment": "%s|%sAdam_MG_%d.Adam_MG_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (MG_MESH, A, slot, slot)},
                {"Name": "NewRow_0", "Tag": "ATOOLactor", "DevComment": "%s|RootSocket|%sAdam_%d.Adam_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (ADAM_BP, A, slot, slot)}]
    elif kind == "FF":
        partners = [{"fbx": D + "/fbx/Tachy_%d.fbx" % slot, "skeleton": UE_SKEL["eve"], "clip": "Tachy_%d" % slot}]
        rows = [{"Name": "NewRow", "Tag": "ATOOLactor", "DevComment": "%s|RootSocket|%sTachy_%d.Tachy_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (TACHY_BP, A, slot, slot)}]
    elif prop and "sword" in scene:   # the game's own sword mesh | our clip on its skeleton (remapped like Adam's)
        partners = [{"fbx": D + "/fbx/Sword_%d.fbx" % slot, "skeleton": SWORD_UE + "_Skeleton", "clip": "Sword_%d" % slot}]
        rows = [{"Name": "NewRow", "Tag": "None", "DevComment": "%s.%s|%sSword_%d.Sword_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (SWORD_UE, SWORD_UE.rsplit("/", 1)[1], A, slot, slot)}]
    elif prop:   # solo + prop: the prop is a skeletal-mesh row like the genital rig (mesh | its clip)
        pm = PROP_DIR + "/" + prop["name"]
        partners = [{"fbx": D + "/fbx/Toy_%d.fbx" % slot, "skeleton": pm + "_Skeleton", "clip": "Toy_%d" % slot, "mesh": pm, "remap": False}]
        rows = [{"Name": "NewRow", "Tag": "None", "DevComment": "%s.%s|%sToy_%d.Toy_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (pm, prop["name"], A, slot, slot)}]
    else:
        partners, rows = [], []
    for k, (ai, oid, mesh, scl) in enumerate(gprops):   # general props: one skeletal-mesh row each (mesh | its clip)
        pm = PROP_DIR + "/" + mesh["name"]
        partners.append({"fbx": D + "/fbx/Prop%d_%d.fbx" % (k, slot), "skeleton": pm + "_Skeleton", "clip": "Prop%d_%d" % (k, slot), "mesh": pm,
                         "remap": False, "material": {"name": mesh["material"], "rgb": mesh["rgb"], "rough": mesh["rough"]}})
        rows.append({"Name": "NewRow_%d" % (10 + k), "Tag": "None",
                     "DevComment": "%s.%s|%sProp%d_%d.Prop%d_%d||0.0'0.0'0.0'0.0'0.0'0.0" % (pm, mesh["name"], A, k, slot, k, slot)})
    jpath = D + "/job_%d.json" % slot; W(jpath, {"slot": str(slot), "eve": D + "/fbx/%d.fbx" % slot, "partners": partners, "rows": rows})
    jobs = [jpath]
    with ThreadPoolExecutor(int(os.environ.get("FBX_THREADS", 6))) as ex: list(ex.map(blender_fbx, todo))
    for old in glob.glob(D + "/fbx/*"):        # only now (Blender succeeded): FBX of other slots / the old layout
        if not re.search(r"(^|_)%d(_bones)?\.(fbx|json)$" % slot, os.path.basename(old)): os.remove(old)
    for old in glob.glob(D + "/job_*.json") + glob.glob(D + "/[0-9]*_*.json"):   # per-stage leftovers of the old layout
        if not os.path.basename(old).startswith(str(slot) + "_") and os.path.basename(old) != "job_%d.json" % slot: os.remove(old)
    entry = {"name": a["name"], "pack": pack, "kind": kind, "target": target, "partner": partner,
                                   "parts": parts, "jobs": jobs, "dir": D, "imported": False, "report": report, "prop": prop and prop["name"], "props": [m["name"] for _, _, m, _ in gprops],
                                   "lint": lint_all}
    if save: registry["scenes"][a["id"]] = entry; W(REG, registry)
    print("READY %s (%s, %s, target %s) slot %d, %.0f s, stages %s" % (a["id"], pack, kind, target, slot, length, [x[2] for x in stages]))
    for ln in report: print("   ", ln)
    for ln in lint_all: print("    LINT", ln)
    if not lint_all: print("    LINT clean")
    return entry


def _work(args):
    sid, slots = args
    try: return sid, prepare(sid, {"scenes": {}}, slots, save=False), None
    except BaseException as ex: return sid, None, repr(ex)


def prepare_many(sids, registry):
    """slots are allocated here, in order (no two workers can take the same ones), then scenes run in parallel processes
    (PORT_JOBS, default 3; each runs FBX_THREADS Blenders) and every finished scene is merged + saved at once"""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    jobs = int(os.environ.get("PORT_JOBS", 3)); os.environ.setdefault("FBX_THREADS", str(max(2, 6 // jobs)))
    todo, reserved = [], set()
    sids = list(dict.fromkeys(find_scene(x)[1]["id"] for x in sids))   # dedupe: two workers on one scene folder clobber it
    batch = set(sids)
    if not os.path.exists(PROP_SK): props.skeleton_json(PROP_SK)      # once, before any worker's Blender reads it
    keep = {}                            # a re-prepared one-clip scene keeps its slot (stable for PEFA; a failure can't collide)
    others = used_slots(registry, exclude=batch)
    for sid in sids:
        e = registry["scenes"].get(sid) or {}; pts = e.get("parts", [])
        if len(pts) == 1 and pts[0].get("kind") == "scene" and pts[0]["slot"] not in others | reserved:
            keep[sid] = [pts[0]["slot"]]; reserved.add(pts[0]["slot"])
    for sid in sids:
        root, a, _ = find_scene(sid); kind, _, why = classify(a, root)
        if not kind: print("SKIP", sid, "-", why); continue
        try: slots = keep.get(sid) or allocate(1, used_slots(registry, exclude=batch, reserved=reserved))
        except SystemExit as ex_:                                     # out of ATOOL slots: run what fits, list the rest
            print("NO SLOT LEFT:", ex_, "- not prepared:", " ".join(x for x in sids[sids.index(sid):])); break
        reserved |= set(slots); todo.append((sid, slots))
    from concurrent.futures.process import BrokenProcessPool
    left, breaks = list(todo), 0
    while left:                              # a hard worker crash breaks the whole pool: resubmit what has not finished
        done_now = set()
        try:
            with ProcessPoolExecutor(jobs) as ex:
                futs = {ex.submit(_work, t): t for t in left}
                for fut in as_completed(futs):
                    t = futs[fut]; _merge(registry, fut, t, keep, reserved); done_now.add(t[0])
        except BrokenProcessPool as ex_:
            breaks += 1; print("worker pool broke (%r): %d scenes not finished" % (ex_, len(left) - len(done_now)))
            if breaks >= 3:
                print("giving up on:", " ".join(t[0] for t in left if t[0] not in done_now), "(try PORT_JOBS=1)"); break
        left = [t for t in left if t[0] not in done_now]
    print("prepared %d scenes" % len(todo))


def _merge(registry, fut, t, keep, reserved):
    """one finished worker -> registry (atomic save); a failed scene keeps its old entry unless its slots were reassigned"""
    try: sid, entry, err = fut.result()
    except BrokenPipeError as ex_: sid, entry, err = t[0], None, repr(ex_)
    if entry: registry["scenes"][sid] = entry; W(REG, registry); return
    old = registry["scenes"].get(sid)
    if old and {p["slot"] for p in old.get("parts", [])} & (reserved - set(keep.get(sid, []))):
        registry["scenes"].pop(sid); W(REG, registry)
        print("FAILED", sid, err, "(old entry dropped: its slots were reassigned)")
    else: print("FAILED", sid, err, "(old entry kept)" if old else "")


FBX_KEEP = re.compile(r"String|Prop|Footsteps|Xtra|Nub|Twist|Ponytail|Hair|Skirt|Breast")
def fbx_bones(c):
    """only the bones make_fbx.py keys (body + genitals + toy, plus ancestors): the full 3765-bone Eve rig made 70 MB jsons"""
    nm, par = c["names"], c["parents"]
    keep = {i for i, x in enumerate(nm) if (x.startswith("Bip001") and not FBX_KEEP.search(x)) or x.startswith(("NPC-Genitals", "Genitals", "Schlong"))}
    if not keep: keep = set(range(len(nm)))      # a rig without body bones (Eve's sword): all of it
    for i in list(keep):
        p = par[i]
        while p >= 0: keep.add(p); p = par[p]
    keep = sorted(keep); new = {o: k for k, o in enumerate(keep)}
    out = {"names": [nm[i] for i in keep], "parents": [new.get(par[i], -1) for i in keep], "fps": c["fps"],
           "frames": [[f[i] for i in keep] for f in c["frames"]]}
    if c.get("root_scale"): out["root_scale"] = c["root_scale"]
    return out


_keep = {}
def keep_for(role, skel):
    """bones a role's clip keeps: animated body bones + genitals (what make_fbx keys) + the bones its body model hangs on.
    Everything else is rest pose relative to its parent, so dropping it changes nothing but memory (1.6 MB/frame on Eve)."""
    if role not in _keep:
        names = rt.ue.load_skeleton(skel)["names"]
        _keep[role] = {n for n in names if (n.startswith("Bip001") and not FBX_KEEP.search(n)) or n.startswith(("NPC-Genitals", "Genitals", "Schlong"))} | hd.body_bones(role)
    return _keep[role]


def slim(r):
    return {"names": r["names"], "parents": r["parents"], "fps": r["fps"], "frames": r["frames"]}


# ------------------------------------------------------------------ build
def run(cmd, log, cwd=None):
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        return subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=cwd).returncode

def plugins(on):
    d = J(PROJ)
    if on: d["Plugins"] = [{"Name": "PythonScriptPlugin", "Enabled": True}, {"Name": "EditorScriptingUtilities", "Enabled": True}]
    else: d.pop("Plugins", None)
    W(PROJ, d)

OPTIONAL = {"Leito": ("Rough", "_nc_")}   # pack -> (suffix, scene-id marker): Leito's bound / aggressive scenes ship as an
                                           # optional pak + PELA file of their own (user, 2026-11-23: some people won't want them)


def release_pack(sid, s):
    """the pak / PELA group a scene ships in: its source pack, or the pack's optional variant"""
    suf, mark = OPTIONAL.get(s["pack"], (None, None))
    return s["pack"] + suf if suf and mark in sid.lower() else s["pack"]


def pack_groups(registry, only=()):
    """scenes -> paks: one per source pack, split so no container holds more than MAX_PAK_ASSETS (a single 938-asset container
    crashed the game at startup, 2026-11-22, while two ~470-asset ones with the same content loaded fine)"""
    groups, group_of, count, of_pack = [], {}, {}, {}      # of_pack: pack -> its groups (a pack named "X2" broke rstrip(digits))
    scenes = sorted(((sid, s) for sid, s in registry["scenes"].items() if (not only or sid in only) and s["pack"] not in DISABLED_PACKS and sid not in DISABLED_SCENES), key=lambda kv: (release_pack(*kv), kv[1]["parts"][0]["slot"]))
    for sid, s in scenes:
        n = sum({"MF": 4, "FF": 3, "F": 3}[s["kind"]] for _ in s["parts"]) + (3 if s.get("prop") else 0) + 3 * len(s.get("props") or [])
        rp = release_pack(sid, s); mine = of_pack.setdefault(rp, [])
        g = next((x for x in reversed(mine) if count[x] + n <= MAX_PAK_ASSETS), None)
        if not g:
            g = rp + (str(len(mine) + 1) if mine else ""); groups.append(g); mine.append(g); count[g] = 0
        group_of[sid] = g; count[g] += n
    # chunk N -> container "pakchunkN" -> IoStore container ID = hash of that name. Chunks 1-3 collided with the game's own
    # pakchunk1-3 (PSO, DLC_1, DLC_2), and a shared ID means only one container mounts (2026-11-22). Unusual numbers only.
    book = registry.setdefault("chunks_test" if TEST else "chunks", {})   # group -> chunk, never reused (released paks keep ids)
    for p in groups:
        if p not in book: book[p] = max(list(book.values()) + [(7400 if TEST else 7300) - 1]) + 1
        PACK_CHUNK[p] = book[p]
    return groups, group_of, scenes


def build():
    registry = reg(); os.makedirs(R + "/log", exist_ok=True)
    only = [x for x in os.environ.get("PORT_ONLY", "").split(",") if x]   # test builds: pack only these scenes
    # One pak per pack, split so no container holds more than MAX_PAK_ASSETS: a single 938-asset container crashed the
    # game at startup (2026-11-22) while two ~470-asset containers with the same content loaded fine.
    packs, group_of, scenes = pack_groups(registry, only)
    jobs, assets = [], {p: [] for p in packs}
    keep, shipped = set(), set()
    for sid, s in scenes:
        for jp in s["jobs"]:
            j = J(jp); j["import"] = not s.get("imported"); jobs.append(j); slot = j["slot"]; keep.add(int(slot))
            base = "/Game/Mods/HD-ATOOL_P/anim/"
            assets[group_of[sid]] += [base + slot, base + slot + "a"] + [base + slot + "a/" + p["clip"] for p in j["partners"]]
            for p in j["partners"]:          # prop mesh/skeleton/material: once, in the first pack that uses them
                mat = PROP_DIR + "/" + (p.get("material") or {}).get("name", "M_SkyrimSilicone")
                for x in ([p["mesh"], p["mesh"] + "_Skeleton", mat] if p.get("mesh") else []):
                    if x not in shipped: shipped.add(x); assets[group_of[sid]].append(x)
    stale = [] if only else sorted(ours_in_project() - keep)
    plan = {"jobs": jobs, "packs": {p: {"chunk": PACK_CHUNK[p], "assets": assets[p]} for p in packs},
            "delete": ["/Game/Mods/HD-ATOOL_P/anim/%d" % s for s in stale] + ["/Game/Mods/HD-ATOOL_P/anim/%da" % s for s in stale],
            "delete_dirs": ["/Game/Mods/HD-ATOOL_P/anim/%da" % s for s in stale], "tracks_out": R + "/work/tracks_all.json"}
    W(R + "/work/plan.json", plan)
    plugins(True)
    print("== UE batch (%d jobs, %d stale slots removed)" % (len(jobs), len(stale)))
    run([UE, PROJ, "-run=pythonscript", "-script=%s/ue/batch_sb.py %s/work/plan.json" % (R, R), "-unattended", "-nopause", "-nosplash", "-stdout"], R + "/log/batch.log")
    bl = open(R + "/log/batch.log", encoding="utf-8", errors="replace").read()
    fails = re.findall(r"SB\| (CLIP FAIL .*|MISSING .*)", bl)
    if "SB| BATCH DONE" not in bl or fails: raise SystemExit("UE batch failed: %s (see log/batch.log)" % fails[:5])
    for sid, s in registry["scenes"].items():
        if sid in group_of: s["imported"] = True                # PORT_ONLY builds import only their own scenes
    W(REG, registry)
    print("== cook"); shutil.rmtree(cfg.MODKIT + "/Saved/Cooked", ignore_errors=True)
    common = ["-project=" + PROJ.replace("/", "\\"), "-noP4", "-platform=Win64", "-clientconfig=Shipping", "-nocompileeditor", "-skipbuildeditor", "-nocompile", "-nobuild", "-utf8output"]
    if run([UAT_DIR + "/AutomationTool.exe", "BuildCookRun", "-cook", "-skipstage", "-unversionedcookedcontent"] + common, R + "/log/cook.log", cwd=UAT_DIR):
        raise SystemExit("cook failed, see log/cook.log")
    print("== remap"); tracks = R + "/work/tracks_all.json"
    import remap_sb
    for j in jobs:
        s = j["slot"]
        remap_sb.main(COOK + "/%s.uasset" % s, "/Game/Mods/HD-ATOOL_P/anim/" + s, tracks, EVE_SK)
        for p in j["partners"]:
            if p.get("remap") is False: continue     # our own prop skeleton ships with the clip: nothing to remap
            sk = SK + p["skeleton"].rsplit("/", 1)[1] + ".json"
            remap_sb.main(COOK + "/%sa/%s.uasset" % (s, p["clip"]), "/Game/Mods/HD-ATOOL_P/anim/%sa/%s" % (s, p["clip"]), tracks, sk)
    print("== pak"); plugins(False)
    rc = run([UAT_DIR + "/AutomationTool.exe", "BuildCookRun", "-skipcook", "-stage", "-pak", "-iostore"] + common, R + "/log/pak.log", cwd=UAT_DIR)
    plugins(True)
    if rc: raise SystemExit("pak failed, see log/pak.log")
    install(registry, packs, group_of)

def write_sounds(registry, sids):
    """ATOOL audio/<slot>.wav per one-clip scene; redone only when the scene or sound.py is newer than the wav"""
    src = os.path.getmtime(R + "/tools/sound.py"); n = 0
    for sid in sids:
        s = registry["scenes"][sid]; pt = s["parts"][0]
        if pt["kind"] != "scene": continue
        out = sound.AUDIO + "%d.wav" % pt["slot"]
        if os.path.exists(out) and os.path.getmtime(out) > max(src, *(os.path.getmtime(j) for j in s["jobs"])): continue
        sound.build(s, s["dir"], s.get("partner"), s.get("target"), out); n += 1
    print("sounds: %d written" % n)


def install(registry, packs, group_of):
    ns = {}; exec(open(R + "/tools/_utoc.py").read().split("res = collections")[0], ns); utoc_paths = ns["utoc_paths"]   # own namespace: it defines GAME too
    os.makedirs(INSTALL, exist_ok=True); os.makedirs(R + "/dist", exist_ok=True)
    if subprocess.run(["tasklist", "/FI", "IMAGENAME eq SB-Win64-Shipping.exe"], capture_output=True, text=True).stdout.count("SB-Win64"):
        raise SystemExit("Stellar Blade is running: close it before installing (its paks are locked)")
    for g in packs:                          # container ids of the new paks vs every OTHER installed container, before deleting
        b = open(STAGED + "/pakchunk%d-WindowsNoEditor.utoc" % PACK_CHUNK[g], "rb").read(64); cid = struct.unpack_from("<Q", b, 56)[0]
        for f in glob.glob(GAME + "/Content/Paks/**/*.utoc", recursive=True):
            if INSTALL.replace("/", "\\") in f.replace("/", "\\"): continue
            h = open(f, "rb").read(64)
            if h[:16] == b"-==--==--==--==-" and struct.unpack_from("<Q", h, 56)[0] == cid:
                raise SystemExit("chunk %d (%s) has the same container id as %s: pick another chunk" % (PACK_CHUNK[g], g, f))
    for f in glob.glob(INSTALL + "/*"): os.remove(f)                              # only our own folder
    for f in glob.glob(R + "/dist/Eve_*"): os.remove(f)
    for g in packs:
        name = "Eve_%d_Skyrim%s_P" % (PACK_CHUNK[g], g)       # stable across updates (was the lowest slot, which moves)
        if TEST: name = name.replace("_P", "Test_P")      # own PEFA group (PEFA groups clips by pak name)
        for e in ("pak", "utoc", "ucas"):
            src = STAGED + "/pakchunk%d-WindowsNoEditor.%s" % (PACK_CHUNK[g], e)
            shutil.copy(src, INSTALL + "/%s.%s" % (name, e)); shutil.copy(src, R + "/dist/%s.%s" % (name, e))
        xs = utoc_paths(open(INSTALL + "/%s.utoc" % name, "rb").read()) or []
        print("installed %s: %d assets" % (name, len(xs)))
    clash = container_clashes()
    if clash: raise SystemExit("IoStore container ID shared with another pak (only one would load): %s" % clash)
    write_sounds(registry, group_of)
    # PELA: one file per source pack, one sequence per scene, stages loop ~7 s, transitions play once, climax last
    for p in sorted({release_pack(sid, s) for sid, s in registry["scenes"].items() if sid in group_of}):
        seqs, singles = [], []
        for sid, s in sorted(registry["scenes"].items()):
            if release_pack(sid, s) != p or sid not in group_of: continue
            parts = []
            stages = [pt for pt in s["parts"] if pt["kind"] == "stage"]
            for pt in s["parts"]:
                if pt["kind"] == "scene":           # one-clip scene: loops/transitions are baked in, climax when the last stage starts
                    last = pt["stages"][-1]
                    parts.append({"clip": pt["slot"], "loops": 1, "climax": True, "climaxAt": round(last[0] * pt["len"] / last[1], 2)})
                    if os.path.exists(sound.AUDIO + "%d.wav" % pt["slot"]): parts[-1]["climaxSound"] = False   # our wav has the orgasm
                    singles.append(pt["slot"]); continue
                if pt["kind"] == "stage":
                    d = {"clip": pt["slot"], "loops": max(1, round(STAGE_SECONDS / max(pt["len"], 0.05)))}
                    if pt is stages[-1]: d["climax"] = True
                    singles.append(pt["slot"])
                else:
                    d = {"clip": pt["slot"], "loops": 1}
                parts.append(d)
            seqs.append({"name": s["name"], "parts": parts})
        tag = " (test)" if TEST else ""
        W(PELA_DIR + "/Skyrim Port - %s%s.json" % (p, tag), {"name": "Skyrim Port - " + p + tag, "enabled": True, "sequences": seqs, "singles": singles})
    import sheet
    os.makedirs(R + "/work/sheets", exist_ok=True)
    for sid, s in registry["scenes"].items():
        if sid not in group_of: continue
        try: shutil.copy(sheet.render(s["dir"], s, s.get("target")), R + "/work/sheets/%s.png" % sid)
        except Exception as ex: print("sheet failed", sid, ex)
    print("contact sheets: work/sheets/")
    write_lint(registry)
    # PEFA window names: "<scene> S1" for stages, "<scene> T1" for transitions (else it shows bare slot numbers)
    nf = PEFA + "/names.txt"; built = {pt["slot"]: (s["name"], pt) for sid, s in registry["scenes"].items() if sid in group_of for pt in s["parts"]}
    ranges = set() if TEST else {x for lo, hi in SLOT_RANGES for x in range(lo, hi + 1)}     # our ranges: drop names of old layouts
    lines = [l for l in open(nf, encoding="utf-8", errors="replace").read().splitlines() if not ((m := re.match(r"(\d+)\s*=", l)) and (int(m.group(1)) in built or int(m.group(1)) in ranges))]
    for slot, (nm, pt) in sorted(built.items()):
        same = [p for p in registry["scenes"][next(k for k, s in registry["scenes"].items() if s["name"] == nm)]["parts"] if p["kind"] == pt["kind"]]
        if pt["kind"] == "scene": lines.append("%d = %s" % (slot, nm)); continue
        lines.append("%d = %s %s%d" % (slot, nm.replace("Leito ", ""), "S" if pt["kind"] == "stage" else "T", same.index(pt) + 1))
    open(nf, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    if not TEST:                              # PELA files of packs we no longer build (e.g. the old "LeitoB")
        want = {"Skyrim Port - %s.json" % release_pack(sid, s) for sid, s in registry["scenes"].items() if s["pack"] not in DISABLED_PACKS}
        for f in glob.glob(PELA_DIR + "/Skyrim Port - *.json"):
            if "(test)" not in f and os.path.basename(f) not in want: os.remove(f)
    old = PELA_DIR + "/Skyrim Port.json"
    if os.path.exists(old): os.remove(old)
    # PEFA caches rows per pak: drop rows of our slots so it re-reads the new tables
    ours = {pt["slot"] for s in registry["scenes"].values() for pt in s["parts"]} | set(range(1000, 1005))
    if not TEST: ours |= {x for lo, hi in SLOT_RANGES for x in range(lo, hi + 1)}   # rows of the old 9-slot layout too
    for fn in ("packs_rows.txt", "packs_cache.txt"):
        fp = PEFA + "/" + fn
        lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
        keep = [l for l in lines if not ((m := re.match(r"(\d+)[\t =]", l)) and int(m.group(1)) in ours) and "Skyrim" not in l]
        open(fp, "w", encoding="utf-8").write("\n".join(keep) + "\n")


def container_clashes():
    """our installed .utoc files whose container ID (header offset 56) another installed container also uses"""
    ids = {}
    for f in glob.glob(GAME + "/Content/Paks/**/*.utoc", recursive=True):
        b = open(f, "rb").read(64)
        if b[:16] == b"-==--==--==--==-": ids.setdefault(struct.unpack_from("<Q", b, 56)[0], []).append(f.replace("\\", "/"))
    return [fs for fs in ids.values() if len(fs) > 1 and any(INSTALL + "/" in x for x in fs)]


def write_lint(registry):
    """work/lint.txt: every stage problem left after the passes -> the only stages worth playtesting"""
    lines = []
    for sid, s in sorted(registry["scenes"].items()):
        if s["pack"] in DISABLED_PACKS or sid in DISABLED_SCENES: continue      # not built: their old lint is just noise
        for x in s.get("lint", []): lines.append("%-34s %s" % (s["name"], x))
    open(R + "/work/lint.txt", "w").write("".join(l + "\n" for l in lines))
    flagged = len({l[:34] for l in lines})
    built = sum(1 for sid, s in registry["scenes"].items() if s["pack"] not in DISABLED_PACKS and sid not in DISABLED_SCENES)
    print("lint: %d issues in %d of %d built scenes -> work/lint.txt" % (len(lines), flagged, built))


# ------------------------------------------------------------------ CLI
def main(argv):
    if not argv: print(__doc__); return
    cmd, rest = argv[0], argv[1:]
    registry = reg()
    if cmd == "list":
        for f in slal_files():
            if rest and rest[0].lower() not in f.lower(): continue
            root = f.replace("\\", "/").rsplit("/SLAnims", 1)[0]
            for a in load_slal(f).get("animations", []):
                k, t, why = classify(a, root)
                print("%-4s %-8s %-40s %s" % (k or "-", t or "-", a["id"], "" if why == "ok" else why))
    elif cmd == "scene":
        if len(rest) == 1: prepare(rest[0], registry)
        else: prepare_many(rest, registry)
    elif cmd == "pack":
        ids = []
        for f in slal_files():
            if not any(x.lower() in (os.path.basename(f).lower(), f.replace("\\", "/").lower()) for x in rest): continue
            for a in load_slal(f).get("animations", []):
                if a["id"] in registry["scenes"]: print("already prepared", a["id"])
                else: ids.append(a["id"])
        prepare_many(ids, registry)
    elif cmd == "drop":
        for sid in rest: registry["scenes"].pop(sid, None)
        W(REG, registry)
    elif cmd in ("build", "install") and os.environ.get("PORT_REG") and not TEST:
        raise SystemExit("PORT_REG is set without PORT_ONLY: that would build/install the real port from a registry copy")
    elif cmd == "build":
        build()
    elif cmd == "install":     # re-copy the last staged build + PELA/names/sheets, no Unreal (e.g. after a failed install step)
        only = [x for x in os.environ.get("PORT_ONLY", "").split(",") if x]
        packs, group_of, _ = pack_groups(registry, only); install(registry, packs, group_of)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
