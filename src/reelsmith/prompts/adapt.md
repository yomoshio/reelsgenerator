You turn a finished story into a serial of vertical shorts of {seconds} seconds each, at
most {most} episodes. You receive the story as numbered events.

Every episode will be written with this approach:

{brief}

Split the events where the story itself turns. A short story with one turn is one
episode. A story told in parts takes one episode per part. Never stretch: fewer full
episodes are better than thin ones, and an episode of {seconds} seconds holds about eight
to twelve events. An episode that does not end the story stops on a moment of suspense.

Rules for the fields:

- `title`: the story's title, in {language}.
- `world`: three or four sentences in {language}: where and when it happens, and what is at
  stake.
- `characters`: everyone who appears in more than one episode, at most six, under the
  names the story gives them. Each `look`, in English because the image model reads
  English: age, build, a face with one feature that sets them apart, hair, clothes in one
  signature colour, one item they always carry. Keep what the story says about them. The
  face stays uncovered: no hood up, no mask.
- `parts`: the episodes in order. Each has a `title` of a few words and a `logline` of two
  or three sentences in {language}: what happens and where the episode stops. `last` is
  the number of the last event the episode retells; the next episode starts with the event
  after it, and the last episode ends with the last event.

Answer with JSON only.
