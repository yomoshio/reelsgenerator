// Beat: «Моррис бросает проклятый предмет в огонь, а мистер Уайт выхватывает его из горячих
// углей. Правило третье: никто не держит лапу дольше минуты.»
// Staging: medium; Morris takes the paw off the table and throws it into the fire; Mr White
// runs to the hearth and takes it out; on «держит» Morris points at it and the camera goes in.
// Things: table, fireplace, monkey_paw (drawn with s.prop, it starts on the table).
function scene(s) {
  s.place("room");
  s.light(0.5);
  const table = s.thing("table", { x: 0.42 });
  const fire = s.thing("fireplace", { x: 0.84, state: 2 });
  const white = s.person("mr_white", { x: 0.68, mood: "worried" });
  const morris = s.person("morris", { x: 0.12, mood: "angry" });
  const paw = s.prop("monkey_paw", { size: 70, on: table, draw: (ctx) => {
    ctx.fillStyle = "#5A4630";
    ctx.beginPath(); ctx.ellipse(0, 12, 17, 22, 0, 0, 2 * Math.PI); ctx.fill();
    for (let i = -2; i <= 2; i++) ctx.fillRect(i * 8 - 3, -32, 6, 30);
    ctx.fillStyle = "#3B2D1E";
    ctx.fillRect(-9, 28, 18, 8);
  } });

  morris.take(paw, { at: 0.3 });
  morris.throw(paw, { to: fire, at: "бросает" });
  fire.state(3, { at: "огонь" });
  white.mood("scared", { at: "огонь" });
  white.walk({ to: fire, at: "Уайт" });
  white.take(paw, { at: "выхватывает" });
  fire.state(2, { at: "углей" });
  white.look(morris, { at: "Правило" });
  morris.point(paw, { at: "держит" });
  s.camera.push({ to: paw, at: "держит", zoom: 1.35 });
}
