#!/usr/bin/env python3
"""Read and answer review notes from the command line (used by apply-notes and video-qa).

  notes.py list CODE [--hook A] [--all]          open notes (or all) as a table + JSON on --json
  notes.py reply CODE ID "what changed" [--keep-open]   reply on a note; marks it done unless --keep-open
  notes.py add CODE FILE SECONDS "text" [--author QA]  add a note (QA flags use --author QA)
  notes.py next CODE HOOK                        path for the next version of a hook (never overwrites)
  notes.py status                                one line per ad: status, open notes, latest versions
  notes.py packages CODE [--trash | --keep]      draft Premiere packages left over once a hook is approved;
                                                 --trash moves them (and media nothing else uses) to the Trash,
                                                 --keep remembers the person wants them kept (not offered again)

ROOT defaults to ~/Video Edits; override with REVIEW_ROOT.
Writes go to <ROOT>/<CODE>/review-notes.json, the same file the review app reads.
"""
import json, os, re, sys, time, uuid
from urllib.parse import unquote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_server as rs  # noqa: E402

ROOT = Path(os.environ.get("REVIEW_ROOT", rs.DEFAULT_ROOT)).expanduser().resolve()
rs.ROOT = ROOT
rs.TX_DIR = ROOT / "_review" / "transcripts"


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def proj(code):
    p = ROOT / code
    if not p.is_dir():
        sys.exit(f"No project folder {p}")
    return p


def cmd_list(code, hook=None, everything=False, as_json=False):
    p = proj(code)
    d = rs.load_notes(p)
    ns = [n for n in d["notes"] if (everything or n["status"] == "open") and (not hook or n["hook"] == hook)]
    ns.sort(key=lambda n: (n["hook"], n["version"], n["t"]))
    if as_json:
        print(json.dumps(ns, indent=2, ensure_ascii=False))
        return
    if not ns:
        print("No open notes.")
        return
    for n in ns:
        print(f"[{n['id']}] {n['hook']} v{n['version']} @ {fmt(n['t'])} ({n['t']:.2f}s) {n['author']} · {n['status']}")
        print(f"    file:  {n['file']}")
        if n.get("words"):
            print(f"    words: \"{n['words']}\"")
        print(f"    note:  {n['text']}")
        if n.get("reply"):
            print(f"    reply: {n['reply']}")


def cmd_reply(code, nid, text, keep_open=False):
    p = proj(code)
    d = rs.load_notes(p)
    for n in d["notes"]:
        if n["id"] == nid:
            n["reply"] = text
            if not keep_open:
                n["status"] = "done"
            n["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            rs.save_notes(p, d)
            print(f"Replied to {nid} ({n['status']}).")
            return
    sys.exit(f"No note {nid} in {code}")


def cmd_add(code, rel, t, text, author="QA"):
    p = proj(code)
    if not (p / rel).exists():
        sys.exit(f"No file {p / rel}")
    hook, version = rs.parse_name(Path(rel).stem)
    d = rs.load_notes(p)
    n = {"id": uuid.uuid4().hex[:8], "file": rel, "hook": hook, "version": version, "t": round(float(t), 2),
         "words": rs.words_at(code, rel, float(t)), "text": text, "author": author, "status": "open",
         "reply": "", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d["notes"].append(n)
    rs.save_notes(p, d)
    print(n["id"])


def cmd_next(code, hook):
    p = proj(code)
    vids = [v for v in rs.scan_videos(p) if v["hook"] == hook]
    nv = max([v["version"] for v in vids] or [0]) + 1
    tag = "Main" if hook == "Main" else f"Hook{hook}"
    print(p / "Exports" / f"{code}_{tag}_v{nv}.mp4")


def cmd_status():
    for p in rs.project_dirs():
        s = rs.project_summary(p)
        hooks = ", ".join(f"{h}:{i['latest'].split('/')[-1]}({i['status']})" for h, i in sorted(s["hooks"].items()))
        print(f"{s['code']:8} {s['status']:9} open={s['open']:<3} {hooks}")


def draft_packages(p):
    """Premiere packages of unapproved, undelivered versions of hooks whose latest version is approved."""
    pkg = p / "Premiere"
    if not pkg.is_dir():
        return [], pkg
    s = rs.project_summary(p)
    approvals = rs.load_notes(p)["approvals"]
    kept = set(json.loads((pkg / ".cleanup.json").read_text()).get("kept", [])) if (pkg / ".cleanup.json").exists() else set()
    try:
        delivered = {d.get("cut") for d in json.loads((p / "delivery.json").read_text()).get("delivered", []) if d.get("kind") == "premiere"}
    except Exception:
        delivered = set()
    approved_hooks = {h for h, i in s["hooks"].items() if i["status"] == "approved"}
    out = []
    for d in sorted(pkg.iterdir()):
        if not (d / f"{d.name}.xml").exists():
            continue
        hook, _ = rs.parse_name(d.name)
        if hook in approved_hooks and not approvals.get(f"Exports/{d.name}.mp4") and d.name not in delivered | kept:
            out.append(d)
    return out, pkg


def cmd_packages(code, trash=False, keep=False):
    p = proj(code)
    drafts, pkg = draft_packages(p)
    if not drafts:
        print("No draft Premiere packages to clean up.")
        return
    size = lambda d: sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    if keep:
        f = pkg / ".cleanup.json"
        d = json.loads(f.read_text()) if f.exists() else {}
        d["kept"] = sorted(set(d.get("kept", [])) | {x.name for x in drafts})
        f.write_text(json.dumps(d, indent=2))
        print(f"Keeping {len(drafts)} package(s); they won't be offered for clean-up again.")
        return
    if not trash:
        print(f"Draft Premiere packages for approved hooks in {code} ({len(drafts)}):")
        for d in drafts:
            print(f"  {d.name}  ({size(d) / 1e6:.1f} MB)")
        print("Run with --trash to move them to the Trash, or --keep to keep them.")
        return
    bin_ = Path.home() / ".Trash"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for d in drafts:
        d.rename(bin_ / f"{code} Premiere {d.name} {stamp}")
        print(f"moved to Trash: {d.name}")
    # media that no remaining timeline uses
    used = set()
    for x in pkg.glob("*/*.xml"):
        used |= {unquote(u) for u in re.findall(r"<pathurl>file://localhost([^<]+)</pathurl>", x.read_text())}
    media = pkg / "media"
    for f in sorted(media.rglob("*")) if media.is_dir() else []:
        if f.is_file() and str(f) not in used:
            f.rename(bin_ / f"{code} Premiere media {f.name} {stamp}")
            print(f"moved to Trash: media/{f.relative_to(media)} (no remaining timeline uses it)")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c = a[0]
    flags = {x for x in a if x.startswith("--")}
    pos = [x for x in a[1:] if not x.startswith("--")]
    if c == "list":
        hook = a[a.index("--hook") + 1] if "--hook" in a else None
        if hook in pos:
            pos.remove(hook)
        cmd_list(pos[0], hook, "--all" in flags, "--json" in flags)
    elif c == "reply":
        cmd_reply(pos[0], pos[1], pos[2], "--keep-open" in flags)
    elif c == "add":
        author = a[a.index("--author") + 1] if "--author" in a else "QA"
        if author in pos:
            pos.remove(author)
        cmd_add(pos[0], pos[1], pos[2], pos[3], author)
    elif c == "next":
        cmd_next(pos[0], pos[1])
    elif c == "status":
        cmd_status()
    elif c == "packages":
        cmd_packages(pos[0], "--trash" in flags, "--keep" in flags)
    else:
        sys.exit(__doc__)
