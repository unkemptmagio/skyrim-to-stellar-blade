# blender -b --python make_fbx.py -- <ue_skeleton.json> <clip.json from retarget.py> <out.fbx> [prop mesh.json]
# Builds the SB rig (body bones + their ancestors) at the game's rest pose with a tiny skinned mesh, keys the clip,
# and exports raw centimetres (Subverse recipe: build in metres, scale x100 + FBX_SCALE_ALL; UE ignores FBX units).
# UE -> Blender: pos (x, -y, z) / 100, quat (w, -x, y, -z).
import bpy, sys, json, re
from mathutils import Matrix, Quaternion, Vector

a = sys.argv[sys.argv.index("--") + 1:]
skel_p, clip_p, out = a[0], a[1], a[2]
sk = json.load(open(skel_p)); sk = next(e for e in sk if e.get("Type") == "Skeleton")["ReferenceSkeleton"]
names = [b["Name"] for b in sk["FinalRefBoneInfo"]]; parents = [b["ParentIndex"] for b in sk["FinalRefBoneInfo"]]
rest = [((t["Translation"]["X"], t["Translation"]["Y"], t["Translation"]["Z"]),
         (t["Rotation"]["W"], t["Rotation"]["X"], t["Rotation"]["Y"], t["Rotation"]["Z"])) for t in sk["FinalRefBonePose"]]
clip = json.load(open(clip_p))
cidx = {n: i for i, n in enumerate(clip["names"])}      # the clip may carry only the bones kept below (port.fbx_bones)

body = lambda n: n.startswith("Bip001") and not re.search(r"String|Prop|Footsteps|Xtra|Nub|Twist|Ponytail|Hair|Skirt|Breast", n)
keep = set(i for i, n in enumerate(names) if body(n) or n.startswith(("NPC-Genitals", "Genitals", "Schlong")))
if not keep: keep = set(range(len(names)))      # a rig without body bones (Eve's sword): all of it
for i in list(keep):                      # ancestors up to the root
    p = parents[i]
    while p >= 0: keep.add(p); p = parents[p]
keep = sorted(keep)

def b_loc(p, q):
    return Matrix.Translation(Vector((p[0], -p[1], p[2])) / 100) @ Quaternion((q[0], -q[1], q[2], -q[3])).to_matrix().to_4x4()
def world(local):
    W = {}
    for i in keep:
        m = b_loc(*local[i]); W[i] = m if parents[i] < 0 else W[parents[i]] @ m
    return W

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene; scn.render.fps = int(round(clip["fps"]))
arm = bpy.data.armatures.new("Armature"); ob = bpy.data.objects.new("Armature", arm); scn.collection.objects.link(ob)
bpy.context.view_layer.objects.active = ob
Wr = world(rest)
bpy.ops.object.mode_set(mode="EDIT")
for i in keep:
    eb = arm.edit_bones.new(names[i]); eb.head = (0, 0, 0); eb.tail = (0, 0.03, 0); eb.matrix = Wr[i]
for i in keep:
    if parents[i] >= 0: arm.edit_bones[names[i]].parent = arm.edit_bones[names[parents[i]]]
bpy.ops.object.mode_set(mode="OBJECT")

# tiny skinned mesh: one triangle per bone, fully weighted to it (keeps every bone and the bind pose)
verts, faces = [], []
for i in keep:
    h = Wr[i].translation; b = len(verts)
    verts += [h[:], (h + Vector((0.004, 0, 0)))[:], (h + Vector((0, 0, 0.004)))[:]]; faces.append((b, b + 1, b + 2))
prop = None
if len(a) > 3:   # optional real mesh (props): {"verts": bone-local UE cm, "tris", "bone"} rigidly on that bone
    pm = json.load(open(a[3])); bi = names.index(pm["bone"]); b0 = len(verts)
    verts += [(Wr[bi] @ (Vector((x, -y, z)) / 100))[:] for x, y, z in pm["verts"]]
    faces += [tuple(b0 + j for j in t) for t in pm["tris"]]; prop = (bi, range(b0, len(verts)))
me = bpy.data.meshes.new("Body"); me.from_pydata(verts, [], faces)
mo = bpy.data.objects.new("Body", me); scn.collection.objects.link(mo); mo.parent = ob
for k, i in enumerate(keep):
    vg = mo.vertex_groups.new(name=names[i]); vg.add([3 * k, 3 * k + 1, 3 * k + 2], 1.0, "REPLACE")
if prop: mo.vertex_groups[names[prop[0]]].add(list(prop[1]), 1.0, "REPLACE")
mo.modifiers.new("Armature", "ARMATURE").object = ob

# keys: basis from Blender's stored rest (robust to any roll it introduced)
Br = {i: arm.bones[names[i]].matrix_local.copy() for i in keep}
off = {i: Wr[i].inverted() @ Br[i] for i in keep}
bpy.context.view_layer.objects.active = ob; bpy.ops.object.mode_set(mode="POSE")
for f, cl in enumerate(clip["frames"]):
    local = [cl[cidx[names[i]]] if names[i] in cidx else rest[i] for i in range(len(names))]
    W = world(local)
    for i in keep:
        Ba = W[i] @ off[i]; pb = ob.pose.bones[names[i]]; pb.rotation_mode = "QUATERNION"
        if parents[i] < 0: pb.matrix_basis = Br[i].inverted() @ Ba
        else:
            pi = parents[i]; pb.matrix_basis = (Br[pi].inverted() @ Br[i]).inverted() @ ((W[pi] @ off[pi]).inverted() @ Ba)
        pb.keyframe_insert("location", frame=f); pb.keyframe_insert("rotation_quaternion", frame=f)
        if parents[i] < 0 and clip.get("root_scale"):   # uniform rig scale on the root (Eve's sword shrunk to toy size)
            k = float(clip["root_scale"]); pb.scale = (k, k, k); pb.keyframe_insert("scale", frame=f)
bpy.ops.object.mode_set(mode="OBJECT")
scn.frame_start, scn.frame_end = 0, len(clip["frames"]) - 1

# Subverse export recipe: scale location keys + rig x100, apply, FBX_SCALE_ALL
for fc in ob.animation_data.action.fcurves if hasattr(ob.animation_data.action, "fcurves") else []:
    pass
from bpy_extras import anim_utils
ad = ob.animation_data
bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
for fc in bag.fcurves:
    if fc.data_path.endswith(".location"):
        for kp in fc.keyframe_points: kp.co.y *= 100; kp.handle_left.y *= 100; kp.handle_right.y *= 100
bpy.ops.object.select_all(action="DESELECT")
for o in (ob, mo): o.select_set(True)
ob.scale = (100, 100, 100); bpy.context.view_layer.objects.active = ob
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.ops.export_scene.fbx(filepath=out, use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False,
    use_armature_deform_only=False, armature_nodetype="NULL", bake_anim=True, bake_anim_use_all_actions=False,
    bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True, bake_anim_simplify_factor=0.0,
    apply_scale_options="FBX_SCALE_ALL", primary_bone_axis="Y", secondary_bone_axis="X")
json.dump([names[i] for i in keep], open(out[:-4] + "_bones.json", "w"))
print("FBX DONE", out, len(keep), "bones,", len(clip["frames"]), "frames")
