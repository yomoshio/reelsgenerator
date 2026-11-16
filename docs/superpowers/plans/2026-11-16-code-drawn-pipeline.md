# Code-Drawn Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the diffusion pipeline with a lean one. Local open models write the story, stage each beat and write the code that draws it. A JS runtime renders that code frame by frame on the CPU. Voice, captions, plates and sound are ours.

**Architecture:** A job is a folder. Stages run in order: write, voice, stage, render, assemble. Each stage reads the previous stage's files and writes its own. Models are reached through one OpenAI-compatible endpoint, which is ollama on a rented box behind an SSH tunnel. Scene code is a JS function `scene(s)` run in a Node `vm` sandbox against our stage API (rig, things, places, devices, camera, word cues). Every scene goes round a loop: write → run keyframes → layout checks → vision questions → rewrite, with a safe fallback scene at the end.

**Tech Stack:** Python 3.12 (pydantic, pydantic-settings, httpx, typer, structlog, Pillow), Node 24 + skia-canvas, ffmpeg, a speech service (Qwen3-TTS + faster-whisper, FastAPI), and ollama.

**Spec:** the conversation of 2026-11-14…16, recorded in memory `reelsmith-direction-nov14`. No separate design doc: the user asked for the pipeline instead of a document.

## Global Constraints

- No closed APIs. Every model runs on the user's own hardware or a rented box, reached at `REELSMITH_LLM_URL` and `REELSMITH_SPEECH_URL`.
- Output is 1080×1920 at 30 fps, H.264 yuv420p, AAC 48 kHz stereo, loudness −14 LUFS (`loudnorm=I=-14:TP=-1.5:LRA=11`).
- An episode runs 60–95 s and a beat 3.5–11 s. The pace is 5.6 syllables/s plus 0.5 s per beat (`PACE`, `BETWEEN` from `beats.py`).
- Our code draws every glyph on screen. Model code gets a canvas without `fillText`/`strokeText`.
- People are drawn only by our rig, from a character card. Model code poses and moves them.
- Model code runs in `node --permission` with no fs or network grants, inside `vm` with only `s` and `Math`. There is a 2 s CPU budget per keyframe call and 512 MB of heap.
- Frames go from Node to ffmpeg over a pipe. Frames are never written to disk.
- ruff (line 100), mypy and pytest stay green. `node --test runtime/test` stays green.
- The Russian operator docs in `docs/` and `README.md` are updated in the same task that changes behaviour. No narrating comments.
- Every phase is its own branch and PR, stacked on the previous one. Never merge without the user's approval, and never force-push.
- `install.cmd`, `install.ps1` and `run.cmd` stay and keep calling `run.sh` inside WSL.
- Never stage the user's own files: `studio/ideas/*` and local edits to `studio/series/twists.txt`. Always `git add` explicit paths.

## Review Focus

1. **Scene code that loops forever or eats memory.** Expected: the keyframe run is killed at its budget, the error goes back to the coder, and the job never stalls. Test in Task 3.6.
2. **A cue word the narrator said differently** («20» heard for «двадцать»). Expected: the cue resolves through the written word aligned to the heard time, and the plate appears on time. Test in Task 5.2.
3. **A story or book far longer than one episode.** Expected: it is split into several jobs, each one episode, never crammed. Test in Task 2.5.
4. **Box unreachable, model missing, or non-JSON reply.** Expected: the job keeps its status with `error` set, `run` moves on to the next job, and a retry resumes. Test in Task 1.4.
5. **Low local disk** (6 GB free today). Expected: render refuses to start below 2 GB free with a clear message, and assemble deletes the beat clips after `final.mp4` is checked. Test in Task 5.4.

---

## File structure after the rewrite

