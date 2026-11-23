# package.py: release zips from the installed build, in the game's folder layout (unzip into the folder that holds SB).
#   python tools/package.py [version]      -> release/SkyrimPort-<Pack>_<version>.zip per release group (e.g. Leito, LeitoRough)
import sys, os, json, glob, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg

R = cfg.ROOT; G = cfg.SB_GAME; VER = sys.argv[1] if len(sys.argv) > 1 else "v1.0b"
NAMES = {"Leito": "Leito-Base", "LeitoRough": "Leito-Rough"}


def main():
    sys.path.insert(0, R); import port
    reg = port.reg(); packs, group_of, _ = port.pack_groups(reg)
    readme = R + "/release/SkyrimPort-Leito/README.txt"
    for g in packs:
        if port.TEST: raise SystemExit("unset PORT_ONLY: package the release build")
        pak = "Eve_%d_Skyrim%s_P" % (port.PACK_CHUNK[g], g)
        files = [(p, "SB/Content/Paks/~mods/_SkyrimPort/" + os.path.basename(p)) for p in glob.glob(port.INSTALL + "/" + pak + ".*")]
        if len(files) != 3: raise SystemExit("%s: pak / ucas / utoc not installed (%d found): build first" % (g, len(files)))
        slots = sorted(reg["scenes"][sid]["parts"][0]["slot"] for sid, x in group_of.items() if x == g)
        for s in slots:
            w = G + "/Content/Paks/LogicMods/HD-ATOOL_P/audio/%d.wav" % s
            if os.path.exists(w): files.append((w, "SB/Content/Paks/LogicMods/HD-ATOOL_P/audio/%d.wav" % s))
        pela = G + "/Content/Paks/~mods/PELA Patches/Skyrim Port - %s.json" % g
        if os.path.exists(pela): files.append((pela, "SB/Content/Paks/~mods/PELA Patches/" + os.path.basename(pela)))
        out = R + "/release/SkyrimPort-%s_%s.zip" % (NAMES.get(g, g), VER)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for src, arc in files: z.write(src, arc)
            z.write(readme, "README - Skyrim Port Leito.txt")
        print("%s: %d scenes, %d sounds, %s -> %s (%.1f MB)" % (g, len(slots), sum(a.endswith(".wav") for _, a in files),
              "PELA" if os.path.exists(pela) else "no PELA", os.path.basename(out), os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
