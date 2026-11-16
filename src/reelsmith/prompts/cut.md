You cut the voiceover of one episode of a vertical short into beats. You receive the plan:
the people with their keys, the places with their keys, the beats of the story and the
whole narration.

{brief}

A beat is one place, the people seen in it, two to four lines the narrator says in a row,
and plates that come up on the narrator's words. The picture is drawn later from your
beats, so every beat must say where it is and who is in it.

Rules:

- The `lines` of all beats together are the narration, word for word and in order, cut at
  sentence ends. Add nothing, drop nothing, change no word: not a particle, not a number.
- {beats} beats. A beat runs 3.5 to 11 seconds read aloud: two short lines are about four
  seconds, four long ones about ten. At least four beats run longer than seven seconds,
  and half of the beats run at most seven.
- `place`: the key of the place where this beat happens. It changes only where the story
  moves.
- `cast`: the keys of the characters seen in this beat; never empty when someone acts.
- `delivery`: a few English words on how the narrator says the beat, such as "quiet and
  collected, a pause before the rule" or "fast, breathless".
- `hook`: the first line of beat 1, word for word.
- `hud`: day and time shown at the top, such as "ДЕНЬ 3 · 02:41", when the story keeps
  time; otherwise empty.
- `cliffhanger`: when the story goes on in another episode, the question on the closing
  card, two to four words, such as "КТО ПОД НАМИ?"; otherwise empty.
- `music`: a short English brief for the music under the episode.

Plates (`reveals`), one to five per beat; a beat longer than seven seconds has at least
two:

- `on_word`: one word of this beat's `lines`, copied exactly as written there; if it is
  said more than once in the beat, `occurrence` says which time. Put a plate on the word
  that names what it shows, so the viewer hears and sees it at once.
- `text`: at most four words in {language}. Digits are fine here: "1. ТИШИНА", "ЭТАЖ 31".
- `kind`:
  - `rule_card`: the numbered rule at the top, "1. ТИШИНА". {rules}
  - `hud`: the day and time strip at the top, when time jumps.
  - `label`: a caption pinned to a thing or a person in the scene.
  - `status`: a coloured plate by a person or a thing, a state in a few words.
  - `stamp`: a red stamp across the scene, one or two words, for a verdict or a twist.
  - `count`: a number the story keeps, such as money left or floors to go.
- `target`: for `label`, `status` and `count`, the key of a character in the beat or the
  English name of a thing in the place, such as "atm", "pipe", "door"; empty otherwise.
- `tone`: "threat" in red for danger, "key" in yellow for the word that matters, "solved"
  in green for a problem dealt with, "neutral" otherwise.
- `persist`: "episode" keeps the plate up through the following beats, as a rule card
  stays until the next one; "beat" otherwise.

Beat 1 opens with the hook as its first line and brings up a plate with tone "threat" on a
word of the hook, within the first two seconds.

Answer with JSON only.
