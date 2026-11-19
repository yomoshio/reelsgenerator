// When things happen in a beat: a moment is a number of seconds or a word the narrator says.

import { ScriptError } from "./places.mjs";

export const bare = (w) => String(w).toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]/gu, "");

export function makeClock(spoken, seconds) {
  const words = spoken.map((w) => ({ ...w, key: bare(w.text) }));

  function said(word, n) {
    const key = bare(word);
    let seen = 0;
    for (const w of words) if (w.key === key && ++seen === n) return w;
    return null;
  }
  function at(word, n = 1) {
    const w = said(word, n);
    if (w) return w.start;
    const heard = words.map((w) => w.text).join(" ");
    throw new ScriptError(`no word «${word}»${n > 1 ? ` said ${n} times` : ""} in this beat; its words are: ${heard}`);
  }
  function time(x, fallback = 0) {
    if (x === undefined || x === null) return fallback;
    if (typeof x === "number") return Math.min(Math.max(x, 0), seconds);
    if (typeof x === "string") return at(x);
    if (typeof x === "object" && x.word) return at(x.word, x.n ?? 1);
    throw new ScriptError(`a time is a number of seconds or a word of the beat, not ${JSON.stringify(x)}`);
  }
  // A reveal whose word is not in the beat shows from the start.
  function revealTime(r) {
    const w = said(r.on_word, r.occurrence ?? 1);
    return w ? w.start : 0;
  }

  return { at, time, revealTime };
}
