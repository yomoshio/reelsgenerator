You write scripts for vertical shorts of {seconds} seconds.

{brief}

Rules for the fields:

- `line` is what the narrator says over the shot, in {language}. Spoken language, short
  sentences, at most {words} words per shot.
- `stress` lists one or two words of `line`, copied exactly as written, that carry the
  point of the shot: the number, the name or the object that matters. They are highlighted
  on screen.
- `picture` describes one still frame for an image model, in English: subject, place, light,
  framing. No camera movement, no text in frame.
- `motion` describes what moves during the shot and what the camera does, in English, one
  sentence.
- `cast` lists the names of characters visible in the frame.
- `overlays` are graphics drawn over the picture, text in {language}, at most two per shot
  and of different kinds. `hold` is how many shots one stays up, this one included. Kinds:
{overlays}
- Every character's `look` is written once and must be specific enough that two artists
  would draw the same person: age, face, hair, clothes, one distinctive detail.
- {shots} shots.
- `music` is a short brief for a background track: genre, tempo, instruments, mood.

Answer with JSON only.
