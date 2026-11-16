// The puppet every person is drawn with. A card says how a person looks; a pose is a set of
// joint angles; between poses the angles ease, and on top of any pose the figure breathes
// and sways a little, so nobody ever stands frozen. People are never drawn any other way.

export const EASE = 0.45; // seconds a change of pose takes
export const WALK_STEP = 0.55; // seconds a step takes

// Lengths in units of the figure's height.
const HEAD = 0.07, NECK = 0.035, TORSO = 0.3;
const SHOULDER = 0.105, HIP = 0.065;
const UPPER = 0.165, FORE = 0.15, HAND = 0.03;
const THIGH = 0.235, SHIN = 0.225, FOOT = 0.065;
const ARM_W = 0.058, LEG_W = 0.074;

// Angles in degrees: 0 points straight down, 90 to the front. The lower bone of a limb is
// given relative to the upper one. "_n" is the near limb, "_f" the far one.
const STAND = {
  lean: 0, head: 0, nod: 0,
  arm_f: -9, fore_f: -5, arm_n: 9, fore_n: 5,
  leg_f: -4, shin_f: 0, leg_n: 4, shin_n: 0,
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
const RIM = "rgba(150,168,200,0.55)";
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
  const shoulder_f = [neck[0] - across[0] * facing, neck[1] - across[1] * facing + 0.025 * size];
  const shoulder_n = [neck[0] + across[0] * facing, neck[1] + across[1] * facing + 0.025 * size];
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

function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
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

// The figure from the back limbs to the head, each part with a light rim, like a cut-out lit
// from behind.
export function draw(ctx, b, card, alpha = 1) {
  const s = b.size;
  const f = b.facing;
  const w = BUILD[card.build] ?? 1;
  const skin = SKIN[card.skin] ?? SKIN.light;
  const top = card.top_colour, legs = card.bottom_colour, shoes = card.shoes_colour;
  const long = card.bottom === "long_skirt" || card.top === "gown";
  const coat = card.top === "coat" || card.top === "raincoat";
  ctx.save();
  ctx.globalAlpha = alpha;

  const ground = Math.max(b.ankle_f[1], b.ankle_n[1]);
  ctx.save();
  ctx.filter = `blur(${0.02 * s}px)`;
  ctx.beginPath();
  ctx.ellipse(b.hip[0], ground + 0.03 * s, 0.2 * s * w, 0.02 * s, 0, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(0,0,0,0.45)";
  ctx.fill();
  ctx.restore();

  const limb = (pts, width, color) => {
    stroke(ctx, pts, width + 5, RIM);
    stroke(ctx, pts, width, color);
  };
  const legColour = (side) => {
    if (card.bottom === "shorts" || card.bottom === "skirt") return side === "n" ? skin : shade(skin.startsWith("#") ? skin : "#C69670", 0.85);
    return side === "n" ? legs : shade(legs, 0.8);
  };
  const leg = (side) => {
    const knee = b[`knee_${side}`], ankle = b[`ankle_${side}`];
    const hip = [b.hip[0] + (side === "n" ? 1 : -1) * HIP * s * 0.6 * f * w, b.hip[1]];
    if (!long) limb([hip, knee, ankle], LEG_W * s * w, legColour(side));
    if (card.bottom === "shorts") limb([hip, [(hip[0] + knee[0]) / 2, (hip[1] + knee[1]) / 2]], LEG_W * s * w * 1.1, side === "n" ? legs : shade(legs, 0.8));
    const toe = [ankle[0] + FOOT * s * f * 0.8, ankle[1] + FOOT * s * 0.25];
    stroke(ctx, [[ankle[0], ankle[1] + LEG_W * s * 0.1], toe], LEG_W * s * 0.72, side === "n" ? shoes : shade(shoes, 0.8));
  };
  const arm = (side) => {
    const shoulder = b[`shoulder_${side}`], elbow = b[`elbow_${side}`], hand = b[`hand_${side}`];
    limb([shoulder, elbow, hand], ARM_W * s * w, side === "n" ? top : shade(top, 0.78));
    disc(ctx, hand, HAND * s, skin);
  };

  leg("f");
  arm("f");
  leg("n");

  // Below the waist: skirts, dresses and long coats are one shape from the hips down.
  const hipL = [b.hip[0] - HIP * s * 1.15 * w, b.hip[1] + 0.02 * s];
  const hipR = [b.hip[0] + HIP * s * 1.15 * w, b.hip[1] + 0.02 * s];
  const knees = (b.knee_f[1] + b.knee_n[1]) / 2;
  const hem = (depth, flare) => {
    ctx.beginPath();
    ctx.moveTo(...hipL);
    ctx.lineTo(hipL[0] - flare, depth);
    ctx.lineTo(hipR[0] + flare, depth);
    ctx.lineTo(...hipR);
    ctx.closePath();
    ctx.lineWidth = 5;
    ctx.strokeStyle = RIM;
    ctx.stroke();
  };
  if (card.top === "gown") {
    hem(ground - 0.01 * s, 0.17 * s);
    ctx.fillStyle = top;
    ctx.fill();
  } else if (card.bottom === "long_skirt" || card.top === "dress") {
    const depth = card.bottom === "long_skirt" ? ground - 0.015 * s : knees + 0.05 * s;
    hem(depth, 0.08 * s);
    ctx.fillStyle = card.top === "dress" ? top : legs;
    ctx.fill();
  } else if (card.bottom === "skirt") {
    hem(knees, 0.05 * s);
    ctx.fillStyle = legs;
    ctx.fill();
  }
  if (coat) {
    hem(knees + 0.02 * s, 0.035 * s);
    ctx.fillStyle = shade(top, 0.92);
    ctx.fill();
  }
  if (card.top === "apron") {
    hem(knees, 0.02 * s);
    ctx.fillStyle = "#E8E4DA";
    ctx.fill();
  }

  // The torso: wider at the shoulders, a collar and a seam down the middle.
  ctx.beginPath();
  ctx.moveTo(...hipL);
  ctx.lineTo(b.shoulder_f[0] - 0.012 * s * f, b.shoulder_f[1] + 0.01 * s);
  ctx.quadraticCurveTo(b.neck[0], b.neck[1] - 0.012 * s, b.shoulder_n[0] + 0.012 * s * f, b.shoulder_n[1] + 0.01 * s);
  ctx.lineTo(...hipR);
  ctx.closePath();
  ctx.lineWidth = 5;
  ctx.strokeStyle = RIM;
  ctx.stroke();
  ctx.fillStyle = card.top === "apron" ? "#E8E4DA" : top;
  ctx.fill();
  stroke(ctx, [[b.neck[0], b.neck[1] + 0.03 * s], b.hip], 0.006 * s, shade(top, 0.7));
  stroke(ctx, [[b.neck[0] - 0.045 * s, b.neck[1] + 0.005 * s], [b.neck[0], b.neck[1] + 0.055 * s], [b.neck[0] + 0.045 * s, b.neck[1] + 0.005 * s]], 0.012 * s, shade(top, 0.62));
  if (!long && card.top !== "dress") stroke(ctx, [[hipL[0] + 0.005 * s, b.hip[1] - 0.005 * s], [hipR[0] - 0.005 * s, b.hip[1] - 0.005 * s]], 0.028 * s, shade(legs, 0.7));
  if (card.top === "uniform") {
    for (let i = 1; i <= 4; i++) disc(ctx, [b.neck[0] + 0.012 * s * f, b.neck[1] + i * 0.06 * s], 0.008 * s, "#D9B44A");
    for (const sh of [b.shoulder_f, b.shoulder_n]) stroke(ctx, [[sh[0] - 0.025 * s, sh[1] - 0.005 * s], [sh[0] + 0.025 * s, sh[1] - 0.005 * s]], 0.014 * s, "#D9B44A");
  }
  if (card.top === "sweater") stroke(ctx, [[hipL[0], b.hip[1] - 0.01 * s], [hipR[0], b.hip[1] - 0.01 * s]], 0.02 * s, shade(top, 0.8));

  const extras = card.extras ?? [];
  if (extras.includes("scarf")) {
    stroke(ctx, [[b.neck[0] - 0.05 * s, b.neck[1] + 0.012 * s], [b.neck[0] + 0.05 * s, b.neck[1] + 0.012 * s]], 0.03 * s, "#B8443A");
    stroke(ctx, [[b.neck[0] + 0.02 * s * f, b.neck[1] + 0.02 * s], [b.neck[0] + 0.035 * s * f, b.neck[1] + 0.13 * s]], 0.025 * s, "#B8443A");
  }
  if (extras.includes("necklace")) {
    for (let i = 0; i <= 8; i++) {
      const a = Math.PI * (0.15 + (0.7 * i) / 8);
      disc(ctx, [b.neck[0] + Math.cos(a) * 0.05 * s, b.neck[1] + 0.012 * s + Math.sin(a) * 0.045 * s], 0.008 * s, i === 4 ? "#F4F0FF" : "#E6DCC0");
    }
  }
  if (extras.includes("bag")) {
    stroke(ctx, [b.shoulder_f, [b.hip[0] + 0.07 * s * f, b.hip[1] - 0.02 * s]], 0.008 * s, "#3A2A20");
    ctx.fillStyle = "#5A4030";
    ctx.fillRect(b.hip[0] + 0.03 * s * f - 0.04 * s, b.hip[1] - 0.04 * s, 0.08 * s, 0.07 * s);
  }
  if (extras.includes("torch")) {
    const tx = b.neck[0] + 0.03 * s * f, ty = b.neck[1] + 0.11 * s;
    stroke(ctx, [[b.neck[0] - 0.02 * s, b.neck[1] + 0.01 * s], [tx, ty]], 2.5, "#141418");
    ctx.fillStyle = "#3C3E46";
    ctx.fillRect(tx - 0.012 * s, ty, 0.024 * s, 0.05 * s);
  }
  arm("n");
  head(ctx, b, card, skin);
  ctx.restore();
}

// Neck and head: skin, hair on the top and the back of the head only, an ear on the far
// side, and whatever the card puts on the face or on top.
function head(ctx, b, card, skin) {
  const s = b.size, f = b.facing;
  stroke(ctx, [[b.neck[0], b.neck[1] + 0.01 * s], b.head], 0.04 * s, shade(skin, 0.85));
  const [hx, hy] = b.head;
  const r = HEAD * s;
  const hair = card.hair_colour;
  const back = hx - r * f;
  if (card.hair === "long") {
    ctx.beginPath();
    ctx.ellipse(hx - r * 0.35 * f, hy + r * 0.7, r * 0.75, r * 1.35, 0, 0, 2 * Math.PI);
    ctx.fillStyle = hair;
    ctx.fill();
  }
  if (card.hair === "ponytail") stroke(ctx, [[back, hy - r * 0.1], [back - r * 0.45 * f, hy + r * 0.9]], r * 0.36, hair);
  disc(ctx, [hx, hy], r + 2.5, RIM);
  const ear = [hx - r * 0.92 * f, hy + r * 0.12];
  ctx.beginPath();
  ctx.ellipse(ear[0], ear[1], r * 0.2, r * 0.26, 0, 0, 2 * Math.PI);
  ctx.fillStyle = shade(skin, 0.9);
  ctx.fill();
  disc(ctx, [hx, hy], r, skin);
  disc(ctx, [hx + r * 0.25 * f, hy + r * 0.05], r * 0.72, `rgba(255,255,255,0.05)`);
  const face = card.face ?? [];
  if (face.includes("freckles")) for (const d of [-0.1, 0.12, 0.3]) disc(ctx, [hx + r * (0.3 + d) * f, hy + r * 0.2], r * 0.05, shade(skin, 0.75));
  if (face.includes("beard")) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(hx, hy, r, 0, 2 * Math.PI);
    ctx.clip();
    ctx.fillStyle = shade(hair, 1.05);
    ctx.beginPath();
    ctx.ellipse(hx + r * 0.1 * f, hy + r * 0.95, r * 0.75, r * 0.5, 0, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
  }
  if (face.includes("mustache")) stroke(ctx, [[hx + r * 0.25 * f, hy + r * 0.32], [hx + r * 0.8 * f, hy + r * 0.32]], r * 0.14, hair);
  if (face.includes("glasses")) {
    ctx.beginPath();
    ctx.arc(hx + r * 0.55 * f, hy - r * 0.02, r * 0.2, 0, 2 * Math.PI);
    ctx.lineWidth = r * 0.07;
    ctx.strokeStyle = "#101014";
    ctx.stroke();
    stroke(ctx, [[hx + r * 0.35 * f, hy - r * 0.05], [hx - r * 0.6 * f, hy - r * 0.08]], r * 0.06, "#101014");
  }
  if (card.hair !== "bald" && card.hat !== "kerchief") {
    // A cap of hair: an arc over the top of the head from the forehead to behind the ear,
    // closed by a line across the head, so the face in front stays clear.
    const R = r * 1.07, cx = hx - r * 0.04 * f, cy = hy - r * 0.05;
    const at = (deg) => {
      const a = (deg * Math.PI) / 180;
      return [cx + Math.cos(a) * R * f, cy + Math.sin(a) * R];
    };
    if (card.hair === "curly") for (let i = 0; i <= 6; i++) disc(ctx, at(165 + i * 30), r * 0.3, hair);
    ctx.beginPath();
    ctx.moveTo(...at(150));
    for (let deg = 150; deg <= 345; deg += 5) ctx.lineTo(...at(deg));
    ctx.quadraticCurveTo(hx + r * 0.1 * f, hy - r * 0.3, ...at(150));
    ctx.closePath();
    ctx.fillStyle = hair;
    ctx.fill();
  }
  if (card.hair === "bun") disc(ctx, [hx - r * 0.5 * f, hy - r * 0.95], r * 0.38, hair);
  if (card.hair === "braids") {
    for (const side of [-1, 1]) {
      const at = [hx + side * r * 0.85, hy + r * 0.2];
      stroke(ctx, [at, [at[0] + side * r * 0.15, at[1] + r * 1.5]], r * 0.32, hair);
      disc(ctx, [at[0] + side * r * 0.15, at[1] + r * 1.55], r * 0.14, "#C83C32");
    }
  }
  const hat = card.hair === "cap" && card.hat === "none" ? "cap" : card.hat;
  if (hat === "cap") {
    ctx.beginPath();
    ctx.arc(hx, hy - r * 0.15, r * 1.05, Math.PI, 2 * Math.PI);
    ctx.fillStyle = "#2A2E38";
    ctx.fill();
    stroke(ctx, [[hx, hy - r * 0.18], [hx + r * 1.45 * f, hy - r * 0.1]], r * 0.16, "#2A2E38");
  } else if (hat === "top_hat") {
    ctx.fillStyle = "#16161A";
    ctx.fillRect(hx - r * 0.7, hy - r * 2.2, r * 1.4, r * 1.35);
    stroke(ctx, [[hx - r * 1.15, hy - r * 0.85], [hx + r * 1.15, hy - r * 0.85]], r * 0.18, "#16161A");
  } else if (hat === "bonnet") {
    ctx.beginPath();
    ctx.arc(hx - r * 0.1 * f, hy - r * 0.1, r * 1.22, Math.PI * 0.85, Math.PI * 2.15);
    ctx.lineWidth = r * 0.42;
    ctx.strokeStyle = "#E4DCC8";
    ctx.stroke();
  } else if (hat === "kerchief") {
    ctx.beginPath();
    ctx.arc(hx, hy - r * 0.05, r * 1.08, Math.PI * 0.9, Math.PI * 2.1);
    ctx.lineTo(hx - r * 1.1 * f, hy + r * 0.9);
    ctx.closePath();
    ctx.fillStyle = "#9C3A34";
    ctx.fill();
  }
}
