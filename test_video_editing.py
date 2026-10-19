"""Real FFmpeg integration tests. No external APIs or user media required."""
import array
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from video_editing.api import router
from video_editing.fonts import resolve_fonts
from video_editing.media import Cancelled, ffmpeg, probe, run
from video_editing.models import Recipe
from video_editing.service import Service, write_json

PREFIX = "/video-editing/v1"


class EditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_dir = tempfile.TemporaryDirectory()
        root = Path(cls.media_dir.name)
        # Clockwise rotation makes the red left half become the upright top half.
        image = Image.new("RGB", (320, 180), "red")
        image.paste(Image.new("RGB", (160, 180), "blue"), (160, 0))
        image.save(root / "halves.png")
        run([ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(root / "halves.png"),
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", str(root / "base.mp4")])
        run([ffmpeg(), "-v", "error", "-y", "-display_rotation", "-90", "-i", str(root / "base.mp4"),
             "-c", "copy", str(root / "rotated.mp4")])
        cls.video = (root / "rotated.mp4").read_bytes()
        photo = io.BytesIO()
        Image.new("RGB", (180, 320), "green").save(photo, "PNG")
        cls.photo = photo.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.media_dir.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"VIDEO_EDITING_DATA_DIR": self.folder.name,
                                           "VIDEO_EDITING_API_KEY": ""})
        self.env.start()
        app = FastAPI()
        app.include_router(router)
        self.app = app
        self.client = TestClient(app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.folder.cleanup()

    def upload(self, name, data):
        r = self.client.post(PREFIX + "/assets", files={"file": (name, data)})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def wait(self, job):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            r = self.client.get(PREFIX + "/jobs/" + job)
            data = r.json()
            if data["status"] not in {"queued", "running", "cancelling"}:
                return data
            time.sleep(.1)
        self.fail("Render timeout")

    def recipe(self, shots, **kwargs):
        return {"width": 240, "height": 426, "fade_in": 0, "fade_out": 0,
                "typography": {"font_profile": "open"}, "shots": shots, **kwargs}

    def test_real_render_rotation_dissolve_slow_audio_and_photo_silence(self):
        video = self.upload("phone.MOV", self.video)
        photo = self.upload("photo.png", self.photo)
        self.assertEqual((video["width"], video["height"]), (180, 320))
        recipe = self.recipe([
            {"asset_id": video["asset_id"], "duration": 1.2, "speed": .75,
             "transition_to_next": {"type": "dissolve", "duration": .2}},
            {"asset_id": photo["asset_id"], "duration": .9, "caption": "Petit Palais"},
            {"asset_id": video["asset_id"], "start": 1, "duration": 1},
        ])
        r = self.client.post(PREFIX + "/render", json=recipe)
        self.assertEqual(r.status_code, 202, r.text)
        item = self.wait(r.json()["id"])
        self.assertEqual(item["status"], "succeeded", item)
        self.assertEqual(item["fonts"]["serif"], "Libre Baskerville")
        result = self.client.get(item["result_url"])
        self.assertEqual(result.status_code, 200)
        output = Path(self.folder.name) / "download.mp4"
        output.write_bytes(result.content)
        info = probe(output)
        self.assertAlmostEqual(info["duration"], 2.9, delta=.07)
        self.assertEqual((info["width"], info["height"], info["rotation"]), (240, 426, 0))
        self.assertTrue(info["has_audio"])
        run([ffmpeg(), "-v", "error", "-i", str(output), "-f", "null", "-"])
        frame = Path(self.folder.name) / "upright.png"
        run([ffmpeg(), "-v", "error", "-y", "-ss", "0.4", "-i", str(output), "-frames:v", "1", str(frame)])
        with Image.open(frame) as im:
            top, bottom = im.getpixel((120, 80)), im.getpixel((120, 250))
            self.assertGreater(top[0], top[2] + 100)
            self.assertGreater(bottom[2], bottom[0] + 100)
        raw = subprocess.check_output([ffmpeg(), "-v", "error", "-i", str(output), "-vn",
                                       "-f", "s16le", "-ac", "1", "-ar", "48000", "-"])
        samples = array.array("h", raw)
        def rms(a, b):
            values = samples[int(a*48000):int(b*48000)]
            return math.sqrt(sum(x*x for x in values) / len(values))
        self.assertGreater(rms(.2, .6), 500)
        self.assertLess(rms(1.3, 1.7), 3)
        self.assertGreater(rms(2.2, 2.6), 500)

    def test_preview_inspection_and_mute_export(self):
        photo = self.upload("photo.png", self.photo)
        r = self.client.post(PREFIX + "/inspect", json={"asset_ids": [photo["asset_id"]]})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("path", r.text)
        preview = self.client.post(PREFIX + "/previews", json={"asset_id": photo["asset_id"]})
        self.assertEqual(preview.status_code, 200, preview.text[:200] if preview.status_code != 200 else "")
        self.assertEqual(Image.open(io.BytesIO(preview.content)).size, (240, 360))
        r = self.client.post(PREFIX + "/render", json=self.recipe([
            {"asset_id": photo["asset_id"], "duration": .6, "title": "PARIS"}], audio="mute"))
        self.assertEqual(r.status_code, 202, r.text)
        job = self.wait(r.json()["id"])
        self.assertEqual(job["status"], "succeeded", job)
        self.assertFalse(probe(Path(self.folder.name) / "jobs" / job["id"] / "result.mp4")["has_audio"])

    def test_bounds_paths_and_auth(self):
        video = self.upload("clip.mp4", self.video)
        bad = self.recipe([{"asset_id": video["asset_id"], "start": 2, "duration": 2}])
        self.assertEqual(self.client.post(PREFIX + "/render", json=bad).status_code, 422)
        self.assertEqual(self.client.post(PREFIX + "/inspect", json={"asset_ids": ["../../main.py"]}).status_code, 422)
        self.assertEqual(self.client.post(PREFIX + "/previews", json={"asset_id": video["asset_id"], "times": [100]}).status_code, 422)
        self.assertEqual(self.client.get(PREFIX + "/jobs/" + "f"*32).status_code, 404)
        with patch.dict(os.environ, {"VIDEO_EDITING_API_KEY": "test-key"}):
            self.assertEqual(self.client.get(PREFIX + "/fonts").status_code, 401)
            self.assertEqual(self.client.get(PREFIX + "/fonts", headers={"X-Video-Editing-Key": "test-key"}).status_code, 200)
        with self.assertRaises(ValueError):
            Recipe.model_validate(self.recipe([
                {"asset_id": video["asset_id"], "duration": .4, "transition_to_next": {"type": "dissolve", "duration": .3}},
                {"asset_id": video["asset_id"], "duration": .5, "transition_to_next": {"type": "dissolve", "duration": .3}},
                {"asset_id": video["asset_id"], "duration": 1},
            ]))

    def test_cancel_running_and_queued_jobs(self):
        photo = self.upload("photo.png", self.photo)
        entered = threading.Event()
        def slow(recipe, assets, folder, cancel, progress):
            entered.set()
            if cancel.wait(10):
                raise Cancelled()
            raise RuntimeError("Cancellation was not delivered")
        with patch("video_editing.service.render", side_effect=slow):
            payload = self.recipe([{"asset_id": photo["asset_id"], "duration": 1}])
            first = self.client.post(PREFIX + "/render", json=payload).json()["id"]
            self.assertTrue(entered.wait(3))
            second = self.client.post(PREFIX + "/render", json=payload).json()["id"]
            self.assertEqual(self.client.post(PREFIX + f"/jobs/{second}/cancel").status_code, 200)
            self.assertEqual(self.client.post(PREFIX + f"/jobs/{first}/cancel").status_code, 200)
            self.assertEqual(self.wait(first)["status"], "cancelled")
            self.assertEqual(self.wait(second)["status"], "cancelled")
            self.assertEqual(self.client.get(PREFIX + f"/jobs/{first}/result").status_code, 409)

    def test_subprocess_cancellation(self):
        event = threading.Event()
        timer = threading.Timer(.2, event.set)
        timer.start()
        try:
            with self.assertRaises(Cancelled):
                run([sys.executable, "-c", "import time; time.sleep(20)"], event)
        finally:
            timer.cancel()

    def test_open_fonts_and_exclusive_worker(self):
        paths, names = resolve_fonts("open")
        self.assertTrue(all(p.exists() for p in paths))
        with self.assertRaises(RuntimeError):
            Service(self.folder.name)

    def test_restart_marks_interrupted_job_failed(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "jobs" / ("a"*32)
            folder.mkdir(parents=True)
            write_json(folder / "job.json", {"id": "a"*32, "status": "running"})
            store = Service(root)
            try:
                self.assertEqual(store.job("a"*32)["status"], "failed")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