```
src/reelsmith/
  settings.py   Settings from .env
  jobs.py       Job, Status, Jobs (folder store), run loop over stages
  llm.py        Llm: json(), text(), code(); OpenAI-compatible
  styles.py     Style folder loader
  books.py      (kept) txt / fb2 / epub → text, split into episodes
  story.py      Outline, Episode, Beat, Card…; plan → edit → cut → direct; checks
  speech.py     Speech client: speak(), words(); align written words to heard ones
  voice.py      stage voice: beat audio + word timings
  runtime.py    Python side of the Node runtime: keys(), frames_cmd()
  scenes.py     stage stage: coder loop, vision questions, fallback
  captions.py   Word, Caption, captions(), to_ass() (from services/ffmpeg.py)
  render.py     stage render: beat clips in parallel, sound mix
  assemble.py   stage assemble: transitions, final card, loudness, reference gate
  library.py    things index: name, tags, file
  cli.py
  prompts/      planner.md editor.md cut.md director.md coder.md vision.md
runtime/
  package.json  {"type":"module","dependencies":{"skia-canvas":"…"}}
  src/run.mjs   CLI: keys | frames, JSON on stdin
  src/stage.mjs the `s` API and timeline
  src/rig.mjs   character card → figure; poses, walk, reach
  src/things.mjs fixtures + SVG things with palette recolour, footprints
  src/places.mjs place kinds: room, stairwell, section, street, shop, outdoors, custom
  src/devices.mjs section, lens, ripples, dashed, counter, route, split
  src/plates.mjs rule_card, hud, label, status, stamp, count, final card
  src/layout.mjs boxes, support, overlap, label placement, problems
  src/sandbox.mjs vm runner
  test/*.test.mjs
services/speech/ app.py (Qwen3-TTS /speak + faster-whisper /words), design_voice.py
styles/blackout/ style.toml, bed/, sfx/   (other styles removed)
library/things/ *.svg + index.json        (game-icons import, Task 7.1)
scripts/        autostop.py, box.sh, import_icons.py, make_sounds.py, vectorize.py
tools/reference_check.py (kept)
```

Removed: `app.py conveyor.py store.py pipeline.py models.py checks.py remix.py series.py report.py pricing.py studio.py beats.py graphics.py stage.py services/ migrations/ comfy_nodes/ workflows/ scripts/make_graphs.py scripts/make_art.py docker/comfy.Dockerfile docker/worker.Dockerfile`, every style but the new `blackout`, and the tests of removed code.

## Shared data (defined in Task 2.1, used everywhere)

```python
class Card(BaseModel):            # how the rig draws a person; enums are what rig.mjs implements
    age: Literal["child", "teen", "adult", "old"]
    build: Literal["slim", "average", "heavy"]
    skin: Literal["light", "medium", "dark"]
    hair: Literal["short", "long", "bun", "braids", "bald", "curly", "ponytail", "cap"]
    hair_colour: str              # "#rrggbb"
    face: list[Literal["beard", "mustache", "glasses", "freckles"]] = []
    top: Literal["shirt", "sweater", "jacket", "coat", "raincoat", "dress", "gown", "uniform", "apron"]
    top_colour: str
    bottom: Literal["trousers", "skirt", "long_skirt", "shorts"]
    bottom_colour: str
    shoes_colour: str
    hat: Literal["none", "cap", "top_hat", "bonnet", "kerchief"] = "none"
    extras: list[Literal["necklace", "scarf", "bag", "torch"]] = []

class Character(BaseModel): key: str; name: str; look: str; card: Card
class Place(BaseModel):     key: str; name: str; look: str; kind: Literal["room","stairwell","section","street","shop","outdoors","custom"]
class Reveal(BaseModel):    on_word: str; occurrence: int = 1; kind: Literal["rule_card","hud","label","status","stamp","count"]; text: str; target: str = ""; tone: Literal["neutral","threat","solved","key"] = "neutral"; persist: Literal["beat","episode"] = "beat"
class Staging(BaseModel):   shot: Literal["wide","medium","close","section","lens","split"]; action: str; devices: list[str]; things: list[str]; questions: list[str]
class Beat(BaseModel):      place: str; cast: list[str]; lines: list[str]; delivery: str; reveals: list[Reveal]; staging: Staging | None = None
class Episode(BaseModel):   title: str; part: int; premise: str; hook: str; places: list[Place]; characters: list[Character]; beats: list[Beat]; ending: str; cliffhanger: str = ""; music: str
```

