# skyrim-to-stellar-blade

A pipeline that ports Skyrim **SexLab (SLAL)** animation packs to **Stellar Blade** as
[ATOOL](https://www.nexusmods.com/stellarblade) clips, with PEFA groups and optional PELA sequences. No manual steps between
"pick a scene" and "pak installed in the game".

This repository contains **code only**. It ships no animations, sounds, meshes or game files: you need your own
copies of the source mods and the game. Releasing ported animations requires the original authors' permission.

## What it does

For each SLAL scene (one female + optional male or female partner, or solo):

1. **Retarget** every stage from the Skyrim XPMSE skeleton to Eve / Adam / Tachy (`tools/retarget.py`, `tools/hkx.py`
   reads both XML and binary hkx).
2. **Contact**: the partner's shaft is placed on Eve's vaginal / anal entry or in her mouth (Adam bends his knees and her
   head turns for oral), depth rhythm kept from the source (`tools/contact.py`).
3. **Legs**: planted feet stop sliding and sit on the floor, knees and raised feet are pushed out of the other body, the
   knee keeps its hinge (`tools/legs.py`).
4. **Hands**: every touch the source makes (own body, partner's body, vulva, shaft) is measured on the Skyrim BodySlide
   bodies and re-made on the Stellar Blade bodies; hands, forearms and elbows are pushed out of any body; spikes from
   bad skin picks are median-filtered (`tools/hands.py`).
5. **One clip per scene**: stages loop ~7 s, loop seams are spread over 0.2 s, stage changes blend at the best-matching
   frame pair, feet are re-planted on the result (`tools/transition.py`).
6. **Props**: SLAL AnimObjects (cuffs, ropes, armbinders, yokes, poles, chairs, toys) become prop actors riding the
   matching SB bone or the world (`tools/props.py`, `tools/nif.py`, see `PROPS_DESIGN.md`). Solo toy scenes can use Eve's
   own sword (game asset, hilt inserted, shrunk).
7. **Sound**: one track per scene, SexLab moans building over the stages, wet sounds on every thrust, climax in the last
   stage; a second voice for the female partner (`tools/sound.py`).
8. **Build**: FBX export with Blender, Unreal 4.26 import + cook, bone-index remap to the game skeletons, IoStore paks
   split under 400 assets, install, PELA / PEFA files, contact sheets and a lint report (`port.py`, `ue/`).

## Requirements

- Windows, Python 3.10 with `numpy` and `Pillow`, `ffmpeg` on PATH
- Blender 5.x
- Unreal Engine 4.26.2 and the Stellar Blade mod-kit project (named `SB`)
- FModel exports of the game skeletons (`CH_P_EVE_01_Skeleton`, `CH_NPC_Adam_01_Skeleton`, `CH_NPC_MaleGenitals_Skeleton`,
  and for the sword option `CH_W_Sword_01_Skeleton`) as JSON in `skeletons/`, plus the Eve / Tachy / Adam body and head
  meshes (psk) under your FModel export folder
- The XPMSE skeletons (`xpmsse_skeleton.hkx`, `xpmsse_skeleton_female.hkx`) in `skeletons/`
- The SLAL packs you want to port, SexLab Framework (sounds), a BodySlide output of the female / male bodies
- `work/anio.json`: AnimObject editor id -> nif path, exported once from your load order (props only)

## Setup

```
copy config.example.json config.json     # then edit the paths in config.json
python tools/cfg.py                      # lists every path and flags the missing ones
```

## Usage

```
python port.py list [pack-filter]        # SLAL scenes and whether they can be ported
python port.py scene <SLAL id> [...]     # prepare scenes (retarget, passes, FBX, slot)
python port.py pack <SLAL json name>     # prepare every portable scene of a pack
python port.py build                     # UE import/cook, remap, paks, install, PELA, sheets, lint
python port.py install                   # redo only the install step
```

Environment switches: `PORT_ONLY=<ids>` (test build into its own folder), `PORT_REG=<registry copy>`,
`PORT_DISABLED=<packs>`, `PORT_JOBS`, `FBX_THREADS`, `PORT_SOLO_TOY=sword|toy`, `SB_VOICES`, `SB_TACHY_VOICE`.

## Status

Beta. Leito's pack is the reference (26 scenes, base + optional "Rough"). Billyy's pack ports but needs more alignment
work. See `TODO.txt` for open items.

## Credits

ATOOL, PEFA, PELA and UE4SS by their authors. SLAL animations by their authors (Leito, Billyy, ...). SexLab Framework.
FModel, Blender, Unreal Engine.
