#!/usr/bin/env python3
"""Local review app for agentic video edits.

Serves every project folder under ROOT (default: ~/Video Edits, or $REVIEW_ROOT)
as one review page: versions + hooks per ad, notes pinned to the playhead (with the words spoken
there), approvals. Notes live in <ROOT>/<CODE>/review-notes.json so apply-notes can read them.

Usage: python3 review_server.py [--root DIR] [--port 8765] [--no-transcribe]
Stdlib only (Python 3.9). Transcripts use mlx_whisper in a background thread.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(os.environ.get("REVIEW_ROOT", "~/Video Edits")).expanduser()
FF_DIRS = [Path(p).expanduser() for p in [os.environ.get("FFMPEG_DIR")] if p]   # optional extra folder holding ffmpeg/ffprobe
WHISPER = Path(os.environ.get("MLX_WHISPER") or shutil.which("mlx_whisper") or next((p for p in [Path.home() / ".local/bin/mlx_whisper", Path("/opt/homebrew/bin/mlx_whisper")] if p.exists()), Path.home() / "Library/Python/3.9/bin/mlx_whisper"))  # pipx installs to ~/.local/bin
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
SKIP_DIRS = {"Media", "Raw", "Ref", "Projects", "Review", "Audio", "Transcripts", "Photos", "parts", "qa", "audio", "sheets", "proxies", "venv"}

LOCK = threading.Lock()
ROOT = DEFAULT_ROOT
TX_DIR = ROOT / "_review" / "transcripts"
TX_STATE = {"queue": [], "running": None, "failed": {}}


def parse_name(stem):
    m = re.search(r"_v(\d+)$", stem)
    version = int(m.group(1)) if m else 1
    base = stem[: m.start()] if m else stem
    h = re.search(r"(?:Hook|Var|Hook-|H-)([A-Z])(?=$|_)", base) or re.search(r"_([A-Z])$", base)
    hook = h.group(1) if h else "Main"
    return hook, version


def project_dirs():
    return sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def scan_videos(proj):
    """Finished cuts: Exports/*.mp4, plus top-level and skill-v*/ mp4s for older projects."""
    cands = []
    for d in [proj / "Exports", proj] + sorted(proj.glob("skill-v*")):
        if d.is_dir():
            cands += [f for f in d.glob("*.mp4") if not f.name.startswith(".")]
    vids = []
    for f in cands:
        hook, version = parse_name(f.stem)
        rel = f.relative_to(proj).as_posix()
        vids.append({"file": rel, "name": f.name, "hook": hook, "version": version,
                     "mtime": f.stat().st_mtime, "src": f"/media/{proj.name}/{rel}"})
    vids.sort(key=lambda v: (v["hook"], v["version"], v["mtime"]))
    return vids


def notes_path(proj):
    return proj / "review-notes.json"


def load_notes(proj):
    p = notes_path(proj)
    if p.exists():
        try:
            d = json.loads(p.read_text())
            d.setdefault("notes", []); d.setdefault("approvals", {}); d.setdefault("title", proj.name)
            return d
        except Exception:
            pass
    return {"title": proj.name, "notes": [], "approvals": {}}


def save_notes(proj, d):
    p = notes_path(proj)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    os.replace(tmp, p)


def tx_file(code, rel):
    return TX_DIR / (code + "__" + rel.replace("/", "__") + ".json")


def load_words(code, rel):
    f = tx_file(code, rel)
    if f.exists():
        try:
            return json.loads(f.read_text()).get("words", [])
        except Exception:
            return None
    return None


def words_at(code, rel, t, before=1.2, after=1.6):
    ws = load_words(code, rel) or []
    near = [w for w in ws if w["e"] >= t - before and w["s"] <= t + after]
    return " ".join(w["w"] for w in near).strip()


def project_summary(proj, full=False):
    vids = scan_videos(proj)
    d = load_notes(proj)
    hooks = {}
    for v in vids:
        hooks.setdefault(v["hook"], []).append(v)
    hook_info = {}
    for h, vs in hooks.items():
        latest = max(vs, key=lambda v: (v["version"], v["mtime"]))
        open_n = sum(1 for n in d["notes"] if n.get("hook") == h and n.get("status") == "open")
        if d["approvals"].get(latest["file"]):
            st = "approved"
        elif open_n:
            st = "notes"
        else:
            st = "review"
        hook_info[h] = {"latest": latest["file"], "status": st, "open": open_n,
                        "versions": vs if full else [{"file": v["file"], "version": v["version"]} for v in vs]}
    sts = [i["status"] for i in hook_info.values()]
    if sts and all(s == "approved" for s in sts):
        status = "approved"
    elif "notes" in sts:
        status = "notes"
    else:
        status = "review"
    out = {"code": proj.name, "title": d.get("title", proj.name), "status": status,
           "open": sum(i["open"] for i in hook_info.values()), "hooks": hook_info,
           "mtime": max([v["mtime"] for v in vids] + [notes_path(proj).stat().st_mtime if notes_path(proj).exists() else 0])}
    if full:
        out["notes"] = d["notes"]
        out["approvals"] = d["approvals"]
        out["words"] = {v["file"]: load_words(proj.name, v["file"]) for v in vids}
    return out


# ---------- transcription worker ----------
def ff_env():
    env = dict(os.environ)
    extra = [str(p) for p in FF_DIRS if (p / "ffmpeg").exists()]
    env["PATH"] = ":".join(extra + [env.get("PATH", "")])
    return env


def transcribe(code, rel):
    src = ROOT / code / rel
    out = tx_file(code, rel)
    with tempfile.TemporaryDirectory() as td:
        cmd = [str(WHISPER), str(src), "--model", WHISPER_MODEL, "--word-timestamps", "True",
               "--output-format", "json", "--output-dir", td, "--output-name", "t", "--verbose", "False",
               "--language", "en"]
        r = subprocess.run(cmd, env=ff_env(), capture_output=True, text=True)
        j = Path(td) / "t.json"
        if r.returncode != 0 or not j.exists():
            raise RuntimeError((r.stderr or r.stdout)[-400:])
        data = json.loads(j.read_text())
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            if w["end"] - w["start"] < 0.02:
                continue
            words.append({"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"file": rel, "words": words}))


def tx_worker():
    while True:
        try:
            for proj in project_dirs():
                for v in scan_videos(proj):
                    key = proj.name + "/" + v["file"]
                    if tx_file(proj.name, v["file"]).exists() or key in TX_STATE["failed"]:
                        continue
                    TX_STATE["running"] = key
                    try:
                        transcribe(proj.name, v["file"])
                    except Exception as e:
                        TX_STATE["failed"][key] = str(e)[:300]
                    TX_STATE["running"] = None
        except Exception as e:
            print("transcribe loop:", e, file=sys.stderr)
        time.sleep(10)


# ---------- "Apply notes" button: run Claude Code headless on one ad ----------
# Fully unattended: the background run may use local file and shell tools without asking.
# No MCP connectors, web or messaging tools are allowed.
# Folder Claude Code starts in. Skills installed in ~/.claude/skills load from anywhere; if you installed them in a
# project's .claude/skills instead, set APPLY_NOTES_CWD to that project folder.
START_DIR = Path(os.environ["APPLY_NOTES_CWD"]).expanduser() if os.environ.get("APPLY_NOTES_CWD") else None
JOBS = {}                                            # code -> job dict (see start_job)
APPLY_TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill", "TodoWrite"]
APPLY_DENY = ["WebFetch", "WebSearch", "mcp__*"]
APPLY_PROMPT = """/apply-notes {code}