The job folder `jobs/<id>/` holds:
- `job.json`, `source.txt`;
- `plan.json` (Outline) and `episode.json` (Episode);
- `voice/beatNN.wav` and `voice/words.json` (`{"NN": [{"text","start","end"}]}`);
- `scenes/beatNN.js` and `scenes/beatNN.json` (the Report of the last round);
- `keys/beatNN-K.png`, `clips/beatNN.mp4`;
- `final.mp4`, `check.json` and `notes.md`.

Runtime input (JSON on stdin of `runtime/src/run.mjs`):

```json
{"mode": "keys|frames", "code": "<js source>", "beat": {…Beat…}, "place": {…Place…},
 "characters": [{…Character…}], "palette": {…}, "fonts": {"plate": "/path.ttf"},
 "words": [{"text","start","end"}], "seconds": 7.3, "fps": 30,
 "keys": [0.4, 3.6, 7.0], "out": "/abs/keys/beat03", "library": "/abs/library/things",
 "carried": [{…Reveal…}]}
```

Report (stdout of `keys`): `{"ok": bool, "error": str|null, "problems": [str], "pngs": [path], "graph": [{"t": float, "items": [{"id","kind","box":[x,y,w,h],"on":str|null}]}]}`.

`frames` writes `seconds*fps` raw RGBA frames of 1080×1920 to stdout.

---

## Phase 0 — Safety (no PR)

### Task 0.1: Keep the old path and the WIP renderer
- [ ] `git tag shots-final 1bde7ff && git push origin shots-final`.
- [ ] `git switch -c wip/stage-skia` (from the current HEAD), `git add src/reelsmith/stage.py`, commit "Keep the skia stage renderer as it stood on 2026-11-14", push, switch back to `feat/qwen-voice`.
- [ ] Verify: `git show wip/stage-skia:src/reelsmith/stage.py | head -3` prints its docstring.

## Phase 1 — Lean core (branch `feat/lean-core` from `1bde7ff`, PR → main)

### Task 1.1: Remove the old path
**Files:** delete everything listed under "Removed", and keep `books.py`, `tools/`, the Windows scripts and `studio/`.
- [ ] Delete. Move `services/ffmpeg.py` `Word/Caption/captions/to_ass/_ass_time/_colour/_tag/_plain/_event/_caption_events/_plate_style` into `captions.py`, and drop the cards and segments code.
- [ ] Remove `psycopg` from `pyproject.toml` and add `[project.optional-dependencies] speech` only if the service needs it locally. It does not, because the service has its own Dockerfile.
- [ ] `ruff check`, `mypy src` and `pytest` (books tests only) pass.
- [ ] Commit "Remove the diffusion path, ComfyUI and the Postgres queue".

### Task 1.2: Settings and styles
**Files:** `settings.py`, `styles.py`, `styles/blackout/style.toml`, `.env.example`, `tests/test_settings.py`, `tests/test_styles.py`.
**Produces:**
- `Settings` (env prefix `REELSMITH_`) with these fields:
  - paths: `jobs: Path = "jobs"`, `styles: Path = "styles"`, `library: Path = "library/things"`, `outbox: Path = "outbox"`;
  - endpoints: `llm_url = "http://localhost:11434/v1"`, `speech_url = "http://localhost:8000"`;
  - models: `planner = "qwen3.5:27b"`, `editor = ""`, `director = "qwen3.5:27b"`, `coder = "qwen3-coder-next"`, `vision = "qwen3.5:27b"`;
  - limits: `language = "ru"`, `rewrites = 2`, `rounds = 4`, `workers = 0` (0 means cpu_count), `min_free_gb = 2.0`.
