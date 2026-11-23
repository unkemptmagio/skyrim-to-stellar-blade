# sound.py: one wav per one-clip scene, played by ATOOL/PELA as <HD-ATOOL_P>/audio/<slot>.wav when the clip starts.
#   moans climb mild -> medium -> hot over the stages (one SexLab voice per scene), a wet/oral sound on every thrust
#   (pelvis-to-pelvis distance minima), orgasm sound at climaxAt (start of the last stage), hot moans fade after it.
# python tools/sound.py <scene id> [out.wav]     (default out: the game's ATOOL audio folder)
import sys, os, json, glob, wave, zlib, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget as rt, cfg

SL = cfg.SEXLAB_SOUNDS
PACKS = {"PPlus": SL, "AIO": cfg.SEXLAB_SOUNDS_AIO}
VOICES = os.environ.get("SB_VOICES", "PPlus_6")   # Eve's voice (user pick); "AIO_3,PPlus_2" = one picked per scene
TACHY_VOICE = os.environ.get("SB_TACHY_VOICE", "PPlus_4")   # FF partner: highest-pitched P+ voice (~460 Hz vs Eve's ~370), full tiers
TACHY_VOL = 0.85                                            # x Eve's moan volume, so Eve stays the lead
AUDIO = cfg.SB_GAME + "/Content/Paks/LogicMods/HD-ATOOL_P/audio/"
SR = 22050
GAP = {"mild": 1.6, "medium": 0.9, "hot": 0.35}          # silence between moans (s)
MOAN_VOL = {"mild": 0.6, "medium": 0.75, "hot": 0.9}
WET = {"vaginal": "fxSex01", "anal": "fxSex01", "oral": "fxOral01"}
WET_VOL = {"mild": 0.25, "medium": 0.4, "hot": 0.55}


def load(path):
    w = wave.open(path); ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
    x = np.frombuffer(w.readframes(n), np.int16).astype(np.float32).reshape(-1, ch).mean(1) / 32768
    return np.interp(np.arange(0, len(x), rate / SR), np.arange(len(x)), x) if rate != SR else x


def lib(folder, root=SL):
    return [load(f) for f in sorted(glob.glob(root + folder + "/*.wav"))]


def pelvis(c):
    i = c["names"].index("Bip001-Pelvis")
    return np.array([rt.world_mats(c["parents"], fr)[1][i] for fr in c["frames"]])


def thrusts(d, fps, min_gap_s=0.25, depth_cm=1.5):
    """frames where the pelvis distance hits a local minimum at least depth_cm below the surrounding peaks"""
    w = max(2, int(min_gap_s * fps)); out = []
    for i in range(w, len(d) - w):
        seg = d[i - w:i + w + 1]
        if d[i] == seg.min() and max(d[max(0, i - 3 * w):i].max(), d[i:i + 3 * w].max()) - d[i] > depth_cm:
            if not out or i - out[-1] >= w: out.append(i)
    return out


def tier(k, n):
    return ["mild", "medium", "medium", "hot"][min(3, int(4 * k / max(n - 1, 1)))]


