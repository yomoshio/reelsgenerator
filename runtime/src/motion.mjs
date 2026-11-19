// Where everything declared on the stage is at a moment: the foot and box of a thing, the
// x, facing and bones of a person, and the point a target stands for. `decl` is the stage's
// declarations and `place` returns its place; nothing here changes either.

import { FLOOR, H, HERO, SCENE_TOP, ScriptError, W, seedOf } from "./places.mjs";
import { WATER } from "./things.mjs";
import * as rig from "./rig.mjs";

const WALK_SPEED = 260; // px a second

export const px = (x) => (Math.abs(x) <= 1.5 ? x * W : x);

export function makeMotion(decl, place) {
  const k = () => place().scale / HERO;

  // --- things -----------------------------------------------------------------------------
  function thingX(t, time_) {
    let x = t.x ?? partPoint(t.base, t.base.spec.parts.top ? "top" : "seat", time_)[0];
    for (const m of t.moves) x += (m.x - x) * rig.ease((time_ - m.t0) / Math.max(m.t1 - m.t0, 0.01));
    return x;
  }
  function thingState(t, time_) {
    let level = t.states[0].n;
    for (const st of t.states.slice(1)) level += (st.n - level) * rig.ease((time_ - st.t) / 1.2);
    return level;
  }
  function thingFoot(t, time_) {
    const x = thingX(t, time_);
    if (t.base) return [x, partPoint(t.base, t.base.spec.parts.top ? "top" : "seat", time_)[1]];
    const ground = place().support(x, t.level);
    const on = t.spec.on;
    if (on === "wall") return [x, ground - (t.spec.lift ?? 0) * t.scale];
    if (on === "ceiling") return [x, SCENE_TOP + 10];
    return [x, ground];
  }
  function thingBox(t, time_) {
    const [x, y] = thingFoot(t, time_);
    const { w, h, on } = t.spec;
    if (on === "ceiling") return [x - (w * t.scale) / 2, y, w * t.scale, h * t.scale];
    if (on === "tall") return [x - (w * t.scale) / 2, 0, w * t.scale, y];
    if (on === "fill") return [0, 0, W, H];
    return [x - (w * t.scale) / 2, y - h * t.scale, w * t.scale, h * t.scale];
  }
  function partPoint(ref, partName, time_) {
    const [x, y] = thingFoot(ref, time_);
    const [dx, dy] = ref.spec.parts[partName];
    if (ref.spec.on === "fill") return [x, waterSurface(time_) ?? y];
    return [x + dx * ref.scale * ref.flip, y + dy * ref.scale];
  }
  function waterSurface(t) {
    const water = decl.things.find((q) => q.name === "water");
    if (!water) return null;
    const hero = HERO * k();
    const level = thingState(water, t);
    const kx = Math.min(Math.floor(level), WATER.length - 2);
    const depth = WATER[kx] + (WATER[kx + 1] - WATER[kx]) * (level - kx);
    return place().support(W / 2, water.level) - depth * hero;
  }

  // --- people -----------------------------------------------------------------------------
  const size = (pr) => rig.heightOf(pr.card, place().scale);
  const ground = (pr, x) => place().support(x, pr.level);

  // The x a person stands at and which way they face at time t.
  function personX(pr, t) {
    let x = pr.x0;
    let facing = pr.facing0;
    let walking = false;
    for (const w of [...pr.walks].sort((a, b) => a.t0 - b.t0)) {
      if (t < w.t0) break;
      const from = w.from ?? x;
      const goal = w.seat ? targetPoint(w.to, w.t0)[0] - 30 * Math.sign(targetPoint(w.to, w.t0)[0] - from || 1) : targetX(w.to, w.t0, pr);
      const dur = w.until !== null ? Math.max(w.until - w.t0, 0.1) : Math.max(Math.abs(goal - from) / WALK_SPEED, 0.3);
      const q = Math.min((t - w.t0) / dur, 1);
      x = from + (goal - from) * (w.seat ? rig.ease(q) : q);
      if (Math.abs(goal - from) > 2) facing = goal > from ? 1 : -1;
      walking = q < 1 && Math.abs(goal - from) > 20;
    }
    for (const l of pr.looks) if (t >= l.t) facing = lookFacing(l.target, x, facing, t);
    return { x, facing, walking };
  }
  function lookFacing(target, x, facing, t) {
    if (target === "left") return -1;
    if (target === "right") return 1;
    const [tx] = targetPoint(target, t);
    return tx === x ? facing : tx > x ? 1 : -1;
  }
  function targetX(target, t, self) {
    if (typeof target === "number") return px(target);
    const [x] = targetPoint(target, t);
    const ref = target?.__ref;
    if (ref?.kind === "thing" || ref?.kind === "person") {
      const box = ref.kind === "thing" ? thingBox(ref, t) : [x - 60, 0, 120, 0];
      const from = personX(self, t).x;
      const gap = 40;
      return from < x ? box[0] - gap : box[0] + box[2] + gap;
    }
    return x;
  }
  function targetPoint(target, t) {
    if (target === null || target === undefined) throw new ScriptError("a target is missing");
    if (typeof target === "number") return [px(target), FLOOR];
    if (Array.isArray(target)) return [px(target[0]), target[1] <= 1.5 ? target[1] * H : target[1]];
    if (target.ref && target.part) return partPoint(target.ref, target.part, t);
    const ref = target.__ref ?? target;
    if (ref.kind === "thing") {
      const b = thingBox(ref, t);
      return [b[0] + b[2] / 2, b[1] + b[3] * 0.35];
    }
    if (ref.kind === "person") {
      const b = personBones(ref, t);
      return b.head;
    }
    throw new ScriptError("a target is a thing, a part of a thing, a person, or [x, y]");
  }

  function seatAt(pr, t) {
    let seat = null;
    for (const st of [...pr.sits].sort((a, b) => a.t - b.t)) if (t >= st.t) seat = st;
    return seat?.ref ? seat : null;
  }

  function personBones(pr, t) {
    const { x, facing, walking } = personX(pr, t);
    const s = size(pr);
    const cues = pr.cues.filter((c) => c.t <= t);
    const now = cues[cues.length - 1];
    const before = cues.length > 1 ? cues[cues.length - 2] : null;
    const angles = (cue) => {
      const a = rig.poseAngles(walking && cue.pose !== "sit" ? "walk" : cue.pose);
      if (cue.target && ["reach", "point", "knock"].includes(cue.pose)) {
        const standing = rig.bones([x, ground(pr, x)], a, s, facing);
        const shoulder = standing.shoulder_n;
        const goal = targetPoint(cue.target, t);
        if (cue.pose === "point") {
          const ang = (Math.atan2((goal[0] - shoulder[0]) * facing, goal[1] - shoulder[1]) * 180) / Math.PI;
          a.arm_n = ang;
          a.fore_n = 0;
        } else [a.arm_n, a.fore_n] = rig.reach(shoulder, goal, s, facing);
      }
      return a;
    };
    let a = angles(now);
    if (before) a = rig.blend(angles(before), a, rig.ease((t - now.t) / rig.EASE));
    a = rig.alive(a, t + seedOf(pr.key) % 7, walking && now.pose !== "sit");
    const seat = seatAt(pr, t);
    let hip = null;
    if (seat) {
      const sp = partPoint(seat.ref, "seat", t);
      const standingHip = rig.bones([x, ground(pr, x)], rig.poseAngles("stand"), s, facing).hip;
      const q = rig.ease((t - pr.sits.find((z) => z.ref === seat.ref).t) / rig.EASE);
      hip = [standingHip[0] + (sp[0] - standingHip[0]) * q, standingHip[1] + (sp[1] - standingHip[1]) * q];
    }
    return rig.bones([x, ground(pr, x)], a, s, facing, hip);
  }

  return { k, thingState, thingFoot, thingBox, personX, targetPoint, seatAt, personBones, ground };
}
