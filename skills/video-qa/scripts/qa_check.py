#!/usr/bin/env python3
"""video-qa mechanical pass: check rendered ads against the video editing standards.

  qa_check.py <video.mp4> [<video.mp4> ...] [--style default|ugly-organic|produced] [--brand NAME|CODE]
              [--plan plan.json] [--ass captions.ass] [--four-five] [--post] [--no-sheet]

Pass every hook variation of one version together; the cross-variation checks (rule 11.2, levels) need them.
For each video it writes <video dir>/.qa/<stem>/: report.json, scan.jsonl (OCR text + positions), words.json
(final-audio transcript), sheet.jpg and hook.jpg (frames for the eye pass). --post adds each issue to the
review app as a note from "QA" (skipping ones already posted, open or dismissed).

Rulebook: ../ve-video-edit-general/references/video-editing-standards.md (relative to this skill)
Brand names / market: brand-house-style.md beside it. Stdlib only (Python 3.9).
"""
import argparse, difflib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]               # the folder holding all three skills
HOUSE = SKILLS / "ve-video-edit-general/references/brand-house-style.md"
NOTES_DIR = SKILLS / "apply-notes/scripts"
FF_DIRS = [Path(p).expanduser() for p in [os.environ.get("FFMPEG_DIR")] if p]   # optional extra folder holding ffmpeg/ffprobe
WHISPER = Path(os.environ.get("MLX_WHISPER") or shutil.which("mlx_whisper") or next((p for p in [Path.home() / ".local/bin/mlx_whisper", Path("/opt/homebrew/bin/mlx_whisper")] if p.exists()), Path.home() / "Library/Python/3.9/bin/mlx_whisper"))  # pipx installs to ~/.local/bin
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
SAFE = (65, 270, 1015, 1248)          # x0, y0, x1, y1 at 1080x1920 (standards 8.1)

PROFILES = {
    # captions: expected on; pause_max: longest silence allowed inside the speech; filler/repetition checks on
    "default":      dict(captions=True,  pause_max=0.30, filler=True,  repetition=True,  length_max=60, tail_max=1.2),
    "produced":     dict(captions=True,  pause_max=0.30, filler=True,  repetition=True,  length_max=60, tail_max=6.0),
    "ugly-organic": dict(captions=False, pause_max=1.60, filler=False, repetition=False, length_max=None, tail_max=1.2),
}
# Conjunctions ("and", "so", "but", "then") at a sentence start are fine (reviewer call, 2026-10-13); only true filler is flagged
FILLER_START = {"basically", "like", "okay", "ok", "well", "yeah"}
FILLER_PHRASES = ["hey everyone", "hey guys", "hi guys", "if you don't know me", "that's it"]
STOP = set("a an the and or but so to of in on at for with is it this that i you my me we our your they he she was "
           "are be just like really very do did not no it's i'm".split())
US_UK = [("color", "colour"), ("colors", "colours"), ("favorite", "favourite"), ("favorites", "favourites"),
         ("organized", "organised"), ("organize", "organise"), ("neighborhood", "neighbourhood"),
         ("aging", "ageing"), ("smelled", "smelt"), ("center", "centre"), ("flavor", "flavour"), ("flavors", "flavours")]
NUM_WORDS = r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
UNITS = r"(?:lbs?|pounds|minutes|mins|hours|weeks|months|percent|dollars|grams|ounces|oz|inches|seconds|leds)"


# ---------------------------------------------------------------- tools
def tool(name):
    p = shutil.which(name)
    if p:
        return p
    for d in FF_DIRS:
        if (d / name).exists():
            return str(d / name)
    sys.exit(f"{name} not found on PATH (or in $FFMPEG_DIR). Install it with: brew install ffmpeg")


FF, FP = tool("ffmpeg"), tool("ffprobe")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


HOMO = str.maketrans("АВЕКМНОРСТХаеорсухіІ", "ABEKMHOPCTXaeopcyxiI")   # Cyrillic look-alikes OCR returns


def norm(w):
    return re.sub(r"[^a-z0-9$%]", "", w.translate(HOMO).lower().replace("’", "'"))


def similar(a, b, cut=0.75):
    return a == b or (len(a) > 2 and len(b) > 2 and difflib.SequenceMatcher(None, a, b).ratio() >= cut)


