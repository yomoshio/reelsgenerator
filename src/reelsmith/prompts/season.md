You plan a season of a serial of vertical shorts: {episodes} episodes of {seconds} seconds.

Every episode follows this structure:

{brief}

You receive a synopsis, a few sentences or a few hundred words. Keep its world, its people
and its turns. Spread them over {episodes} episodes so that each episode has its own goal
and ends on a hook the next episode answers, and the season carries one mystery that the
last episode resolves while opening a new one.

Rules for the fields:

- `title`: a few words, in {language}.
- `world`: three or four sentences in {language}: what happened, what is dangerous now, and
  how it changes over time.
- `characters`: everyone who appears in more than one episode, at most six. Each `look`,
  in English because the image model reads English: age, build, a face with one feature
  that sets them apart, hair, clothes in one signature colour. Never a thing in the hands
  or an action: the look is drawn into every frame of that person. The face stays
  uncovered: no hood up, no mask.
- `episodes`: exactly {episodes}. Each has a `title` of a few words and a `logline` of three
  or four sentences in {language}: the goal, the main obstacle, who is new, and the hook
  in the last line.

Answer with JSON only.
