// skia-canvas 2.0 draws roundRect in screen space, ignoring the transform, so a rounded
// frame under a rotation or a camera move lands somewhere else. This one is built from arcs,
// which follow the transform; importing the module replaces the broken one everywhere,
// in scene code a model writes too.

import { CanvasRenderingContext2D } from "skia-canvas";

CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, radius = 0) {
  if (w < 0) [x, w] = [x + w, -w];
  if (h < 0) [y, h] = [y + h, -h];
  const r = Math.max(0, Math.min(Array.isArray(radius) ? (radius[0] ?? 0) : radius, w / 2, h / 2));
  this.moveTo(x + r, y);
  this.arcTo(x + w, y, x + w, y + h, r);
  this.arcTo(x + w, y + h, x, y + h, r);
  this.arcTo(x, y + h, x, y, r);
  this.arcTo(x, y, x + w, y, r);
  this.closePath();
};