def clock(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------- inputs
def probe(v):
    j = json.loads(run([FP, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(v)]).stdout)
    vs = next(s for s in j["streams"] if s["codec_type"] == "video")
    au = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    num, den = (vs.get("avg_frame_rate") or "30/1").split("/")
    return {"dur": float(j["format"]["duration"]), "w": vs["width"], "h": vs["height"],
            "fps": float(num) / float(den or 1), "channels": au["channels"] if au else 0}


def textscan(v, cache):
    out = cache / "scan.jsonl"
    if not out.exists() or out.stat().st_mtime < v.stat().st_mtime:
        exe = HERE / "textscan"
        if not exe.exists():
            r = run(["swiftc", "-O", str(HERE / "textscan.swift"), "-o", str(exe)])
            if r.returncode:
                sys.exit("could not build textscan: " + r.stderr[-400:])
        r = run([str(exe), str(v), "--fps", "4"])
        if r.returncode:
            sys.exit("textscan failed: " + r.stderr[-400:])
        out.write_text(r.stdout)
    return [json.loads(l) for l in out.read_text().splitlines() if l.strip()]


def transcribe(v, cache):
    out = cache / "words.json"
    if out.exists() and out.stat().st_mtime >= v.stat().st_mtime:
        return json.loads(out.read_text())
    env = dict(os.environ)
    env["PATH"] = ":".join([str(Path(FF).parent), env.get("PATH", "")])
    with tempfile.TemporaryDirectory() as td:
        r = run([str(WHISPER), str(v), "--model", WHISPER_MODEL, "--word-timestamps", "True", "--output-format", "json",
                 "--output-dir", td, "--output-name", "t", "--verbose", "False", "--language", "en",
                 "--initial-prompt", "Um, uh, I- I, so, so, like, you know."], env=env)
        if r.returncode or not (Path(td) / "t.json").exists():
            sys.exit("transcription failed: " + (r.stderr or r.stdout)[-400:])
        data = json.loads((Path(td) / "t.json").read_text())
    words = [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)}
             for seg in data.get("segments", []) for w in seg.get("words", []) if w["end"] - w["start"] >= 0.02]
    out.write_text(json.dumps(words))
    return words


def ass_events(path):
    """Caption chunks (Cap style) and other text events from a render's captions.ass."""
    def sec(x):
        h, m, s = x.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    caps, other = [], []
    for line in Path(path).read_text().splitlines():
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        text = re.sub(r"\{[^}]*\}", "", f[9]).replace("\\N", " ").strip()
        ev = {"s": sec(f[1]), "e": sec(f[2]), "style": f[3], "text": text}
        (caps if f[3] == "Cap" else other).append(ev)
    chunks = []   # one Dialogue per active word: merge consecutive identical texts
    for ev in caps:
        if chunks and chunks[-1]["text"] == ev["text"] and abs(chunks[-1]["e"] - ev["s"]) < 0.05:
            chunks[-1]["e"] = ev["e"]
        else:
            chunks.append(dict(ev))
    return chunks, other


def house_style():
    rows = []
    if not HOUSE.exists():
        return rows
    lines = [l for l in HOUSE.read_text().splitlines() if l.startswith("|")]
    if len(lines) < 3:
        return rows
    head = [c.strip().lower() for c in lines[0].strip("|").split("|")]
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip("|").split("|")]
        rows.append(dict(zip(head, cells)))
    return rows


def pick_brand(rows, hint):
    if not hint:
        return None
    h = hint.lower()
    for r in rows:
        if h in (r.get("brand", "").lower(), r.get("code", "").lower()):
            return r
    for r in rows:   # project folder like ACM08 -> code ACM
        code = r.get("code", "").lower()
        if code and re.match(code + r"\d", h):
            return r
    return None


def house_forms(row):
    forms = []
    for part in re.split(r"[;,]", row.get("house form (exactly as written)", "")):
        f = re.sub(r"\(.*?\)", "", part).strip()
        if f:
            forms.append(f)
    return forms


