// The stage a scene's code builds and the frames drawn from it. Scene code runs once and
// only declares: the place, things, people, what they do and when, camera moves, light and
// devices. Every frame is then computed from those declarations for its moment, so motion
// is smooth to a fraction of a pixel and nothing changes that the code did not ask for.
// Where things are at a moment is motion.mjs; the camera, light, devices, plates and the
// checks of what was declared each have a module of their own.

import { nothing, options, strict } from "./strict.mjs";
import "./canvas.mjs";
import { Canvas } from "skia-canvas";
import { FLOOR, H, HERO, SCENE_BOTTOM, SCENE_TOP, ScriptError, W, alpha, makePlace, seedOf } from "./places.mjs";
import { FIXTURES, drawWater, spec } from "./things.mjs";
import * as rig from "./rig.mjs";
import { problems as frameProblems } from "./layout.mjs";
import { bare, makeClock } from "./clock.mjs";
import { makeMotion, px } from "./motion.mjs";
import { applyView, boxToScreen, view } from "./camera.mjs";
import { darkness, vignette } from "./light.mjs";
import { DEVICES, sceneDevices, screenDevices } from "./devices.mjs";
import { drawPlates, layPlates } from "./platelayout.mjs";
import { declared } from "./checks.mjs";
import { dress } from "./dressing.mjs";

const HELD = 90; // px: the most a thing in a hand stands tall
const PLATES = ["stamp", "status", "label", "rule_card", "plate", "caption", "text", "subtitle"];
// Somebody in the crowd, in the greys of the place.
const EXTRA = {
  age: "adult", build: "average", skin: "light", hair: "short", hair_colour: "#2A2C33", face: [],
  top: "jacket", top_colour: "#4A5160", bottom: "trousers", bottom_colour: "#2B2F3A",
  shoes_colour: "#15171C", hat: "none", extras: [],
};
// What the model calls a pose the rig has under another name; a pose it does not have at
// all is stood through.
const ALIASES = {
  shout: "arms_out", yell: "arms_out", scream: "arms_out", panic: "arms_out", shrug: "arms_out",
  hit: "knock", slap: "knock", bang: "knock", push: "reach", tap: "reach", press: "reach", touch: "reach", type: "reach", swipe: "reach",
  eat: "hold", carry: "hold", hold_phone: "hold", read: "look_down", sleep: "sit", lie: "sit", lie_down: "sit",
  hear: "listen", wave: "point", show: "point",
};

// Words the model uses for a face, and the mood the rig has for each.
const FEELINGS = {
  smile: "happy", laugh: "happy", grin: "happy", relieved: "happy", calm: "neutral",
  cry: "sad", sigh: "sad", upset: "sad", disappointed: "sad", shake_head: "sad",
  afraid: "scared", fear: "scared", panic: "scared", scream: "scared", terrified: "scared",
  shout: "angry", yell: "angry", furious: "angry", annoyed: "angry", frown: "angry",
  shocked: "surprised", gasp: "surprised", confused: "worried", nervous: "worried", anxious: "worried",
  think: "worried", sleepy: "tired", exhausted: "tired", sleep: "tired",
};

// Names the model gives a thing the runtime draws itself.
const NAMED = { fire: "fireplace", hearth: "fireplace", fire_place: "fireplace", chimney: "fireplace", stove: "fireplace" };

// The longest walk in from off the frame, edge to edge at walking speed.
const ENTER_SECONDS = 4;

export { bare };

