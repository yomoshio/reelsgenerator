# Providers, quality gates, experiments and metrics — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generative step of reelsmith a named provider chosen per job, add the research's quality gates, record cost per call, support A/B forks on identical frames with a metrics report, and prove it all end to end with synthetic providers and real ffmpeg.

**Architecture:** The existing conveyor (Postgres queue, batch-by-stage) stays. Stages resolve adapters from the job's `Recipe` through a `Providers` registry; `metered()` records a `Call` around each generative call; policy (retries, rewinds, failure) lives on `Job`. Synthetic providers implement the same ports with ffmpeg-made media so the real assembly runs without models.

**Tech Stack:** Python 3.12, pydantic 2, httpx, psycopg 3, typer, structlog, anthropic SDK (new), ffmpeg; pytest + pytest-asyncio, ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-10-29-providers-gates-experiments-design.md`

**Status (2026-10-30):** superseded by the flat structure, see
`docs/superpowers/specs/2026-10-30-flat-structure-design.md`; module names below are historical.

**Status (2026-10-29, evening):** all tasks done. After Task 11 Egor decided the pipeline
runs on local models only, so the API contour (Anthropic, Gemini, ElevenLabs, moderation
refusals, fallback providers) was removed and Tasks 12–14 below are the local-only
versions that were actually built. 99 tests, ruff and mypy --strict green.

The project is not a git repository and the user has not asked for one, so there are no
commit steps. Each task ends with `make test lint` green.

## Global Constraints

- Python 3.12; the only new runtime dependency is `anthropic`.
- `ruff check`, `ruff format --check`, `mypy --strict src` green after every task.
- No narrating comments; a comment only states a non-obvious why.
- Keep the module layout: `domain.py` pure, `ports.py` protocols, `adapters/` per service, `bootstrap.py` the only composition root.
- Provider names, tariffs and model ids come from the spec tables; prices are the research's October 2026 figures.

## Review Focus

1. A job whose recipe names a provider that is not registered must fail that stage with the role and the name in the error, not crash the worker — pinned in Task 3.
2. A `Refused` from every provider in the chain for one shot must leave the clips already rendered for other shots in `assets.clips` so the job-level retry does not redo them — pinned in Task 7.
3. A QA rewind must clear the clips it names and nothing else, and the third rewind must park the job as FAILED rather than loop — pinned in Tasks 1 and 8.
4. `metered()` must record the call when the provider raises, with `refused` for `Refused` and `failed` for anything else, so refusal rates count every attempt — pinned in Task 2.
5. The ffmpeg graph must accept an mp3 voice track and an mp3 music track (ElevenLabs output), not only wav/flac — pinned in Task 10's end-to-end test by running the synthetic narrator with `.mp3`.

---

### Task 1: Domain

**Files:**
- Modify: `src/reelsmith/domain.py`
- Modify: `src/reelsmith/errors.py`
- Test: `tests/test_domain.py`

**Interfaces (produces):**
- `Status.MEASURED` after `PUBLISHED`; `GOOD: frozenset[Status] = {APPROVED, PUBLISHED, MEASURED}`.
- `class Recipe(BaseModel)`: `script, judge, image, video, voice, music: str`; `hook_video: str | None = None`; `hook_shots: int = 2`; `fallback_video: str | None = None`; `def video_chain(self, shot: int) -> list[str]` (first the hook or main provider, then the fallback if set and different).
- `Script.hook_kind: str` (required, description "One word: question, threat, promise, secret, countdown").
- `class Verdict(BaseModel)`: `score: float = Field(ge=0, le=10)`, `notes: str = ""`, `bad_shots: list[int] = []`.
- `class Outcome(StrEnum)`: `OK = "ok"`, `REFUSED = "refused"`, `FLAGGED = "flagged"`, `FAILED = "failed"`.
- `class Call(BaseModel)`: `stage: str`, `provider: str`, `units: float`, `usd: float`, `outcome: Outcome = OK`, `shot: int | None = None`, `seconds: float = 0.0`, `shared: bool = False`.
- `class Metrics(BaseModel)`: `views: int`, `retention_3s: float (0..1)`, `completion: float (0..1)`.
- `class Post(BaseModel)`: `caption: str`, `hook_kind: str`, `ai_generated: bool = True`.
- `Assets.candidates: dict[int, list[str]]`, `Assets.posted: str | None`.
- `Job` fields added: `recipe: Recipe` (positional after `status`), `last_error: str | None`, `critique: Verdict | None`, `qa: Verdict | None`, `calls: list[Call]`, `experiment: str | None`, `arm: str | None`, `parent: UUID | None`, `rating: int | None`, `metrics: Metrics | None`.
- `Job.new(idea: str, recipe: Recipe, *, experiment: str | None = None, arm: str | None = None) -> Job` (classmethod, fresh uuid4, status NEW).
- `Job.cost -> float` (every call, shared included), `Job.spent -> float` (own calls only), `Job.good -> bool`.
- `Job.fail(reason: str, max_attempts: int) -> None`: attempts += 1, `last_error = reason`, status FAILED when `attempts >= max_attempts`.
- `Job.rewind(to: Status, reason: str, max_attempts: int) -> None`: same accounting, status `to` unless parked.
- `Job.fork(recipe: Recipe, arm: str, *, parent_arm: str = "A") -> Job`: labels the parent first (`experiment = experiment or str(id)`, `arm = arm or parent_arm`); the child gets a new id, `parent = self.id`, the parent's experiment, deep copies of script, critique, voices, frames and candidates, no clips/music/final/posted, status = the parent's when it is before FRAMED in conveyor order, else FRAMED; `calls` = copies of the parent's calls with `shared=True`; `rating`, `qa`, `metrics`, `last_error` None, `attempts` 0.
- `errors.py`: `class Refused(StageError)`; `class ProviderError(StageError)`; `class UnknownProvider(StageError)`; `class Rewind(Exception)` with `__init__(self, to: Status, reason: str)` and attributes `to`, `reason`.

- [ ] **Step 1: Write the failing tests** in `tests/test_domain.py`:
  - `test_status_walks_the_whole_conveyor` now ends at `MEASURED`.
  - `test_video_chain_routes_hook_shots_and_falls_back`: recipe `video="omni-flash", hook_video="kling-3", hook_shots=2, fallback_video="wan-2.2"`; `video_chain(0) == ["kling-3", "wan-2.2"]`, `video_chain(2) == ["omni-flash", "wan-2.2"]`; without `fallback_video` the chain has one entry; a fallback equal to the main provider is not repeated.
  - `test_fail_parks_the_job_at_the_limit`: two fails with `max_attempts=3` keep status, third sets FAILED and `last_error`.
  - `test_rewind_moves_back_and_counts_an_attempt`: rewind from ASSEMBLED to FRAMED → status FRAMED, attempts 1; at the limit → FAILED.
  - `test_fork_starts_at_frames_with_shared_calls`: fork of an ASSEMBLED job with clips and one call → status FRAMED, clips/music/final empty, frames equal, `calls[0].shared`, `cost` equal to the parent's, `spent == 0`, parent now has `experiment == str(parent.id)` and `arm == "A"`, mutating the fork's assets leaves the parent's untouched.
  - `test_fork_of_a_scripted_job_keeps_its_status`.
  - `test_cost_sums_calls`.
- [ ] **Step 2: Run** `pytest tests/test_domain.py -q` → fails on imports.
- [ ] **Step 3: Implement** the interfaces above. Keep `Shot`, `Character`, `looks_of`, `seconds` as they are.
- [ ] **Step 4: Run** `pytest tests/test_domain.py -q` → pass. Other test files fail on `Job(...)` arity; they are fixed in their own tasks.

### Task 2: Pricing and metering

**Files:**
- Create: `src/reelsmith/pricing.py`
- Test: `tests/test_pricing.py`

**Interfaces (produces):**
- `class Unit(StrEnum)`: `CALL = "call"`, `IMAGE = "image"`, `SECOND = "second"`, `CHAR = "char"`.
- `@dataclass(frozen=True, slots=True) class Rate`: `unit: Unit`, `usd: float`, `gpu_seconds: float = 0.0`.
- `def local(unit: Unit, gpu_seconds: float, *, usd_per_gpu_hour: float = 0.99) -> Rate`.
- `class Tariff`: `__init__(self, rates: Mapping[str, Rate])`; `rate(provider) -> Rate` (KeyError with the provider name); `usd(provider, units) -> float`; `gpu_seconds(provider, units) -> float`.
- `DEFAULT: Tariff` with: `claude-sonnet-4-6` CALL 0.01; `ollama` local(CALL, 15); `nano-banana-2` IMAGE 0.067; `nano-banana` IMAGE 0.039; `z-image` local(IMAGE, 10); `omni-flash` SECOND 0.10; `kling-3` SECOND 0.11; `wan-2.2` local(SECOND, 48); `elevenlabs` CHAR 0.0001; `voxcpm` local(CHAR, 0.05); `eleven-music` SECOND 0.0025; `ace-step` local(SECOND, 2).
- `@contextmanager def metered(job: Job, tariff: Tariff, *, stage: str, provider: str, units: float = 1.0, shot: int | None = None) -> Iterator[Call]`: yields the `Call` (usd priced up front), sets `outcome` REFUSED on `Refused`, FAILED on any other exception, records wall `seconds`, always appends to `job.calls`, re-raises.

- [ ] **Step 1: Tests**: `test_local_rate_prices_gpu_time` (`local(Unit.SECOND, 48).usd == pytest.approx(0.0132)`), `test_tariff_rejects_unknown_provider` (KeyError match name), `test_metered_records_ok_call_with_price` (units 5 on omni-flash → usd 0.5, outcome OK, seconds ≥ 0), `test_metered_marks_refusals_and_reraises`, `test_metered_marks_other_errors_failed`, `test_caller_can_flag_the_call_afterwards`.
- [ ] **Step 2: Run** → fails. **Step 3: Implement.** **Step 4: Run** → pass.

### Task 3: Ports and the provider registry

**Files:**
- Modify: `src/reelsmith/ports.py`
- Create: `src/reelsmith/providers.py`
- Create: `tests/fakes.py`
- Test: `tests/test_providers.py`

**Interfaces (produces):**
- Every provider protocol gains `name: str` and `tenant: str | None`.
- `Writer.write(idea: str, notes: str | None = None) -> Script`; `Critic.review(script: Script) -> Verdict`; `Judge.pick(brief: str, images: list[Path]) -> int`, `Judge.inspect(motion: str, stills: list[Path]) -> Verdict`, `Judge.review(script: Script, stills: list[Path]) -> Verdict`; `Painter.paint(prompt, *, seed, out) -> Path`; `Animator.animate(frame, motion, *, seconds, seed, out) -> Path` plus `max_seconds: float` and `length(seconds: float) -> float` (seconds generated and billed); `Narrator.speak(text, out) -> Path` plus `suffix: str`; `Composer.compose(brief, *, seconds, seed, out) -> Path` plus `suffix: str`; `Transcriber.words(audio) -> list[Word]`; `Montage.seconds(media) -> float`, `Montage.stills(video: Path, count: int, out_dir: Path) -> list[Path]`, `Montage.render(cut, out) -> Path`; `Publisher.publish(video: Path, post: Post) -> str`; `Analytics.measure(posted: str) -> Metrics`; `GpuTenant.release()` only (no name).
- `JobStore`: `add(job)`, `get(job_id) -> Job` (LookupError), `claim(status, limit, settled: timedelta = timedelta(0)) -> list[Job]`, `save(job)`, `find(*, experiment: str | None = None, status: Status | None = None) -> list[Job]`, `summary() -> dict[str, int]`.
- `providers.py`: `@dataclass(frozen=True) class Providers` with `writers, critics, judges, painters, animators, narrators, composers: Mapping[str, ...]`; accessors `writer(recipe) -> Writer`, `critic(recipe)`, `judge(recipe)`, `painter(recipe)`, `animator(name: str) -> Animator`, `narrator(recipe)`, `composer(recipe)`, each raising `UnknownProvider("no {role} provider named {name!r}; have: a, b")`; `check(recipe) -> None` runs every accessor including each name in `video_chain` for shots 0 and `hook_shots`.
- `tests/fakes.py`: in-memory providers with no ffmpeg: `FakeWriter(hook_kind="question")`, `FakeCritic(scores: list[float])` (pops scores, last one repeats), `FakeJudge(picks: int = 0, flag: set[int] = (), reject: Verdict | None = None)`, `FakePainter()`, `FakeAnimator(name, *, refuse: bool = False, max_seconds=8.0)`, `FakeNarrator(suffix=".wav")`, `FakeComposer(suffix=".flac")`, `FakeMontage(seconds=3.0)` (stills writes `count` empty files, render writes an empty file), `FakeTranscriber()`, `FakePublisher()`, `FakeAnalytics(retention=0.5)`; helpers `recipe(**overrides) -> Recipe` (defaults `script="fake", judge="fake", image="fake", video="fast", voice="fake", music="fake"`), `providers(**overrides) -> Providers` (registers the fakes under those names and `animators={"fast": FakeAnimator("fast"), "slow": FakeAnimator("slow")}`), `tariff() -> Tariff` (flat rates for the fake names), `job(idea="zombies", status=Status.NEW, **kw) -> Job`. Every fake writes `out.write_bytes(b"")` and records calls in a `log: list` attribute.

- [ ] **Step 1: Tests** in `tests/test_providers.py`: `test_accessor_names_the_role_and_the_missing_provider` (`pytest.raises(UnknownProvider, match="video provider named 'veo'")`), `test_check_covers_hook_and_fallback_names`, `test_check_passes_for_a_complete_recipe`.
- [ ] **Step 2: Run** → fails. **Step 3: Implement** ports, registry, fakes. **Step 4: Run** → pass; `mypy src` green.

### Task 4: In-memory job store

**Files:**
- Create: `src/reelsmith/adapters/memory.py`
- Test: `tests/test_memory_store.py`

**Interfaces (produces):**
- `class MemoryJobs` implementing `JobStore`; `__init__(self, *, lease: timedelta = timedelta(minutes=45), clock: Callable[[], datetime] = _utcnow)`; `claim` leases the returned jobs until `clock() + lease` and skips leased ones, honours `settled` against the job's last save time, orders by creation; `save` clears the lease and stamps the save time.

- [ ] **Step 1: Tests**: `test_claim_returns_oldest_first_and_leases`, `test_save_releases_the_lease`, `test_settled_hides_recently_saved_jobs` (clock stub advanced past `settled`), `test_find_filters_by_experiment_and_status`, `test_get_raises_lookup_error`, `test_summary_counts_statuses`.
- [ ] **Step 2–4:** fail, implement, pass.

### Task 5: Conveyor

**Files:**
- Modify: `src/reelsmith/conveyor.py`, `src/reelsmith/gpu.py`
- Modify: `tests/test_conveyor.py`

**Interfaces (produces):**
- `class Stage(Protocol)`: `takes: ClassVar[Status]`, `settled: timedelta`, `def tenant(self, job: Job) -> str | None`, `async def run(self, job: Job) -> None`.
- `Conveyor.__init__(self, stages: Sequence[Stage], store: JobStore, arbiter: GpuArbiter, *, batch_size: int, max_attempts: int)`; `turn() -> int`; `run_forever(idle_seconds)`.
- `GpuArbiter.__init__(self, tenants: Mapping[str, GpuTenant])`; `hold(name: str | None)` is a no-op context for `None`.
- `_push`: `Rewind` → `job.rewind(back.to, back.reason, max_attempts)`, `StageError` → `job.fail(...)`, success → `status.next()`; every branch calls `store.save(job)`.

- [ ] **Step 1: Tests** (rewrite `tests/test_conveyor.py` on `MemoryJobs` and fakes): keep the three existing behaviours; add `test_rewind_sends_the_job_back_and_counts_an_attempt`, `test_a_job_fails_for_good_after_max_attempts`, `test_tenant_is_held_per_job_so_mixed_recipes_hand_over` (two jobs, stage tenant depends on recipe: handover released once), `test_settled_is_passed_to_claim` (store spy records the timedelta).
- [ ] **Step 2–4:** fail, implement, pass.

### Task 6: Media folder and montage stills

**Files:**
- Modify: `src/reelsmith/media.py`, `src/reelsmith/editing.py`, `src/reelsmith/adapters/ffmpeg.py`
- Test: `tests/test_editing.py`, `tests/test_media.py`

**Interfaces (produces):**
- `JobFolder.voice(shot: int, suffix: str = ".wav")`, `frame(shot: int, candidate: int = 0)` → `frames/{shot:02d}-{candidate}.png`, `clip(shot)`, `stills(shot: int | None)` → directory `stills/{shot:02d}` or `stills/final`, `music(suffix: str = ".flac")`, `subtitles()`, `final()`.
- `editing.stills_args(video: Path, count: int, out_dir: Path) -> list[str]`: ffmpeg `-vf fps=count/duration` is not known up front, so use `select='not(mod(n,{step}))'`? No: use `-vf "fps={count}/{seconds}"` requires duration. Decided: `["ffmpeg","-y","-hide_banner","-loglevel","error","-i",video,"-vf",f"thumbnail={count}"...]` is also wrong. Use `-vf "select='isnan(prev_selected_t)+gte(t-prev_selected_t,{spacing})'"` — too clever. **Decision:** `FfmpegMontage.stills` probes the duration first (`seconds()`), then runs `-vf fps=1/{duration/count}` with `-frames:v count` writing `out_dir/%02d.png`; `stills_args(video, count, seconds, out_dir)` builds that argv as a pure function.
- `adapters/ffmpeg.py`: `run(*argv) -> str` made public (used by the synthetic providers); `FfmpegMontage.stills` returns the sorted PNG paths.

- [ ] **Step 1: Tests**: `test_stills_args_spaces_frames_over_the_clip` (count 4 on 5 s → `fps=1/1.250`, `-frames:v 4`, output pattern ends with `%02d.png`), `test_folder_names_candidates_and_stills`.
- [ ] **Step 2–4:** fail, implement, pass. Keep `ffmpeg_args` unchanged.

### Task 7: Stages — script, voice, frames, motion

**Files:**
- Modify: `src/reelsmith/stages.py`
- Test: `tests/test_stages.py`

**Interfaces (produces):**
- Constants: `SCRIPT_PASS = 7.0`, `CLIP_PASS = 6.0`, `QA_PASS = 7.0`, `CANDIDATES = 2`, `STILLS = 4`, `SHOT_PADDING`, `SHOT_MIN/MAX` as before.
- `seed_for` salts: music 0, frame candidate `1000 + shot * 10 + candidate`, clip `2000 + shot * 10 + attempt + 100 * job.attempts`.
- `Frames` and `Motion` take `parallel: int = 4` and run their per-shot work under `asyncio.Semaphore(parallel)` with `asyncio.gather(..., return_exceptions=True)`; results of finished shots are stored before the first exception is re-raised. Tests must not depend on the order of `job.calls`.
- `@dataclass class WriteScript`: `providers: Providers`, `tariff: Tariff`, `rewrites: int = 2`; stage names `"script"` / `"critic"`.
- `@dataclass class Voice`: `providers, tariff, montage: Montage, media_root: Path`; metered `"voice"` with `units=len(shot.line)`.
- `@dataclass class Frames`: `providers, tariff, media_root, candidates: int = CANDIDATES`; metered `"frame"` per candidate and `"pick"` per shot.
- `@dataclass class Motion`: `providers, tariff, montage, media_root, retries: int = 2, parallel: int = 4`; metered `"animate"` (units = `animator.length(seconds)`) and `"inspect"`; flagged animate calls get `outcome = FLAGGED`; after `retries` flagged attempts the last clip is kept; a `Refused` from the whole chain propagates after the shots before it are stored in `assets.clips`.
- Each stage: `takes`, `settled = timedelta(0)` (class attribute), `tenant(job)` returning the resolved provider's `tenant` (Motion: main video provider's, else hook's).

- [ ] **Step 1: Tests**: `test_script_is_rewritten_with_the_critics_notes_until_it_passes` (scores `[5, 8]` → writer called twice, second call carries notes, `critique.score == 8`, four calls recorded), `test_best_draft_is_kept_after_the_last_rewrite` (scores `[6, 5, 6.5]` → script from the third draft, critique 6.5), `test_frames_paint_two_candidates_and_keep_the_pick` (judge picks 1 → `assets.frames[i]` ends with `-1.png`, `candidates[i]` has two entries, calls: 2 frame + 1 pick per shot), `test_hook_shots_use_the_hook_provider`, `test_refusal_falls_through_to_the_fallback_and_is_counted` (first animator refuses → calls `[refused, ok]`, clip from the fallback), `test_refused_by_every_provider_keeps_earlier_clips` (Review Focus 2), `test_flagged_clip_is_retried_with_a_new_seed_then_kept` (judge flags attempts 0 and 1 → three animate calls, first two FLAGGED, seeds differ, clip stored), `test_voice_sets_shot_seconds_from_the_recording` (kept from the current behaviour).
- [ ] **Step 2–4:** fail, implement, pass.

### Task 8: Stages — score, assemble, publish, measure

**Files:**
- Modify: `src/reelsmith/stages.py`, `src/reelsmith/adapters/outbox.py`
- Test: `tests/test_stages.py`

**Interfaces (produces):**
- `Score`: `providers, tariff, media_root`; metered `"music"` units = seconds.
- `Assemble`: `providers, tariff, transcriber, montage, media_root`; after render: stills of the final → `judge.review(script, stills)` metered `"qa"` → `job.qa`; below `QA_PASS`: remove `assets.clips[i]` for `bad_shots` (all clips when empty), set `assets.final = None`, `raise Rewind(Status.FRAMED, verdict.notes)`.
- `Publish`: `publisher: Publisher, media_root`; builds `Post(caption=script.title, hook_kind=script.hook_kind)`; stores the returned reference in `assets.posted`.
- `Measure`: `analytics: Analytics`, `settled: timedelta` (dataclass field, default `timedelta(hours=24)`); `takes = PUBLISHED`; sets `job.metrics`. Only the synthetic build has it.
- `OutboxPublisher.publish(video, post)` writes `post.json` with `caption`, `hook_kind`, `is_aigc: true` and returns the folder path.

- [ ] **Step 1: Tests**: `test_qa_rejection_rewinds_to_frames_and_drops_only_the_bad_clips` (bad_shots `[1]` → clips keep 0 and 2, `final is None`, `Rewind.to is FRAMED`, `job.qa.score` stored), `test_qa_rejection_without_named_shots_drops_every_clip`, `test_publish_records_the_reference_and_hook_kind` (FakePublisher log holds the `Post`), `test_measure_stores_metrics`, `test_outbox_post_json_marks_ai_content` (tmp_path).
- [ ] **Step 2–4:** fail, implement, pass. Delete the old `gpu: ClassVar` attributes.

### Task 9: Metrics report and arm comparison

**Files:**
- Create: `src/reelsmith/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces (produces):**
- `REFUSAL_ALERT = 0.2`.
- `@dataclass(frozen=True) class ProviderRow`: `provider, calls, refused, flagged, usd`; properties `refusal_rate`, `flag_rate` (0 when no calls), `alarming -> bool`.
- `@dataclass(frozen=True) class HookRow`: `kind, videos, retention_3s, completion` (means over measured jobs).
- `@dataclass(frozen=True) class Report`: `videos, good, failed, pending, usd, cost_per_good: float | None, qa_pass_rate: float | None, providers: list[ProviderRow], hooks: list[HookRow], gpu_hours`.
- `def report(jobs: Iterable[Job], tariff: Tariff) -> Report` — counts only calls with `shared=False`; `pending` = neither good nor failed; `qa_pass_rate` over jobs with a `qa` verdict (`score >= QA_PASS`); providers sorted by usd desc; `gpu_hours` from `tariff.gpu_seconds` over OK/FLAGGED calls.
- `@dataclass(frozen=True) class Arm`: `name, videos, good, usd, cost_per_video, cost_per_good: float | None, qa_score: float | None, flagged, refused, rating: float | None, retention_3s: float | None`.
- `def compare(jobs: Iterable[Job]) -> list[Arm]` grouped by `job.arm` (`None` → `"-"`), sorted by name; `usd` uses `job.cost` (shared calls included) so arms are comparable; `flagged`/`refused` count own calls only.

