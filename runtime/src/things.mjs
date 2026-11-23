// Things a scene can put on stage. Each is drawn around its foot, the middle of its bottom
// edge, standing on the ground the place gives under it; wall things hang at a fixed height
// above that ground. A thing knows its size, the named parts a hand can reach or a person
// can sit on, and how it looks at each of its states.

import { readFileSync } from "node:fs";
import { Canvas, loadImage } from "skia-canvas";
import { H, W, alpha, rng, seedOf, shade, ScriptError } from "./places.mjs";

// A block with a body: lit from above, darker toward the floor, a contour around it, a
// line of light on its top edge and a shadow down the side turned from the light. Small
// details, a key of a keypad, stay flat.
const box = (ctx, x, y, w, h, colour) => {
  if (Math.min(w, h) < 12 || colour.startsWith("rgba")) {
    ctx.fillStyle = colour;
    ctx.fillRect(x, y, w, h);
    return;
  }
  ctx.fillStyle = OUT;
  ctx.fillRect(x - 2.5, y - 2.5, w + 5, h + 5);
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, shade(colour, 1.12));
  g.addColorStop(1, shade(colour, 0.8));
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = alpha("#FFFFFF", 0.16);
  ctx.fillRect(x, y, w, Math.min(3, h / 4));
  ctx.fillStyle = "rgba(0,0,0,0.22)";
  ctx.fillRect(x, y, Math.min(w * 0.12, 9), h);
};
// The top of a table or a seat, seen a little from above: it runs back from the front edge
// at (x, y), `depth` px up the picture, narrowing as it goes.
const slab = (ctx, x, y, w, depth, colour) => {
  const skew = depth * 0.55;
  const path = (grow) => {
    ctx.beginPath();
    ctx.moveTo(x - grow, y + grow);
    ctx.lineTo(x + w + grow, y + grow);
    ctx.lineTo(x + w - skew + grow, y - depth - grow);
    ctx.lineTo(x + skew - grow, y - depth - grow);
    ctx.closePath();
  };
  path(2.5);
  ctx.fillStyle = OUT;
  ctx.fill();
  path(0);
  const g = ctx.createLinearGradient(0, y - depth, 0, y);
  g.addColorStop(0, shade(colour, 1.05));
  g.addColorStop(1, shade(colour, 1.32));
  ctx.fillStyle = g;
  ctx.fill();
};
const OUT = "rgba(6,8,14,0.9)";
const line = (ctx, pts, width, colour) => {
  ctx.beginPath();
  ctx.moveTo(...pts[0]);
  for (const q of pts.slice(1)) ctx.lineTo(...q);
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.strokeStyle = colour;
  ctx.stroke();
};
const round = (ctx, x, y, w, h, r, colour) => {
  if (Math.min(w, h) >= 12) {
    ctx.beginPath();
    ctx.roundRect(x - 2.5, y - 2.5, w + 5, h + 5, r + 2);
    ctx.fillStyle = OUT;
    ctx.fill();
  }
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, shade(colour, 1.12));
  g.addColorStop(1, shade(colour, 0.8));
  ctx.fillStyle = Math.min(w, h) >= 12 ? g : colour;
  ctx.fill();
};

const WOOD = "#70523A", WOOD_DARK = "#4E3828", STEEL = "#68727F", STEEL_LIT = "#B6C0CC";

