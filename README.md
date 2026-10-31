# reelsmith

Turns a one-line idea ("зомби в ночном метро") into a 30–50 second vertical video on local
models only: Qwen3.5 on Ollama writes the script, criticises it and judges the pictures;
Z-Image draws the key frames; Wan 2.2 animates them; VoxCPM2 reads the lines; ACE-Step
scores it; ffmpeg cuts it together. Every model call is written down in GPU seconds, so the
cost of a good video and the share of the card each model takes are known numbers. Two
video models can be compared blind on the same frames.

No API keys, no cloud. The only network traffic is downloading weights once.


## Highlights

- Script: Qwen3.5 with a critic loop (structured JSON through Ollama's `format`)
- Key frames: Z-Image Turbo, two candidates per shot, a vision model picks one
- Animation: Wan 2.2 14B; the 5B draft graph as a second model for A/B runs
- Voice: VoxCPM2 with a cloned voice; music: ACE-Step; subtitles: faster-whisper on CPU
- Gates: critic ≥ 7, clip inspection ≥ 6 with retries, QA of the cut ≥ 7 with rewind
- Cost: GPU seconds per call, dollars at your hourly rent, report per model and per hook
- Experiments: fork a job into arm B on identical frames, blind rating, side-by-side table
- Synthetic mode: the whole conveyor with no weights, real ffmpeg, for tests and demos


## System requirements

One Linux host with an NVIDIA card. The pipeline was sized for an RTX 5090 (32 GB): Wan 2.2
14B in FP8 needs it; a 24 GB card runs only the 5B draft model at 480p.

- OS: Ubuntu 24.04
- NVIDIA driver, Docker, NVIDIA container toolkit (scripted in `host/`)
- Python 3.12 on the host only for development and the synthetic demo
- Disk: ~150 GB for weights

See `host/setup-ubuntu-24.04.sh` for the scripted setup of a fresh host.


## Quick start

    sudo host/setup-ubuntu-24.04.sh driver && sudo reboot
    sudo host/setup-ubuntu-24.04.sh docker
    sudo host/setup-ubuntu-24.04.sh toolkit
    host/setup-ubuntu-24.04.sh check

    make setup              # .env and data folders; edit .env
    make build
    make models             # weights from models.toml, ~150 GB
    make llm-model          # pulls the Ollama tag from .env
    cp my-voice.wav voices/narrator.wav && echo "текст этой записи" > voices/narrator.txt
    make up                 # then export the ComfyUI graphs, see workflows/README.md
    make migrate

    docker compose run --rm worker add "зомби в ночном метро" "пациент, который не спит"
    make logs
    docker compose run --rm worker status
    docker compose run --rm worker approve <job-id>

Finished videos land in `outbox/<timestamp>-<id>/video.mp4` with a `post.json` caption.


## How it works

One worker process, no GPU of its own, drives jobs through a conveyor of stages. Jobs live
in Postgres; a stage claims a batch, does one thing to every job in it, saves, and moves on.
Each stage talks to exactly one GPU service, so the worker can ask the previous service to
unload before the next one loads: a 32 GB card does not hold the LLM, the TTS model and
Wan at once.

    new → scripted → voiced → painted → framed → animated → checked → scored → assembled
                                                                                  │
                                                                  (you: approve / reject)
                                                                                  ▼
                                       approved → published → (you: measure) → measured

| Stage | Status it takes | GPU | What it does | Gate |
| --- | --- | --- | --- | --- |
| write | new | Ollama | Writer returns title, hook and its kind, characters, 3–10 shots (line, picture, motion, cast), music brief. Critic scores it. | < 7: rewrite with the notes, up to 2 times; best draft kept |
| voice | scripted | TTS | One file per line. The recording's length plus 0.35 s becomes the shot's length (2–8 s). | |
| paint | voiced | ComfyUI | Two candidate frames per shot from the character looks, the picture and a fixed film-still style. | |
| pick | painted | Ollama | The vision model chooses one candidate per shot. | |
| animate | framed | ComfyUI | One clip per shot from its frame; hook shots may use another model. Skips shots that already have a clip. | |
| check | animated | Ollama | Four stills per clip go to the judge. | < 6: clip dropped, job back to `framed` with a new seed; after 3 tries the clip stays |
| score | checked | ComfyUI | One music track for the script's length plus 2 s. Runs once per job. | |
| assemble | scored | Ollama | ffmpeg: clips cut to their lines, 1080×1920 30 fps, voice over ducked music, burnt subtitles. Eight stills of the result go to the judge. | < 7: bad shots dropped, job back to `framed` |
| approve / reject | assembled | | A person. `reject` drops every clip and rewinds. | |
| publish | approved | | Copies the cut and `post.json` into the outbox. A person uploads. | |
| measure | published | | `reelsmith measure` enters the platform's numbers by hand. | |

Every rewind counts as an attempt; after `REELSMITH_MAX_ATTEMPTS` the job is `failed` with
the reason in `last_error`. Failures inside a stage (ComfyUI error, timeout, a reply that
does not match the schema) also count; anything else crashes the worker on purpose, docker
restarts it, and the 45-minute lease on the claimed jobs expires.

Every model call is recorded on the job: stage, model, units (frames, clip seconds,
characters, calls), GPU seconds × hourly rent in dollars, outcome (`ok`, `flagged`,
`failed`), shot, wall seconds. Units are what the model generates: Wan rounds to 4k+1
frames.

Key modules:

- `src/reelsmith/models.py` — Job, Script, Recipe, Call, statuses; the rules for attempts,
  rewinds, human reject and A/B forks. No I/O.
- `src/reelsmith/pipeline.py` — the stages as plain functions in conveyor order, the
  `Services` they need, the per-job file layout, the gate thresholds.
- `src/reelsmith/conveyor.py` — claims a batch, holds the card for one service, turns
  stage errors and rewinds into job state.
- `src/reelsmith/store.py` — the queue: Postgres with leases, and an in-memory twin for
  tests and the demo.
- `src/reelsmith/pricing.py` — GPU seconds per unit for each model, dollars at the rent.
- `src/reelsmith/report.py` — cost per good video, flags and GPU hours per model,
  retention per hook, arm comparison.
- `src/reelsmith/services/` — one file per thing the pipeline talks to: `ollama.py`
  (writer, critic, judge), `comfy.py` (graphs, frames, clips, music), `voxcpm.py`,
  `whisper.py`, `ffmpeg.py` (cut plan, subtitles, render), `outbox.py`, `synthetic.py`
  (stand-ins for every model).
- `src/reelsmith/app.py` — builds the local or the synthetic service set from settings,
  wires the conveyor, runs the demo.
- `src/reelsmith/cli.py` — `reelsmith add / work / status / approve / reject / rate /
  fork / measure / compare / report / demo / migrate`.
- `src/reelsmith/prompts/` — the writer, critic and judge briefs.
- `services/tts/` — HTTP wrapper around VoxCPM2 (its own container).
- `workflows/` — ComfyUI graphs exported as JSON; the code fills in nodes titled
  `@slot:input`.

Per-job files live under `/data/media/<job-id>/`:

    voice/00.wav …            one recording per shot
    frames/00-0.png, 00-1.png candidates; the chosen one is recorded on the job
    clips/00.mp4 …            one clip per shot
    stills/00/, stills/final/ what the judge looked at
    music.flac  subtitles.ass  final.mp4


## Models and workflows

Weights are listed in `models.toml` with their licenses; only Apache 2.0 and MIT entries
download by default because the channel is monetised. `make models ONLY=video,music`
limits the download to some stages.

| Role | Model | Where | License |
| --- | --- | --- | --- |
| script, critic, judge | Qwen3.5 27B (`REELSMITH_WRITER_MODEL`, `REELSMITH_JUDGE_MODEL`) | Ollama | Apache 2.0 |
| image | Z-Image Turbo | ComfyUI `workflows/keyframe.json` | Apache 2.0 |
| video | Wan 2.2 14B I2V, FP8, lightx2v 4-step LoRAs | ComfyUI `workflows/animate.json` | Apache 2.0 |
| video (draft) | Wan 2.2 TI2V 5B | ComfyUI `workflows/animate-draft.json` (optional) | Apache 2.0 |
| voice | VoxCPM2 | `services/tts` | Apache 2.0 |
| music | ACE-Step 1.5 | ComfyUI `workflows/score.json` | MIT |
| subtitles | faster-whisper large-v3-turbo | worker, CPU | MIT |

The three ComfyUI graphs are exported by hand from the editor once (see
`workflows/README.md`); the worker checks their slots on start and refuses to run if a
title is missing. The draft graph is optional: when it exists, `wan-5b` becomes a video
model you can put in a recipe.

Model names a recipe understands: `z-image`, `wan-2.2`, `wan-5b`. The judge model must
accept images.


## Configuration

Everything is read from `.env` with the prefix `REELSMITH_` (see `src/reelsmith/settings.py`).

| Variable | Default | Description |
| --- | --- | --- |
| `REELSMITH_SERVICES` | local | `synthetic` runs the worker with no models, against the real database |
| `REELSMITH_WRITER_MODEL` | qwen3.5:27b | Ollama tag for the writer and the critic |
| `REELSMITH_JUDGE_MODEL` | qwen3.5:27b | Ollama tag for the judge; must take images |
| `REELSMITH_LANGUAGE` | ru | language of the lines and the subtitles |
| `REELSMITH_VOICE` | narrator | `voices/<name>.wav` + `.txt` for cloning |
| `REELSMITH_WHISPER_MODEL` | large-v3-turbo | subtitle model, runs on CPU |
| `REELSMITH_IMAGE_MODEL` | z-image | default image model of new jobs |
| `REELSMITH_VIDEO_MODEL` | wan-2.2 | default video model of new jobs |
| `REELSMITH_HOOK_VIDEO_MODEL` | | video model for the first `HOOK_SHOTS` shots; empty = same |
| `REELSMITH_HOOK_SHOTS` | 2 | how many leading shots count as the hook |
| `REELSMITH_GPU_HOUR_USD` | 0.99 | what an hour of your card costs; converts GPU seconds to dollars |
| `REELSMITH_BATCH_SIZE` | 6 | jobs claimed per stage per turn |
| `REELSMITH_MAX_ATTEMPTS` | 5 | rewinds and failures before a job is parked |
| `REELSMITH_LEASE_MINUTES` | 45 | how long a claimed job stays invisible to other workers |
| `REELSMITH_IDLE_SECONDS` | 20 | sleep when the queue is empty |
| `REELSMITH_OLLAMA_URL` | http://llm:11434 | |
| `REELSMITH_COMFY_URL` | http://comfy:8188 | |
| `REELSMITH_TTS_URL` | http://tts:8000 | |
| `REELSMITH_DATABASE_URL` | postgresql://…@db:5432/reelsmith | set by compose |
| `REELSMITH_MEDIA_ROOT` | /data/media | per-job files |
| `REELSMITH_OUTBOX` | /data/outbox | finished videos |
| `REELSMITH_WORKFLOWS` | /app/workflows | exported ComfyUI graphs |

Gate thresholds and counts (score 7 / 6 / 7, two rewrites, two candidates, three clip
tries) are constants at the top of `pipeline.py`, not settings: nobody tunes them per
deployment.

A job's recipe is fixed when it is added: `reelsmith add "идея" --video wan-5b
--hook-video wan-2.2` keeps the hook on the big model and the rest on the draft one.
Changing `.env` later does not touch queued jobs.


## Run

    reelsmith migrate                                          # once per database
    reelsmith add "идея" ["идея" ...] [--image M] [--video M] [--hook-video M] [--hook-shots N]
                                      [--experiment X --arm A]
    reelsmith work [--once] [--stages write,voice,...]         # the conveyor
    reelsmith status                                           # jobs per status
    reelsmith approve ID | reject ID [--reason ...] | rate ID 1..10
    reelsmith fork ID [--arm B] [--video M ...]                # arm B on the same frames
    reelsmith measure ID --views N --retention-3s X --completion Y
    reelsmith compare EXPERIMENT                               # arms side by side
    reelsmith report                                           # cost, flags, GPU hours, hooks
    reelsmith demo [--ideas 3] [--arm-a wan-2.2] [--arm-b wan-5b] [--out demo]

Inside compose every command is `docker compose run --rm worker <command>`.

`work --stages` runs a subset of stages in one process so stages can be scaled apart;
the stage names are those in the table above.

An A/B run: add ideas, let the conveyor reach `framed`, fork each job into arm B with
another video model, let both arms finish, rate the cuts blind, publish, enter the
platform's numbers after a day, then `compare <experiment>`. The fork inherits the
parent's script, voices and frames and their cost marked `shared`: `compare` counts it in
both arms, `report` counts it once.


## Testing and linting

    pip install -e ".[dev]"
    make test lint          # pytest, ruff check, ruff format --check, mypy --strict
    make demo               # the whole conveyor on synthetic models, prints the tables

The synthetic models need no weights and no network: scripts come from fixed lines,
frames and clips are colour fills from ffmpeg, voice and music are tones. The judge flags
20 % of clips and rejects 15 % of cuts so the report has something to show. Montage,
subtitles, stills, outbox and the cost ledger are the real code paths.


## Troubleshooting

- Worker refuses to start naming a graph and a slot: re-export that workflow with the
  node titles from `workflows/README.md`.
- `no video model named 'wan-5b'`: `animate-draft.json` is not exported; use `wan-2.2`
  or export the draft graph.
- Job parked as `failed` with `comfy: prompt … did not finish`: the ComfyUI run hit its
  time limit (30 min for a clip); check `make logs` and the card's memory.
- Job parked with `ollama: Script does not match schema`: the writer model ignored the
  JSON schema; pick a larger tag or lower the temperature in `services/ollama.py`.
- Out of memory on the card: the judge model loads next to nothing else only because
  stages alternate; make sure `REELSMITH_JUDGE_MODEL` fits alone and that no other
  process holds the card.
- Cost looks wrong: the seconds per unit in `pricing.py` are research assumptions for an
  RTX 5090; replace them with your own measurements.


## Project status

- Code, gates, cost ledger, CLI and synthetic demo are complete and covered by tests.
- Nothing has run on a GPU yet. Unverified on real hardware: the exported graphs, Qwen3.5
  as a judge of artifacts, VoxCPM2 in Russian, the benchmark seconds in `pricing.py`.