- `Style` (from `styles/<name>/style.toml`) with these fields:
  - `name`, `about`;
  - `story: StoryRules(seconds: tuple[int,int], beats: tuple[int,int], words: int, brief: str)`;
  - `director: str` (brief) and `palette: dict[str,str]`;
  - `fonts: Fonts(plate: str, caption: str)`, `captions: CaptionLook` (the fields `captions.py` needs), `plates: dict[str, PlateLook]`;
  - `voice: Voice(file: str, about: str)`, `music: str` (file in the style folder), `bed: str`.
- `Styles(folder).get(name) -> Style` and `.names()`.
- [ ] Tests: `test_blackout_loads` (palette has `wall`, `floor`, `ink`, `threat`, `key`, `solved`, and `story.seconds == (60, 95)`); `test_unknown_style_names_known_ones`; `test_settings_read_env` (monkeypatched env sets `coder`).
- [ ] Build `blackout` from `rules-beats.toml` (story brief) and `rules-serial.toml` (look, captions). Take the palette from `stage.py` constants. The plate font is Montserrat ExtraBold.
- [ ] Commit.

### Task 1.3: LLM client
**Files:** `llm.py`, `tests/test_llm.py`.
**Produces:**
- `Llm(url: str, *, timeout: float = 600)`.
- `async json[T: BaseModel](model, system, user, schema: type[T], images: Sequence[Path] = ()) -> T`: posts `/chat/completions` with `response_format={"type":"json_schema","json_schema":{"name":schema.__name__,"schema":schema.model_json_schema(),"strict":True}}`, sends images as `image_url` data URLs, and validates. On invalid JSON it retries once with the validation error appended.
- `async text(model, system, user) -> str`.
- `async code(model, system, user) -> str`: takes the last fenced block, `js`/`javascript` or bare, and raises `LlmError` if there is none.
- `LlmError(Exception)`.
- [ ] Tests with `httpx.MockTransport`: `test_json_validates`, `test_json_retries_once_with_error`, `test_code_takes_last_fence`, `test_code_without_fence_raises`, `test_images_sent_as_data_urls`.
- [ ] Commit.

### Task 1.4: Jobs and the run loop
**Files:** `jobs.py`, `cli.py`, `tests/test_jobs.py`.
**Produces:**
- `Status(StrEnum)`: `new, written, voiced, staged, rendered, assembled, approved, rejected, failed`.
- `Source(kind: Literal["idea","story","book"], text: str, title: str = "")`.
- `Entry(at, step, model, seconds, note)`.
- `Job(id, created, style, source: Source, status, error: str|None, tries: int, log: list[Entry], scores: dict[str,int], notes: str)`.
- `Jobs(root)` with `create(source, style) -> Job`, `get(id_prefix) -> Job`, `all() -> list[Job]`, `save(job)`, `folder(job) -> Path`.
- `Step = Callable[[Job, Path, Context], Awaitable[None]]`, `STEPS: list[tuple[Status, Status, str, Step]]`, filled by later phases.
- `async run_once(jobs, ctx, *, max_tries=3) -> int`: advances every job one step. An exception sets `error`, increments `tries` and leaves the status; after `max_tries` the job becomes `failed`.
- `Context(settings, llm, speech, styles, library)`.
- CLI: `add TEXT|--file PATH [--style]`, `run [--once]`, `jobs`, `show ID`, `approve ID` (copies `final.mp4` and `post.txt` to outbox), `reject ID --reason`, `retry ID [--status]`.
- [ ] Tests: `test_create_writes_folder_and_json`, `test_get_by_prefix`, `test_failing_step_keeps_status_and_records_error` (Review Focus 4), `test_third_failure_marks_failed`, `test_run_moves_on_to_next_job`.
- [ ] Docs: rewrite `README.md`, `docs/how-it-works.md` (stages, folder layout) and `docs/settings.md`; delete `docs/comfyui.md` and `docs/workflows.md`.
- [ ] Commit, push, open PR "Lean core: a job is a folder, models behind one endpoint".

## Phase 2 — Story (branch `feat/story` on `feat/lean-core`)

