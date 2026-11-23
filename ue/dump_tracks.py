# UE 4.26 commandlet: write track names (track order) of each clip to <out.json>
import sys, json, unreal
out, paths = sys.argv[1], sys.argv[2:]
res = {p: [str(n) for n in unreal.AnimationLibrary.get_animation_track_names(unreal.load_asset(p))] for p in paths}
json.dump(res, open(out, "w"), indent=0); unreal.log_warning("TRACKS %s" % {p: len(v) for p, v in res.items()})
