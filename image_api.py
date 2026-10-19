"""Unified single-image generation, independent of n8n and the video engines."""
import base64
import binascii
import io
import os
import json
import math
import secrets
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal, Optional

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, FileResponse
from starlette.background import BackgroundTask
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, PrivateAttr, ValidationError, model_validator

router = APIRouter(tags=["Image generation"])
MAX_IMAGE_BYTES = 15 * 1024 * 1024
TIMEOUT = (15, 180)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReferenceImage(StrictModel):
    url: Optional[str] = None
    base64: Optional[str] = Field(default=None, max_length=21_000_000)

    @model_validator(mode="after")
    def one_source(self):
        if sum(bool(x) for x in (self.url, self.base64)) != 1:
            raise ValueError("Cada referencia exige exatamente url ou base64.")
        return self


class ImageOptions(StrictModel):
    company: Optional[str] = Field(default=None, description="google, openai ou local")
    technology: Literal["gemini", "chatgpt", "openai", "comfyui", "html"] = "gemini"
    model: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]+$", max_length=150)
    api_key: Optional[SecretStr] = None
    prompt: Optional[str] = Field(default=None, max_length=32000)
    prompt_style: Literal["raw", "reel_cover"] = "raw"
    on_screen_text: Optional[str] = Field(default=None, max_length=4000)
    reference_images: list[ReferenceImage] = Field(default_factory=list, max_length=4)
    aspect_ratio: str = Field(default="9:16", pattern=r"^[1-9][0-9]?:[1-9][0-9]?$" )
    image_size: Optional[Literal["1K", "2K", "4K"]] = None
    size: str = Field(default="auto", pattern=r"^(auto|[1-9][0-9]{2,3}x[1-9][0-9]{2,3})$")
    quality: Literal["auto", "low", "medium", "high"] = "auto"
    seed: Optional[int] = Field(default=None, ge=0, le=18_446_744_073_709_551_615)
    steps: Optional[int] = Field(default=None, ge=1, le=100)
    html: Optional[str] = Field(default=None, max_length=1_000_000)
    css: str = Field(default="", max_length=500_000)
    width: int = Field(default=1080, ge=64, le=4096)
    height: int = Field(default=1920, ge=64, le=4096)


class GenerateImageRequest(ImageOptions):
    response_format: Literal["binary", "base64"] = "binary"

    @model_validator(mode="after")
    def combinations(self):
        expected = {"gemini": "google", "chatgpt": "openai", "openai": "openai",
                    "comfyui": "local", "html": "local"}[self.technology]
        if self.company and self.company.lower() != expected:
            raise ValueError(f"company deve ser {expected} para esta technology.")
        self.company = expected
        if self.technology == "html":
            if not self.html:
                raise ValueError("html e obrigatorio para technology=html.")
            if self.reference_images or self.model or self.prompt or self.on_screen_text or self.seed is not None or self.steps is not None:
                raise ValueError("HTML recebe html/css prontos; nao recebe prompt, modelo ou referencias.")
        else:
            if not self.prompt:
                raise ValueError("prompt e obrigatorio para geracao por IA.")
            if self.html or self.css:
                raise ValueError("html/css exigem technology=html.")
        if self.technology in ("openai", "chatgpt") and self.image_size:
            raise ValueError("OpenAI usa size em pixels; image_size e exclusivo do Gemini.")
        if self.technology == "gemini" and (self.size != "auto" or self.quality != "auto"):
            raise ValueError("Gemini usa aspect_ratio/image_size; size/quality sao da OpenAI.")
        if self.technology != "comfyui" and (self.seed is not None or self.steps is not None):
            raise ValueError("seed/steps sao exclusivos do ComfyUI.")
        if self.technology == "comfyui":
            if self.reference_images:
                raise ValueError("O workflow ComfyUI Z-Image-Turbo atual nao aceita imagens de referencia.")
            if self.image_size or self.quality != "auto":
                raise ValueError("ComfyUI usa aspect_ratio ou size; image_size/quality nao se aplicam.")
            comfyui_dimensions(self)
        return self


class BatchImageRequest(StrictModel):
    defaults: ImageOptions = Field(default_factory=ImageOptions)
    images: list[ImageOptions] = Field(min_length=1, max_length=20)
    skip_first: bool = False
    response_format: Literal["zip"] = "zip"
    include_manifest: bool = False
    _requests: list[GenerateImageRequest] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def prepare_all(self):
        selected = self.images[1:] if self.skip_first else self.images
        if not selected:
            raise ValueError("Nenhuma imagem restante apos skip_first.")
        common = self.defaults.model_dump(exclude_unset=True)
        self._requests = []
        for index, item in enumerate(selected, start=int(self.skip_first)):
            merged = {**common, **item.model_dump(exclude_unset=True)}
            try:
                self._requests.append(GenerateImageRequest.model_validate(merged))
            except ValidationError as exc:
                # Never include raw input (credentials/base64/prompts) in this error.
                messages = "; ".join(e["msg"] for e in exc.errors(include_input=False, include_context=False))
                raise ValueError(f"images[{index}]: {messages}") from None
        return self


