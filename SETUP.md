# Setup checklist (for Claude)

Follow this when someone asks to "set up video editing" on their Mac, or when an edit fails because a tool is missing. The person is probably not technical: explain each step in one plain sentence, run the commands yourself, and only hand them a step when it needs their password or a click in a system dialog. Re-running the checklist is safe; skip any step whose check already passes.

## What the person does first

1. Install the Claude desktop app and sign in. (Done if you're reading this.)
2. Install Homebrew from https://brew.sh. It asks for their Mac password, so they run it themselves in the Terminal app. Walk them through it if needed: open Terminal (Spotlight → "Terminal"), paste the command from brew.sh, press Return, type their Mac password (nothing shows while typing; that's normal), and press Return when prompted. At the end, Homebrew prints two or three "Next steps" commands to add it to the PATH: they paste and run those too.
3. Install ffmpeg: `brew install ffmpeg`. You can run this one for them once Homebrew works.

## Steps Claude runs

Run each check; act only if it fails.

| # | Check | If it fails |
| --- | --- | --- |
| 1 | `uname -m` prints `arm64` | Stop. These skills need a Mac with Apple Silicon (M1 or later): transcription, rendering and QA all use Apple-only libraries. |
| 2 | `brew --version` | Back to "What the person does first", step 2. If Homebrew is installed but not found, run `eval "$(/opt/homebrew/bin/brew shellenv)"` and ask them to run the "Next steps" lines again. |
| 3 | `ffmpeg -version` | `brew install ffmpeg` |
| 4 | `xcode-select -p` (Apple's command-line tools; `video-qa` needs them to build its text-reading helper) | Normally already there: the Homebrew installer installs them. If the check fails anyway, run `xcode-select --install`; a system dialog opens, and the person clicks Install and waits for it to finish. |
| 5 | A compatible Python: `/opt/homebrew/bin/python3.13 --version` (3.10 to 3.14 all work) | `brew install python@3.13`. **Don't use plain `python3`:** Homebrew's default is now 3.15, and mlx-whisper's dependencies (torch) don't support 3.15 yet. That's the cause of "requirements are unsatisfiable … cp315" and "externally-managed-environment" errors. |
| 6 | `pipx --version` | `brew install pipx && pipx ensurepath` |
| 7 | `~/.local/bin/mlx_whisper --help` | `pipx install --python /opt/homebrew/bin/python3.13 mlx-whisper`. Never `pip3 install` into Homebrew's Python. |
| 8 | Skills installed **and up to date** with this folder's `skills/`. Checking that they exist isn't enough: people who tried an earlier version of these skills may have old copies that are missing fixes. | Follow "Step 8 in detail" below. |
| 9 | Projects folder: `ls -d ~/"Video Edits"` | `mkdir -p ~/"Video Edits"` |
| 10 | Review-app launcher: `ls ~/"Video Edits"/.claude/launch.json` | Write `~/Video Edits/.claude/launch.json` with the contents below. It lets Claude open the review app in the desktop app's browser panel when a session is opened on `~/Video Edits`. If the file already exists with other configurations, add this one to its `configurations` list instead of replacing it. |
| 11 | Google Drive for desktop, for delivering cuts to shared folders: `ls -d ~/Library/CloudStorage/GoogleDrive-*` lists a folder for their work account, and it contains `My Drive` (and `Shared drives` if their team uses them). | Optional: skip it if they won't deliver to Drive, and say so. Otherwise they install it from https://www.google.com/drive/download/, open it and sign in with their work Google account. Leave its default "stream files" setting: files download only when opened, so a large shared drive doesn't fill the Mac. The first time Claude reads or writes a Drive folder, macOS may ask them to allow access; they click Allow. |

### Step 8 in detail: install or update the skills

`<repo>` below is this folder (the one holding `SETUP.md`). The skills are `ve-video-edit-general`, `apply-notes` and `video-qa`.

**a. Move stray backups out of the skills folder.** Claude loads every folder in `~/.claude/skills` that has a `SKILL.md`, so a backup kept there (e.g. `ve-video-edit-general.bak-2026-10-01`, from older instructions) loads as a duplicate copy of the old skill. Move any such folder into `~/.claude/skills-backups/`.

**b. Compare.** For each skill:

```bash
diff -rq "<repo>/skills/<skill>" ~/.claude/skills/<skill> -x __pycache__ -x .DS_Store -x textscan -x video-editing-standards.md -x brand-house-style.md
```

`textscan` and `__pycache__` are built on the Mac when the skills run, so they're ignored. The two reference files are compared separately in step d, because they're supposed to differ once the person has used the skills.

- No output for any of the three skills: the code is current. Go to step d.
- A skill folder is missing: copy it in (`mkdir -p ~/.claude/skills && cp -R "<repo>/skills/<skill>" ~/.claude/skills/`).
- Any other difference: the installed copy is an older or modified version. Do step c.

**c. Back up, then replace.** Tell the person in one sentence that an older version of the video-editing skills was found and you're replacing it with the current one, keeping a backup. Then, for the three skills together (replace all three even if only one differs, since they're built to work as a set):

```bash
B=~/.claude/skills-backups/$(date +%Y-%m-%d-%H%M) && mkdir -p "$B" && for s in ve-video-edit-general apply-notes video-qa; do [ -d ~/.claude/skills/$s ] && mv ~/.claude/skills/$s "$B/"; cp -R "<repo>/skills/$s" ~/.claude/skills/; done && echo "$B"
```

Re-run the comparison in step b; it should print nothing. Then do step d against the backup in `$B`.

**d. Merge the two learned files.** `ve-video-edit-general/references/video-editing-standards.md` (the editing rulebook) and `ve-video-edit-general/references/brand-house-style.md` (brand spellings) grow as the person uses the review app: "Apply notes" adds general rules from review notes to the rulebook, with a dated entry in its section 12 revision log, and adds corrected brand names to the brand table. Never let an update throw those away. Compare the person's copy (the backup from step c, or the installed copy if nothing was replaced) with `<repo>`'s:

- Identical: nothing to do.
- Rulebook: keep the repo's version, then carry over everything the person's copy has that the repo's doesn't. That means revision-log entries and the rule changes those entries describe. Text that only differs because it's an older wording of the original rules takes the repo's version.
- Brand table: keep every row from both. Where both have a row for the same brand, merge the spellings.
- If you can't tell whether a difference is something they learned or just old text, show the person the two versions in plain words and ask.
- Write the merged files into `~/.claude/skills/ve-video-edit-general/references/`. Tell the person what you carried over, in a sentence (e.g. "kept your 3 house rules and 2 brand spellings").

**e. Record where the skills came from:** `echo "<repo>" > ~/.claude/skills/.video-editing-source` (the absolute path of this folder). The skills' update check reads it to see whether GitHub has a newer version; nobody needs a GitHub account for that, because the repository is public. If this folder isn't a `git clone` (e.g. it was downloaded as a zip), say that automatic update checks won't work and suggest cloning it instead.

**f. New sessions only.** Sessions that were already open keep the skills they started with. Include this in the hand-off.

Re-run step 8 whenever this folder's skills are updated: it's also how the person gets new versions without losing their learned rules.

Contents for step 10 (it uses `$HOME`, so it works unchanged on any Mac):

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "review-app",
      "runtimeExecutable": "/bin/sh",
      "runtimeArgs": ["-c", "exec python3 \"$HOME/.claude/skills/apply-notes/scripts/review_server.py\" --port 8765"],
      "port": 8765
    }
  ]
}
```

## Test it

1. Transcription (this also downloads the speech model, about 1.5 GB, once; warn them it takes a few minutes):
   ```bash
   T=$(mktemp -d) && say -o "$T/t.aiff" "Testing one two three" && ffmpeg -loglevel error -i "$T/t.aiff" "$T/t.wav" && ~/.local/bin/mlx_whisper "$T/t.wav" --model mlx-community/whisper-large-v3-turbo --language en --output-dir "$T" && cat "$T/t.txt"
   ```
   It should print "Testing 1 2 3" (or similar).
2. Project tools: `bash ~/.claude/skills/ve-video-edit-general/scripts/setup.sh "$(mktemp -d)"`. It should end by printing a Python version (3.10 to 3.14), an ffmpeg version and a font list.

## Hand-off to the person

Tell them, in plain words:
- Setup is done. **Start a new session** so Claude picks up the new skills (skills load when a session starts). Open it on the **Video Edits** folder in their home folder: that's where their edits live and where the review app opens from.
- To edit: open a new session and say *"Edit this ad. Brief: <Google Doc link or pasted text>. Footage: <Drive folder link or a folder on this Mac>."*
- Footage on Google Drive: with Google Drive for desktop (step 11), they can give Claude the Drive folder's link, private team folders included. Without it, Claude can only download files shared as "anyone with the link"; otherwise they download the folder to their Mac first and give Claude that folder.
- To share a finished cut with the team, they ask Claude to put it on Drive in any words ("upload SCB01 to the drive"). The first time, Claude asks for the link of the Drive folder to use, and it asks again when they move on to a different client.
- Claude checks for updates to the video-editing skills once a day and asks before installing one.
- To review a cut, ask Claude to "open the review app". In a session on `~/Video Edits`, Claude starts the `review-app` configuration from step 10 and the app opens in the browser panel beside the chat. In any other folder, Claude runs `python3 ~/.claude/skills/apply-notes/scripts/review_server.py` as a background command and they open http://localhost:8765 in their browser. Either way the app stops when that session ends; asking again restarts it. Only one copy can run at a time, so if port 8765 is busy, check whether the app is already open before starting another.
