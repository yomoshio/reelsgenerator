# Flat structure

Decision of 2026-10-30: Egor asked for a pipeline that is less deep and easier to read, and
for a what-where-how spec in the style of void-deepstream-core's README. This records what
changed and why; the README is the spec.

## What was deep

A stage reached a model through five hops: `Recipe` name → `Providers` accessor → port
`Protocol` → adapter class → HTTP client. Eight stage classes each carried `takes`,
`settled`, `tenant()` and `run()`. Seven exception classes. Three modules (`ports`,
`providers`, `errors`) existed only to connect the others. Tests needed a fake per port
and the demo its own synthetic set with the same names.

## What it is now

    models.py      data and the rules on it (attempts, rewinds, reject, fork)
    pipeline.py    the stages as functions, in order; the Services they need; per-job files
    conveyor.py    claims a batch, holds the card, turns errors into job state
    store.py       Postgres + memory, one Protocol
    pricing.py     GPU seconds per unit, dollars at the rent
    report.py      the numbers
    services/      one file per thing the pipeline talks to
    app.py         builds the service set, wires the conveyor, runs the demo
    cli.py         commands

A stage is `async def paint(job, s: Services)`. `Services` is one dataclass with a field
per thing a stage may call; the two roles that have alternatives (`painters`,
`animators`) are mappings looked up by the recipe's name, everything else is a single
object. The GPU service a stage needs is a column in the `STAGES` table, not resolved
per job. Two exceptions: `StageError` (the job is retried or parked) and `Rewind` (the
job goes back). Writer, critic and judge are one `Llm` interface with five methods,
implemented once for Ollama and once synthetically.

## One behaviour change

The judge used to be called in the middle of the ComfyUI stages (pick after each paint,
inspect after each clip). That meant Ollama loading a 27B model while ComfyUI still held
Wan on the same card. Now `pick` and `check` are stages of their own, so every stage uses
exactly one GPU service and the conveyor's one-model-per-stage rule holds everywhere.
A flagged clip is handled by the same mechanism as a failed QA: drop it, rewind to
`framed`, re-animate only what is missing with the attempt in the seed. A shot gets three
animations at most; after that its clip stays whatever the judge says. `MAX_ATTEMPTS`
default rose from 3 to 5 because clip retries and QA rewinds now share the counter.

Two statuses were added for the new stages: `painted` (candidates exist, none chosen) and
`checked` (clips passed inspection). Per-shot parallelism was removed: one card, and
ComfyUI serialises its queue anyway.

## Unchanged

Recipes, A/B forks with shared cost, the report, the synthetic demo, the Postgres queue
with leases, the ffmpeg cut, the prompts, the ComfyUI slot convention, the tests' intent
(95 tests, ruff, mypy --strict).
