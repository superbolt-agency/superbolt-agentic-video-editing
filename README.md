# Agentic video editing

Claude Code skills for editing performance video ads (Meta, TikTok) without opening a timeline. Hand Claude a brief and a folder of raw footage. It cuts a finished 9:16 ad, checks its own work, and gets better every time you leave a review note.

These are the skills from the [AI video editing livestream](https://www.youtube.com/watch?v=GQey2B90__4). The full transcript, with a summary, is in [`transcript/`](transcript/2026-10-13-ai-video-editing-livestream.md).

Forked from Parker repo: https://github.com/real-simple-labs/agentic-video-editing

## What's in here

| Skill | What it does |
| --- | --- |
| [`ve-video-edit-general`](skills/ve-video-edit-general/SKILL.md) | Raw takes + a script or brief → a finished 1080×1920 ad. It picks the best take of each line, tightens the voiceover, cuts A-roll and relevant B-roll only on line boundaries, and burns in captions and a hook overlay. |
| [`apply-notes`](skills/apply-notes/SKILL.md) | A local review app (your own Frame.io). Leave notes at timestamps, press **Apply notes**, and Claude applies them in the background, renders the next version and replies on each note. |
| [`video-qa`](skills/video-qa/SKILL.md) | A QA pass on every render: on-screen text and safe zone, captions against the final audio, pauses, filler, flash cuts and loudness. Findings appear as notes in the review app. |
| [`video-editing-standards.md`](skills/ve-video-edit-general/references/video-editing-standards.md) | The one rulebook all three skills read: pacing, cuts, b-roll, captions, on-screen text, audio and variations. |

### How they fit together

```
brief + footage ──▶ /ve-video-edit-general ──▶ v1 ──▶ /video-qa ──▶ review app
                                                                      │  your notes
                          video-editing-standards.md ◀── general ── /apply-notes ──▶ v2 ──▶ /video-qa ──▶ …
                          (every skill reads it)          rules
```

When a note states a general rule ("don't cut people off before the end of a sentence"), `/apply-notes` writes it into `video-editing-standards.md`. Every skill reads that file, so the next edit starts from the corrected default. Notes that only apply to one ad stay out of the standards.

## Requirements

- **macOS 15+ on Apple Silicon.** Transcription uses `mlx-whisper`, rendering uses VideoToolbox, and QA uses Apple Vision OCR.
- [Claude Code](https://claude.com/claude-code), signed in. Opus 5.5 at medium effort works well.
- Python 3.9+
- Xcode Command Line Tools
- `ffmpeg`
- `mlx-whisper`
- Google Drive desktop app (https://support.google.com/a/users/answer/13022292?hl=en)

## Install

Get the Google Drive desktop app (https://support.google.com/a/users/answer/13022292?hl=en). Sign in with your account. You can skip the step where you need to sync your local folders, it's not necessary here.

Open your Terminal (Mac / Applications / Utilities / Terminal). Check if you have Homebrew installed by typing this command and pressing enter.
```bash
brew --version
```

If you don't have Homebrew installed, enter this command and go through the Homebrew installation process. It might ask you yes/no questions during installation.
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Next, install FFMPEG by entering this command in the Terminal.
```bash
brew install ffmpeg
```

Clone this repo into your Documents folder by entering this in your Terminal.
```bash
cd ~/Documents
mkdir claude-resources
cd claude-resources
git clone https://github.com/superbolt-agency/superbolt-agentic-video-editing.git
```

Start a new Claude Code session in the Claude desktop app. Choose the repo folder you just downloaded. It should be located on your computer at:

**Documents/claude-resources/superbolt-agentic-video-editing**

Say *"set up video editing"*. Claude follows [`SETUP.md`](SETUP.md): it checks every requirement, installs what's missing, installs the skills and tests transcription.

---

## Use it

Start a new Claude Code session in the desktop app and choose the **Video Edits** folder in your home folder (setup creates it). That's where your edits live, and it's where the review app can open right beside the chat.

1. **Edit.** Say *"Edit this ad. Brief: <Google Doc or Notion link, or pasted script>. Footage: <Google Drive folder link or a folder on your Mac>."* Private team Drive folders work through the Google Drive desktop app. To pick the project's name, add it (e.g. *"call it SCB02"*); use the same letters for every project of a client. `/ve-video-edit-general` cuts variation A, runs `/video-qa` and drops it into the review app.
2. **Review.** Say *"open the review app"*. Claude starts it in the browser panel beside the chat. In a session on another folder, it runs in the background instead: open http://localhost:8765 in your browser. If it isn't running when you come back, ask again. Watch the cut and leave notes at the playhead.
3. **Apply notes.** Click **Apply notes** in the app, or tell Claude *"apply notes on SCB02"*. It renders v2 and replies on each note.
4. **Approve and build variations.** Once A is approved, click **Build variations** to get hooks B, C and D cut from the approved A.
5. **Put it on Google Drive.** Say *"upload SCB02 to the drive"* (any wording works). The first time for a client, Claude asks for the link to the Drive folder to use (open the folder in Drive in your browser and copy the address bar). Each project goes in its own subfolder, named after the project unless you choose another name. Claude uploads the latest approved version of each hook, never overwrites anything already in Drive, and sends you links once Google has the files. Later projects for the same client go to the same folder; Claude asks before switching to a different client's folder. **The Google Drive desktop app must be open for this step**.

**Auto Updates.** Once a day, when you start an edit, a review or an upload, Claude checks this repository on GitHub for a newer version. If there is one, it tells you what changed and asks before updating. Updating keeps the house rules and brand spellings your reviews have added. New versions apply from your next new session.

Projects live in `~/Video Edits/<CODE>/` (set `REVIEW_ROOT` to change it). Finished cuts go in `Exports/<CODE>_Hook<X>_v<N>.mp4`, and stay there after they're uploaded.

## Make it yours

- **Edit `video-editing-standards.md`.** It's a starting point built from review notes on real ad edits. Change any rule your team disagrees with. Better still, have your best editor review 20 ads in the app and let the notes rewrite it.
- **Add your brands to `brand-house-style.md`** (same folder): exact brand, product and URL spellings, plus the US/UK market. Captions are corrected to it and QA checks against it.
- **Build style skills on top.** Give Claude three or four example ads in one edit style and ask for a skill that layers on `ve-video-edit-general`. Rule 2.3 of the standards says what a style skill may override.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `REVIEW_ROOT` | `~/Video Edits` | Projects folder the review app, `notes.py` and the skills use |
| `FFMPEG_DIR` | none | Extra folder to look in for `ffmpeg`/`ffprobe` |
| `MLX_WHISPER` | found on PATH | Path to the `mlx_whisper` command |
| `CLAUDE_BIN` | found on PATH | Path to the Claude Code CLI used by the Apply notes button |
| `APPLY_NOTES_CWD` | projects folder | Where headless runs start. Set it if you installed the skills in a project's `.claude/skills` rather than `~/.claude/skills`. |

The **Apply notes** button runs Claude Code headless with local file and shell tools allowed without asking (`--permission-mode acceptEdits`). Web tools and MCP connectors are blocked. Runs only touch the ad's project folder; you can stop them from the app.

## Limits

These skills are built for ads: 1080p phone footage cut to an ad of about a minute or less. Long-form or high-production edits haven't been tested. Expect to give a note or two on most v1s; that's what the review loop is for.

## License

MIT