- [ ] **Step 1: Tests** on hand-built jobs: `test_cost_per_good_video_includes_failed_spend` (2 good at $4 each + 1 failed at $4 → 6.0), `test_report_does_not_count_shared_calls_twice`, `test_refusal_rate_per_provider_flags_above_twenty_percent`, `test_retention_is_averaged_per_hook_kind`, `test_compare_groups_arms` (arm A/B cost, qa mean, rating mean, `-` arm for unlabeled).
- [ ] **Step 2–4:** fail, implement, pass.

### Task 10: Synthetic providers and the end-to-end run

**Files:**
- Create: `src/reelsmith/adapters/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces (produces):**
- `@dataclass(frozen=True) class Odds`: `refuse: float = 0.0`, `flag: float = 0.0`, `reject: float = 0.0`.
- `def rng(*parts: object) -> random.Random` seeded from sha256 of the parts.
- `SyntheticWriter(name="synthetic", tenant=None)`: `write(idea, notes)` → `Script` with six shots from fixed templates, `hook_kind` from `("question", "threat", "promise", "secret", "countdown")` by `rng(idea)`, `title = idea`; with `notes` the lines are rewritten (different text, same count).
- `SyntheticCritic(name)`: `score = round(5 + 4.9 * rng(script.model_dump_json()).random(), 1)`, notes `"tighten the hook"`.
- `SyntheticJudge(name, odds: Odds)`: `pick` by `rng(*paths)`; `inspect` flags with `odds.flag` → `Verdict(score=4.0, notes="motion smear")` else 8.0; `review` rejects with `odds.reject` → `Verdict(5.0, "shot drifts", bad_shots=[one shot])` else 8.5.
- `SyntheticPainter(name)`: ffmpeg colour PNG 720×1280 (colour from `rng(prompt, seed)`).
- `SyntheticAnimator(name, odds, max_seconds=8.0)`: raises `Refused(f"{name} declined the prompt")` with `odds.refuse` by `rng(name, motion, seed)`; else ffmpeg colour clip of `seconds` at 360×640, 12 fps.
- `SyntheticNarrator(name, suffix=".wav")`: tone of `max(1.0, 0.065 * len(text))` s via ffmpeg `sine`, writes `out.with_suffix(".txt")` with the text.
- `SyntheticComposer(name, suffix=".flac")`: low tone of `seconds`.
- `SyntheticTranscriber()`: words of the sidecar text spread evenly over the wav duration (`wave` module).
- `SyntheticAnalytics()`: reads `post.json` from `posted`, `retention_3s` = base per hook kind (`question .55, threat .5, promise .45, secret .6, countdown .4`) ± 0.1 noise, `completion = retention * 0.6`, `views` 1000–20000.
- `def synthetic_providers(odds: Mapping[str, Odds] = DEMO_ODDS) -> Providers` registering the spec's names (`claude-sonnet-4-6`, `ollama`, `nano-banana-2`, `nano-banana`, `z-image`, `omni-flash`, `kling-3`, `wan-2.2`, `elevenlabs`, `voxcpm`, `eleven-music`, `ace-step`) with the matching `tenant`, `suffix` and `max_seconds` values. `DEMO_ODDS`: `omni-flash` refuse 0.1, `kling-3` refuse 0.25, `wan-2.2` refuse 0, judge flag 0.2 reject 0.15.

- [ ] **Step 1: Tests**: `test_synthetic_outputs_are_deterministic` (two writers, same idea → equal scripts; two animators, same inputs → same refusal decision), `test_rewrite_changes_the_lines`, `test_transcriber_spreads_words_over_the_recording` (narrator → transcriber, words count equals text words, last end ≈ duration), `test_end_to_end_synthetic_run_produces_a_final_cut` (skip if no ffmpeg): MemoryJobs + synthetic providers with zero odds + real `FfmpegMontage` + outbox in `tmp_path`, a narrator with `suffix=".mp3"` (Review Focus 5); stages built by hand; loop `turn()` until 0; assert one job reaches ASSEMBLED, `final.mp4` exists and `ffprobe` reports duration within 1 s of `script.seconds`, calls include every stage name, `job.cost > 0`.
- [ ] **Step 2–4:** fail, implement, pass. Mark the e2e test with `pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")`.

