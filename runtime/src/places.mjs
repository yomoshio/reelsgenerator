// The kinds of places a beat can be set in. A place draws its background and says where
// the ground is under any x, so things and people stand on it instead of hanging in the air.

export const W = 1080, H = 1920;
export const SCENE_TOP = 180, SCENE_BOTTOM = 1150; // captions live below the scene
export const FLOOR = 1040;
export const HERO = 560; // px from soles to crown of an adult in a room

export function rng(seed) {
  let a = seed >>> 0 || 1;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function seedOf(text) {
  let h = 2166136261;
  for (const ch of String(text)) h = Math.imul(h ^ ch.codePointAt(0), 16777619);
  return h >>> 0;
}

export function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  if (k <= 1) [r, g, b] = [r * k, g * k, b * k];
  else [r, g, b] = [r + (255 - r) * (k - 1), g + (255 - g) * (k - 1), b + (255 - b) * (k - 1)];
  return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`;
}

export function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function vertical(ctx, x, y, w, h, stops) {
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  stops.forEach((c, i) => g.addColorStop(i / Math.max(stops.length - 1, 1), c));
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);
}

function beam(ctx, top, bottom, colour, a) {
  ctx.save();
  ctx.filter = "blur(40px)";
  ctx.beginPath();
  ctx.moveTo(...top[0]);
  ctx.lineTo(...top[1]);
  ctx.lineTo(...bottom[1]);
  ctx.lineTo(...bottom[0]);
  ctx.closePath();
  ctx.fillStyle = alpha(colour, a);
  ctx.fill();
  ctx.restore();
}

function wall(ctx, p, floor, seams = true) {
  vertical(ctx, 0, 0, W, floor, [p.night, p.wall, shade(p.wall, 0.78)]);
  if (seams) {
    ctx.strokeStyle = shade(p.wall, 0.88);
    ctx.lineWidth = 3;
    for (let x = -60; x < W; x += 270) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, floor - 18);
      ctx.stroke();
    }
  }
  ctx.fillStyle = shade(p.line, 1.1);
  ctx.fillRect(0, floor - 18, W, 22);
}

function ground(ctx, p, floor, lines = true) {
  vertical(ctx, 0, floor, W, H - floor, [p.floor, shade(p.floor, 0.6)]);
  if (!lines) return;
  ctx.strokeStyle = alpha(p.light, 0.06);
  ctx.lineWidth = 2;
  for (let i = 1; i <= 6; i++) {
    const y = floor + i * i * 9;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
}

function stars(ctx, seed, top, bottom, count = 50) {
  const r = rng(seed);
  for (let i = 0; i < count; i++) {
    ctx.beginPath();
    ctx.arc(r() * W, top + r() * (bottom - top), 1 + r() * 1.4, 0, 2 * Math.PI);
    ctx.fillStyle = `rgba(210,220,240,${0.25 + r() * 0.45})`;
    ctx.fill();
  }
}

// Every kind gives: `support(x, level)` the y of the ground under x (`level` picks a floor
// of a section), `scale` the height of an adult here, and `draw(ctx, t)` the background.
export function makePlace(kind, palette, opts = {}) {
  const p = palette;
  const seed = seedOf(opts.seed ?? kind);
  const floor = opts.floor ?? FLOOR;
  const flat = (y) => ({ support: () => y, scale: HERO });
  const make = {
    room: () => ({
      ...flat(floor),
      draw(ctx) {
        wall(ctx, p, floor);
        ground(ctx, p, floor);
        const x = (opts.light ?? 0.55) * W;
        beam(ctx, [[x - 70, 0], [x + 70, 0]], [[x - 330, floor + 60], [x + 330, floor + 60]], p.light, 0.09);
      },
    }),
    shop: () => ({
      ...flat(floor),
      draw(ctx) {
        vertical(ctx, 0, 0, W, floor, [p.night, shade(p.wall, 1.12), p.wall]);
        ctx.fillStyle = shade(p.line, 1.1);
        ctx.fillRect(0, floor - 18, W, 22);
        vertical(ctx, 0, floor, W, H - floor, [shade(p.floor, 1.3), p.floor]);
        ctx.strokeStyle = alpha(p.light, 0.08);
        ctx.lineWidth = 2;
        for (let x = -40; x < W + 40; x += 90) {
          ctx.beginPath();
          ctx.moveTo(x, floor);
          ctx.lineTo(x + (x - W / 2) * 0.6, SCENE_BOTTOM);
          ctx.stroke();
        }
        for (const x of [0.25, 0.75]) {
          ctx.fillStyle = "rgba(235,245,255,0.85)";
          ctx.fillRect(x * W - 120, SCENE_TOP + 20, 240, 12);
          beam(ctx, [[x * W - 120, SCENE_TOP + 30], [x * W + 120, SCENE_TOP + 30]], [[x * W - 300, floor + 40], [x * W + 300, floor + 40]], p.light, 0.07);
        }
      },
    }),
    stairwell: () => {
      const start = (opts.stairs ?? 0.55) * W, rise = 50, run = 56, steps = 9;
      return {
        scale: HERO,
        stairs: { start, rise, run, steps, floor },
        support(x) {
          if (x < start) return floor;
          const i = Math.min(Math.floor((x - start) / run) + 1, steps);
          return floor - i * rise;
        },
        draw(ctx) {
          wall(ctx, p, floor);
          ground(ctx, p, floor);
          for (let i = 0; i < steps; i++) {
            const sx = start + i * run, top = floor - (i + 1) * rise;
            ctx.fillStyle = shade(p.wall, 0.7 - i * 0.015);
            ctx.fillRect(sx, top, W - sx + 40, rise + 20);
            ctx.strokeStyle = shade(p.line, 1.25);
            ctx.lineWidth = 4;
            ctx.beginPath();
            ctx.moveTo(sx, top);
            ctx.lineTo(sx + run, top);
            ctx.stroke();
          }
          beam(ctx, [[start - 60, 0], [start + 60, 0]], [[start - 360, floor + 60], [start + 300, floor + 60]], p.light, 0.08);
        },
      };
    },
    section: () => {
      const floors = Math.max(2, Math.min(opts.floors ?? 9, 40));
      const groundY = SCENE_BOTTOM - 60, roof = SCENE_TOP + 70;
      const storey = (groundY - roof) / floors;
      const left = 150, right = 930;
      return {
        scale: storey * 0.78,
        floors,
        storey,
        bounds: [left, right],
        levelY: (n) => groundY - (Math.min(Math.max(n, 1), floors) - 1) * storey,
        support(x, level = 1) {
          return groundY - (Math.min(Math.max(level, 1), floors) - 1) * storey;
        },
        draw(ctx) {
          vertical(ctx, 0, 0, W, H, [p.night, shade(p.night, 1.15), shade(p.night, 0.8)]);
          stars(ctx, seed, 0, roof - 10);
          ctx.fillStyle = shade(p.wall, 0.9);
          ctx.fillRect(left, roof, right - left, groundY - roof);
          for (let k = 1; k <= floors; k++) {
            const fy = groundY - (k - 1) * storey;
            ctx.fillStyle = shade(p.line, 1.4);
            ctx.fillRect(left, fy - 8, right - left, 10);
            ctx.fillStyle = shade(p.night, 1.3);
            for (const wx of [left + 70, left + 240]) ctx.fillRect(wx, fy - storey * 0.72, 90, storey * 0.42);
            const sx = right - 230;
            ctx.strokeStyle = shade(p.line, 1.6);
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(sx, fy);
            for (let i = 0; i < 6; i++) {
              ctx.lineTo(sx + i * 30, fy - (i * storey) / 6);
              ctx.lineTo(sx + (i + 1) * 30, fy - (i * storey) / 6);
            }
            ctx.stroke();
            if (opts.numbers !== false) {
              ctx.fillStyle = alpha(p.light, 0.5);
              ctx.font = `${Math.max(14, storey * 0.22)}px Plate`;
              ctx.fillText(`${(opts.first ?? 1) + k - 1}`, left - 60, fy - storey * 0.35);
            }
          }
          ctx.fillStyle = shade(p.line, 1.4);
          ctx.fillRect(left - 14, roof - 20, right - left + 28, 20);
          ctx.fillRect(left - 14, roof, 14, groundY - roof);
          ctx.fillRect(right, roof, 14, groundY - roof);
          ctx.fillStyle = shade(p.floor, 0.8);
          ctx.fillRect(0, groundY, W, H - groundY);
        },
      };
    },
    street: () => ({
      ...flat(floor + 30),
      draw(ctx) {
        vertical(ctx, 0, 0, W, floor, [p.night, shade(p.night, 1.25)]);
        stars(ctx, seed, 0, SCENE_TOP + 120, 30);
        const r = rng(seed);
        let x = -40;
        while (x < W) {
          const bw = 220 + r() * 160, top = SCENE_TOP + 60 + r() * 220;
          ctx.fillStyle = shade(p.wall, 0.8 + r() * 0.2);
          ctx.fillRect(x, top, bw - 12, floor - top);
          for (let wy = top + 40; wy < floor - 120; wy += 90)
            for (let wx = x + 30; wx < x + bw - 60; wx += 70) {
              ctx.fillStyle = r() < 0.18 ? alpha(p.warm ?? "#FFD696", 0.75) : shade(p.night, 1.2);
              ctx.fillRect(wx, wy, 34, 48);
            }
          x += bw;
        }
        ctx.fillStyle = shade(p.line, 1.2);
        ctx.fillRect(0, floor + 10, W, 20);
        ground(ctx, p, floor + 30, false);
      },
    }),
    outdoors: () => ({
      ...flat(floor),
      draw(ctx) {
        vertical(ctx, 0, 0, W, floor, [p.night, shade(p.wall, 0.9)]);
        stars(ctx, seed, 0, floor - 300, 60);
        ctx.fillStyle = shade(p.floor, 1.2);
        ctx.beginPath();
        ctx.moveTo(0, floor - 40);
        for (let x = 0; x <= W; x += 60) ctx.lineTo(x, floor - 40 - 20 * Math.sin(x / 170 + seed));
        ctx.lineTo(W, floor);
        ctx.lineTo(0, floor);
        ctx.fill();
        ground(ctx, p, floor, false);
      },
    }),
    custom: () => ({
      ...flat(floor),
      draw(ctx) {
        vertical(ctx, 0, 0, W, H, [p.night, shade(p.night, 1.2), shade(p.night, 0.8)]);
      },
    }),
  };
  if (!make[kind]) throw new ScriptError(`no place kind '${kind}'; kinds: ${Object.keys(make).join(", ")}`);
  return { kind, floor, ...make[kind]() };
}

export class ScriptError extends Error {}

export const KINDS = ["room", "shop", "stairwell", "section", "street", "outdoors", "custom"];
