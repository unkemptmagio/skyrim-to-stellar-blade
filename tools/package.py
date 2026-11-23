# package.py: release zips from the installed build, in the game's folder layout (unzip into the folder that holds SB).
#   python tools/package.py [version]      -> release/SkyrimPort-<Pack>_<version>.zip per release group (e.g. Leito, LeitoRough)
import sys, os, json, glob, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg

R = cfg.ROOT; G = cfg.SB_GAME; VER = sys.argv[1] if len(sys.argv) > 1 else "v1.0b"
NAMES = {"Leito": "Leito-Base", "LeitoRough": "Leito-Rough", "BillyyExperimental": "Billyy-Experimental"}
README = {"BillyyExperimental": "release/SkyrimPort-Billyy/README.txt"}     # default: the Leito readme
VERSION = {"BillyyExperimental": "v0.1-experimental"}                        # default: the command-line version


def main():
    sys.path.insert(0, R); import port
    reg = port.reg(); packs, group_of, _ = port.pack_groups(reg)
    if port.TEST: raise SystemExit("unset PORT_ONLY: package the release build")
    rel = {}                                   # release group -> its paks (a big pack is split: Billyy, Billyy2, ...)
    for sid, g in group_of.items(): rel.setdefault(port.release_pack(sid, reg["scenes"][sid]), set()).add(g)
    for g, paks in sorted(rel.items()):
        readme = R + "/" + README.get(g, "release/SkyrimPort-Leito/README.txt")
        files = []
        for pk in sorted(paks):
            pak = "Eve_%d_Skyrim%s_P" % (port.PACK_CHUNK[pk], pk); got = glob.glob(port.INSTALL + "/" + pak + ".*")
            if len(got) != 3: raise SystemExit("%s: pak / ucas / utoc not installed (%d found): build first" % (pk, len(got)))
            files += [(p, "SB/Content/Paks/~mods/_SkyrimPort/" + os.path.basename(p)) for p in got]
        slots = sorted(reg["scenes"][sid]["parts"][0]["slot"] for sid, x in group_of.items() if x in paks)
        for s in slots:
            w = G + "/Content/Paks/LogicMods/HD-ATOOL_P/audio/%d.wav" % s
            if os.path.exists(w): files.append((w, "SB/Content/Paks/LogicMods/HD-ATOOL_P/audio/%d.wav" % s))
        pela = G + "/Content/Paks/~mods/PELA Patches/Skyrim Port - %s.json" % g
        if os.path.exists(pela): files.append((pela, "SB/Content/Paks/~mods/PELA Patches/" + os.path.basename(pela)))
        out = R + "/release/SkyrimPort-%s_%s.zip" % (NAMES.get(g, g), VERSION.get(g, VER))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for src, arc in files: z.write(src, arc)
            z.write(readme, "README - Skyrim Port %s.txt" % NAMES.get(g, g).replace("-", " "))
        print("%s: %d scenes, %d sounds, %s -> %s (%.1f MB)" % (g, len(slots), sum(a.endswith(".wav") for _, a in files),
              "PELA" if os.path.exists(pela) else "no PELA", os.path.basename(out), os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
