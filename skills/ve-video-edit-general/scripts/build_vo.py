"""Assemble the voiceover from the chosen takes in plan.json and compute the timeline.
Run from the workdir:  PATH=$PWD/venv/bin:$PATH ./venv/bin/python <skill>/scripts/build_vo.py [plan.json]
- Tightens pauses inside a line (> gap_max) down to gap_keep, snapping cuts to the quietest point.
- Pads each line on energy-detected onset/offset so first/last syllables are not clipped, but never past the
  neighbouring words in the take (no half-word bleed from the line before/after).
- Removes stumbles listed in a line's "drop" ranges (source seconds) and joins the pieces either side.
- Reports every pause >= 0.25s left in the assembled VO (loose cuts) so they can be tightened before render.
- Applies plan["speed"] (atempo, pitch preserved).
Writes edl.json (line boundaries + word timings in OUTPUT time) and qa/vo_check.wav, then re-transcribes
the assembled VO and diffs it against the script text so clipped / swallowed words are caught."""
import json, subprocess, sys, wave, difflib, re
import numpy as np

plan = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "plan.json"))
FF = "./venv/bin/ffmpeg"
SPEED = plan.get("speed", 1.0)
GAP_MAX = plan.get("gap_max", 0.20)
GAP_KEEP = plan.get("gap_keep", 0.10)
LINE_GAP = plan.get("line_gap", 0.05)
JOIN_GAP = 0.02   # between the pieces either side of a dropped stumble
FIX = plan.get("fix_words", {})
def fix(t):   # house spellings: whole words, any case ("creel" also catches "Creel"), punctuation kept
    for k, v in FIX.items(): t = re.sub(r"(?<!\w)" + re.escape(k) + r"(?!\w)", v, t, flags=re.I)
    return t

def load(name):
    w = wave.open(f"audio/{name}.wav"); a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a, w.getframerate()

def envelope(a, sr, hop=0.01):
    h = int(sr * hop); m = len(a) // h
    return np.sqrt((a[: m * h].reshape(m, h) ** 2).mean(1) + 1e-12), hop

def onset(e, hop, t, thr):
    lo, hi = int(max(0, t - 0.30) / hop), int((t + 0.40) / hop)
    idx = np.where(e[lo:hi] > thr)[0]
    return max(0, (lo + idx[0]) * hop - 0.04) if len(idx) else max(0, t - 0.06)

def offset(e, hop, t, thr):
    lo, hi = int(max(0, t - 0.25) / hop), min(len(e), int((t + 0.45) / hop))
    idx = np.where(e[lo:hi] > thr)[0]
    return (lo + idx[-1]) * hop + 0.06 if len(idx) else t + 0.10

def quietest(e, hop, a, b):
    lo = int(a / hop); hi = max(lo + 1, int(b / hop))
    return (lo + int(np.argmin(e[lo:hi]))) * hop

segments, words_out, lines_out, t = [], [], [], 0.0
for L in plan["lines"]:
    take, ws, we = L["take"], L["start"], L["end"]
    a, sr = load(take); e, hop = envelope(a, sr)
    thr = max(plan.get("edge_floor", 0.012), float(np.percentile(e, 30)) * 3)   # lower edge_floor for quietly recorded takes whose word tails fall under it
    tx = json.load(open(f"tx/{take}.json"))
    allw = [w for s in tx["segments"] for w in s["words"]]
    drops = sorted(tuple(d) for d in L.get("drop", []))   # stumbles to cut out, in source seconds (set from the energy, not whisper)
    words = [w for w in allw if w["start"] >= ws - 0.01 and w["end"] <= we + 0.01]
    if not words: sys.exit(f"{L['id']}: no words between {ws} and {we} in tx/{take}.json")
    # neighbouring words in the take that must NOT bleed in at the line edges
    prev_end = max([w["end"] for w in allw if w["end"] <= ws - 0.02] + [0.0])
    next_start = min([w["start"] for w in allw if w["start"] >= we + 0.02] + [1e9])
    chunks, cur = [], [words[0]]
    for w in words[1:]:
        if w["start"] - cur[-1]["end"] > GAP_MAX: chunks.append(cur); cur = [w]
        else: cur.append(w)
    chunks.append(cur)
    t_line, pmap = t, []
    for ci, ch in enumerate(chunks):
        if ci == 0: s = max(onset(e, hop, ch[0]["start"], thr), min(prev_end + 0.03, ch[0]["start"] - 0.02))
        else:
            prev = chunks[ci - 1][-1]["end"]
            s = max(quietest(e, hop, prev + 0.05, ch[0]["start"]) - GAP_KEEP / 2, prev + 0.04)
        if ci == len(chunks) - 1: en = min(offset(e, hop, ch[-1]["end"], thr) + L.get("end_pad", 0), max(next_start - 0.03, ch[-1]["end"] + 0.02))   # end_pad: extend a soft word tail (e.g. a trailing "s") the energy read misses
        else:
            nxt = chunks[ci + 1][0]["start"]
            en = min(quietest(e, hop, ch[-1]["end"] + 0.05, nxt) + GAP_KEEP / 2, nxt - 0.04)
        pieces, a0 = [], s                                  # cut the drop ranges out of this chunk
        for d0, d1 in drops:
            if d1 <= a0 or d0 >= en: continue
            if d0 > a0: pieces.append((a0, d0))
            a0 = max(a0, d1)
        if en > a0: pieces.append((a0, en))
        for pi, (p0, p1) in enumerate(pieces):
            if pi: segments.append({"line": L["id"], "src": None, "dur": JOIN_GAP, "t0": t}); t += JOIN_GAP
            segments.append({"line": L["id"], "src": take, "in": round(p0, 3), "out": round(p1, 3), "t0": t})
            pmap.append((p0, p1, t)); t += p1 - p0
    def to_out(x):
        for p0, p1, o in pmap:
            if x <= p1: return o + max(0.0, x - p0)
        return pmap[-1][2] + pmap[-1][1] - pmap[-1][0]
    if drops:
        # whisper mis-times stumbles, so caption words for a repaired line come from the script text,
        # spread over the kept speech in proportion to word length
        toks = L["text"].split(); span = sum(p1 - p0 for p0, p1, _ in pmap); tot = sum(len(x) + 1 for x in toks); acc = 0.0
        speech_t = lambda k: next(o + (k - c) for (p0, p1, o), c in zip(pmap, np.cumsum([0] + [q1 - q0 for q0, q1, _ in pmap])) if k <= c + (p1 - p0) + 1e-9)
        for x in toks:
            a_, acc = acc, acc + (len(x) + 1) / tot * span
            x = fix(x)
            words_out.append({"line": L["id"], "w": x, "s": speech_t(a_), "e": speech_t(acc) - 0.02})
    else:
        for w in words:
            txt = w["word"].strip()
            txt = fix(txt)
            words_out.append({"line": L["id"], "w": txt, "s": to_out(w["start"]), "e": to_out(w["end"])})
    lines_out.append({"line": L["id"], "t0": t_line, "t1": t})
    segments.append({"line": L["id"], "src": None, "dur": LINE_GAP, "t0": t}); t += LINE_GAP