def credential(value, env):
    key = value.get_secret_value() if value else os.getenv(env, "")
    if not key.strip():
        raise HTTPException(422, f"Informe a credencial ou configure {env} no servidor.")
    return key.strip()


def request_json(method, url, stage, **kwargs):
    try:
        response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        if not 200 <= response.status_code < 300:
            raise HTTPException(502, {"stage": stage, "upstream_status": response.status_code})
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
        return payload
    except requests.Timeout:
        raise HTTPException(504, {"stage": stage, "message": "Tempo limite do servico externo."}) from None
    except (requests.RequestException, ValueError):
        raise HTTPException(502, {"stage": stage, "message": "Resposta externa invalida."}) from None


def inspect_image(data, status=422):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status, "Imagem vazia ou maior que 15 MiB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError()
            if image.width * image.height > 25_000_000:
                raise ValueError()
            fmt, dimensions = image.format, image.size
            image.verify()
        return {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt], dimensions
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status, "Imagem invalida: use PNG, JPEG ou WebP com ate 25 megapixels.") from None


def decode_image(value, status=422):
    try:
        data = base64.b64decode(value.split(",", 1)[-1] if value.startswith("data:") else value, validate=True)
    except (ValueError, binascii.Error, AttributeError):
        raise HTTPException(status, "Base64 de imagem invalido.") from None
    inspect_image(data, status)
    return data


