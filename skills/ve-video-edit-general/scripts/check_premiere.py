"""Check a Premiere package timeline using only its XML, the way Premiere will read it.
Run from the workdir after premiere_xml.py:  ./venv/bin/python <skill>/scripts/check_premiere.py <cut>.xml [plan.json]
Checks: every clip points at media that exists and stays inside it; V1 runs gap-free from the first frame; no clips
overlap on a track; the picture follows the plan's shots in order; every graphic sits inside the Meta safe zone;
and the voice, rebuilt from A1 alone and transcribed, says the plan's script. Exit 1 if anything fails."""
import sys, os, re, json, subprocess, tempfile, difflib, xml.etree.ElementTree as ET
from urllib.parse import unquote
from PIL import Image

XML = sys.argv[1]
plan = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "plan.json"))
FF = "./venv/bin/ffmpeg" if os.path.exists("./venv/bin/ffmpeg") else "ffmpeg"
SAFE = dict(x0=65, x1=1015, y0=270, y1=1248)
fails, oks = [], []

seq = ET.parse(XML).getroot().find("sequence")
fps = int(seq.find("rate/timebase").text); total = int(seq.find("duration").text)
files = {}
for f in seq.iter("file"):
    if f.find("pathurl") is not None:
        files[f.get("id")] = {"path": unquote(f.find("pathurl").text.replace("file://localhost", "", 1)),
                              "dur": int(f.find("duration").text), "name": f.find("name").text}

def items(track):
    out = []
    for ci in track.findall("clipitem"):
        g = lambda k: int(ci.find(k).text)
        sc = ci.find(".//parameter[parameterid='scale']/value")
        out.append({"name": ci.find("name").text, "start": g("start"), "end": g("end"), "in": g("in"), "out": g("out"),
                    "file": files[ci.find("file").get("id")], "scale": float(sc.text) if sc is not None else 100.0})
    return sorted(out, key=lambda c: c["start"])

vt = seq.findall("media/video/track"); at = seq.findall("media/audio/track")
V1, A1 = items(vt[0]), items(at[0])

# 1. media exists and every clip stays inside it; durations agree; no overlaps on any track
bad = 0
for ti, tr in enumerate(vt + at):
    prev = None
    for c in items(tr):
        f = c["file"]
        if not os.path.exists(f["path"]): fails.append(f"missing media: {f['path']}"); bad += 1
        if c["in"] < 0 or c["out"] > f["dur"]: fails.append(f"{c['name']}: frames {c['in']}-{c['out']} outside its media (0-{f['dur']})"); bad += 1
        if c["out"] - c["in"] != c["end"] - c["start"] or c["end"] <= c["start"]: fails.append(f"{c['name']} at {c['start']}: bad length"); bad += 1
        if prev and c["start"] < prev["end"]: fails.append(f"track {ti + 1}: {c['name']} overlaps {prev['name']} at frame {c['start']}"); bad += 1
        prev = c
if not bad: oks.append(f"all {sum(len(t.findall('clipitem')) for t in vt + at)} clips point at existing media and stay inside it; no overlaps")

# 2. V1 covers the sequence without gaps
gaps = [(a["end"], b["start"]) for a, b in zip(V1, V1[1:]) if b["start"] != a["end"]]
if V1 and V1[0]["start"] == 0 and not gaps and V1[-1]["end"] >= total - 1: oks.append(f"V1 runs gap-free for {total} frames ({total / fps:.2f}s)")
else: fails.append(f"V1 isn't continuous: starts at {V1[0]['start'] if V1 else '-'}, gaps {gaps[:5]}, ends {V1[-1]['end'] if V1 else '-'} of {total}")

# 3. picture follows the plan's shots in order (by source clip)
stem = lambda p: os.path.splitext(os.path.basename(p))[0]
L = {l["id"]: l for l in plan["lines"]}
want = []
for s in plan["shots"]:
    for src in ([L[i]["take"] for i in s["lines"]] if s["type"] == "aroll" else [s["clip"]]):
        if not want or want[-1] != src: want.append(src)
got = []
for c in V1:
    if not got or got[-1] != stem(c["file"]["path"]): got.append(stem(c["file"]["path"]))
if got == want: oks.append(f"V1 follows the plan's shots in order ({' > '.join(got)})")
else: fails.append(f"V1 order {got} doesn't match the plan {want}")

# 4. graphics inside the safe zone
gfx = [c for t in vt[1:] for c in items(t)]
for c in gfx:
    im = Image.open(c["file"]["path"]).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box is None: continue
    if c["scale"] != 100: fails.append(f"{c['name']}: scaled to {c['scale']}%, can't check the safe zone"); continue
    x0, y0, x1, y1 = box
    if x0 < SAFE["x0"] or x1 > SAFE["x1"] or y0 < SAFE["y0"] or y1 > SAFE["y1"]:
        fails.append(f"graphic '{c['name']}' spans x {x0}-{x1}, y {y0}-{y1}: outside the safe zone")
if gfx and not any("safe zone" in f for f in fails): oks.append(f"{len(gfx)} graphic(s) inside the safe zone")

# 5. the voice, rebuilt from A1 alone, says the script
def report():
    for o in oks: print("OK  ", o)
    for f in fails: print("FAIL", f)
    sys.exit(1 if fails else 0)
if not A1: fails.append("A1 has no voice clips"); report()
if any(not os.path.exists(c["file"]["path"]) for c in A1): fails.append("voice not checked: A1 points at missing media"); report()
tmp = tempfile.mkdtemp(); ins, fc = [], ""
for i, c in enumerate(A1):
    ins += ["-ss", f"{c['in'] / fps:.4f}", "-t", f"{(c['out'] - c['in']) / fps:.4f}", "-i", c["file"]["path"]]
    fc += f"[{i}:a]aformat=sample_rates=16000:channel_layouts=mono,adelay={int(c['start'] / fps * 1000)}[a{i}];"
fc += "".join(f"[a{i}]" for i in range(len(A1))) + f"amix=inputs={len(A1)}:normalize=0[o]"
r = subprocess.run([FF, "-loglevel", "error", "-y", *ins, "-filter_complex", fc, "-map", "[o]", "-ac", "1", f"{tmp}/a1.wav"], capture_output=True, text=True)
if r.returncode: fails.append(f"voice not checked: ffmpeg couldn't rebuild A1 ({r.stderr.strip()[-200:]})"); report()
import mlx_whisper
heard = mlx_whisper.transcribe(f"{tmp}/a1.wav", path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en")["text"]
norm = lambda t: re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()
fixes = {k.lower(): v.lower() for k, v in plan.get("fix_words", {}).items()}
a, b = norm(" ".join(l["text"] for l in plan["lines"])), [fixes.get(w, w) for w in norm(heard)]
ratio = difflib.SequenceMatcher(None, a, b).ratio()
diff = [d for d in difflib.ndiff(a, b) if d[0] in "+-"]
(oks if ratio >= 0.97 else fails).append(f"voice rebuilt from A1 matches the script {ratio:.0%}" + (f" (differences: {' '.join(diff)})" if diff else ""))
report()
