---
name: video-qa
description: Check finished video ads against the video editing standards before a person reviews them. A script pass reads the rendered MP4 (on-screen text with positions, final-audio transcript, cuts, loudness) and an eye pass looks at frame sheets; findings go into the review app as notes from "QA". Runs automatically as the last step of /ve-video-edit-general, /apply-notes and any style skills; also use when the user says "QA this ad", "check these cuts", "run QA on ACM08", "anything wrong with this edit", or wants an existing or human-edited ad checked.
---

# Video QA

A second pair of eyes on every render, so the reviewer's time goes on taste, not on mistakes a machine can catch. It never edits anything; it reports. Fixes happen in the editing skill or through `/apply-notes`.

The rulebook it checks against: `video-editing-standards.md` in the `ve-video-edit-general` skill's `references/` folder. Brand names and spelling market: `brand-house-style.md` beside it. Rule numbers in findings point at the rulebook.

`$QA` = this skill's folder (e.g. `~/.claude/skills/video-qa`). `$AN` = the apply-notes skill beside it (`$QA/../apply-notes`). Needs macOS (Apple Vision OCR), `ffmpeg`/`ffprobe` on PATH and `mlx_whisper`.

## When it runs

- **Automatically** at the end of `/ve-video-edit-general`, `/apply-notes` and any style skill, on every export of that round, before telling the user it's ready.
- **On request** for any MP4: an old edit, a human editor's cut, a downloaded ad.

## 1. Script pass

Pass all hook variations of one version together, so the cross-variation checks run:

```bash
python3 $QA/scripts/qa_check.py <dir>/Exports/ACM08_HookA_v2.mp4 <dir>/Exports/ACM08_HookB_v2.mp4 ... --post
```

Options: `--style default|ugly-organic|produced` (otherwise read from the plan; `captions: false` + `jump_zoom: false` means ugly-organic), `--brand <name or code>` (otherwise taken from the folder code, e.g. ACM08 → the `ACM` row in `brand-house-style.md`), `--four-five` when a 4:5 version will be delivered, `--plan` / `--ass` when the sidecars aren't next to the MP4, `--no-sheet` to skip the frame sheets.

**Sidecars make it exact.** If `<stem>.captions.ass` and `<stem>.plan.json` sit next to the MP4 (`/ve-video-edit-general` saves them, see its step 7), captions are checked from the caption file: exact words, a dictionary spell-check, and safe-zone failures are hard fails. Without them, captions are read from the frames with Apple Vision OCR (`scripts/textscan`, built from `textscan.swift` on first run). OCR findings are warnings: look at the frame before acting on one.

It takes about 30–40s per minute of video the first time; the transcript and text scan are cached in `<dir>/.qa/<stem>/` and reused until the MP4 changes.

**What it checks** (rule numbers from the rulebook):

| Area | Checks |
| --- | --- |
| Hook (3) | a text overlay in the first second; no captions under it; no more than one text element on screen; no "hey guys" in the first 3s |
| Voice track (4, 5) | late first word; pauses over the style's limit (0.30s default, 1.6s ugly-organic; one ≤0.45s beat before the close is allowed); filler at sentence starts ("basically", "like", "okay", "well", "yeah"; never "and"/"so"/"but"/"then") and "hey everyone"-type phrases; doubled words; a 4-word phrase said twice; run-on past the last word (end card or dead footage) |
| Captions (7) | caption words that aren't in the audio (ghost words, typos); doubled caption words; ALL CAPS when sentence case is the default; emoji; spelling (with a caption file); captions present in a no-captions style; captions missing |
| On-screen text (7, 8) | brand and product names in house form; US/UK spelling for the brand's market; number style (digits with units, $, 2-in-1, money-back, drugstore); every caption, overlay and end-card line inside x 65–1015, y 270–1248 (and the 4:5 crop with `--four-five`) |
| Picture (5.7, 11.4) | shots under 0.3s (flash cuts); black frames; 1080x1920 at 30fps; length over 60s for styles with a target |
| Audio (9) | integrated loudness (about -16 LUFS), true peak under -1 dBTP, voice in one ear |
| Variations (9, 11.2) | loudness differs across hooks by more than 1.5 LU; the body differs between hooks (a fix applied to one variation only) |

