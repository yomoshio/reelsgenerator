"""The stage of a beat, drawn by vector code for every frame: the place, the hero and the
people with him, and the props the story changes. Everything is antialiased and placed to a
fraction of a pixel, so a slow move is smooth, and nothing in the picture is ever invented:
the hero is the same figure in every frame of every episode.

The hero is a rig of joints. A pose is a set of angles; between poses the angles ease over a
fraction of a second, so the hero moves instead of jumping. A pose `hand_on_<anchor>` bends
the arm until the hand rests on that anchor. On top of any pose he breathes and sways a
little, and `walk` swings the legs and arms in step.

A place is laid out from its anchors: a room with a wall and a floor, a stairwell, or a cut
through a building when it has `floor_<n>` anchors. Each anchor with a known name brings its
object: a door, a window, a bed, a workbench, a railing, a wardrobe. Water rises and sinks in
steps as the story's `prop_stage` reveals say, and a moved wardrobe slides aside."""

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache

import skia
from PIL import Image

from reelsmith.beats import Anchor, Location

W, H = 1080, 1920
SCENE_BOTTOM = 1150
HERO = 560  # px from soles to the crown; about 29% of the frame, as in the reference
EASE = 0.45  # seconds a change of pose takes
Color = tuple[int, int, int]
Point = tuple[float, float]


def rgb(c: Color, alpha: int = 255) -> int:
    return skia.Color(c[0], c[1], c[2], alpha)


def shade(c: Color, k: float) -> Color:
    """The colour darker (k < 1) or lighter (k > 1)."""
    if k <= 1:
        return (round(c[0] * k), round(c[1] * k), round(c[2] * k))
    return tuple(round(v + (255 - v) * (k - 1)) for v in c)  # type: ignore[return-value]


def fill(c: Color, alpha: int = 255) -> skia.Paint:
    return skia.Paint(AntiAlias=True, Color=rgb(c, alpha))


def stroke(c: Color, width: float, alpha: int = 255) -> skia.Paint:
    return skia.Paint(
        AntiAlias=True,
        Color=rgb(c, alpha),
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=width,
        StrokeCap=skia.Paint.kRound_Cap,
        StrokeJoin=skia.Paint.kRound_Join,
    )


def glow(c: Color, alpha: int, blur: float) -> skia.Paint:
    return skia.Paint(
        AntiAlias=True,
        Color=rgb(c, alpha),
        MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur),
    )


def vertical(top: float, bottom: float, colors: Sequence[Color], alphas: Sequence[int] = ()) -> skia.Paint:
    stops = [rgb(c, alphas[i] if alphas else 255) for i, c in enumerate(colors)]
    shader = skia.GradientShader.MakeLinear([skia.Point(0, top), skia.Point(0, bottom)], stops)
    return skia.Paint(AntiAlias=True, Shader=shader)