// on: floor stands on the ground; wall hangs `lift` px above it; ceiling hangs from the top;
// tall runs from the ground to the top of the frame; fill covers the whole place.
export const FIXTURES = {
  door: {
    w: 250, h: 520, on: "floor", flat: true, parts: { handle: [80, -270], middle: [0, -260] },
    draw(ctx, s, t, p) {
      box(ctx, -143, -538, 286, 538, shade(p.line, 1.05));
      const g = ctx.createLinearGradient(0, -520, 0, 0);
      g.addColorStop(0, "#40342C");
      g.addColorStop(1, "#302721");
      ctx.fillStyle = g;
      const open = Math.min(Math.max(s, 0), 1);
      ctx.fillRect(-125, -520, 250 * (1 - open * 0.75), 520);
      if (open > 0) box(ctx, -125 + 250 * (1 - open * 0.75), -520, 250 * open * 0.75, 520, "#0A0C10");
      for (const [py, ph] of [[-480, 190], [-250, 210]]) {
        ctx.beginPath();
        ctx.roundRect(-91, py, 182 * (1 - open * 0.75), ph, 6);
        ctx.lineWidth = 5;
        ctx.strokeStyle = "#241D19";
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(81 - open * 190, -270, 11, 0, 2 * Math.PI);
      ctx.fillStyle = STEEL_LIT;
      ctx.fill();
    },
  },
  window: {
    w: 320, h: 380, on: "wall", lift: 430, parts: { glass: [0, -190] },
    draw(ctx, s, t, p, seed) {
      const r = rng(seed);
      box(ctx, -176, -396, 352, 412, shade(p.line, 1.1));
      const g = ctx.createLinearGradient(0, -380, 0, 0);
      g.addColorStop(0, "#121E34");
      g.addColorStop(0.6, "#223A5C");
      g.addColorStop(1, "#284862");
      ctx.fillStyle = g;
      ctx.fillRect(-160, -380, 320, 380);
      for (let i = 0; i < 14; i++) {
        ctx.beginPath();
        ctx.arc(-160 + r() * 320, -380 + r() * 170, 1.2 + r() * 1.4, 0, 2 * Math.PI);
        ctx.fillStyle = `rgba(220,228,240,${0.35 + r() * 0.4})`;
        ctx.fill();
      }
      ctx.beginPath();
      ctx.moveTo(-160, 0);
      let bx = -160;
      while (bx < 160) {
        const bw = 26 + r() * 34, bh = 30 + r() * 120;
        ctx.lineTo(bx, -60 - bh);
        ctx.lineTo(Math.min(bx + bw, 160), -60 - bh);
        bx += bw;
      }
      ctx.lineTo(160, 0);
      ctx.fillStyle = "#101826";
      ctx.fill();
      line(ctx, [[0, -380], [0, 0]], 12, shade(p.line, 1.1));
      line(ctx, [[-160, -228], [160, -228]], 12, shade(p.line, 1.1));
      box(ctx, -190, 16, 380, 18, shade(p.line, 1.3));
    },
  },
  bed: {
    w: 440, h: 330, on: "floor", parts: { seat: [40, -200], pillow: [-140, -270] },
    draw(ctx) {
      round(ctx, -240, -330, 36, 330, 8, WOOD_DARK);
      box(ctx, -230, -190, 420, 70, WOOD);
      round(ctx, -220, -250, 404, 64, 22, "#B2BAC6");
      round(ctx, -206, -300, 126, 62, 26, "#D6DCE4");
      ctx.beginPath();
      ctx.moveTo(-110, -252);
      ctx.bezierCurveTo(-10, -270, 130, -262, 194, -240);
      ctx.lineTo(208, -150);
      ctx.bezierCurveTo(110, -160, -30, -150, -110, -176);
      ctx.closePath();
      ctx.fillStyle = "#485C80";
      ctx.fill();
      for (const lx of [-224, 168]) box(ctx, lx, -120, 16, 120, WOOD_DARK);
    },
  },
  bench: {
    w: 360, h: 130, on: "floor", parts: { seat: [0, -125] },
    draw(ctx) {
      for (const lx of [-142, 126]) box(ctx, lx, -124, 12, 98, shade(WOOD_DARK, 0.7));
      for (const lx of [-166, 150]) box(ctx, lx, -98, 16, 98, WOOD_DARK);
      slab(ctx, -180, -130, 360, 30, WOOD);
      box(ctx, -180, -130, 360, 24, WOOD);
      box(ctx, -180, -106, 360, 8, WOOD_DARK);
    },
  },
  chair: {
    w: 130, h: 270, on: "floor", parts: { seat: [0, -135] },
    draw(ctx) {
      box(ctx, 34, -150, 12, 122, shade(WOOD_DARK, 0.7));
      box(ctx, -65, -270, 16, 270, WOOD_DARK);
      box(ctx, 50, -122, 14, 122, WOOD_DARK);
      box(ctx, -60, -262, 14, 112, WOOD);
      box(ctx, -49, -250, 40, 14, WOOD);
      box(ctx, -49, -205, 40, 14, WOOD);
      slab(ctx, -65, -140, 130, 26, WOOD);
      box(ctx, -65, -140, 130, 18, WOOD);
    },
  },
  fireplace: {
    w: 360, h: 400, on: "floor", back: true, state: 2, parts: { hearth: [0, -90], fire: [0, -90], top: [0, -330], mantel: [0, -330] },
    // The light a fire gives the room: none cold, a little from embers, more when it roars.
    glow: (s) => ({ at: [0, -110], r: 260 + 190 * Math.min(s, 3), a: [0, 0.2, 0.42, 0.6][Math.round(Math.min(Math.max(s, 0), 3))], colour: "#FF9A3C" }),
    draw(ctx, s, t, p, seed) {
      const STONE = "#6E6660", STONE_DARK = "#4A4541";
      box(ctx, -180, -330, 360, 330, STONE);
      for (let row = 0; row < 7; row++) {
        for (let col = -3; col < 4; col++) {
          const bx = col * 56 + (row % 2 ? 28 : 0) - 26, by = -322 + row * 46;
          if (bx < -176 || bx + 52 > 176) continue;
          ctx.fillStyle = shade(STONE, 0.86 + ((row * 7 + col * 13 + 40) % 5) * 0.05);
          ctx.fillRect(bx, by, 52, 42);
        }
      }
      round(ctx, -116, -236, 232, 236, 22, "#0B0907");
      slab(ctx, -200, -362, 400, 30, WOOD);
      box(ctx, -200, -362, 400, 34, WOOD);
      box(ctx, -190, -24, 380, 24, STONE_DARK);
      const heat = Math.min(Math.max(s, 0), 3);
      // Logs, and the coals between them, which glow as long as there is any heat.
      for (const [lx, a] of [[-52, -0.12], [34, 0.15]]) {
        ctx.save();
        ctx.translate(lx, -42);
        ctx.rotate(a);
        round(ctx, -62, -15, 124, 30, 14, heat > 0.2 ? "#3B2416" : "#2A211B");
        ctx.restore();
      }
      if (heat > 0.05) {
        for (let i = 0; i < 9; i++) {
          const pulse = 0.55 + 0.45 * Math.sin(t * (2 + (i % 3)) + i * 1.7);
          ctx.fillStyle = `rgba(255,${90 + 60 * pulse},30,${Math.min(heat, 1) * (0.5 + 0.5 * pulse)})`;
          ctx.beginPath();
          ctx.ellipse(-88 + i * 22, -30 - (i % 2) * 8, 11, 6, 0, 0, 2 * Math.PI);
          ctx.fill();
        }
      }
      const tall = Math.max(0, heat - 1);
      if (tall > 0.02) {
        const tongue = (x, w, h, colour, phase) => {
          const sway = Math.sin(t * 5.3 + phase) * w * 0.35 + Math.sin(t * 8.9 + phase * 2) * w * 0.15;
          const lift = h * (0.86 + 0.14 * Math.sin(t * 7.1 + phase * 1.3));
          ctx.beginPath();
          ctx.moveTo(x - w, -36);
          ctx.bezierCurveTo(x - w * 1.1, -36 - lift * 0.5, x + sway - w * 0.3, -36 - lift * 0.7, x + sway, -36 - lift);
          ctx.bezierCurveTo(x + sway + w * 0.4, -36 - lift * 0.6, x + w * 1.1, -36 - lift * 0.45, x + w, -36);
          ctx.closePath();
          ctx.fillStyle = colour;
          ctx.fill();
        };
        const k = 0.55 + 0.45 * Math.min(tall, 2) / 2 + (tall > 1 ? 0.25 : 0);
        ctx.save();
        ctx.beginPath();
        ctx.rect(-116, -236, 232, 236);
        ctx.clip();
        for (const [x, w, h, ph] of [[-60, 30, 120, 0], [48, 32, 130, 2.1], [-8, 44, 185, 4.0], [-34, 26, 150, 1.2], [26, 26, 160, 3.1]]) tongue(x, w, h * k, "#E2571B", ph + (seed % 5));
        for (const [x, w, h, ph] of [[-40, 22, 105, 0.6], [30, 24, 115, 2.6], [-4, 32, 150, 4.4]]) tongue(x, w, h * k, "#FF9E2C", ph);
        for (const [x, w, h, ph] of [[-14, 14, 80, 1.1], [14, 14, 88, 3.4]]) tongue(x, w, h * k, "#FFE7A0", ph);
        ctx.restore();
      }
    },
  },
  table: {
    w: 380, h: 240, on: "floor", parts: { top: [0, -240] },
    draw(ctx) {
      for (const lx of [-150, 134]) box(ctx, lx, -236, 14, 206, shade(WOOD_DARK, 0.7));
      for (const lx of [-176, 160]) box(ctx, lx, -206, 18, 206, WOOD_DARK);
      box(ctx, -168, -110, 336, 14, WOOD_DARK);
      slab(ctx, -190, -240, 380, 34, WOOD);
      box(ctx, -190, -240, 380, 26, WOOD);
      box(ctx, -190, -214, 380, 8, WOOD_DARK);
    },
  },
  counter: {
    w: 440, h: 260, on: "floor", parts: { top: [0, -260], front: [0, -130] },
    draw(ctx, s, t, p) {
      box(ctx, -210, -232, 420, 232, shade(p.wall, 1.25));
      for (const cx of [-140, 0, 140]) box(ctx, cx - 58, -200, 116, 170, shade(p.wall, 1.12));
      slab(ctx, -220, -260, 440, 34, shade(p.light, 0.55));
      box(ctx, -220, -260, 440, 28, shade(p.light, 0.55));
      box(ctx, 40, -320, 120, 60, "#2A2F38");
      box(ctx, 52, -312, 96, 38, alpha(p.key ?? "#F2C230", 0.35));
    },
  },
  shelf: {
    w: 360, h: 520, on: "floor", back: true, parts: { top: [0, -520], middle: [0, -300] },
    draw(ctx, s, t, p, seed) {
      const r = rng(seed);
      slab(ctx, -180, -518, 360, 24, shade(p.wall, 0.9));
      box(ctx, -180, -520, 360, 520, shade(p.wall, 0.75));
      const tones = ["#B8443A", "#D9B44A", "#4A7A9A", "#6A8A4A", "#C6C0B0", "#8A5A9A"];
      for (let k = 0; k < 5; k++) {
        const y = -500 + k * 100;
        box(ctx, -180, y + 86, 360, 12, shade(p.line, 1.5));
        let x = -170;
        while (x < 160) {
          const w = 26 + r() * 30, h = 40 + r() * 40;
          box(ctx, x, y + 86 - h, w - 4, h, tones[Math.floor(r() * tones.length)]);
          x += w;
        }
      }
    },
  },
  wardrobe: {
    w: 220, h: 420, on: "floor", back: true, parts: { door: [50, -220], top: [0, -420] },
    draw(ctx, s) {
      const fallen = Math.min(Math.max(s, 0), 1);
      ctx.save();
      ctx.translate(110, 0);
      ctx.rotate((-fallen * 70 * Math.PI) / 180);
      ctx.translate(-110, 0);
      slab(ctx, -110, -418, 220, 24, WOOD_DARK);
      round(ctx, -110, -420, 220, 420, 6, WOOD_DARK);
      box(ctx, -96, -406, 92, 392, WOOD);
      box(ctx, 4, -406, 92, 392, WOOD);
      for (const hx of [-18, 18]) {
        ctx.beginPath();
        ctx.arc(hx, -220, 6, 0, 2 * Math.PI);
        ctx.fillStyle = STEEL_LIT;
        ctx.fill();
      }
      ctx.restore();
    },
  },
  atm: {
    w: 180, h: 400, on: "floor", back: true, parts: { screen: [0, -290], slot: [0, -210], keys: [0, -170] },
    draw(ctx, s, t, p) {
      slab(ctx, -90, -398, 180, 22, "#4A525E");
      round(ctx, -90, -400, 180, 400, 10, "#4A525E");
      box(ctx, -90, -400, 180, 46, p.solved ?? "#2E9E5B");
      ctx.fillStyle = "#0E1218";
      ctx.fillRect(-60, -336, 120, 90);
      const state = Math.round(s);
      const glow = state === 2 ? p.threat : state === 1 ? "#5AB0E0" : "#1C3A52";
      ctx.fillStyle = alpha(glow.startsWith("#") ? glow : "#5AB0E0", state ? 0.85 : 0.6);
      ctx.fillRect(-54, -330, 108, 78);
      box(ctx, -40, -214, 80, 8, "#14181E");
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) box(ctx, -36 + j * 26, -190 + i * 22, 20, 14, "#8A929E");
      box(ctx, -70, -60, 140, 10, "#14181E");
    },
  },
  lamp: {
    w: 120, h: 160, on: "ceiling", parts: { bulb: [0, 150] },
    draw(ctx, s, t, p) {
      const on = Math.min(Math.max(s, 0), 1);
      line(ctx, [[0, 0], [0, 100]], 4, "#20242C");
      ctx.beginPath();
      ctx.moveTo(-60, 150);
      ctx.lineTo(-22, 100);
      ctx.lineTo(22, 100);
      ctx.lineTo(60, 150);
      ctx.closePath();
      ctx.fillStyle = "#3A404C";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, 150, 14, 0, 2 * Math.PI);
      ctx.fillStyle = on > 0.5 ? (p.warm ?? "#FFD696") : "#4A4A50";
      ctx.fill();
      if (on > 0) {
        ctx.save();
        ctx.filter = "blur(30px)";
        ctx.beginPath();
        ctx.moveTo(-50, 160);
        ctx.lineTo(50, 160);
        ctx.lineTo(320, 900);
        ctx.lineTo(-320, 900);
        ctx.closePath();
        ctx.fillStyle = alpha(p.warm ?? "#FFD696", 0.12 * on);
        ctx.fill();
        ctx.restore();
      }
    },
  },
  railing: {
    w: 520, h: 190, on: "floor", flat: true, parts: { rail: [0, -190] },
    draw(ctx, s, t, p, seed, place, x) {
      const st = place.stairs;
      if (st) {
        const hand = 190, x0 = st.start - x - 40, y0 = st.floor;
        line(ctx, [[x0, -hand], [x0 + 40 + st.steps * st.run, -st.steps * st.rise - hand]], 12, STEEL);
        for (let i = 0; i <= st.steps; i += 2) {
          const bx = st.start - x + i * st.run - 10;
          line(ctx, [[bx, -i * st.rise - hand], [bx, -i * st.rise]], 6, shade(STEEL, 0.75));
        }
        return;
      }
      line(ctx, [[-260, -190], [260, -190]], 12, STEEL);
      for (let bx = -250; bx <= 250; bx += 50) line(ctx, [[bx, -190], [bx, 0]], 6, shade(STEEL, 0.75));
    },
  },
  pipe: {
    w: 44, h: 0, on: "tall", parts: { middle: [0, -400], top: [0, -800] },
    draw(ctx, s, t, p, seed, place, x, y) {
      box(ctx, -18, -y, 36, y + 6, STEEL);
      box(ctx, -4, -y, 12, y + 6, alpha("#B6C0CC", 0.6));
      for (let k = 1; k < 4; k++) box(ctx, -24, -k * 260, 48, 14, shade(STEEL, 0.8));
    },
  },
  radiator: {
    w: 280, h: 170, on: "wall", lift: 60, parts: { top: [0, -170] },
    draw(ctx) {
      for (let i = 0; i < 9; i++) round(ctx, -140 + i * 31, -170, 26, 170, 10, i % 2 ? "#D8DCE2" : "#C8CCD4");
      box(ctx, -150, -20, 300, 10, "#A8ACB4");
    },
  },
  water: {
    w: W, h: 0, on: "fill", parts: { surface: [0, 0] },
    draw() {},
  },
};

