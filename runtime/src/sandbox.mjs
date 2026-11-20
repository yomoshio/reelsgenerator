// Scene code runs in its own context: no require, no process, no eval, a time budget for
// the scene and a smaller one for every draw call. Math.random is seeded again before each
// call, so a scene that scatters stars draws the same stars in every frame.

import vm from "node:vm";
import { rng } from "./places.mjs";
import { ScriptError } from "./places.mjs";

export const SCENE_MS = 2000;
export const DRAW_MS = 250;

export function load(code, seed = 1) {
  let random = rng(seed);
  const math = Object.create(null);
  for (const name of Object.getOwnPropertyNames(Math)) math[name] = Math[name];
  math.random = () => random();
  const context = vm.createContext(
    { Math: Object.freeze(math), console: { log() {} } },
    { codeGeneration: { strings: false, wasm: false } },
  );
  run(context, code, SCENE_MS, "scene.js");
  if (vm.runInContext("typeof scene", context) !== "function") {
    throw new ScriptError("the code must define `function scene(s) { ... }`");
  }
  return {
    run(api) {
      context.__s = api;
      run(context, "scene(__s)", SCENE_MS, "scene.js");
    },
    call(fn, ...args) {
      random = rng(seed);
      context.__f = fn;
      context.__a = args;
      run(context, "__f(...__a)", DRAW_MS, "draw.js");
    },
  };
}

function run(context, code, timeout, filename) {
  try {
    vm.runInContext(code, context, { timeout, filename });
  } catch (exc) {
    if (exc?.code === "ERR_SCRIPT_EXECUTION_TIMEOUT") {
      throw new ScriptError(`${filename === "draw.js" ? "a draw call" : "the scene"} took longer than ${timeout / 1000} s; it must not loop for long`);
    }
    if (exc instanceof ScriptError) throw exc;
    if (exc?.name === "ReferenceError" && /^s is not defined/.test(exc.message)) {
      throw new ScriptError("`s` exists only inside `function scene(s) { ... }`; put the whole scene in that function");
    }
    const where = String(exc?.stack ?? "").match(/scene\.js:(\d+)/);
    throw new ScriptError(`${exc?.name ?? "Error"}: ${exc?.message ?? exc}${where ? ` (line ${where[1]})` : ""}`);
  }
}
