// Devices: the diagram marks a scene may ask for. Ripples and dashed lines are drawn in the
// scene, under the camera; the lens, section, counter and split are drawn on the screen.
// `where` is the stage's motion (see motion.mjs), which turns targets into points.

import { Canvas } from "skia-canvas";
import { SCENE_BOTTOM, SCENE_TOP, W, H, alpha, shade } from "./places.mjs";
import { ease } from "./rig.mjs";
import { tones } from "./plates.mjs";
import { toScreen } from "./camera.mjs";
import { px } from "./motion.mjs";

export const DEVICES = ["section", "lens", "ripples", "dashed", "counter", "route", "split"];

export function sceneDevices(ctx, t, devices, p, where) {
  for (const d of devices) {
    if (t < d.t0 || t > d.t1) continue;
    const q = ease((t - d.t0) / 0.6);
    const o = d.o;
    const colour = tones(p)[o.tone ?? "key"]?.[0] ?? p.key;
    if (d.name === "ripples") {
      const [x, y] = where.targetPoint(o.from, t);
      const along = o.along ? where.thingBox(o.along.__ref ?? o.along, t) : null;
      for (let i = 0; i < (o.count ?? 3); i++) {
        const phase = ((t - d.t0) * 0.9 + i / (o.count ?? 3)) % 1;
        const cy = along ? y - phase * (y - along[1]) * (o.down ? -1 : 1) : y;
        const r = along ? 26 + 18 * Math.sin(phase * Math.PI) : 20 + phase * 140;
        ctx.beginPath();
        ctx.ellipse(x, cy, r, along ? r * 0.45 : r, 0, 0, 2 * Math.PI);
        ctx.lineWidth = 3;
        ctx.strokeStyle = alpha(colour, (1 - phase) * 0.85 * q);
        ctx.stroke();
      }
    }
    if (d.name === "dashed" || d.name === "route") {
      const pts = (d.name === "route" ? o.points : [o.from, o.to]).map((z) => where.targetPoint(z, t));
      const total = pts.slice(1).reduce((s, b, i) => s + Math.hypot(b[0] - pts[i][0], b[1] - pts[i][1]), 0);
      let left = total * ease((t - d.t0) / Math.max((o.draw ?? 0.8), 0.1));
      ctx.beginPath();
      ctx.moveTo(...pts[0]);
      for (let i = 1; i < pts.length && left > 0; i++) {
        const [a, b] = [pts[i - 1], pts[i]];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        const f = Math.min(left / Math.max(len, 1), 1);
        ctx.lineTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f);
        left -= len;
      }
      ctx.setLineDash([14, 10]);
      ctx.lineWidth = 4;
      ctx.strokeStyle = colour;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

export function screenDevices(ctx, t, v, devices, p, where) {
  for (const d of devices) {
    if (t < d.t0 || t > d.t1) continue;
    const o = d.o;
    const q = ease((t - d.t0) / 0.5);
    if (d.name === "lens") {
      const target = toScreen(v, where.targetPoint(o.on, t));
      const r = o.r ?? 170, zoom = o.zoom ?? 2.2;
      const cx = Math.min(Math.max(target[0] + (target[0] < W / 2 ? 260 : -260), r + 30), W - r - 30);
      const cy = Math.min(Math.max(target[1] - 220, SCENE_TOP + r + 20), SCENE_BOTTOM - r - 20);
      const copy = new Canvas(W, H);
      copy.getContext("2d").drawImage(ctx.canvas, 0, 0);
      ctx.save();
      ctx.globalAlpha = q;
      ctx.beginPath();
      ctx.moveTo(...target);
      ctx.lineTo(cx, cy);
      ctx.setLineDash([10, 8]);
      ctx.lineWidth = 3;
      ctx.strokeStyle = alpha(p.light, 0.8);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(cx, cy, r * q, 0, 2 * Math.PI);
      ctx.save();
      ctx.clip();
      const half = r / zoom;
      ctx.drawImage(copy, target[0] - half, target[1] - half, 2 * half, 2 * half, cx - r, cy - r, 2 * r, 2 * r);
      ctx.restore();
      ctx.lineWidth = 10;
      ctx.strokeStyle = shade(p.light, 0.9);
      ctx.stroke();
      ctx.restore();
    }
    if (d.name === "section") {
      const floors = o.floors ?? 9, n = o.highlight ?? 1;
      const x0 = o.left ? 40 : W - 300, y0 = SCENE_TOP + 40, w = 260, h = 360;
      ctx.save();
      ctx.globalAlpha = q;
      ctx.fillStyle = "rgba(8,10,16,0.85)";
      ctx.beginPath();
      ctx.roundRect(x0, y0, w, h, 14);
      ctx.fill();
      const storey = (h - 40) / floors;
      for (let i = 0; i < floors; i++) {
        const fy = y0 + h - 20 - (i + 1) * storey;
        ctx.fillStyle = i + 1 === n ? alpha(p.threat, 0.85) : shade(p.wall, 1.1);
        ctx.fillRect(x0 + 30, fy + 3, w - 60, storey - 6);
      }
      ctx.restore();
    }
    if (d.name === "counter") {
      const from = o.from ?? 0, to = o.to ?? 0;
      const value = Math.round(from + (to - from) * ease((t - d.t0) / Math.max(d.t1 - d.t0, 0.1)));
      const [x, y] = [px(o.x ?? 0.82), o.y ?? SCENE_TOP + 120];
      ctx.save();
      ctx.globalAlpha = q;
      ctx.font = "120px Plate";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = tones(p)[o.tone ?? "key"][0];
      ctx.fillText(String(value), x, y);
      ctx.restore();
    }
    if (d.name === "split") {
      ctx.save();
      ctx.globalAlpha = q;
      ctx.fillStyle = p.night;
      ctx.fillRect(W / 2 - 6, SCENE_TOP, 12, SCENE_BOTTOM - SCENE_TOP);
      ctx.restore();
    }
  }
}