// Water depth for each state, in units of an adult's height: ankle, knee, waist, chest.
export const WATER = [0.07, 0.27, 0.48, 0.66];

export function drawWater(ctx, ground, hero, level, t, p, walkers) {
  const k = Math.min(Math.floor(level), WATER.length - 2);
  const f = level - k;
  const depth = WATER[k] + (WATER[k + 1] - WATER[k]) * f;
  const surface = ground - depth * hero;
  const wave = (x) => surface + 5 * Math.sin(x / 70 + t * 2.1) + 3 * Math.sin(x / 23 - t * 3.3);
  ctx.beginPath();
  ctx.moveTo(0, H);
  for (let x = 0; x <= W + 40; x += 40) ctx.lineTo(x, wave(x));
  ctx.lineTo(W, H);
  ctx.closePath();
  const g = ctx.createLinearGradient(0, surface, 0, H);
  g.addColorStop(0, alpha(p.water ?? "#346880", 0.5));
  g.addColorStop(1, alpha(p.water ?? "#346880", 0.85));
  ctx.fillStyle = g;
  ctx.fill();
  for (let x = 0; x < W; x += 40) line(ctx, [[x, wave(x)], [x + 24, wave(x)]], 2.5, alpha(p.light, 0.45));
  for (const wx of walkers) {
    const ring = (t * 0.8 + wx / 300) % 1;
    ctx.beginPath();
    ctx.ellipse(wx, surface, 40 + 60 * ring, 6 + 6 * ring, 0, 0, 2 * Math.PI);
    ctx.lineWidth = 2;
    ctx.strokeStyle = alpha(p.light, 0.55 * (1 - ring));
    ctx.stroke();
  }
  return surface;
}

