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
  // The model names a moment by a phrase («за спиной») or by another form of the word
  // («стоят» for «стоит») as often as by the word itself.
  function near(word) {
    for (const part of String(word).split(/\s+/)) {
      const w = said(part, 1);
      if (w) return w;
    }
    const key = bare(String(word).split(/\s+/)[0]);
    let best = null;
    for (const w of words) {
      let same = 0;
      while (same < key.length && same < w.key.length && key[same] === w.key[same]) same++;
      if (same >= 3 && same >= Math.min(key.length, w.key.length) * 0.6 && (!best || same > best[1])) best = [w, same];
    }
    return best?.[0] ?? null;
  }
  function at(word, n = 1) {
    const w = said(word, n) ?? near(word);
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
