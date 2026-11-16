# Scene API

You write `function scene(s) { ... }`. It runs once and declares what happens in the beat;
the runtime draws every frame from your declarations. Do not draw frames yourself, do not
loop over time, do not keep state between calls.

The frame is 1080 × 1920. The scene lives between y = 180 and y = 1150; captions are drawn
below it. `x` values from 0 to 1 are fractions of the width (0.5 is the middle); larger
values are pixels.

## Time

Every `at` is a word of the beat (`at: "банкомат"`, the moment the narrator starts saying
it), `{ word: "нет", n: 2 }` for its second time, or a number of seconds from the start of
the beat. Use the narrator's words: the picture changes when the viewer hears why.
`s.at(word, n)` gives the seconds; `s.seconds` is the beat's length; `s.words` its words.

## Place

```js
s.place("room");                    // room, shop, stairwell, section, street, outdoors, custom
s.place("room", { light: 0.3 });    // where the light falls from, 0..1 across
s.place("section", { floors: 9, first: 1 });   // a cut through a building
```

Call it first. Without it the beat's own place kind is used.

## Things

```js
const bed = s.thing("bed", { x: 0.28 });          // stands on the ground at x
const atm = s.thing("atm", { x: 0.2, state: 0 });
const win = s.thing("window", { x: 0.72 });       // wall things hang at their own height
s.thing("water", { state: 0 });                   // fills the room from the floor
s.thing("lamp", { x: 0.5, state: 1 });            // hangs from the ceiling; state 0 is off
const shelf = s.thing("shelf", { x: 0.8, front: true });  // drawn in front of people
const table = s.thing("table", { x: 0.3 });
s.thing("candle_holder", { on: table, scale: 0.5 });      // stands on the table's top
```

Options: `x`, `scale` (1 is natural), `flip`, `state`, `front`, `level` (the floor of a
section), `on` (another thing with a top or a seat to stand on). Things stand on the
ground by themselves; never give a y. Small things from the library, such as a candle, a
phone or a necklace, usually stand `on` a table, a counter or a shelf, at `scale` 0.3–0.6.

- `atm.state(2, { at: "ошибка" })`: change state, eased over a second. Water: 0 ankle,
  1 knee, 2 waist, 3 chest. Atm: 0 idle, 1 lit, 2 red error. Door: 0 shut, 1 open.
  Wardrobe: 0 upright, 1 fallen. Lamp: 0 off, 1 on.
- `atm.move({ to: 0.6, at: "двигает" })`: slide along the ground.
- `atm.part("screen")`: a point to reach, point at, magnify or start ripples from.

Parts: door handle, middle · window glass · bed seat, pillow · bench seat · chair seat ·
table top · counter top, front · shelf top, middle · wardrobe door, top · atm screen, slot,
keys · lamp bulb · railing rail · pipe middle, top · radiator top · water surface.

## People

```js
const ivan = s.person("ivan", { x: 0.6, facing: "left" });
```

Only the characters of the episode, by key, each once. Options: `x`, `facing` ("left" or
"right"), `pose`, `level` (a floor of a section). The rig draws them from their card; you
only place and move them. They breathe and sway by themselves.

- `ivan.walk({ to: atm, at: "подходит" })`: walks to stand beside a thing or a person, or
  to an x (`to: 0.3`). `until` sets when they arrive.
- `ivan.sit(bed, { at: "садится" })` and `ivan.stand({ at: "встаёт" })`: sits on a thing with
  a seat (bed, bench, chair), walking to it first.
- `ivan.reach(atm.part("slot"), { at: "карту" })`, `ivan.point(atm, { at })`,
  `ivan.knock(door, { at })`: the near hand goes to the target.
- `ivan.pose(name, { at })`: stand, walk, listen, look_down, sit, hold, knock, point, reach,
  arms_out.
- `ivan.look(atm, { at })` or `ivan.look("left", { at })`: turns to face it.
- `ivan.enter({ from: "right", at: "входит" })`: walks in from off the frame to their x.

## Camera, light

```js
s.camera.push({ to: atm.part("screen"), at: "экран", zoom: 1.25 });  // move in on a target
s.camera.pan({ to: ivan, at: "оборачивается" });                     // follow without zoom
s.camera.back({ at: "снова" });                                      // back to the whole set
s.light(0.2, { at: "гаснет" });                 // 1 full light, 0 dark; people with a torch light a cone
s.light(0.6, { at: "мигает", flicker: true, until: "гаснет" });
```

The camera never shows past the edge of the set, so a push near an edge moves less.

## Devices

One only where it explains what the eye cannot see; at most two in a beat.

```js
s.device("lens", { on: atm.part("screen"), at: "ошибка", zoom: 2.2 });  // a magnified circle
s.device("ripples", { from: door.part("middle"), at: "стук", until: "тишина" });
s.device("ripples", { from: pipe.part("middle"), along: pipe, at: "стучит" });  // up the pipe
s.device("dashed", { from: ivan, to: atm, at: "видит", tone: "key" });
s.device("route", { points: [ivan, door, [0.9, 1000]], at: "идёт" });
s.device("counter", { from: 1000, to: 0, at: "списывает", until: "ноль", x: 0.8 });
s.device("section", { floors: 9, highlight: 3, at: "этаже" });          // an inset cut
```

`tone` is key (yellow), threat (red), solved (green) or neutral.

## Your own drawing

```js
s.draw((ctx, t) => {
  ctx.fillStyle = "rgba(255,214,150,0.2)";
  ctx.beginPath(); ctx.arc(540, 400, 60 + 10 * Math.sin(t * 3), 0, 2 * Math.PI); ctx.fill();
}, { layer: "back" });   // back: behind things; front: over people; top: over everything
```

A plain canvas for what no thing or device draws: a crack in a wall, a glow, smoke. It is
called for every frame with the time `t`; draw from `t`, never keep state. It cannot draw
text, and it has a quarter of a second.

## Plates

Text on screen comes only from the beat's plates. They appear on their words by
themselves and find room near their target; a plate's target must be on stage, so place
every person and thing a plate points at.
