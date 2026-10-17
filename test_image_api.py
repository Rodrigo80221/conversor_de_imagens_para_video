"""Contract tests; no API credits, Baserow mutations or browser required."""
import base64
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import image_api

buffer = io.BytesIO()
Image.new("RGB", (64, 128), "blue").save(buffer, format="PNG")
PNG = buffer.getvalue()
B64 = base64.b64encode(PNG).decode()


def response(payload, status=200):
    return Mock(status_code=status, json=Mock(return_value=payload))


class ImageApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(image_api.router)
        self.client = TestClient(app)
        self.payload = {"prompt": "A landscape", "api_key": "test-only-key"}

    def post(self, **kwargs):
        return self.client.post("/generate-image", json={**self.payload, **kwargs})

    @patch("image_api.requests.request")
    def test_gemini_finds_image_after_text_and_preserves_model(self, http):
        http.return_value = response({"candidates": [{"content": {"parts": [
            {"text": "Here is your image"}, {"inlineData": {"data": B64}}]}}]})
        result = self.post(model="gemini-3-pro-image-preview", image_size="2K")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, PNG)
        self.assertEqual(result.headers["content-type"], "image/png")
        args, kwargs = http.call_args
        self.assertTrue(args[1].endswith("gemini-3-pro-image-preview:generateContent"))
        self.assertEqual(kwargs["json"]["generationConfig"]["imageConfig"], {"aspectRatio": "9:16", "imageSize": "2K"})
        self.assertNotIn("key=", args[1])

    @patch("image_api.requests.request")
    def test_gemini_reference_and_base64_response(self, http):
        http.return_value = response({"candidates": [{"content": {"parts": [{"inlineData": {"data": B64}}]}}]})
        result = self.post(reference_images=[{"base64": B64}], response_format="base64")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["base64"], B64)
        part = http.call_args.kwargs["json"]["contents"][0]["parts"][1]
        self.assertEqual(part["inlineData"]["mimeType"], "image/png")

    @patch("image_api.requests.request")
    def test_openai_generation_and_edit(self, http):
        http.return_value = response({"data": [{"b64_json": B64}]})
        result = self.post(technology="chatgpt", size="1024x1536", quality="high")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(http.call_args.args[1].endswith("/images/generations"))
        result = self.post(technology="openai", reference_images=[{"base64": B64}])
        self.assertEqual(result.status_code, 200)
        self.assertTrue(http.call_args.args[1].endswith("/images/edits"))
        self.assertEqual(http.call_args.kwargs["files"][0][0], "image[]")

    def test_html_reuses_renderer_and_cleans_temp_dir(self):
        paths = []
        def render(html, css, width, height, output_path):
            paths.append(output_path)
            self.assertEqual((html, css, width, height), ("<h1>Hello</h1>", "h1{color:red}", 64, 128))
            output_path.write_bytes(PNG)
        with patch.dict(sys.modules, {"html_img_engine": types.SimpleNamespace(generate_image_from_html=render)}):
            result = self.client.post("/generate-image", json={"technology": "html", "html": "<h1>Hello</h1>",
                                      "css": "h1{color:red}", "width": 64, "height": 128})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, PNG)
        self.assertFalse(paths[0].parent.exists())

    @patch("image_api.requests.request")
    def test_removed_storage_contract_rejected(self, http):
        for fields in [
            {"baserow_token": "old-token"},
            {"baserow": {"table_id": 42, "row_id": 123, "field": "Cover"}},
            {"response_format": "baserow"},
            {"reference_images": [{"baserow": {"table_id": 12, "row_id": 34}}]},
        ]:
            self.assertEqual(self.post(**fields).status_code, 422)
        http.assert_not_called()

    @patch("image_api.download_image", return_value=PNG)
    @patch("image_api.requests.request")
    def test_reference_url_and_no_storage_calls(self, http, download):
        http.return_value = response({"data": [{"b64_json": B64}]})
        result = self.post(technology="chatgpt", reference_images=[{"url": "https://example.com/ref.png"}])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, PNG)
        download.assert_called_once_with("https://example.com/ref.png")
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[1], "https://api.openai.com/v1/images/edits")

    @patch("image_api.requests.request")
    def test_invalid_requests_never_call_provider(self, http):
        cases = [{"company": "cloud"}, {"technology": "cloud"}, {"prompt": " "},
                 {"reference_images": [{"url": "https://example.com", "base64": B64}]},
                 {"reference_images": [{"base64": "not base64"}]},
                 {"technology": "html"}, {"model": "../other"}, {"typo": 1},
                 {"baserow": {"table_id": 12}}, {"technology": "chatgpt", "image_size": "2K"}]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self.post(**case).status_code, 422)
        http.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    @patch("image_api.requests.request")
    def test_missing_credentials_before_generation(self, http):
        self.assertEqual(self.post(api_key=None).status_code, 422)
        self.assertEqual(self.post(response_format="baserow").status_code, 422)
        http.assert_not_called()

    @patch("image_api.requests.request")
    def test_upstream_errors_no_retry_no_secret_echo(self, http):
        http.return_value = response({"error": "test-only-key"}, 429)
        result = self.post()
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("test-only-key", result.text)
        self.assertEqual(http.call_count, 1)
        http.side_effect = requests.Timeout()
        self.assertEqual(self.post().status_code, 504)

    @patch("image_api.requests.request")
    def test_no_image_and_malformed_image(self, http):
        for payload in [{}, {"candidates": [{"content": {"parts": [{"inlineData": {"data": "broken"}}]}}]}, []]:
            http.return_value = response(payload)
            self.assertEqual(self.post().status_code, 502)

    def test_private_reference_is_rejected(self):
        with self.assertRaises(image_api.HTTPException) as caught:
            image_api.download_image("http://127.0.0.1/private")
        self.assertEqual(caught.exception.status_code, 422)

    def test_openapi_exposes_contract(self):
        document = self.client.get("/openapi.json").json()
        self.assertIn("/generate-image", document["paths"])
        self.assertIn("GenerateImageRequest", document["components"]["schemas"])
        self.assertNotIn("baserow", str(document).lower())


if __name__ == "__main__":
    unittest.main()
