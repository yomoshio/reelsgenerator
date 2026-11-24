You draw one small thing for a flat vector animation, as a JavaScript arrow function on an
HTML canvas. The thing is seen from the side, lit warmly from one side, in two to four flat
colours with a darker outline.

Rules:

- Answer with the function only, in one ```js block: `(ctx, t) => { ... }`.
- Draw inside a box 70 wide and 70 tall whose middle is 0,0: x and y from -35 to 35.
- Use only canvas calls: fillStyle, strokeStyle, lineWidth, beginPath, moveTo, lineTo,
  quadraticCurveTo, bezierCurveTo, arc, ellipse, rect, fillRect, closePath, fill, stroke,
  save, restore, translate, rotate. No text, no images, no loops over time.
- Six to twenty lines. Make the silhouette say what the thing is: a paw has a palm and
  fingers, a letter is a folded sheet with a seal, a key has a ring and a bit.

An example, a dried monkey's paw:

```js
(ctx, t) => {
  ctx.fillStyle = "#5A4630"; ctx.strokeStyle = "#2B2016"; ctx.lineWidth = 2.5;
  ctx.beginPath(); ctx.ellipse(0, 12, 16, 20, 0, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  for (let i = -2; i <= 2; i++) {
    ctx.save(); ctx.translate(i * 7, -6); ctx.rotate(i * 0.16);
    ctx.beginPath(); ctx.rect(-3, -26, 6, 26); ctx.fill(); ctx.stroke();
    ctx.restore();
  }
  ctx.fillStyle = "#3B2D1E"; ctx.fillRect(-9, 28, 18, 6);
}
```
