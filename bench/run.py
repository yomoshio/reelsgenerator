"""Runs a list of video tests through ComfyUI and writes down what each one cost.

    python3 bench/run.py bench/tests/smoke.json --comfy-dir /root/ComfyUI --out bench/out

A test names a workflow from bench/workflows and the values to put into it:

    {"name": "ltx-t2v-rain", "workflow": "video_ltx2_5_t2v",
     "set": [["Prompt", "value", "Rain on a window..."], ["Duration", "value", 6]],
     "images": ["out/refs/white.png"]}

The first word of a `set` is a node's title or its class; `LoadImage#2` is the second of
its kind. `images` fill the LoadImage nodes in order; `refs` are the reference pictures of
MiniMax H3, as many as the test names, <Picture 1> first. Paths are counted from this folder.
Every run adds a line to results.jsonl
in the output folder: seconds, the most video memory in use, the file. A test whose file is
already there is skipped, so a list can be rerun after a failure. Runs on the server, with
nothing but the standard library."""

import argparse
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


class Memory(threading.Thread):
    """The most video memory in use while it runs, in GB."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.most = 0.0
        self.done = threading.Event()

    def run(self) -> None:
        ask = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
        while not self.done.wait(1.0):
            try:
                used = subprocess.run(
                    ask, capture_output=True, text=True, timeout=10, check=True
                ).stdout
                self.most = max(self.most, max(float(n) for n in used.split()) / 1024)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass


def call(url: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return json.loads(reply.read() or b"null")


def found(graph: dict[str, Any], name: str) -> dict[str, Any]:
    """The node with this title or class; `Name#2` is the second such in the graph's order."""
    name, _, nth = name.partition("#")
    nodes = [
        node for node in graph.values()
        if name in (node.get("_meta", {}).get("title"), node["class_type"])
    ]  # fmt: skip
    if len(nodes) < int(nth or 1):
        raise KeyError(f"no node {name!r} number {nth or 1}")
    return nodes[int(nth or 1) - 1]


def shown(graph: dict[str, Any], pictures: list[str]) -> None:
    """Gives MiniMax H3 these reference pictures in place of the template's own."""
    node = found(graph, "MiniMaxH3ReferenceToVideo")
    for key in [k for k in node["inputs"] if k.startswith("ref_images.")]:
        graph.pop(node["inputs"].pop(key)[0], None)
    for n, name in enumerate(pictures):
        graph[f"ref{n}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        node["inputs"][f"ref_images.ref_image_{n}"] = [f"ref{n}", 0]


def filled(test: dict[str, Any], workflows: Path, inputs: Path) -> dict[str, Any]:
    graph: dict[str, Any] = json.loads((workflows / f"{test['workflow']}.json").read_text())
    for image in [*test.get("images", []), *test.get("refs", [])]:
        shutil.copy(HERE / image, inputs / Path(image).name)
    for n, image in enumerate(test.get("images", []), 1):
        found(graph, f"LoadImage#{n}")["inputs"]["image"] = Path(image).name
    if "refs" in test:
        shown(graph, [Path(image).name for image in test["refs"]])
    for name, field, value in test.get("set", []):
        node = found(graph, name)
        if field not in node["inputs"]:
            raise KeyError(f"{name!r} has no input {field!r}: {sorted(node['inputs'])}")
        node["inputs"][field] = value
    seed = test.get("seed", 1)
    for node in graph.values():
        if node["class_type"] == "RandomNoise":
            node["inputs"]["noise_seed"] = seed
        if node["class_type"] in ("SaveVideo", "SaveImage"):
            node["inputs"]["filename_prefix"] = f"bench/{test['name']}"
    return graph


def files(history: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for node in history.get("outputs", {}).values():
        for items in node.values():
            if isinstance(items, list):
                out += [item for item in items if isinstance(item, dict) and "filename" in item]
    return out


def run(test: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    line: dict[str, Any] = {"name": test["name"], "workflow": test["workflow"]}
    watch = Memory()
    started = time.time()
    try:
        graph = filled(test, args.workflows, args.comfy_dir / "input")
        watch.start()
        queued = call(f"{args.comfy}/prompt", {"prompt": graph})["prompt_id"]
        while not (history := call(f"{args.comfy}/history/{queued}").get(queued)):
            time.sleep(2)
        status = history.get("status", {})
        if status.get("status_str") != "success":
            errors = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
            told = [f"{e.get('node_type')}: {e.get('exception_message')}" for e in errors]
            raise RuntimeError("; ".join(told) or str(status))
        made = files(history)
        if not made:
            raise RuntimeError("the run left no file")
        first = made[0]
        source = args.comfy_dir / "output" / first.get("subfolder", "") / first["filename"]
        target = args.out / f"{test['name']}{source.suffix}"
        shutil.copy(source, target)
        line["file"] = target.name
    except urllib.error.HTTPError as exc:
        line["error"] = exc.read().decode(errors="replace")[:1500]
    except (KeyError, RuntimeError, OSError) as exc:
        line["error"] = str(exc)[:1500]
    watch.done.set()
    line["seconds"] = round(time.time() - started, 1)
    line["peak_gb"] = round(watch.most, 1)
    return line


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("tests", type=Path)
    parser.add_argument("--comfy", default="http://127.0.0.1:8188")
    parser.add_argument("--comfy-dir", type=Path, default=Path("/root/ComfyUI"))
    parser.add_argument("--workflows", type=Path, default=HERE / "workflows")
    parser.add_argument("--out", type=Path, default=HERE / "out")
    parser.add_argument("--only", nargs="*", help="run only the tests with these names")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for test in json.loads(args.tests.read_text(encoding="utf-8")):
        if args.only and test["name"] not in args.only:
            continue
        if list(args.out.glob(f"{test['name']}.*")):
            continue
        line = run(test, args)
        with (args.out / "results.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(json.dumps(line, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
