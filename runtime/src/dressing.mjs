// What a room has in it before the story puts anything there: panelling and a rail on the
// wall, a rug, pictures, a clock or a shelf of books where the wall is free, a plant in a
// corner. Chosen by the place's seed, so a room looks the same every time the story comes
// back to it, and laid around the things of the scene, never over them.

import { W, alpha, rng, shade } from "./places.mjs";
import { overlap } from "./layout.mjs";

const OUT = "rgba(9,12,22,0.42)";
const WOOD = "#4E4038";

function framed(ctx, x, y, w, h, colour) {
  ctx.fillStyle = OUT;
  ctx.fillRect(x - 3, y - 3, w + 6, h + 6);
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, shade(colour, 1.15));
  g.addColorStop(1, shade(colour, 0.78));
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);
}

function picture(ctx, cx, cy, r, p) {
  const tall = r() < 0.5;
  const [w, h] = tall ? [150, 196] : [214, 150];
  const x = cx - w / 2, y = cy - h / 2;
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fillRect(x + 8, y + 10, w, h);
  framed(ctx, x, y, w, h, WOOD);
  framed(ctx, x + 14, y + 14, w - 28, h - 28, shade(p.neutral, 0.42));
  const [ix, iy, iw, ih] = [x + 24, y + 24, w - 48, h - 48];
  ctx.save();
  ctx.beginPath();
  ctx.rect(ix, iy, iw, ih);
  ctx.clip();
  const sky = ctx.createLinearGradient(0, iy, 0, iy + ih);
  sky.addColorStop(0, "#39506E");
  sky.addColorStop(1, "#8A7A6A");
  ctx.fillStyle = sky;
  ctx.fillRect(ix, iy, iw, ih);
  for (const [k, tone] of [[0.62, "#3F5A4E"], [0.78, "#2C4038"]]) {
    ctx.beginPath();
    ctx.moveTo(ix, iy + ih);
    for (let q = 0; q <= 6; q++) ctx.lineTo(ix + (iw * q) / 6, iy + ih * (k - 0.16 * r()));
    ctx.lineTo(ix + iw, iy + ih);
    ctx.fillStyle = tone;
    ctx.fill();
  }
  ctx.beginPath();
  ctx.arc(ix + iw * (0.25 + 0.5 * r()), iy + ih * 0.3, 11, 0, 2 * Math.PI);
  ctx.fillStyle = "#E8D8B0";
  ctx.fill();
  ctx.restore();
  return [x, y, w, h];
}

function clock(ctx, cx, cy, r, p) {
  const R = 54;
  ctx.beginPath();
  ctx.arc(cx + 6, cy + 8, R, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fill();
  for (const [rad, tone] of [[R + 3, OUT], [R, WOOD], [R - 10, shade(p.neutral, 0.6)]]) {
    ctx.beginPath();
    ctx.arc(cx, cy, rad, 0, 2 * Math.PI);
    ctx.fillStyle = tone;
    ctx.fill();
  }
  ctx.strokeStyle = "#1A1A1E";
  ctx.lineCap = "round";
  for (let k = 0; k < 12; k++) {
    const a = (k * Math.PI) / 6;
    ctx.lineWidth = k % 3 ? 2 : 4;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * (R - 18), cy + Math.sin(a) * (R - 18));
    ctx.lineTo(cx + Math.cos(a) * (R - 13), cy + Math.sin(a) * (R - 13));
    ctx.stroke();
  }
  for (const [a, len, width] of [[r() * 6.28, 24, 5], [r() * 6.28, 34, 3]]) {
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(a) * len, cy + Math.sin(a) * len);
    ctx.stroke();
  }
  return [cx - R, cy - R, 2 * R, 2 * R];
}

function books(ctx, cx, cy, r) {
  const w = 230;
  const x = cx - w / 2;
  let bx = x + 10;
  const tones = ["#6E3E3C", "#85744A", "#3C5670", "#4A5C42", "#77756E", "#59456A"];
  while (bx < x + w - 70) {
    const bw = 16 + r() * 14, bh = 52 + r() * 34;
    framed(ctx, bx, cy - bh, bw, bh, tones[Math.floor(r() * tones.length)]);
    bx += bw + 3;
  }
  ctx.beginPath();
  ctx.ellipse(x + w - 34, cy - 26, 16, 26, 0, 0, 2 * Math.PI);
  ctx.fillStyle = OUT;
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(x + w - 34, cy - 26, 13, 23, 0, 0, 2 * Math.PI);
  ctx.fillStyle = "#6E8A9A";
  ctx.fill();
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fillRect(x + 6, cy + 14, w, 10);
  framed(ctx, x, cy, w, 14, WOOD);
  for (const sx of [x + 30, x + w - 40]) framed(ctx, sx, cy + 14, 10, 22, shade(WOOD, 0.7));
  return [x, cy - 90, w, 130];
}

