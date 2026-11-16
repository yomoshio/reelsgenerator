// Draws one beat from the JSON on stdin.
//   keys:   PNGs of the moments in `keys` to `<out>-<n>.png`, and a report on stdout
//   frames: seconds × fps raw RGBA frames of 1080×1920 on stdout
//   card:   the closing card of an episode as raw frames
// A report is {"ok", "error", "problems", "pngs", "graph"}.

import { readFileSync, writeSync } from "node:fs";
import { join } from "node:path";
import { Canvas, FontLibrary } from "skia-canvas";
import { H, ScriptError, W } from "./places.mjs";
import { makeStage } from "./stage.mjs";
import { load } from "./sandbox.mjs";
import { FIXTURES, libraryThing } from "./things.mjs";
import { drawCard } from "./plates.mjs";
import { seedOf } from "./places.mjs";

const input = JSON.parse(readFileSync(0, "utf8"));
FontLibrary.use("Plate", [input.fonts.plate]);
const canvas = new Canvas(W, H);
const ctx = canvas.getContext("2d");

function out(report) {
  process.stdout.write(JSON.stringify(report) + "\n");
}

function frame(n) {
  writeSync(1, canvas.toBufferSync("raw"));
}

if (input.mode === "card") {
  const total = Math.round(input.seconds * input.fps);
  for (let n = 0; n < total; n++) {
    drawCard(ctx, n / input.fps, input.card, input.palette);
    frame(n);
  }
  process.exit(0);
}

async function libraryFor(names) {
  const found = {};
  for (const name of names) {
    if (FIXTURES[name]) continue;
    const file = join(input.library, `${name}.svg`);
    try {
      found[name] = await libraryThing(name, file, input.palette.steel ?? "#68727F");
    } catch {
      // an unknown thing is reported when the scene asks for it
    }
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

try {
  const library = await libraryFor(input.beat.staging?.things ?? []);
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
  out({ ok: problems.size === 0, error: null, problems: [...problems], pngs, graph });
} catch (exc) {
  if (input.mode === "frames") {
    process.stderr.write(String(exc?.message ?? exc) + "\n");
    process.exit(2);
  }
  const known = exc instanceof ScriptError;
  out({ ok: false, error: known ? exc.message : `${exc?.name}: ${exc?.message}`, problems: [], pngs: [], graph: [] });
}
