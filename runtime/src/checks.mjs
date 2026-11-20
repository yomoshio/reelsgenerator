// What the scene's code got wrong without looking at a frame.

export function declared(decl, input, known = () => true) {
  const found = [];
  const seconds = input.seconds;
  const placed = new Set(decl.people.map((q) => q.key));
  const missing = input.beat.cast.filter((key) => !placed.has(key));
  if (missing.length) found.push(`the beat's cast ${missing.join(", ")} never appears; put every one of them on stage with s.person`);
  const staged = new Set(decl.things.map((q) => q.name));
  const absent = (input.beat.staging?.things ?? []).filter((n) => known(n) && !staged.has(n));
  if (absent.length) found.push(`the staging puts ${absent.join(", ")} in this place, but the scene never places them; add them with s.thing`);
  if (seconds >= 5 && decl.events === 0) found.push(`nothing moves or changes in ${seconds.toFixed(1)} s; make something happen on the narrator's words`);
  // A plate pinned to what the story names but the stage cannot draw is laid free; only a
  // target the scene could have placed and did not is the coder's to fix.
  for (const r of input.beat.reveals) {
    const placeable = input.beat.cast.includes(r.target) || known(r.target);
    if (r.target && placeable && !decl.people.some((q) => q.key === r.target) && !decl.things.some((q) => q.name === r.target))
      found.push(`the plate '${r.text}' is pinned to '${r.target}', which the scene never places`);
  }
  return found;
}
