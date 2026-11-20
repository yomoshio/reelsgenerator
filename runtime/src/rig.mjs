// The puppet every person is drawn with. A card says how a person looks; a pose is a set of
// joint angles; between poses the angles ease, and on top of any pose the figure breathes
// and sways a little, so nobody ever stands frozen. People are never drawn any other way.

export const EASE = 0.45; // seconds a change of pose takes
export const WALK_STEP = 0.55; // seconds a step takes

// Lengths in units of the figure's height.
const HEAD = 0.092, NECK = 0.022, TORSO = 0.29;
const SHOULDER = 0.092, HIP = 0.062;
const UPPER = 0.165, FORE = 0.15, HAND = 0.03;
const THIGH = 0.222, SHIN = 0.212, FOOT = 0.065;
const ARM_W = 0.052, LEG_W = 0.072;

// Angles in degrees: 0 points straight down, 90 to the front. The lower bone of a limb is
// given relative to the upper one. "_n" is the near limb, "_f" the far one.
const STAND = {
  lean: 0, head: 0, nod: 0,
  arm_f: -7, fore_f: 16, arm_n: 6, fore_n: 20,
  leg_f: -6, shin_f: 2, leg_n: 5, shin_n: 1,
};
export const POSES = {
  stand: {},
  walk: {},
  listen: { head: 12, arm_n: 105, fore_n: 130 },
  look_down: { head: 8, nod: 0.5, lean: 4, arm_f: -14, arm_n: 14 },
  sit: { leg_f: 82, shin_f: -84, leg_n: 88, shin_n: -90, arm_f: 18, fore_f: 40, arm_n: 26, fore_n: 44, lean: -3 },
  hold: { arm_f: 20, fore_f: 95, arm_n: 25, fore_n: 90 },
  knock: { arm_n: 75, fore_n: 60 },
  point: { arm_n: 100, fore_n: 0 },
  reach: { arm_n: 80, fore_n: 10 },
  arms_out: { arm_f: -70, fore_f: -10, arm_n: 70, fore_n: 10 },
};

const SKIN = { light: "#E8C0A0", medium: "#C69670", dark: "#7A543A" };
const RIM = "rgba(160,178,210,0.1)"; // the faint light from behind that lifts a figure off a dark wall
const OUT = "rgba(9,12,22,0.42)"; // the contour: a soft dark edge, never a black line

// What a face shows. `tilt` turns the brows: above zero the inner ends go up, worry; below,
// down, anger. `open` is how wide the eyes are, `mouth` the curve of the lips from a frown
// (-1) to a smile (1), `gape` how far the mouth is open.
export const MOODS = {
  neutral: { tilt: 0, lift: 0, open: 1, mouth: 0, gape: 0 },
  happy: { tilt: 0, lift: 0.3, open: 0.85, mouth: 1, gape: 0.15 },
  sad: { tilt: 0.6, lift: 0, open: 0.8, mouth: -0.8, gape: 0 },
  worried: { tilt: 0.8, lift: 0.2, open: 1.08, mouth: -0.45, gape: 0 },
  scared: { tilt: 1, lift: 0.7, open: 1.4, mouth: -0.3, gape: 0.8 },
  angry: { tilt: -1, lift: -0.4, open: 0.8, mouth: -0.7, gape: 0 },
  surprised: { tilt: 0.2, lift: 1, open: 1.45, mouth: 0, gape: 1 },
  tired: { tilt: 0.3, lift: -0.3, open: 0.5, mouth: -0.3, gape: 0 },
};
// The face a pose comes with, unless the scene says another.
export const POSE_MOOD = { arms_out: "scared", listen: "worried", look_down: "sad", knock: "worried" };
const AGE = { child: 0.62, teen: 0.85, adult: 1, old: 0.95 };
const BUILD = { slim: 0.86, average: 1, heavy: 1.25 };

export function ease(p) {
  p = Math.min(Math.max(p, 0), 1);
  return p * p * (3 - 2 * p);
}

export function heightOf(card, base) {
  return base * (AGE[card.age] ?? 1);
}

function go([x, y], angle, length) {
  const a = (angle * Math.PI) / 180;
  return [x + Math.sin(a) * length, y + Math.cos(a) * length];
}

// The joints for these angles. `facing` is 1 when the figure faces right; angles are given
// as if it did, and mirrored otherwise. With `hip` the figure is put there (sitting);
// otherwise the lower foot stands on `feet`.
export function bones(feet, angles, size, facing, hip = null) {
  const a = {};
  for (const [k, v] of Object.entries(angles)) a[k] = k === "nod" ? v : v * facing;
  const origin = [0, 0];
  const knee_f = go(origin, a.leg_f, THIGH * size);
  const knee_n = go(origin, a.leg_n, THIGH * size);
  const ankle_f = go(knee_f, a.leg_f + a.shin_f, SHIN * size);
  const ankle_n = go(knee_n, a.leg_n + a.shin_n, SHIN * size);
  const drop = Math.max(ankle_f[1], ankle_n[1]) + FOOT * 0.35 * size;
  const [ox, oy] = hip ? hip : [feet[0], feet[1] - drop];
  const put = ([x, y]) => [x + ox, y + oy];
  const hipP = [ox, oy];
  const lean = (a.lean * Math.PI) / 180;
  const neck = [hipP[0] + Math.sin(lean) * TORSO * size, hipP[1] - Math.cos(lean) * TORSO * size];
  const across = [Math.cos(lean) * SHOULDER * size, Math.sin(lean) * SHOULDER * size];
  // The body is turned a little the way it faces: the shoulder behind sits nearer the neck.
  const shoulder_f = [neck[0] - across[0] * facing * 0.78, neck[1] - across[1] * facing + 0.03 * size];
  const shoulder_n = [neck[0] + across[0] * facing * 0.92, neck[1] + across[1] * facing + 0.026 * size];
  const tilt = (a.head * Math.PI) / 180;
  const up = (NECK + HEAD) * size;
  const head = [
    neck[0] + Math.sin(tilt) * up * 0.4 + a.nod * HEAD * size * 0.3 * facing,
    neck[1] - up + a.nod * HEAD * size,
  ];
  const elbow_f = go(shoulder_f, a.arm_f, UPPER * size);
  const elbow_n = go(shoulder_n, a.arm_n, UPPER * size);
  const hand_f = go(elbow_f, a.arm_f + a.fore_f, FORE * size);
  const hand_n = go(elbow_n, a.arm_n + a.fore_n, FORE * size);
  return {
    hip: hipP, neck, head, shoulder_f, shoulder_n, elbow_f, elbow_n, hand_f, hand_n,
    knee_f: put(knee_f), knee_n: put(knee_n), ankle_f: put(ankle_f), ankle_n: put(ankle_n),
    size, facing,
  };
}

