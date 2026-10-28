---
name: ve-video-edit-general
description: Edit raw footage into a finished vertical ad (UGC / creator / b-roll + voiceover) from a script or concept brief — pick the best take of every line, tighten the VO, cut A-roll and relevant b-roll strictly on line boundaries, burn captions and callouts, and export a Meta/TikTok-ready 9:16 MP4. Use whenever the user shares raw files (Google Drive folder, local folder, Frame.io) plus a script/brief (Notion page, doc, pasted text) and asks for an edit, a cut, a video ad, a re-cut, a v2, a cutdown or hook variants — even if the request is just "put this together" or "edit this concept". Also use it when the user asks whether the video-editing skills are up to date or to check for or install an update to them ("check for updates", "update the video editing skills").
---

# VE Video Edit (General)

Turn raw takes + a script into a finished ad. The output is a 1080×1920 MP4 with the VO assembled from the best takes, picture cut from the 4K originals, word-highlight captions and on-screen callouts.

## Read the rulebook first

Before planning any edit, read `references/video-editing-standards.md` in full. It is the one source of truth for pacing, cuts, footage, captions, on-screen text, audio, end cards and variations; this skill doesn't repeat it. Rules tagged `cut` are yours to apply while editing. Then load the brand's row from `references/brand-house-style.md` into the plan's `fix_words` (add a row if the brand isn't there yet).

The defaults that matter most:
- **Organic by default:** no music, no end card, no transitions or sound effects, no stock, lowercase on-screen copy. Produced elements only when the brief asks, and never mixed with organic ones.
- **Every video gets a hook text overlay** that isn't the captions (`"hook": true` callout on the first line; `validate_plan.py` R5 refuses a plan without one). Captions are hidden while it's on screen and start when it leaves; `render.py` does this.
- **Captions in sentence case** (`caption_case`, default `"sentence"`), not ALL CAPS.
- **No b-roll shot held over about 4s** (`validate_plan.py` warns).
- **Cut filler, repetition and the creator's warm-up;** scan the whole take for the strongest 3–4 seconds when building hooks.

## The two editing rules (non-negotiable)

These come from reviewing past edits. Both are enforced mechanically by `scripts/validate_plan.py`, and `render.py` refuses to run while the plan breaks them.

**1. Only cut on line boundaries.** A "line" is one line or row of the script as written. Every shot, whether A-roll or b-roll, starts at the start of a line and ends at the end of a line. Never cut into b-roll mid-line, never cut from one b-roll to another mid-line, and never cut back to A-roll mid-line. A shot may span several consecutive lines. Why: mid-line cuts chop the sentence the viewer is listening to and make the ad feel stitched together.
- Allowed inside a line: the jump cuts that remove pauses within a single A-roll take (the render alternates a slight punch-in to hide them), and a slow push-in on a b-roll shot (`"push": true`). Neither switches to a different source.
- If a line is long and one shot will feel static, use a push-in, or stay on A-roll. Don't split the line. If a script line really should be two shots, flag it to the user rather than cutting mid-line.

**2. B-roll must be relevant to the line it covers.** The footage has to literally show what the line is about: the product named, the action described, the setting mentioned. "Vibes" b-roll doesn't count.
- In the plan, each b-roll shot declares `illustrates` and `shows`:
  - `illustrates`: words copied verbatim from the line that the footage depicts. The validator checks they are really in the line, and rejects filler such as "so" or "honestly".
  - `shows`: what is actually on screen at that in-point. Write it only after looking at the frames.
- If no footage relevant to a line exists, stay on A-roll and list the gap in the hand-off. Don't reach for loosely related filler.
- Calibration (all three were wrong in a real edit):
  - Hair-brushing over "you actually have to stick with it": not relevant.
  - Phone scrolling over "read": not reading, so not relevant.
  - A different woman's lifestyle shot over "I": a weak match. Prefer the same creator when the VO says "I".

## Review rules

These come from reviewer notes on real edits. Rules 1, 3 and 4 have mechanical checks, but the checks only catch problems; you still have to fix them.

