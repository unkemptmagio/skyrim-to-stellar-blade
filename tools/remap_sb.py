# Remap cooked UE 4.26 AnimSequence bone indices from the stub skeleton's order to the game skeleton's order.
# Patches every tagged BoneTreeIndex (TrackToSkeletonMapTable) and the raw CompressedTrackToSkeletonMapTable in the .uexp.
# usage: remap_sb.py <cooked anim .uasset> <tracks.json key> <tracks.json> <game skeleton.json>
# (adapted from the Subverse GalleryDance remap_tracks.py; 4.26 cooks still write tagged properties here)
import struct, sys, json


def fstring(d, o):
    n = struct.unpack_from("<i", d, o)[0]; o += 4
    if n < 0: return d[o:o - n * 2].decode("utf-16-le").rstrip("\0"), o - n * 2
    return d[o:o + n].decode("latin-1").rstrip("\0"), o + n


def names(uasset):
    d = open(uasset, "rb").read(); o = 4
    legacy = struct.unpack_from("<i", d, o)[0]; o += 4
    if legacy != -4: o += 4
    o += 8
    ncv = struct.unpack_from("<i", d, o)[0]; o += 4 + ncv * 20
    o += 4; _, o = fstring(d, o); o += 4
    count, off = struct.unpack_from("<ii", d, o)
    out, o = [], off
    for _ in range(count):
        s, o = fstring(d, o); o += 4; out.append(s)
    return out


def main(ua, key, tracks_json, skel_json):
    tracks = json.load(open(tracks_json))[key]
    sk = next(e for e in json.load(open(skel_json)) if e.get("Type") == "Skeleton")["ReferenceSkeleton"]
    gi = {b["Name"]: i for i, b in enumerate(sk["FinalRefBoneInfo"])}
    miss = [n for n in tracks if n not in gi]; assert not miss, "bones not in game skeleton: %s" % miss
    nm = names(ua); bti, intp = nm.index("BoneTreeIndex"), nm.index("IntProperty")
    d = bytearray(open(ua[:-7] + ".uexp", "rb").read())
    tag = struct.pack("<iiiiii", bti, 0, intp, 0, 4, 0)
    slots, o = [], d.find(tag)
    while o >= 0: slots.append(o + len(tag) + 1); o = d.find(tag, o + 1)
    vals = [struct.unpack_from("<i", d, s)[0] for s in slots]
    # tagged table skips nothing in 4.26; track i -> stub bone vals[i], stub order == track order here
    assert len(vals) in (len(tracks), len(tracks) - 1), (len(vals), len(tracks))
    raw = d.find(struct.pack("<i", len(tracks)) + struct.pack("<%di" % len(tracks), *range(len(tracks))))
    assert raw >= 0, "raw track table not found"
    new = [gi[t] for t in tracks]
    for s, v in zip(slots, vals): struct.pack_into("<i", d, s, new[v])
    struct.pack_into("<%di" % len(new), d, raw + 4, *new)
    open(ua[:-7] + ".uexp", "wb").write(d)
    print("remapped %s: %d tagged + raw @%d, e.g. %s" % (ua.rsplit("/", 1)[-1], len(slots), raw, list(zip(tracks[:4], new[:4]))))


if __name__ == "__main__":
    main(*sys.argv[1:5])
