// Plates: every piece of text on screen besides the captions. Scene code never draws text;
// plates come from the beat's reveals, appear on the narrator's word and stay to the end of
// the beat, or of the episode. A plate pinned to someone or something finds free room near
// it, away from people, things and other plates, and points at it with a line.

import { SCENE_BOTTOM, SCENE_TOP, W, H, alpha } from "./places.mjs";
import { ease } from "./rig.mjs";

const CARD = "#E9DFC4", INK = "#1A1A1A", NUMBER = "#B3261E", WHITE = "#FFFFFF";

export function tones(p) {
  return {
    neutral: [p.neutral ?? "#ECE8DE", INK],
    threat: [p.threat ?? "#C8382D", WHITE],
    key: [p.key ?? "#F2C230", INK],
    solved: [p.solved ?? "#2E9E5B", WHITE],
  };
}

function font(ctx, size) {
  ctx.font = `${size}px Plate`;
}

export function measure(ctx, text, size) {
  font(ctx, size);
  return ctx.measureText(text.toUpperCase()).width;
}

function shadow(ctx) {
  ctx.shadowColor = "rgba(0,0,0,0.5)";
  ctx.shadowBlur = 10;
  ctx.shadowOffsetY = 5;
}

// The pill of a label or a status: [w, h] for a text at `size`.
export function pillSize(ctx, text, size) {
  return [measure(ctx, text, size) + 2 * size, Math.round(size * 1.75)];
}

function pill(ctx, x, y, text, tone, size, p) {
  const [fill, ink] = tones(p)[tone] ?? tones(p).neutral;
  const [w, h] = pillSize(ctx, text, size);
  ctx.save();
  shadow(ctx);
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, h / 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.restore();
  font(ctx, size);
  ctx.fillStyle = ink;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text.toUpperCase(), x + w / 2, y + h / 2 + size * 0.05);
  return [w, h];
}

// How a plate comes in: 0..1 of its entrance; scale, alpha and a shake.
function entrance(kind, t, start) {
  const lasts = kind === "stamp" ? 0.25 : kind === "hud" ? 0.3 : 0.3;
  const p = Math.min(Math.max((t - start) / lasts, 0), 1);
  if (kind === "stamp") {
    return { p, scale: 1.6 - 0.6 * Math.min(p / 0.6, 1), alpha: Math.min(p / 0.3, 1), shake: p > 0.6 && p < 1 ? 6 * Math.sin(p * 40) : 0 };
  }
  if (kind === "hud") return { p, scale: 1, alpha: ease(p), shake: 0 };
  const scale = p < 0.45 ? 0.7 + (0.4 * p) / 0.45 : 1.1 - (0.1 * (p - 0.45)) / 0.55;
  return { p, scale, alpha: Math.min(p / 0.35, 1), shake: 0 };
}

function around(ctx, cx, cy, e, draw) {
  ctx.save();
  ctx.globalAlpha *= e.alpha;
  ctx.translate(cx + e.shake, cy);
  ctx.scale(e.scale, e.scale);
  ctx.translate(-cx, -cy);
  draw();
  ctx.restore();
}

export function drawRuleCard(ctx, text, t, start, p) {
  const [number, ...rest] = text.split(" ");
  const body = rest.join(" ").toUpperCase();
  const small = 48, big = 66;
  const w = measure(ctx, number + " ", small) + measure(ctx, body, big) + 64, h = 112;
  const x = W / 2 - w / 2, y = 44;
  around(ctx, W / 2, y + h / 2, entrance("rule_card", t, start), () => {
    ctx.save();
    ctx.translate(W / 2, y + h / 2);
    ctx.rotate((-2.5 * Math.PI) / 180);
    ctx.translate(-W / 2, -(y + h / 2));
    shadow(ctx);
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 6);
    ctx.fillStyle = CARD;
    ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    font(ctx, small);
    ctx.fillStyle = NUMBER;
    ctx.fillText(number, x + 32, y + 62);
    font(ctx, big);
    ctx.fillStyle = INK;
    ctx.fillText(body, x + 32 + measure(ctx, number + " ", small), y + 80);
    ctx.restore();
  });
  return [x, y, w, h];
}

export function drawHud(ctx, text, t, start, p) {
  const size = 40, w = measure(ctx, text, size) + 56, h = 64, x = 36, y = SCENE_TOP + 16;
  around(ctx, x, y, entrance("hud", t, start), () => {
    ctx.fillStyle = "rgba(8,10,16,0.78)";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = p.key ?? "#F2C230";
    ctx.fillRect(x, y, 8, h);
    font(ctx, size);
    ctx.fillStyle = WHITE;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(text.toUpperCase(), x + 30, y + h / 2);
  });
  return [x, y, w, h];
}