export function makeStage(input, library = {}) {
  const p = input.palette;
  const seconds = input.seconds;
  const { at, time, revealTime } = makeClock(input.words, seconds);
  const cast = Object.fromEntries(input.characters.map((c) => [c.key, c]));
  const decl = { place: null, things: [], people: [], moves: [], lights: [], devices: [], draws: [], events: 0, ignored: [] };
  const handles = {};
  const props = {};
  const known = (name) => props[name] ?? FIXTURES[name] ?? library[name];
  let sandbox = null;

  // --- the place --------------------------------------------------------------------------
  function setPlace(kind, opts = {}) {
    const chosen = kind ?? input.place.kind;
    decl.place = makePlace(chosen, p, { seed: input.place.key, ...opts });
    return decl.place;
  }
  const stagePlace = () => decl.place ?? setPlace();
  function pose(name) {
    if (rig.POSES[name]) return name;
    decl.ignored.push(`pose ${name}`);
    return ALIASES[name] ?? "stand";
  }
  const where = makeMotion(decl, stagePlace);
  const { k, thingState, thingFoot, thingBox, rest, personX, seatAt, personBones, ground } = where;

  // --- things -----------------------------------------------------------------------------
  function thing(name, opts = {}) {
    opts = options(opts, ["x", "scale", "flip", "state", "front", "level", "floor", "on", "hidden"], `s.thing("${name}")`, decl.ignored);
    name = String(name).replace(/#\d+$/, ""); // the brief calls a second door `door#2`
    name = NAMED[name] ?? name;
    // Plates are laid by the runtime from the beat's reveals, and a thing neither the runtime
    // nor the library has cannot be drawn: both are left out, and whatever is done to them.
    if (PLATES.includes(name) || !known(name)) return decl.ignored.push(`s.thing("${name}")`), nothing;
    const s = props[name] ?? spec(name, library);
    const count = decl.things.filter((t) => t.name === name).length;
    // A thing put on one with no top, a padlock on a door, hangs on its middle.
    // A thing put on a person is in their hand, and goes where they go.
    let base = opts.on?.__ref ?? opts.on?.ref ?? null;
    const holder = base?.kind === "person" ? base : null;
    if (base?.kind !== "thing") base = null;
    if (opts.on && !base && !holder) decl.ignored.push(`s.thing("${name}") option on`);
    if (holder && !opts.hidden && holder.cues[0].pose === "stand") holder.cues[0].pose = "hold";
    const t = {
      kind: "thing", name, id: count ? `${name}#${count + 1}` : name, spec: s, base, holder,
      x: opts.x === undefined && base ? null : px(opts.x ?? 0.5), level: opts.level ?? opts.floor ?? 1,
      scale: holder ? Math.min((opts.scale ?? 1) * k(), (HELD / s.h) * k()) : (opts.scale ?? 1) * k(),
      flip: opts.flip ? -1 : 1, front: !!opts.front, hidden: !!opts.hidden, pocket: opts.hidden ? holder : null,
      rests: [], carried: !!holder,
      states: [{ t: 0, n: opts.state ?? s.state ?? 0 }], moves: [],
    };
    decl.things.push(t);
    const handle = strict({
      id: t.id,
      x: (t.x ?? W / 2) / W,
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
        if (s.parts[partName]) return { ref: t, part: partName };
        decl.ignored.push(`${name}.part("${partName}")`);
        return handle;
      },
      __ref: t,
    }, name, decl.ignored);
    return handle;
  }

  // A thing neither the runtime nor the library has, drawn by the scene: a monkey's paw, a
  // torn letter. It is a thing like any other: it can be carried, pointed at and labelled.
  function prop(name, opts = {}) {
    name = String(name);
    const { draw: fn, w, h, size, ...rest_ } = opts ?? {};
    if (typeof fn !== "function") return thing(name, rest_);
    const tall = Math.min(Math.max(Number(h ?? size) || 70, 20), 400);
    const wide = Math.min(Math.max(Number(w ?? size) || tall, 20), 400);
    props[name] = {
      w: wide, h: tall, on: "floor", small: true, parts: {},
      draw(ctx, state, t) {
        ctx.translate(0, -tall / 2);
        sandbox.call(fn, guarded(ctx), t, state);
      },
    };
    return thing(name, rest_);
  }

  // --- people -----------------------------------------------------------------------------
  function person(key, opts = {}) {
    opts = options(opts, ["x", "facing", "pose", "mood", "level", "floor", "enter"], `s.person("${key}")`, decl.ignored);
    if (handles[key]) return handles[key];
    // A name outside the cast is somebody in the crowd: a queue, a passer-by.
    const card = cast[key]?.card ?? EXTRA;
    const pr = {
      kind: "person", key, id: key, card, extra: !cast[key], level: opts.level ?? opts.floor ?? 1,
      x0: px(opts.x ?? 0.5), facing0: opts.facing === "left" ? -1 : 1,
      cues: [{ t: 0, pose: pose(opts.pose ?? "stand"), target: null }], walks: [], looks: [], sits: [],
      appear: 0, moods: [],
    };
    const feel = (name, at_) => {
      const mood = rig.MOODS[name] ? name : FEELINGS[name];
      if (mood) pr.moods.push({ t: at_, mood });
      return !!mood;
    };
    if (opts.mood && !feel(opts.mood, 0)) decl.ignored.push(`mood ${opts.mood}`);
    decl.people.push(pr);
    // A thing a person takes up is sized for a hand from the start.
    const carriedThing = (target, verb) => {
      const th = target?.__ref ?? target?.ref;
      if (th?.kind !== "thing" || th.spec.on === "fill") return decl.ignored.push(`${key}.${verb} without a thing`), null;
      th.carried = true;
      th.scale = Math.min(th.scale, (HELD / th.spec.h) * k());
      return th;
    };
    const aimed = (pose, target, o) => {
      if ((target?.__ref ?? target?.ref) === pr) target = null; // a hand to one's own pocket
      pr.cues.push({ t: time(o.at), pose, target: target ?? null });
      decl.events++;
      return handle;
    };
    const handle = strict({
      id: key,
      pose(name, o = {}) {
        // A pose the rig lacks is often a feeling: `shout`, `smile`, `cry`.
        const felt = !rig.POSES[name] && feel(name, time(o.at));
        if (felt && !ALIASES[name]) return handle;
        pr.cues.push({ t: time(o.at), pose: pose(name), target: o.target ?? null });
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
        if (target && !target.__ref && !target.ref) [target, o] = [null, target];
        let ref = target?.__ref ?? target?.ref;
        // Told to sit on a table or on nothing, a person takes the nearest seat on stage.
        if (!ref?.spec?.parts?.seat) {
          const seats = decl.things.filter((q) => q.spec.parts.seat);
          ref = seats.sort((a, b) => Math.abs((a.x ?? 0) - pr.x0) - Math.abs((b.x ?? 0) - pr.x0))[0];
          if (!ref) return decl.ignored.push(`${key}.sit with no seat on stage`), handle;
        }
        const t0 = time(o.at);
        pr.sits.push({ t: t0, ref });
        pr.walks.push({ t0: Math.max(0, t0 - 0.9), until: t0, to: { __ref: ref }, seat: true });
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
      reach: (target, o = {}) => aimed("reach", target, o),
      point: (target, o = {}) => aimed("point", target, o),
      knock: (target, o = {}) => aimed("knock", target, o),
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
      take(target, o = {}) {
        const th = carriedThing(target, "take");
        if (!th) return handle;
        const t0 = time(o.at);
        // Out of a pocket it was never seen before; off a table the hand goes for it first.
        if (!th.rests.length && !th.holder && (typeof o.from === "string" || th.hidden)) Object.assign(th, { hidden: true, pocket: pr });
        const was = lastRest(th);
        if (!was.pocket && was.holder !== pr) pr.cues.push({ t: Math.max(0, t0 - rig.EASE), pose: "reach", target: spotOf(th, was) });
        pr.cues.push({ t: t0, pose: "hold", target: null });
        th.rests.push({ t: t0, takes: 0.3, holder: pr });
        decl.events++;
        return handle;
      },
      put(target, o = {}) {
        const th = carriedThing(target, "put");
        if (!th) return handle;
        const t0 = time(o.at);
        const on = o.on ?? o.to;
        const base = on?.__ref ?? on?.ref;
        const r = base?.kind === "thing" && base !== th ? { base, x: o.x === undefined ? null : px(o.x) }
          : { dropped: true, x: typeof on === "number" ? px(on) : o.x === undefined ? null : px(o.x) };
        if (r.dropped && r.x === null) r.x = pr.x0 + pr.facing0 * 90;
        const next = { t: t0 + rig.EASE * 0.7, takes: 0.2, ...r };
        pr.cues.push({ t: t0, pose: "reach", target: spotOf(th, next) }, { t: t0 + rig.EASE + 0.5, pose: "stand", target: null });
        th.rests.push(next);
        decl.events++;
        return handle;
      },
      give(target, o = {}) {
        const th = carriedThing(target, "give");
        const other = (o.to?.__ref ?? o.to?.ref ?? o.to)?.kind === "person" ? (o.to.__ref ?? o.to.ref ?? o.to) : decl.people.find((q) => q.key === o.to);
        if (!th) return handle;
        if (!other || other === pr) return decl.ignored.push(`${key}.give without a person in \`to\``), handle;
        const t0 = time(o.at);
        // Both hands meet half-way between them, at chest height.
        const meet = { spot: (t) => {
          const [a, b] = [where.walked(pr, t).x, where.walked(other, t).x];
          const reach_ = Math.min(Math.abs(b - a) / 2, 120) * Math.sign(b - a || 1);
          return [a + reach_, ground(pr, a) - where.size(pr) * 0.58];
        } };
        const theirs = { spot: (t) => {
          const [a, b] = [where.walked(pr, t).x, where.walked(other, t).x];
          const reach_ = Math.min(Math.abs(b - a) / 2, 120) * Math.sign(a - b || 1);
          return [b + reach_, ground(other, b) - where.size(other) * 0.58];
        } };
        pr.looks.push({ t: t0, target: { __ref: other } });
        other.looks.push({ t: t0, target: { __ref: pr } });
        pr.cues.push({ t: t0, pose: "reach", target: meet }, { t: t0 + rig.EASE + 0.6, pose: "stand", target: null });
        other.cues.push({ t: t0, pose: "reach", target: theirs }, { t: t0 + rig.EASE + 0.25, pose: "hold", target: null });
        th.rests.push({ t: t0 + rig.EASE, takes: 0.25, holder: other });
        decl.events++;
        return handle;
      },
      throw(target, o = {}) {
        const th = carriedThing(target, "throw");
        if (!th) return handle;
        const t0 = time(o.at);
        const to = o.to ?? pr.x0 / W + pr.facing0 * 0.3;
        const into = (to?.__ref ?? to?.ref)?.name ?? "";
        const gone = o.gone ?? /fire|stove|oven|bin|trash|well|water|window|river|pit|hole/.test(into);
        const land = typeof to === "number" ? { dropped: true, x: px(to) } : { point: (to?.__ref ?? to?.ref) === th ? [0.5, 0.5] : to };
        pr.looks.push({ t: t0, target: to });
        pr.cues.push({ t: t0, pose: "point", target: typeof to === "number" ? [px(to), FLOOR - 200] : land.point }, { t: t0 + 1.1, pose: "stand", target: null });
        th.rests.push({ t: t0 + 0.18, takes: 0.55, how: "throw", hidden: !!gone, ...land });
        decl.events++;
        return handle;
      },
      drop(target, o = {}) {
        const th = carriedThing(target, "drop");
        if (!th) return handle;
        const t0 = time(o.at);
        pr.cues.push({ t: t0, pose: "stand", target: null });
        th.rests.push({ t: t0, takes: 0.38, how: "drop", dropped: true, x: null, under: pr });
        decl.events++;
        return handle;
      },
      part: () => handle,
      mood(name, o = {}) {
        if (!feel(name, time(o.at))) decl.ignored.push(`mood ${name}`);
        decl.events++;
        return handle;
      },
      x: pr.x0 / W, // where they start, as a share of the width, for code that draws by hand
      __ref: pr,
    }, key, decl.ignored);
    handles[key] = handle;
    return handle;
  }

  const lastRest = (th) => th.rests.at(-1) ?? { first: true, holder: th.holder, base: th.base, hidden: th.hidden, pocket: th.pocket };
  // The middle of a thing where it rests, for a hand to go to.
  const spotOf = (th, r) => ({ spot: (t) => {
    const [x, y] = where.restFoot(th, r, t);
    return [x, y - (th.spec.h * th.scale) / 2];
  } });

  // --- camera, light, devices, drawing ----------------------------------------------------
  const camera = strict({
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
  }, "s.camera", decl.ignored);

  function light(level, o = {}) {
    decl.lights.push({ t: time(o.at), level: Math.min(Math.max(level, 0), 1), flicker: !!o.flicker, until: o.until !== undefined ? time(o.until) : null });
    decl.events++;
  }

  function device(name, o = {}) {
    if (!DEVICES.includes(name)) return void decl.ignored.push(`s.device("${name}")`);
    decl.devices.push({ name, o, t0: time(o.at), t1: o.until !== undefined ? time(o.until) : seconds });
    decl.events++;
  }
  function draw(fn, o = {}) {
    if (typeof fn !== "function") throw new ScriptError("draw takes a function (ctx, t) => { ... }");
    decl.draws.push({ fn, layer: o.layer ?? "front" });
  }

  const api = strict({
    W, H, width: W, height: H, floor: FLOOR, seconds, words: input.words.map((w) => w.text),
    place: (kind, opts) => (setPlace(kind, opts), undefined),
    thing, prop, person, camera, light, device, draw, at,
  }, "s", decl.ignored);

  // The model places by eye and puts two things or two people on one spot. The later one
  // steps aside; what the scene moves later it still moves from there.
  function settle() {
    const floor = decl.things.filter((q) => q.spec.on === "floor" && !q.spec.small && !q.spec.flat && !q.base && !q.holder && !q.carried && q.x !== null);
    for (let pass = 0; pass < 4; pass++) {
      for (let i = 0; i < floor.length; i++) {
        for (let j = i + 1; j < floor.length; j++) {
          const [a, b] = [floor[i], floor[j]];
          const need = ((a.spec.w * a.scale + b.spec.w * b.scale) / 2) * 0.8;
          if (Math.abs(b.x - a.x) >= need) continue;
          const side = b.x >= a.x ? 1 : -1;
          const half = (b.spec.w * b.scale) / 2;
          b.x = Math.min(Math.max(a.x + side * need, half), W - half);
          if (Math.abs(b.x - a.x) < need) b.x = Math.min(Math.max(a.x - side * need, half), W - half);
        }
      }
    }
    // Nobody stands inside a table: a person put on its spot stands at its nearer end, and
    // one put behind a counter serves from behind it. Nothing stands in a side wall.
    const tables = decl.things.filter((q) => q.spec.on === "floor" && !q.base && !q.holder && q.spec.parts.top && !q.spec.parts.seat && !q.spec.small && !q.spec.back && q.x !== null);
    const beside = (x) => {
      for (const q of tables) {
        const half = (q.spec.w * q.scale) / 2;
        if (q.name === "counter" || Math.abs(x - q.x) >= half + 40) continue;
        const side = x >= q.x ? 1 : -1;
        const out = q.x + side * (half + 64);
        return out > 0.08 * W && out < 0.92 * W ? out : q.x - side * (half + 64);
      }
      return x;
    };
    const edge = (stagePlace().walls ?? 0) + 70;
    for (const pr of decl.people) {
      pr.behind = tables.find((q) => q.name === "counter" && Math.abs(pr.x0 - q.x) < (q.spec.w * q.scale) / 2) ?? null;
      pr.x0 = Math.min(Math.max(beside(pr.x0), edge), W - edge);
      for (const w of pr.walks) if (typeof w.to === "number") w.to = Math.min(Math.max(beside(px(w.to)), edge), W - edge);
    }
    for (const q of decl.things) {
      if (q.x === null || q.spec.on === "fill" || q.spec.on === "tall") continue;
      const half = Math.min((q.spec.w * q.scale) / 2, W / 2 - edge + 60);
      q.x = Math.min(Math.max(q.x, edge - 60 + half), W - edge + 60 - half);
    }
    const people = [...decl.people].sort((a, b) => a.x0 - b.x0);
    for (let i = 1; i < people.length; i++) {
      const apart = (people[i].extra && people[i - 1].extra ? 0.07 : 0.13) * W; // a crowd stands close
      if (people[i].x0 - people[i - 1].x0 < apart) people[i].x0 = people[i - 1].x0 + apart;
    }
    const over = people.length ? people.at(-1).x0 - 0.92 * W : 0;
    if (over > 0) for (const pr of people) pr.x0 = Math.max(pr.x0 - over, 0.06 * W);
    // Three people told to run to the same spot arrive one behind another.
    const taken = [];
    for (const pr of decl.people) {
      for (const w of pr.walks) {
        if (typeof w.to !== "number") continue;
        let goal = px(w.to);
        const back = goal >= pr.x0 ? -1 : 1;
        while (taken.some((q) => q.pr !== pr && Math.abs(q.t0 - w.t0) < 2 && Math.abs(q.goal - goal) < 0.1 * W)) goal += back * 0.11 * W;
        taken.push({ pr, t0: w.t0, goal });
        w.to = goal;
      }
    }
  }

  // --- a frame ----------------------------------------------------------------------------
  let backdrop = null;
  let laid = null;

  function render(ctx, t) {
    const place = stagePlace();
    if (!backdrop) {
      backdrop = new Canvas(W, H);
      place.draw(backdrop.getContext("2d"), 0);
      if (place.walls) {
        const taken = decl.things.filter((q) => !q.holder && q.spec.on !== "fill").map((q) => thingBox(q, 0));
        dress(backdrop.getContext("2d"), taken, place.floor, p, seedOf(input.place.key), place.walls);
      }
    }
    if (!laid) laid = layPlates(ctx, input, decl, where, revealTime);
    const v = view(decl.moves, seconds, t, where.targetPoint);
    ctx.save();
    ctx.fillStyle = p.night;
    ctx.fillRect(0, 0, W, H);
    applyView(ctx, v);
    ctx.drawImage(backdrop, 0, 0);
    custom(ctx, t, "back");
    const now = new Map(decl.things.map((q) => [q, rest(q, t)]));
    const held = (q) => now.get(q).holder;
    const based = (q) => now.get(q).base;
    const drawThing = (th) => {
      const [x, y] = thingFoot(th, t);
      // What stands on the floor darkens it underneath.
      if (th.spec.on === "floor" && !th.base && !th.carried && !th.spec.flat) {
        ctx.save();
        ctx.filter = "blur(10px)";
        ctx.beginPath();
        ctx.ellipse(x, y + 8, th.spec.w * th.scale * 0.56, 13, 0, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(0,0,0,0.55)";
        ctx.fill();
        ctx.restore();
      }
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(th.scale * th.flip, th.scale);
      th.spec.draw(ctx, thingState(th, t), t, p, seedOf(th.id + input.place.key), place, x, y);
      ctx.restore();
    };
    const items = [];
    const free = decl.things.filter((q) => !held(q) && !now.get(q).hidden && !now.get(q).flying);
    const people = [...decl.people].sort((a, b) => ground(a, personX(a, t).x) - ground(b, personX(b, t).x));
    // Whoever serves at a counter stands behind it: it is drawn over their legs.
    const over = new Set(free.filter((q) => q.name === "counter" && decl.people.some((pr) => pr.behind === q)));
    const front = (q) => q.front || over.has(q) || (based(q) && (based(q).front || over.has(based(q))));
    for (const th of free.filter((q) => q.spec.on !== "floor" && q.spec.on !== "fill")) drawThing(th);
    // A door and a railing are part of the wall: furniture stands in front of them.
    const standing = free.filter((q) => q.spec.on === "floor" && !based(q) && !front(q));
    for (const th of [...standing.filter((q) => q.spec.flat), ...standing.filter((q) => !q.spec.flat)]) drawThing(th);
    for (const th of free.filter((q) => based(q) && !front(q))) drawThing(th);
    const walkers = [];
    for (const pr of people) {
      if (t < pr.appear) continue; // not in yet: `enter` brings them in from off the frame
      const b = personBones(pr, t);
      rig.draw(ctx, b, pr.card);
      for (const th of decl.things.filter((q) => held(q) === pr && !now.get(q).hidden)) drawThing(th);
      walkers.push(b.hip[0]);
      const lowest = Math.max(b.ankle_f[1], b.ankle_n[1]) + 0.065 * b.size * 0.35;
      const seated = seatAt(pr, t);
      const entering = pr.walks.some((w) => w.from !== undefined && t >= w.t0 && t < w.t0 + ENTER_SECONDS);
      items.push({ id: pr.key, kind: "person", extra: pr.extra, entering, box: rig.box(b), screen: boxToScreen(v, rig.box(b)), gap: seated ? 0 : ground(pr, b.hip[0]) - lowest });
    }
    for (const th of free.filter((q) => q.spec.on === "fill")) {
      drawWater(ctx, place.support(W / 2, th.level), HERO * k(), thingState(th, t), t, p, walkers);
    }
    for (const th of free.filter((q) => q.spec.on === "floor" && !based(q) && front(q))) drawThing(th);
    for (const th of free.filter((q) => based(q) && front(q))) drawThing(th);
    for (const th of decl.things.filter((q) => now.get(q).flying && !now.get(q).hidden)) drawThing(th);
    for (const th of decl.things) {
      if (now.get(th).hidden || (held(th) && t < held(th).appear)) continue;
      const b = thingBox(th, t);
      const [x, y] = thingFoot(th, t);
      const stands = held(th) || now.get(th).flying ? "hand" : based(th) ? "thing" : th.spec.on;
      items.push({ id: th.id, kind: th.spec.on === "fill" ? "fill" : "thing", small: !!th.spec.small || !!th.spec.flat, on: stands, box: b, screen: boxToScreen(v, b), gap: 0 });
    }
    custom(ctx, t, "front");
    sceneDevices(ctx, t, decl.devices, p, where);
    darkness(ctx, t, decl.lights, people, p, personBones);
    // What burns lights what is near it, and shows through the dark.
    for (const th of decl.things.filter((q) => q.spec.glow && !now.get(q).hidden)) {
      const g = th.spec.glow(thingState(th, t));
      if (!(g.a > 0)) continue;
      const [x, y] = thingFoot(th, t);
      const [gx, gy] = [x + g.at[0] * th.scale * th.flip, y + g.at[1] * th.scale];
      const beat = 1 + 0.06 * Math.sin(t * 9.3) + 0.04 * Math.sin(t * 15.1 + 1);
      const fall = ctx.createRadialGradient(gx, gy, 0, gx, gy, g.r * th.scale * beat);
      fall.addColorStop(0, alpha(g.colour, g.a * beat));
      fall.addColorStop(0.35, alpha(g.colour, g.a * 0.45));
      fall.addColorStop(1, alpha(g.colour, 0));
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      ctx.fillStyle = fall;
      ctx.fillRect(gx - g.r * 1.2, gy - g.r * 1.2, g.r * 2.4, g.r * 2.4);
      ctx.restore();
    }
    ctx.restore();
    vignette(ctx);
    screenDevices(ctx, t, v, decl.devices, p, where);
    const shown = drawPlates(ctx, laid, t, v, p);
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

  return {
    api,
    run(box) {
      sandbox = box;
      box.run(api);
      stagePlace();
      settle();
    },
    render,
    declared: () => declared(decl, input, (name) => !!known(name)),
    ignored: () => [...new Set(decl.ignored)],
    frameProblems,
  };
}

// The canvas scene code draws on: everything a canvas does except text, which is ours.
function guarded(ctx) {
  return new Proxy(ctx, {
    get(target, prop) {
      if (prop === "fillText" || prop === "strokeText") {
        return () => {}; // text on screen is drawn by plates
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
