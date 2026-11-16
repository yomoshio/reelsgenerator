import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
export const PALETTE = {
  night: "#0E131D", wall: "#283245", floor: "#131823", line: "#2E394E", light: "#C4D4EC",
  ink: "#1A1A1A", neutral: "#ECE8DE", threat: "#C8382D", key: "#F2C230", solved: "#2E9E5B",
  steel: "#68727F", water: "#346880", warm: "#FFD696",
};
export const CARD = {
  age: "adult", build: "average", skin: "light", hair: "short", hair_colour: "#1E1B1C", face: [],
  top: "raincoat", top_colour: "#2E4670", bottom: "trousers", bottom_colour: "#1C2130",
  shoes_colour: "#101218", hat: "none", extras: [],
};
const WORDS = "Артём сидит на кровати и слушает воду внизу".split(" ");

export function input(code, extra = {}) {
  const out = join(mkdtempSync(join(tmpdir(), "rt-")), "k");
  return {
    mode: "keys", code,
    beat: { place: "flat", cast: ["artem"], lines: [WORDS.join(" ")], delivery: "", reveals: [],
            staging: { shot: "wide", action: "", devices: [], things: [], questions: ["?"] } },
    place: { key: "flat", name: "Квартира", look: "", kind: "room" },
    characters: [{ key: "artem", name: "Артём", look: "", card: CARD }],
    palette: PALETTE, fonts: { plate: join(ROOT, "fonts", "Montserrat-ExtraBold.ttf") },
    words: WORDS.map((w, i) => ({ text: w, start: 0.2 + i * 0.5, end: 0.6 + i * 0.5 })),
    seconds: 5, fps: 30, keys: [0.5, 2.5, 4.6], out, library: join(ROOT, "..", "library", "things"),
    carried: [], ...extra,
  };
}

export function run(data, args = []) {
  const r = spawnSync("node", ["--max-old-space-size=256", ...args, join(ROOT, "src", "run.mjs")], {
    input: JSON.stringify(data), maxBuffer: 1 << 30, timeout: 60000,
  });
  if (data.mode === "keys") {
    const text = r.stdout.toString().trim();
    return text ? JSON.parse(text.split("\n").pop()) : { ok: false, error: `exit ${r.status}: ${r.stderr}` };
  }
  return r;
}
