Skyrim Port - Billyy  (EXPERIMENTAL)
====================================
Billyy's SexLab (SLAL) scenes, ported from Skyrim to Stellar Blade for ATOOL, including the bondage props
(cuffs, ropes, armbinders, yokes, chains, poles) and toys.

READ THIS FIRST
  This is an experimental release. From testing so far:
  - Every scene plays, with its own sound track and its partner (Adam / Tachy).
  - Most props work: they show up and follow the bodies.
  - Most scenes have HEAVY MISALIGNMENT: bodies and props don't line up well yet (clipping, hands and props off
    target, partners out of place). Billyy's animations are long clips built for Skyrim bodies, and the correction
    passes that make the Leito port clean don't hold up on them yet.
  Want a polished experience? Get "Skyrim Port - Leito" instead.

WHAT YOU GET
  - One clip per scene (all stages back to back, smooth stage changes), its own sound track, climax in the last stage
  - Props as their own animated objects, in flat colours (wood, metal, rope, silicone): no textures
  - PEFA groups "SkyrimBillyyExperimental" (split over a few paks: the pack is too big for one) and an optional PELA file

REQUIREMENTS
  - ATOOL (HD-ATOOL_P)
  - UE4SS, the build your PEFA/PELA use (RevOG UE4SS 3.0.1)
  - PEFA
  OPTIONAL: PELA (LustyAndroid)

INSTALL (manual, or let Vortex deploy the same layout)
  Content/Paks/~mods/_SkyrimPort/Eve_73xx_SkyrimBillyyExperimental*_P.pak/.ucas/.utoc   the animations
  Content/Paks/LogicMods/HD-ATOOL_P/audio/<slot>.wav                                     the sounds
  Content/Paks/~mods/PELA Patches/Skyrim Port - BillyyExperimental.json                  only with PELA
  Restart the game after installing: ATOOL lists its clips at startup.

ATOOL SLOTS
  Uses slots 379-641 (one per scene, 259 scenes; the PEFA group / ATOOL menu lists them). No overlap with Skyrim Port - Leito
  (352-378) or the packs listed in its readme. ATOOL only reads slots up to 1000.

FEEDBACK
  Post the slot number and what's off (stage, body part, prop). The worst scenes get fixed first.

CREDITS
  All credit for the animations and props goes to their author; this is a port, the motion is Billyy's.
  Animations and props: Billyy - Billyy's SLAL Animations
              https://www.loverslab.com/files/file/3999-billyy
  Sounds:     built from SexLab P+ by Scrab (https://www.loverslab.com/files/file/25318-sexlab-p/,
              https://github.com/Scrabx3/SexLab) and the original SexLab Framework by Ashal
              (https://www.loverslab.com/forum/49-sexlab-framework/).
  ATOOL, PEFA, PELA, UE4SS: their authors.
  Porting pipeline (open source, MIT): https://github.com/unkemptmagio/skyrim-to-stellar-blade

TAKEDOWN
  The original authors could not be reached before release. If you are the author of any animation, prop or sound
  used here (or represent them) and want it removed, get in touch: it comes down, no questions asked.

AI ASSISTANCE
  The porting pipeline (retargeting, contact and hand correction, transitions, props, sound mixing, build tools) was
  written with AI assistance (Claude by Anthropic). The animations and prop meshes are Billyy's, converted by that
  code: no AI-generated animation, art or voice is included.
