// The light of a scene: its level at a moment, the darkness that level lays over the set,
// torch beams through it, and the vignette every frame gets.

import { H, W, alpha } from "./places.mjs";
import { ease } from "./rig.mjs";

export function lightAt(lights, t) {
  let level = 1, flicker = false;
  for (const l of lights) {
    if (t < l.t) continue;
    level += (l.level - level) * ease((t - l.t) / 0.5);
    flicker = l.flicker && (l.until === null || t < l.until);
  }
  if (flicker) level *= 0.55 + 0.45 * Math.max(0, Math.sin(t * 9.1) * Math.sin(t * 3.7 + 1.3));
  return level;
}

// `bonesOf(person, t)` gives the bones a torch beam starts from.
export function darkness(ctx, t, lights, people, p, bonesOf) {
  const level = lightAt(lights, t);
  if (level >= 0.999) return;
  ctx.save();
  ctx.fillStyle = `rgba(4,6,10,${(1 - level) * 0.85})`;
  ctx.fillRect(-W, -H, 3 * W, 3 * H);
  for (const pr of people.filter((q) => (q.card.extras ?? []).includes("torch"))) {
    const b = bonesOf(pr, t);
    const f = b.facing;
    ctx.save();
    ctx.filter = "blur(26px)";
    ctx.beginPath();
    ctx.moveTo(b.neck[0] + 10 * f, b.neck[1] + 0.1 * b.size);
    ctx.lineTo(b.neck[0] + 760 * f, b.neck[1] - b.size * 0.6);
    ctx.lineTo(b.neck[0] + 760 * f, b.neck[1] + b.size);
    ctx.closePath();
    ctx.fillStyle = alpha(p.warm ?? "#FFD696", 0.28 * (1 - level));
    ctx.fill();
    ctx.restore();
  }
  ctx.restore();
}

export function vignette(ctx) {
  const g = ctx.createRadialGradient(W / 2, H * 0.4, 0, W / 2, H * 0.4, H * 0.8);
  g.addColorStop(0, "rgba(0,0,0,0)");
  g.addColorStop(1, "rgba(0,0,0,0.47)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}
