import { test } from "node:test";
import assert from "node:assert/strict";
import { input, run } from "./helpers.mjs";

const scene = (body) => `function scene(s) { s.place("room"); const a = s.person("artem", { x: 0.5 }); ${body} }`;

test("a scene that loops forever is stopped with a reason", () => {
  const r = run(input(scene("while (true) {}")));
  assert.match(r.error, /took longer than 2 s/);
});

test("scene code has no require and no process", () => {
  assert.match(run(input(scene("require('fs')"))).error, /require is not defined/);
  assert.match(run(input(scene("process.exit(1)"))).error, /process is not defined/);
});

test("text drawn by scene code is left out, plates draw the text", () => {
  const r = run(input(scene("s.draw((ctx) => ctx.fillText('x', 0, 0));")));
  assert.equal(r.error, null);
});

test("a syntax error names its line", () => {
  const r = run(input("function scene(s) {\n  s.place('room');\n  const = 1;\n}"));
  assert.match(r.error, /SyntaxError/);
});

test("code without a scene function is refused", () => {
  assert.match(run(input("const x = 1;")).error, /function scene\(s\)/);
});

test("a scene that eats memory ends with an error, not a hang", () => {
  const r = run(input(scene("const a = []; for (let i = 0; i < 1e9; i++) a.push(new Array(1e5).fill(i));")));
  assert.equal(r.ok, false);
  assert.ok(r.error);
});