// Angles of an upper arm and forearm that put the hand on `target`, the elbow bending
// down; a target out of reach gets the arm stretched toward it. In the facing-right frame.
export function reach(shoulder, target, size, facing) {
  const a = UPPER * size, b = FORE * size;
  const dx = (target[0] - shoulder[0]) * facing, dy = target[1] - shoulder[1];
  const d = Math.min(Math.max(Math.hypot(dx, dy), Math.abs(a - b) + 1), a + b - 1);
  const toward = (Math.atan2(dx, dy) * 180) / Math.PI;
  const inner = (Math.acos((a * a + d * d - b * b) / (2 * a * d)) * 180) / Math.PI;
  const elbow = (Math.acos((a * a + b * b - d * d) / (2 * a * b)) * 180) / Math.PI;
  return [toward + inner, -(180 - elbow)];
}

// Breath, a little sway, and the swing of legs and arms when walking.
export function alive(angles, t, walking) {
  const out = { ...angles };
  const breath = Math.sin((2 * Math.PI * t) / 3.4);
  out.lean += 0.6 * breath;
  out.head += 1.2 * Math.sin((2 * Math.PI * t) / 4.3 + 0.7);
  out.arm_f -= 1.4 * breath;
  out.arm_n += 1.4 * breath;
  if (walking) {
    const phase = Math.sin((Math.PI * t) / WALK_STEP);
    out.leg_f += 20 * phase;
    out.leg_n -= 20 * phase;
    out.shin_f -= 18 * Math.max(0, -phase);
    out.shin_n -= 18 * Math.max(0, phase);
    out.arm_f -= 16 * phase;
    out.arm_n += 16 * phase;
    out.fore_f -= 10;
    out.fore_n += 10;
  }
  return out;
}

export function poseAngles(name) {
  return { ...STAND, ...(POSES[name] ?? {}) };
}

export function blend(from, to, p) {
  const out = {};
  for (const k of Object.keys(to)) out[k] = from[k] + (to[k] - from[k]) * p;
  return out;
}

function mix(colour, toward, k) {
  const a = shade(colour, 1).match(/[\d.]+/g).map(Number), b = shade(toward, 1).match(/[\d.]+/g).map(Number);
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * k)).join(",")})`;
}
const AIR = "#27344E";

function shade(colour, k) {
  let r, g, b;
  if (colour.startsWith("rgb")) [r, g, b] = colour.match(/[\d.]+/g).map(Number);
  else {
    const n = parseInt(colour.slice(1), 16);
    [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  if (k <= 1) [r, g, b] = [r * k, g * k, b * k];
  else [r, g, b] = [r + (255 - r) * (k - 1), g + (255 - g) * (k - 1), b + (255 - b) * (k - 1)];
  return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`;
}

function stroke(ctx, points, width, color) {
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (const p of points.slice(1)) ctx.lineTo(...p);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();
}

function disc(ctx, [x, y], r, color) {
  ctx.beginPath();
  ctx.arc(x, y, Math.max(r, 0.5), 0, 2 * Math.PI);
  ctx.fillStyle = color;
  ctx.fill();
}

// The box a figure takes up: [x, y, w, h].
export function box(b) {
  const pts = [b.head, b.hand_f, b.hand_n, b.ankle_f, b.ankle_n, b.knee_f, b.knee_n, b.hip, b.neck];
  const r = HEAD * b.size * 1.1;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs) - r * 0.6, x1 = Math.max(...xs) + r * 0.6;
  const y0 = Math.min(...ys) - r * 1.2, y1 = Math.max(...ys) + FOOT * b.size * 0.4;
  return [x0, y0, x1 - x0, y1 - y0];
}

// A tapered limb from a to b, round at both ends.
function capsule(ctx, a, b, wa, wb) {
  const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  ctx.beginPath();
  ctx.arc(a[0], a[1], wa / 2, ang + Math.PI / 2, ang + (3 * Math.PI) / 2);
  ctx.arc(b[0], b[1], wb / 2, ang - Math.PI / 2, ang + Math.PI / 2);
  ctx.closePath();
}