# ---------------------------------------------------------------- checks
class QA:
    def __init__(self, v, args, plan, ass):
        self.v, self.args, self.plan, self.ass = v, args, plan, ass
        self.issues = []
        self.cache = v.parent / ".qa" / v.stem
        self.cache.mkdir(parents=True, exist_ok=True)
        style = args.style or plan.get("style") or (
            "ugly-organic" if plan and plan.get("captions") is False and plan.get("jump_zoom") is False else "default")
        self.style, self.P = style, PROFILES.get(style, PROFILES["default"])

    def add(self, t, level, rule, check, text):
        self.issues.append({"file": self.v.name, "t": round(t, 2), "level": level, "rule": rule, "check": check, "text": text})

    def run(self):
        self.info = probe(self.v)
        self.scan = textscan(self.v, self.cache)
        self.words = transcribe(self.v, self.cache)
        self.split_text()
        rows = house_style()
        self.brand = pick_brand(rows, self.args.brand or self.plan.get("brand") or self.v.parent.parent.name or "") or pick_brand(rows, self.v.parent.name)
        self.c_media()
        self.c_audio()
        self.c_shots()
        self.c_speech()
        self.c_hook()
        self.c_captions()
        self.c_text_style()
        self.c_safe_zone()
        return self

    # ---- which OCR text is caption vs overlay
    def split_text(self):
        """Captions = lines in the caption band (the most common centred position in the lower half).
        Overlays = upper-half lines that hold still for >= 0.5s. Everything else is text in the footage."""
        H, W = self.info["h"], self.info["w"]
        cy = lambda l: (l["box"][1] + l["box"][3]) / 2
        cx = lambda l: (l["box"][0] + l["box"][2]) / 2
        lows = [cy(l) for fr in self.scan for l in fr["lines"] if cy(l) >= 0.52 * H and abs(cx(l) - W / 2) < 0.2 * W and l["conf"] >= 0.8]
        band = sorted(lows)[len(lows) // 2] if lows else 0.62 * H
        self.band = band
        self.upper, self.lower = [], []
        def spoken(l, t):
            """A caption line is mostly words being said around now; a product label or a sign isn't."""
            toks = [norm(x) for x in l["text"].split() if norm(x)]
            near = [norm(w["w"]) for w in self.words if abs(w["s"] - t) < 3]
            return toks and sum(any(similar(x, n, 0.65) for n in near) for x in toks) >= 0.5 * len(toks)
        ht = lambda l: l["box"][3] - l["box"][1]
        hs = sorted(ht(l) for fr in self.scan for l in fr["lines"]
                    if abs(cy(l) - band) < 0.06 * H and abs(cx(l) - W / 2) < 0.2 * W and l["conf"] >= 0.8)
        hmed = hs[len(hs) // 2] if hs else 0.03 * H
        for k, fr in enumerate(self.scan):
            # captions share one line height and one vertical position; logos and labels near them don't
            lo = [l for l in fr["lines"] if abs(cy(l) - band) < 0.6 * hmed and 0.7 * hmed < ht(l) < 1.4 * hmed
                  and abs(cx(l) - W / 2) < 0.25 * W and spoken(l, fr["t"])]
            up = []
            for l in fr["lines"]:
                if cy(l) >= 0.52 * H or l["conf"] < 0.6 or abs(cx(l) - W / 2) > 0.22 * W:
                    continue
                nb = [m for j in (k - 1, k + 1) if 0 <= j < len(self.scan) for m in self.scan[j]["lines"]
                      if similar(norm(m["text"]), norm(l["text"]), 0.8) and abs(m["box"][1] - l["box"][1]) < 12]
                if nb:
                    up.append(l)
            self.upper.append((fr["t"], up))
            self.lower.append((fr["t"], lo))

    def runs(self, frames):
        """Consecutive frames with the same (normalised) text -> [{s, e, text}]."""
        out = []
        for t, lines in frames:
            txt = " ".join(l["text"] for l in lines).strip()
            key = " ".join(norm(x) for x in txt.split())
            if out and (out[-1]["key"] == key or similar(out[-1]["key"].replace(" ", ""), key.replace(" ", ""), 0.7)):
                out[-1]["e"] = t
                if len(key) > len(out[-1]["key"]):
                    out[-1]["key"], out[-1]["text"] = key, txt
            else:
                out.append({"s": t, "e": t, "text": txt, "key": key})
        return [r for r in out if r["key"]]

    # ---- format, black frames
    def c_media(self):
        i = self.info
        if (i["w"], i["h"]) != (1080, 1920):
            self.add(0, "warn", "11.4", "format", f"{i['w']}x{i['h']}; delivery format is 1080x1920 (9:16)")
        if not 29 <= i["fps"] <= 31:
            self.add(0, "warn", "11.4", "format", f"{i['fps']:.2f} fps; delivery is 30 fps")
        lm = self.P["length_max"]
        if lm and i["dur"] > lm:
            self.add(i["dur"], "warn", "4", "length", f"{i['dur']:.0f}s long; over {lm}s needs a reason in the brief")
        r = run([FF, "-hide_banner", "-nostats", "-i", str(self.v), "-vf", "blackdetect=d=0.06:pix_th=0.08", "-an", "-f", "null", "-"])
        for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr):
            self.add(float(m.group(1)), "fail", "5.7", "black frame", f"black frames {float(m.group(1)):.2f}-{float(m.group(2)):.2f}s")

    # ---- loudness, peaks, channels
    def c_audio(self):
        if not self.info["channels"]:
            self.add(0, "fail", "9", "audio", "no audio track")
            return
        r = run([FF, "-hide_banner", "-nostats", "-i", str(self.v), "-af", "ebur128=peak=true", "-f", "null", "-"])
        m = re.search(r"Integrated loudness:\s+I:\s+(-?[\d.]+) LUFS", r.stderr)
        p = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", r.stderr)
        self.lufs = float(m.group(1)) if m else None
        if self.lufs is not None and not -18.0 <= self.lufs <= -13.5:
            self.add(0, "warn", "9", "loudness", f"integrated loudness {self.lufs:.1f} LUFS; target about -16")
        if p and float(p.group(1)) > -1.0:
            self.add(0, "warn", "9", "true peak", f"true peak {float(p.group(1)):.1f} dBTP; keep under -1")
        if self.info["channels"] >= 2:
            r = run([FF, "-hide_banner", "-nostats", "-i", str(self.v), "-af", "astats=measure_overall=none:measure_perchannel=RMS_level", "-f", "null", "-"])
            lv = [float(x) for x in re.findall(r"RMS level dB:\s+(-?[\d.]+|-inf)", r.stderr) if x != "-inf"][:2]
            if len(lv) == 2 and abs(lv[0] - lv[1]) > 6:
                self.add(0, "fail", "9", "channels", f"left/right differ by {abs(lv[0]-lv[1]):.0f} dB (voice in one ear)")

    # ---- shot lengths (flash cuts)
    def c_shots(self):
        r = run([FF, "-hide_banner", "-nostats", "-i", str(self.v), "-vf", "scale=270:-2,select='gt(scene,0.30)',showinfo", "-an", "-f", "null", "-"])
        cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
        self.cuts = cuts
        bounds = [0.0] + cuts + [self.info["dur"]]
        for a, b in zip(bounds, bounds[1:]):
            if 0 < b - a < 0.3 and a > 0:
                self.add(a, "warn", "5.7", "flash cut", f"shot of {b-a:.2f}s at {clock(a)}: check frame by frame (sliver, or fast motion)")

    # ---- the voice track: start, end, pauses, filler, repetition, doubles
    def c_speech(self):
        W = self.words
        if not W:
            self.add(0, "warn", "7.1", "transcript", "no speech found in the final audio")
            return
        if W[0]["s"] > 0.6:
            self.add(0, "warn", "5.3", "late start", f"first word at {W[0]['s']:.1f}s; open on the first line")
        tail = self.info["dur"] - W[-1]["e"]
        if tail > self.P["tail_max"]:
            self.add(W[-1]["e"], "warn", "10", "ending", f"video runs {tail:.1f}s past the last word (end card or dead footage?)")
        # pauses from the audio itself, inside the speech
        pm = self.P["pause_max"]
        r = run([FF, "-hide_banner", "-nostats", "-i", str(self.v), "-af", f"silencedetect=noise=-38dB:d={pm}", "-f", "null", "-"])
        ss = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
        se = [(float(a), float(b)) for a, b in re.findall(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", r.stderr)]
        for s0, (e0, d) in zip(ss, se):
            if s0 < W[0]["s"] or e0 > W[-1]["e"]:
                continue
            if self.style != "ugly-organic" and d <= 0.45 and s0 > 0.8 * W[-1]["e"]:
                continue   # one deliberate beat before the close is allowed
            lvl = "fail" if d > 2 * pm else "warn"
            self.add(s0, lvl, "4", "pause", f"{d:.2f}s pause at {clock(s0)} (max {pm:.2f}s)")
        toks = [norm(w["w"]) for w in W]
        if self.P["repetition"]:
            for i in range(1, len(toks)):
                if toks[i] and toks[i] == toks[i - 1] and toks[i] not in {"very", "no", "so"}:
                    self.add(W[i - 1]["s"], "warn", "5.9", "doubled word", f"\"{W[i-1]['w']} {W[i]['w']}\" in the voice track (stumble survived a cut?)")
            seen = {}
            for i in range(len(toks) - 3):
                g = tuple(toks[i:i + 4])
                if all(x in STOP or not x for x in g):
                    continue
                if g in seen and W[i]["s"] - seen[g] > 2:
                    self.add(W[i]["s"], "warn", "5.2", "repetition", f"\"{' '.join(w['w'] for w in W[i:i+4])}\" said again (first at {clock(seen[g])})")
                seen.setdefault(g, W[i]["s"])
        if self.P["filler"]:
            prev_end = True
            for i, w in enumerate(W):
                if prev_end and toks[i] in FILLER_START:
                    self.add(w["s"], "warn", "5.1", "filler", f"sentence starts with \"{w['w']}\" at {clock(w['s'])}")
                prev_end = bool(re.search(r"[.?!]$", w["w"]))
            text = " ".join(w["w"].lower() for w in W)
            for ph in FILLER_PHRASES:
                for m in re.finditer(re.escape(ph), text):
                    k = text[:m.start()].count(" ")
                    self.add(W[min(k, len(W) - 1)]["s"], "warn", "5.1", "filler", f"\"{ph}\" at {clock(W[min(k, len(W)-1)]['s'])}")
        first3 = " ".join(w["w"].lower() for w in W if w["s"] < 3)
        if re.search(r"\b(hey|hi) (guys|everyone)\b", first3):
            self.add(0, "warn", "3.6", "hook", "\"hey guys\" in the first 3 seconds")

    # ---- hook overlay present, captions hidden under it, one text element
    def c_hook(self):
        up_runs = self.runs(self.upper)
        ass_hook = [e for e in (self.ass[1] if self.ass else []) if e["s"] < 1.0]
        plan_hook = [c for c in self.plan.get("callouts", []) if c.get("hook")]
        first = up_runs[0] if up_runs and up_runs[0]["s"] < 1.0 else None
        if not first and not ass_hook:
            self.add(0, "fail", "3.1", "hook overlay", "no text overlay on screen in the first second (captions alone are never enough)"
                     + (" — plan has a hook callout; check it rendered" if plan_hook else ""))
            self.hook_end = 0
            return
        # hook overlay window = from 0 until the first upper-text run that starts at 0 ends
        self.hook_end = (ass_hook[0]["e"] if ass_hook else first["e"] + 0.25)
        hook_text = ass_hook[0]["text"] if ass_hook else first["text"]
        self.hook_text = hook_text
        if not self.P["captions"]:
            return
        under = [t for t, lines in self.lower if t < self.hook_end - 0.1 and lines]
        if self.ass:
            under = [c["s"] for c in self.ass[0] if c["s"] < self.hook_end - 0.1]
        if under:
            self.add(under[0], "fail", "3.2", "captions under hook", f"captions on screen with the hook overlay \"{hook_text[:40]}\" (0–{self.hook_end:.1f}s); hide them until it leaves")
        for t, lines in ([] if under else self.upper):
            if t > self.hook_end and len(lines) >= 2:
                lo = next(x for tt, x in self.lower if tt == t)
                if lo and len({l['box'][1] // 120 for l in lines}) >= 2:
                    self.add(t, "warn", "3.2", "text clutter", f"{len(lines)} separate text items plus captions at {clock(t)}: one text element at a time")
                    break

    # ---- captions: present/absent, match the audio, doubled, casing
    def c_captions(self):
        if self.ass:
            chunks = [{"s": c["s"], "text": c["text"]} for c in self.ass[0]]
        else:
            chunks = [{"s": r["s"], "text": r["text"]} for r in self.runs(self.lower)]
        self.caption_chunks = chunks
        if not self.P["captions"]:
            if len(chunks) > 3:
                self.add(chunks[0]["s"], "fail", "2.3", "captions present", f"{len(chunks)} caption-like text changes in the lower half; this style has no captions")
            return
        if not chunks:
            self.add(self.hook_end, "fail", "7.6", "captions missing", "no captions found after the hook overlay")
            return
        cap = [(c["s"], w) for c in chunks for w in c["text"].split()]
        freq = {}   # OCR: how many frames read this exact token (a real typo reads the same every frame)
        for _, lines in self.lower:
            for tok in {norm(x) for l in lines for x in l["text"].split()}:
                freq[tok] = freq.get(tok, 0) + 1
        dictionary = set()
        if self.ass and Path("/usr/share/dict/words").exists():
            dictionary = {w.strip().lower() for w in open("/usr/share/dict/words")}
        ct = [norm(w) for _, w in cap]
        tw = [norm(w["w"]) for w in self.words]
        pairs = {a + b for a, b in zip(tw, tw[1:])}
        sm = difflib.SequenceMatcher(None, ct, tw, autojunk=False)
        src = "caption file" if self.ass else "OCR (check the frame before acting)"
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("insert", "equal"):
                continue
            for k in range(i1, i2):
                c = ct[k]
                if not c or len(set(c)) == 1:
                    continue   # empty, or a run of one letter ("wwww" = OCR on a highlighted word)
                t = cap[k][0]
                near = [norm(w["w"]) for w in self.words if abs(w["s"] - t) < 2.5]
                joins = {c}
                if k > 0: joins.add(ct[k - 1] + c)
                if k + 1 < len(ct): joins.add(c + ct[k + 1])
                cut = 0.75 if self.ass else 0.65
                joins |= {j[:-1] for j in joins if j.endswith("o")}   # OCR reads a full stop as "o"
                ok = any(similar(j, n, cut) for j in joins for n in near) or bool(joins & pairs) or len(c) <= 2 and any(n.endswith(c) for n in near)
                if not self.ass and (freq.get(c, 0) < 2 or len(c) < 3):
                    ok = True   # single-frame OCR reading: noise, not evidence
                if ok and dictionary and c.isalpha() and len(c) > 3 and c not in dictionary and c.rstrip("s") not in dictionary \
                        and not any(c == norm(f) for f in house_forms(self.brand or {}) + [(self.brand or {}).get("brand", "")]) and c not in tw:
                    self.add(t, "warn", "7.1", "spelling", f"caption word \"{cap[k][1]}\" isn't a dictionary word or in the audio; check spelling")
                if not ok:
                    self.add(t, "warn" if not self.ass else "fail", "7.1", "caption mismatch",
                             f"caption word \"{cap[k][1]}\" isn't in the audio near {clock(t)} (ghost word or typo; from {src})")
        chunk_of = [ci for ci, c in enumerate(chunks) for _ in c["text"].split()]
        for k in range(1, len(ct)):
            same_chunk = chunk_of[k] == chunk_of[k - 1]
            if ct[k] and ct[k] == ct[k - 1] and (self.ass or same_chunk) and not any(tw[j] == tw[j + 1] == ct[k] for j in range(len(tw) - 1)):
                self.add(cap[k][0], "fail", "7.1", "doubled caption", f"\"{cap[k-1][1]} {cap[k][1]}\" doubled in captions, not in the audio")
        letters = [w for _, w in cap if re.search(r"[A-Za-z]{2}", w)]
        if letters and sum(w.isupper() for w in letters) / len(letters) > 0.8 and self.plan.get("caption_case") != "upper":
            self.add(cap[0][0], "warn", "7.5", "caption case", "captions are ALL CAPS; the default is sentence case")
        if self.ass and any(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", c["text"]) for c in self.ass[0]):
            self.add(0, "warn", "7.6", "emoji", "emoji in captions")

    # ---- brand names, market spelling, number style on every piece of on-screen text
    def c_text_style(self):
        texts = [(c["s"], c["text"]) for c in self.caption_chunks]
        texts += [(r["s"], r["text"]) for r in self.runs(self.upper)]
        if self.ass:
            texts += [(e["s"], e["text"]) for e in self.ass[1]]
        brand = self.brand
        seen = set()
        def flag(t, rule, check, msg):
            if (check, msg) not in seen:
                seen.add((check, msg)); self.add(t, "warn", rule, check, msg)
        for t, txt in texts:
            if brand:
                for f in house_forms(brand):
                    for m in re.finditer(r"(?<![\w.])" + re.escape(f) + r"(?![\w])", txt, re.I):
                        if m.group(0) != f and not (txt.isupper() and not f.isupper()):   # ALL CAPS text is flagged once under 7.5
                            flag(t, "7.2", "brand name", f"\"{m.group(0)}\" should be \"{f}\" at {clock(t)}")
                for bad in [b.strip() for b in re.split(r"[;,]", brand.get("corrected from", "")) if b.strip()]:   # known misspellings
                    for m in re.finditer(r"(?<![\w.])" + re.escape(bad) + r"(?![\w])", txt, re.I):
                        flag(t, "7.2", "brand name", f"\"{m.group(0)}\" is a known misspelling (house form: {', '.join(house_forms(brand)[:2])}) at {clock(t)}")
                mk = brand.get("market", "")
                if mk.startswith("US") or mk.startswith("UK"):
                    for us, uk in US_UK:
                        bad = uk if mk.startswith("US") else us
                        good = us if mk.startswith("US") else uk
                        if re.search(r"\b" + bad + r"\b", txt, re.I):
                            flag(t, "7.3", "market spelling", f"\"{bad}\" should be \"{good}\" ({mk[:2]} market) at {clock(t)}")
                    if mk.startswith("US") and re.search(r"\bmate\b", txt, re.I):
                        flag(t, "7.3", "market spelling", f"\"mate\" in a US ad at {clock(t)}")
            low = txt.lower()
            if re.search(r"\b" + NUM_WORDS + r"[\s-]+" + UNITS + r"\b", low):
                flag(t, "7.4", "number style", f"spelled-out number with a unit in \"{txt[:40]}\"; use digits (45 lbs, 12 minutes)")
            if re.search(r"\b\d[\d,.]*\s*dollars\b", low):
                flag(t, "7.4", "number style", f"\"dollars\" in \"{txt[:40]}\"; use $")
            if re.search(r"\bdrug store\b", low):
                flag(t, "7.4", "number style", "\"drug store\" should be \"drugstore\"")
            if re.search(r"\b(2|two) in (1|one)\b", low):
                flag(t, "7.4", "number style", "use \"2-in-1\"")
            if re.search(r"\bmoney back\b", low) or re.search(r"\b\d+ day money", low):
                flag(t, "7.4", "number style", "hyphenate: \"90-day money-back guarantee\"")

    # ---- every piece of text inside the safe zone (and the 4:5 frame)
    def c_safe_zone(self):
        W, H = self.info["w"], self.info["h"]
        sx = W / 1080
        x0, y0, x1, y1 = (v * sx for v in SAFE)
        lower = dict(self.lower)
        upper = dict(self.upper)
        level = "fail" if self.ass else "warn"
        # graphic text anywhere = crisp, wide lines that hold still into the next sample (end cards, badges)
        graphic = {}
        for k, fr in enumerate(self.scan):
            nxt = self.scan[k + 1]["lines"] if k + 1 < len(self.scan) else []
            graphic[fr["t"]] = [l for l in fr["lines"] if l["conf"] >= 0.9 and l["box"][2] - l["box"][0] > 0.35 * W
                                and any(norm(m["text"]) == norm(l["text"]) and abs(m["box"][1] - l["box"][1]) < 8 for m in nxt)]

        def out_of(b):
            out = []
            if b[0] < x0 - 4 or b[2] > x1 + 4: out.append("sides")
            if b[1] < y0 - 4: out.append("top 14%")
            if b[3] > y1 + 4: out.append("bottom 35%")
            if self.args.four_five and (b[1] < 300 * sx or b[3] > 1620 * sx): out.append("4:5 crop")
            return out

        caps_out, seen = [], set()
        for fr in self.scan:
            t = fr["t"]
            for l in lower.get(t, []):
                o = out_of(l["box"])
                if o and len(re.sub(r"\W", "", l["text"])) >= 2:
                    caps_out.append((t, l["box"], tuple(o)))
            for l in upper.get(t, []) + [g for g in graphic.get(t, []) if g not in lower.get(t, [])]:
                o = out_of(l["box"])
                key = (norm(l["text"])[:20], tuple(o))
                if o and len(re.sub(r"\W", "", l["text"])) >= 3 and key not in seen:
                    seen.add(key)
                    self.add(t, level, "8.1", "safe zone", f"\"{l['text'][:40]}\" crosses the safe zone ({', '.join(o)}) at {clock(t)}")
        if caps_out:   # captions share one position: report them once, not per chunk
            where = sorted({x for _, _, o in caps_out for x in o})
            lo_edge = max(b[3] for _, b, _ in caps_out) / sx
            hi_edge = min(b[1] for _, b, _ in caps_out) / sx
            edge = f"lowest edge y {lo_edge:.0f}" if "bottom 35%" in where else f"top edge y {hi_edge:.0f}"
            self.add(caps_out[0][0], level, "8.1", "safe zone",
                     f"captions cross the safe zone ({', '.join(where)}) in {len(caps_out)} frames from {clock(caps_out[0][0])} to "
                     f"{clock(caps_out[-1][0])} ({edge} at 1080x1920; the limit is y 270–1248)")


# ---------------------------------------------------------------- variations
def compare(qas):
    issues = []
    lv = [(q.v.name, q.lufs) for q in qas if getattr(q, "lufs", None) is not None]
    if len(lv) > 1 and max(x for _, x in lv) - min(x for _, x in lv) > 1.5:
        issues.append({"file": "all", "t": 0, "level": "warn", "rule": "9", "check": "levels across variations",
                       "text": "loudness differs across variations: " + ", ".join(f"{n} {x:.1f}" for n, x in lv)})
    ref = qas[0]
    rt = [norm(w["w"]) for w in ref.words]
    for q in qas[1:]:
        qt = [norm(w["w"]) for w in q.words]
        sm = difflib.SequenceMatcher(None, rt, qt, autojunk=False)
        n = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal" or i1 < 0.25 * len(rt) or j1 < 0.25 * len(qt):
                continue   # hooks differ by design; compare the body
            if max(i2 - i1, j2 - j1) < 3:
                continue   # one or two words = transcription noise, not an edit difference
            if q.words[min(j1, len(q.words) - 1)]["s"] > q.info["dur"] - 1.5:
                continue
            a = " ".join(w["w"] for w in ref.words[i1:i2]) or "(nothing)"
            b = " ".join(w["w"] for w in q.words[j1:j2]) or "(nothing)"
            t = q.words[min(j1, len(q.words) - 1)]["s"]
            issues.append({"file": q.v.name, "t": round(t, 2), "level": "warn", "rule": "11.2", "check": "variation drift",
                           "text": f"body differs from {ref.v.name} at {clock(t)}: \"{b[:60]}\" here vs \"{a[:60]}\" there (fix applied to one variation only?)"})
            n += 1
            if n >= 5:
                break
    return issues


# ---------------------------------------------------------------- eye-pass sheets
def sheets(q, issues):
    """hook.jpg = first 3s every 0.5s; sheet.jpg = mid-frame of every shot + every flagged moment, timestamped."""
    def grab(times, out, cols):
        with tempfile.TemporaryDirectory() as td:
            fs = []
            for t in times:
                f = Path(td) / f"{len(fs):03d}.jpg"   # numbered by success, so one bad grab can't end the sheet
                label = clock(t).replace(":", "\\:")
                run([FF, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, t):.2f}", "-i", str(q.v), "-frames:v", "1",
                     "-vf", f"scale=270:480,drawtext=fontfile={FONT}:text='{label}':x=8:y=8:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,scale=out_range=full,format=yuvj420p",
                     "-y", str(f)])
                if f.exists():
                    fs.append(f)
            if not fs:
                return
            rows = (len(fs) + cols - 1) // cols
            run([FF, "-hide_banner", "-loglevel", "error", "-framerate", "1", "-i", str(Path(td) / "%03d.jpg"),
                 "-vf", f"tile={cols}x{rows}:padding=4:color=black", "-frames:v", "1", "-y", str(out)])
    dur = q.info["dur"]
    grab([x * 0.5 for x in range(7)], q.cache / "hook.jpg", 7)
    bounds = [0.0] + q.cuts + [dur]
    mids = [(a + b) / 2 for a, b in zip(bounds, bounds[1:]) if b - a > 0.15][:48]
    flagged = sorted({i["t"] for i in issues if i["file"] == q.v.name and i["t"] > 0})[:16]
    grab(sorted(set(round(t, 2) for t in mids + flagged)), q.cache / "sheet.jpg", 8)


# ---------------------------------------------------------------- posting to the review app
def post(issues, videos):
    sys.path.insert(0, str(NOTES_DIR))
    import review_server as rs
    import uuid, time
    for v in videos:
        root = next((p for p in v.parents if (p / "_review").is_dir()), None) or rs.DEFAULT_ROOT
        try:
            rel_proj = v.resolve().relative_to(Path(root).resolve())
        except ValueError:
            print(f"(not posted: {v} is outside the review root {root})")
            continue
        code = rel_proj.parts[0]
        proj = Path(root) / code
        rel = v.resolve().relative_to(proj.resolve()).as_posix()
        rs.ROOT = Path(root); rs.TX_DIR = Path(root) / "_review" / "transcripts"
        d = rs.load_notes(proj)
        have = {(n["file"], n["text"]) for n in d["notes"] if n.get("author") == "QA"}
        hook, version = rs.parse_name(Path(rel).stem)
        added = 0
        for i in issues:
            if i["file"] not in (v.name, "all"):
                continue
            text = f"[{i['level'].upper()} · rule {i['rule']}] {i['text']}"
            if (rel, text) in have:
                continue
            d["notes"].append({"id": uuid.uuid4().hex[:8], "file": rel, "hook": hook, "version": version, "t": i["t"],
                               "words": rs.words_at(code, rel, i["t"]), "text": text, "author": "QA", "status": "open",
                               "reply": "", "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
            added += 1
        rs.save_notes(proj, d)
        print(f"posted {added} QA note(s) to {code}/{rel}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--style")
    ap.add_argument("--brand")
    ap.add_argument("--plan")
    ap.add_argument("--ass")
    ap.add_argument("--four-five", action="store_true")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    vids = [Path(x).expanduser().resolve() for x in a.videos]
    qas = []
    for v in vids:
        side_plan = v.with_suffix(".plan.json")
        side_ass = v.with_suffix(".captions.ass")
        plan = json.loads(Path(a.plan or side_plan).read_text()) if (a.plan or side_plan.exists()) else {}
        assp = a.ass or (str(side_ass) if side_ass.exists() else None)
        q = QA(v, a, plan, ass_events(assp) if assp else None).run()
        qas.append(q)
    issues = [i for q in qas for i in q.issues]
    if len(qas) > 1:
        issues += compare(qas)
    order = {"fail": 0, "warn": 1}
    issues.sort(key=lambda i: (i["file"], order[i["level"]], i["t"]))
    for q in qas:
        mine = [i for i in issues if i["file"] in (q.v.name, "all")]
        (q.cache / "report.json").write_text(json.dumps({"file": str(q.v), "style": q.style,
            "brand": (q.brand or {}).get("brand"), "captions_from": "ass" if q.ass else "ocr",
            "duration": q.info["dur"], "issues": mine}, indent=2))
        if not a.no_sheet:
            sheets(q, issues)
        f = sum(i["level"] == "fail" for i in mine); w = sum(i["level"] == "warn" for i in mine)
        print(f"\n== {q.v.name}  [{q.style}; brand {(q.brand or {}).get('brand', '?')}; captions from {'ass' if q.ass else 'ocr'}]  {f} fail, {w} warn")
        for i in mine:
            print(f"  {i['level'].upper():4} {clock(i['t']):>7}  rule {i['rule']:<5} {i['check']}: {i['text']}")
        print(f"  eye-pass frames: {q.cache/'hook.jpg'}  {q.cache/'sheet.jpg'}")
    if a.post:
        post(issues, vids)
    sys.exit(1 if any(i["level"] == "fail" for i in issues) else 0)


if __name__ == "__main__":
    main()