`--post` adds each finding to `<CODE>/review-notes.json` as an open note from "QA", tagged `[FAIL · rule 3.2]` or `[WARN · rule 7.4]`, at its timestamp. It never posts the same finding twice, so a finding the reviewer dismissed stays dismissed. Exit code 1 = at least one FAIL.

## 2. Eye pass

The script writes two images per video into `<dir>/.qa/<stem>/`: `hook.jpg` (the first 3s every 0.5s) and `sheet.jpg` (the middle of every shot plus every flagged moment, timestamped). Read both, plus the brief, and check the rules no script can:

1. **Hook overlay (3.3, 3.5):** plain and specific, readable at a glance, says something the voice doesn't (premise, category, tension, POV); understood muted.
2. **B-roll (6.1–6.5):** each insert literally shows what's being said; best clip available (not dark, blurry, crooked or dull); no mirrored text; clean background and edges; the person matches the script's persona, and it's the same creator on "I" lines.
3. **Competitor branding (11.3):** logos, labels, shop signs, clothing.
4. **Text (8.2, 8.3, 8.5, 7.7):** legible on busy footage; lists complete and consistent; numbers on screen match the voice and the brief; caption colour consistent.
5. **Style (2):** organic stayed organic (no music, end card, transitions, SFX, stock), nothing produced mixed in; or, for a style skill, its own rules (the skill lists the sections it overrides). Where the client's creative context requires something produced (e.g. a template end card), that isn't a finding.
6. **Client creative context:** if the project has `<CODE>/client-creative.md`, check the on-screen text and footage against each rule in it: wording and claims, product and shade names, required copy, amount and style of text, footage preferences. Cite the rule ("client context: launch ads say NEW, not 'just launched'") instead of a rulebook number. Skip rules the file marks as overridden by the person or left for the Premiere finish.
7. **OCR findings:** open the frame for any `caption mismatch` or `safe zone` warning from OCR and confirm it before keeping it.

Post what you find with the apply-notes helper, one note per issue, at the timestamp from the sheet:

```bash
python3 $AN/scripts/notes.py add <CODE> <file relative to the project> <seconds> "[WARN · rule 6.3] mirrored text on the box at 0:12" --author QA
```

Dismiss your own false alarms rather than leaving them for the reviewer: `notes.py reply <CODE> <id> "OCR misread, caption is correct"` marks it done.

## 3. Report

In chat, keep it to: the files checked, fails and warnings per file, the three most important findings, and a pointer to the review app. If anything FAILS on a fresh render, the editing skill fixes it and re-renders before handing over; don't hand over a cut with a known fail unless the fix needs the user's decision.

## Style profiles

| Style | Captions | Pause limit | Filler / repetition checks | Length / tail |
| --- | --- | --- | --- | --- |
| `default` (organic, `/ve-video-edit-general`) | required, hidden under the hook | 0.30s | on | ≤60s, ≤1.2s after the last word |
| `ugly-organic` | must be absent | 1.6s | off (the mess is the style) | no target, ≤1.2s tail |
| `produced` | required | 0.30s | on | ≤60s, end card up to 6s |

A new style skill that overrides the rulebook (rule 2.3) should get a profile here and in `PROFILES` in `scripts/qa_check.py`.

## Limits

- OCR misses captions shorter than a quarter-second and can misread highlighted words; it's triage, the frames are the evidence.
- It can't tell text in the footage (a label, a sign) from a graphic with certainty. It only checks the caption line, held overlays and wide crisp text for the safe zone; a product label crossing the edge is not flagged.
- The transcript can mishear ("vet" as "bet"). Single-word differences are ignored in the variation check for that reason.
