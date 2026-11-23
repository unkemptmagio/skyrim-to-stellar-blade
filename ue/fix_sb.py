# UE 4.26 commandlet after import_sb.py: name clips exactly (import leaves *_Anim), fill the partner table, report.
# run: UE4Editor-Cmd.exe SB.uproject -run=pythonscript -script="fix_sb.py <job.json>"
import sys, json, unreal
job = json.load(open(sys.argv[1])); slot = job["slot"]
lib = unreal.EditorAssetLibrary; DTL = unreal.DataTableFunctionLibrary
ANIM = "/Game/Mods/HD-ATOOL_P/anim"
clips = [(ANIM, slot)] + [(ANIM + "/" + slot + "a", p["clip"]) for p in job.get("partners", [])]
for d, c in clips:
    if lib.does_asset_exist(d + "/" + c + "_Anim") and not lib.does_asset_exist(d + "/" + c):
        unreal.log_warning("RENAME %s %s" % (c, lib.rename_asset(d + "/" + c + "_Anim", d + "/" + c)))
    s = unreal.load_asset(d + "/" + c)
    unreal.log_warning("CLIP %s/%s %s len=%s skel=%s" % (d, c, s.get_class().get_name() if s else None,
        s.get_editor_property("sequence_length") if s else None, s.get_editor_property("skeleton").get_path_name() if s else None))

dt = unreal.load_asset(ANIM + "/" + slot + "a")
def q(s): return '"' + s.replace('"', '""') + '"'
csv = "---,Tag,DevComment\n" + "\n".join('%s,%s,%s' % (r["Name"], "" if r["Tag"] == "None" else r["Tag"], q(r["DevComment"])) for r in job["rows"])
ok = DTL.fill_data_table_from_csv_string(dt, csv)
unreal.log_warning("TABLE csv fill=%s rows=%s" % (ok, [str(n) for n in DTL.get_data_table_row_names(dt)]))
for r in job["rows"]:
    unreal.log_warning("ROW %s tag=%s comment=%s" % (r["Name"], DTL.get_data_table_column_as_string(dt, "Tag") if False else "",
                                                   DTL.get_data_table_column_as_string(dt, "DevComment")))
    break
lib.save_asset(ANIM + "/" + slot + "a")
lib.save_directory("/Game", only_if_is_dirty=False, recursive=True)
unreal.log_warning("FIX DONE")
