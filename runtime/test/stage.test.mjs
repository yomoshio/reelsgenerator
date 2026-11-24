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

test("of two things put in the same spot the later one steps aside", () => {
  const r = run(input(`function scene(s) { s.place("room"); s.thing("atm", { x: 0.3 }); s.thing("shelf", { x: 0.32 });
    s.person("artem", { x: 0.7 }).pose("point", { at: "слушает" }); }`));
  assert.deepEqual(r.problems, []);
  const [atm, shelf] = ["atm", "shelf"].map((id) => r.graph[0].items.find((i) => i.id === id).box);
  assert.ok(shelf[0] >= atm[0] + atm[2] * 0.5);
});

test("a thing nobody can draw is left out with all that is done to it", () => {
  const r = run(input(`function scene(s) { const x = s.thing("atmachine"); x.state(1, { at: "воду" }); s.person("artem").reach(x.part("screen"), { at: "воду" }); }`));
  assert.equal(r.error, null);
  assert.ok(r.ignored.includes('s.thing("atmachine")'));
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

test("a thing put on one without a top hangs on its middle", () => {
  const r = run(input(`function scene(s) { s.place("room"); const d = s.thing("door", { x: 0.7 }); s.thing("chair", { on: d });
    s.person("artem", { x: 0.3 }).pose("point", { at: "слушает" }); }`));
  assert.equal(r.error, null);
  const [door, chair] = ["door", "chair"].map((id) => r.graph[0].items.find((i) => i.id === id).box);
  assert.ok(chair[1] + chair[3] < door[1] + door[3] - 50 && chair[1] + chair[3] > door[1]);
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

for (const [what, code, left] of [
  ["a guessed method of the stage", `function scene(s) { s.place("room"); s.plate("ОШИБКА").at("воду"); }`, "s.plate"],
  ["a guessed method of a person", `function scene(s) { s.person("artem").shout({ at: "воду" }).pose("point"); }`, "artem.shout"],
  ["a guessed option", `function scene(s) { s.person("artem", { x: 0.4, y: 0.1 }); }`, 's.person("artem") option y'],
  ["a guessed pose", `function scene(s) { s.person("artem").pose("juggle", { at: "воду" }); }`, "pose juggle"],
  ["a guessed device", `function scene(s) { s.person("artem"); s.device("stamp", { text: "x" }); }`, 's.device("stamp")'],
]) {
  test(`${what} is left out and the rest is drawn`, () => {
    const r = run(input(code));
    assert.equal(r.error, null);
    assert.ok(r.ignored.includes(left), r.ignored.join("; "));
  });
}

test("a moment is found by a phrase or by another form of the word", () => {
  const r = run(input(`function scene(s) { const a = s.person("artem"); a.pose("point", { at: "слушает воду" }); a.pose("listen", { at: "кроватью" }); }`));
  assert.equal(r.error, null);
});

test("a name outside the cast is somebody in the crowd, and a crowd may stand close", () => {
  const r = run(input(`function scene(s) { s.place("shop"); s.person("artem", { x: 0.2 }).pose("point", { at: "воду" });
    for (let i = 0; i < 4; i++) s.person("queue" + i, { x: 0.5 + i * 0.02 }); }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
  assert.equal(r.graph[0].items.filter((i) => i.extra).length, 4);
});

test("a person told to sit on nothing takes the nearest seat", () => {
  const r = run(input(`function scene(s) { s.place("room"); const t = s.thing("table", { x: 0.3 }); s.thing("chair", { x: 0.6 });
    s.person("artem", { x: 0.5 }).sit(t, { at: "сидит" }); }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
});

test("a thing put on a person is in their hand and goes with them", () => {
  const data = input(`function scene(s) { s.place("room"); const a = s.person("artem", { x: 0.3 });
    s.thing("chair", { on: a }); a.walk({ to: 0.7, at: "сидит" }); }`);
  const r = run(data);
  assert.equal(r.error, null);
  assert.deepEqual(r.problems, []);
  const at = (g) => ["artem", "chair"].map((id) => g.items.find((i) => i.id === id).box);
  const [[p0, c0], [p1, c1]] = [at(r.graph[0]), at(r.graph.at(-1))];
  assert.ok(c0[3] <= 95 && Math.abs(c0[0] - p0[0]) < 250);
  assert.ok(c1[0] - c0[0] > 200 && Math.abs(c1[0] - p1[0]) < 250);
});

test("a reach at oneself and arithmetic on a handle do not crash the scene", () => {
  const r = run(input(`function scene(s) { s.place("room"); const a = s.person("artem", { x: 0.4 });
    a.reach(a, { at: "воду" }); const ghost = s.thing("nowhere");
    s.draw((ctx) => ctx.fillRect(a.x * 1080 + ghost.x * 2, 900, 10, 10)); s.camera.push({ to: [a.x + 0.05, 0.6], at: "воду" }); }`));
  assert.equal(r.error, null);
});

test("a feeling asked as a pose or as a mood shows on the face", () => {
  const r = run(input(`function scene(s) { s.place("room"); const a = s.person("artem", { mood: "worried" });
    a.pose("smile", { at: "сидит" }); a.mood("scared", { at: "воду" }); a.mood("glum", { at: "внизу" }); }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.ignored, ["mood glum"]);
});

test("a thing or a person as a target is the thing or the person, not the floor under it", () => {
  const data = input(`function scene(s) { s.place("room"); const d = s.thing("door", { x: 0.8 }); s.person("artem", { x: 0.3 });
    s.camera.push({ to: d, at: 0, until: 0.2, zoom: 2 }); }`);
  data.keys = [3];
  const door = run(data).graph[0].items.find((i) => i.id === "door").screen;
  assert.ok(door[1] < 400 && door[1] + door[3] > 1000, JSON.stringify(door));
});

const CARRY = `function scene(s) {
  s.place("room");
  const table = s.thing("table", { x: 0.5 });
  const a = s.person("artem", { x: 0.25 });
  const b = s.person("lena", { x: 0.75, facing: "left" });
  const paw = s.prop("monkey_paw", { size: 70, draw: (ctx) => { ctx.fillStyle = "#6B4A2E"; ctx.fillRect(-20, -30, 40, 60); } });
  BODY
}`;
function carry(body, keys) {
  const data = input(CARRY.replace("BODY", body), { seconds: 5, keys });
  data.beat.cast = ["artem", "lena"];
  data.characters.push({ key: "lena", name: "Лена", look: "", card: CARD });
  const r = run(data);
  assert.equal(r.error, null);
  assert.deepEqual(r.ignored, []);
  return r.graph.map((g) => g.items.find((i) => i.id === "monkey_paw"));
}

test("a prop out of a pocket is unseen, then in the hand, then on the table where it stays", () => {
  const [hidden, inHand, onTable, later] = carry(
    `a.take(paw, { from: "pocket", at: 1 }); a.put(paw, { on: table, at: 2 });`, [0.5, 1.6, 3.2, 4.5]);
  assert.equal(hidden, undefined);
  assert.equal(inHand.on, "hand");
  assert.equal(onTable.on, "thing");
  assert.deepEqual(onTable.box, later.box);
});

test("a thing given ends in the other hand, thrown it flies, dropped it lies on the floor", () => {
  const [mine, theirs, flying, lying] = carry(
    `a.take(paw, { from: "pocket", at: 0 }); a.give(paw, { to: b, at: 1 }); b.throw(paw, { to: 0.4, at: 2.5 }); `, [0.6, 2.2, 2.95, 4.5]);
  assert.ok(mine.box[0] < 540 && theirs.box[0] > 540);
  assert.ok(flying.box[1] < (theirs.box[1] + lying.box[1]) / 2 - 60);
  assert.ok(lying.box[1] > theirs.box[1] + 200);
});

test("a thing thrown into the fire is gone, and two people who look at each other do not loop", () => {
  const [gone] = carry(
    `const fire = s.thing("fireplace", { x: 0.9 }); a.look(b); b.look(a); a.take(paw, { from: "pocket", at: 0 }); a.throw(paw, { to: fire, at: 1 });`, [3]);
  assert.equal(gone, undefined);
});

test("a fire is drawn by the runtime under the names a model gives it, and takes a state", () => {
  const r = run(input(`function scene(s) {
    s.place("room"); s.light(0.3);
    const fire = s.thing("fire", { x: 0.7 });
    fire.state(3, { at: 1 }); fire.state(0, { at: 3 });
    s.person("artem", { x: 0.3 }).look(fire.part("hearth"));
  }`));
  assert.equal(r.error, null);
  assert.deepEqual(r.ignored, []);
  assert.ok(r.graph[0].items.some((i) => i.id === "fireplace"));
});

test("a full room keeps its furniture in a row and nobody stands before the fire or the door", () => {
  const r = run(input(`function scene(s) {
    s.place("room");
    s.thing("fireplace", { x: 0.3 }); s.thing("table", { x: 0.4 }); s.thing("door", { x: 0.5 });
    s.thing("door");
    s.person("artem", { x: 0.3 }).pose("listen", { at: "слушает" });
  }`));
  assert.equal(r.error, null);
  const of = (id) => r.graph[0].items.find((i) => i.id === id).box;
  const [fire, table, door, artem] = ["fireplace", "table", "door", "artem"].map(of);
  assert.ok(!r.graph[0].items.some((i) => i.id === "door#2"));
  assert.ok(fire[0] + fire[2] * 0.9 <= table[0] + 1 && table[0] + table[2] * 0.9 <= door[0] + 1);
  const mid = artem[0] + artem[2] / 2;
  for (const b of [fire, door]) assert.ok(mid < b[0] + 20 || mid > b[0] + b[2] - 20);
});

test("a hand pointed at the thing it holds does not loop", () => {
  const [held] = carry(`a.take(paw, { from: "pocket", at: 0 }); a.point(paw, { at: 1 }); a.reach(paw, { at: 2 });`, [3]);
  assert.equal(held.on, "hand");
});
