// The stage a scene's code builds and the frames drawn from it. Scene code runs once and
// only declares: the place, things, people, what they do and when, camera moves, light and
// devices. Every frame is then computed from those declarations for its moment, so motion
// is smooth to a fraction of a pixel and nothing changes that the code did not ask for.

import { Canvas } from "skia-canvas";
import { FLOOR, H, HERO, SCENE_BOTTOM, SCENE_TOP, ScriptError, W, alpha, makePlace, seedOf, shade } from "./places.mjs";
import { FIXTURES, WATER, drawWater, spec } from "./things.mjs";
import * as rig from "./rig.mjs";
import * as plates from "./plates.mjs";
import { place as placePlate, problems as frameProblems } from "./layout.mjs";

const WALK_SPEED = 260; // px a second
const CAMERA_MOVE = 1.6; // seconds a camera move takes by default

export const bare = (w) => String(w).toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]/gu, "");

export function makeStage(input, library = {}) {
  const p = input.palette;
  const seconds = input.seconds;
  const words = input.words.map((w) => ({ ...w, key: bare(w.text) }));
  const cast = Object.fromEntries(input.characters.map((c) => [c.key, c]));
  const decl = { place: null, things: [], people: [], moves: [], lights: [], devices: [], draws: [], events: 0 };
  let sandbox = null;

  // --- time -------------------------------------------------------------------------------
  function at(word, n = 1) {
    const key = bare(word);
    let seen = 0;
    for (const w of words) if (w.key === key && ++seen === n) return w.start;
    const heard = words.map((w) => w.text).join(" ");
    throw new ScriptError(`no word «${word}»${n > 1 ? ` said ${n} times` : ""} in this beat; its words are: ${heard}`);
  }
  function time(x, fallback = 0) {
    if (x === undefined || x === null) return fallback;
    if (typeof x === "number") return Math.min(Math.max(x, 0), seconds);
    if (typeof x === "string") return at(x);
    if (typeof x === "object" && x.word) return at(x.word, x.n ?? 1);
    throw new ScriptError(`a time is a number of seconds or a word of the beat, not ${JSON.stringify(x)}`);
  }
  const px = (x) => (Math.abs(x) <= 1.5 ? x * W : x);

  // --- the place --------------------------------------------------------------------------
  function setPlace(kind, opts = {}) {
    const chosen = kind ?? input.place.kind;
    decl.place = makePlace(chosen, p, { seed: input.place.key, ...opts });
    return decl.place;
  }
  const stagePlace = () => decl.place ?? setPlace();
  const k = () => stagePlace().scale / HERO;

  // --- things -----------------------------------------------------------------------------
  function thing(name, opts = {}) {
    const s = spec(name, library);
    const count = decl.things.filter((t) => t.name === name).length;
    const t = {
      kind: "thing", name, id: count ? `${name}#${count + 1}` : name, spec: s,
      x: px(opts.x ?? 0.5), level: opts.level ?? opts.floor ?? 1,
      scale: (opts.scale ?? 1) * k(), flip: opts.flip ? -1 : 1, front: !!opts.front,
      states: [{ t: 0, n: opts.state ?? 0 }], moves: [],
    };
    decl.things.push(t);
    const handle = {
      id: t.id,
      state(n, o = {}) {
        t.states.push({ t: time(o.at), n });
        decl.events++;
        return handle;
      },
      move(o = {}) {
        t.moves.push({ t0: time(o.at), t1: time(o.until, time(o.at) + 1.2), x: px(o.to ?? o.x ?? t.x) });
        decl.events++;
        return handle;
      },
      part(partName) {
        if (!s.parts[partName]) throw new ScriptError(`'${name}' has no part '${partName}'; parts: ${Object.keys(s.parts).join(", ")}`);
        return { ref: t, part: partName };
      },
      __ref: t,
    };
    return handle;
  }
  function thingX(t, time_) {
    let x = t.x;
    for (const m of t.moves) x += (m.x - x) * rig.ease((time_ - m.t0) / Math.max(m.t1 - m.t0, 0.01));
    return x;
  }
  function thingState(t, time_) {
    let level = t.states[0].n;
    for (const st of t.states.slice(1)) level += (st.n - level) * rig.ease((time_ - st.t) / 1.2);
    return level;
  }
  function thingFoot(t, time_) {
    const place = stagePlace();
    const x = thingX(t, time_);
    const ground = place.support(x, t.level);
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

  // --- people -----------------------------------------------------------------------------
  function person(key, opts = {}) {
    const card = cast[key]?.card;
    if (!card) throw new ScriptError(`no character '${key}'; characters: ${Object.keys(cast).join(", ")}`);
    if (decl.people.some((q) => q.key === key)) throw new ScriptError(`'${key}' is already on stage`);
    const pr = {
      kind: "person", key, id: key, card, level: opts.level ?? opts.floor ?? 1,
      x0: px(opts.x ?? 0.5), facing0: opts.facing === "left" ? -1 : 1,
      cues: [{ t: 0, pose: opts.pose ?? "stand", target: null }], walks: [], looks: [], sits: [],
      appear: opts.enter ? null : 0,
    };
    decl.people.push(pr);
    const handle = {
      id: key,
      pose(name, o = {}) {
        if (!rig.POSES[name]) throw new ScriptError(`no pose '${name}'; poses: ${Object.keys(rig.POSES).join(", ")}`);
        pr.cues.push({ t: time(o.at), pose: name, target: o.target ?? null });
        decl.events++;
        return handle;
      },
      walk(o = {}) {
        if (o.to === undefined) throw new ScriptError("walk needs `to`: an x, a thing or a person");
        const t0 = time(o.at);
        pr.walks.push({ t0, until: o.until === undefined ? null : time(o.until), to: o.to });
        decl.events++;
        return handle;
      },
      sit(target, o = {}) {
        const ref = target?.__ref ?? target?.ref;
        if (!ref || !ref.spec?.parts?.seat) throw new ScriptError("sit needs a thing with a seat: bed, bench or chair");
        const t0 = time(o.at);
        pr.sits.push({ t: t0, ref });
        pr.walks.push({ t0: Math.max(0, t0 - 0.9), until: t0, to: target, seat: true });
        pr.cues.push({ t: t0, pose: "sit", target: null });
        decl.events++;
        return handle;
      },
      stand(o = {}) {
        const t0 = time(o.at);
        pr.sits.push({ t: t0, ref: null });
        pr.cues.push({ t: t0, pose: "stand", target: null });
        decl.events++;
        return handle;
      },
      reach(target, o = {}) {
        pr.cues.push({ t: time(o.at), pose: "reach", target });
        decl.events++;
        return handle;
      },
      point(target, o = {}) {
        pr.cues.push({ t: time(o.at), pose: "point", target });
        decl.events++;
        return handle;
      },
      knock(target, o = {}) {
        pr.cues.push({ t: time(o.at), pose: "knock", target });
        decl.events++;
        return handle;
      },
      look(target, o = {}) {
        pr.looks.push({ t: time(o.at), target });
        decl.events++;
        return handle;
      },
      enter(o = {}) {
        const from = o.from === "left" ? -0.12 * W : 1.12 * W;
        const t0 = time(o.at);
        pr.appear = t0;
        pr.walks.push({ t0, until: null, to: pr.x0, from });
        decl.events++;
        return handle;
      },
      __ref: pr,
    };
    return handle;
  }
  const size = (pr) => rig.heightOf(pr.card, stagePlace().scale);

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
  const ground = (pr, x) => stagePlace().support(x, pr.level);

  // --- camera, light, devices, drawing ----------------------------------------------------
  const camera = {
    push(o = {}) {
      decl.moves.push({ t0: time(o.at), t1: o.until !== undefined ? time(o.until) : null, to: o.to ?? null, zoom: o.zoom ?? 1.18 });
      decl.events++;
      return camera;
    },
    pan(o = {}) {
      decl.moves.push({ t0: time(o.at), t1: o.until !== undefined ? time(o.until) : null, to: o.to ?? null, zoom: null });
      decl.events++;
      return camera;
    },
    back(o = {}) {
      decl.moves.push({ t0: time(o.at), t1: o.until !== undefined ? time(o.until) : null, to: [0.5, (SCENE_TOP + SCENE_BOTTOM) / 2], zoom: 1 });
      decl.events++;
      return camera;
    },
  };
  function view(t) {
    let cx = W / 2, cy = (SCENE_TOP + SCENE_BOTTOM) / 2, zoom = 1 + 0.025 * rig.ease(t / Math.max(seconds, 0.1));
    for (const m of decl.moves) {
      if (t < m.t0) continue;
      const q = rig.ease((t - m.t0) / Math.max((m.t1 ?? m.t0 + CAMERA_MOVE) - m.t0, 0.1));
      const goal = m.to ? targetPoint(m.to, m.t0) : [cx, cy];
      cx += (goal[0] - cx) * q;
      cy += (goal[1] - cy) * q;
      if (m.zoom) zoom += (m.zoom - zoom) * q;
    }
    // The camera never shows past the edge of the set.
    const fy = (SCENE_TOP + SCENE_BOTTOM) / 2;
    const halfW = W / 2 / zoom;
    cx = Math.min(Math.max(cx, halfW), W - halfW);
    cy = Math.min(Math.max(cy, fy / zoom), H - (H - fy) / zoom);
    return { cx, cy, zoom };
  }
  function applyView(ctx, v) {
    const fy = (SCENE_TOP + SCENE_BOTTOM) / 2;
    ctx.translate(W / 2, fy);
    ctx.scale(v.zoom, v.zoom);
    ctx.translate(-v.cx, -v.cy);
  }
  const toScreen = (v, [x, y]) => {
    const fy = (SCENE_TOP + SCENE_BOTTOM) / 2;
    return [(x - v.cx) * v.zoom + W / 2, (y - v.cy) * v.zoom + fy];
  };
  const boxToScreen = (v, b) => {
    const [x0, y0] = toScreen(v, [b[0], b[1]]);
    return [x0, y0, b[2] * v.zoom, b[3] * v.zoom];
  };

  function light(level, o = {}) {
    decl.lights.push({ t: time(o.at), level: Math.min(Math.max(level, 0), 1), flicker: !!o.flicker, until: o.until !== undefined ? time(o.until) : null });
    decl.events++;
  }
  function lightAt(t) {
    let level = 1, flicker = false;
    for (const l of decl.lights) {
      if (t < l.t) continue;
      level += (l.level - level) * rig.ease((t - l.t) / 0.5);
      flicker = l.flicker && (l.until === null || t < l.until);
    }
    if (flicker) level *= 0.55 + 0.45 * Math.max(0, Math.sin(t * 9.1) * Math.sin(t * 3.7 + 1.3));
    return level;
  }

  const DEVICES = ["section", "lens", "ripples", "dashed", "counter", "route", "split"];
  function device(name, o = {}) {
    if (!DEVICES.includes(name)) throw new ScriptError(`no device '${name}'; devices: ${DEVICES.join(", ")}`);
    decl.devices.push({ name, o, t0: time(o.at), t1: o.until !== undefined ? time(o.until) : seconds });
    decl.events++;
  }
  function draw(fn, o = {}) {
    if (typeof fn !== "function") throw new ScriptError("draw takes a function (ctx, t) => { ... }");
    decl.draws.push({ fn, layer: o.layer ?? "front" });
  }

  const api = {
    W, H, floor: FLOOR, seconds, words: words.map((w) => w.text),
    place: (kind, opts) => (setPlace(kind, opts), undefined),
    thing, person, camera, light, device, draw, at,
  };

  // --- plates -----------------------------------------------------------------------------
  function revealTime(r) {
    const key = bare(r.on_word);
    let seen = 0;
    for (const w of words) if (w.key === key && ++seen === (r.occurrence ?? 1)) return w.start;
    return 0;
  }
  function plateTarget(name, t) {
    const pr = decl.people.find((q) => q.key === name);
    if (pr) {
      const b = rig.box(personBones(pr, t));
      return { point: [b[0] + b[2] / 2, b[1] + 10], feet: [b[0] + b[2] / 2, b[1] + b[3]], box: b };
    }
    const th = decl.things.find((q) => q.name === name);
    if (th) {
      const b = thingBox(th, t);
      return { point: [b[0] + b[2] / 2, b[1] + Math.min(b[3] * 0.3, 120)], feet: [b[0] + b[2] / 2, b[1] + b[3]], box: b };
    }
    return null;
  }
  let laid = null;
  function layPlates(ctx) {
    laid = [];
    const reveals = [...(input.carried ?? []).map((r) => ({ ...r, start: 0 })), ...input.beat.reveals.map((r) => ({ ...r, start: revealTime(r) }))];
    const rules = reveals.filter((r) => r.kind === "rule_card").sort((a, b) => a.start - b.start);
    for (const r of reveals) {
      const end = r.kind === "rule_card" ? (rules.find((q) => q.start > r.start)?.start ?? seconds + 1) : seconds + 1;
      const plate = { ...r, end, tone: r.tone ?? "neutral" };
      if (["label", "status", "count"].includes(r.kind)) {
        const target = r.target ? plateTarget(r.target, r.start) : null;
        const sizeOf = r.kind === "status" ? 30 : r.kind === "count" ? 54 : 40;
        const wh = plates.pillSize(ctx, r.text, sizeOf);
        const obstacles = [
          ...decl.people.map((q) => rig.box(personBones(q, r.start))),
          ...decl.things.filter((q) => q.spec.on === "floor").map((q) => thingBox(q, r.start)),
          ...laid.filter((q) => q.box).map((q) => q.box),
        ];
        const anchor = target ? (r.kind === "status" ? target.feet : target.point) : [W / 2, SCENE_TOP + 260];
        const at_ = placePlate(wh, anchor, obstacles, r.kind === "status");
        Object.assign(plate, { size: sizeOf, at: at_, target: r.kind === "status" || !target ? null : target.point, box: [...at_, ...wh], pinned: true });
      }
      laid.push(plate);
    }
  }

  // --- a frame ----------------------------------------------------------------------------
  let backdrop = null;
  let surface = null;
  function waterSurface(t) {
    const water = decl.things.find((q) => q.name === "water");
    if (!water) return null;
    const hero = HERO * k();
    const level = thingState(water, t);
    const kx = Math.min(Math.floor(level), WATER.length - 2);
    const depth = WATER[kx] + (WATER[kx + 1] - WATER[kx]) * (level - kx);
    return stagePlace().support(W / 2, water.level) - depth * hero;
  }

  function render(ctx, t) {
    const place = stagePlace();
    if (!backdrop) {
      backdrop = new Canvas(W, H);
      place.draw(backdrop.getContext("2d"), 0);
    }
    if (!laid) layPlates(ctx);
    const v = view(t);
    ctx.save();
    ctx.fillStyle = p.night;
    ctx.fillRect(0, 0, W, H);
    applyView(ctx, v);
    ctx.drawImage(backdrop, 0, 0);
    custom(ctx, t, "back");
    const drawThing = (th) => {
      const [x, y] = thingFoot(th, t);
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(th.scale * th.flip, th.scale);
      th.spec.draw(ctx, thingState(th, t), t, p, seedOf(th.id + input.place.key), place, x, y);
      ctx.restore();
    };
    const items = [];
    for (const th of decl.things.filter((q) => q.spec.on !== "floor" && q.spec.on !== "fill")) drawThing(th);
    for (const th of decl.things.filter((q) => q.spec.on === "floor" && !q.front)) drawThing(th);
    const people = [...decl.people].sort((a, b) => ground(a, personX(a, t).x) - ground(b, personX(b, t).x));
    const walkers = [];
    for (const pr of people) {
      const b = personBones(pr, t);
      rig.draw(ctx, b, pr.card);
      walkers.push(b.hip[0]);
      const lowest = Math.max(b.ankle_f[1], b.ankle_n[1]) + 0.065 * b.size * 0.35;
      const seated = seatAt(pr, t);
      items.push({ id: pr.key, kind: "person", box: rig.box(b), screen: boxToScreen(v, rig.box(b)), gap: seated ? 0 : ground(pr, b.hip[0]) - lowest });
    }
    for (const th of decl.things.filter((q) => q.spec.on === "fill")) {
      surface = drawWater(ctx, place.support(W / 2, th.level), HERO * k(), thingState(th, t), t, p, walkers);
    }
    for (const th of decl.things.filter((q) => q.spec.on === "floor" && q.front)) drawThing(th);
    for (const th of decl.things) {
      const b = thingBox(th, t);
      const [x, y] = thingFoot(th, t);
      items.push({ id: th.id, kind: th.spec.on === "fill" ? "fill" : "thing", on: th.spec.on, box: b, screen: boxToScreen(v, b), gap: th.spec.on === "floor" ? place.support(x, th.level) - y : 0 });
    }
    custom(ctx, t, "front");
    sceneDevices(ctx, t);
    darkness(ctx, t, people);
    ctx.restore();
    vignette(ctx);
    screenDevices(ctx, t, v);
    const shown = drawPlates(ctx, t, v);
    custom(ctx, t, "top");
    return { items, plates: shown };
  }

  function custom(ctx, t, layer) {
    for (const d of decl.draws.filter((q) => q.layer === layer)) {
      ctx.save();
      sandbox.call(d.fn, guarded(ctx), t);
      ctx.restore();
    }
  }

  function sceneDevices(ctx, t) {
    for (const d of decl.devices) {
      if (t < d.t0 || t > d.t1) continue;
      const q = rig.ease((t - d.t0) / 0.6);
      const o = d.o;
      const colour = plates.tones(p)[o.tone ?? "key"]?.[0] ?? p.key;
      if (d.name === "ripples") {
        const [x, y] = targetPoint(o.from, t);
        const along = o.along ? thingBox(o.along.__ref ?? o.along, t) : null;
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
        const pts = (d.name === "route" ? o.points : [o.from, o.to]).map((z) => targetPoint(z, t));
        const total = pts.slice(1).reduce((s, b, i) => s + Math.hypot(b[0] - pts[i][0], b[1] - pts[i][1]), 0);
        let left = total * rig.ease((t - d.t0) / Math.max((o.draw ?? 0.8), 0.1));
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

  function screenDevices(ctx, t, v) {
    for (const d of decl.devices) {
      if (t < d.t0 || t > d.t1) continue;
      const o = d.o;
      const q = rig.ease((t - d.t0) / 0.5);
      if (d.name === "lens") {
        const target = toScreen(v, targetPoint(o.on, t));
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
        const value = Math.round(from + (to - from) * rig.ease((t - d.t0) / Math.max(d.t1 - d.t0, 0.1)));
        const [x, y] = [px(o.x ?? 0.82), o.y ?? SCENE_TOP + 120];
        ctx.save();
        ctx.globalAlpha = q;
        ctx.font = "120px Plate";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = plates.tones(p)[o.tone ?? "key"][0];
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

  function darkness(ctx, t, people) {
    const level = lightAt(t);
    if (level >= 0.999) return;
    ctx.save();
    ctx.fillStyle = `rgba(4,6,10,${(1 - level) * 0.85})`;
    ctx.fillRect(-W, -H, 3 * W, 3 * H);
    for (const pr of people.filter((q) => (q.card.extras ?? []).includes("torch"))) {
      const b = personBones(pr, t);
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

  function vignette(ctx) {
    const g = ctx.createRadialGradient(W / 2, H * 0.4, 0, W / 2, H * 0.4, H * 0.8);
    g.addColorStop(0, "rgba(0,0,0,0)");
    g.addColorStop(1, "rgba(0,0,0,0.47)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }

  function drawPlates(ctx, t, v) {
    const shown = [];
    for (const pl of laid) {
      if (t < pl.start || t >= pl.end) continue;
      if (pl.kind === "rule_card") shown.push({ text: pl.text, box: plates.drawRuleCard(ctx, pl.text, t, pl.start, p) });
      else if (pl.kind === "hud") shown.push({ text: pl.text, box: plates.drawHud(ctx, pl.text, t, pl.start, p) });
      else if (pl.kind === "stamp") shown.push({ text: pl.text, box: plates.drawStamp(ctx, pl.text, t, pl.start, p) });
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

  // What the scene's code got wrong without looking at a frame.
  function declared() {
    const found = [];
    const placed = new Set(decl.people.map((q) => q.key));
    const missing = input.beat.cast.filter((key) => !placed.has(key));
    if (missing.length) found.push(`the beat's cast ${missing.join(", ")} never appears; put every one of them on stage with s.person`);
    const staged = new Set(decl.things.map((q) => q.name));
    const absent = (input.beat.staging?.things ?? []).filter((n) => !staged.has(n));
    if (absent.length) found.push(`the staging puts ${absent.join(", ")} in this place, but the scene never places them; add them with s.thing`);
    if (seconds >= 5 && decl.events === 0) found.push(`nothing moves or changes in ${seconds.toFixed(1)} s; make something happen on the narrator's words`);
    for (const r of input.beat.reveals) {
      if (r.target && !decl.people.some((q) => q.key === r.target) && !decl.things.some((q) => q.name === r.target))
        found.push(`the plate '${r.text}' is pinned to '${r.target}', which the scene never places`);
    }
    return found;
  }

  return {
    api,
    run(box) {
      sandbox = box;
      box.run(api);
      stagePlace();
    },
    render,
    declared,
    frameProblems,
  };
}

// The canvas scene code draws on: everything a canvas does except text, which is ours.
function guarded(ctx) {
  return new Proxy(ctx, {
    get(target, prop) {
      if (prop === "fillText" || prop === "strokeText") {
        return () => {
          throw new ScriptError("text on screen is drawn by plates; scene code never draws text");
        };
      }
      const value = target[prop];
      return typeof value === "function" ? value.bind(target) : value;
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
  });
}