### Task 11: Postgres store and migration

**Files:**
- Create: `migrations/002_experiments.sql`
- Modify: `src/reelsmith/adapters/postgres.py`

**Interfaces (produces):**
- Columns: `recipe jsonb not null default '{}'`, `experiment text`, `arm text`, `parent uuid`, `calls jsonb not null default '[]'`, `critique jsonb`, `qa jsonb`, `rating int`, `metrics jsonb`; index on `(experiment)`.
- `PostgresJobs(pool, *, lease_minutes)` implementing the new `JobStore`; `claim` adds `and updated_at < now() - %(settled)s` (interval); `save` is a single `update` of every mutable column; `find`, `get`, `summary`.

- [ ] **Step 1:** Write the SQL and the mapping. No database here: verify with `mypy src` and `ruff`, and keep `_payload`/`_to_job` symmetric with `MemoryJobs` behaviour (a round trip test on `_payload` → `_to_job` with `Jsonb` unwrapped is enough: `tests/test_postgres_mapping.py::test_job_round_trips_through_the_row`).
- [ ] **Step 2:** `pytest tests/test_postgres_mapping.py -q` pass.

### Task 12: Local-only cut

**Files:** `domain.py`, `errors.py`, `pricing.py`, `providers.py`, `metrics.py`, `stages.py`,
`adapters/synthetic.py`, `adapters/ollama.py`, `adapters/comfy.py`, `adapters/voxcpm.py`,
`prompts/critic.md`, `prompts/judge.md`; tests updated, `tests/test_ollama.py` added.

