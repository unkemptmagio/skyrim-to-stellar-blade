# Props in solo and duo scenes (2026-11-23)

## What the source packs use
- SLAL scenes attach props ("AnimObjects") through the FNIS animation lists (`-o` entries per stage hkx), with or
  without the scene's `AnimObject` tag. Billyy: 68 duo + 6 solo scenes, untagged. Leito: 9 tagged duo + 5 solo.
- Billyy's are mostly restraints: rope / metal cuffs on wrists and ankles, armbinder, yoke, chains, poles, pillories,
  crosses, plus dildos. Leito: double dildo, potion, chair, dildos.
- 121 of 122 Billyy+Leito props read; the miss is a bed packed in a BSA.

## How a prop is placed
Each distinct (actor, AnimObject) of a scene becomes its own prop actor: a skeletal mesh on the two-bone prop
skeleton (Root, Bip001-Toy) plus its own clip and one ATOOL row (`mesh|clip`, like the genital rig). A prop that a
stage does not use is parked 100 m under the floor; at a stage blend it snaps in or out at mid-blend.

Where the prop rides:
1. Skinned props (Billyy's armbinder and yoke: fully weighted to Spine2; poles: to the root) ride their dominant
   bone, with vertices in that bone's space (`nif.skinned_parts`).
2. Static props on a body bone (rope / metal cuffs: Prn = forearm or calf) are modelled in the skeleton's bind
   pose; they are moved into the bone's space with the rest pose (whichever of bind / local hugs the bone).
3. Props on AnimObjectA/B (root) ride the body bone whose whole length lies closest to their vertices, unless they
   are big (> 80 Skyrim units: poles, crosses, pillories, chairs) or far: those are world props.
4. WEAPON / SHIELD nodes are aliased to the right hand / left forearm.

Anchored props keep their Skyrim offset from the anchor bone, applied to the SB bone after every pass (the
SB-vs-Skyrim bone frame comes from the raw retarget), so they stay on SB's arms after the IK moved them. World props
keep the Skyrim position x scale, moved along with the actor's Bip001 when the port slides an actor.

Solo scenes with one toy-sized prop in every stage and a vaginal/anal target keep the older path: the toy is aligned
to her entry and her hand keeps its grip.

Dropped: effect meshes (paper-flat decals, magic / fx / cum names) would show as solid slabs.

## Materials
Flat colours by name: rope (tan), metal (dark grey: cuffs, yoke, chains, binder), wood (furniture, poles, crosses,
staffs), silicone (pink: everything else, e.g. dildos).

## Measured on the test scenes (vertex median distance to the SB bone)
- Rope wrist cuffs 4-5 cm from the SB forearm, ankle ropes 5 cm from the calf, armbinder 6-9 cm from the arms.
- Chair on the floor, her pelvis over the seat. Staff between her legs in the riding stages.

## Open
- Eve's sword as the solo toy (hilt inserted): needs one FModel export of the sword mesh (psk) + a psk triangle reader.
- Multi-part skinned props use their biggest part only.
- Furniture-tagged scenes are still skipped (beds / tables placed in the world, not AnimObjects).
- Billyy is disabled for release; its prop scenes are only in the test build.