// A limb with a body to it: a contour, the colour, a shadow along the side turned from the
// light and a thin light along the other. `f` is the way the figure faces; the light comes
// from above and in front of it.
function limb(ctx, points, widths, colour, f) {
  const segs = points.slice(1).map((q, i) => [points[i], q, widths[i], widths[i + 1]]);
  for (const [a, b, wa, wb] of segs) {
    capsule(ctx, a, b, wa + 7, wb + 7);
    ctx.fillStyle = RIM;
    ctx.fill();
  }
  for (const [a, b, wa, wb] of segs) {
    capsule(ctx, a, b, wa + 2.6, wb + 2.6);
    ctx.fillStyle = OUT;
    ctx.fill();
  }
  for (const [a, b, wa, wb] of segs) {
    const w = (wa + wb) / 2;
    const d = [-f * 0.6 * w * 0.3, 0.8 * w * 0.3];
    ctx.save();
    capsule(ctx, a, b, wa, wb);
    ctx.fillStyle = colour;
    ctx.fill();
    ctx.clip();
    stroke(ctx, [[a[0] + d[0] * 1.15, a[1] + d[1] * 1.15], [b[0] + d[0] * 1.15, b[1] + d[1] * 1.15]], w * 0.5, shade(colour, 0.8));
    ctx.restore();
  }
}

function hand(ctx, elbow, wrist, s, skin, f) {
  const ang = Math.atan2(wrist[1] - elbow[1], wrist[0] - elbow[0]);
  const along = [Math.cos(ang), Math.sin(ang)], side = [-along[1] * f, along[0] * f];
  const palm = [wrist[0] + along[0] * 0.018 * s, wrist[1] + along[1] * 0.018 * s];
  const thumb = [palm[0] - side[0] * 0.024 * s + along[0] * 0.012 * s, palm[1] - side[1] * 0.024 * s + along[1] * 0.012 * s];
  capsule(ctx, palm, thumb, 0.018 * s + 3, 0.014 * s + 3);
  ctx.fillStyle = OUT;
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(palm[0], palm[1], 0.034 * s + 1.8, 0.026 * s + 1.8, ang, 0, 2 * Math.PI);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(palm[0], palm[1], 0.034 * s, 0.026 * s, ang, 0, 2 * Math.PI);
  ctx.fillStyle = skin;
  ctx.fill();
  capsule(ctx, palm, thumb, 0.018 * s, 0.014 * s);
  ctx.fill();
  for (const k of [-0.008, 0.006]) {
    const from = [palm[0] + along[0] * 0.012 * s + side[0] * k * s, palm[1] + along[1] * 0.012 * s + side[1] * k * s];
    stroke(ctx, [from, [from[0] + along[0] * 0.02 * s, from[1] + along[1] * 0.02 * s]], 0.004 * s, shade(skin, 0.72));
  }
}

function shoe(ctx, ankle, s, f, colour) {
  const [x, y] = ankle;
  const len = FOOT * s * 1.25, tall = 0.042 * s;
  const path = (grow) => {
    ctx.beginPath();
    ctx.moveTo(x - 0.03 * s * f - grow * f, y - tall * 0.5 - grow);
    ctx.lineTo(x + 0.02 * s * f, y - tall * 0.55 - grow);
    ctx.quadraticCurveTo(x + len * 0.7 * f, y - tall * 0.2 - grow, x + (len + grow) * f, y + tall * 0.55);
    ctx.lineTo(x + (len + grow) * f, y + tall + grow);
    ctx.lineTo(x - 0.03 * s * f - grow * f, y + tall + grow);
    ctx.closePath();
  };
  path(2);
  ctx.fillStyle = OUT;
  ctx.fill();
  path(0);
  ctx.fillStyle = colour;
  ctx.fill();
  ctx.fillStyle = shade(colour, 0.55);
  ctx.fillRect(Math.min(x - 0.03 * s * f, x + len * f), y + tall * 0.72, len + 0.03 * s, tall * 0.28);
  stroke(ctx, [[x + 0.015 * s * f, y - tall * 0.3], [x + len * 0.45 * f, y + tall * 0.05]], 0.005 * s, shade(colour, 1.25));
}