- [x] `Recipe` loses `fallback_video` and `video_chain`; gains `video_for(shot)`. `Job.reject`.
- [x] `Refused`, `ProviderError` and `Outcome.REFUSED` removed; `WriterError` → `OllamaError`.
- [x] `Rate(unit, gpu_seconds)`, `RATES` for the six local names, `Tariff(rates, usd_per_gpu_hour)`.
- [x] `Motion` resolves one animator per shot. `ProviderRow` gets `gpu_hours`, loses refusals.
- [x] `Ollama` client with `chat[T](system, user, shape, images, temperature)` and `release()`
      that unloads every loaded model; `OllamaWriter` (notes on rewrite), `OllamaCritic`,
      `OllamaJudge` (base64 images, clamped pick). Prompts for critic and judge.
- [x] ComfyUI adapters carry `name`, `tenant`, `suffix`, `max_seconds`, `length()`; the
      animator takes `fps` so the 5B draft graph runs at 24 fps. VoxCPM carries its name.
- [x] Synthetic providers register `ollama`, `z-image`, `wan-2.2`, `wan-5b`, `voxcpm`,
      `ace-step`; the judge takes `flag` and `reject` probabilities.

### Task 13: Settings, bootstrap, CLI and demo

**Files:** `settings.py`, `bootstrap.py`, `demo.py`, `cli.py`; `tests/test_bootstrap.py`,
`tests/test_demo.py`, `tests/test_cli.py`.

- [x] Settings as in the spec, `recipe()`, `tariff()`, `env_ignore_empty`.
- [x] `local_providers` builds ComfyUI providers only for graphs that exist; `stages()`;
      `only()`; `application()` with `stage_names` and startup `check`.
- [x] `demo.run` on `MemoryJobs`: front stages, fork every job into arm B, drain,
      auto-approve, synthetic ratings, drain to MEASURED, return jobs, arms, report.
- [x] CLI commands `migrate`, `add`, `fork`, `approve`, `reject`, `rate`, `measure`,
      `compare`, `report`, `status`, `work`, `demo` with plain-text tables; `LookupError`
      becomes an exit code, not a traceback.
- [x] Tests: `CliRunner` with a monkeypatched `database()` yielding `MemoryJobs`; demo end
      to end with ffmpeg.

### Task 14: Docs and config

- [x] `.env.example` with the local recipe, gate knobs and `GPU_HOUR_USD`; `make demo`;
      `demo/` ignored; `workflows/README.md` documents `animate-draft.json`.
- [x] `README.md` rewritten for the local-only pipeline; `docs/how-it-works.md` (Russian
      operator guide) rewritten with real demo output; this spec and plan revised.
