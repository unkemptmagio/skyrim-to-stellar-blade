# UE 4.26 commandlet: build stub skeletons at the game's paths, import ATOOL clips, make the partner table + chunk label.
# run: UE4Editor-Cmd.exe SB.uproject -run=pythonscript -script="import_sb.py <job.json>"
# job.json: {"slot": "1000", "eve": "<fbx>", "partners": [{"fbx": ..., "skeleton": "/Game/..._Skeleton", "clip": "Adam_1000"}],
#            "rows": [{"Name": "NewRow", "Tag": "None", "DevComment": "..."}]}
import sys, json, unreal

job = json.load(open(sys.argv[1]))
lib = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
ANIM = "/Game/Mods/HD-ATOOL_P/anim"
slot = job["slot"]


def task(fbx, dest, name, ui):
    t = unreal.AssetImportTask()
    for k, v in (("filename", fbx), ("destination_path", dest), ("destination_name", name), ("automated", True),
                 ("replace_existing", True), ("save", True), ("options", ui)):
        t.set_editor_property(k, v)
    tools.import_asset_tasks([t])
    return list(t.get_editor_property("imported_object_paths"))


def stub_skeleton(fbx, skel_path):
    """first clip on a skeleton builds it (rest pose = game rest, written into the FBX)."""
    if lib.does_asset_exist(skel_path):
        return unreal.load_asset(skel_path)
    d, n = skel_path.rsplit("/", 1)
    ui = unreal.FbxImportUI()
    for k, v in (("import_mesh", True), ("import_as_skeletal", True), ("import_animations", False), ("import_materials", False),
                 ("import_textures", False), ("create_physics_asset", False)):
        ui.set_editor_property(k, v)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    stub = "Stub_" + n
    unreal.log_warning("STUB MESH %s" % task(fbx, d, stub, ui))
    unreal.log_warning("STUB RENAME %s" % lib.rename_asset(d + "/" + stub + "_Skeleton", skel_path))
    return unreal.load_asset(skel_path)


def clip(fbx, skeleton, dest, name):
    ui = unreal.FbxImportUI()
    for k, v in (("import_mesh", False), ("import_as_skeletal", True), ("import_animations", True), ("import_materials", False),
                 ("import_textures", False), ("create_physics_asset", False), ("skeleton", skeleton)):
        ui.set_editor_property(k, v)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
    ui.set_editor_property("original_import_type", unreal.FBXImportType.FBXIT_ANIMATION)
    ad = ui.get_editor_property("anim_sequence_import_data")
    ad.set_editor_property("import_bone_tracks", True)
    ad.set_editor_property("animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
    paths = task(fbx, dest, name, ui)
    unreal.log_warning("CLIP %s -> %s" % (name, paths))
    for p in paths:  # drop extras an anim import can still create, name the clip exactly
        base = p.split(".")[0]
        a = unreal.load_asset(base)
        if a and a.get_class().get_name() != "AnimSequence":
            lib.delete_asset(base)
        elif a and base != dest + "/" + name and not lib.does_asset_exist(dest + "/" + name):
            lib.rename_asset(base, dest + "/" + name)
    s = unreal.load_asset(dest + "/" + name)
    unreal.log_warning("CLIP OK %s %s frames=%s" % (name, s.get_class().get_name() if s else None,
                                                  s.get_editor_property("number_of_frames") if s else None))


eve_skel = stub_skeleton(job["eve"], "/Game/Art/Character/PC/CH_P_EVE_01/CH_P_EVE_01_Skeleton")
clip(job["eve"], eve_skel, ANIM, slot)
for p in job.get("partners", []):
    clip(p["fbx"], stub_skeleton(p["fbx"], p["skeleton"]), ANIM + "/" + slot + "a", p["clip"])

if job.get("rows"):
    tpath = ANIM + "/" + slot + "a"
    if lib.does_asset_exist(tpath):
        lib.delete_asset(tpath)
    f = unreal.DataTableFactory()
    f.set_editor_property("struct", unreal.GameplayTagTableRow.static_struct())
    dt = tools.create_asset(slot + "a", ANIM, unreal.DataTable, f)
    rows = [{"Name": r["Name"], "Tag": {"TagName": r["Tag"]}, "DevComment": r["DevComment"]} for r in job["rows"]]
    ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, json.dumps(rows))
    unreal.log_warning("TABLE %s fill=%s rows=%s" % (tpath, ok, unreal.DataTableFunctionLibrary.get_data_table_row_names(dt)))
    lib.save_asset(tpath)

# chunk label: only the mod folder goes to chunk 1 (not recursive, so the stub skeletons stay in chunk 0)
lab = ANIM + "/PAL_SkyrimPort"
if not lib.does_asset_exist(lab):
    df = unreal.DataAssetFactory(); df.set_editor_property("data_asset_class", unreal.PrimaryAssetLabel)
    label = tools.create_asset("PAL_SkyrimPort", ANIM, unreal.PrimaryAssetLabel, df)
else:
    label = unreal.load_asset(lab)
rules = unreal.PrimaryAssetRules()
rules.set_editor_property("chunk_id", 1)
rules.set_editor_property("apply_recursively", False)
rules.set_editor_property("cook_rule", unreal.PrimaryAssetCookRule.ALWAYS_COOK)
rules.set_editor_property("priority", 10)
label.set_editor_property("rules", rules)
label.set_editor_property("label_assets_in_my_directory", True)
lib.save_asset(lab)
lib.save_directory("/Game", only_if_is_dirty=False, recursive=True)
unreal.log_warning("IMPORT DONE")
