You write one part of a serial for vertical shorts of 60 to 95 seconds.

{brief}

The video is a dark motion infographic. Each beat is one still scene: one place from the
series library, the hero as a small figure in one pose, and a narrator who says two to four
lines in a row. The story moves on through graphics that come up on the narrator's words:
a numbered rule card, a status plate by the hero, a red stamp, a label on a thing, a
circle that magnifies a detail, a prop that changes step by step. The camera never moves
and nobody is animated, so what the viewer learns must be in the lines and the graphics.

The viewers speak {language}. The `title`, `hook`, `hud`, `cliffhanger`, every `line` and
every reveal's `text` are in {language}. A script with a line in another language goes
back to you.

Rules for the fields:

- `title`: the episode's name in a few words; it is posted under the video.
- `part`: the number of this part in the serial.
- `hook`: at most eight words, a question to the viewer or a threat, with the danger in
  it. It is also the first line of beat 1, word for word.
- `hud`: day and time shown at the top, such as "ДЕНЬ 3 · 02:41".
- `beats`: nine to sixteen beats. Read aloud at a calm pace, the episode runs 60 to 95
  seconds and each beat 3.5 to 11 seconds: two short lines are about four seconds, four
  long ones about ten. At least four beats run longer than seven seconds, and each of
  them brings up at least two graphics.
- `cliffhanger`: the question on the closing card that announces the next part, two to
  four words, such as "КТО ПОД НАМИ?".
- `music`: a short brief in English for a low background drone: tempo, instruments, mood.

Rules for a beat:

- `location` and `pose` are keys of the library below, as written there. The place
  changes only from one beat to the next; to show the hero doing something else within a
  beat, use a `pose` reveal.
- `lines`: two to four sentences of spoken {language} in a row, as a storyteller says
  them: present tense, third person, plain words, one fact per sentence, numbers as words.
  Mix short and longer sentences. Each beat moves the story by one step.
- `delivery`: a few English words on how the narrator says the beat, such as "quiet and
  collected, a pause before the rule" or "fast, breathless".
- `reveals`: one to five graphics. Each comes up as the narrator says `on_word`, a single
  word of this beat's `lines` copied exactly as written there; if that word is said more
  than once in the beat, `occurrence` says which time. Put a graphic on the word that names
  what it shows, so the viewer hears and sees it at once. A graphic stays up to the end of
  the beat; `persist: "episode"` keeps it up through the following beats, for a rule card
  until the next rule card replaces it.
- `text` of a reveal: at most four words in {language}. Digits are fine here: "1. ТИШИНА",
  "ЭТАЖ 31".
- `target`: an anchor of the beat's location from the library for `label`, `status`,
  `lens`, `diagram_step`; the prop for `prop_stage`; the new pose for `pose`; empty for
  `rule_card`, `hud` and `stamp`.
- `style`: "threat" in red for danger, "key" in yellow for the word that matters, "solved"
  in green for a problem dealt with, "neutral" otherwise.
- `sfx`: one sound of the library per reveal, in the same order; leave it shorter if a
  reveal should be silent.

Kinds of reveals:
  - `rule_card`: the numbered rule at the top, "1. ТИШИНА". An episode has two to four
    rules, numbered from 1 in order, each said aloud by the narrator in its beat.
  - `hud`: the day and time strip at the top, when time jumps.
  - `label`: a caption pinned to a thing in the scene.
  - `status`: a coloured plate by the hero or a thing, a state in a few words.
  - `stamp`: a red stamp across the scene, one or two words, for a verdict or a twist.
  - `diagram_step`: one step of a diagram drawn over the scene: a floor, a path, a line.
  - `lens`: a circle that magnifies the anchor in `target`.
  - `prop_stage`: the prop in `target` goes to its next stage.
  - `pose`: the hero jumps to the pose in `target`.

Beat 1 opens with the hook as its first line and brings up a graphic with style "threat"
on a word of the hook, within the first two seconds.

The series library, the only places, anchors, poses, props and sounds you may use:

{library}

Two beats from another series, to show the shape. Use this series' library and your own
story, never their words:

```json
{examples}
```

Answer with JSON only.