S = lambda x: round(x / SPEED, 3)
for s in segments: s["T0"] = S(s["t0"])
for w in words_out: w["S"], w["E"] = max(0.0, S(w["s"])), S(w["e"])
for i, l in enumerate(lines_out):
    l["T0"], l["T1"] = S(l["t0"]), S(l["t1"])
# Picture boundaries: a line owns [its first-audio start, next line's start). First line starts at 0.
total = S(t - LINE_GAP)
end = round(total + plan.get("tail", 0.55), 3)
for i, l in enumerate(lines_out):
    l["cut_in"] = 0.0 if i == 0 else lines_out[i]["T0"]
    l["cut_out"] = lines_out[i + 1]["T0"] if i + 1 < len(lines_out) else end
json.dump({"speed": SPEED, "segments": segments, "words": words_out, "lines": lines_out, "total": total, "end": end},
          open("edl.json", "w"), indent=1)

# QA render (16k, for timing / intelligibility check only — final audio is cut from originals in render.py)
ins, fc, n = [], "", 0
for s in segments[:-1]:
    if s["src"]:
        d = s["out"] - s["in"]; ins += ["-ss", str(s["in"]), "-t", f"{d:.3f}", "-i", f"audio/{s['src']}.wav"]
    else:
        d = s["dur"]; ins += ["-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=16000:cl=mono"]
    fc += f"[{n}:a]aformat=sample_rates=16000:channel_layouts=mono,afade=t=in:d=0.012,afade=t=out:st={max(0, d - 0.015):.3f}:d=0.015[a{n}];"; n += 1
fc += "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,atempo={SPEED}[o]"
subprocess.run([FF, "-loglevel", "error", "-y", *ins, "-filter_complex", fc, "-map", "[o]", "qa/vo_check.wav"], check=True)

for l in lines_out: print(f'{l["line"]:5s} cut {l["cut_in"]:6.2f} -> {l["cut_out"]:6.2f}   speech {l["T0"]:6.2f}-{l["T1"]:6.2f}')
print(f"total speech {total}s, video end {end}s")

import mlx_whisper
r = mlx_whisper.transcribe("qa/vo_check.wav", path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en")
norm = lambda s: re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("-", " ")).split()
want, got = norm(" ".join(L["text"] for L in plan["lines"])), norm(r["text"])
diff = [d for d in difflib.ndiff(want, got) if d[0] in "+-"]
print("\nRE-TRANSCRIPTION:", r["text"].strip())
print("\nWORD DIFF vs script (- missing / + extra):", " ".join(diff) if diff else "none")

# loose-cut report: pauses left in the assembled VO (output time). Target ~0.15s between sentences.
w = wave.open("qa/vo_check.wav"); va = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
ve, vh = envelope(va, w.getframerate()); vthr = max(0.006, float(np.percentile(ve, 10)) * 4)
loose, k = [], 0
while k < len(ve):
    if ve[k] < vthr:
        j = k
        while j < len(ve) and ve[j] < vthr: j += 1
        if (j - k) * vh >= 0.25 and k > 0 and j < len(ve):
            before = [x["w"] for x in words_out if x["E"] <= k * vh + 0.05][-1:]
            after = [x["w"] for x in words_out if x["S"] >= j * vh - 0.10][:1]
            loose.append(f"{k * vh:6.2f}s  {(j - k) * vh:.2f}s  {' '.join(before)} | {' '.join(after)}")
        k = j
    else: k += 1
print("\nLOOSE PAUSES (>=0.25s):" + ("\n  " + "\n  ".join(loose) if loose else " none"))
