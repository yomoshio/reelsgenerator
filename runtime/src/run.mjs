// Draws one beat from the JSON on stdin.
//   keys:   PNGs of the moments in `keys` to `<out>-<n>.png`, and a report on stdout
//   frames: seconds × fps raw RGBA frames of 1080×1920 on stdout
//   card:   the closing card of an episode as raw frames
// A report is {"ok", "error", "problems", "pngs", "graph"}.

import { readFileSync, readdirSync, writeSync } from "node:fs";
import { join } from "node:path";
import { Canvas, FontLibrary } from "skia-canvas";
import { H, ScriptError, W } from "./places.mjs";
import { makeStage } from "./stage.mjs";
import { load } from "./sandbox.mjs";
import { FIXTURES, artThing, libraryThing } from "./things.mjs";
import { drawCard } from "./plates.mjs";
import { seedOf } from "./places.mjs";

const input = JSON.parse(readFileSync(0, "utf8"));
FontLibrary.use("Plate", [input.fonts.plate]);
const canvas = new Canvas(W, H);
const ctx = canvas.getContext("2d");

function out(report) {
  process.stdout.write(JSON.stringify(report) + "\n");
}

// The canvas keeps every drawing command since it was made and replays them all for each
// frame it hands out: a beat of 400 frames drew slower and slower. Each frame starts clean.
function frame(n) {
  writeSync(1, canvas.toBufferSync("raw"));
  ctx.reset();
}

if (input.mode === "card") {
  const total = Math.round(input.seconds * input.fps);
  for (let n = 0; n < total; n++) {
    drawCard(ctx, n / input.fps, input.card, input.palette);
    frame(n);
  }
  process.exit(0);
}

// The library thing a name means: the file of that name, or the shortest name that holds
// every word of it, so `phone` finds `smartphone` and `walkie-talkie` finds `walkie_talkie`.
function libraryFile(name, all) {
  const wanted = name.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  if (all.includes(wanted)) return wanted;
  const parts = wanted.split("_").filter((q) => q.length > 2);
  if (!parts.length) return null;
  const close = all.filter((k) => parts.every((q) => k.includes(q)));
  return close.sort((a, b) => a.length - b.length || a.localeCompare(b))[0] ?? null;
}

async function libraryFor(names) {
  const found = {};
  let all = [];
  try {
    all = readdirSync(input.library).filter((f) => f.endsWith(".svg")).map((f) => f.slice(0, -4));
  } catch {
    // no library on this machine: only the runtime's own things exist
  }
  for (const name of new Set(names)) {
    if (FIXTURES[name]) continue;
    const file = libraryFile(name, all);
    if (!file) continue; // an unknown thing is reported when the scene asks for it
    found[name] = await libraryThing(name, join(input.library, `${file}.svg`), input.palette.steel ?? "#68727F");
  }
  return found;
}

function luminance() {
  const data = ctx.getImageData(0, 180, W, 970).data;
  let sum = 0, n = 0;
  for (let i = 0; i < data.length; i += 4 * 97) {
    sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    n++;
  }
  return sum / n;
}

// Things drawn by an artist take the place of the runtime's own of the same name, when the
// input asks for them with `art: true`. What burns or lights the room stays the runtime's:
// a picture has no states.
async function art() {
  if (!input.art) return;
  const dir = join(input.library, "..", "art");
  let index = {};
  try {
    index = JSON.parse(readFileSync(join(dir, "index.json"), "utf8"));
  } catch {
    return;
  }
  for (const [name, meta] of Object.entries(index)) if (!FIXTURES[name]?.glow) FIXTURES[name] = await artThing(join(dir, `${name}.svg`), meta);
}

try {
  await art();
  const asked = [...input.code.matchAll(/thing\(\s*["'`]([^"'`]+)["'`]/g)].map((m) => m[1].replace(/#\d+$/, ""));
  const library = await libraryFor([...(input.beat.staging?.things ?? []), ...asked]);
  const stage = makeStage(input, library);
  stage.run(load(input.code, seedOf(input.place.key)));
  if (input.mode === "frames") {
    const total = Math.round(input.seconds * input.fps);
    for (let n = 0; n < total; n++) {
      stage.render(ctx, n / input.fps);
      frame(n);
    }
    process.exit(0);
  }
  const problems = new Set(stage.declared());
  const pngs = [];
  const graph = [];
  for (const [n, t] of input.keys.entries()) {
    const drawn = stage.render(ctx, t);
    const path = `${input.out}-${n}.png`;
    await canvas.saveAs(path, { format: "png" });
    pngs.push(path);
    graph.push({ t, items: drawn.items, plates: drawn.plates });
    for (const p of stage.frameProblems({ t, ...drawn, luminance: luminance() })) problems.add(p);
  }
  out({ ok: problems.size === 0, error: null, problems: [...problems], pngs, graph, ignored: stage.ignored() });
} catch (exc) {
  if (input.mode === "frames") {
    process.stderr.write(String(exc?.message ?? exc) + "\n");
    process.exit(2);
  }
  const known = exc instanceof ScriptError;
  out({ ok: false, error: known ? exc.message : `${exc?.name}: ${exc?.message}`, problems: [], pngs: [], graph: [] });
}
