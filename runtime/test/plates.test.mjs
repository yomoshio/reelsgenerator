import { test } from "node:test";
import assert from "node:assert/strict";
import { Canvas, loadImage } from "skia-canvas";
import "../src/canvas.mjs";
import { input, run } from "./helpers.mjs";

test("a rounded frame follows the transform", () => {
  const ctx = new Canvas(400, 400).getContext("2d");
  ctx.translate(200, 200);
  ctx.rotate(0.3);
  ctx.fillStyle = "#f00";
  ctx.beginPath();
  ctx.roundRect(-20, -20, 40, 40, 4);
  ctx.fill();
  const red = (x, y) => ctx.getImageData(x, y, 1, 1).data[0];
  assert.equal(red(200, 200), 255);
  assert.equal(red(10, 10), 0);
});

async function reds(png, [x, y, w, h]) {
  const image = await loadImage(png);
  const ctx = new Canvas(image.width, image.height).getContext("2d");
  ctx.drawImage(image, 0, 0);
  const data = ctx.getImageData(x, y, w, h).data;
  let n = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] > 150 && data[i + 1] < 90 && data[i + 2] < 90) n++;
  return n;
}

test("a stamp stays in the frame and off the person in the middle", async () => {
  const data = input(`function scene(s) {
    s.place("room");
    const a = s.person("artem", { x: 0.5 });
    a.look("right", { at: "слушает" });
  }`);
  data.beat.reveals = [{ on_word: "Артём", kind: "stamp", text: "лифта больше нет совсем", target: "", tone: "threat" }];
  const r = run(data);
  assert.equal(r.error, null);
  const last = r.pngs.at(-1);
  assert.equal(await reds(last, [440, 620, 200, 300]), 0, "the stamp lies on the person");
  assert.ok((await reds(last, [60, 200, 960, 300])) > 2000, "the stamp is not above the person");
  assert.equal(await reds(last, [0, 180, 12, 970]) + await reds(last, [1068, 180, 12, 970]), 0, "the stamp runs off the frame");
});