function plant(ctx, cx, floor, r) {
  ctx.save();
  ctx.filter = "blur(8px)";
  ctx.beginPath();
  ctx.ellipse(cx, floor + 16, 62, 12, 0, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fill();
  ctx.restore();
  for (let k = 0; k < 9; k++) {
    const a = -Math.PI / 2 + (k - 4) * 0.3 + (r() - 0.5) * 0.2, len = 120 + r() * 90;
    const tip = [cx + Math.cos(a) * len, floor - 86 + Math.sin(a) * len];
    const mid = [cx + Math.cos(a) * len * 0.5 + 18 * Math.sign(k - 4.5), floor - 86 + Math.sin(a) * len * 0.55];
    for (const [width, tone] of [[30, OUT], [24, k % 2 ? "#2F4A40" : "#38584A"]]) {
      ctx.beginPath();
      ctx.moveTo(cx, floor - 80);
      ctx.quadraticCurveTo(mid[0] - width / 2, mid[1], ...tip);
      ctx.quadraticCurveTo(mid[0] + width / 2, mid[1], cx, floor - 80);
      ctx.fillStyle = tone;
      ctx.fill();
    }
  }
  ctx.beginPath();
  ctx.moveTo(cx - 46, floor - 86);
  ctx.lineTo(cx + 46, floor - 86);
  ctx.lineTo(cx + 34, floor + 14);
  ctx.lineTo(cx - 34, floor + 14);
  ctx.closePath();
  ctx.lineWidth = 5;
  ctx.strokeStyle = OUT;
  ctx.stroke();
  const g = ctx.createLinearGradient(cx - 46, 0, cx + 46, 0);
  g.addColorStop(0, "#54403A");
  g.addColorStop(1, "#7A5C4C");
  ctx.fillStyle = g;
  ctx.fill();
  framed(ctx, cx - 50, floor - 96, 100, 14, "#6E5448");
}

// `taken` are the boxes of the scene's things; `walls` is how far the side walls come in.
export function dress(ctx, taken, floor, p, seed, walls) {
  const r = rng(seed ^ 0x51ed);
  const left = walls, right = W - walls;

  // The wall: paper in stripes, a rail, and panelling under it.
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, 0, right - left, floor - 26);
  ctx.clip();
  for (let x = left + 20; x < right; x += 46) {
    ctx.fillStyle = alpha(p.light, x % 92 < 46 ? 0.022 : 0.006);
    ctx.fillRect(x, 0, 23, floor - 320);
  }
  const rail = floor - 320;
  ctx.fillStyle = "rgba(0,0,0,0.16)";
  ctx.fillRect(left, rail, right - left, 300);
  for (let x = left + 26; x < right - 40; x += 190) {
    ctx.strokeStyle = alpha(p.light, 0.07);
    ctx.lineWidth = 3;
    ctx.strokeRect(x, rail + 44, 150, 214);
    ctx.strokeStyle = "rgba(0,0,0,0.3)";
    ctx.strokeRect(x + 3, rail + 47, 150, 214);
  }
  ctx.fillStyle = shade(p.line, 1.25);
  ctx.fillRect(left, rail, right - left, 12);
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fillRect(left, rail + 12, right - left, 5);
  ctx.restore();

  // A rug across the middle of the floor, seen from above and from the side at once.
  const tone = ["#4E2E34", "#2C4254", "#463E34"][Math.floor(r() * 3)];
  const [x0, x1, y0, y1] = [W * 0.2, W * 0.8, floor + 44, floor + 150];
  const rug = (grow, colour) => {
    ctx.beginPath();
    ctx.moveTo(x0 + 34 - grow, y0 - grow * 0.4);
    ctx.lineTo(x1 - 34 + grow, y0 - grow * 0.4);
    ctx.lineTo(x1 + 30 + grow, y1 + grow * 0.4);
    ctx.lineTo(x0 - 30 - grow, y1 + grow * 0.4);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
  };
  rug(4, OUT);
  rug(0, tone);
  rug(-16, shade(tone, 1.3));
  rug(-24, shade(tone, 0.85));

  // The upper wall, wherever no thing of the scene is in the way.
  const laid = [...taken];
  const fits = (b) => b[0] > left + 24 && b[0] + b[2] < right - 24 && laid.every((q) => overlap(b, [q[0] - 24, q[1] - 24, q[2] + 48, q[3] + 48]) === 0);
  const spots = [];
  for (let x = left + 130; x <= right - 130; x += 44) spots.push(x);
  spots.sort(() => r() - 0.5);
  const kinds = [picture, clock, books, picture].sort(() => r() - 0.5);
  let hung = 0;
  for (const cx of spots) {
    if (hung >= 3) break;
    const cy = floor - 560 + Math.round(r() * 50);
    const size = kinds[hung] === books ? [240, 150] : kinds[hung] === clock ? [116, 116] : [220, 200];
    if (!fits([cx - size[0] / 2, cy - size[1] / 2, ...size])) continue;
    laid.push(kinds[hung](ctx, cx, cy, r, p));
    hung++;
  }

  // A plant in whichever corner is free.
  for (const cx of r() < 0.5 ? [left + 78, right - 78] : [right - 78, left + 78]) {
    if (laid.some((q) => overlap([cx - 80, floor - 300, 160, 320], q) > 0)) continue;
    plant(ctx, cx, floor, r);
    break;
  }
}
