# cfg.py: this machine's paths. Copy config.example.json to config.json (repo root, not committed) and edit it.
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
_d = {
    "skyrim_mods": "C:/Path/To/MO2/mods",                  # Mod Organizer mods folder holding the SLAL packs
    "bodyslide_meshes": "C:/Path/To/BodySlide Output/meshes/actors/character/character assets/",   # femalebody_1 / malebody_1 nifs
    "sexlab_sounds": "C:/Path/To/MO2/mods/SexLab Framework PPLUS/Sound/fx/SexLab/",
    "sexlab_sounds_aio": "C:/Path/To/MO2/mods/Sexlab Framework Sound Replacer AIO/Sound/fx/SexLab/",
    "sb_game": "C:/Path/To/StellarBlade/SB",              # the game's SB folder
    "vortex_staging": "C:/Path/To/Vortex Mods/stellarblade",
    "ue_root": "C:/Path/To/UE_4.26",                      # Unreal Engine 4.26.2
    "modkit": "C:/Path/To/SBModKit/SB",                   # the Stellar Blade mod-kit Unreal project (named SB)
    "blender": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
    "fmodel_exports": "C:/Path/To/FModel/Output/Exports/SB/Content/",
}
try:
    _d.update(json.load(open(ROOT + "/config.json", encoding="utf-8")))
except FileNotFoundError:
    pass

SKYRIM_MODS = _d["skyrim_mods"]; BODYSLIDE = _d["bodyslide_meshes"]
SEXLAB_SOUNDS, SEXLAB_SOUNDS_AIO = _d["sexlab_sounds"], _d["sexlab_sounds_aio"]
SB_GAME, VORTEX_SB = _d["sb_game"], _d["vortex_staging"]
UE_ROOT, MODKIT, BLENDER, FMODEL = _d["ue_root"], _d["modkit"], _d["blender"], _d["fmodel_exports"]

if __name__ == "__main__":
    for k, v in sorted(_d.items()): print("%-18s %s %s" % (k, v, "" if os.path.exists(v) else "(missing)"))
