"""Premiere Pro package for a finished cut: an editable timeline (Final Cut Pro 7 XML, which Premiere opens with
File > Import), the captions as .srt, every headline/callout as a transparent PNG, and the end card.
Run from the workdir after render.py:  ./venv/bin/python <skill>/scripts/premiere_xml.py <package dir> [plan.json] [name]
<package dir> is normally $EDITS/<CODE>/Premiere; [name] defaults to the plan's output name (<CODE>_Hook<X>_v<N>).
Needs plan.json, edl.json, clips.json and captions.ass (prep.py, build_vo.py and render.py write them) and the
source files they point to. Optional sources.json ({clip: {"folder", "name"}}) overrides the media folder/file names.

Layout of <package dir> (every version and hook of a project shares one package; media is written once):
  README.txt                                  how to open, relink and match the MP4's pace (written every run)
  media/<Drive folder>/<original file name>   the source clips the timeline points to (APFS clones, no extra disk)
  <name>/<name>.xml                           the timeline: V1 picture, V2+ headlines, top track end card, A1 voice
  <name>/<name>_captions.srt                  import and drop on the sequence for an editable caption track
  <name>/graphics/*.png                       headline PNGs (1080x1920, transparent) and the end card
  <name>/<name>_notes.txt                     what this timeline doesn't reproduce from the MP4

The timeline runs at natural speed: every clip plays at 100%, so trims and slips behave normally. The export sped
the voice up by plan["speed"]; README.txt explains the one step that matches it exactly.
Not carried over: the colour grade, loudness normalisation, punch-in/push-in animation (scale is set, not keyframed)."""
import json, os, sys, re, subprocess, shutil, html
from urllib.parse import quote
import numpy as np
from PIL import Image

