// Beat: «Что делать, если вода уже по колено? Артём просыпается на третьем этаже, и рука
// свисает прямо в ледяную воду. Ночью выше по реке прорвало дамбу.»
// Staging: wide; Artem sits up on the bed as he wakes, the water rises to his knees on
// «ледяную», he turns to the window on «Ночью». Things: bed, window, door, water.
function scene(s) {
  s.place("room", { light: 0.6 });
  const bed = s.thing("bed", { x: 0.28 });
  const win = s.thing("window", { x: 0.7 });
  s.thing("door", { x: 0.9 });
  const water = s.thing("water", { state: 0 });
  const artem = s.person("artem", { x: 0.45 });
  artem.sit(bed, { at: 0 });
  water.state(1, { at: "ледяную" });
  artem.look(win, { at: "Ночью" });
  s.camera.push({ to: bed, at: "просыпается", zoom: 1.1 });
}
