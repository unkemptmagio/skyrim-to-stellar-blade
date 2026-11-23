# Lists pak mods that ship files at vanilla paths (/Game/Art/Character/...), i.e. replacers.
# .utoc: parses the IoStore directory index (located via its mount-point string).
# .pak : greps the full-directory-index path strings.
# ponytail: mount-point search instead of a full TOC header parser; fine for SB's UE4.26 containers.
import struct, re, pathlib, datetime, collections
import sys as _sys; _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent) if "__file__" in globals() else "tools"); import cfg as _cfg
GAME = pathlib.Path(_cfg.SB_GAME) / "Content" / "Paks" / "~mods"
STAGE = pathlib.Path(_cfg.VORTEX_SB)
CUTOFF = datetime.datetime(2026, 11, 20, 16, 5).timestamp()
VANILLA = re.compile(r"(?:^|/)(?:SB/Content|Game)/Art/Character/", re.I)

def fstr(b, o):
    n = struct.unpack_from("<i", b, o)[0]; o += 4
    if n == 0: return "", o
    if n < 0:  # utf-16
        n = -n; s = b[o:o + 2 * n].decode("utf-16-le", "replace"); return s.rstrip("\0"), o + 2 * n
    return b[o:o + n].decode("latin-1").rstrip("\0"), o + n

def utoc_paths(b):
    for m in re.finditer(rb"\.\./\.\./\.\./", b):
        o = m.start() - 4
        try:
            mount, o = fstr(b, o)
            nd = struct.unpack_from("<I", b, o)[0]; o += 4
            if not 0 < nd < 200000: continue
            dirs = [struct.unpack_from("<IIII", b, o + 16 * i) for i in range(nd)]; o += 16 * nd
            nf = struct.unpack_from("<I", b, o)[0]; o += 4
            if not 0 <= nf < 500000: continue
            files = [struct.unpack_from("<III", b, o + 12 * i) for i in range(nf)]; o += 12 * nf
            ns = struct.unpack_from("<I", b, o)[0]; o += 4
            if not 0 < ns < 500000: continue
            strs = []
            for _ in range(ns):
                s, o = fstr(b, o); strs.append(s)
        except (struct.error, IndexError, UnicodeDecodeError):
            continue
        NONE = 0xFFFFFFFF; out = []
        def walk(di, prefix, depth=0):
            while di != NONE and depth < 64:
                name, child, sib, ff = dirs[di]
                path = prefix + (strs[name] + "/" if name != NONE else "")
                f = ff
                while f != NONE:
                    out.append(mount + path + strs[files[f][0]]); f = files[f][1]
                walk(child, path, depth + 1); di = sib
        try:
            walk(0, ""); return out
        except IndexError:
            continue
    return None

def pak_paths(b):
    return [s.decode("latin-1") for s in re.findall(rb"(?:\.\./)*[\w/]*Art/Character/[\x21-\x7e]{1,200}", b[-8_000_000:])]

res = collections.defaultdict(lambda: {"van": set(), "total": 0, "unparsed": False})
for p in GAME.rglob("*"):
    suf = p.suffix.lower()
    if suf not in (".utoc", ".pak") or not p.is_file(): continue
    if suf == ".pak" and p.with_suffix(".utoc").exists(): continue  # IoStore stub pak
    folder = p.relative_to(GAME).parts[0]
    mod = folder[4:] if re.match(r"^[A-Z]{3}-", folder) else folder
    b = p.read_bytes()
    paths = utoc_paths(b) if suf == ".utoc" else pak_paths(b)
    r = res[mod]
    if paths is None: r["unparsed"] = True; continue
    r["total"] += len(paths)
    r["van"].update(x.split("Art/Character/", 1)[1] for x in paths if VANILLA.search(x) or suf == ".pak")

rows = []
for mod, r in res.items():
    if not r["van"] and not r["unparsed"]: continue
    d = STAGE / mod
    new = d.exists() and d.stat().st_ctime > CUTOFF
    rows.append((new, len(r["van"]), mod, r))
rows.sort(key=lambda t: (not t[0], -t[1]))
for new, n, mod, r in rows:
    tag = "UNPARSED" if r["unparsed"] and not n else f"{n:4d} vanilla files"
    folders = sorted({v.split("/")[1] if v.startswith("PC/") else v.split("/")[0] for v in r["van"]})
    print(f"{'NEW' if new else 'old'} | {tag} | {mod}")
    if folders: print("      ", " ".join(folders[:14]) + (" ..." if len(folders) > 14 else ""))
