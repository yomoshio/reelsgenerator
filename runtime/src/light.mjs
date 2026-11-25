// The light of a scene: its level at a moment, the darkness that level lays over the set,
// torch beams through it, and the vignette every frame gets.

import { Canvas } from "skia-canvas";
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
  ctx.fillStyle = `rgba(4,6,10,${(1 - level) * 0.62})`;
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

// One light for the whole scene, laid over everything drawn in it: the cool air of the
// place, then a warm pool under every lamp that is on, bright at the bulb and fading over
// the wall and the floor. `lamps` are [x, y, strength] in scene coordinates.
export function grade(ctx, lamps, floor, p) {
  ctx.save();
  ctx.globalCompositeOperation = "soft-light";
  ctx.fillStyle = "rgba(52,84,150,0.42)";
  ctx.fillRect(-W, -H, 3 * W, 3 * H);
  ctx.globalCompositeOperation = "screen";
  const warm = p.warm ?? "#FFD696";
  for (const [x, y, k] of lamps) {
    const glow = ctx.createRadialGradient(x, y, 0, x, y, 760);
    glow.addColorStop(0, alpha(warm, 0.3 * k));
    glow.addColorStop(0.35, alpha(warm, 0.1 * k));
    glow.addColorStop(1, alpha(warm, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(x - 760, y - 760, 1520, 1520);
    const bulb = ctx.createRadialGradient(x, y, 0, x, y, 70);
    bulb.addColorStop(0, alpha("#FFF2D8", 0.5 * k));
    bulb.addColorStop(1, alpha(warm, 0));
    ctx.fillStyle = bulb;
    ctx.fillRect(x - 70, y - 70, 140, 140);
    ctx.save();
    ctx.translate(x, floor + 70);
    ctx.scale(1, 0.2);
    const pool = ctx.createRadialGradient(0, 0, 0, 0, 0, 430);
    pool.addColorStop(0, alpha(warm, 0.2 * k));
    pool.addColorStop(1, alpha(warm, 0));
    ctx.fillStyle = pool;
    ctx.fillRect(-430, -430, 860, 860);
    ctx.restore();
  }
  ctx.restore();
}

// Grain: one small sheet of noise, made once and laid over every frame at a new spot, the
// way film looks. It takes the plastic off flat colour.
let noise = null;
function grain(ctx, t) {
  if (!noise) {
    noise = new Canvas(360, 640);
    const c = noise.getContext("2d");
    const data = c.createImageData(360, 640);
    let a = 12345;
    for (let i = 0; i < data.data.length; i += 4) {
      a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
      const v = a >>> 24;
      data.data[i] = data.data[i + 1] = data.data[i + 2] = v;
      data.data[i + 3] = 255;
    }
    c.putImageData(data, 0, 0);
  }
  const n = Math.floor(t * 30);
  ctx.save();
  ctx.globalCompositeOperation = "overlay";
  ctx.globalAlpha = 0.02;
  ctx.drawImage(noise, -((n * 73) % 120), -((n * 41) % 120), W + 120, H + 120);
  ctx.restore();
}

export function vignette(ctx, t = 0) {
  const g = ctx.createRadialGradient(W / 2, H * 0.36, H * 0.12, W / 2, H * 0.36, H * 0.78);
  g.addColorStop(0, "rgba(4,7,14,0)");
  g.addColorStop(1, "rgba(4,7,14,0.6)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  grain(ctx, t);
}