// The figure from the back limbs to the head. Every part has a contour, a lit side and a
// shadow side, and clothes carry what tells them apart: a collar, buttons, a belt, cuffs.
export function draw(ctx, b, card, alpha = 1) {
  const s = b.size;
  const f = b.facing;
  const w = BUILD[card.build] ?? 1;
  // Clothes and skin lean to the colour of the air: a red coat in a dark room is a dark red.
  const skin = mix(SKIN[card.skin] ?? SKIN.light, AIR, 0.16);
  const top = mix(card.top_colour, AIR, 0.3), legs = mix(card.bottom_colour, AIR, 0.34), shoes = mix(card.shoes_colour, AIR, 0.4);
  const long = card.bottom === "long_skirt" || card.top === "gown";
  const coat = card.top === "coat" || card.top === "raincoat";
  const bare = card.bottom === "shorts" || card.bottom === "skirt";
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineJoin = "round";

  const ground = Math.max(b.ankle_f[1], b.ankle_n[1]);
  ctx.save();
  ctx.filter = `blur(${0.022 * s}px)`;
  ctx.beginPath();
  ctx.ellipse(b.hip[0] - 0.03 * s * f, ground + 0.05 * s, 0.26 * s * w, 0.03 * s, 0, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fill();
  ctx.restore();

  const far = (colour) => shade(colour, 0.72);
  const leg = (side) => {
    const knee = b[`knee_${side}`], ankle = b[`ankle_${side}`];
    const hip = [b.hip[0] + (side === "n" ? 0.62 : -0.42) * HIP * s * f * w, b.hip[1]];
    const tone = (c) => (side === "n" ? c : far(c));
    if (!long) {
      const lw = LEG_W * s * w;
      limb(ctx, [hip, knee, ankle], [lw * 1.26, lw * 0.96, lw * 0.66], tone(bare ? skin : legs), f);
      if (card.bottom === "shorts") limb(ctx, [hip, [(hip[0] + knee[0]) / 2, (hip[1] + knee[1]) / 2]], [lw * 1.2, lw * 1.12], tone(legs), f);
      if (!bare) stroke(ctx, [[ankle[0] - lw * 0.36, ankle[1] - 0.012 * s], [ankle[0] + lw * 0.36, ankle[1] - 0.012 * s]], 0.012 * s, shade(tone(legs), 0.7));
    }
    shoe(ctx, ankle, s, f, tone(shoes));
  };
  const arm = (side) => {
    const shoulder = b[`shoulder_${side}`], elbow = b[`elbow_${side}`], wrist = b[`hand_${side}`];
    const tone = side === "n" ? top : far(top);
    const aw = ARM_W * s * w;
    hand(ctx, elbow, wrist, s, side === "n" ? skin : shade(skin, 0.82), f);
    limb(ctx, [shoulder, elbow, wrist], [aw * 1.28, aw * 0.98, aw * 0.7], tone, f);
    const back = [wrist[0] + (elbow[0] - wrist[0]) * 0.1, wrist[1] + (elbow[1] - wrist[1]) * 0.1];
    stroke(ctx, [back, wrist], aw * 0.74, shade(tone, card.top === "sweater" ? 0.8 : 0.66));
  };

  leg("f");
  arm("f");
  leg("n");

  // Below the waist: skirts, dresses and long coats are one shape from the hips down.
  const hipL = [b.hip[0] - HIP * s * 1.15 * w, b.hip[1] + 0.02 * s];
  const hipR = [b.hip[0] + HIP * s * 1.15 * w, b.hip[1] + 0.02 * s];
  const knees = (b.knee_f[1] + b.knee_n[1]) / 2;
  const lit = (colour, x0, x1) => {
    const g = ctx.createLinearGradient(f > 0 ? x0 : x1, 0, f > 0 ? x1 : x0, 0);
    g.addColorStop(0, shade(colour, 0.66));
    g.addColorStop(0.45, colour);
    g.addColorStop(1, shade(colour, 1.1));
    return g;
  };
  const hem = (depth, flare, colour) => {
    ctx.beginPath();
    ctx.moveTo(...hipL);
    ctx.lineTo(hipL[0] - flare, depth);
    ctx.quadraticCurveTo(b.hip[0], depth + 0.015 * s, hipR[0] + flare, depth);
    ctx.lineTo(...hipR);
    ctx.closePath();
    ctx.lineWidth = 4;
    ctx.strokeStyle = OUT;
    ctx.stroke();
    ctx.fillStyle = lit(colour, hipL[0] - flare, hipR[0] + flare);
    ctx.fill();
    for (const k of [0.3, 0.62]) {
      const x = hipL[0] + (hipR[0] - hipL[0]) * k;
      stroke(ctx, [[x, b.hip[1] + 0.05 * s], [x + (k - 0.5) * flare * 1.6, depth - 0.01 * s]], 0.005 * s, shade(colour, 0.7));
    }
  };
  if (card.top === "gown") hem(ground - 0.01 * s, 0.17 * s, top);
  else if (card.bottom === "long_skirt" || card.top === "dress") hem(card.bottom === "long_skirt" ? ground - 0.015 * s : knees + 0.05 * s, 0.08 * s, card.top === "dress" ? top : legs);
  else if (card.bottom === "skirt") hem(knees, 0.05 * s, legs);
  if (coat) hem(knees + 0.02 * s, 0.035 * s, shade(top, 0.92));
  if (card.top === "apron") hem(knees, 0.02 * s, "#E8E4DA");

  // The torso: shoulders, a waist, and the light across it from the front.
  const cloth = card.top === "apron" ? "#E8E4DA" : top;
  const waistL = [hipL[0] + 0.012 * s * w, (hipL[1] + b.shoulder_f[1]) / 2 + 0.03 * s];
  const waistR = [hipR[0] - 0.012 * s * w, waistL[1]];
  const shF = [b.shoulder_f[0] - 0.02 * s * f * w, b.shoulder_f[1] + 0.008 * s];
  const shN = [b.shoulder_n[0] + 0.02 * s * f * w, b.shoulder_n[1] + 0.008 * s];
  const [left, right] = f > 0 ? [shF, shN] : [shN, shF];
  ctx.beginPath();
  ctx.moveTo(...hipL);
  ctx.quadraticCurveTo(waistL[0], waistL[1], left[0], left[1] + 0.03 * s);
  ctx.quadraticCurveTo(left[0], left[1] - 0.012 * s, left[0] + 0.03 * s, left[1] - 0.018 * s);
  ctx.quadraticCurveTo(b.neck[0], b.neck[1] - 0.02 * s, right[0] - 0.03 * s, right[1] - 0.018 * s);
  ctx.quadraticCurveTo(right[0], right[1] - 0.012 * s, right[0], right[1] + 0.03 * s);
  ctx.quadraticCurveTo(waistR[0], waistR[1], ...hipR);
  ctx.closePath();
  ctx.lineWidth = 9;
  ctx.strokeStyle = RIM;
  ctx.stroke();
  ctx.lineWidth = 3;
  ctx.strokeStyle = OUT;
  ctx.stroke();
  ctx.fillStyle = lit(cloth, Math.min(left[0], hipL[0]), Math.max(right[0], hipR[0]));
  ctx.fill();

  // What the clothes are made of. The middle of the chest is turned a little the way the
  // figure faces.
  const mid = (k) => [b.neck[0] + (b.hip[0] - b.neck[0]) * k + 0.018 * s * f, b.neck[1] + (b.hip[1] - b.neck[1]) * k];
  const dark = shade(cloth, 0.58), light = shade(cloth, 1.22);
  const collar = (spread, drop, colour, width = 0.014 * s) =>
    stroke(ctx, [[b.neck[0] - spread * s, b.neck[1] + 0.004 * s], [mid(0)[0], b.neck[1] + drop * s], [b.neck[0] + spread * s, b.neck[1] + 0.004 * s]], width, colour);
  const buttons = (from, to, n, colour) => {
    for (let i = 0; i < n; i++) disc(ctx, mid(from + ((to - from) * i) / Math.max(n - 1, 1)), 0.007 * s, colour);
  };
  if (card.top === "shirt") {
    stroke(ctx, [mid(0.14), mid(0.97)], 0.005 * s, dark);
    buttons(0.24, 0.86, 4, light);
    collar(0.05, 0.06, light, 0.02 * s);
    ctx.strokeStyle = dark;
    ctx.lineWidth = 0.004 * s;
    ctx.strokeRect(mid(0.3)[0] + 0.03 * s * f - (f < 0 ? 0.04 * s : 0), mid(0.3)[1], 0.04 * s, 0.045 * s);
  } else if (card.top === "sweater") {
    collar(0.045, 0.03, dark, 0.022 * s);
    stroke(ctx, [[hipL[0] + 0.004 * s, b.hip[1] - 0.012 * s], [hipR[0] - 0.004 * s, b.hip[1] - 0.012 * s]], 0.026 * s, shade(cloth, 0.78));
    for (const k of [0.3, 0.5, 0.7]) stroke(ctx, [[waistL[0] + 0.02 * s, mid(k)[1]], [waistR[0] - 0.02 * s, mid(k)[1]]], 0.003 * s, shade(cloth, 0.86));
  } else if (card.top === "jacket") {
    ctx.beginPath();
    ctx.moveTo(mid(0)[0] - 0.02 * s, b.neck[1] + 0.004 * s);
    ctx.lineTo(mid(0)[0] + 0.02 * s, b.neck[1] + 0.004 * s);
    ctx.lineTo(mid(0.98)[0] + 0.012 * s, mid(0.98)[1]);
    ctx.lineTo(mid(0.98)[0] - 0.012 * s, mid(0.98)[1]);
    ctx.closePath();
    ctx.fillStyle = shade(cloth, 1.5);
    ctx.fill();
    for (const side of [-1, 1]) stroke(ctx, [[mid(0)[0] + side * 0.05 * s, b.neck[1]], [mid(0.3)[0] + side * 0.012 * s, mid(0.3)[1]], [mid(0.98)[0] + side * 0.013 * s, mid(0.98)[1]]], 0.012 * s, dark);
    for (const side of [-1, 1]) stroke(ctx, [[mid(0.66)[0] + side * 0.035 * s, mid(0.66)[1]], [mid(0.66)[0] + side * 0.075 * s, mid(0.66)[1]]], 0.006 * s, dark);
  } else if (coat) {
    for (const side of [-1, 1]) stroke(ctx, [[mid(0)[0] + side * 0.055 * s, b.neck[1]], [mid(0.34)[0], mid(0.34)[1]]], 0.02 * s, shade(cloth, 0.8));
    stroke(ctx, [mid(0.34), mid(1)], 0.005 * s, dark);
    buttons(0.44, 0.9, 3, dark);
    stroke(ctx, [[hipL[0] + 0.006 * s, mid(0.8)[1]], [hipR[0] - 0.006 * s, mid(0.8)[1]]], 0.02 * s, shade(cloth, 0.62));
    if (card.top === "raincoat") {
      ctx.beginPath();
      ctx.ellipse(b.neck[0] - 0.03 * s * f, b.neck[1] + 0.006 * s, 0.075 * s, 0.03 * s, 0, 0, 2 * Math.PI);
      ctx.fillStyle = shade(cloth, 0.8);
      ctx.fill();
    }
  } else if (card.top === "uniform") {
    stroke(ctx, [mid(0.1), mid(0.97)], 0.005 * s, dark);
    buttons(0.2, 0.86, 4, "#D9B44A");
    collar(0.045, 0.045, dark, 0.02 * s);
    for (const sh of [b.shoulder_f, b.shoulder_n]) stroke(ctx, [[sh[0] - 0.028 * s, sh[1] - 0.006 * s], [sh[0] + 0.028 * s, sh[1] - 0.006 * s]], 0.016 * s, "#D9B44A");
    ctx.fillStyle = "#E8E4DA";
    ctx.fillRect(mid(0.3)[0] + (f > 0 ? 0.025 : -0.07) * s, mid(0.3)[1], 0.045 * s, 0.022 * s);
  } else {
    collar(0.045, 0.05, dark);
    stroke(ctx, [mid(0.2), mid(0.6)], 0.004 * s, dark);
  }
  if (!long && card.top !== "dress" && !coat) {
    stroke(ctx, [[hipL[0] + 0.006 * s, b.hip[1] - 0.004 * s], [hipR[0] - 0.006 * s, b.hip[1] - 0.004 * s]], 0.026 * s, shade(legs, 0.55));
    ctx.fillStyle = "#B9A25E";
    ctx.fillRect(mid(1)[0] - 0.014 * s, b.hip[1] - 0.016 * s, 0.028 * s, 0.024 * s);
  }

  const extras = card.extras ?? [];
  if (extras.includes("scarf")) {
    stroke(ctx, [[b.neck[0] - 0.05 * s, b.neck[1] + 0.012 * s], [b.neck[0] + 0.05 * s, b.neck[1] + 0.012 * s]], 0.034 * s, "#B8443A");
    stroke(ctx, [[b.neck[0] + 0.02 * s * f, b.neck[1] + 0.02 * s], [b.neck[0] + 0.035 * s * f, b.neck[1] + 0.13 * s]], 0.028 * s, "#B8443A");
    stroke(ctx, [[b.neck[0] + 0.026 * s * f, b.neck[1] + 0.06 * s], [b.neck[0] + 0.035 * s * f, b.neck[1] + 0.13 * s]], 0.006 * s, "#8A2E28");
  }
  if (extras.includes("necklace")) {
    for (let i = 0; i <= 8; i++) {
      const a = Math.PI * (0.15 + (0.7 * i) / 8);
      disc(ctx, [b.neck[0] + Math.cos(a) * 0.05 * s, b.neck[1] + 0.012 * s + Math.sin(a) * 0.045 * s], 0.008 * s, i === 4 ? "#F4F0FF" : "#E6DCC0");
    }
  }
  if (extras.includes("bag")) {
    stroke(ctx, [b.shoulder_f, [b.hip[0] + 0.07 * s * f, b.hip[1] - 0.02 * s]], 0.01 * s, "#3A2A20");
    ctx.fillStyle = OUT;
    ctx.fillRect(b.hip[0] + 0.03 * s * f - 0.045 * s, b.hip[1] - 0.045 * s, 0.09 * s, 0.08 * s);
    ctx.fillStyle = "#6A4A34";
    ctx.fillRect(b.hip[0] + 0.03 * s * f - 0.04 * s, b.hip[1] - 0.04 * s, 0.08 * s, 0.07 * s);
    ctx.fillStyle = "#4A3224";
    ctx.fillRect(b.hip[0] + 0.03 * s * f - 0.04 * s, b.hip[1] - 0.04 * s, 0.08 * s, 0.025 * s);
  }
  if (extras.includes("torch")) {
    const tx = b.neck[0] + 0.03 * s * f, ty = b.neck[1] + 0.11 * s;
    stroke(ctx, [[b.neck[0] - 0.02 * s, b.neck[1] + 0.01 * s], [tx, ty]], 2.5, "#141418");
    ctx.fillStyle = "#3C3E46";
    ctx.fillRect(tx - 0.012 * s, ty, 0.024 * s, 0.05 * s);
    ctx.fillStyle = "#FFE9A8";
    ctx.fillRect(tx - 0.012 * s, ty + 0.042 * s, 0.024 * s, 0.01 * s);
  }
  arm("n");
  head(ctx, b, card, skin);
  ctx.restore();
}

// Neck and head, turned three quarters the way the figure faces: both eyes show, the nose
// sits between them, and the brows and the mouth carry the mood.
function head(ctx, b, card, skin) {
  const s = b.size, f = b.facing;
  card = { ...card, hair_colour: mix(card.hair_colour?.startsWith("#") ? card.hair_colour : "#2A2022", AIR, 0.22) };
  const [hx, hy] = b.head;
  const r = HEAD * s * (card.age === "child" ? 1.12 : 1);
  const hair = card.hair_colour;
  const mood = MOODS[b.mood] ?? MOODS.neutral;
  const blink = b.blink ?? 1;

  const base = [b.neck[0], b.neck[1] + 0.012 * s];
  capsule(ctx, base, [hx, hy + r * 0.4], 0.05 * s + 3.5, 0.046 * s + 3.5);
  ctx.fillStyle = OUT;
  ctx.fill();
  capsule(ctx, base, [hx, hy + r * 0.4], 0.05 * s, 0.046 * s);
  ctx.fillStyle = shade(skin, 0.74);
  ctx.fill();

  const back = hx - r * f;
  if (card.hair === "long") {
    ctx.beginPath();
    ctx.ellipse(hx - r * 0.35 * f, hy + r * 0.7, r * 0.78, r * 1.4, 0, 0, 2 * Math.PI);
    ctx.fillStyle = OUT;
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(hx - r * 0.35 * f, hy + r * 0.7, r * 0.74, r * 1.36, 0, 0, 2 * Math.PI);
    ctx.fillStyle = hair;
    ctx.fill();
  }
  if (card.hair === "ponytail") stroke(ctx, [[back, hy - r * 0.1], [back - r * 0.45 * f, hy + r * 0.9]], r * 0.36, hair);

  // The skull and the jaw as one shape: rounder behind, a chin in front.
  const skull = (grow) => {
    ctx.beginPath();
    if (f > 0) ctx.ellipse(hx, hy - r * 0.04, r + grow, r * 1.04 + grow, 0, Math.PI, 2 * Math.PI);
    else ctx.ellipse(hx, hy - r * 0.04, r + grow, r * 1.04 + grow, 0, 0, Math.PI, true);
    ctx.bezierCurveTo(hx + (r + grow) * f, hy + r * 0.7, hx + r * 0.75 * f, hy + r * 1.12 + grow, hx + r * 0.3 * f, hy + r * 1.1 + grow);
    ctx.bezierCurveTo(hx - r * 0.3 * f, hy + r * 1.08 + grow, hx - (r + grow) * f, hy + r * 0.75, hx - (r + grow) * f, hy - r * 0.04);
    ctx.closePath();
  };
  skull(5.5);
  ctx.fillStyle = RIM;
  ctx.fill();
  skull(2.5);
  ctx.fillStyle = OUT;
  ctx.fill();
  const ear = [hx - r * 0.72 * f, hy + r * 0.16];
  ctx.save();
  skull(0);
  ctx.fillStyle = skin;
  ctx.fill();
  ctx.clip();
  ctx.beginPath();
  ctx.ellipse(hx - r * 1.05 * f, hy + r * 0.25, r * 0.62, r * 1.3, 0, 0, 2 * Math.PI);
  ctx.fillStyle = shade(skin, 0.8);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(hx + r * 0.2 * f, hy + r * 1.25, r * 0.9, r * 0.32, 0, 0, 2 * Math.PI);
  ctx.fillStyle = shade(skin, 0.84);
  ctx.fill();
  disc(ctx, [hx + r * 0.42 * f, hy + r * 0.42], r * 0.2, "rgba(214,110,96,0.16)");
  ctx.restore();
  ctx.beginPath();
  ctx.ellipse(ear[0], ear[1], r * 0.17, r * 0.25, 0, 0, 2 * Math.PI);
  ctx.fillStyle = shade(skin, 0.9);
  ctx.fill();
  ctx.lineWidth = r * 0.05;
  ctx.strokeStyle = shade(skin, 0.6);
  ctx.stroke();

  const face = card.face ?? [];
  if (card.age === "old") {
    for (const k of [0.55, 0.68]) stroke(ctx, [[hx + r * 0.08 * f, hy - r * k], [hx + r * 0.62 * f, hy - r * (k + 0.02)]], r * 0.03, shade(skin, 0.74));
  }
  if (face.includes("freckles")) for (const d of [-0.12, 0.08, 0.26]) disc(ctx, [hx + r * (0.36 + d) * f, hy + r * 0.36], r * 0.045, shade(skin, 0.7));

  // Eyes: the near one wider, the far one by the edge of the face.
  const eyes = [[hx + r * 0.26 * f, hy - r * 0.02, r * 0.17], [hx + r * 0.72 * f, hy - r * 0.02, r * 0.12]];
  const open = Math.min(mood.open, 1.5) * blink;
  for (const [ex, ey, rx] of eyes) {
    const ry = Math.max(rx * 0.86 * open, rx * 0.08);
    ctx.beginPath();
    ctx.ellipse(ex, ey, rx, ry, 0, 0, 2 * Math.PI);
    ctx.fillStyle = "#D9D5CC";
    ctx.fill();
    ctx.save();
    ctx.clip();
    disc(ctx, [ex + rx * 0.22 * f, ey + (b.gaze ?? 0) * rx * 0.4], rx * 0.56, "#2B2320");
    disc(ctx, [ex + rx * 0.22 * f, ey + (b.gaze ?? 0) * rx * 0.4], rx * 0.26, "#0C0B0D");
    disc(ctx, [ex + rx * 0.02 * f, ey - rx * 0.28], rx * 0.14, "rgba(255,255,255,0.85)");
    ctx.restore();
    ctx.beginPath();
    ctx.ellipse(ex, ey, rx, ry, 0, Math.PI, 2 * Math.PI);
    ctx.lineWidth = r * 0.07;
    ctx.strokeStyle = "#1A1416";
    ctx.stroke();
  }
  // Brows: `inner` is the end by the nose, between the eyes and nearer the far one.
  const browY = hy - r * 0.36 - mood.lift * r * 0.12;
  const brow = card.hair === "bald" || card.age === "old" ? shade(skin, 0.45) : shade(hair.startsWith("#") ? hair : "#2A2022", 0.8);
  const browAt = ([ex, , rx], inward) => {
    const inner = [ex + inward * rx * 1.05, browY - mood.tilt * r * 0.13];
    const outer = [ex - inward * rx * 1.15, browY + mood.tilt * r * 0.05];
    stroke(ctx, [outer, [(inner[0] + outer[0]) / 2, Math.min(inner[1], outer[1]) - r * 0.03], inner], r * 0.085, brow);
  };
  browAt(eyes[0], f);
  browAt(eyes[1], -f);
  stroke(ctx, [[hx + r * 0.52 * f, hy + r * 0.02], [hx + r * 0.6 * f, hy + r * 0.32], [hx + r * 0.46 * f, hy + r * 0.36]], r * 0.055, shade(skin, 0.6));
  if (face.includes("glasses")) {
    ctx.lineWidth = r * 0.07;
    ctx.strokeStyle = "#101014";
    for (const [ex, ey, rx] of eyes) {
      ctx.beginPath();
      ctx.ellipse(ex, ey, rx * 1.45, rx * 1.35, 0, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(190,210,235,0.14)";
      ctx.fill();
      ctx.stroke();
    }
    stroke(ctx, [[eyes[0][0] - eyes[0][2] * 1.45 * f, eyes[0][1]], [ear[0], ear[1] - r * 0.12]], r * 0.06, "#101014");
  }
  // The mouth: a line that curves with the mood, open when the mood gapes.
  const mx = hx + r * 0.46 * f, my = hy + r * 0.66, mw = r * 0.2;
  if (mood.gape > 0.3) {
    ctx.beginPath();
    ctx.ellipse(mx, my + r * 0.02, mw * 0.8, mood.gape * r * 0.17, 0, 0, 2 * Math.PI);
    ctx.fillStyle = "#3A1616";
    ctx.fill();
    if (mood.mouth > 0.5) {
      ctx.fillStyle = "#F4F0E8";
      ctx.fillRect(mx - mw * 0.6, my - mood.gape * r * 0.1, mw * 1.2, r * 0.05);
    }
  } else {
    ctx.beginPath();
    ctx.moveTo(mx - mw, my - mood.mouth * r * 0.05);
    ctx.quadraticCurveTo(mx, my + mood.mouth * r * 0.16, mx + mw, my - mood.mouth * r * 0.05);
    ctx.lineWidth = r * 0.07;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#5A2A26";
    ctx.stroke();
  }
  if (face.includes("beard")) {
    ctx.save();
    skull(0);
    ctx.clip();
    ctx.beginPath();
    ctx.moveTo(hx - r * 0.75 * f, hy + r * 0.3);
    ctx.quadraticCurveTo(hx + r * 0.2 * f, hy + r * 0.62, hx + r * 0.95 * f, hy + r * 0.5);
    ctx.lineTo(hx + r * f, hy + r * 1.3);
    ctx.lineTo(hx - r * f, hy + r * 1.3);
    ctx.closePath();
    ctx.fillStyle = shade(hair.startsWith("#") ? hair : "#2A2022", 0.95);
    ctx.fill();
    ctx.restore();
    stroke(ctx, [[mx - mw, my], [mx + mw, my]], r * 0.06, "#5A2A26");
  }
  if (face.includes("mustache")) stroke(ctx, [[mx - mw * 1.2, my - r * 0.14], [mx, my - r * 0.2], [mx + mw * 1.2, my - r * 0.14]], r * 0.13, hair);

  if (card.hair !== "bald" && card.hat !== "kerchief") {
    // A cap of hair over the top and the back of the head, a fringe over the brow and a
    // lighter lock on top.
    const R = r * 1.1, cx = hx - r * 0.05 * f, cy = hy - r * 0.08;
    const at = (deg, k = 1) => {
      const a = (deg * Math.PI) / 180;
      return [cx + Math.cos(a) * R * k * f, cy + Math.sin(a) * R * k];
    };
    if (card.hair === "curly") for (let i = 0; i <= 7; i++) disc(ctx, at(160 + i * 27), r * 0.3, hair);
    ctx.beginPath();
    ctx.moveTo(...at(140));
    for (let deg = 140; deg <= 338; deg += 4) ctx.lineTo(...at(deg));
    ctx.quadraticCurveTo(hx + r * 0.5 * f, hy - r * 0.62, hx + r * 0.05 * f, hy - r * 0.5);
    ctx.quadraticCurveTo(hx - r * 0.45 * f, hy - r * 0.35, hx - r * 0.5 * f, hy + r * 0.05);
    ctx.quadraticCurveTo(hx - r * 0.75 * f, hy + r * 0.2, ...at(140));
    ctx.closePath();
    ctx.lineWidth = 3;
    ctx.strokeStyle = OUT;
    ctx.stroke();
    ctx.fillStyle = hair;
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(...at(205, 0.86));
    for (let deg = 205; deg <= 290; deg += 5) ctx.lineTo(...at(deg, 0.86));
    ctx.lineWidth = r * 0.09;
    ctx.lineCap = "round";
    ctx.strokeStyle = shade(hair.startsWith("#") ? hair : "#2A2022", 1.28);
    ctx.stroke();
  }
  if (card.hair === "bun") {
    disc(ctx, [hx - r * 0.55 * f, hy - r * 1.0], r * 0.4 + 2, OUT);
    disc(ctx, [hx - r * 0.55 * f, hy - r * 1.0], r * 0.4, hair);
  }
  if (card.hair === "braids") {
    for (const side of [-1, 1]) {
      const from = [hx + side * r * 0.85, hy + r * 0.3];
      stroke(ctx, [from, [from[0] + side * r * 0.15, from[1] + r * 1.5]], r * 0.34, hair);
      for (const k of [0.4, 0.8, 1.2]) stroke(ctx, [[from[0] + side * r * 0.04 * k - r * 0.12, from[1] + r * k], [from[0] + side * r * 0.04 * k + r * 0.12, from[1] + r * k + r * 0.08]], r * 0.04, shade(hair.startsWith("#") ? hair : "#2A2022", 0.6));
      disc(ctx, [from[0] + side * r * 0.15, from[1] + r * 1.55], r * 0.15, "#C83C32");
    }
  }
  const hat = card.hair === "cap" && card.hat === "none" ? "cap" : card.hat;
  if (hat === "cap") {
    ctx.beginPath();
    ctx.arc(hx, hy - r * 0.2, r * 1.08, Math.PI, 2 * Math.PI);
    ctx.fillStyle = "#2A2E38";
    ctx.fill();
    stroke(ctx, [[hx, hy - r * 0.22], [hx + r * 1.5 * f, hy - r * 0.14]], r * 0.17, "#20232B");
    stroke(ctx, [[hx - r * 0.9, hy - r * 0.26], [hx + r * 0.9, hy - r * 0.26]], r * 0.07, "#3A4050");
  } else if (hat === "top_hat") {
    ctx.fillStyle = "#16161A";
    ctx.fillRect(hx - r * 0.7, hy - r * 2.3, r * 1.4, r * 1.4);
    ctx.fillStyle = "#6A2A2A";
    ctx.fillRect(hx - r * 0.7, hy - r * 1.15, r * 1.4, r * 0.2);
    stroke(ctx, [[hx - r * 1.15, hy - r * 0.9], [hx + r * 1.15, hy - r * 0.9]], r * 0.18, "#16161A");
  } else if (hat === "bonnet") {
    ctx.beginPath();
    ctx.arc(hx - r * 0.1 * f, hy - r * 0.1, r * 1.22, Math.PI * 0.85, Math.PI * 2.15);
    ctx.lineWidth = r * 0.42;
    ctx.strokeStyle = "#E4DCC8";
    ctx.stroke();
  } else if (hat === "kerchief") {
    ctx.beginPath();
    ctx.arc(hx, hy - r * 0.08, r * 1.1, Math.PI * 0.9, Math.PI * 2.1);
    ctx.lineTo(hx - r * 1.15 * f, hy + r * 0.95);
    ctx.closePath();
    ctx.fillStyle = "#9C3A34";
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = OUT;
    ctx.stroke();
  }
}