You were started by the review app's "Apply notes" button, so nobody is watching this run. Apply every open review note on {code} following the apply-notes skill end to end: change the edit, render the next version(s) into Exports, check them, and reply on every note with notes.py. Don't ask questions or wait for confirmation. If a note is ambiguous or can't be done, reply on that note with your question using --keep-open and carry on with the rest. Only touch files for this edit; don't upload, send or share anything. Finish with a 2-3 sentence summary of what you rendered and what is still open."""
VARIATIONS_PROMPT = """/apply-notes {code} build variations

You were started by the review app after the reviewer approved variation A of {code}, so nobody is watching this run. Follow the apply-notes skill's "Build the variations" section: take the approved A cut as fixed, build the other hook variations the brief/plan calls for (B, C, D by default) so they differ from A only in the hook, render v1 of each into Exports, run video-qa on all hooks together, and fix any FAILs on the new variations without changing A. Don't ask questions or wait for confirmation. Only touch files for this edit; don't upload, send or share anything. Finish with a 2-3 sentence summary of the variations you built and what each hook does differently."""


def claude_bin():
    """The Claude Code CLI: CLAUDE_BIN, PATH, the usual install spots, else the newest copy bundled with the desktop app."""
    cands = [os.environ.get("CLAUDE_BIN"), shutil.which("claude"),
             str(Path.home() / ".local/bin/claude"), str(Path.home() / ".claude/local/claude")]
    bundled = sorted(Path.home().glob("Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for c in cands + [str(p) for p in bundled]:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def claude_signed_in(binp):
    try:
        r = subprocess.run([binp, "auth", "status"], capture_output=True, text=True, timeout=20)
        return bool(json.loads(r.stdout or "{}").get("loggedIn"))
    except Exception:
        return False


def summarize_event(ev):
    """One short progress line from a stream-json event."""
    if ev.get("type") != "assistant":
        return None
    for c in reversed(ev.get("message", {}).get("content", [])):
        if c.get("type") == "tool_use":
            inp = c.get("input", {})
            what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("skill") or ""
            return f"{c.get('name')}: {str(what)[:120]}"
        if c.get("type") == "text" and c.get("text", "").strip():
            return c["text"].strip().splitlines()[0][:160]
    return None


def job_public(j):
    return {k: j.get(k) for k in ("status", "mode", "started", "finished", "last", "result", "log", "error")}


def start_job(code, mode="notes"):
    binp = claude_bin()
    if not binp:
        return {"error": "Couldn't find the Claude Code CLI on this Mac."}
    if not claude_signed_in(binp):
        return {"error": "The Claude Code CLI isn't signed in. Run `claude` once in a terminal and sign in, then try again."}
    logdir = ROOT / "_review" / "apply-logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / f"{code}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    prompt = (VARIATIONS_PROMPT if mode == "variations" else APPLY_PROMPT).format(code=code)
    cmd = [binp, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *APPLY_TOOLS,
           "--disallowedTools", *APPLY_DENY, "--add-dir", str(ROOT)]
    proc = subprocess.Popen(cmd, cwd=str(START_DIR or ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=ff_env(), start_new_session=True)
    j = {"status": "running", "mode": mode, "started": time.time(), "finished": None, "last": "Starting Claude…",
         "result": "", "log": str(log), "proc": proc, "error": ""}
    JOBS[code] = j

    def pump():
        with open(log, "w") as fh:
            for line in proc.stdout:
                fh.write(line); fh.flush()
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                s = summarize_event(ev)
                if s:
                    j["last"] = s
                if ev.get("type") == "result":
                    j["result"] = (ev.get("result") or "").strip()
                    if ev.get("is_error"):
                        j["error"] = j["result"] or "Claude stopped with an error."
        proc.wait()
        j["finished"] = time.time()
        if j["status"] == "stopped":
            return
        j["status"] = "failed" if (proc.returncode or j["error"]) else "done"
        if j["status"] == "failed" and not j["error"]:
            j["error"] = f"Exited with code {proc.returncode}. Log: {log}"

    threading.Thread(target=pump, daemon=True).start()
    return {"ok": True}


def stop_job(code):
    j = JOBS.get(code)
    if j and j["status"] == "running":
        j["status"] = "stopped"
        try:
            os.killpg(j["proc"].pid, 15)
        except Exception:
            pass


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def proj(self, code):
        p = (ROOT / code).resolve()
        if p.parent != ROOT.resolve() or not p.is_dir():
            raise KeyError(code)
        return p

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                b = (HERE / "review.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/state":
                self.send_json({"root": str(ROOT), "projects": [project_summary(p) for p in project_dirs()],
                                "transcribing": TX_STATE["running"],
                                "jobs": {c: job_public(j) for c, j in JOBS.items()}})
            elif u.path == "/api/project":
                self.send_json(project_summary(self.proj(q["code"][0]), full=True))
            elif u.path.startswith("/media/"):
                self.serve_media(unquote(u.path[len("/media/"):]))
            else:
                self.send_error(404)
        except KeyError:
            self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_media(self, relpath):
        f = (ROOT / relpath).resolve()
        if ROOT.resolve() not in f.parents or not f.is_file():
            return self.send_error(404)
        size = f.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:
                    start = max(0, size - int(m.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        length = end - start + 1
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            proj = self.proj(body["code"])
            if u.path == "/api/apply":
                j = JOBS.get(proj.name)
                if j and j["status"] == "running":
                    return self.send_json({"error": "Claude is already working on this ad."}, 409)
                mode = body.get("mode", "notes")
                if mode == "variations":
                    s_ = project_summary(proj)
                    first = sorted(s_["hooks"])[0] if s_["hooks"] else None
                    if not first or s_["hooks"][first]["status"] != "approved":
                        return self.send_json({"error": "Approve variation A first."}, 400)
                elif not any(n["status"] == "open" for n in load_notes(proj)["notes"]):
                    return self.send_json({"error": "No open notes on this ad."}, 400)
                r = start_job(proj.name, mode)
                return self.send_json(r, 200 if r.get("ok") else 400)
            if u.path == "/api/apply/stop":
                stop_job(proj.name)
                return self.send_json({"ok": True})
            if u.path == "/api/apply/clear":
                j = JOBS.get(proj.name)
                if j and j["status"] != "running":
                    JOBS.pop(proj.name)
                return self.send_json({"ok": True})
            with LOCK:
                d = load_notes(proj)
                if u.path == "/api/notes/add":
                    rel = body["file"]
                    hook, version = parse_name(Path(rel).stem)
                    t = round(float(body["t"]), 2)
                    n = {"id": uuid.uuid4().hex[:8], "file": rel, "hook": hook, "version": version, "t": t,
                         "words": body.get("words") or words_at(proj.name, rel, t),
                         "text": body["text"].strip(), "author": body.get("author", "Reviewer"),
                         "status": "open", "reply": "", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    d["notes"].append(n)
                elif u.path == "/api/notes/update":
                    for n in d["notes"]:
                        if n["id"] == body["id"]:
                            for k in ("status", "text"):
                                if k in body:
                                    n[k] = body[k]
                            n["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                elif u.path == "/api/notes/delete":
                    d["notes"] = [n for n in d["notes"] if n["id"] != body["id"]]
                elif u.path == "/api/approve":
                    if body.get("value"):
                        d["approvals"][body["file"]] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    else:
                        d["approvals"].pop(body["file"], None)
                else:
                    return self.send_error(404)
                save_notes(proj, d)
            self.send_json(project_summary(proj, full=True))
        except KeyError:
            self.send_error(400)


def main():
    global ROOT, TX_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-transcribe", action="store_true")
    a = ap.parse_args()
    ROOT = Path(a.root).expanduser().resolve()
    TX_DIR = ROOT / "_review" / "transcripts"
    if not a.no_transcribe and WHISPER.exists():
        threading.Thread(target=tx_worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"Review app: http://localhost:{a.port}  (root: {ROOT})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
