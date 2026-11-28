"""Turns ComfyUI's workflow templates into the form its API runs.

A template is a picture of a graph, with groups of nodes folded into one; the server takes a
flat list of nodes. Only ComfyUI's own page knows how to unfold one into the other, so this
opens the page in Firefox without a window, loads each template and writes what the page
would queue. ComfyUI may run on the processor for this (`main.py --cpu`): nothing is computed.

    python bench/export.py --comfy http://127.0.0.1:8188 templates/*.json --out bench/workflows

Needs `pip install selenium`, Firefox and geckodriver (`--driver` if it is not on the path;
with the Ubuntu snap it is /snap/bin/geckodriver)."""

import argparse
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

READY = "return !!((window.app ?? window.comfyAPI?.app?.app)?.graph)"
UNFOLD = """
const done = arguments[arguments.length - 1];
const app = window.app ?? window.comfyAPI.app.app;
app.loadGraphData(arguments[0]).then(() => app.graphToPrompt())
    .then((prompt) => done(prompt.output)).catch((error) => done({error: String(error)}));
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("templates", type=Path, nargs="+")
    parser.add_argument("--comfy", default="http://127.0.0.1:8188")
    parser.add_argument("--driver", default="/snap/bin/geckodriver")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.add_argument("-headless")
    page = webdriver.Firefox(options=options, service=Service(args.driver))
    page.set_script_timeout(120)
    page.get(args.comfy)
    until = time.time() + 120
    while not page.execute_script(READY):
        if time.time() > until:
            raise SystemExit(f"the page at {args.comfy} never loaded its graph")
        time.sleep(2)
    for template in args.templates:
        flat = page.execute_async_script(UNFOLD, json.loads(template.read_text(encoding="utf-8")))
        if "error" in flat:
            raise SystemExit(f"{template.name}: {flat['error']}")
        target = args.out / template.name
        target.write_text(json.dumps(flat, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{template.name}: {len(flat)} nodes")
    page.quit()


if __name__ == "__main__":
    main()