def download_image(url):
    # References are public URLs; never forward provider credentials.
    from urllib.parse import urlsplit
    import ipaddress
    import socket
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "URL de referencia invalida.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise HTTPException(422, "A URL de referencia deve ser publica.")
        with requests.get(url, timeout=(15, 60), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise HTTPException(502, "Falha ao baixar referencia. Use uma URL direta, sem redirecionamento.")
            result = bytearray()
            for chunk in response.iter_content(65536):
                result.extend(chunk)
                if len(result) > MAX_IMAGE_BYTES:
                    raise HTTPException(422, "Referencia maior que 15 MiB.")
    except (requests.RequestException, OSError, ValueError):
        raise HTTPException(502, "Falha ao baixar imagem de referencia.") from None
    data = bytes(result)
    inspect_image(data)
    return data


def references(req):
    result = []
    for ref in req.reference_images:
        if ref.base64:
            data = decode_image(ref.base64)
        else:
            data = download_image(ref.url)
        result.append((data, inspect_image(data)[0]))
    return result


def build_prompt(req):
    prompt = req.prompt
    if req.prompt_style == "reel_cover":
        prompt = (f"Create an ultra-realistic Instagram Reel cover ({req.aspect_ratio}). "
                  "Cinematic lighting, shallow depth of field, premium modern aesthetic, high contrast, "
                  "realistic textures. Avoid clutter, watermark, blur and distortion.\nScene: " + prompt)
    if req.on_screen_text:
        prompt += (f'\nIntegrate this exact text: "{req.on_screen_text}". Use bold modern typography, '
                   "strong contrast and mobile readability; keep text away from edges and UI overlays.")
    return prompt


def gemini(req, key, refs, prompt):
    model = req.model or "gemini-3-pro-image-preview"
    parts = [{"text": prompt}] + [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}} for data, mime in refs]
    config = {"aspectRatio": req.aspect_ratio}
    if req.image_size:
        config["imageSize"] = req.image_size
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": config}}
    result = request_json("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          "generation", headers={"x-goog-api-key": key}, json=body)
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData", part.get("inline_data", {}))
            if inline.get("data") and not part.get("thought"):
                return decode_image(inline["data"], 502), model
    raise HTTPException(502, "Gemini nao retornou imagem; verifique prompt, modelo e politicas do provedor.")


def openai_image(req, key, refs, prompt):
    model = req.model or "gpt-image-1"
    body = {"model": model, "prompt": prompt + f"\nRequested composition aspect ratio: {req.aspect_ratio}.",
            "n": 1, "size": req.size, "quality": req.quality, "output_format": "png"}
    headers = {"Authorization": f"Bearer {key}"}
    if refs:
        files = [("image[]", (f"reference_{i}.{mime.split('/')[1]}", data, mime)) for i, (data, mime) in enumerate(refs)]
        result = request_json("POST", "https://api.openai.com/v1/images/edits", "generation", headers=headers, data=body, files=files)
    else:
        result = request_json("POST", "https://api.openai.com/v1/images/generations", "generation", headers=headers, json=body)
    items = result.get("data", [])
    if not items or not items[0].get("b64_json"):
        raise HTTPException(502, "OpenAI nao retornou imagem em base64. Utilize um modelo GPT Image.")
    return decode_image(items[0]["b64_json"], 502), model


def comfyui_dimensions(req):
    if req.size != "auto":
        width, height = (int(value) for value in req.size.split("x", 1))
        if width % 16 or height % 16 or not 256 <= width <= 2048 or not 256 <= height <= 2048:
            raise ValueError("Para ComfyUI, size deve usar multiplos de 16 entre 256 e 2048.")
        return width, height

    numerator, denominator = (int(value) for value in req.aspect_ratio.split(":", 1))
    ratio = numerator / denominator
    if not 0.25 <= ratio <= 4:
        raise ValueError("Para ComfyUI, aspect_ratio deve ficar entre 1:4 e 4:1.")
    target_pixels = 1024 * 1024
    width = math.sqrt(target_pixels * ratio)
    height = math.sqrt(target_pixels / ratio)
    if max(width, height) > 1536:
        scale = 1536 / max(width, height)
        width *= scale
        height *= scale
    width = max(256, int(round(width / 16)) * 16)
    height = max(256, int(round(height / 16)) * 16)
    return width, height


def comfyui_headers():
    client_id = os.getenv("COMFYUI_ACCESS_CLIENT_ID", "").strip()
    client_secret = os.getenv("COMFYUI_ACCESS_CLIENT_SECRET", "").strip()
    if bool(client_id) != bool(client_secret):
        raise HTTPException(500, "Configure juntos COMFYUI_ACCESS_CLIENT_ID e COMFYUI_ACCESS_CLIENT_SECRET.")
    if not client_id:
        return {}
    return {"CF-Access-Client-Id": client_id, "CF-Access-Client-Secret": client_secret}


def comfyui_workflow(prompt, width, height, seed, steps, model):
    clip_model = os.getenv("COMFYUI_CLIP_MODEL", "qwen_3_4b.safetensors").strip()
    vae_model = os.getenv("COMFYUI_VAE_MODEL", "ae.safetensors").strip()
    return {
        "28": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}},
        "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_model, "type": "lumina2", "device": "default"}},
        "29": {"class_type": "VAELoader", "inputs": {"vae_name": vae_model}},
        "27": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["30", 0]}},
        "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["27", 0]}},
        "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3.0}},
        "13": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["11", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple",
            "positive": ["27", 0], "negative": ["33", 0], "latent_image": ["13", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["29", 0]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    }


def comfyui_image(req, _key, _refs, prompt):
    base_url = os.getenv("COMFYUI_BASE_URL", "https://comfyui.progridai.com.br").strip().rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise HTTPException(500, "COMFYUI_BASE_URL deve ser uma URL HTTP(S).")
    model = req.model or os.getenv("COMFYUI_MODEL", "z_image_turbo_bf16.safetensors").strip()
    if model in ("z-image-turbo", "z_image_turbo"):
        model = "z_image_turbo_bf16.safetensors"
    width, height = comfyui_dimensions(req)
    seed = req.seed if req.seed is not None else secrets.randbelow(2**63)
    steps = req.steps or 8
    headers = comfyui_headers()
    workflow = comfyui_workflow(prompt, width, height, seed, steps, model)
    queued = request_json("POST", f"{base_url}/prompt", "comfyui_queue", headers=headers,
                          json={"prompt": workflow, "client_id": secrets.token_hex(16)})
    prompt_id = queued.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 200:
        raise HTTPException(502, {"stage": "comfyui_queue", "message": "ComfyUI nao retornou prompt_id valido."})

    try:
        timeout_seconds = min(900, max(30, int(os.getenv("COMFYUI_TIMEOUT_SECONDS", "300"))))
    except ValueError:
        raise HTTPException(500, "COMFYUI_TIMEOUT_SECONDS deve ser um numero inteiro.") from None
    deadline = time.monotonic() + timeout_seconds
    image_info = None
    while time.monotonic() < deadline:
        history = request_json("GET", f"{base_url}/history/{prompt_id}", "comfyui_history", headers=headers)
        item = history.get(prompt_id)
        if isinstance(item, dict):
            status = item.get("status", {})
            output = item.get("outputs", {}).get("9", {})
            images = output.get("images", []) if isinstance(output, dict) else []
            if images and isinstance(images[0], dict):
                image_info = images[0]
                break
            if status.get("completed") or status.get("status_str") in ("error", "failed"):
                raise HTTPException(502, {"stage": "comfyui_generation", "message": "ComfyUI concluiu sem imagem."})
        time.sleep(1)
    if image_info is None:
        raise HTTPException(504, {"stage": "comfyui_generation", "message": "Tempo limite aguardando o ComfyUI."})

    params = {key: image_info.get(key, "") for key in ("filename", "subfolder", "type")}
    if not params["filename"]:
        raise HTTPException(502, {"stage": "comfyui_result", "message": "ComfyUI retornou arquivo invalido."})
    try:
        response = requests.request("GET", f"{base_url}/view", params=params, headers=headers, timeout=(15, 60))
        if not 200 <= response.status_code < 300:
            raise HTTPException(502, {"stage": "comfyui_result", "upstream_status": response.status_code})
        data = response.content
    except requests.Timeout:
        raise HTTPException(504, {"stage": "comfyui_result", "message": "Tempo limite baixando a imagem."}) from None
    except requests.RequestException:
        raise HTTPException(502, {"stage": "comfyui_result", "message": "Falha ao baixar a imagem."}) from None
    inspect_image(data, 502)
    return data, model


# Register new providers here without changing the HTTP contract or the n8n flow.
PROVIDERS = {"gemini": (gemini, "GEMINI_API_KEY"), "chatgpt": (openai_image, "OPENAI_API_KEY"),
             "openai": (openai_image, "OPENAI_API_KEY"), "comfyui": (comfyui_image, None)}


def render_image(req: GenerateImageRequest):
    """Shared renderer: returns validated bytes and metadata, never persists externally."""
    if req.technology == "html":
        import html_img_engine
        try:
            with tempfile.TemporaryDirectory(prefix="generate_image_") as folder:
                path = Path(folder) / "image.png"
                html_img_engine.generate_image_from_html(req.html, req.css, req.width, req.height, path)
                data = path.read_bytes()
        except Exception:
            raise HTTPException(500, "Falha ao renderizar HTML; verifique Chromium/CHROME_BIN no servidor.") from None
        model = None
    else:
        adapter, env = PROVIDERS[req.technology]
        key = credential(req.api_key, env) if env else None
        data, model = adapter(req, key, references(req), build_prompt(req))
    mime, (width, height) = inspect_image(data, 502)
    filename = "generated_image." + {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
    result = {"success": True, "company": req.company, "technology": req.technology, "model": model,
              "filename": filename, "mime_type": mime, "width": width, "height": height}
    return data, result


def generate_batch(req: BatchImageRequest):
    # Check every credential and inline reference before starting any paid generation.
    for index, item in enumerate(req._requests, start=int(req.skip_first)):
        try:
            if item.technology != "html":
                env = PROVIDERS[item.technology][1]
                if env:
                    credential(item.api_key, env)
            for ref in item.reference_images:
                if ref.base64:
                    decode_image(ref.base64)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, {"index": index, "completed": 0, "message": exc.detail}) from None
    folder = tempfile.mkdtemp(prefix="generate_batch_")
    path = Path(folder) / "generated_images.zip"
    entries = []
    total_bytes = 0
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, item in enumerate(req._requests, start=int(req.skip_first)):
                try:
                    data, metadata = render_image(item)
                    total_bytes += len(data)
                    if total_bytes > 200 * 1024 * 1024:
                        raise HTTPException(413, "O lote excedeu o limite de 200 MiB de imagens.")
                except HTTPException as exc:
                    raise HTTPException(exc.status_code, {"index": index, "completed": len(entries),
                        "message": exc.detail, "archive_returned": False}) from None
                filename = f"image_{len(entries) + 1}{Path(metadata['filename']).suffix}"
                archive.writestr(filename, data)
                entries.append({**metadata, "filename": filename, "source_index": index})
            if req.include_manifest:
                archive.writestr("manifest.json", json.dumps({"count": len(entries), "images": entries}, ensure_ascii=False, indent=2))
        return FileResponse(path, media_type="application/zip", filename="generated_images.zip",
                            headers={"X-Image-Count": str(len(entries))},
                            background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True))
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@router.post("/generate-image", summary="Gerar imagem unica ou lote de imagens em ZIP")
def generate_image(req: GenerateImageRequest | BatchImageRequest):
    # Synchronous route: FastAPI runs HTTP/render work in its thread pool.
    if isinstance(req, BatchImageRequest):
        return generate_batch(req)
    data, result = render_image(req)
    if req.response_format == "binary":
        return Response(data, media_type=result["mime_type"], headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'})
    result["base64"] = base64.b64encode(data).decode()
    return result