// A stamp is as wide as the frame allows at most; `stampSize` gives its box before it is laid.
export function stampSize(ctx, text) {
  const full = measure(ctx, text, 104) + 90;
  const size = Math.floor(104 * Math.min(1, (W - 120) / full));
  return { size, w: measure(ctx, text, size) + 90 * (size / 104), h: Math.round(size * 1.63) };
}

export function drawStamp(ctx, text, t, start, p, cy = (SCENE_TOP + SCENE_BOTTOM) / 2) {
  const { size, w, h } = stampSize(ctx, text);
  const cx = W / 2;
  around(ctx, cx, cy, entrance("stamp", t, start), () => {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((-9 * Math.PI) / 180);
    const red = alpha(p.threat ?? "#C8382D", 0.92);
    ctx.beginPath();
    ctx.roundRect(-w / 2, -h / 2, w, h, 14);
    ctx.lineWidth = Math.max(size * 0.115, 6);
    ctx.strokeStyle = red;
    ctx.stroke();
    font(ctx, size);
    ctx.fillStyle = red;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text.toUpperCase(), 0, size * 0.06);
    ctx.restore();
  });
  return [cx - w / 2, cy - h / 2, w, h];
}

// A label or a count: the pill at its place, a line to the target that draws itself.
export function drawPinned(ctx, plate, t, p) {
  const { text, tone, start, at, target, size } = plate;
  const [w, h] = pillSize(ctx, text, size);
  const e = entrance("label", t, start);
  const [fill] = tones(p)[tone] ?? tones(p).neutral;
  if (target) {
    const from = [at[0] + w / 2, at[1] + (target[1] > at[1] ? h : 0)];
    const q = ease(Math.min((t - start) / 0.2, 1));
    ctx.beginPath();
    ctx.moveTo(...from);
    ctx.lineTo(from[0] + (target[0] - from[0]) * q, from[1] + (target[1] - from[1]) * q);
    ctx.setLineDash([12, 9]);
    ctx.lineWidth = 4;
    ctx.strokeStyle = alpha(fill.startsWith("#") ? fill : "#ECE8DE", 0.85);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(target[0], target[1], 7 * q, 0, 2 * Math.PI);
    ctx.fillStyle = fill;
    ctx.fill();
  }
  around(ctx, at[0] + w / 2, at[1] + h / 2, e, () => pill(ctx, at[0], at[1], text, tone, size, p));
}

// A status: the pill under its target with a bar in the same colour.
export function drawStatus(ctx, plate, t, p) {
  const { text, tone, start, at, size } = plate;
  const [w, h] = pillSize(ctx, text, size);
  const [fill] = tones(p)[tone] ?? tones(p).neutral;
  around(ctx, at[0] + w / 2, at[1] + h / 2, entrance("status", t, start), () => {
    pill(ctx, at[0], at[1], text, tone, size, p);
    ctx.beginPath();
    ctx.roundRect(at[0] + 8, at[1] + h + 6, w - 16, 10, 5);
    ctx.fillStyle = fill;
    ctx.fill();
  });
}

// The closing card of an episode: the next part and its question.
export function drawCard(ctx, t, card, p) {
  ctx.fillStyle = "#06080C";
  ctx.fillRect(0, 0, W, H);
  const e = ease(Math.min(t / 0.4, 1));
  ctx.globalAlpha = e;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  if (card.part) {
    font(ctx, 44);
    ctx.fillStyle = alpha(p.light ?? "#C4D4EC", 0.8);
    ctx.fillText(`ЧАСТЬ ${card.part}`.toUpperCase(), W / 2, H * 0.4 - 80);
  }
  const lines = wrap(ctx, card.text.toUpperCase(), 96, W - 160);
  font(ctx, 96);
  lines.forEach((l, i) => {
    ctx.fillStyle = i === lines.length - 1 ? (p.threat ?? "#C8382D") : WHITE;
    ctx.fillText(l, W / 2, H * 0.4 + i * 110);
  });
  ctx.globalAlpha = 1;
}

function wrap(ctx, text, size, width) {
  const out = [];
  let line = "";
  for (const word of text.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure(ctx, next, size) > width) {
      out.push(line);
      line = word;
    } else line = next;
  }
  if (line) out.push(line);
  return out;
}
