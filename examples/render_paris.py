"""Upload local sources, resolve the template and render via HTTP only."""
import argparse
import json
import os
from pathlib import Path
import time

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--media-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font-profile", choices=["auto", "original", "open"], default=None)
    parser.add_argument("--preview", action="store_true", help="Render em 360x640 para revisao rapida")
    args = parser.parse_args()
    recipe = json.loads(Path(__file__).with_name("paris_edit.template.json").read_text(encoding="utf-8"))
    if args.font_profile:
        recipe["typography"]["font_profile"] = args.font_profile
    if args.preview:
        recipe.update(width=360, height=640)
    session = requests.Session()
    if os.environ.get("VIDEO_EDITING_API_KEY"):
        session.headers["X-Video-Editing-Key"] = os.environ["VIDEO_EDITING_API_KEY"]
    base = args.api_url.rstrip("/") + "/video-editing/v1"
    assets = {}
    # Check all source files before sending any upload.
    for shot in recipe["shots"]:
        path = args.media_dir / shot["source"]
        if not path.is_file():
            raise FileNotFoundError(path)
    for shot in recipe["shots"]:
        filename = shot.pop("source")
        if filename not in assets:
            with (args.media_dir / filename).open("rb") as file:
                response = session.post(base + "/assets", files={"file": (filename, file)}, timeout=(10, 600))
            response.raise_for_status()
            assets[filename] = response.json()["asset_id"]
            print("Importado:", filename, flush=True)
        shot["asset_id"] = assets[filename]
    response = session.post(base + "/render", json=recipe, timeout=30)
    response.raise_for_status()
    job = response.json()
    print("Job:", job["id"], flush=True)
    last_stage = None
    try:
        while job["status"] in ("queued", "running", "cancelling"):
            if job["stage"] != last_stage:
                print(f"{job['progress']:.0%} {job['stage']}", flush=True)
                last_stage = job["stage"]
            time.sleep(2)
            response = session.get(base + "/jobs/" + job["id"], timeout=30)
            response.raise_for_status()
            job = response.json()
    except KeyboardInterrupt:
        session.post(base + "/jobs/" + job["id"] + "/cancel", timeout=30).raise_for_status()
        raise SystemExit("Cancelamento solicitado.")
    if job["status"] != "succeeded":
        raise RuntimeError(job.get("error") or job["status"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with session.get(base + "/jobs/" + job["id"] + "/result", stream=True, timeout=(10, 600)) as response:
        response.raise_for_status()
        with args.output.open("wb") as output:
            for chunk in response.iter_content(1024*1024):
                output.write(chunk)
    args.output.with_suffix(".recipe.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Salvo:", args.output)


if __name__ == "__main__":
    main()