PKG = os.path.abspath(os.path.expanduser(sys.argv[1]))
PLAN = sys.argv[2] if len(sys.argv) > 2 else "plan.json"
plan, edl = json.load(open(PLAN)), json.load(open("edl.json"))
NAME = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(plan.get("output", "edit_v1.mp4"))[0]
FF, FPS, W, H = "./venv/bin/ffmpeg", 30, 1080, 1920
FFPROBE = shutil.which("ffprobe") or next((p for p in ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"] if os.path.exists(p)), None)
if not FFPROBE: sys.exit("ffprobe not found: install ffmpeg with Homebrew (brew install ffmpeg)")
SP, END = edl["speed"], edl["end"]
MIN_SHOT = plan.get("min_shot", 0.30)
src_info = json.load(open("sources.json")) if os.path.exists("sources.json") else {}
clips_info = json.load(open("clips.json")) if os.path.exists("clips.json") else {}
LB = {l["line"]: l for l in edl["lines"]}

# edl.json and captions.ass belong to the LAST build_vo.py / render.py run in this workdir. If that was another plan
# (another hook or version), the package would mix two cuts, so refuse instead.
if [l["id"] for l in plan["lines"]] != [l["line"] for l in edl["lines"]]:
    sys.exit(f"edl.json was built from a different plan than {PLAN}: run build_vo.py and render.py on it first")
_ass = open("captions.ass").read()
_over = sorted(re.sub(r"\{[^}]*\}", "", l.split(",", 9)[9]) for l in _ass.splitlines() if l.startswith("Dialogue:") and l.split(",", 9)[3] != "Cap")
_want = sorted(c["text"].replace("\n", "\\N") for c in plan.get("callouts", []) if c.get("style") != "image")
if _over != _want:
    sys.exit(f"captions.ass is from a different render than {PLAN} (its headlines don't match the plan's callouts): run render.py on it first")

OUT = f"{PKG}/{NAME}"; GFX = f"{OUT}/graphics"
os.makedirs(GFX, exist_ok=True)
fr = lambda t: int(round(t * FPS))          # seconds -> sequence frames
nat = lambda t: t * SP                      # export time -> natural-speed timeline time
IMG = (".jpg", ".jpeg", ".png", ".heic")

def raw_path(code):
    if code in clips_info and os.path.exists(clips_info[code]["path"]): return clips_info[code]["path"]   # what render.py used
    for dp, _, fs in os.walk("raw"):
        for f in fs:
            if os.path.splitext(f)[0] == code: return os.path.join(dp, f)
    sys.exit(f"no raw file for {code}")

def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height,channels:stream_side_data=rotation:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    j = json.loads(r.stdout); v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    w, h = v.get("width", W), v.get("height", H)
    if any(abs(sd.get("rotation", 0)) == 90 for sd in v.get("side_data_list", [])): w, h = h, w
    if path.lower().endswith(IMG):   # a photo: no real duration, so give it an hour like the headline stills
        return {"w": w, "h": h, "dur": 3600, "ach": 0, "still": True}
    return {"w": w, "h": h, "dur": float(j["format"]["duration"]), "ach": a["channels"] if a else 0}

# ---------- media: copy each used clip into the package under its original name ----------
files, fid = {}, [0]
def media(code):
    if code in files: return files[code]
    s = src_info.get(code, {}); rp = raw_path(code)
    folder, name = s.get("folder", os.path.basename(os.path.dirname(rp))), s.get("name", os.path.basename(rp))
    dst = f"{PKG}/media/{folder}/{name}"
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if subprocess.run(["cp", "-c", rp, dst]).returncode: shutil.copy2(rp, dst)   # APFS clone, else a real copy
    fid[0] += 1
    files[code] = dict(probe(rp), id=f"file-{fid[0]}", name=name, path=dst, defined=False)
    return files[code]

def still(path):
    fid[0] += 1
    return {"w": W, "h": H, "dur": 3600, "ach": 0, "id": f"file-{fid[0]}", "name": os.path.basename(path), "path": path, "defined": False, "still": True}

def file_xml(f):
    if f["defined"]: return f'<file id="{f["id"]}"/>'
    f["defined"] = True
    aud = (f'<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>'
           f'<channelcount>{f["ach"]}</channelcount></audio>') if f["ach"] else ""
    return (f'<file id="{f["id"]}"><name>{html.escape(f["name"])}</name><pathurl>file://localhost{quote(f["path"])}</pathurl>'
            f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><duration>{fr(f["dur"])}</duration>'
            f'<media><video><samplecharacteristics><width>{f["w"]}</width><height>{f["h"]}</height></samplecharacteristics></video>{aud}</media></file>')

def motion(scale):
    return ('<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>'
            '<effecttype>motion</effecttype><mediatype>video</mediatype><parameter authoringApp="PremierePro"><parameterid>scale</parameterid>'
            f'<name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>{scale:.2f}</value></parameter></effect></filter>')

cid = [0]
def clip(f, start, end, src_in, kind="video", scale=None, label=None):
    """start/end on the timeline and src_in in the source, all in seconds."""
    n = fr(end) - fr(start)
    if n <= 0: return ""                     # under half a frame: a 0-frame clip confuses Premiere, skip it
    cid[0] += 1; i0 = fr(src_in)
    body = (f'<clipitem id="clipitem-{cid[0]}"><name>{html.escape(label or f["name"])}</name><enabled>TRUE</enabled>'
            f'<duration>{fr(f["dur"])}</duration><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
            f'<start>{fr(start)}</start><end>{fr(start) + n}</end><in>{i0}</in><out>{i0 + n}</out>{file_xml(f)}')
    if kind == "audio": body += '<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>'
    elif scale is not None: body += motion(scale)
    return body + "</clipitem>"

# ---------- V1 picture: same pieces render.py cuts, laid out at natural speed ----------
def aroll_pieces(line, a, b):   # mirrors render.py: picture follows the voice's pause trims, slivers folded
    segs = [s for s in edl["segments"] if s["line"] == line]
    out, last = [], None
    for s in segs:
        t0 = s["T0"]
        if s["src"]: t1 = t0 + (s["out"] - s["in"]) / SP; src, sin = s["src"], s["in"]; last = (src, s["out"], t1)
        else: t1 = t0 + s["dur"] / SP; src, sin = last[0], last[1]
        lo, hi = max(a, t0), min(b, t1)
        if hi - lo > 1e-3: out.append((src, sin + (lo - t0) * SP, hi - lo))
    if a < segs[0]["T0"] - 1e-3:
        out.insert(0, (segs[0]["src"], max(0, segs[0]["in"] - (segs[0]["T0"] - a) * SP), segs[0]["T0"] - a))
    got = sum(p[2] for p in out)
    if b - a - got > 1e-3: src, sout, t1 = last; out.append((src, sout + max(0, a - t1) * SP, b - a - got))
    merged = []
    for p in out:
        if merged and p[2] < MIN_SHOT: s0, i0, d0 = merged[-1]; merged[-1] = (s0, i0, d0 + p[2])
        else: merged.append(p)
    if len(merged) > 1 and merged[0][2] < MIN_SHOT:
        s1, i1, d1 = merged[1]; merged[1] = (s1, i1 - merged[0][2] * SP, d1 + merged[0][2]); merged.pop(0)
    return merged

cover = lambda f: 100 * max(W / f["w"], H / f["h"])   # fill the 9:16 frame and crop, as render.py does

v1, notes, t = [], [], 0.0
for s in plan["shots"]:
    a, b = LB[s["lines"][0]]["cut_in"], LB[s["lines"][-1]]["cut_out"]
    if s["type"] == "aroll":
        k = 0
        for lid in s["lines"]:
            for src, sin, d in aroll_pieces(lid, LB[lid]["cut_in"], LB[lid]["cut_out"]):
                f = media(src); z = s.get("zoom", 1.0) * (1.08 if (s.get("jump_zoom", plan.get("jump_zoom", True)) and k % 2) else 1.0)
                v1.append(clip(f, t, t + d * SP, sin, scale=cover(f) * z)); t += d * SP; k += 1
    elif s["type"] == "still":
        f = media(s["clip"]); d = (b - a) * SP
        v1.append(clip(f, t, t + d, 0, scale=cover(f))); t += d
        notes.append(f"{t - d:.1f}s: slow push-in on {f['name']} not carried over (add Scale keyframes +7%)")
    else:
        f = media(s["clip"]); d = (b - a) * SP; sin = s.get("in", 0)
        if sin + d > f["dur"]: notes.append(f"{s['clip']}: not enough footage after {sin}s at natural speed; started earlier"); sin = max(0, f["dur"] - d)
        v1.append(clip(f, t, t + d, sin, scale=cover(f) * s.get("zoom", 1.0))); t += d
        if s.get("push"): notes.append(f"{t - d:.1f}s: slow push-in on {f['name']} not carried over (add Scale keyframes +7%)")

# ---------- A1 voice ----------
a1 = []
segs = [g for g in edl["segments"] if g["src"]]
for i, g in enumerate(segs):
    f = media(g["src"]); st = nat(g["T0"]); d = g["out"] - g["in"]
    if i == len(segs) - 1: d += (END - edl["total"]) * SP           # render.py lets the last take run through the tail
    a1.append(clip(f, st, st + d, g["in"], kind="audio"))

# ---------- headlines -> transparent PNGs on V2; captions -> .srt ----------
ass = open("captions.ass").read().splitlines()
head_i = next(i for i, l in enumerate(ass) if l.startswith("[Events]"))
def secs(x): h, m, s = x.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)
events = [l for l in ass[head_i:] if l.startswith("Dialogue:")]
cap, over = [], []
for l in events:
    p = l.split(",", 9); a, b, style, txt = secs(p[1]), secs(p[2]), p[3], p[9]
    (cap if style == "Cap" else over).append((a, b, txt, l))

def matte(lines, out):
    """render ASS lines over black and over white, solve for colour + alpha: exactly the libass look, transparent."""
    tmp = f"{GFX}/_tmp.ass"; open(tmp, "w").write("\n".join(ass[:head_i + 2] + lines) + "\n")
    shots = []
    for bg in ("black", "white"):
        o = f"{GFX}/_{bg}.png"
        subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color={bg}:s={W}x{H}:d=1", "-vf",
                        f"subtitles={tmp}:fontsdir=fonts", "-frames:v", "1", o], check=True)
        shots.append(np.asarray(Image.open(o).convert("RGB")).astype(np.float32)); os.remove(o)
    os.remove(tmp)
    k, wh = shots
    alpha = np.clip(1 - (wh - k).mean(axis=2) / 255, 0, 1)
    alpha[alpha < 3 / 255] = 0                                   # rounding noise: keep the background fully clear
    rgb = np.where(alpha[..., None] > 1e-3, k / np.maximum(alpha[..., None], 1e-3), 0)
    Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8), "RGBA").save(out)

