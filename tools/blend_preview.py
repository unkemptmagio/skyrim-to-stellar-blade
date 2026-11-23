# blender -b --python blend_preview.py -- <out_dir> <a.json> [b.json ...]
# Builds one armature per JSON (bone rest = Skyrim world rest), keys local anim, renders stick-figure previews.
import bpy, json, sys, os
from mathutils import Matrix, Quaternion, Vector

args = sys.argv[sys.argv.index("--") + 1:]
out_dir, jsons = args[0], args[1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
COLORS = [(1, .3, .5, 1), (.3, .6, 1, 1)]

def loc(p, q): return Matrix.Translation(Vector(p)) @ Quaternion(q).to_matrix().to_4x4()

for n, jp in enumerate(jsons):
    d = json.load(open(jp)); K0 = 1.43 if d.get("units") == "cm" else 1.0
    bones, parents, ref = d["bones"], d["parents"], d["ref"]
    world = []
    for i in range(len(bones)):
        m = loc(*ref[i]); world.append(m if parents[i] < 0 else world[parents[i]] @ m)
    arm = bpy.data.armatures.new("A%d" % n); ob = bpy.data.objects.new(os.path.basename(jp)[:-5], arm)
    scn.collection.objects.link(ob); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    for i, name in enumerate(bones):
        eb = arm.edit_bones.new(name); eb.head = (0, 0, 0); eb.tail = (0, 3, 0); eb.matrix = world[i]
    for i, name in enumerate(bones):
        if parents[i] >= 0: arm.edit_bones[name].parent = arm.edit_bones[bones[parents[i]]]
    bpy.ops.object.mode_set(mode="POSE")
    # key from Blender's STORED rest (bone.matrix_local), keeping any offset it introduced vs the Skyrim rest
    Br = [arm.bones[bones[i]].matrix_local.copy() for i in range(len(bones))]
    off = [world[i].inverted() @ Br[i] for i in range(len(bones))]
    for f, row in enumerate(d["frames"]):
        W = [None] * len(bones)
        for i in range(len(bones)):
            pq = row.get(str(i)) or ref[i]
            m = loc(*pq); W[i] = m if parents[i] < 0 else W[parents[i]] @ m
        for i in range(len(bones)):
            if str(i) not in row: continue
            Ba = W[i] @ off[i]
            if parents[i] < 0: basis = Br[i].inverted() @ Ba
            else:
                pi = parents[i]; Pa = W[pi] @ off[pi]
                basis = (Br[pi].inverted() @ Br[i]).inverted() @ (Pa.inverted() @ Ba)
            pb = ob.pose.bones[bones[i]]; pb.rotation_mode = "QUATERNION"; pb.matrix_basis = basis
            pb.keyframe_insert("location", frame=f); pb.keyframe_insert("rotation_quaternion", frame=f)
    bpy.ops.object.mode_set(mode="OBJECT")
    # stick figure: a thin box per parent->child segment, rigidly weighted to the parent bone
    me = bpy.data.meshes.new("stick%d" % n); verts, faces, owner = [], [], []
    for i in range(len(bones)):
        pi = parents[i]
        core = lambda nm: (nm.startswith("NPC ") or nm.startswith("Bip001") or nm.startswith("NPC-Genitals")) and not any(k in nm for k in ("Root", "Magic", "Weapon", "Pauldron", "Shield", "Quiver", "Bow", "Twist", "Breast", "Butt", "Belly", "Finger", "Look"))
        if pi < 0 or not core(bones[i]) or not core(bones[pi]): continue
        h, t = world[pi].translation, world[i].translation
        if (t - h).length < 0.5: continue
        dv = (t - h).normalized(); u = dv.orthogonal().normalized() * 1.2 * K0; v = dv.cross(u).normalized() * 1.2 * K0
        base = len(verts)
        for e in (h, t):
            for su, sv in ((1, 1), (-1, 1), (-1, -1), (1, -1)): verts.append((e + u * su + v * sv)[:])
        faces += [(base, base+1, base+2, base+3), (base+4, base+7, base+6, base+5)] + [(base+k, base+4+k, base+4+(k+1)%4, base+(k+1)%4) for k in range(4)]
        owner += [bones[pi]] * 8
    me.from_pydata(verts, [], faces); st = bpy.data.objects.new("stick%d" % n, me); scn.collection.objects.link(st)
    for vi, b in enumerate(owner):
        vg = st.vertex_groups.get(b) or st.vertex_groups.new(name=b); vg.add([vi], 1.0, "REPLACE")
    st.modifiers.new("arm", "ARMATURE").object = ob
    mat = bpy.data.materials.new("m%d" % n); mat.diffuse_color = COLORS[n % 2]; st.data.materials.append(mat)
    scn.frame_end = len(d["frames"]) - 1

K = 1.43 if any(json.load(open(j)).get("units") == "cm" for j in jsons) else 1.0
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scn.collection.objects.link(cam); scn.camera = cam
light = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); scn.collection.objects.link(light)
light.rotation_euler = (0.8, 0.2, 0.5)
scn.render.engine = "BLENDER_WORKBENCH"; scn.render.resolution_x = 480; scn.render.resolution_y = 480
scn.display.shading.color_type = "MATERIAL"
os.makedirs(out_dir, exist_ok=True)
for name, (x, y) in {"side": (260, 0), "front": (0, -260)}.items():
    cam.location = (x * K, y * K, 70 * K); cam.rotation_euler = (Vector((0, 0, 45 * K)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    for f in (0, scn.frame_end // 2):
        scn.frame_set(f); scn.render.filepath = os.path.join(out_dir, "%s_f%02d.png" % (name, f)); bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "skyrim_scene.blend"))
print("PREVIEW DONE")
