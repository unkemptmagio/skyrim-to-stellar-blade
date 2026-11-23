# UE 4.26 commandlet, ONE editor session for a whole build:
#   delete stale slots -> import FBX (jobs flagged import) -> name clips -> fill partner tables -> dump track order
#   -> one PrimaryAssetLabel per pack (explicit assets, own chunk id) so every pack becomes its own pak.
# run: UE4Editor-Cmd.exe SB.uproject -run=pythonscript -script="batch_sb.py <plan.json>"
# plan.json: {"jobs": [job + {"import": bool}], "delete": ["/Game/..."], "packs": {"Leito": {"chunk": 1, "assets": [...]}},
#             "tracks_out": "<path>"}
import sys, json, unreal

plan = json.load(open(sys.argv[1]))
lib = unreal.EditorAssetLibrary; tools = unreal.AssetToolsHelpers.get_asset_tools(); DTL = unreal.DataTableFunctionLibrary
ANIM = "/Game/Mods/HD-ATOOL_P/anim"
log = lambda m: unreal.log_warning("SB| " + m)

for p in plan.get("delete", []):
    if lib.does_asset_exist(p): log("DELETE %s %s" % (p, lib.delete_asset(p)))
for d in plan.get("delete_dirs", []):
    if lib.does_directory_exist(d): log("DELETE DIR %s %s" % (d, lib.delete_directory(d)))


def task(fbx, dest, name, ui):
    t = unreal.AssetImportTask()
    for k, v in (("filename", fbx), ("destination_path", dest), ("destination_name", name), ("automated", True),
                 ("replace_existing", True), ("save", True), ("options", ui)):
        t.set_editor_property(k, v)
    tools.import_asset_tasks([t])
    return list(t.get_editor_property("imported_object_paths"))


def stub_skeleton(fbx, skel_path):
    if lib.does_asset_exist(skel_path): return unreal.load_asset(skel_path)
    d, n = skel_path.rsplit("/", 1)
    ui = unreal.FbxImportUI()
    for k, v in (("import_mesh", True), ("import_as_skeletal", True), ("import_animations", False), ("import_materials", False),
                 ("import_textures", False), ("create_physics_asset", False)):
        ui.set_editor_property(k, v)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    task(fbx, d, "Stub_" + n, ui); lib.rename_asset(d + "/Stub_" + n + "_Skeleton", skel_path)
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
    if lib.does_asset_exist(dest + "/" + name): lib.delete_asset(dest + "/" + name)
    task(fbx, dest, name, ui)
    # 4.26 still creates a mesh (+ physics asset) under <name> and puts the clip at <name>_Anim: drop extras, rename
    for extra in (name, name + "_PhysicsAsset", name + "_Skeleton"):
        x = unreal.load_asset(dest + "/" + extra) if lib.does_asset_exist(dest + "/" + extra) else None
        if x and x.get_class().get_name() != "AnimSequence": lib.delete_asset(dest + "/" + extra)
    if lib.does_asset_exist(dest + "/" + name + "_Anim"): lib.rename_asset(dest + "/" + name + "_Anim", dest + "/" + name)
    a = unreal.load_asset(dest + "/" + name)
    if not a or a.get_class().get_name() != "AnimSequence": log("CLIP FAIL %s/%s" % (dest, name))


def prop_mesh(fbx, mesh_path, mat=None):
    """our prop (Skyrim AnimObject): skeletal mesh + <name>_Skeleton from the first stage FBX, one shared flat material per
    kind (mat = {"name", "rgb", "rough"}; default the pink silicone)"""
    mat = mat or {"name": "M_SkyrimSilicone", "rgb": [0.78, 0.22, 0.52], "rough": 0.35}
    d, n = mesh_path.rsplit("/", 1); mp = d + "/" + mat["name"]
    if not lib.does_asset_exist(mp):
        MEL = unreal.MaterialEditingLibrary
        m = tools.create_asset(mat["name"], d, unreal.Material, unreal.MaterialFactoryNew())
        c = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -300, 0)
        c.set_editor_property("constant", unreal.LinearColor(mat["rgb"][0], mat["rgb"][1], mat["rgb"][2], 1.0))
        MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
        r = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -300, 200); r.set_editor_property("r", mat["rough"])
        MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
        m.set_editor_property("two_sided", True); MEL.recompile_material(m); lib.save_asset(mp)
    if lib.does_asset_exist(mesh_path): return
    ui = unreal.FbxImportUI()
    for k, v in (("import_mesh", True), ("import_as_skeletal", True), ("import_animations", False), ("import_materials", False),
                 ("import_textures", False), ("create_physics_asset", False)):
        ui.set_editor_property(k, v)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    task(fbx, d, n, ui)
    sm = unreal.load_asset(mesh_path); sl = unreal.SkeletalMaterial()      # a fresh slot list: the import made none (grey default)
    sl.set_editor_property("material_interface", unreal.load_asset(mp)); sl.set_editor_property("material_slot_name", "Toy")
    sm.set_editor_property("materials", [sl]); lib.save_asset(mesh_path)
    log("PROP %s skeleton %s" % (mesh_path, lib.does_asset_exist(mesh_path + "_Skeleton")))


