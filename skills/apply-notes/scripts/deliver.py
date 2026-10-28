#!/usr/bin/env python3
"""Deliver finished cuts to a Google Drive folder through Google Drive for desktop.

Drive folders are found by their Drive ID (from a link), never by a typed path: names can repeat
across a drive and can carry invisible trailing spaces. Files are copied, never overwritten.

  deliver.py show CODE                                  destination + what a delivery would copy (JSON)
  deliver.py set CODE --folder LINK_OR_ID [--subfolder NAME | --no-subfolder]
  deliver.py run CODE [--file REL ...] [--wait 180]     copy approved cuts (or the given files) and confirm
  deliver.py resolve LINK_OR_ID [--hint PATH]           local folder for a Drive folder
  deliver.py clients                                    folders used before, by project-code prefix

ROOT defaults to ~/Video Edits; override with REVIEW_ROOT.
Per project: <ROOT>/<CODE>/delivery.json (destination + delivery log).
Per Mac: <ROOT>/_review/delivery-folders.json (which folder each client prefix, e.g. "SCB", went to last).
"""
import argparse, ctypes, ctypes.util, filecmp, glob, json, os, re, shutil, sys, time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_server as rs  # noqa: E402

ROOT = Path(os.environ.get("REVIEW_ROOT", rs.DEFAULT_ROOT)).expanduser().resolve()
rs.ROOT = ROOT
CLIENTS = ROOT / "_review" / "delivery-folders.json"
XATTR = b"com.google.drivefs.item-id#S"   # set by Google Drive for desktop on every synced file and folder
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def drive_id(path):
    buf = ctypes.create_string_buffer(512)
    n = libc.getxattr(os.fsencode(str(path)), XATTR, buf, 512, 0, 0)
    return buf.raw[:n].decode() if n > 0 else None


