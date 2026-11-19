// The stage a scene's code builds and the frames drawn from it. Scene code runs once and
// only declares: the place, things, people, what they do and when, camera moves, light and
// devices. Every frame is then computed from those declarations for its moment, so motion
// is smooth to a fraction of a pixel and nothing changes that the code did not ask for.
// Where things are at a moment is motion.mjs; the camera, light, devices, plates and the
// checks of what was declared each have a module of their own.

import "./canvas.mjs";
import { Canvas } from "skia-canvas";
import { FLOOR, H, HERO, SCENE_BOTTOM, SCENE_TOP, ScriptError, W, makePlace, seedOf } from "./places.mjs";
import { drawWater, spec } from "./things.mjs";
import * as rig from "./rig.mjs";
import { problems as frameProblems } from "./layout.mjs";
import { bare, makeClock } from "./clock.mjs";
import { makeMotion, px } from "./motion.mjs";
import { applyView, boxToScreen, view } from "./camera.mjs";
import { darkness, vignette } from "./light.mjs";
import { DEVICES, sceneDevices, screenDevices } from "./devices.mjs";
import { drawPlates, layPlates } from "./platelayout.mjs";
import { declared } from "./checks.mjs";

export { bare };

export function makeStage(input, library = {}) {
  const p = input.palette;
  const seconds = input.seconds;
  const { at, time, revealTime } = makeClock(input.words, seconds);
  const cast = Object.fromEntries(input.characters.map((c) => [c.key, c]));
  const decl = { place: null, things: [], people: [], moves: [], lights: [], devices: [], draws: [], events: 0 };
  let sandbox = null;

  // --- the place --------------------------------------------------------------------------
  function setPlace(kind, opts = {}) {
    const chosen = kind ?? input.place.kind;
    decl.place = makePlace(chosen, p, { seed: input.place.key, ...opts });
    return decl.place;
  }
  const stagePlace = () => decl.place ?? setPlace();
  const where = makeMotion(decl, stagePlace);
  const { k, thingState, thingFoot, thingBox, personX, seatAt, personBones, ground } = where;

  // --- things -----------------------------------------------------------------------------
  function thing(name, opts = {}) {
    const s = spec(name, library);
    const count = decl.things.filter((t) => t.name === name).length;
    const base = opts.on?.__ref ?? null;
    if (opts.on && (!base || base.kind !== "thing")) throw new ScriptError("`on` takes a thing, such as { on: table }");
    if (base && !["top", "seat"].some((q) => base.spec.parts[q])) throw new ScriptError(`nothing can stand on '${base.name}'; it has no top or seat`);
    const t = {
      kind: "thing", name, id: count ? `${name}#${count + 1}` : name, spec: s, base,
      x: opts.x === undefined && base ? null : px(opts.x ?? 0.5), level: opts.level ?? opts.floor ?? 1,
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

  function light(level, o = {}) {
    decl.lights.push({ t: time(o.at), level: Math.min(Math.max(level, 0), 1), flicker: !!o.flicker, until: o.until !== undefined ? time(o.until) : null });
    decl.events++;
  }

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
    W, H, floor: FLOOR, seconds, words: input.words.map((w) => w.text),
    place: (kind, opts) => (setPlace(kind, opts), undefined),
    thing, person, camera, light, device, draw, at,
  };

  // --- a frame ----------------------------------------------------------------------------
  let backdrop = null;
  let laid = null;

  function render(ctx, t) {
    const place = stagePlace();
    if (!backdrop) {
      backdrop = new Canvas(W, H);
      place.draw(backdrop.getContext("2d"), 0);
    }
    if (!laid) laid = layPlates(ctx, input, decl, where, revealTime);
    const v = view(decl.moves, seconds, t, where.targetPoint);
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
    for (const th of decl.things.filter((q) => q.spec.on === "floor" && !q.front && !q.base)) drawThing(th);
    for (const th of decl.things.filter((q) => q.base && !q.front)) drawThing(th);
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
      drawWater(ctx, place.support(W / 2, th.level), HERO * k(), thingState(th, t), t, p, walkers);
    }
    for (const th of decl.things.filter((q) => q.spec.on === "floor" && q.front)) drawThing(th);
    for (const th of decl.things) {
      const b = thingBox(th, t);
      const [x, y] = thingFoot(th, t);
      const stands = th.base ? "thing" : th.spec.on;
      items.push({ id: th.id, kind: th.spec.on === "fill" ? "fill" : "thing", on: stands, box: b, screen: boxToScreen(v, b), gap: stands === "floor" ? place.support(x, th.level) - y : 0 });
    }
    custom(ctx, t, "front");
    sceneDevices(ctx, t, decl.devices, p, where);
    darkness(ctx, t, decl.lights, people, p, personBones);
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
    },
    render,
    declared: () => declared(decl, input),
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
