# Providers, quality gates, experiments and metrics

Design for turning the research verdict ("AI Video Pipeline — сравнительный System
Design", 2026-10-28) into code on top of the existing reelsmith conveyor.

**Revision of 2026-10-29, evening:** the API contour is gone. Egor decided the pipeline
runs on local models only. Everything below describes the local-only system; the cloud
adapters, API keys, moderation refusals and fallback providers of the first draft were
removed from the code, the plan and this document.

## Intent

The research says: keep every generative step behind one interface so the model is a
name in `.env`, add the quality gates from the pipeline diagram, measure cost per good
video and retention per hook, and pick the video model by a blind A/B on identical
keyframes. None of that can be exercised on this machine: the GPU host is elsewhere and
no weights are loaded here. So the pipeline must be complete and verifiable with
synthetic providers first, and the local adapters must plug into the same ports.

The existing code (conveyor, stages, editing, ComfyUI/Ollama/VoxCPM adapters) is kept
and extended.

## Goals

1. **Recipes.** Every job carries a `Recipe`: provider names for script, judge, image,
   video, voice, music, plus `hook_video` and `hook_shots`. Defaults come from settings; a
   job can override any field at `add` time.
2. **Quality gates** as in the research diagram: critic loop on the script (score ≥ 7,
   ≤ 2 rewrites); two keyframe candidates per shot with a vision pick; artifact check on
   every clip with per-shot retry (≤ 2) on a new seed; QA of the final cut with rewind to
   animation when rejected; manual approve / reject.
3. **Routing.** The first `hook_shots` shots go to `hook_video`, the rest to `video`, so a
   heavy model can serve the hook and a draft model the rest.
4. **Cost and calls.** Every generative call is recorded on the job: stage, provider,
   units, USD, outcome (ok / flagged / failed), shot, wall seconds. Units are what the
   model generates (Wan rounds to 4k+1 frames). Price is GPU seconds per unit from the
   research benchmark (RTX 5090, FP8, lightx2v LoRAs) times the hourly rent from
   settings, so the report gives both GPU hours and dollars.
5. **Experiments.** Fork a job into another arm with a different recipe, sharing script,
   voices and frames: the fork starts at FRAMED (or earlier if the parent has not got that
   far) with clips, music and final dropped. The parent is labelled at the same time
   (experiment = its id, arm `A`). The fork inherits the parent's calls marked `shared`:
   `compare` counts them, `report` skips them. Rate a cut blind. Compare arms: videos,
   cost per video, cost per good video, QA score, flags, rating, retention.
6. **Metrics report.** Cost per good video (failed ones included in the numerator), flag
   rate and GPU hours per provider, QA pass rate, retention at 3 s per hook kind, GPU hours
   total. Platform numbers are entered by hand (`measure`); a `Measure` stage exists only
   where analytics can be read by code, which today is the synthetic demo.
7. **Synthetic mode.** Deterministic providers with no network and no models that produce
   real media (ffmpeg colour clips, generated tones) so the real assembly runs end to end.
   `reelsmith demo` runs several ideas through the whole conveyor in memory, forks a B arm
   on the same frames, auto-approves, measures, and prints the comparison and the report.
   `REELSMITH_PROVIDERS=synthetic` runs the same providers inside the real worker.
8. **Local adapters** for every role: Ollama writer, critic and vision judge (structured
   output through `format`, images as base64), ComfyUI painter / animator / composer named
   after their exported graphs, VoxCPM narrator. Each is tested against a mock transport
   or an in-memory graph.
9. Workers can be split per stage (`reelsmith work --stages voice,frames`).

## Non-goals

- Cloud providers of any kind, API keys, moderation handling, fallback providers.
- Celery, Redis, MinIO. Postgres stays the queue; stage boundaries are the worker
  boundaries.
- SFX track, TikTok / Instagram publishers and analytics. Ports exist; outbox and
  synthetic analytics are the only implementations.
- Separate hook-generation stage. The script writer returns the hook and its kind.
- Downloading weights or running anything on a GPU from this machine.

## Anti-goals

- Comments that narrate code, abstractions for providers that do not exist, settings
  nobody reads.
- Hidden cost accounting (context variables, global ledgers). Calls are recorded where
  the stage makes them.

## Constraints

- Python 3.12, no new runtime dependencies.
- Keep the module layout and the style of the existing code: pure domain, ports as
  protocols, adapters per service, one composition root.
- `ruff check`, `ruff format --check`, `mypy --strict src` stay green.

## Decided shape

### Domain (`domain.py`)

- `Status` gains `MEASURED` after `PUBLISHED`. ASSEMBLED → APPROVED is human only. A QA
  rejection moves ASSEMBLED back to FRAMED.
- `Recipe(script, judge, image, video, voice, music, hook_video=None, hook_shots=2)` with
  `video_for(shot)`.
- `Script` gains `hook_kind`. `Verdict(score, notes, bad_shots)`.
- `Call(stage, provider, units, usd, outcome: ok|flagged|failed, shot, seconds, shared)`.
- `Metrics(views, retention_3s, completion)`. `Assets` gains `candidates` and `posted`.
- `Job` gains `recipe`, `last_error`, `critique`, `qa`, `calls`, `experiment`, `arm`,
  `parent`, `rating`, `metrics`. Policy lives here: `fail`, `rewind`, `reject` (a person
  turned the cut down: clips and final dropped, rewind to FRAMED), `fork`, `cost`, `spent`,
  `good`.

### Pricing (`pricing.py`)

`Rate(unit, gpu_seconds)`, `RATES` for the six local providers, `Tariff(rates,
usd_per_gpu_hour)` with `gpu_seconds()` and `usd()`, and `metered()`, a context manager
that appends the `Call`, times the block and marks `failed` when an exception escapes.
The stage may set `call.outcome = FLAGGED` after the judge speaks.

### Ports (`ports.py`)

Every provider has `name` and `tenant` (GPU tenant: `llm`, `comfy`, `tts`). Writer,
Critic, Judge (`pick`, `inspect`, `review`), Painter, Animator (`max_seconds`,
`length()`), Narrator (`suffix`), Composer (`suffix`), Transcriber, Montage, Publisher,
Analytics, GpuTenant, JobStore (`add`, `get`, `claim(status, limit, settled)`, `save`,
`find(experiment, status)`, `summary`).

### Providers (`providers.py`, `bootstrap.local_providers`)

`Providers` is a frozen dataclass of `name -> adapter` mappings per role with accessors
that raise `UnknownProvider` naming the role, the name and what is available, and
`check(recipe)` for startup. Names:

| role   | names                                                    |
| ------ | -------------------------------------------------------- |
| script | `ollama` (writer model)                                  |
| judge  | `ollama` (critic on the writer model, judge on the judge model) |
| image  | `z-image` (`keyframe.json`)                              |
| video  | `wan-2.2` (`animate.json`, 16 fps), `wan-5b` (`animate-draft.json`, 24 fps) |
| voice  | `voxcpm`                                                 |
| music  | `ace-step` (`score.json`)                                |

ComfyUI providers are built only when their graph exists in the workflows folder.

### Stages (`stages.py`)

As in the first draft, minus the refusal chain: `Motion` resolves one animator per shot
from `recipe.video_for(i)`, caps the request at `max_seconds`, bills `length(seconds)`,
inspects stills and retries flagged clips with a new seed. Shots run under a semaphore of
`parallel_shots`, default 1 on one card.

### Conveyor, experiments, metrics, persistence, synthetic providers

Unchanged from the first draft except: `ProviderRow` carries `flagged`, `flag_rate`,
`usd`, `gpu_hours` and no refusal fields; `Arm` has no `refused`; synthetic providers
register the six local names and take `flag` and `reject` probabilities for the judge.

### Settings, bootstrap, CLI (`settings.py`, `bootstrap.py`, `demo.py`, `cli.py`)

- Settings: service URLs, `providers: local|synthetic`, `writer_model`, `judge_model`,
  `language`, `voice`, `whisper_model`, one `*_provider` per role plus `hook_shots`,
  gate knobs (`script_rewrites`, `candidates`, `shot_retries`, `parallel_shots`),
  `gpu_hour_usd`, folders, conveyor knobs; `recipe()` and `tariff()`.
- `bootstrap.local_providers(settings, ollama, comfy, tts)`, `stages(...)` in conveyor
  order with `Measure` only when analytics is given, `only(stages, names)`,
  `application(settings, stage_names)` which validates the default recipe at startup when
  no stage filter is given.
- `demo.run(ideas, arm_a, arm_b, out)` on `MemoryJobs`, synthetic providers with
  `FLAG = 0.2`, `REJECT = 0.15`, real ffmpeg, outbox under `out`.
- CLI: `migrate`, `add` (recipe overrides, `--experiment`, `--arm`), `fork`, `approve`,
  `reject`, `rate`, `measure`, `compare`, `report`, `status`, `work [--once] [--stages]`,
  `demo`. Plain-text tables.
