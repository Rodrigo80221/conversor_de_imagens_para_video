import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from voice_cors import VoiceCORSMiddleware


class VoiceCorsTests(unittest.TestCase):
    def client(self, origins="*"):
        app = FastAPI()
        app.add_middleware(VoiceCORSMiddleware)

        @app.post("/process-voice")
        def voice(fail: bool = False):
            if fail:
                raise HTTPException(422, "Audio invalido")
            return {"ok": True}

        @app.get("/other")
        def other():
            return {"ok": True}

        with patch.dict(os.environ, {"VOICE_ALLOWED_ORIGINS": origins}):
            client = TestClient(app)
            client.get("/other")  # Build middleware under this configuration.
        return client

    def test_voice_preflight_and_validation_errors_have_cors(self):
        client = self.client()
        headers = {"Origin": "http://localhost:51780"}
        response = client.options("/process-voice", headers={**headers, "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        for url in ["/process-voice", "/process-voice?fail=true"]:
            response = client.post(url, headers=headers)
            self.assertEqual(response.headers["access-control-allow-origin"], "*")
            self.assertIn("X-Audio-Cuts", response.headers["access-control-expose-headers"])
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("access-control-allow-origin", client.get("/other", headers=headers).headers)

    def test_configured_origins_do_not_allow_unlisted_sites(self):
        client = self.client("https://nina.example")
        self.assertEqual(client.post("/process-voice", headers={"Origin": "https://nina.example"}).headers["access-control-allow-origin"], "https://nina.example")
        self.assertNotIn("access-control-allow-origin", client.post("/process-voice", headers={"Origin": "https://other.example"}).headers)


if __name__ == "__main__":
    unittest.main()