**1. Everything inside the safe zone.** Every caption and callout sits inside Meta's 9:16 safe zone. At 1080×1920 that is x 65–1015, y 270–1248: nothing in the top 14%, the bottom 35% or at the side edges.
- No text box spans the full width. Break any callout line longer than about 26 characters onto two lines.
- `render.py` renders the overlay layer alone and refuses to export if any text pixel falls outside the zone. `validate_plan.py` rejects a callout `pos` outside it.

**2. Remove every stumble.** Cut false starts, restarts, repeated words and half-words completely.
- Examples a reviewer flagged: "I stumbled upon… I stumbled upon", "There's no, nothing" → "There's nothing", and "So now we, now we get" → "So now we get".
- Fix inside a take by listing the stumble's source seconds in the line's `drop` (see `references/plan-format.md`). Set those seconds from a 10ms energy read, not from whisper; whisper mis-times restarts and merges repeated words.
- No line may end on the start of the next word ("the best part and—"). `build_vo.py` stops each line before the take's next word and starts it after the previous one. Still check every edge in the re-transcription.

**3. Tight pacing, no loose cuts.** Cut dead air between and inside lines.
- Aim for about 0.15s between sentences and about 0.1s for pauses inside a sentence. Keep breaths that carry emphasis so it doesn't sound rushed.
- Tightening must never clip the first or last word of a line.
- `build_vo.py` prints `LOOSE PAUSES` (anything ≥0.25s left in the VO). Fix each one before rendering: move the line's `start`/`end`, or add a `drop` for the silence.

**4. No glitch cuts.** Never cut from one clip to another and away again within a fraction of a second; no shot is on screen for less than about 0.3s.
- Pause-trims inside A-roll create slivers of a few frames, and the alternating punch-in makes them flash. `render.py` folds any piece shorter than `min_shot` (0.3s) into its neighbour.
- After rendering, it lists any remaining short shots under `CHECK FLASH CUTS`. Look at each one frame by frame; fast motion inside b-roll can also trigger it.

**5. End on the last spoken line.** No end card or text CTA unless the script or brief asks for one. Hold about half a second on the final shot after the last word.

**6. When the user cuts a line,** cut exactly what they asked and rebuild the edit around the gap. That includes removing any b-roll or callout that only existed for that line.
- In the hand-off, say if the cut takes away something that matters, such as a brief must-include claim or the payoff to the hook.

## Workflow

Work in the session scratchpad. Every script runs from the workdir, so start each Bash call with `cd "$W" &&` (Bash cwd resets between calls). `$SK` is this skill's folder (e.g. `~/.claude/skills/ve-video-edit-general`). `$AN` is the apply-notes skill beside it (`$SK/../apply-notes`). `$EDITS` is the review app's projects folder: `$REVIEW_ROOT`, default `~/Video Edits`.