def parse_id(s):
    m = re.search(r"/folders/([\w-]{10,})", s) or re.search(r"[?&]id=([\w-]{10,})", s) or re.search(r"/d/([\w-]{10,})", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{10,}", s.strip()):
        return s.strip()
    sys.exit(f"Can't find a Drive folder ID in {s!r}. Paste the folder's link from the browser address bar.")


def drive_roots():
    roots = [Path(p) for p in sorted(glob.glob(str(Path.home() / "Library/CloudStorage/GoogleDrive-*")))]
    if not roots:
        sys.exit("Google Drive for desktop isn't set up on this Mac (no ~/Library/CloudStorage/GoogleDrive-* folder). "
                 "Install it from https://www.google.com/drive/download/ and sign in.")
    return roots


def index_paths(target_id):
    """Candidate local paths from Drive for desktop's own metadata index (instant, unlike walking the drive).
    The index is undocumented, so every candidate is still checked against the folder's Drive ID by the caller."""
    import sqlite3
    out = []
    for db in glob.glob(str(Path.home() / "Library/Application Support/Google/DriveFS/*/metadata_sqlite_db")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            rows = con.execute(
                "WITH RECURSIVE chain(sid, depth) AS (SELECT stable_id, 0 FROM items WHERE id=? "
                "UNION ALL SELECT p.parent_stable_id, depth+1 FROM stable_parents p JOIN chain c ON p.item_stable_id=c.sid WHERE depth<40) "
                "SELECT i.local_title, i.stable_id = i.team_drive_stable_id FROM chain c JOIN items i ON i.stable_id=c.sid ORDER BY depth",
                (target_id,)).fetchall()
            con.close()
        except Exception:
            continue
        if not rows:
            continue
        names = [r[0] for r in reversed(rows)]
        top_is_shared_drive = bool(rows[-1][1])
        for r in drive_roots():
            if top_is_shared_drive:
                out.append(r / "Shared drives" / Path(*names))
            else:   # My Drive: the top of the chain is the My Drive root itself
                out.append(r / "My Drive" / Path(*names[1:]) if len(names) > 1 else r / "My Drive")
    return out


def resolve(target_id, hints=(), limit=60):
    """Local folder whose Drive ID is target_id: hints, then Drive's index, then walk the synced drives."""
    for h in list(hints) + index_paths(target_id):
        if h and Path(h).is_dir() and drive_id(h) == target_id:
            return Path(h)
    t0 = time.time()
    q = deque()
    for r in drive_roots():
        for top in ("My Drive", "Shared drives", "Other computers"):
            if (r / top).is_dir():
                q.append((r / top, 0))
    while q:
        d, depth = q.popleft()
        if drive_id(d) == target_id:
            return d
        if depth >= 12 or time.time() - t0 > limit:
            continue
        try:
            for e in os.scandir(d):
                if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                    q.append((Path(e.path), depth + 1))
        except OSError:
            pass
    sys.exit(f"No synced folder has Drive ID {target_id}. Check that this Google account can open the link "
             "and that Google Drive for desktop has finished starting up.")


def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def save(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    os.replace(tmp, p)


def proj(code):
    p = ROOT / code
    if not p.is_dir():
        sys.exit(f"No project folder {p}")
    return p


def prefix(code):
    m = re.match(r"[A-Za-z]+", code)
    return m.group(0).upper() if m else code


def approved_files(p):
    s = rs.project_summary(p)
    return [h["latest"] for _, h in sorted(s["hooks"].items()) if h["status"] == "approved"]


def cmd_show(code):
    p = proj(code)
    cfg = load(p / "delivery.json", {})
    clients = load(CLIENTS, {})
    out = {"code": code, "destination": None, "suggested": None, "approved": approved_files(p),
           "delivered": [d["file"] for d in cfg.get("delivered", [])]}
    if cfg.get("folder"):
        out["destination"] = {"folder": cfg["folder"], "subfolder": cfg.get("subfolder")}
    elif prefix(code) in clients:
        out["suggested"] = {"prefix": prefix(code), **clients[prefix(code)]}
    out["to_deliver"] = [f for f in out["approved"] if f not in out["delivered"]]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_set(code, folder, subfolder, no_subfolder):
    p = proj(code)
    fid = parse_id(folder)
    clients = load(CLIENTS, {})
    cfg = load(p / "delivery.json", {})
    hints = [cfg.get("folder", {}).get("path")] + [c.get("path") for c in clients.values()]
    d = resolve(fid, hints)
    cfg["folder"] = {"id": fid, "name": d.name, "path": str(d), "link": f"https://drive.google.com/drive/folders/{fid}"}
    if no_subfolder:
        cfg["subfolder"] = None
    elif subfolder is not None:
        cfg["subfolder"] = subfolder.strip()
    else:
        cfg.setdefault("subfolder", code)
    cfg.pop("subfolder_id", None)
    cfg.setdefault("delivered", [])
    save(p / "delivery.json", cfg)
    clients[prefix(code)] = {**{k: cfg["folder"][k] for k in ("id", "name", "path", "link")}, "last_code": code,
                             "last_used": time.strftime("%Y-%m-%d")}
    save(CLIENTS, clients)
    where = d.name + (f" / {cfg['subfolder']}" if cfg["subfolder"] else "")
    print(f"{code} delivers to: {where}\n  local: {d}")


def wait_id(path, wait):
    t0 = time.time()
    while time.time() - t0 < wait:
        i = drive_id(path)
        if i:
            return i
        time.sleep(2)
    return None


def cmd_run(code, files, wait):
    p = proj(code)
    cfg = load(p / "delivery.json", {})
    if not cfg.get("folder"):
        sys.exit(f"No destination set for {code}. Ask which Drive folder to use, then: deliver.py set {code} --folder <link>")
    clients = load(CLIENTS, {})
    folder = resolve(cfg["folder"]["id"], [cfg["folder"].get("path")] + [c.get("path") for c in clients.values()])
    cfg["folder"]["path"] = str(folder)
    dest = folder
    if cfg.get("subfolder"):
        dest = folder / cfg["subfolder"]
        if dest.exists() and not dest.is_dir():
            sys.exit(f"{dest} exists and isn't a folder.")
        if not dest.exists():
            dest.mkdir()
            print(f"created folder: {cfg['subfolder']}")
        sid = wait_id(dest, wait)
        if sid:
            cfg["subfolder_id"] = sid
    todo = files or [f for f in approved_files(p) if f not in {d["file"] for d in cfg.get("delivered", [])}]
    if not todo:
        sys.exit("Nothing to deliver: no approved version that hasn't been delivered already. "
                 "Approve a version in the review app, or name the file with --file.")
    results, problems = [], []
    for rel in todo:
        src = p / rel
        if not src.is_file():
            problems.append(f"{rel}: not found in the project"); continue
        out = dest / src.name
        if out.exists():
            if out.stat().st_size == src.stat().st_size and filecmp.cmp(src, out, shallow=False):
                status = "already there (identical)"
            else:
                problems.append(f"{src.name}: a different file with this name is already in the Drive folder; not overwritten"); continue
        else:
            shutil.copyfile(src, out)
            if not filecmp.cmp(src, out, shallow=False):
                problems.append(f"{src.name}: copy doesn't match the original"); continue
            status = "copied"
        fid = wait_id(out, wait)
        rec = {"file": rel, "name": src.name, "size": src.stat().st_size, "dest": str(dest),
               "drive_id": fid, "link": f"https://drive.google.com/file/d/{fid}/view" if fid else None,
               "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": status}
        results.append(rec)
        cfg.setdefault("delivered", [])
        cfg["delivered"] = [d for d in cfg["delivered"] if d["file"] != rel] + [rec]
        if not fid:
            problems.append(f"{src.name}: Drive hasn't picked it up after {wait}s (still uploading, or Drive for desktop is paused)")
    save(p / "delivery.json", cfg)
    print(json.dumps({"folder": cfg["folder"]["name"], "subfolder": cfg.get("subfolder"),
                      "subfolder_link": f"https://drive.google.com/drive/folders/{cfg['subfolder_id']}" if cfg.get("subfolder_id") else None,
                      "results": results, "problems": problems}, indent=2, ensure_ascii=False))
    sys.exit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("show"); a.add_argument("code")
    a = sub.add_parser("set"); a.add_argument("code"); a.add_argument("--folder", required=True)
    g = a.add_mutually_exclusive_group(); g.add_argument("--subfolder"); g.add_argument("--no-subfolder", action="store_true")
    a = sub.add_parser("run"); a.add_argument("code"); a.add_argument("--file", action="append", default=[])
    a.add_argument("--wait", type=int, default=180)
    a = sub.add_parser("resolve"); a.add_argument("target"); a.add_argument("--hint")
    sub.add_parser("clients")
    a = ap.parse_args()
    if a.cmd == "show": cmd_show(a.code)
    elif a.cmd == "set": cmd_set(a.code, a.folder, a.subfolder, a.no_subfolder)
    elif a.cmd == "run": cmd_run(a.code, a.file, a.wait)
    elif a.cmd == "resolve": print(resolve(parse_id(a.target), [a.hint]))
    elif a.cmd == "clients": print(json.dumps(load(CLIENTS, {}), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
