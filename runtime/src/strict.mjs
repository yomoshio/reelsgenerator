// A model that writes scene code guesses names: `s.plate`, `artem.shout`, `{ y: 0.4 }`.
// Telling it so did not help: it sent the same guess back round after round. A guess is
// now left out and written down, and the rest of the scene is drawn.

const QUIET = new Set(["ref", "kind", "spec", "then", "toJSON", "constructor"]); // the runtime and the engine probe these

// Swallows any chain of calls: s.plate("...").at("слово").
export const nothing = new Proxy(function () {}, {
  get: (o, key) => (typeof key === "symbol" ? undefined : nothing),
  apply: () => nothing,
});

export function strict(target, name, ignored = []) {
  return new Proxy(target, {
    get(o, key) {
      if (typeof key === "symbol" || key in o || QUIET.has(key)) return o[key];
      ignored.push(`${name}.${key}`);
      return nothing;
    },
  });
}

export function options(opts, known, name, ignored = []) {
  if (opts === null || typeof opts !== "object") return {};
  for (const k of Object.keys(opts)) if (!known.includes(k)) ignored.push(`${name} option ${k}`);
  return opts;
}
