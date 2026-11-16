// Boxes, free room for plates, and what is wrong with a frame. A box is [x, y, w, h].

import { SCENE_BOTTOM, SCENE_TOP, W } from "./places.mjs";

export function overlap(a, b) {
  const x = Math.max(0, Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]));
  const y = Math.max(0, Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]));
  return x * y;
}

export function share(a, b) {
  return overlap(a, b) / Math.max(Math.min(a[2] * a[3], b[2] * b[3]), 1);
}

const inside = (b) => b[0] >= 20 && b[0] + b[2] <= W - 20 && b[1] >= SCENE_TOP + 10 && b[1] + b[3] <= SCENE_BOTTOM - 10;

// Where a plate of size [w, h] goes near `target`: the first of the spots around it that
// stays in the scene and clear of every obstacle, else the one that covers least.
export function place(size, target, obstacles, below = false) {
  const [w, h] = size;
  const [x, y] = target;
  const spots = below
    ? [[x - w / 2, y + 14], [x - w / 2, y - h - 230], [x + 40, y + 14], [x - w - 40, y + 14]]
    : [
        [x - w / 2, y - h - 170], [x - w - 60, y - h - 120], [x + 60, y - h - 120],
        [x - w / 2, y - h - 300], [x + 90, y - h / 2], [x - w - 90, y - h / 2],
        [x - w / 2, y + 120], [x - w / 2, y - h - 60],
      ];
  let best = null;
  for (const [sx, sy] of spots) {
    const b = [Math.min(Math.max(sx, 24), W - w - 24), Math.min(Math.max(sy, SCENE_TOP + 24), SCENE_BOTTOM - h - 24), w, h];
    const covered = obstacles.reduce((sum, o) => sum + overlap(b, o), 0);
    if (covered === 0 && inside(b)) return [b[0], b[1]];
    if (!best || covered < best[1]) best = [b, covered];
  }
  return [best[0][0], best[0][1]];
}

// What is wrong in one frame, as instructions the coder can act on.
export function problems(frame) {
  const found = [];
  const { t, items, plates, luminance } = frame;
  const at = `at ${t.toFixed(1)} s`;
  for (const it of items) {
    if (it.kind === "person" || (it.kind === "thing" && it.on === "floor")) {
      if (it.gap > 6) found.push(`${it.id} floats ${Math.round(it.gap)} px above the ground ${at}; let it stand on the ground or sit on a seat`);
      if (it.gap < -40) found.push(`${it.id} sinks ${Math.round(-it.gap)} px into the ground ${at}`);
    }
    const b = it.box;
    const out = Math.max(0, -b[0]) + Math.max(0, b[0] + b[2] - W);
    if (it.kind !== "fill" && out > b[2] * 0.3) found.push(`${it.id} is mostly outside the frame ${at}; keep x between 0.1 and 0.9`);
    if (it.kind === "person" && (b[1] < SCENE_TOP - 40 || b[1] + b[3] > SCENE_BOTTOM + 60)) found.push(`${it.id} leaves the scene band ${at}; the area below y=${SCENE_BOTTOM} is for captions`);
  }
  const floor = items.filter((i) => i.kind === "thing" && i.on === "floor");
  for (let i = 0; i < floor.length; i++)
    for (let j = i + 1; j < floor.length; j++)
      if (share(floor[i].box, floor[j].box) > 0.35) found.push(`${floor[i].id} and ${floor[j].id} stand inside each other ${at}; move one along x`);
  const people = items.filter((i) => i.kind === "person");
  for (let i = 0; i < people.length; i++)
    for (let j = i + 1; j < people.length; j++)
      if (share(people[i].box, people[j].box) > 0.5) found.push(`${people[i].id} and ${people[j].id} overlap ${at}; put them apart`);
  for (const plate of plates)
    for (const person of people)
      if (share(plate.box, person.screen ?? person.box) > 0.25 && plate.pinned) found.push(`the plate '${plate.text}' covers ${person.id} ${at}`);
  if (luminance < 10) found.push(`the frame is almost black ${at} (mean ${luminance.toFixed(0)}); light the scene`);
  if (luminance > 70) found.push(`the frame is too bright ${at} (mean ${luminance.toFixed(0)}); the channel is dark`);
  return found;
}
