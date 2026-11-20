// Laying the beat's plates out once, against where people and things stand when each plate
// appears, and drawing the ones a moment shows. `where` is the stage's motion (motion.mjs).

import { SCENE_BOTTOM, SCENE_TOP, W } from "./places.mjs";
import * as rig from "./rig.mjs";
import * as plates from "./plates.mjs";
import { overlap, place as placePlate } from "./layout.mjs";
import { toScreen } from "./camera.mjs";

function plateTarget(decl, where, name, t) {
  const pr = decl.people.find((q) => q.key === name);
  if (pr) {
    const b = rig.box(where.personBones(pr, t));
    return { point: [b[0] + b[2] / 2, b[1] + 10], feet: [b[0] + b[2] / 2, b[1] + b[3]], box: b };
  }
  const th = decl.things.find((q) => q.name === name);
  if (th) {
    const b = where.thingBox(th, t);
    return { point: [b[0] + b[2] / 2, b[1] + Math.min(b[3] * 0.3, 120)], feet: [b[0] + b[2] / 2, b[1] + b[3]], box: b };
  }
  return null;
}

// `revealTime(reveal)` gives the second the reveal's word is said.
export function layPlates(ctx, input, decl, where, revealTime) {
  const seconds = input.seconds;
  const laid = [];
  const reveals = [...(input.carried ?? []).map((r) => ({ ...r, start: 0 })), ...input.beat.reveals.map((r) => ({ ...r, start: revealTime(r) }))];
  const rules = reveals.filter((r) => r.kind === "rule_card").sort((a, b) => a.start - b.start);
  for (const r of reveals) {
    const end = r.kind === "rule_card" ? (rules.find((q) => q.start > r.start)?.start ?? seconds + 1) : seconds + 1;
    const plate = { ...r, end, tone: r.tone ?? "neutral" };
    if (["label", "status", "count"].includes(r.kind)) {
      const target = r.target ? plateTarget(decl, where, r.target, r.start) : null;
      const sizeOf = r.kind === "status" ? 30 : r.kind === "count" ? 54 : 40;
      const wh = plates.pillSize(ctx, r.text, sizeOf);
      const obstacles = [
        ...decl.people.map((q) => rig.box(where.personBones(q, r.start))),
        ...decl.things.filter((q) => q.spec.on === "floor").map((q) => where.thingBox(q, r.start)),
        ...laid.filter((q) => q.box).map((q) => q.box),
      ];
      const anchor = target ? (r.kind === "status" ? target.feet : target.point) : [W / 2, SCENE_TOP + 260];
      const at_ = placePlate(wh, anchor, obstacles, r.kind === "status");
      Object.assign(plate, { size: sizeOf, at: at_, target: r.kind === "status" || !target ? null : target.point, box: [...at_, ...wh], pinned: true });
    }
    if (r.kind === "stamp") {
      const { w, h } = plates.stampSize(ctx, r.text);
      const taken = [...decl.people.map((q) => rig.box(where.personBones(q, r.start))), ...laid.filter((q) => q.box).map((q) => q.box)];
      const covers = (cy) => taken.reduce((sum, b) => sum + overlap([W / 2 - w / 2, cy - h / 2, w, h], b), 0);
      const spots = [(SCENE_TOP + SCENE_BOTTOM) / 2, SCENE_TOP + 40 + h / 2, SCENE_BOTTOM - 60 - h / 2];
      plate.cy = spots.reduce((best, cy) => (covers(cy) < covers(best) ? cy : best));
      plate.box = [W / 2 - w / 2, plate.cy - h / 2, w, h];
    }
    laid.push(plate);
  }
  return laid;
}

export function drawPlates(ctx, laid, t, v, p) {
  const shown = [];
  for (const pl of laid) {
    if (t < pl.start || t >= pl.end) continue;
    if (pl.kind === "rule_card") shown.push({ text: pl.text, box: plates.drawRuleCard(ctx, pl.text, t, pl.start, p) });
    else if (pl.kind === "hud") shown.push({ text: pl.text, box: plates.drawHud(ctx, pl.text, t, pl.start, p) });
    else if (pl.kind === "stamp") shown.push({ text: pl.text, box: plates.drawStamp(ctx, pl.text, t, pl.start, p, pl.cy) });
    else {
      const at_ = toScreen(v, pl.at);
      const target = pl.target ? toScreen(v, pl.target) : null;
      const moved = { ...pl, at: at_, target };
      if (pl.kind === "status") plates.drawStatus(ctx, moved, t, p);
      else plates.drawPinned(ctx, moved, t, p);
      shown.push({ text: pl.text, box: [...at_, pl.box[2] * 1, pl.box[3]], pinned: true });
    }
  }
  return shown;
}