v2 = []
for i, (a, b, txt, l) in enumerate(over):
    png = f"{GFX}/{NAME}_text{i + 1:02d}.png"
    p = l.split(",", 9); p[1], p[2] = "0:00:00.00", "0:00:05.00"   # on screen at frame 0, without its fade
    body = re.sub(r"\\fad\(\d+,\d+\)", "", ",".join(p))
    matte([body], png)
    plain = re.sub(r"\{[^}]*\}", "", txt).replace("\\N", " / ")
    v2.append((nat(a), nat(b), clip(still(png), nat(a), nat(b), 0, scale=100, label=plain)))

# an image-style hook (ugly-organic) isn't in captions.ass: render.py overlays hook.png instead, so place that
for c in plan.get("callouts", []):
    if c.get("style") == "image" and os.path.exists("hook.png"):
        a, b = LB[c["lines"][0]]["cut_in"], LB[c["lines"][-1]]["cut_out"]
        png = f"{GFX}/{NAME}_hook.png"; shutil.copy("hook.png", png)
        v2.append((nat(a), nat(b), clip(still(png), nat(a), nat(b), 0, scale=100, label="hook " + c.get("text", "").replace("\n", " / "))))

def srt_tc(x):
    ms = int(round(x * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
chunks = []
for a, b, txt, _ in cap:                  # one event per highlighted word: merge into one cue per caption chunk
    plain = re.sub(r"\{[^}]*\}", "", txt).strip()
    if chunks and chunks[-1][2] == plain and abs(chunks[-1][1] - a) < 0.05: chunks[-1][1] = b
    else: chunks.append([a, b, plain])
with open(f"{OUT}/{NAME}_captions.srt", "w") as f:
    for i, (a, b, txtc) in enumerate(chunks, 1): f.write(f"{i}\n{srt_tc(nat(a))} --> {srt_tc(nat(b))}\n{txtc}\n\n")

# ---------- V3 end card ----------
v3, total = [], nat(END)
ec = plan.get("endcard")
if ec:
    img = ec["image"]; dst = f"{GFX}/endcard.png"; shutil.copy(img, dst)
    fade, hold = ec.get("fade", 0.4), ec.get("hold", 1.8)
    v3.append(clip(still(dst), nat(END) - fade, nat(END) + hold, 0, scale=100, label="end card"))
    total = nat(END) + hold
    notes.append(f"end card cross-fade ({fade}s) not carried over: add a Cross Dissolve or opacity fade at {nat(END) - fade:.1f}s")

track = lambda items: "<track>" + "".join(items) + "</track>"
# headlines that overlap in time can't share a track: stack them on V2, V3, ... (end card goes on the track above)
lanes = []
for a, b, x in sorted(v2, key=lambda e: e[0]):
    lane = next((l for l in lanes if fr(l[-1][1]) <= fr(a)), None)
    if lane is None: lanes.append([]); lane = lanes[-1]
    lane.append((a, b, x))
v2_tracks = "".join(track([x for _, _, x in l]) for l in lanes) or track([])
xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="sequence-1"><name>{NAME}</name>'
       f'<duration>{fr(total)}</duration><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
       f'<timecode><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
       f'<media><video><format><samplecharacteristics><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><width>{W}</width><height>{H}</height>'
       f'<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>{track(v1)}{v2_tracks}{track(v3)}</video>'
       f'<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>'
       f'{track(a1)}</audio></media></sequence></xmeml>\n')
open(f"{OUT}/{NAME}.xml", "w").write(xml)
open(f"{OUT}/{NAME}_notes.txt", "w").write(
    f"{NAME}: timeline at natural speed ({total:.2f}s). The exported MP4 ran the voice at {SP}x ({total / SP:.2f}s).\n"
    f"To match the MP4's pace: nest the sequence and set Speed/Duration to {SP * 100:g}% with Maintain Audio Pitch on.\n"
    f"Not carried over from the MP4:\n- colour grade ({plan.get('grade', 'eq=contrast=1.04:saturation=1.07')}: a light contrast/saturation lift)\n"
    "- loudness normalisation (-14 LUFS, light compression, 80 Hz high-pass)\n"
    + "".join(f"- {n}\n" for n in notes))
open(f"{PKG}/README.txt", "w").write("""Premiere Pro package
====================

Each folder here is one cut (<project>_Hook<letter>_v<version>). media/ holds the original clips every cut uses.

Open a cut
1. In Premiere: File > Import, choose the cut's .xml file. Premiere adds a sequence with the cut's name.
2. If Premiere asks where the media is (the "Link Media" window): click Locate, open this package's media folder,
   select the clip it names and keep "Relink others automatically" ticked. The rest relink with it.
3. Captions: File > Import the cut's _captions.srt and drag it onto the sequence as a caption track
   (restyle it in the Essential Graphics or Captions panel).

What's on the timeline
- V1: the picture (talking head and b-roll), every clip at 100% speed with the punch-ins set as Scale.
- V2 and up: headlines and callouts as transparent PNGs (graphics/), positioned exactly as in the MP4.
- Top video track: the end card, when there is one.
- A1: the voice, one clip per kept phrase from the original takes.

Matching the MP4's pace
The MP4 plays the voice slightly faster than recorded (the speed is in each cut's _notes.txt, e.g. 1.08x).
The timeline is at natural speed so trims and slips behave normally. To match the MP4 exactly: right-click the
sequence in a new sequence to nest it, then Speed/Duration > the percentage in the cut's _notes.txt
(108% for 1.08x) with Maintain Audio Pitch on.

Not carried over from the MP4 (listed per cut in _notes.txt): the colour grade, loudness normalisation and
compression, push-in animations and fades.
""")
print(f"premiere: {OUT}/{NAME}.xml  ({len(v1)} picture clips, {len(v2)} headlines on {max(len(lanes), 1)} track(s), {len(a1)} voice clips, {len(chunks)} captions, {total:.2f}s)")
