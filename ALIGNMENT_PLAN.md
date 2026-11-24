# Billyy alignment plan (bodies + props), 2026-11-23

## What the data says (release build, work/lint.txt + log/billyy_full_prep.txt)
- 140 of 259 Billyy scenes have lint flags (Leito: 18 of 26, mostly small).
- Genital contact is NOT the problem: all 555 vaginal / anal / oral stage contacts end at 0 cm miss
  (medians before the pass: 7 / 12 / 17 cm).
- The problem is everything the contact pass doesn't look at:
  - bodies overlapping: 112 stage flags (eve in adam 87, adam in eve 25)
  - limbs inside the partner: hands 52, arms 65, knees 38
  - limbs inside their own body: ~90 (tied-arm poses: armbinder, hogtie, wrists on the back)
  - props: no automatic measure at all. Test scenes: rope cuffs 4-5 cm off the SB limb, armbinder 6-9 cm,
    world props (poles, pillories, crosses) at their Skyrim position x scale.
- Ruled out: SLAL position offsets (Billyy's jsons have none, only SOS bend).
- Likely cause: the contact pass moves Adam until the genitals meet on SB proportions, and nothing pushes the rest of
  the bodies apart. Billyy's poses are tight (bondage, holding, hogtie), so SB's thicker bodies collide far more than
  in Leito.

## Phase 0 results (done 2026-11-23)
- `python tools/score.py [bench [old.json]]` -> work/score.txt (ranked) + score.json; props now drawn on the
  contact sheets (grey dots). Benchmark set: work/bench.json (12 scenes), baseline work/score_bench.json (total 391).
- Prop fit uses a full-body model (hands.sb_body(full=True): arms, hands, neck, feet). The capsule model reads
  points ON the skin as ~2-3 cm inside, so sinking is flagged from 4 cm; restraints are flagged when their median
  distance to the skin is over 3.5 cm (snug ropes ~1.7, loose 5-7). Yokes: sinking only (the bar stands off).
- Scores: Billyy 72 scenes > 10 (Leito 3); worst are body stacking (Laying Back Anal: Eve lies inside Adam in
  every stage), standing holds, hogties (arms in own body), and loose binders / ropes (4-6 cm off).
- No world props in the built set (poles / pillories were never ported). Instead: 43 furniture scenes
  (Bed / Chair / Table / Wall / Counter) ship WITHOUT their furniture, so the actors pose on thin air. P5 becomes:
  drop them from the release, or add furniture (separate decision).

## Principle
A Skyrim scene is a set of contacts, not a set of joint angles. Record what touches what in the source (and what is
close but must not touch), then re-solve those contacts on the SB bodies. Props are part of the same graph.

## Phases
P0  Measure (first, small)
    - prop lint: gap / penetration of each prop against the SB body surface per stage (cuff to limb, binder to arms,
      grips on world props)
    - one score per scene + a ranked list; props drawn on the contact sheets
    - benchmark set of ~12 scenes, one per kind: armbinder, wrist/ankle cuffs, yoke, hogtie, pole, pillory/cross,
      standing hold, cowgirl, blowjob, FF, solo toy, a clean control. User grades each in game (1 good / 2 minor /
      3 bad) = baseline.
P1  Speed (prerequisite): cache each scene's retarget output so the later passes rerun alone; do the deferred FK
    precompute. Goal: benchmark set re-prepared in < 10 min (today ~45 min; full pack ~12 h).
P2  Contact graph from the Skyrim side: per frame, body-region pairs (and body-prop pairs) closer than a threshold,
    using the Skyrim body shapes (XPMSSE + BodySlide meshes from config.json).
P3  Body solver: SB bodies as capsules fitted to the SB meshes; per frame, push penetrations apart while holding
    fixed constraints (genital contact, planted feet, graph touches). Movable: Adam's root/pelvis (small slide),
    spines (limited bend), arms and legs through IK; smoothed over time. Replaces the dropped spine-bend pass and
    should also fix Leito's leftovers (Lotus, Aggressive Doggy S1, Bound Anal Missionary S3).
P4  Restraints: the prop is the authority, the body adapts.
    - cuffs / ropes refit around the SB limb (centred on the bone, radius from the SB mesh + margin)
    - wrists / ankles IK'd to the cuff, chain or binder position
    - tied arms on the back: target pushed out by the SB-vs-Skyrim back thickness (same fix as Leito Bound Doggy)
P5  World props: per scene, one rigid transform (+ clamped scale) that best fits the graph's anchor points (hands on
    the pole, neck / wrists in the pillory holes, pelvis on the seat); static for the scene, then the bodies are
    solved against it as a collider.
P6  Release tiers: scenes under the score threshold AND graded 1-2 move to a stable "Billyy" pack; the rest stay
    Experimental; the last few go to manual Blender fixes (same workflow as Leito).

## Order and loop
P0 -> P1 -> P2+P3 -> P4 -> P5 -> P6. After each phase: re-prepare the benchmark set, compare scores, user grades in
game, then run the full pack overnight only when the benchmark improved and no control scene got worse.

## Risks
- The solver fighting the contact pass: genital contact stays a hard constraint, the solver moves everything else.
- Capsules are approximate: fine for torsos and limbs, not for hands on skin (hands keep the existing hands.py pass).
- Multi-part skinned props use only their biggest part today (armbinder straps may be missing pieces).
- Long clips (~370 frames per stage): every pass x5 cost, hence P1 first.