### 0. Check for updates (chat sessions only)
Run `bash $SK/scripts/check_updates.sh`. It checks GitHub at most once a day and changes nothing.
- `UPDATE AVAILABLE`: tell the person in a sentence what's new (from the list it prints) and ask whether to update now. If yes: `git -C <the folder it names> pull --ff-only`, then SETUP.md step 8 from that folder (it backs up the old skills and keeps their learned rules). Carry on with this edit as it is; the update applies from their next new session, so say so.
- `INSTALLED COPY OUT OF DATE`: same, without the pull: SETUP.md step 8.
- `UP TO DATE`, `SKIPPED` or `CAN'T CHECK`: carry on without mentioning it. (For `CAN'T CHECK`, mention it once only if it says the source folder is missing.)
- In a headless run (started by the review app's buttons), skip this step.
- **When the person asks about updates themselves** ("check for updates", "are my video editing skills up to date?", "update the skills"), run it with `--now` so the once-a-day limit doesn't skip it, and report every result in plain words, `UP TO DATE` and `CAN'T CHECK` included. Handle `UPDATE AVAILABLE` as above. If they asked to update, they've already said yes, so don't ask again. That's the whole request: don't start an edit.

### 1. Gather inputs
- **Script/brief:** fetch it (e.g. a Notion page through the Notion MCP, a Google Doc, or pasted text). Split the script into lines exactly as written; those are your cut points. Note the filming notes, product claims and offer.
- **Footage list (Google Drive):** with a Google Drive MCP, search the folder (`parentId = '<folder id>'`), recursing into subfolders. Write `list.txt` with one line per file: `<subdir> <file_id> <name.ext>`. For a local folder, copy or symlink the files into `$W/raw/` instead and skip `fetch_drive.sh`.
- **Inspo (optional):** if you have access to the brand's ad account or an ad-library tool, look at its top video ads from the last 90 days: hooks, caption use and opening visuals.

### 2. Set up and fetch
```bash
bash $SK/scripts/setup.sh "$W"                 # venv: ffmpeg, mlx-whisper, PIL; fonts/
bash $SK/scripts/fetch_drive.sh "$W" list.txt  # parallel curl via drive.usercontent (gdown hits quota)
cd "$W" && ./venv/bin/python $SK/scripts/prep.py   # proxies, 16k wavs, contact sheets, clips.json
```

### 3. Transcribe the takes
```bash
cd "$W" && PATH=$PWD/venv/bin:$PATH ./venv/bin/python $SK/scripts/transcribe.py audio/<takes>*.wav --words
```
- For every script line, choose a take. Prefer, in this order:
  1. matches the script wording,
  2. clean delivery (no restarts, no long mid-word stretches; huge word durations in the timestamps mean a stumble),
  3. energy,
  4. what the creator is doing on camera, for A-roll lines (e.g. holding the product being named).
- Later takes are usually better, but check.

### 4. Review the footage — look before you place
- Read every contact sheet in `sheets/`. Catalogue each clip in a few words: who is in it, what happens, and when.
- Before committing an in-point, make fine strips for the candidate ranges:
```bash
cd "$W" && ./venv/bin/python $SK/scripts/strips.py qa/s1.jpg CLIP:start:end:step CLIP:start:end:step ...
```
- Note what the brief asked for but the footage doesn't have (e.g. "wearing both devices"). It goes in the hand-off.

### 5. Write `plan.json`
The format, with a worked example, is in `references/plan-format.md`.
- Start by deciding, line by line: A-roll or b-roll, and if b-roll, which clip proves the line. Then write the plan.
- Default to A-roll for the hook's payoff, personal claims, the "realisation" beat and the close. Use b-roll where the line names a product, feature, action or setting you have footage of.

### 6. Build the VO and validate
```bash
cd "$W" && PATH=$PWD/venv/bin:$PATH ./venv/bin/python $SK/scripts/build_vo.py
cd "$W" && ./venv/bin/python $SK/scripts/validate_plan.py
```
- `build_vo.py` assembles the takes, tightens pauses, applies the speed lift, then re-transcribes the result and diffs it against the script.
- Any missing or garbled word means a clipped edge or a muddy take: swap the take or adjust `start`/`end`. You can't listen, so this re-transcription is your ears.
- If the last word of a line keeps coming back changed or cut short ("traveling" → "trapped", "formulas" → "formula") however you set `end`, the take is recorded quietly and the loudness read is trimming the word's tail. Use `edge_floor` and then `end_pad` (field notes in `references/plan-format.md`). To confirm a single word, cut that stretch of the final audio and transcribe it alone.
- Repeated or extra words in the diff mean a stumble survived: add a `drop` (rule 2). Ambiguous spots (a transcriber mishearing a word only in context) are worth re-checking: cut that line's audio alone and transcribe it with an `initial_prompt` of fillers ("Um, uh, I- I, no, now we") so repeats show up.
- Clear every `LOOSE PAUSES` entry (rule 3).
- Fix every validator error. Read its shot table: for each b-roll row, ask whether a viewer who hears that line and sees that footage would think the edit matches.

### 7. Render and QA
```bash
cd "$W" && ./venv/bin/python $SK/scripts/render.py
```
Read `qa/final_sheet.jpg` and `qa/cuts.jpg`, which show the frames either side of every cut. Check:
- Picture changes only at the listed line boundaries.
- Each b-roll matches its line.
- No callout covers a face, the product or the captions. Callouts default to the top of the safe zone (y≈320); use `"pos": [540, 800]` for mid-frame. Captions sit around y≈1150–1220.
- `render.py` printed `safe zone: OK` (rule 1) and no unexplained `CHECK FLASH CUTS` (rule 4).
- Total length is reasonable for the script.

Fix and re-render as needed. Then deliver into the review app and run QA:
- Pick a short project code for the ad (e.g. `ACM08`): the client's prefix plus the next free number, checked against the folders already in `$EDITS` so two projects never share a code. If the person gives the project a name, use theirs (letters, numbers and hyphens: it becomes the folder name and the start of every file name). The delivery skill uses the leading letters to recognise the client, so keep one prefix per client. Copy each export to `$EDITS/<CODE>/Exports/<CODE>_Hook<X>_v<N>.mp4` (get the path from `python3 $AN/scripts/notes.py next <CODE> <X>`; never overwrite). Beside each, copy that render's `plan.json` as `<stem>.plan.json` and `captions.ass` as `<stem>.captions.ass`: `/video-qa` checks captions exactly when they're there.
- **Render variation A only** (`$EDITS/<CODE>/Exports/<CODE>_HookA_v1.mp4`, so the review app picks it up). Write the planned B, C and D hooks into the hand-off and `hooks-planned.md` in the project folder, but don't render them: they're built from the approved A cut by `/apply-notes` once the user approves A (standards 11.1).
- Run `/video-qa` on the hooks of this version with `--post` (just A at v1). Fix every FAIL and re-render before handing over; leave warnings for the user unless they're quick fixes.
- Hand off by pointing the user at the review app (`python3 $AN/scripts/review_server.py`, then http://localhost:8765), not by attaching files.

## Defaults
- **Pace:** `speed` 1.08. Pauses inside a line over 0.20s are tightened to 0.10s; lines are joined with 0.05s plus their edge pads, which comes to about 0.15s between sentences. Raise the speed if the brief asks for an upbeat delivery and the takes are slow; keep it ≤1.12.
- **Look and sound:** light grade (contrast 1.04, saturation 1.07). Audio is high-passed, lightly compressed and normalised to −14 LUFS.
- **Captions:** 1–3 word chunks, sentence case (`caption_case`), hidden under the hook overlay, active word in the brand accent colour. The renderer's font is still Montserrat Black; organic ads should use a platform-native font, so set `font` when one is installed in `fonts/`.
- **Callouts:** a hook overlay on the first line (`"hook": true`, required); feature callouts (numbers, claims straight from the brief); a concept title. Use only claims that appear in the brief. No end card or offer/guarantee card unless the script or brief asks for one (rule 5).
- **Music:** none unless the user supplies a track. Say so in the hand-off.

## Hand-off message
Keep it short. Include:
- the file;
- length and format;
- a one-line structure summary;
- footage gaps against the brief (shots asked for but not filmed, and lines kept on A-roll because nothing relevant existed);
- anything to check by ear;
- how long the hook overlay stays up and why (hook only, or the whole opener/video for a POV or premise headline);
- for revisions, a per-variation checklist confirming each requested change on A, B, C and so on;
- the planned B, C and D hooks (one line each), built once A is approved;
- offered next steps (cutdown, 4:5).

## Gotchas
- iPhone `.MOV` files are HEVC 4K with rotation metadata. ffmpeg auto-rotates, so plan in portrait.
- mlx-whisper shells out to `ffmpeg`, so prefix commands with `PATH=$PWD/venv/bin:$PATH`.
- zsh doesn't word-split `$var` in loops. Use the scripts or `bash -c`.
- The font cache warning (`Fontconfig error`) is harmless; libass reads `fonts/` via `fontsdir`.
- Whisper word start times run early after silence. `build_vo.py` re-detects onsets from audio energy, so trust its cut points over the raw timestamps.
