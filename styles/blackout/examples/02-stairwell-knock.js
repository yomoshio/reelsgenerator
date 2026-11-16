// Beat: «Марк не отвечает стуком. Любой звук по трубе так же легко выдаст, где он. Поэтому
// первое — тишина.»
// Staging: medium; Mark stands by the riser pipe; on «звук» rings run up the pipe, on
// «выдаст» he steps back from it and looks up. Things: pipe, door. Devices: ripples.
function scene(s) {
  s.place("stairwell", { stairs: 0.6 });
  const pipe = s.thing("pipe", { x: 0.32 });
  s.thing("door", { x: 0.12 });
  const mark = s.person("mark", { x: 0.5, facing: "left" });
  mark.reach(pipe.part("middle"), { at: "отвечает" });
  s.device("ripples", { from: pipe.part("middle"), along: pipe, at: "звук", until: "Поэтому" });
  mark.walk({ to: 0.62, at: "выдаст" });
  mark.look(pipe, { at: "выдаст" });
  mark.pose("look_down", { at: "тишина" });
  s.camera.push({ to: pipe.part("middle"), at: "звук", zoom: 1.15 });
}
