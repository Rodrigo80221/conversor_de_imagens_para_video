"""Measured FFmpeg integration tests; generated fixtures, no paid services."""
import array
import io
import itertools
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import voice_api
import voice_engine

RATE = 16000


def recording(noise=False, stereo=False, silence_only=False):
    rng = random.Random(1)
    segments = [(0.6, False), (0.5, True), (0.4, False), (0.5, True), (1.4, False), (0.5, True), (0.8, False)]
    samples = array.array("h")
    for duration, speech in segments:
        for i in range(round(duration * RATE)):
            value = (6000 * math.sin(2 * math.pi * 440 * i / RATE) if speech and not silence_only else 0)
            value += rng.gauss(0, 100) if noise else 0
            samples.append(int(value))
            if stereo:
                samples.append(0)  # Voice in one channel must not be classified as silence.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(2 if stereo else 1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def wav_info(data):
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.getnframes() / wav.getframerate(), wav.getnchannels(), wav.readframes(wav.getnframes())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VoiceApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(voice_api.router)
        self.app = app
        self.client = TestClient(app)
        self.off = {"trim_start": "false", "trim_end": "false", "shorten_pauses": "false", "reduce_noise": "false"}

    def post(self, flags=None, data=None, filename="recording.wav"):
        return self.client.post("/process-voice", files={"file": (filename, recording() if data is None else data, "application/octet-stream")}, data=flags or {})

    def test_all_eight_cut_combinations_are_independent(self):
        for start, end, middle in itertools.product((False, True), repeat=3):
            flags = {**self.off, "trim_start": str(start).lower(), "trim_end": str(end).lower(), "shorten_pauses": str(middle).lower()}
            with self.subTest(start=start, end=end, middle=middle):
                result = self.post(flags)
                self.assertEqual(result.status_code, 200, result.text[:200] if result.status_code != 200 else "")
                duration, channels, samples = wav_info(result.content)
                self.assertAlmostEqual(duration, 4.7 - 0.55*start - 0.75*end - 1.15*middle, delta=0.015)
                self.assertEqual(int(result.headers["X-Audio-Cuts"]), start + end + middle)
                self.assertEqual(channels, 1)
                if not (start or end or middle):
                    self.assertEqual(samples, wav_info(recording())[2])

    def test_four_effects_enabled_by_default(self):
        result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertLess(wav_info(result.content)[0], 2.5)

    def test_noise_reduction_keeps_duration_and_lowers_noise(self):
        noisy = recording(noise=True)
        original = self.post(self.off, noisy)
        denoised = self.post({**self.off, "reduce_noise": "true"}, noisy)
        self.assertEqual(denoised.status_code, 200)
        d0, _, raw0 = wav_info(original.content)
        d1, _, raw1 = wav_info(denoised.content)
        self.assertAlmostEqual(d0, d1, delta=1/RATE)
        def rms(raw):
            samples = array.array("h", raw)[round(0.15*RATE):round(0.45*RATE)]
            return math.sqrt(sum(x*x for x in samples)/len(samples))
        self.assertLess(rms(raw1), rms(raw0)*0.8)
        # Strong tone remains; noise removal must not erase all audio.
        voice = array.array("h", raw1)[round(0.7*RATE):round(0.9*RATE)]
        self.assertGreater(max(voice), 1000)

    def test_stereo_voice_is_preserved(self):
        result = self.post({**self.off, "shorten_pauses": "true"}, recording(stereo=True))
        self.assertEqual(result.status_code, 200)
        duration, channels, _ = wav_info(result.content)
        self.assertEqual(channels, 2)
        self.assertAlmostEqual(duration, 3.55, delta=0.02)

    def test_webm_browser_upload_and_all_output_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"source.wav"
            source.write_bytes(recording())
            for extension, codec in [("webm", "libopus"), ("m4a", "aac"), ("ogg", "libopus"), ("mp3", "libmp3lame")]:
                target = Path(folder)/f"browser.{extension}"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:a", codec, str(target)], check=True, capture_output=True)
                result = self.post(self.off, target.read_bytes(), target.name)
                self.assertEqual(result.status_code, 200, extension)
                self.assertAlmostEqual(wav_info(result.content)[0],4.7,delta=0.15)
            for fmt, mime in [("mp3", "audio/mpeg"), ("webm", "audio/webm")]:
                result = self.post({**self.off, "output_format": fmt})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers["content-type"],mime)
                output = Path(folder)/f"output.{fmt}"
                output.write_bytes(result.content)
                subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],check=True,capture_output=True)

    def test_pure_silence_has_explicit_error_or_is_preserved(self):
        quiet = recording(silence_only=True)
        self.assertEqual(self.post(data=quiet).status_code, 422)
        result = self.post({**self.off, "shorten_pauses": "true"}, quiet)
        self.assertEqual(result.status_code, 200)
        self.assertAlmostEqual(wav_info(result.content)[0],4.7,delta=0.01)

    def test_invalid_parameters_and_missing_audio(self):
        for fields in [{"trim_start":"invalid"}, {"silence_threshold_db":"-2"}, {"noise_reduction_db":"100"},
                       {"keep_pause_seconds":"2", "min_pause_seconds":"1"}, {"output_format":"exe"}]:
            with self.subTest(fields=fields):
                self.assertEqual(self.post(fields).status_code,422)
        self.assertEqual(self.post(data=b"").status_code,422)
        self.assertEqual(self.post(data=b"not audio").status_code,422)
        self.assertEqual(self.client.post("/process-voice").status_code,422)

    def test_upload_size_and_duration_limits(self):
        with patch("voice_api.MAX_UPLOAD_BYTES", 100):
            self.assertEqual(self.post().status_code,413)
        with patch("voice_engine.MAX_DURATION", 1):
            self.assertEqual(self.post().status_code,413)

    def test_response_and_error_clean_up_temporary_files(self):
        folders = []
        original = tempfile.mkdtemp
        def capture(*args, **kwargs):
            folder = original(*args, **kwargs)
            folders.append(Path(folder))
            return folder
        with patch("voice_api.tempfile.mkdtemp", side_effect=capture):
            self.assertEqual(self.post(self.off).status_code,200)
            self.assertEqual(self.post(data=b"bad").status_code,422)
        self.assertTrue(folders)
        self.assertTrue(all(not p.exists() for p in folders))

    def test_missing_ffmpeg_timeout_and_openapi(self):
        with patch("voice_engine.shutil.which", return_value=None):
            self.assertEqual(self.post().status_code,503)
        with patch("voice_engine.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg",180)):
            self.assertEqual(self.post().status_code,504)
        schema = self.client.get("/openapi.json").json()
        body_schema = schema["paths"]["/process-voice"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
        model = schema["components"]["schemas"][body_schema["$ref"].split("/")[-1]]
        self.assertTrue({"file","trim_start","trim_end","shorten_pauses","reduce_noise"} <= set(model["properties"]))


if __name__ == "__main__":
    unittest.main()
