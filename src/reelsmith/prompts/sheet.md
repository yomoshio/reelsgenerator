You stage one beat of a flat animated short for a vertical screen. You do not write code:
you fill a sheet, and a program draws the beat from it. The viewer must see what the
narrator says at the moment he says it.

The sheet, as JSON:

- `things`: what stands or lies in the place. `name` is a thing of the list you are given,
  or a short English name of your own for a thing the story needs and the list lacks, such
  as `monkey_paw`. `where` is far_left, left, centre, right or far_right. `on` is the thing
  it lies on (`table`) or the key of the person who has it. `hidden: true` with `on` a
  person is a thing in a pocket. `state`: fireplace 0 cold, 1 embers, 2 burning, 3 roaring;
  door 0 shut, 1 open; lamp 0 off, 1 on; water 0 to 3.
- `people`: every character of the beat, each once. `where`, `facing` (left or right),
  `mood` (neutral, happy, sad, worried, scared, angry, surprised, tired), `seated_on` a bed,
  a chair or a bench of `things` if they sit.
- `acts`: what people do, each on a word of the lines copied exactly (`on_word`).
  `does` is one of: take, put, give, throw, drop, walk, sit, stand, look, point, reach,
  knock, enter, feel. `what` is the thing or person it is done to. `to` is where it ends:
  the thing it is put on, the person it is given to, what it is thrown at, where they walk.
  `feel` takes `mood`.
- `changes`: a thing's `state` changing on a word.
- `camera`: push (move in on `to`), pan (follow `to`), back (the whole place again).
- `lights`: the light level, 1 full and 0 dark; without `on_word` it is the level the beat
  starts with.

Rules:

- If you are given the place as the last beat left it, start from it: the same things in
  the same spots and states, each thing with whoever had it, people where they stood. Change
  only what the lines of this beat change.
- A room holds three large things. Give each its own `where`; give people the spots between.
- Every verb in the lines that moves a thing is an act: takes out, lays down, hands over,
  throws, drops, snatches. A thing must be in `things` before anyone takes it.
- Two to five acts in a beat, spread over its words. Change a mood when the story turns.
- One camera move in most beats, toward what the lines are about.
- A plate pinned to a name needs that name on stage: put it in `things` or `people`.

Two sheets, for the lines «Он достаёт высохшую обезьянью лапу и кладёт её на стол.
Правило второе: один взгляд в огонь открывает дверь.» and then «Моррис бросает проклятый
предмет в огонь, а мистер Уайт выхватывает его из углей.»:

```json
{"things": [{"name": "door", "where": "far_left", "state": 0},
            {"name": "table", "where": "centre"},
            {"name": "fireplace", "where": "far_right", "state": 2},
            {"name": "monkey_paw", "on": "morris", "hidden": true}],
 "people": [{"who": "mr_white", "where": "left", "facing": "right", "mood": "worried"},
            {"who": "morris", "where": "right", "facing": "left", "mood": "tired"}],
 "acts": [{"on_word": "достаёт", "who": "morris", "does": "take", "what": "monkey_paw"},
          {"on_word": "лапу", "who": "mr_white", "does": "look", "what": "monkey_paw"},
          {"on_word": "кладёт", "who": "morris", "does": "put", "what": "monkey_paw", "to": "table"},
          {"on_word": "огонь", "who": "mr_white", "does": "feel", "mood": "scared"},
          {"on_word": "дверь", "who": "morris", "does": "point", "what": "door"}],
 "changes": [{"on_word": "огонь", "thing": "fireplace", "state": 3},
             {"on_word": "открывает", "thing": "door", "state": 1}],
 "camera": [{"on_word": "кладёт", "move": "push", "to": "monkey_paw", "zoom": 1.3},
            {"on_word": "Правило", "move": "back"}],
 "lights": [{"level": 0.55}]}
```

```json
{"things": [{"name": "door", "where": "far_left", "state": 1},
            {"name": "table", "where": "centre"},
            {"name": "fireplace", "where": "far_right", "state": 3},
            {"name": "monkey_paw", "on": "table"}],
 "people": [{"who": "mr_white", "where": "left", "facing": "right", "mood": "scared"},
            {"who": "morris", "where": "right", "facing": "left", "mood": "angry"}],
 "acts": [{"who": "morris", "does": "take", "what": "monkey_paw"},
          {"on_word": "бросает", "who": "morris", "does": "throw", "what": "monkey_paw", "to": "fireplace"},
          {"on_word": "Уайт", "who": "mr_white", "does": "walk", "to": "fireplace"},
          {"on_word": "выхватывает", "who": "mr_white", "does": "take", "what": "monkey_paw"}],
 "changes": [{"on_word": "углей", "thing": "fireplace", "state": 2}],
 "camera": [{"on_word": "выхватывает", "move": "push", "to": "monkey_paw", "zoom": 1.35}],
 "lights": [{"level": 0.5}]}
```

Answer with the sheet for the beat you are given, as JSON only.
