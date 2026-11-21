"""What the runtime can put on stage, as the director and the coder read it: kinds of
places, things, devices that explain what the eye cannot see, and poses of the rig. The
runtime fills it from its own code and the thing library; the defaults here are what the
runtime draws by itself."""

from dataclasses import dataclass, field

PLACES = {
    "room": "a room seen from the side: a wall, a floor, a skirting line, one light",
    "stairwell": "a staircase with a flight up, a railing and a landing",
    "section": "a cut through a building: floors stacked, the stairs inside",
    "street": "a street or yard at ground level: a building front, pavement, sky",
    "shop": "a small shop inside: a wall of shelves, a floor, a counter by the door",
    "outdoors": "open ground: sky, a horizon, the earth",
    "custom": "a place the scene draws itself with the canvas",
}
THINGS = {
    "door": "a door in the wall; parts: handle",
    "window": "a window in the wall; parts: glass",
    "bed": "a bed; parts: seat",
    "bench": "a bench; parts: seat",
    "chair": "a chair; parts: seat",
    "table": "a table or workbench; parts: top",
    "fireplace": "a hearth that burns: state 0 cold, 1 embers, 2 burning, 3 roaring; parts: hearth",
    "counter": "a shop counter; parts: top",
    "shelf": "shelves with goods; parts: top",
    "wardrobe": "a wardrobe; parts: door",
    "atm": "a cash machine; parts: screen, slot",
    "lamp": "a lamp on the ceiling; parts: bulb",
    "railing": "a stair railing",
    "pipe": "a riser pipe from floor to ceiling",
    "radiator": "a radiator under the window",
    "water": "water that fills the room from the floor up; stages rise it",
}
DEVICES = {
    "section": "a cut through the building that shows which floor is which",
    "lens": "a circle that magnifies a detail: a screen, a note, a face",
    "ripples": "rings that show sound travelling from a point or along a pipe",
    "dashed": "a dashed line: who sees whom, where a thing will go",
    "counter": "a number that counts up or down on screen: floors, minutes, money",
    "route": "a path drawn step by step on the scene",
    "split": "two places side by side at once",
}
POSES = {
    "stand": "stands still",
    "walk": "walks; give it a target",
    "sit": "sits on a thing with a seat",
    "reach": "reaches a hand to a thing or a part",
    "point": "points at a thing",
    "knock": "knocks on a door or a pipe",
    "listen": "a hand at the ear, head tilted",
    "look_down": "looks down",
    "hold": "holds something in both hands in front",
    "arms_out": "arms out, startled or blocking",
}


@dataclass(frozen=True)
class Catalog:
    places: dict[str, str] = field(default_factory=lambda: dict(PLACES))
    things: dict[str, str] = field(default_factory=lambda: dict(THINGS))
    devices: dict[str, str] = field(default_factory=lambda: dict(DEVICES))
    poses: dict[str, str] = field(default_factory=lambda: dict(POSES))

    def text(self) -> str:
        def listed(title: str, items: dict[str, str]) -> str:
            return f"{title}:\n" + "\n".join(f"  - `{k}`: {v}" for k, v in items.items())

        return "\n".join(
            [
                listed("Kinds of places", self.places),
                listed("Things", self.things),
                listed("Devices", self.devices),
                listed("Poses", self.poses),
            ]
        )
