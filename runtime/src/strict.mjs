// A model that writes scene code guesses names: `s.push`, `artem.sits`, `{ face: "left" }`.
// Plain JavaScript answers a guess with "undefined is not a function", which tells the
// model nothing; these answer with the names that do exist.

import { ScriptError } from "./places.mjs";

const QUIET = new Set(["ref", "kind", "spec", "then", "toJSON", "constructor"]); // the runtime and the engine probe these

export function strict(target, name) {
  return new Proxy(target, {
    get(o, key) {
      if (typeof key === "symbol" || key in o || QUIET.has(key)) return o[key];
      const has = Object.keys(o).filter((k) => !k.startsWith("__") && k !== "id");
      throw new ScriptError(`${name} has no \`${key}\`; it has: ${has.join(", ")}`);
    },
  });
}

export function options(opts, known, name) {
  if (opts === null || typeof opts !== "object") throw new ScriptError(`${name} takes its options as an object, such as { ${known[0]}: ... }`);
  const extra = Object.keys(opts).filter((k) => !known.includes(k));
  if (extra.length) throw new ScriptError(`${name} has no option \`${extra.join("`, `")}\`; its options: ${known.join(", ")}`);
}
