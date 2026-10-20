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
| 8 | Skills installed: `ls ~/.claude/skills/ve-video-edit-general/SKILL.md ~/.claude/skills/apply-notes/SKILL.md ~/.claude/skills/video-qa/SKILL.md` | `mkdir -p ~/.claude/skills && cp -R <this folder>/skills/* ~/.claude/skills/`. If they already exist, ask before replacing them: the installed `video-editing-standards.md` may hold rules learned from their review notes. Back up the old folders first (`mv ~/.claude/skills/<name> ~/.claude/skills/<name>.bak-<date>`). |
| 9 | Projects folder: `ls -d ~/"Video Edits"` | `mkdir -p ~/"Video Edits"` |
| 10 | Review-app launcher: `ls ~/"Video Edits"/.claude/launch.json` | Write `~/Video Edits/.claude/launch.json` with the contents below. It lets Claude open the review app in the desktop app's browser panel when a session is opened on `~/Video Edits`. If the file already exists with other configurations, add this one to its `configurations` list instead of replacing it. |

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
- Footage from Drive downloads directly only when the files are shared as "anyone with the link". Otherwise, they should download the folder to their Mac first (or use Google Drive for desktop) and give Claude that folder.
- To review a cut, ask Claude to "open the review app". In a session on `~/Video Edits`, Claude starts the `review-app` configuration from step 10 and the app opens in the browser panel beside the chat. In any other folder, Claude runs `python3 ~/.claude/skills/apply-notes/scripts/review_server.py` as a background command and they open http://localhost:8765 in their browser. Either way the app stops when that session ends; asking again restarts it. Only one copy can run at a time, so if port 8765 is busy, check whether the app is already open before starting another.
