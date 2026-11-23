Skyrim Port - Leito  (beta)
===========================
26 of Leito's SexLab (SLAL) scenes, ported from Skyrim to Stellar Blade for ATOOL, in two parts:
  BASE      16 scenes  (anal, vaginal, oral, lesbian with Tachy)
  OPTIONAL  10 scenes  "Rough": 6 Bound + 4 Aggressive. A separate pak: skip it if that's not your thing.
Each scene is ONE clip: all 5 stages play back to back (~40 s), with smooth transitions, and the climax happens in the last stage.
Every scene has its own sound track: moans build up stage by stage, wet sounds are synced to the motion, and the climax peaks in
the last stage. In the lesbian scenes Tachy has her own voice and moans together with Eve.

REQUIREMENTS
  - ATOOL (HD-ATOOL_P)
  - UE4SS, the build your PEFA/PELA use (RevOG UE4SS 3.0.1)
  - PEFA: groups the clips ("SkyrimLeito", "SkyrimLeitoRough") and spawns the partner (Adam / Tachy)

OPTIONAL
  - PELA (LustyAndroid): plays each scene as a sequence with Lust, climax effects and facial expressions.
    Without PELA, pick the clips in ATOOL's menu; the animation and sound play the same.
    Known issue: stock PELA shows the climax face for the whole scene, because it starts the climax face when the
    part starts, not at "climaxAt". The climax effects themselves (drops, pool) happen at the right moment.

INSTALL (manual, or let Vortex deploy the same layout)
  Base:
    Content/Paks/~mods/_SkyrimPort/Eve_7300_SkyrimLeito_P.pak/.ucas/.utoc          the animations
    Content/Paks/LogicMods/HD-ATOOL_P/audio/352.wav ... 368.wav                     the sounds (ATOOL plays audio/<slot>.wav)
    Content/Paks/~mods/PELA Patches/Skyrim Port - Leito.json                        only with PELA
  Optional "Rough" (needs nothing from the base, can be installed alone):
    Content/Paks/~mods/_SkyrimPort/Eve_7304_SkyrimLeitoRough_P.pak/.ucas/.utoc
    Content/Paks/LogicMods/HD-ATOOL_P/audio/369.wav ... 378.wav
    Content/Paks/~mods/PELA Patches/Skyrim Port - LeitoRough.json                   only with PELA
  Restart the game after installing: ATOOL lists its clips at startup.

ATOOL SLOTS
  Base uses slots 352-368, Rough uses 369-378 (one per scene, list below). ATOOL only reads slots up to 1000, and every
  animation pack shares that space. Two packs on the same slot override each other. Checked against these packs, no overlap:
    279-290   Creeper X Eve BBFH
    291, 297-301, 312-316   PELA Main Files
    292-296, 302-306, 317-320   Masturbate AnimPack
    307-311   OldDroid AnimPack
    321-332   Lesbian AnimPack
    343-351   Adam AnimPack
    352-368   Skyrim Port - Leito (base; 363 is reserved, unused)
    369-378   Skyrim Port - Leito Rough (optional)
    700-709   ESAP
    810, 813, 850, 900   Exorbic Loops
    901-907   Bot PosePack
  Still free (as of these packs): 333-342, 379-699, 710-809, 908-1000.
  If you see a Leito clip play someone else's animation (or the reverse), two packs share a slot: tell us which pack.

SCENES (slot - name - type)
  Base
  352  Anal Doggy 2                  anal
  353  Anal Missionary               anal
  354  Anal Missionary 2             anal
  355  Powerbomb                     anal
  356  Anal Reverse Cowgirl          anal
  357  Lesbian 1                     with Tachy
  358  Lesbian 2                     with Tachy
  359  69                            oral
  360  Blowjob 2                     oral
  361  Blowjob 3                     oral
  362  Cunnilingus 2                 oral (Adam)
  364  Cowgirl 2                     vaginal
  365  Doggy 2                       vaginal
  366  Lotus                         vaginal
  367  Missionary 3                  vaginal
  368  Standing 2                    vaginal
  Optional "Rough"
  369  Bound Anal Missionary         anal
  370  Bound Anal Rear Entry         anal
  371  Bound Blowjob                 oral
  372  Bound Doggy                   vaginal
  373  Bound Fisting                 fisting
  374  Bound Missionary              vaginal
  375  Aggressive Anal Missionary    anal
  376  Aggressive Blowjob            oral
  377  Aggressive Doggy              vaginal
  378  Aggressive Missionary         vaginal

KNOWN ISSUES (beta)
  - Some clipping: hips/torso overlap in lap poses (e.g. Lotus), hands that drift off the body in a few stages.
  - Rough: tied elbows sink into her back (Bound Doggy, last stages); Adam's hand stops a little short in Bound Fisting S3.
  - The animations were made for Skyrim bodies, so contact is corrected per scene but not perfect on every frame.

CREDITS
  All credit for the animations goes to their author; this is a port, the motion is Leito's.
  Animations: Leito - SLAL Animation Pack by Leito SE
              https://www.loverslab.com/files/file/6357-slal-animation-pack-by-leito-se/
  Sounds:     built from SexLab P+ by Scrab (https://www.loverslab.com/files/file/25318-sexlab-p/,
              https://github.com/Scrabx3/SexLab) and the original SexLab Framework by Ashal
              (https://www.loverslab.com/forum/49-sexlab-framework/): P+ female voices 06 (Eve) and 04 (Tachy) and the
              SexLab fx, mixed and synced to each scene.
  ATOOL, PEFA, PELA, UE4SS: their authors.
  Porting pipeline (open source, MIT): https://github.com/unkemptmagio/skyrim-to-stellar-blade

TAKEDOWN
  The original authors could not be reached before release. If you are the author of any animation or sound used here
  (or represent them) and want it removed, get in touch: it comes down, no questions asked.

AI ASSISTANCE
  The porting pipeline (retargeting, contact and hand correction, transitions, sound mixing, build tools) was written with
  AI assistance (Claude by Anthropic). The animations are Leito's, converted by that code: no AI-generated animation, art
  or voice is included.