### Task 2.1: Story models and checks
**Files:** `story.py`, `tests/test_story.py`.
**Produces:**
- The shared data above.
- `Outline(title, premise, characters: list[OutlineCharacter(key,name,look)], places: list[Place], beats: list[str], planted, ending, narration)`.
- `problems(ep: Episode, style: Style, language: str, narration: str) -> list[str]`, which ports the checks from `beats.py`:
  - language, `on_word` said, lengths by `PACE`/`BETWEEN`, median, hook, rule numbering;
  - from `checks.py`: retold ≥ 0.95, unknown place, unknown cast key;
  - new: a reveal `target` is a cast key or a thing named in `staging.things`.
- `told_length(narration, style) -> str`.
- [ ] Tests: port the beats.py and checks.py tests that cover these. Add `test_reveal_target_must_exist` and `test_cast_key_must_exist`.
- [ ] Commit.

### Task 2.2: Plan and editor
**Files:** `prompts/planner.md` (from #46, plus a `card` per character), `prompts/editor.md`, `story.py`.
- `async plan(ctx, style, source) -> Outline` re-plans up to `rewrites+1` times while `told_length` complains. `async edit(ctx, outline) -> Outline` runs only when `settings.editor` is set: it fixes grammar and invented words in `narration` and `ending`, keeps every fact and the word count within ±5%, and falls back to the original if the count drifts.
- [ ] Tests with a fake Llm: `test_plan_replans_when_too_long`, `test_editor_skipped_when_unset`, `test_editor_result_rejected_when_length_drifts`.
- [ ] Commit.

### Task 2.3: Cut into beats, cast cards, direct
**Files:** `prompts/cut.md` (from `beats.md`, now cutting the narration word for word), `prompts/director.md`, `story.py`.
- `async cut(ctx, style, outline) -> Episode`: lines, reveals and cast per beat, and characters with `card`. Rewrites up to `rewrites` times on `problems`.
- `async direct(ctx, style, ep, catalog: str) -> Episode`: fills `staging` for every beat in one call with the whole episode visible, so places and things stay put. `catalog` is the device and thing list from the runtime (Task 3.7).
- [ ] Tests: `test_cut_rewrites_on_problems`, `test_direct_fills_every_beat`, `test_direct_things_persist_per_place` (a check: a thing named in a place in one beat appears in that place's later beats).
- [ ] Commit.

### Task 2.4: The write step
- `async write(job, folder, ctx)`: source → plan → edit → cut → direct. Writes `plan.json` and `episode.json` and sets status `written`. Registered in `STEPS`.
- [ ] Test: `test_write_step_produces_episode` with fakes.
- [ ] Commit.

### Task 2.5: Long sources become several jobs
- `add --file book.fb2` uses `books.py` to split into episodes, and each episode becomes a job with `Source(kind="book", title=f"{title}, часть {n}")`.
- [ ] Test: `test_long_story_split_into_jobs` (Review Focus 3). A 3000-word text gives at least 2 jobs, each under the episode word budget.
- [ ] Docs: `docs/stories.md` rewritten. Commit, push, PR.

## Phase 3 — Runtime (branch `feat/runtime` on `feat/story`)

### Task 3.1: Skeleton, sandbox and run.mjs
**Files:** `runtime/package.json`, `runtime/src/run.mjs`, `runtime/src/sandbox.mjs`, `runtime/src/stage.mjs` (minimal), `runtime/test/sandbox.test.mjs`.
- `run.mjs` reads stdin JSON, loads `code` via `sandbox.load(code) -> (s) => void` (`vm.runInNewContext` with `{Math}`, `timeout: 2000`), builds the stage, calls `scene(s)`, then renders keys or frames.
- Python starts it as `node --permission --allow-fs-read=<runtime>,<library>,<fonts> --allow-fs-write=<out> --max-old-space-size=512 runtime/src/run.mjs`.
- [ ] Tests: `infinite loop → error "scene took longer than 2 s"`, `require is not defined`, `ctx.fillText → error "text is drawn by plates"`, `syntax error → message with line`.
- [ ] Commit.

### Task 3.2: Rig
**Files:** `runtime/src/rig.mjs`, `runtime/test/rig.test.mjs`.
- Port `stage.py` (from `wip/stage-skia`): Bones, POSES, ease, `_alive`, walk, `reach`. Fix the hair cap drawn over the face: the back hair circle sits above the ear line and behind the head outline.
- `figure(card) -> Figure` implements every Card enum.
- `Figure.draw(ctx, {feet, size, facing, pose, t})` and `Figure.box(...) -> [x,y,w,h]`.
- `Figure.sit(seat)` puts the hips on a seat point and the feet on the floor.
- [ ] Tests: `every card enum draws without throwing`, `sit puts hip y within 4 px of the seat`, `box contains every joint`, plus a golden PNG per age at `test/golden/` (pixel diff ≤ 1%).
- [ ] Commit.

### Task 3.3: Places and things with footprints
**Files:** `runtime/src/places.mjs`, `runtime/src/things.mjs`, `runtime/test/things.test.mjs`.
- Place kinds draw a background from palette and light, and expose `floor(x)` (a support line) plus `surfaces` such as steps.
- Fixtures ported from `stage.py`: door, window, bed (with `seat`), bench, table, stairs, railing, wardrobe, water, section floors. New: counter, shelf, atm, chair, lamp.
- `thing(name)` looks for a fixture first, then `library/things/<name>.svg`, recoloured to the palette (every fill becomes the palette's `ink` shade by luminance).
- Each thing has a `footprint`, an `anchor("seat"|"top"|"screen"|…)` and `on`, the surface it stands on.
- [ ] Tests: `thing on floor has bottom at floor(x)`, `svg thing is recoloured`, `unknown thing → error naming close matches`.
- [ ] Commit.

### Task 3.4: Plates and label placement
**Files:** `runtime/src/plates.mjs`, `runtime/src/layout.mjs`, `runtime/test/plates.test.mjs`.
- Port `graphics.py` rule_card, hud, label, status and stamp. Add count, plus the final card for the end of the episode.
- `place(labels, obstacles) -> positions` tries 8 spots around the target in order and picks the first that does not overlap people, things, plates or the caption band (y > 1150), drawing a leader line.
- [ ] Tests: `label avoids a person box`, `two labels never overlap`, `nothing enters the caption band`.
- [ ] Commit.

### Task 3.5: Devices and camera
**Files:** `runtime/src/devices.mjs`, `runtime/src/stage.mjs`.
- `s.device("section"|"lens"|"ripples"|"dashed"|"counter"|"route"|"split", opts)`.
- `s.camera.push({to, at, zoom})` and `s.camera.pan({to, at})`, eased and subpixel.
- `lens` magnifies the live frame around its target.
- [ ] Tests: `lens is not empty over a thing` (pixel variance above a threshold), `camera push is monotonic and smooth` (frame-to-frame offset ≤ 2 px at 30 fps).
- [ ] Commit.

### Task 3.6: The stage API and problems
**Files:** `runtime/src/stage.mjs`, `runtime/test/stage.test.mjs`.
- `s.place(opts?)`.
- `s.thing(name, {x, on?, scale?})` returns a handle with `.part(name)`, `.stage(n, {at})` and `.move({to, at})`.
- `s.person(key, {x, facing?})` returns a handle with `.pose(name, {at})`, `.walk({to, from, at})`, `.sit(thing, {at})`, `.reach(target, {at})` and `.look(target)`.
- `s.at(word, n=1) -> seconds` and `s.draw(fn, {layer})`; `fn(ctx, t)` gets the sandboxed ctx.
- Reveals from the beat are drawn by plates. `carried` reveals are drawn from t=0.
- `problems()` checks every keyframe:
  - floating: a bottom more than 6 px above its support;
  - a person or thing outside the scene band;
  - a plate over a person;
  - an empty lens;
  - mean luminance outside 12..60;
  - an unknown cue word, with the beat's words listed;
  - a person in `beat.cast` who was never placed.
- [ ] Tests: `floating thing reported`, `unknown cue lists words`, `cast member missing reported`, `fallback scene passes` (Task 4.3 code), `memory hog killed` (Review Focus 1).
- [ ] Commit.

### Task 3.7: Python bridge and catalog
**Files:** `runtime.py`, `tests/test_runtime.py`.
- `async keys(input: dict, out: Path) -> Report`.
- `frames_cmd(input_path: Path) -> list[str]`.
- `catalog(library: Library) -> str`, listing devices, fixtures, place kinds, poses and library thing names for the director and coder prompts.
- `library.py`: `Library(root)` with `names() -> list[str]` and `find(name) -> Path | None`.
- [ ] Tests: `test_keys_returns_report_and_pngs` (real node), `test_frames_byte_count == seconds*fps*1080*1920*4`.
- [ ] Docs: new `docs/runtime.md` covering the scene API for people who read model code. Commit, push, PR.

## Phase 4 — Scenes (branch `feat/scenes` on `feat/runtime`)

### Task 4.1: Coder prompt and loop
**Files:** `prompts/coder.md`, `scenes.py`, `tests/test_scenes.py`.
- The prompt gives:
  - the API reference, generated from `runtime/src/stage.mjs` JSDoc by `catalog()`;
  - two worked examples from `styles/blackout/examples/*.js`;
  - the beat's lines, words with times, staging, place, cast cards and the things already standing in this place from earlier beats.
- `async stage_beat(ctx, ep, n, words, folder) -> SceneResult(code, report, rounds, fallback: bool)`:
  1. The coder writes code.
  2. `keys` runs at 3 times: 0.4 s, the middle, and the end − 0.3 s.
  3. On a runtime error or problems, the errors go back to the coder.
  4. Otherwise the vision step runs (Task 4.2), and any "no" answers go back.
  5. This repeats up to `settings.rounds` rounds. The result is the first clean round, or else the fallback.
- [ ] Tests with a fake Llm and real node: `test_error_goes_back_to_coder`, `test_clean_round_stops`, `test_fallback_after_rounds`.
- [ ] Commit.

### Task 4.2: Vision questions
**Files:** `prompts/vision.md`, `scenes.py`.
- `async look(ctx, pngs, beat) -> list[str]` asks `staging.questions` plus two fixed questions: "Is anything floating, cut off or overlapping wrongly?" and "Does the picture show what the lines say?". It returns the questions answered against.
- [ ] Test: `test_no_answer_becomes_problem`.
- [ ] Commit.

### Task 4.3: Fallback scene
- `fallback(beat, place, things_in_place) -> str` is JS that places the place, its things at even slots and the cast standing. It must pass `problems()` (pinned in Task 3.6).
- [ ] Test: `test_fallback_for_every_place_kind_passes`.
- [ ] Commit.

### Task 4.4: The stage step
- `async stage(job, folder, ctx)` runs over the beats in order and carries `things_in_place` forward. It writes `scenes/beatNN.js` and `.json` and sets status `staged`.
- CLI: `storyboard ID` (one key per beat on a sheet) and `redo ID --beat N --note "…"` (the note is added to the coder prompt).
- [ ] Test: `test_stage_step_writes_every_beat`.
- [ ] Docs, commit, push, PR.

## Phase 5 — Voice, render, assemble (branch `feat/voice-render` on `feat/scenes`)

### Task 5.1: Speech service
**Files:** `services/speech/app.py` (from `services/tts/qwen/app.py`), `services/speech/design_voice.py`, `docker/speech.Dockerfile`, `compose.yaml` (services `llm` and `speech` only).
- `/speak` as now. `/words` takes multipart audio plus `language` and returns `[{text,start,end}]` from faster-whisper large-v3 with word timestamps. `/health` and `/unload`.
- [ ] Test: `tests/test_speech_client.py` with MockTransport (the service itself is exercised on the box).
- [ ] Commit.

### Task 5.2: Voice step
**Files:** `speech.py`, `voice.py`, `tests/test_voice.py`.
- `Speech(url)` with `speak(text, voice, out)` and `words(audio, language) -> list[Word]`.
- `align(written: list[str], heard: list[Word]) -> list[Word]` ports `pipeline.as_written` and `render._heard`.
- `async voice(job, folder, ctx)`: one take per beat. It retakes up to 2 times when the heard words add words that are not in the lines, writes `voice/beatNN.wav` and `voice/words.json`, and sets status `voiced`.
- Order: voice runs before stage, because the cues need times. `STEPS` order is write → voice → stage → render → assemble.
- [ ] Tests: `test_align_number_heard_as_digits` (Review Focus 2), `test_retake_on_extra_words`.
- [ ] Commit.

### Task 5.3: Render step
**Files:** `render.py`, `tests/test_render.py`.
- `async render(job, folder, ctx)` renders beats in parallel, up to `workers` at once. Each beat runs `node … frames | ffmpeg` with the ASS captions and the mixed sound. The mix is ported from `render.mix_args`: voice, bed, sfx on reveals.
- [ ] Tests: `test_render_beat_duration_matches_voice` (±1 frame), `test_parallel_render_keeps_order`.
- [ ] Commit.

### Task 5.4: Assemble step
**Files:** `assemble.py`, `tests/test_assemble.py`.
- Clips are joined with `xfade=transition=pixelize:duration=0.25`, plus `acrossfade`. The final card comes from plates with the cliffhanger for 1.6 s. Music runs from the style under everything, then loudness.
- Then `tools/reference_check.py --json` runs into `check.json`, and status becomes `assembled`.
- The clips are deleted after a successful check.
- A free-space guard runs at the start of render and assemble.
- [ ] Tests: `test_assemble_length_is_sum_minus_overlaps`, `test_refuses_when_disk_low` (Review Focus 5), `test_clips_removed_after_check`.
- [ ] Docs, commit, push, PR.

## Phase 6 — Running it (branch `feat/box` on `feat/voice-render`)

### Task 6.1: run.sh, install.sh, box
**Files:** `run.sh`, `install.sh`, `scripts/box.sh`, `scripts/autostop.py`, `docs/setup.md`, `docs/daily.md`.
- `install.sh`: venv, `pip install -e .`, `npm ci` in `runtime/`, ffmpeg and font checks, and `.env` from the example. No Docker locally.
- `run.sh` passes commands through to `reelsmith`, plus `box up` / `box down` / `box tunnel` / `box status`:
  - `up` rents via the vast API (key read from `~/.config/vastai/vast_api_key`, never printed);
  - it installs docker, starts `llm` and `speech`, pulls the models in `.env` and starts autostop **before anything else**;
  - it opens the SSH tunnel to `localhost:11434` and `localhost:8000`.
- autostop keeps two rules: no request to llm or speech and GPU under 10% for `--idle-minutes`, or credit under one hour. Either one destroys the box.
- The Windows scripts keep working through WSL. Only the `up` message in `run.cmd` changes, because there is no ComfyUI.
- [ ] Tests: `tests/test_autostop.py` adapted.
- [ ] Commit, push, PR.

## Phase 7 — Growth (branch `feat/library` on `feat/box`)

### Task 7.1: Thing library
- `scripts/import_icons.py` fetches game-icons.net SVGs (CC BY 3.0) into `library/things/` with `index.json` (name, tags, author). Attribution goes into `post.txt` when a job uses one.
- [ ] Test: `test_index_lookup_by_tag`.

### Task 7.2: Vectorize an image into a thing
- `scripts/vectorize.py IMAGE NAME` runs vtracer to a flat SVG and recolours it. A raster from any image model on the box becomes a library thing after the user looks at it.

### Task 7.3: Remembered scenes and variants
- Approved jobs copy their scene code into `styles/<style>/examples/` with the beat text. The coder prompt gets the 2 most similar by word overlap.
- `settings.variants` (default 1) makes the director propose N stagings, and vision picks one.
- [ ] Tests: `test_examples_most_similar_first`, `test_variants_vision_picks`.
- [ ] Docs, commit, push, PR.