EVE_SKEL = "/Game/Art/Character/PC/CH_P_EVE_01/CH_P_EVE_01_Skeleton"
tracks = {}
for j in plan["jobs"]:
    s = j["slot"]
    if j.get("import"):
        clip(j["eve"], stub_skeleton(j["eve"], EVE_SKEL), ANIM, s)
        for p in j.get("partners", []):
            if p.get("mesh"): prop_mesh(p["fbx"], p["mesh"], p.get("material"))
            clip(p["fbx"], stub_skeleton(p["fbx"], p["skeleton"]), ANIM + "/" + s + "a", p["clip"])
    # partner table (recreated every build: cheap, and keeps rows in sync with the job)
    tpath = ANIM + "/" + s + "a"
    if lib.does_asset_exist(tpath): lib.delete_asset(tpath)
    f = unreal.DataTableFactory(); f.set_editor_property("struct", unreal.GameplayTagTableRow.static_struct())
    dt = tools.create_asset(s + "a", ANIM, unreal.DataTable, f)
    q = lambda x: '"' + x.replace('"', '""') + '"'
    csv = "---,Tag,DevComment\n" + "\n".join("%s,%s,%s" % (r["Name"], "" if r["Tag"] == "None" else r["Tag"], q(r["DevComment"])) for r in j["rows"])
    DTL.fill_data_table_from_csv_string(dt, csv); lib.save_asset(tpath)
    keys = [ANIM + "/" + s] + [ANIM + "/" + s + "a/" + p["clip"] for p in j.get("partners", [])]
    for k in keys:
        a = unreal.load_asset(k)
        tracks[k] = [str(n) for n in unreal.AnimationLibrary.get_animation_track_names(a)] if a else None
        if not a: log("MISSING %s" % k)
json.dump(tracks, open(plan["tracks_out"], "w"))

# chunk labels: one per pack, explicit assets only (stub skeletons stay in chunk 0 and never ship)
old = ANIM + "/PAL_SkyrimPort"
if lib.does_asset_exist(old): lib.delete_asset(old)
LDIR = "/Game/SkyrimPortLabels"
if lib.does_directory_exist(LDIR):                     # drop every old label (a stale one kept assigning assets to its chunk)
    for a in lib.list_assets(LDIR, recursive=True, include_folder=False):
        lib.delete_asset(a.split(".")[0])
for name, pk in plan["packs"].items():
    lp = LDIR + "/PAL_" + name
    if lib.does_asset_exist(lp): lib.delete_asset(lp)
    df = unreal.DataAssetFactory(); df.set_editor_property("data_asset_class", unreal.PrimaryAssetLabel)
    lab = tools.create_asset("PAL_" + name, LDIR, unreal.PrimaryAssetLabel, df)
    r = unreal.PrimaryAssetRules()
    r.set_editor_property("chunk_id", pk["chunk"]); r.set_editor_property("apply_recursively", False)
    r.set_editor_property("cook_rule", unreal.PrimaryAssetCookRule.ALWAYS_COOK); r.set_editor_property("priority", 10)
    lab.set_editor_property("rules", r)
    lab.set_editor_property("label_assets_in_my_directory", False)
    objs = [unreal.load_asset(a) for a in pk["assets"]]
    lab.set_editor_property("explicit_assets", [o for o in objs if o])
    lib.save_asset(lp)
    log("LABEL %s chunk %d assets %d" % (name, pk["chunk"], len([o for o in objs if o])))
lib.save_directory("/Game", only_if_is_dirty=False, recursive=True)
log("BATCH DONE")
