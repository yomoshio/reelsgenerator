import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CARD, input, run } from "./helpers.mjs";

test("a clean scene passes and leaves a PNG per key", () => {
  const r = run(input(`function scene(s) {
    s.place("room");
    const bed = s.thing("bed", { x: 0.3 });
    const a = s.person("artem", { x: 0.6 });
    a.sit(bed, { at: "сидит" });
    a.look("right", { at: "слушает" });
  }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
  assert.equal(r.pngs.length, 3);
  assert.equal(readFileSync(r.pngs[0]).subarray(1, 4).toString(), "PNG");
});

test("an unknown cue word lists the words of the beat", () => {
  const r = run(input(`function scene(s) { s.person("artem").pose("point", { at: "самолёт" }); }`));
  assert.match(r.error, /no word «самолёт».*Артём сидит на кровати/);
});

test("a cast member the scene never places is a problem", () => {
  const data = input(`function scene(s) { s.place("room"); s.person("artem").pose("listen", { at: "слушает" }); }`);
  data.beat.cast = ["artem", "lena"];
  data.characters.push({ key: "lena", name: "Лена", look: "", card: { ...CARD, age: "child" } });
  assert.ok(run(data).problems.some((p) => /lena never appears/.test(p)));
});

test("a thing the staging names but the scene leaves out is a problem", () => {
  const data = input(`function scene(s) { s.place("room"); s.person("artem").pose("listen", { at: "слушает" }); }`);
  data.beat.staging.things = ["atm"];
  assert.ok(run(data).problems.some((p) => /never places them/.test(p)));
});

test("a still scene longer than five seconds is a problem", () => {
  const r = run(input(`function scene(s) { s.place("room"); s.person("artem"); }`, { seconds: 6 }));
  assert.ok(r.problems.some((p) => /nothing moves/.test(p)));
});

test("two things put in the same spot are a problem", () => {
  const r = run(input(`function scene(s) { s.place("room"); s.thing("atm", { x: 0.3 }); s.thing("shelf", { x: 0.32 });
    s.person("artem", { x: 0.7 }).pose("point", { at: "слушает" }); }`));
  assert.ok(r.problems.some((p) => /stand inside each other/.test(p)));
});

test("an unknown thing suggests close names", () => {
  const r = run(input(`function scene(s) { s.thing("atmachine"); }`));
  assert.match(r.error, /no thing 'atmachine'; did you mean atm/);
});

test("the lens shows the scene, not an empty disc", () => {
  const data = input(`function scene(s) { s.place("shop"); const atm = s.thing("atm", { x: 0.3 }); atm.state(2, { at: "сидит" });
    s.person("artem", { x: 0.7 }).point(atm, { at: "слушает" }); s.device("lens", { on: atm.part("screen"), at: 1 }); }`);
  data.keys = [4.5];
  assert.equal(run(data).ok, true);
});

test("every card value draws", () => {
  const values = {
    age: ["child", "teen", "adult", "old"], build: ["slim", "heavy"], hair: ["long", "bun", "braids", "bald", "curly", "ponytail", "cap"],
    top: ["shirt", "sweater", "jacket", "coat", "dress", "gown", "uniform", "apron"], bottom: ["skirt", "long_skirt", "shorts"],
    hat: ["cap", "top_hat", "bonnet", "kerchief"],
  };
  for (const [field, list] of Object.entries(values))
    for (const value of list) {
      const data = input(`function scene(s) { s.place("room"); s.person("artem").pose("point", { at: "слушает" }); }`);
      data.characters[0].card = { ...CARD, [field]: value, face: ["beard", "mustache", "glasses", "freckles"], extras: ["necklace", "scarf", "bag", "torch"] };
      data.keys = [3];
      assert.equal(run(data).error, null, `${field}=${value}`);
    }
});

test("frames come out as raw RGBA of the beat's length", () => {
  const data = input(`function scene(s) { s.place("room"); s.person("artem").walk({ to: 0.8, at: "сидит" }); }`, { mode: "frames", seconds: 0.5 });
  const r = run(data);
  assert.equal(r.status, 0);
  assert.equal(r.stdout.length, 15 * 1080 * 1920 * 4);
});

test("a small thing stands on a table, not inside it", () => {
  const r = run(input(`function scene(s) { s.place("room"); const t = s.thing("table", { x: 0.3 });
    s.thing("lamp", { x: 0.3 }); s.thing("chair", { on: t, scale: 0.4 });
    s.person("artem", { x: 0.7 }).point(t, { at: "слушает" }); }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
  const items = r.graph[0].items;
  const table = items.find((i) => i.id === "table"), chair = items.find((i) => i.id === "chair");
  assert.ok(Math.abs(chair.box[1] + chair.box[3] - table.box[1]) < 2);
});

test("nothing stands on a thing without a top", () => {
  const r = run(input(`function scene(s) { const d = s.thing("door"); s.thing("chair", { on: d }); }`));
  assert.match(r.error, /nothing can stand on 'door'/);
});

test("a person walks to a thing and to another person", () => {
  const data = input(`function scene(s) {
    s.place("room");
    const door = s.thing("door", { x: 0.85 });
    const a = s.person("artem", { x: 0.2 });
    const l = s.person("lena", { x: 0.55 });
    a.walk({ to: l, at: "сидит" });
    l.walk({ to: door, at: "слушает" });
  }`);
  data.beat.cast = ["artem", "lena"];
  data.characters.push({ key: "lena", name: "Лена", look: "", card: CARD });
  const r = run(data);
  assert.equal(r.error, null);
  const x = (id) => { const b = r.graph.at(-1).items.find((i) => i.id === id).box; return b[0] + b[2] / 2; };
  assert.ok(x("artem") > 300 && x("artem") < x("lena"), "artem did not come up to lena");
  assert.ok(x("lena") > 700 && x("lena") < x("door"), "lena did not come up to the door");
});

for (const [what, code, says] of [
  ["a guessed method of the stage", `function scene(s) { s.place("room"); s.push({ zoom: 1.1 }); }`, /s has no `push`; it has: .*camera/],
  ["a guessed method of a person", `function scene(s) { s.person("artem").sits(); }`, /artem has no `sits`; it has: .*sit/],
  ["a guessed option", `function scene(s) { s.person("artem", { x: 0.4, y: 0.1, face: "left" }); }`, /no option `y`, `face`; its options: x, facing/],
  ["a reach at nothing", `function scene(s) { s.person("artem").reach(undefined, { at: 1 }); }`, /artem\.reach needs a target/],
  ["code outside the scene function", `s.place("room");\nfunction scene(s) {}`, /only inside `function scene/],
]) {
  test(`${what} is answered with what exists`, () => {
    assert.match(run(input(code)).error, says);
  });
}

test("a person who enters is not on stage before the word", () => {
  const data = input(`function scene(s) {
    s.place("room");
    const a = s.person("artem", { x: 0.5 });
    a.enter({ from: "right", at: "воду" });
  }`);
  const r = run(data);
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
  assert.equal(r.graph[0].items.some((i) => i.id === "artem"), false);
  assert.equal(r.graph.at(-1).items.some((i) => i.id === "artem"), true);
});

test("a person still walking in from off the frame is not a problem", () => {
  const r = run(input(`function scene(s) {
    s.place("room");
    s.person("artem", { x: 0.5 }).enter({ from: "right", at: "Артём" });
  }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
});
