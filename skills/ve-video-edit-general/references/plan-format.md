# plan.json format

One file drives the whole edit. `build_vo.py` reads `lines`, `validate_plan.py` checks `shots`, and `render.py` renders everything.

```jsonc
{
  "output": "Brand_ConceptCode_Name_v1.mp4",
  "speed": 1.08,                 // VO pace lift (atempo, pitch preserved). 1.0–1.12
  "tail": 0.55,                  // seconds held after the last word
  "accent": "#FF3355",           // caption active-word colour (brand colour)
  "font": "Montserrat Black", "font_alt": "Montserrat ExtraBold",
  "fix_words": {"acme sleep": "AcmeSleep"},   // spelling fixes applied to caption words
  "captions": true,
  // pacing (defaults shown): gap_max 0.20, gap_keep 0.10, line_gap 0.05; min_shot 0.30 = shortest picture piece allowed
  // "edge_floor": 0.012 (default) = loudness floor for finding where speech starts/ends; lower it for quiet takes (see field notes)

  // One entry per script line, in script order. These are the ONLY places a cut can happen.
  "lines": [
    {"id": "L1", "text": "Okay, if you're thinking about red light therapy for your hair and your skin, this makes so much sense.",
     "take": "vo_125421", "start": 9.38, "end": 14.48}
    // take = file name (no extension) of the chosen take; start/end = first word start / last word end in that take (from tx/*.json)
    ,{"id": "L10", "text": "So now we get to skip the $400 repair bill.", "take": "body2", "start": 27.34, "end": 31.54,
     "drop": [[28.17, 28.66]]}
    // drop = stumbles to cut out of the take, in source seconds (here the repeated "now we"). Set them from a 10ms
    // energy read at real silences, not from whisper times. Caption words for a line with drops come from "text".
    ,{"id": "L11", "text": "I was hacking even my own formulas.", "take": "body3", "start": 28.46, "end": 33.74,
     "end_pad": 0.12}
    // end_pad = extra seconds kept after the detected end of the line, for a soft last sound (a trailing "s") that got clipped
  ],

  // Shots cover the lines in order; each shot = one or more WHOLE consecutive lines.
  "shots": [
    {"lines": ["L1"], "type": "broll", "clip": "IMG_2189", "in": 0.0, "push": true,
     "illustrates": "red light therapy for your hair and your skin",
     "shows": "creator holding the device box up to camera"},
    {"lines": ["L2", "L3"], "type": "aroll"},                    // picture synced from each line's own take
    {"lines": ["L4"], "type": "aroll", "zoom": 1.1},             // optional fixed punch-in; jump_zoom (default true) alternates 1.08 on pause-trim jump cuts
    {"lines": ["L9"], "type": "still", "clip": "IMG_2194",       // photo with slow push
     "illustrates": "...", "shows": "..."}
  ],

  // Text overlays. These are not cuts, so they may start/end on words inside a line.
  "callouts": [
    {"lines": ["L1"], "text": "Red light for my hair + skin\n...while I watch TV", "style": "box"},
    {"lines": ["L5"], "text": "12 MIN / DAY", "style": "big", "at_word": "12", "until_word": "500"},
    {"lines": ["L5"], "text": "500 LASERS\n+ LEDs", "style": "big", "at_word": "500", "pos": [540, 800]},
    {"lines": ["L7"], "text": "INFRARED", "style": "big", "at_word": "infrared", "color": "#C0101A", "pos": [540, 460]}
  ]
}
```

## Field notes
- **Shot `type` values**
  - `aroll`: the creator on camera. Picture follows each line's take in sync, including its pause trims.
  - `broll`: a video clip at natural speed, starting at `in`, for the full length of the lines it covers. Check that the clip has that much usable footage after `in`; the validator checks the clip length but not whether the footage is still usable.
  - `still`: an image with a slow push-in.
- **`illustrates`** must be a verbatim substring of the covered lines' text. Pick the words the footage proves, e.g. "watch TV", "put it on", "red light, infrared light and blue light". If you can't find such words, the b-roll isn't relevant: use A-roll.
- **`shows`** describes what is visible from `in` to `in + duration`. Write it from the strips, not from the file name.
- **`push: true`** adds a slow 7% push-in. Use it on b-roll held longer than about 4s.
- **Callout `style`**
  - `box`: white box with dark text, top of frame. Use for hooks, offers and guarantees.
  - `big`: large white outlined text, top by default. Use for short feature callouts.
- **Callout `pos`** is `[x, y]` of the top-centre of the text. Use `[540, 800]` for mid-frame when the top would cover a face or the product. Captions occupy about y 1140–1220. Keep `y` between 270 and 1150, so the text stays inside the safe zone (x 65–1015, y 270–1248). Break callout lines longer than about 26 characters with `\n`.
- **Callout claims** must come from the brief.
- **`"hook": true`** marks the hook text overlay. Every plan needs one covering the first line (`validate_plan.py` R5). It says what the voice isn't saying (premise, category, tension, POV), and captions stay hidden until it leaves. Keep it on screen only for the hook, unless it's a POV/premise headline meant to run longer: say which in the hand-off.
- **`caption_case`**: `"sentence"` (default) capitalises sentence starts and lowercases a line that continues a sentence after a cut; `"lower"` for all-lowercase organic; `"upper"` for the old ALL CAPS look. Words in `fix_words` values, "I", and words with internal capitals (AcmeSleep, iPhone) are never re-cased. A proper noun that starts a line mid-sentence would be lowercased, so add it to `fix_words`.
- **Clipped line edges (`edge_floor`, `end_pad`).** `build_vo.py` ignores the exact `end` you write: it finds where the speech really stops by reading the audio's loudness, and cuts there. On quietly recorded takes (a clip-on mic, low gain) the soft end of a word sits below the loudness floor and gets cut, so the re-transcription shows a missing or changed last word ("traveling" heard as "trapped", "formulas" as "formula"). Fix it in this order:
  1. Set `"edge_floor": 0.006` at the top of the plan (about −44 dB instead of −38 dB). This fixes every line of a quiet shoot at once. Check the `LOOSE PAUSES` list afterwards, since a lower floor can also keep a little more silence at line edges.
  2. If one line is still clipped, add `"end_pad": 0.08`–`0.15` to that line.
  3. Moving `end` later only helps if the transcript's word timing was wrong; it doesn't override the loudness read.
- **`fix_words`**: load the brand's row from `brand-house-style.md` in this folder (house names, URLs) before rendering.
