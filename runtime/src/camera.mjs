// The camera: the view at a moment from the declared moves, and scene points on screen.
// A view is { cx, cy, zoom }: the scene point at the middle of the scene band, and the scale.

import { H, SCENE_BOTTOM, SCENE_TOP, W } from "./places.mjs";
import { ease } from "./rig.mjs";

const CAMERA_MOVE = 1.6; // seconds a camera move takes by default
const FY = (SCENE_TOP + SCENE_BOTTOM) / 2;

// `targetPoint(target, t)` gives the scene point a move looks at.
export function view(moves, seconds, t, targetPoint) {
  let cx = W / 2, cy = FY, zoom = 1 + 0.025 * ease(t / Math.max(seconds, 0.1));
  for (const m of moves) {
    if (t < m.t0) continue;
    const q = ease((t - m.t0) / Math.max((m.t1 ?? m.t0 + CAMERA_MOVE) - m.t0, 0.1));
    const goal = m.to ? targetPoint(m.to, m.t0) : [cx, cy];
    cx += (goal[0] - cx) * q;
    cy += (goal[1] - cy) * q;
    if (m.zoom) zoom += (m.zoom - zoom) * q;
  }
  // The camera never shows past the edge of the set.
  const halfW = W / 2 / zoom;
  cx = Math.min(Math.max(cx, halfW), W - halfW);
  cy = Math.min(Math.max(cy, FY / zoom), H - (H - FY) / zoom);
  return { cx, cy, zoom };
}

export function applyView(ctx, v) {
  ctx.translate(W / 2, FY);
  ctx.scale(v.zoom, v.zoom);
  ctx.translate(-v.cx, -v.cy);
}

export const toScreen = (v, [x, y]) => [(x - v.cx) * v.zoom + W / 2, (y - v.cy) * v.zoom + FY];

export function boxToScreen(v, b) {
  const [x0, y0] = toScreen(v, [b[0], b[1]]);
  return [x0, y0, b[2] * v.zoom, b[3] * v.zoom];
}