def ease(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


# --- palette -----------------------------------------------------------------------------

NIGHT = (14, 19, 29)
WALL, WALL_LOW = (40, 50, 69), (30, 38, 54)
FLOOR, FLOOR_FAR = (19, 24, 35), (11, 14, 21)
LINE = (46, 57, 78)
TRIM = (52, 63, 84)
WOOD, WOOD_DARK = (112, 82, 58), (78, 56, 40)
STEEL, STEEL_LIT = (104, 114, 128), (182, 192, 204)
GLASS, GLASS_LOW = (34, 58, 92), (22, 38, 62)
WATER = (52, 104, 128)
LIGHT = (196, 212, 236)
RIM = (150, 168, 200)
WARM = (255, 214, 150)


# --- people ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    """How one character is drawn: the colours of the figure and its height in pixels at
    the size the place shows people."""

    skin: Color = (224, 180, 140)
    hair: Color = (30, 27, 28)
    top: Color = (46, 70, 112)
    legs: Color = (28, 33, 46)
    shoes: Color = (16, 18, 24)
    hair_style: str = "short"
    torch: bool = False
    scale: float = 1.0  # of the hero's height


HERO_LOOK = Person(torch=True)
COMPANION_LOOK = Person(
    skin=(232, 190, 152),
    hair=(46, 32, 24),
    top=(222, 176, 44),
    legs=(48, 58, 86),
    shoes=(120, 40, 36),
    hair_style="braids",
    scale=0.62,
)

# Lengths in units of the figure's height.
HEAD, NECK, TORSO = 0.07, 0.035, 0.30
SHOULDER, HIP = 0.105, 0.065
UPPER, FORE, HAND = 0.165, 0.15, 0.03
THIGH, SHIN, FOOT = 0.235, 0.225, 0.065
ARM_W, LEG_W = 0.058, 0.074

# Angles in degrees: 0 points straight down, 90 to the right, -90 to the left. The lower
# bone of a limb is given relative to the upper one.
STAND: dict[str, float] = {
    "lean": 0, "head": 0, "nod": 0,
    "arm_l": -9, "fore_l": -5, "arm_r": 9, "fore_r": 5,
    "leg_l": -4, "shin_l": 0, "leg_r": 4, "shin_r": 0,
}  # fmt: skip
POSES: dict[str, dict[str, float]] = {
    "stand": {},
    "listen": {"head": 12, "arm_r": 105, "fore_r": 130},
    "look_down": {"head": 8, "nod": 0.5, "lean": 4, "arm_l": -14, "arm_r": 14},
    "walk": {},
    "sit": {"leg_l": 80, "shin_l": -82, "leg_r": 86, "shin_r": -88, "arm_l": 18, "fore_l": 40,
            "arm_r": 26, "fore_r": 44, "lean": -3},
    "hold_item": {"arm_l": -20, "fore_l": 105, "arm_r": 20, "fore_r": -105},
    "knock": {"arm_r": 75, "fore_r": 60},
    "point": {"arm_r": 100, "fore_r": 0},
    "arms_out": {"arm_l": -70, "fore_l": -10, "arm_r": 70, "fore_r": 10},
}  # fmt: skip


@dataclass
class Bones:
    """Where the joints of one figure are in the frame for one moment."""

    hip: Point
    neck: Point
    head: Point
    shoulder_l: Point
    shoulder_r: Point
    elbow_l: Point
    elbow_r: Point
    hand_l: Point
    hand_r: Point
    knee_l: Point
    knee_r: Point
    ankle_l: Point
    ankle_r: Point
    size: float
    facing: int


def _go(p: Point, angle: float, length: float) -> Point:
    a = math.radians(angle)
    return p[0] + math.sin(a) * length, p[1] + math.cos(a) * length


def bones(feet: Point, angles: Mapping[str, float], size: float, facing: int) -> Bones:
    """The joints for these angles, standing so that the lower foot is on the floor."""
    hip = (0.0, 0.0)
    knee_l = _go(hip, angles["leg_l"], THIGH * size)
    knee_r = _go(hip, angles["leg_r"], THIGH * size)
    ankle_l = _go(knee_l, angles["leg_l"] + angles["shin_l"], SHIN * size)
    ankle_r = _go(knee_r, angles["leg_r"] + angles["shin_r"], SHIN * size)
    drop = max(ankle_l[1], ankle_r[1]) + FOOT * 0.35 * size
    ox, oy = feet[0] - (ankle_l[0] + ankle_r[0]) / 2 * 0.0, feet[1] - drop

    def put(p: Point) -> Point:
        return p[0] + ox, p[1] + oy

    hip_p = put(hip)
    lean = math.radians(angles["lean"])
    neck = (hip_p[0] + math.sin(lean) * TORSO * size, hip_p[1] - math.cos(lean) * TORSO * size)
    across = (math.cos(lean) * SHOULDER * size, math.sin(lean) * SHOULDER * size)
    shoulder_l = (neck[0] - across[0], neck[1] - across[1] + 0.025 * size)
    shoulder_r = (neck[0] + across[0], neck[1] + across[1] + 0.025 * size)
    tilt = math.radians(angles["head"])
    reach = (NECK + HEAD) * size
    head = (
        neck[0] + math.sin(tilt) * reach * 0.4 + angles["nod"] * HEAD * size * 0.3 * facing,
        neck[1] - reach + angles["nod"] * HEAD * size,
    )
    elbow_l = _go(shoulder_l, angles["arm_l"], UPPER * size)
    elbow_r = _go(shoulder_r, angles["arm_r"], UPPER * size)
    hand_l = _go(elbow_l, angles["arm_l"] + angles["fore_l"], FORE * size)
    hand_r = _go(elbow_r, angles["arm_r"] + angles["fore_r"], FORE * size)
    return Bones(
        hip_p, neck, head, shoulder_l, shoulder_r, elbow_l, elbow_r, hand_l, hand_r,
        put(knee_l), put(knee_r), put(ankle_l), put(ankle_r), size, facing,
    )  # fmt: skip


def reach(shoulder: Point, target: Point, size: float, side: int) -> tuple[float, float]:
    """The angles of an upper arm and forearm that put the hand on `target`, the elbow
    bending downward; a target out of reach gets the arm stretched toward it."""
    a, b = UPPER * size, FORE * size
    dx, dy = target[0] - shoulder[0], target[1] - shoulder[1]
    d = min(max(math.hypot(dx, dy), abs(a - b) + 1), a + b - 1)
    toward = math.degrees(math.atan2(dx, dy))
    inner = math.degrees(math.acos((a * a + d * d - b * b) / (2 * a * d)))
    elbow = math.degrees(math.acos((a * a + b * b - d * d) / (2 * a * b)))
    bend = side if side else 1
    upper = toward + inner * bend
    return upper, -(180 - elbow) * bend


@dataclass(frozen=True)
class Cue:
    """From `start`, the figure takes `pose`; `target` is the point a reaching hand goes to."""

    start: float
    pose: str
    target: Point | None = None


@dataclass
class Actor:
    """One person on the stage: where they stand, how they look, and the poses they take."""

    look: Person
    feet: Point
    size: float
    cues: list[Cue]
    facing: int = 1
    drift: float = 0.0  # px the figure walks to the right over the beat
    appear: float = 0.0

    def angles(self, t: float, seconds: float) -> dict[str, float]:
        made = [self._pose(c) for c in self.cues]
        now = max((i for i, c in enumerate(self.cues) if c.start <= t), default=0)
        current = made[now]
        if now > 0:
            before = made[now - 1]
            p = ease((t - self.cues[now].start) / EASE)
            current = {k: before[k] + (current[k] - before[k]) * p for k in current}
        elif self.cues[0].pose.startswith("hand_on_") or self.cues[0].pose in ("point", "knock"):
            p = ease((t - 0.15) / (EASE * 1.6))
            current = {k: STAND[k] + (current[k] - STAND[k]) * p for k in current}
        walking = self.cues[now].pose == "walk"
        return _alive(current, t, walking)

    def where(self, t: float, seconds: float) -> Point:
        walking = any(c.pose == "walk" for c in self.cues)
        p = t / max(seconds, 0.1) if walking else 0.0
        bob = abs(math.sin(math.pi * t / WALK_STEP)) * 0.012 * self.size if walking else 0.0
        return self.feet[0] + self.drift * p, self.feet[1] - bob

    def _pose(self, cue: Cue) -> dict[str, float]:
        angles = {**STAND, **POSES.get(cue.pose, {})}
        if cue.target is not None:
            side = 1 if cue.target[0] >= self.feet[0] else -1
            standing = bones(self.feet, angles, self.size, self.facing)
            shoulder = standing.shoulder_r if side > 0 else standing.shoulder_l
            upper, lower = reach(shoulder, cue.target, self.size, -side)
            key = "r" if side > 0 else "l"
            angles[f"arm_{key}"], angles[f"fore_{key}"] = upper, lower
        return angles


WALK_STEP = 0.55  # seconds a step takes


def _alive(angles: dict[str, float], t: float, walking: bool) -> dict[str, float]:
    """Breath, a little sway, and the swing of the legs and arms when walking."""
    out = dict(angles)
    breath = math.sin(2 * math.pi * t / 3.4)
    out["lean"] += 0.6 * breath
    out["head"] += 1.2 * math.sin(2 * math.pi * t / 4.3 + 0.7)
    out["arm_l"] -= 1.4 * breath
    out["arm_r"] += 1.4 * breath
    if walking:
        phase = math.sin(math.pi * t / WALK_STEP)
        out["leg_l"] += 20 * phase
        out["leg_r"] -= 20 * phase
        out["shin_l"] -= 18 * max(0.0, -phase)
        out["shin_r"] -= 18 * max(0.0, phase)
        out["arm_l"] -= 16 * phase
        out["arm_r"] += 16 * phase
        out["fore_l"] -= 10
        out["fore_r"] += 10
    return out


def draw_person(c: skia.Canvas, b: Bones, look: Person, alpha: int = 255) -> None:
    """The figure from the back limbs to the head, each part with a light rim, like a cut-out
    lit from behind."""
    s = b.size
    near_arm, far_arm = ("r", "l") if b.facing > 0 else ("l", "r")
    far_leg, near_leg = far_arm, near_arm
    rim = stroke(RIM, 1, round(alpha * 0.55))

    def limb(a: Point, m: Point, z: Point, width: float, color: Color) -> None:
        rim.setStrokeWidth(width + 5)
        path = skia.Path()
        path.moveTo(*a)
        path.lineTo(*m)
        path.lineTo(*z)
        c.drawPath(path, rim)
        c.drawPath(path, stroke(color, width, alpha))

    def leg(side: str, color: Color) -> None:
        knee, ankle = getattr(b, f"knee_{side}"), getattr(b, f"ankle_{side}")
        hip = (b.hip[0] + (HIP * s if side == "r" else -HIP * s) * 0.6, b.hip[1])
        limb(hip, knee, ankle, LEG_W * s, color)
        toe = (ankle[0] + FOOT * s * b.facing * 0.8, ankle[1] + FOOT * s * 0.25)
        shoe = stroke(look.shoes, LEG_W * s * 0.72, alpha)
        c.drawLine(ankle[0], ankle[1] + LEG_W * s * 0.1, toe[0], toe[1], shoe)

    def arm(side: str, color: Color) -> None:
        shoulder = getattr(b, f"shoulder_{side}")
        elbow, hand = getattr(b, f"elbow_{side}"), getattr(b, f"hand_{side}")
        limb(shoulder, elbow, hand, ARM_W * s, color)
        c.drawCircle(hand[0], hand[1], HAND * s, fill(look.skin, alpha))

    c.drawOval(
        skia.Rect.MakeLTRB(
            b.hip[0] - 0.2 * s, max(b.ankle_l[1], b.ankle_r[1]) + 0.012 * s,
            b.hip[0] + 0.2 * s, max(b.ankle_l[1], b.ankle_r[1]) + 0.05 * s,
        ),
        glow((0, 0, 0), round(alpha * 0.45), 0.02 * s),
    )  # fmt: skip
    leg(far_leg, shade(look.legs, 0.8))
    arm(far_arm, shade(look.top, 0.78))
    leg(near_leg, look.legs)

    # The torso: wider at the shoulders, a collar, a belt and a seam down the middle.
    torso = skia.Path()
    hl = (b.hip[0] - HIP * s * 1.15, b.hip[1] + 0.02 * s)
    hr = (b.hip[0] + HIP * s * 1.15, b.hip[1] + 0.02 * s)
    torso.moveTo(*hl)
    torso.lineTo(b.shoulder_l[0] - 0.012 * s, b.shoulder_l[1] + 0.01 * s)
    torso.quadTo(b.neck[0], b.neck[1] - 0.012 * s, b.shoulder_r[0] + 0.012 * s, b.shoulder_r[1] + 0.01 * s)
    torso.lineTo(*hr)
    torso.close()
    c.drawPath(torso, stroke(RIM, 5, round(alpha * 0.55)))
    c.drawPath(torso, fill(look.top, alpha))
    lit = skia.Path()
    lit.moveTo(b.neck[0] + 0.02 * s * b.facing, b.neck[1] + 0.01 * s)
    lit.lineTo((hr if b.facing > 0 else hl)[0] - 0.025 * s * b.facing, b.hip[1] + 0.02 * s)
    lit.lineTo(*(hr if b.facing > 0 else hl))
    lit.lineTo(*(b.shoulder_r if b.facing > 0 else b.shoulder_l))
    lit.close()
    c.drawPath(lit, fill(shade(look.top, 1.12), alpha))
    c.drawLine(b.neck[0], b.neck[1] + 0.03 * s, b.hip[0], b.hip[1], stroke(shade(look.top, 0.7), 0.006 * s, alpha))
    collar = skia.Path()
    collar.moveTo(b.neck[0] - 0.045 * s, b.neck[1] + 0.005 * s)
    collar.lineTo(b.neck[0], b.neck[1] + 0.055 * s)
    collar.lineTo(b.neck[0] + 0.045 * s, b.neck[1] + 0.005 * s)
    c.drawPath(collar, stroke(shade(look.top, 0.62), 0.012 * s, alpha))
    c.drawLine(hl[0] + 0.005 * s, b.hip[1] - 0.005 * s, hr[0] - 0.005 * s, b.hip[1] - 0.005 * s,
               stroke(shade(look.legs, 0.7), 0.028 * s, alpha))  # fmt: skip
    if look.torch:
        tx, ty = b.neck[0] + 0.03 * s * b.facing, b.neck[1] + 0.11 * s
        c.drawLine(b.neck[0] - 0.02 * s, b.neck[1] + 0.01 * s, tx, ty, stroke((20, 20, 24), 2.5, alpha))
        c.drawRoundRect(skia.Rect.MakeXYWH(tx - 0.012 * s, ty, 0.024 * s, 0.05 * s), 3, 3,
                        fill((60, 62, 70), alpha))  # fmt: skip
    arm(near_arm, look.top)

    # Neck and head: skin, a cap of hair, an ear on the far side.
    c.drawLine(b.neck[0], b.neck[1] + 0.01 * s, b.head[0], b.head[1], stroke(shade(look.skin, 0.85), 0.04 * s, alpha))
    hx, hy, r = b.head[0], b.head[1], HEAD * s
    c.drawCircle(hx, hy, r + 2.5, fill(RIM, round(alpha * 0.55)))
    ear = (hx - r * 0.92 * b.facing, hy + r * 0.12)
    c.drawOval(skia.Rect.MakeXYWH(ear[0] - r * 0.2, ear[1] - r * 0.26, r * 0.4, r * 0.52), fill(shade(look.skin, 0.9), alpha))
    c.drawCircle(hx, hy, r, fill(look.skin, alpha))
    c.drawCircle(hx + r * 0.25 * b.facing, hy + r * 0.05, r * 0.72, fill(shade(look.skin, 1.06), round(alpha * 0.5)))
    cap = skia.Path()
    cap.addArc(skia.Rect.MakeLTRB(hx - r * 1.04, hy - r * 1.08, hx + r * 1.04, hy + r * 1.0), 180, 180)
    cap.lineTo(hx + r * 1.04 * b.facing * 0.3, hy - r * 0.32)
    cap.close()
    c.drawPath(cap, fill(look.hair, alpha))
    c.drawCircle(hx - r * 0.55 * b.facing, hy - r * 0.15, r * 0.6, fill(look.hair, alpha))
    if look.hair_style == "braids":
        for side in (-1, 1):
            top = (hx + side * r * 0.85, hy + r * 0.2)
            c.drawLine(top[0], top[1], top[0] + side * r * 0.15, top[1] + r * 1.5, stroke(look.hair, r * 0.32, alpha))
            c.drawCircle(top[0] + side * r * 0.15, top[1] + r * 1.55, r * 0.14, fill((200, 60, 50), alpha))
    c.drawOval(skia.Rect.MakeXYWH(ear[0] - r * 0.12, ear[1] - r * 0.16, r * 0.24, r * 0.32), fill(shade(look.skin, 0.8), alpha))


# --- places ------------------------------------------------------------------------------


def at(anchor: Anchor) -> Point:
    return anchor.x * W, anchor.y * H


@dataclass(frozen=True)
class Change:
    """A prop takes its `stage`, counted from 0, from `start` on."""

    start: float
    prop: str
    stage: int


@dataclass
class Stage:
    """Everything that moves in a beat, drawn for any moment of it."""

    location: Location
    actors: list[Actor]
    changes: list[Change] = field(default_factory=list)
    stages: Mapping[str, int] = field(default_factory=dict)  # stages each prop has
    seconds: float = 6.0
    seed: int = 0
    dark: bool = False
    _back: skia.Image | None = None

    @property
    def floor(self) -> float:
        return at(self.location.anchors["hero"])[1]

    def prop(self, name: str, t: float) -> float:
        """The stage of a prop at `t`, easing from one stage to the next."""
        moves = [ch for ch in self.changes if ch.prop == name]
        level = 0.0
        for ch in moves:
            level += (ch.stage - level) * ease((t - ch.start) / 1.2)
        return level

    def frame(self, t: float) -> Image.Image:
        surface = skia.Surface.MakeRaster(
            skia.ImageInfo.Make(W, H, skia.ColorType.kRGBA_8888_ColorType, skia.AlphaType.kPremul_AlphaType)
        )
        c = surface.getCanvas()
        if self._back is None:
            self._back = _picture(lambda back: layout(back, self.location, self.seed))
        hero_at = at(self.location.anchors["hero"])
        zoom = 1.0 + 0.025 * ease(t / max(self.seconds, 0.1))
        c.save()
        c.translate(hero_at[0], hero_at[1] - 200)
        c.scale(zoom, zoom)
        c.translate(-hero_at[0], -(hero_at[1] - 200))
        c.drawImage(self._back, 0, 0, skia.SamplingOptions(skia.FilterMode.kLinear))
        objects(c, self, t, behind=True)
        for actor in sorted(self.actors, key=lambda a: a.feet[1]):
            if t < actor.appear:
                continue
            alpha = round(255 * ease((t - actor.appear) / 0.4)) if actor.appear else 255
            b = bones(actor.where(t, self.seconds), actor.angles(t, self.seconds), actor.size, actor.facing)
            draw_person(c, b, actor.look, alpha)
        objects(c, self, t, behind=False)
        if self.dark:
            _darkness(c, self, t)
        c.restore()
        _vignette(c)
        raw = surface.makeImageSnapshot().tobytes()
        return Image.frombuffer("RGBA", (W, H), raw, "raw", "RGBA", 0, 1)


def _picture(draw: Callable[[skia.Canvas], None]) -> skia.Image:
    surface = skia.Surface.MakeRaster(
        skia.ImageInfo.Make(W, H, skia.ColorType.kRGBA_8888_ColorType, skia.AlphaType.kPremul_AlphaType)
    )
    draw(surface.getCanvas())
    return surface.makeImageSnapshot()


def layout(c: skia.Canvas, location: Location, seed: int) -> None:
    """The parts of the place that never move."""
    anchors = location.anchors
    floor = at(anchors["hero"])[1]
    if any(name.startswith("floor_") for name in anchors):
        _section(c, location, seed)
        return
    c.drawRect(skia.Rect(0, 0, W, floor), vertical(0, floor, [NIGHT, WALL, WALL_LOW]))
    for x in range(-60, W, 270):
        c.drawLine(x, 0, x, floor - 18, stroke(shade(WALL, 0.88), 3))
    c.drawRect(skia.Rect(0, floor - 18, W, floor + 4), fill(TRIM))
    c.drawRect(skia.Rect(0, floor, W, H), vertical(floor, H, [FLOOR, FLOOR_FAR]))
    for i in range(1, 7):
        y = floor + i * i * 9
        c.drawLine(0, y, W, y, stroke(shade(FLOOR, 1.12), 2, 90))
    if "window" in anchors:
        x, y = at(anchors["window"])
        beam = skia.Path()
        beam.moveTo(x - 150, y - 150)
        beam.lineTo(x + 150, y - 150)
        beam.lineTo(x + 40, floor + 140)
        beam.lineTo(x - 470, floor + 140)
        beam.close()
        c.drawPath(beam, glow(LIGHT, 26, 40))
    else:
        x = at(anchors["hero"])[0] + 60
        beam = skia.Path()
        beam.moveTo(x - 70, 0)
        beam.lineTo(x + 70, 0)
        beam.lineTo(x + 330, floor + 60)
        beam.lineTo(x - 330, floor + 60)
        beam.close()
        c.drawPath(beam, glow(LIGHT, 22, 50))
    for name, anchor in anchors.items():
        _fixture(c, name, at(anchor), floor, anchors)


def _fixture(c: skia.Canvas, name: str, xy: Point, floor: float, anchors: Mapping[str, Anchor]) -> None:
    x, y = xy
    if name in ("door", "roof_door"):
        _door(c, x, floor, lock=name == "roof_door")
    elif name == "window":
        _window(c, x, y, wide=False)
    elif name == "bed":
        _bed(c, x, floor)
    elif name == "table":
        _bench(c, x, y, floor)
    elif name in ("pipe", "riser"):
        c.drawRect(skia.Rect(x - 18, 0, x + 18, floor + 6), fill(STEEL))
        c.drawRect(skia.Rect(x - 4, 0, x + 8, floor + 6), fill(STEEL_LIT, 150))
    elif name == "railing":
        _stairs_up(c, x, y, floor)
    elif name == "stairs_down":
        _stairs_down(c, x, floor)


def _door(c: skia.Canvas, x: float, floor: float, *, lock: bool) -> None:
    w, h = 250, 520
    left, top = x - w / 2, floor - h
    c.drawRect(skia.Rect(left - 18, top - 18, left + w + 18, floor), fill(shade(TRIM, 0.9)))
    c.drawRect(skia.Rect(left, top, left + w, floor), vertical(top, floor, [(64, 52, 44), (48, 39, 33)]))
    for py, ph in ((top + 40, 190), (top + 270, 210)):
        c.drawRoundRect(skia.Rect.MakeXYWH(left + 34, py, w - 68, ph), 6, 6, stroke((36, 29, 25), 5))
    c.drawRect(skia.Rect(left + w - 16, top, left + w, floor), fill((34, 28, 24), 160))
    c.drawCircle(left + w - 44, top + h * 0.52, 11, fill(STEEL_LIT))
    if lock:
        lx, ly = left + w - 44, top + h * 0.52 + 46
        c.drawRoundRect(skia.Rect.MakeXYWH(lx - 22, ly, 44, 40), 6, 6, fill((168, 140, 60)))
        c.drawArc(skia.Rect.MakeXYWH(lx - 15, ly - 26, 30, 44), 180, 180, False, stroke((150, 150, 158), 7))


def _window(c: skia.Canvas, x: float, y: float, *, wide: bool) -> None:
    w, h = (440, 400) if wide else (320, 380)
    r = skia.Rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    c.drawRect(r.makeOutset(16, 16), fill(TRIM))
    c.drawRect(r, vertical(r.top(), r.bottom(), [(18, 30, 52), GLASS, (40, 72, 98)]))
    rnd = random.Random(int(x * 7 + y))
    for _ in range(14):
        sx, sy = rnd.uniform(r.left(), r.right()), rnd.uniform(r.top(), r.top() + h * 0.45)
        c.drawCircle(sx, sy, rnd.uniform(1.2, 2.6), fill((220, 228, 240), rnd.randint(90, 200)))
    sky = r.bottom() - h * 0.42
    city = skia.Path()
    city.moveTo(r.left(), r.bottom())
    bx = r.left()
    while bx < r.right():
        bw = rnd.uniform(26, 60)
        bh = rnd.uniform(30, h * 0.36)
        city.lineTo(bx, sky + h * 0.36 - bh)
        city.lineTo(min(bx + bw, r.right()), sky + h * 0.36 - bh)
        bx += bw
    city.lineTo(r.right(), r.bottom())
    city.close()
    c.drawPath(city, fill((16, 24, 38)))
    water_top = r.bottom() - h * 0.16
    c.drawRect(skia.Rect(r.left(), water_top, r.right(), r.bottom()), fill(shade(WATER, 0.7), 220))
    for k in range(3):
        c.drawLine(r.left() + 20 + k * 60, water_top + 10 + k * 12, r.left() + 90 + k * 70, water_top + 10 + k * 12,
                   stroke(LIGHT, 2, 110))  # fmt: skip
    c.drawLine(x, r.top(), x, r.bottom(), stroke(TRIM, 12))
    c.drawLine(r.left(), y - h * 0.1, r.right(), y - h * 0.1, stroke(TRIM, 12))
    c.drawRect(skia.Rect(r.left() - 30, r.bottom() + 16, r.right() + 30, r.bottom() + 34), fill(shade(TRIM, 1.15)))


def _bed(c: skia.Canvas, x: float, floor: float) -> None:
    left, right = x - 230, x + 190
    c.drawRoundRect(skia.Rect(left - 10, floor - 330, left + 26, floor), 8, 8, fill(WOOD_DARK))
    c.drawRect(skia.Rect(left, floor - 190, right, floor - 120), fill(WOOD))
    c.drawRoundRect(skia.Rect(left + 10, floor - 250, right - 6, floor - 186), 22, 22, fill((178, 186, 198)))
    c.drawRoundRect(skia.Rect(left + 24, floor - 300, left + 150, floor - 238), 26, 26, fill((214, 220, 228)))
    blanket = skia.Path()
    blanket.moveTo(left + 120, floor - 252)
    blanket.cubicTo(left + 220, floor - 270, right - 60, floor - 262, right + 4, floor - 240)
    blanket.lineTo(right + 18, floor - 150)
    blanket.cubicTo(right - 80, floor - 160, left + 200, floor - 150, left + 120, floor - 176)
    blanket.close()
    c.drawPath(blanket, fill((72, 92, 128)))
    for lx in (left + 6, right - 22):
        c.drawRect(skia.Rect(lx, floor - 120, lx + 16, floor), fill(WOOD_DARK))


def _bench(c: skia.Canvas, x: float, y: float, floor: float) -> None:
    top = floor - 230
    c.drawRect(skia.Rect(x - 190, top, x + 190, top + 26), fill(WOOD))
    c.drawRect(skia.Rect(x - 190, top + 26, x + 190, top + 34), fill(WOOD_DARK))
    for lx in (x - 176, x + 160):
        c.drawRect(skia.Rect(lx, top + 34, lx + 18, floor), fill(WOOD_DARK))
    c.drawRect(skia.Rect(x - 168, top + 120, x + 168, top + 134), fill(WOOD_DARK))
    c.drawRoundRect(skia.Rect.MakeXYWH(x - 120, top - 60, 110, 60), 6, 6, fill((96, 104, 118)))
    c.drawLine(x + 30, top - 8, x + 120, top - 50, stroke((150, 120, 80), 10))
    c.drawRoundRect(skia.Rect.MakeXYWH(x + 104, top - 70, 40, 26), 4, 4, fill(STEEL))


def _stairs_up(c: skia.Canvas, x: float, y: float, floor: float) -> None:
    """A flight going up to the right from the landing, with a railing along it."""
    start, steps, rise, run = x - 230, 9, 50, 56
    for i in range(steps):
        sx = start + i * run
        top = floor - (i + 1) * rise
        c.drawRect(skia.Rect(sx, top, sx + run + 600, top + rise), fill(shade(WALL_LOW, 0.92 - i * 0.02)))
        c.drawLine(sx, top, sx + run, top, stroke(shade(LINE, 1.25), 4))
        c.drawLine(sx, top, sx, top + rise, stroke(shade(LINE, 0.9), 3))
    hand = 190
    c.drawLine(start - 40, floor - hand, start + steps * run, floor - steps * rise - hand, stroke(STEEL, 12))
    for i in range(0, steps + 1, 2):
        bx = start + i * run - 10
        c.drawLine(bx, floor - i * rise - hand + i * 0, bx, floor - i * rise, stroke(shade(STEEL, 0.75), 6))


def _stairs_down(c: skia.Canvas, x: float, floor: float) -> None:
    for i in range(6):
        top = floor + i * 30
        c.drawRect(skia.Rect(x - 120 + i * 52, top, W, top + 30), fill(shade(FLOOR, 1.15 - i * 0.1)))
        c.drawLine(x - 120 + i * 52, top, W, top, stroke(LINE, 3))
    c.drawRect(skia.Rect(x - 120 + 6 * 52, floor + 175, W, floor + 260), fill(shade(WATER, 0.55), 230))


def _section(c: skia.Canvas, location: Location, seed: int) -> None:
    """A cut through a building: storeys stacked, the stairs inside, the sky around it."""
    anchors = location.anchors
    floors = sorted(
        (int(name.removeprefix("floor_")), at(a)[1])
        for name, a in anchors.items()
        if name.startswith("floor_") and name.removeprefix("floor_").isdigit()
    )
    (n0, y0), (n1, y1) = floors[0], floors[-1]
    storey = (y0 - y1) / max(n1 - n0, 1)
    ground = y0 + (n0 - 1) * storey
    roof = y1 - storey * 0.15
    c.drawRect(skia.Rect(0, 0, W, H), vertical(0, H, [NIGHT, (20, 27, 40), (12, 16, 24)]))
    rnd = random.Random(seed)
    for _ in range(50):
        c.drawCircle(rnd.uniform(0, W), rnd.uniform(0, roof - 10), rnd.uniform(1, 2.4), fill((210, 220, 240), rnd.randint(60, 170)))
    left, right = 150, 930
    c.drawRect(skia.Rect(left, roof, right, ground), fill((30, 38, 54)))
    for k in range(1, n1 + 1):
        fy = ground - (k - 1) * storey
        c.drawRect(skia.Rect(left, fy - 10, right, fy + 4), fill((58, 70, 92)))
        for wx in (left + 70, left + 240):
            c.drawRect(skia.Rect.MakeXYWH(wx, fy - storey * 0.72, 90, storey * 0.42), fill((24, 32, 48)))
        sx = right - 230
        step = skia.Path()
        step.moveTo(sx, fy)
        for i in range(6):
            step.lineTo(sx + i * 30, fy - i * storey / 6)
            step.lineTo(sx + (i + 1) * 30, fy - i * storey / 6)
        c.drawPath(step, stroke((70, 82, 106), 4))
    c.drawRect(skia.Rect(left - 14, roof - 20, right + 14, roof), fill((58, 70, 92)))
    c.drawRect(skia.Rect(left - 14, roof, left, ground), fill((58, 70, 92)))
    c.drawRect(skia.Rect(right, roof, right + 14, ground), fill((58, 70, 92)))
    c.drawRect(skia.Rect(0, ground, W, H), fill((12, 16, 24)))


def _section_scale(location: Location) -> float | None:
    floors = sorted(at(a)[1] for name, a in location.anchors.items() if name.startswith("floor_"))
    if len(floors) < 2:
        return None
    names = [int(n.removeprefix("floor_")) for n in location.anchors if n.startswith("floor_") and n[6:].isdigit()]
    storey = (floors[-1] - floors[0]) / max(max(names) - min(names), 1)
    return storey * 0.78


def objects(c: skia.Canvas, stage: Stage, t: float, *, behind: bool) -> None:
    """The props that change: the wardrobe before the people, the water over them."""
    anchors = stage.location.anchors
    floor = stage.floor
    if behind and "shelf" in anchors:
        x, y = at(anchors["shelf"])
        p = stage.prop("shelf", t)
        angle = 52 * (1 - p)
        dx = 230 * p
        c.save()
        c.translate(x + 60 + dx, floor - 20 - 150 * (1 - p))
        c.rotate(angle)
        c.drawRoundRect(skia.Rect(-110, -300, 110, 40), 6, 6, fill(WOOD_DARK))
        c.drawRect(skia.Rect(-96, -286, -4, 26), fill(WOOD))
        c.drawRect(skia.Rect(4, -286, 96, 26), fill(WOOD))
        c.drawCircle(-18, -130, 6, fill(STEEL_LIT))
        c.drawCircle(18, -130, 6, fill(STEEL_LIT))
        c.restore()
    if not behind and "water" in anchors:
        _water(c, stage, t)


WATER_LEVELS = (0.07, 0.27, 0.48)  # ankle, knee, waist, in units of the hero's height


def _water(c: skia.Canvas, stage: Stage, t: float) -> None:
    anchors = stage.location.anchors
    if any(n.startswith("floor_") for n in anchors):
        level = at(anchors["water"])[1]
        top_left = 0.0
    else:
        hero_size = next((a.size for a in stage.actors if a.look.torch), HERO)
        p = stage.prop("water", t)
        k = min(int(p), len(WATER_LEVELS) - 2)
        f = p - k
        depth = WATER_LEVELS[k] + (WATER_LEVELS[k + 1] - WATER_LEVELS[k]) * f
        start = WATER_LEVELS[1] if not any(ch.prop == "water" for ch in stage.changes) else depth
        level = stage.floor - start * hero_size
        top_left = 0.0
    surface = skia.Path()
    surface.moveTo(top_left, H)
    surface.lineTo(top_left, level)
    for i in range(0, W + 41, 40):
        surface.lineTo(i, level + 5 * math.sin(i / 70 + t * 2.1) + 3 * math.sin(i / 23 - t * 3.3))
    surface.lineTo(W, H)
    surface.close()
    c.drawPath(surface, vertical(level, H, [shade(WATER, 0.9), shade(WATER, 0.3)], [120, 215]))
    for i in range(0, W, 40):
        y = level + 5 * math.sin(i / 70 + t * 2.1) + 3 * math.sin(i / 23 - t * 3.3)
        c.drawLine(i, y, i + 24, y, stroke(LIGHT, 2.5, 120))
    for actor in stage.actors:
        x = actor.where(t, stage.seconds)[0]
        ring = (t * 0.8 + x / 300) % 1.0
        c.drawOval(skia.Rect.MakeXYWH(x - 40 - 60 * ring, level - 6 - 6 * ring, 80 + 120 * ring, 12 + 12 * ring),
                   stroke(LIGHT, 2, round(140 * (1 - ring))))  # fmt: skip


def _darkness(c: skia.Canvas, stage: Stage, t: float) -> None:
    """The dark floor: everything black but a torch cone from the hero that flickers."""
    hero = next((a for a in stage.actors if a.look.torch), stage.actors[0])
    x, y = hero.where(t, stage.seconds)
    flick = 0.55 + 0.45 * max(0.0, math.sin(t * 9.1) * math.sin(t * 3.7 + 1.3))
    cone = skia.Path()
    cone.moveTo(x + 10 * hero.facing, y - hero.size * 0.66)
    cone.lineTo(x + 760 * hero.facing, y - hero.size * 1.35)
    cone.lineTo(x + 760 * hero.facing, y + 260)
    cone.close()
    dark = skia.Paint(AntiAlias=True, Color=rgb((4, 6, 10), 175))
    c.save()
    c.clipPath(cone, skia.ClipOp.kDifference, True)
    c.drawRect(skia.Rect(-200, -200, W + 200, H + 200), dark)
    c.restore()
    c.drawPath(cone, glow(WARM, round(40 * flick), 30))


def _vignette(c: skia.Canvas) -> None:
    shader = skia.GradientShader.MakeRadial(
        skia.Point(W / 2, H * 0.4), H * 0.8, [rgb((0, 0, 0), 0), rgb((0, 0, 0), 120)]
    )
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=shader))


@cache
def _darkish(key: str) -> bool:
    return "dark" in key


def build(
    key: str,
    location: Location,
    *,
    pose: str,
    cues: Sequence[tuple[float, str]],
    changes: Sequence[Change],
    stages: Mapping[str, int],
    seconds: float,
    companion: bool,
) -> Stage:
    """The stage of one beat: the hero on his anchor taking the beat's pose and the poses
    its reveals call for, the companion on hers when the place has one."""
    anchors = location.anchors
    feet = at(anchors["hero"])
    size = _section_scale(location) or HERO

    def cue(start: float, name: str) -> Cue:
        target = None
        if name.startswith("hand_on_") and (a := anchors.get(name.removeprefix("hand_on_"))):
            target = at(a)
            if name.removeprefix("hand_on_") in ("railing", "window", "shelf"):
                target = (target[0], max(target[1], feet[1] - size * 0.62))
        return Cue(start, name, target)

    first = cue(0.0, pose)
    later = [cue(s, n) for s, n in cues]
    targets = [c.target for c in (first, *later) if c.target is not None]
    facing = 1 if (targets[0][0] if targets else W / 2) >= feet[0] else -1
    drift = 120.0 if pose == "walk" else 0.0
    actors = [Actor(HERO_LOOK, feet, size, [first, *later], facing=facing, drift=drift)]
    if companion and "companion" in anchors:
        where = at(anchors["companion"])
        actors.append(
            Actor(
                COMPANION_LOOK, where, size * COMPANION_LOOK.scale, [Cue(0.0, "stand")],
                facing=1 if where[0] < feet[0] else -1,
            )
        )  # fmt: skip
    return Stage(
        location, actors, list(changes), stages, seconds=seconds,
        seed=sum(map(ord, key)), dark=_darkish(key),
    )  # fmt: skip


__all__ = ["Change", "Stage", "build", "replace"]
