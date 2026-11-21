// Beat: «Он достаёт высохшую обезьянью лапу и кладёт её на стол рядом с шахматной доской.
// Правило второе: один взгляд в огонь открывает дверь.»
// Staging: wide; Morris takes the paw out of his coat and lays it on the table; on «огонь»
// the fire flares and Mr White turns to it, on «открывает» the door swings open.
// Things: table, window, fireplace, door, monkey_paw (not in the catalog: drawn with s.prop).
function scene(s) {
  s.place("room");
  s.light(0.55);
  const door = s.thing("door", { x: 0.12 });
  s.thing("window", { x: 0.36 });
  const fire = s.thing("fireplace", { x: 0.84, state: 2 });
  const table = s.thing("table", { x: 0.5 });
  const white = s.person("mr_white", { x: 0.3, mood: "worried" });
  const morris = s.person("morris", { x: 0.7, facing: "left", mood: "tired" });
  const paw = s.prop("monkey_paw", { size: 70, draw: (ctx) => {
    ctx.fillStyle = "#5A4630";
    ctx.beginPath(); ctx.ellipse(0, 12, 17, 22, 0, 0, 2 * Math.PI); ctx.fill();
    for (let i = -2; i <= 2; i++) ctx.fillRect(i * 8 - 3, -32, 6, 30);
    ctx.fillStyle = "#3B2D1E";
    ctx.fillRect(-9, 28, 18, 8);
  } });

  morris.take(paw, { from: "pocket", at: "достаёт" });
  white.look(paw, { at: "лапу" });
  morris.put(paw, { on: table, at: "кладёт" });
  s.camera.push({ to: paw, at: "кладёт", zoom: 1.3 });

  s.camera.back({ at: "Правило" });
  fire.state(3, { at: "огонь" });
  white.look(fire, { at: "огонь" });
  white.mood("scared", { at: "огонь" });
  door.state(1, { at: "открывает" });
  morris.point(door, { at: "дверь" });
}