def build(scene, dir_, partner, target, out):
    pt = scene["parts"][0]; stages = pt["stages"]; L = pt["len"]
    rng = np.random.default_rng(zlib.crc32(scene["name"].encode()))
    pool = [v for v in VOICES.split(",") if v] or ["PPlus_%d" % i for i in range(1, 9)]
    voice = pool[rng.integers(len(pool))]; pk, n = voice.split("_")
    moans = {t: lib("vFemaleMoan%02d/%s" % (int(n), t), PACKS[pk]) for t in GAP}
    if not moans["hot"]: moans["hot"] = moans["medium"]          # voices 5, 6, 8 have no hot tier
    sl = pt["slot"]; eve = json.load(open("%s/%d_eve.json" % (dir_, sl))); fps = eve["fps"]
    N = int(L * SR) + 1; mix = np.zeros(N + SR * 10, np.float32)
    climax = stages[-1][0] / fps
    stage_of = lambda t: next((k for k, s in enumerate(stages) if t * fps < s[1]), len(stages) - 1)
    def put(x, t, v):
        a = int(t * SR); mix[a:a + len(x)] += x[:len(mix) - a] * v
    # moans: back to back, gap and tier from the stage the moan starts in, none running into the climax
    t = 0.3; cues = []                          # (time, tier, volume) of every Eve moan: Tachy moans on the same cues
    while t < climax:
        tr = tier(stage_of(t), len(stages)); x = moans[tr][rng.integers(len(moans[tr]))]
        if t + len(x) / SR > climax + 0.1: break
        put(x, t, MOAN_VOL[tr]); cues.append((t, tr, MOAN_VOL[tr])); t += len(x) / SR + GAP[tr] * rng.uniform(0.7, 1.3)
    # climax: her 3 strongest hot moans back to back, loudest of the scene; then mild afterglow moans fading out
    peak = sorted(moans["hot"], key=lambda x: -float(np.sqrt((x ** 2).mean())))[:3]
    t = climax
    for x in peak: put(x, t, 1.15); cues.append((t, "peak", 1.15)); t += len(x) / SR + 0.08
    t += 0.8
    while t < L - 1:
        x = moans["mild"][rng.integers(len(moans["mild"]))]
        v = 0.6 * max(0.4, 1 - (t - climax) / max(L - climax, 1)); put(x, t, v); cues.append((t, "mild", v))
        t += len(x) / SR + GAP["mild"] * rng.uniform(0.7, 1.3)
    # Tachy (FF scenes had no partner voice, QA 2026-11-23): she moans WITH Eve, a moan of the same tier on each of Eve's cues
    # (user: "in parallel, at the same time"), a few hundredths of a second apart so the two voices don't phase into one
    if scene.get("kind") == "FF":
        tp, tn = TACHY_VOICE.split("_"); tm = {k: lib("vFemaleMoan%02d/%s" % (int(tn), k), PACKS[tp]) for k in GAP}
        if not tm["hot"]: tm["hot"] = tm["medium"]
        tm["peak"] = sorted(tm["hot"], key=lambda x: -float(np.sqrt((x ** 2).mean())))[:3]
        trng = np.random.default_rng(zlib.crc32((scene["name"] + "/tachy").encode()))
        for t, tr, v in cues:
            put(tm[tr][trng.integers(len(tm[tr]))], t + trng.uniform(0.02, 0.12), v * TACHY_VOL)
    # wet / oral sound on each thrust
    if target in WET and partner:
        wet = lib(WET[target]); d = np.linalg.norm(pelvis(eve) - pelvis(json.load(open("%s/%d_%s.json" % (dir_, sl, partner)))), axis=1)
        for f in thrusts(d, fps):
            tr = tier(stage_of(f / fps), len(stages)); put(wet[rng.integers(len(wet))], f / fps, WET_VOL[tr])
    put(lib("fxOrgasm01")[rng.integers(2)], climax, 0.5)
    y = mix[:N]; y = y / max(1.0, np.abs(y).max() / 0.95)       # no clipping
    # MP3 inside a RIFF/WAVE file: ATOOL opens <slot>.wav and WMF decodes it (tested in game 2026-11-22; a bare MP3 named
    # .wav stays silent, MS ADPCM also plays). ~5x smaller than 16-bit PCM.
    tmp = out + ".pcm.wav"
    w = wave.open(tmp, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((y * 32767).astype(np.int16).tobytes()); w.close()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", tmp, "-c:a", "libmp3lame", "-b:a", "64k", "-f", "wav", out], check=True)
    os.remove(tmp)
    return voice, climax


if __name__ == "__main__":
    R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    s = json.load(open(R + "/work/registry.json"))["scenes"][sys.argv[1]]
    out = sys.argv[2] if len(sys.argv) > 2 else AUDIO + "%d.wav" % s["parts"][0]["slot"]
    print(out, build(s, s["dir"], s.get("partner"), s.get("target"), out))