// A thing from the library: an SVG drawn flat in one colour of the palette, `h` px tall in
// a room.
// Library things a hand holds. The library has no sizes: without this a walkie-talkie
// stands as tall as a wardrobe.
const SMALL = /phone|walkie|radio|flashlight|torch|lantern|candle|key|lock|card|coin|wallet|cup|mug|glass|bottle|book|note|letter|paper|pen|knife|spoon|fork|plate|watch|clock|lighter|match|remote|tablet|camera|ticket|ring|pill|battery|bag|can|jar|toy/;

export async function libraryThing(name, file, colour, h = SMALL.test(name) ? 90 : 260) {
  let svg = readFileSync(file, "utf8");
  svg = svg.replace(/fill="(?!none)[^"]*"/g, `fill="${colour}"`).replace(/fill:\s*(?!none)[^;"]+/g, `fill:${colour}`);
  if (!/fill=/.test(svg)) svg = svg.replace(/<path/g, `<path fill="${colour}"`);
  const flat = await loadImage(Buffer.from(svg));
  const w = (h * flat.width) / Math.max(flat.height, 1);
  // The silhouette gets a body once, when it is loaded: light from above, a dark contour.
  const pad = 6, k = 2;
  const made = new Canvas((w + 2 * pad) * k, (h + 2 * pad) * k);
  const c = made.getContext("2d");
  c.scale(k, k);
  for (let a = 0; a < 8; a++) c.drawImage(flat, pad + Math.cos((a * Math.PI) / 4) * 2.5, pad + Math.sin((a * Math.PI) / 4) * 2.5, w, h);
  c.globalCompositeOperation = "source-in";
  c.fillStyle = OUT;
  c.fillRect(0, 0, w + 2 * pad, h + 2 * pad);
  const body = new Canvas((w + 2 * pad) * k, (h + 2 * pad) * k);
  const d = body.getContext("2d");
  d.scale(k, k);
  d.drawImage(flat, pad, pad, w, h);
  d.globalCompositeOperation = "source-atop";
  const g = d.createLinearGradient(0, pad, 0, pad + h);
  g.addColorStop(0, "rgba(255,255,255,0.3)");
  g.addColorStop(0.5, "rgba(255,255,255,0)");
  g.addColorStop(1, "rgba(0,0,0,0.38)");
  d.fillStyle = g;
  d.fillRect(0, 0, w + 2 * pad, h + 2 * pad);
  c.globalCompositeOperation = "source-over";
  c.drawImage(body, 0, 0, w + 2 * pad, h + 2 * pad);
  return {
    w, h, on: "floor", small: h < 120, parts: { top: [0, -h], middle: [0, -h / 2] },
    draw(ctx) {
      ctx.drawImage(made, -w / 2 - pad, -h - pad, w + 2 * pad, h + 2 * pad);
    },
  };
}

export function spec(name, library) {
  const found = FIXTURES[name] ?? library[name];
  if (!found) {
    const known = [...Object.keys(FIXTURES), ...Object.keys(library)];
    const close = known.filter((k) => k.includes(name.slice(0, 3)) || name.includes(k.slice(0, 3)));
    throw new ScriptError(
      `no thing '${name}'` + (close.length ? `; did you mean ${close.join(", ")}?` : `; things: ${known.join(", ")}`),
    );
  }
  return found;
}

export { seedOf };
