from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from fastapi.responses import FileResponse
import uvicorn
import requests
import io
import wave
import json
import shutil
import tempfile
import os
from pathlib import Path
import zipfile
import video_engine
import music_engine
import html_img_engine
from starlette.concurrency import run_in_threadpool
import base64
import mimetypes

app = FastAPI()

@app.get("/check-chrome")
def check_chrome():
    return {
        "which_chromium": os.popen("which chromium").read().strip(),
        "which_chromium_browser": os.popen("which chromium-browser").read().strip(),
        "ls_usr_bin_chromium": os.path.exists("/usr/bin/chromium"),
        "ls_usr_bin_chromium_browser": os.path.exists("/usr/bin/chromium-browser"),
    }

@app.get("/")
def read_root():
    return {"status": "Online", "message": "API de Video/Audio rodando no Easypanel!"}

@app.post("/add-silence")
async def add_silence_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    duration_ms: int = Form(...)
):
    temp_dir = tempfile.mkdtemp()
    try:
        # Save audio file
        # Preserve original extension or assume wav
        original_ext = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        input_path = os.path.join(temp_dir, f"input_audio{original_ext}")
        
        with open(input_path, "wb") as f:
            f.write(await file.read())
            
        output_filename = f"audio_silenced{original_ext}"
        output_path = os.path.join(temp_dir, output_filename)
        
        await run_in_threadpool(
            video_engine.add_silence_to_audio,
            input_file=Path(input_path),
            output_file=Path(output_path),
            duration_ms=duration_ms
        )
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Silence addition failed (no output file created)"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="audio/wav", 
            filename=output_filename
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/humanize-audio")
async def humanize_audio_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    preset: str = Form("celular")
):
    temp_dir = tempfile.mkdtemp()
    try:
        # Save audio file
        original_ext = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        input_path = os.path.join(temp_dir, f"input_audio{original_ext}")
        
        with open(input_path, "wb") as f:
            f.write(await file.read())
            
        output_filename = f"audio_humanized{original_ext}"
        output_path = os.path.join(temp_dir, output_filename)
        
        await run_in_threadpool(
            video_engine.humanize_audio,
            input_file=Path(input_path),
            output_file=Path(output_path),
            preset=preset
        )
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Humanization failed (no output file created)"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="audio/wav", 
            filename=output_filename
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/get-duration")
async def get_audio_duration(file: UploadFile = File(...)):
    # Lê o arquivo de áudio da memória
    file_bytes = await file.read()
    audio_file = io.BytesIO(file_bytes)
    
    try:
        with wave.open(audio_file, 'rb') as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            duration = frames / float(rate)
            return {
                "filename": file.filename,
                "duration_seconds": duration,
                "duration_formatted": f"{duration:.2f}s"
            }
    except Exception as e:
        return {"error": str(e)}

def cleanup_temp_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception as e:
        print(f"Error cleaning up {path}: {e}")

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    config: str = Form(...),
    cover_file: UploadFile = File(...),
    file: UploadFile = File(...)
):
    try:
        config_data = json.loads(config)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in 'config' field"}

    # Create temp dir
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Save cover file
        # Usamos o nome original do arquivo para que o JSON possa referenciá-lo corretamente
        # ou, se o usuário preferir, poderíamos renomear para 'cover.jpg'.
        # Vou manter o nome original para flexibilidade, mas certifique-se que o JSON usa esse nome.
        cover_path = os.path.join(temp_dir, cover_file.filename)
        with open(cover_path, "wb") as f:
            f.write(await cover_file.read())

        # Save zip
        zip_path = os.path.join(temp_dir, "data.zip")
        with open(zip_path, "wb") as f:
            f.write(await file.read())
        
        # Extract zip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            
        # Define output path
        output_filename = "output.mp4"
        output_path = os.path.join(temp_dir, output_filename)
        
        # Run engine
        # base_dir is where the images are extracted (temp_dir)
        video_engine.generate_video_from_config(config_data, Path(temp_dir), Path(output_path))
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Video generation failed (no output file created)"}

        # Return file and schedule cleanup
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="video/mp4", 
            filename="generated_video.mp4"
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/generate-music")
async def generate_music(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    duration: int = Form(25)
):
    temp_dir = tempfile.mkdtemp()
    try:
        output_filename = "generated_music.mp3"
        output_path = os.path.join(temp_dir, output_filename)
        
        music_engine.generate_music(prompt, duration, Path(output_path))
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Music generation failed"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="audio/mpeg", 
            filename="generated_music.mp3"
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/merge-video-audio")
async def merge_video_audio_endpoint(
    background_tasks: BackgroundTasks,
    video_file: UploadFile = File(...),
    narration_file: Optional[UploadFile] = File(None),
    background_file: Optional[UploadFile] = File(None),
    vol_narration: float = Form(1.0),
    vol_background: float = Form(0.1),
    fade_duration: float = Form(2.0)
):
    temp_dir = tempfile.mkdtemp()
    try:
        # Save video file
        video_path = os.path.join(temp_dir, "input_video.mp4")
        with open(video_path, "wb") as f:
            f.write(await video_file.read())
            
        narration_path = None
        if narration_file:
            # Pega extensão original ou assume wav
            # Se filename for None (raro), usa .wav
            original_ext = os.path.splitext(narration_file.filename)[1] if narration_file.filename else ""
            ext = original_ext or ".wav"
            narration_path = os.path.join(temp_dir, f"narration{ext}")
            with open(narration_path, "wb") as f:
                f.write(await narration_file.read())
                
        background_path = None
        if background_file:
            original_ext = os.path.splitext(background_file.filename)[1] if background_file.filename else ""
            ext = original_ext or ".mp3"
            background_path = os.path.join(temp_dir, f"background{ext}")
            with open(background_path, "wb") as f:
                f.write(await background_file.read())
                
        output_filename = "merged_output.mp4"
        output_path = os.path.join(temp_dir, output_filename)
        
        video_engine.merge_video_audio(
            video_input=Path(video_path),
            output_file=Path(output_path),
            narration_input=Path(narration_path) if narration_path else None,
            background_input=Path(background_path) if background_path else None,
            vol_narration=vol_narration,
            vol_background=vol_background,
            fade_duration=fade_duration
        )
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Merge failed (no output file created)"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="video/mp4", 
            filename="merged_video.mp4"
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/add-subtitles")
async def add_subtitles_endpoint(
    background_tasks: BackgroundTasks,
    video_file: UploadFile = File(...),
    subtitle_content: str = Form(...),
    position_y: int = Form(0), # 0 = Base Absoluta, Valor Positivo = Sobe em direção ao topo
    font_color: str = Form("#FFFFFF"),
    outline_color: str = Form("#000000"),
    font_size: int = Form(24),
    output_name: str = Form("video_subbed"),
    max_lines: Optional[int] = Form(None)
):
    temp_dir = tempfile.mkdtemp()
    try:
        # Save video
        # We try to keep original extension or default to mp4
        orig_ext = os.path.splitext(video_file.filename)[1] if video_file.filename else ".mp4"
        video_path = os.path.join(temp_dir, f"input_video{orig_ext}")
        with open(video_path, "wb") as f:
            f.write(await video_file.read())
            
        # Save SRT
        srt_path = os.path.join(temp_dir, "subtitles.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(subtitle_content)
            
        # Ensure output name ends with .mp4
        if not output_name.lower().endswith(".mp4"):
            output_name += ".mp4"
            
        output_filename = "video_with_subs.mp4" # Internal name
        output_path = os.path.join(temp_dir, output_filename)
        
        # --- A CORREÇÃO ESTÁ AQUI ---
        video_engine.add_subtitles(
            video_input=Path(video_path),
            srt_input=Path(srt_path),
            output_file=Path(output_path),
            position_y=position_y,      # <--- Corrigido de vertical_pos para position_y
            font_color=font_color,
            outline_color=outline_color,
            font_size=font_size,
            max_lines=max_lines
        )
        # ----------------------------
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "Subtitle addition failed (no output file created)"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="video/mp4", 
            filename=output_name
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/auto-subtitles")
async def auto_subtitles_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    words_per_line: int = Form(5)
):
    temp_dir = tempfile.mkdtemp()
    try:
        # Save audio/video
        orig_ext = os.path.splitext(file.filename)[1] if file.filename else ".mp3"
        # Generate generic name but keep extension
        input_path = os.path.join(temp_dir, f"input_media{orig_ext}")
        with open(input_path, "wb") as f:
            f.write(await file.read())
            
        # Generate subtitles using Whisper
        try:
            srt_content = await run_in_threadpool(
                video_engine.generate_subtitles,
                audio_path=Path(input_path),
                output_srt_path=None, # Don't need file output
                words_per_line=words_per_line
            )
        except Exception as e:
            raise RuntimeError(f"Subtitle generation failed: {e}")

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        
        # Return the content directly
        return {"subtitles": srt_content}

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}


# Models that belong to the Gemini 3 image family and require special handling:
# - responseModalities must be set explicitly
# - responses may include "thought" parts that should be skipped
GEMINI3_IMAGE_MODELS = {
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
}

# Alias map: normalizes any user-supplied variant to the canonical API model ID.
# Keys are lowercase; values are the exact string the Gemini API expects.
MODEL_ALIASES: dict[str, str] = {
    # gemini-3-pro-image-preview aliases
    "gemini-3-pro-image-preview":   "gemini-3-pro-image-preview",
    "gemini-3-pro-image":           "gemini-3-pro-image-preview",
    "gemini-3-pro":                 "gemini-3-pro-image-preview",
    "gemini3proimagepreview":       "gemini-3-pro-image-preview",
    # gemini-3.1-flash-image-preview aliases
    "gemini-3.1-flash-image-preview":  "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-image":          "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash":                "gemini-3.1-flash-image-preview",
    # gemini-2.5-flash-image aliases (existing model, keep as-is)
    "gemini-2.5-flash-image":       "gemini-2.5-flash-image",
    "gemini-2.5-flash":             "gemini-2.5-flash-image",
}

def normalize_model_name(model_name: str) -> str:
    """Normalize a user-supplied model name to its canonical Gemini API ID.

    Handles wrong casing, missing '-preview' suffix, and common abbreviations.
    If the name is unknown, falls back to 'gemini-3.1-flash-image-preview'.
    """
    DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
    if not model_name:
        return DEFAULT_MODEL
    key = model_name.strip().lower()
    if key in MODEL_ALIASES:
        return MODEL_ALIASES[key]
    # Unknown model — fall back to default and warn
    print(f"[create-images] Unknown model '{model_name}', falling back to '{DEFAULT_MODEL}'")
    return DEFAULT_MODEL

def is_gemini3_image_model(model_name: str) -> bool:
    """Return True for any Gemini 3 image generation model."""
    if not model_name:
        return False
    name = model_name.strip().lower()
    if name in {m.lower() for m in GEMINI3_IMAGE_MODELS}:
        return True
    # Catch any future gemini-3* image model
    return name.startswith("gemini-3") and "image" in name


@app.post("/create-images")
async def create_images_endpoint(
    background_tasks: BackgroundTasks,
    token: str = Form(...),
    payload: str = Form(...),
    reference_url: Optional[str] = Form(None),
    files: List[UploadFile] = File(None),
    aspect_ratio: str = Form("9:16")
):
    temp_dir = tempfile.mkdtemp()
    
    def upload_to_gemini(content_bytes, mime_type, display_name):
        # 1. Initiate Resumable Upload
        init_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={token}"
        headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(content_bytes)),
            "X-Goog-Upload-Header-Content-Type": "application/json",
            "Content-Type": "application/json"
        }
        # Note: Initial header content type for metadata is application/json.
        # X-Goog-Upload-Header-Content-Type is the MIME of the actual file (e.g. image/jpeg).
        init_headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(content_bytes)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json"
        }
        meta_body = {"file": {"display_name": display_name}}
        
        init_resp = requests.post(init_url, headers=init_headers, json=meta_body)
        if init_resp.status_code != 200:
            raise RuntimeError(f"Failed to init upload: {init_resp.text}")
        
        upload_url = init_resp.headers.get("X-Goog-Upload-URL")
        
        # 2. Upload Bytes
        upload_headers = {
            "Content-Length": str(len(content_bytes)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize"
        }
        
        upload_resp = requests.post(upload_url, headers=upload_headers, data=content_bytes)
        if upload_resp.status_code != 200:
            raise RuntimeError(f"Failed to upload bytes: {upload_resp.text}")
        
        return upload_resp.json().get("file", {}).get("uri")

    try:
        req_data = json.loads(payload)
        images_data = []
        
        # Determine if this is the "Visual Strategy" video plan schema
        is_video_plan = "structure" in req_data and "scenes" in req_data["structure"]
        
        tasks = []
        
        if is_video_plan:
            # Plan Schema
            scenes = req_data["structure"]["scenes"]
            for scene in scenes:
                raw_model = scene.get("generation_technology", "gemini-2.5-flash-image")
                model_name = normalize_model_name(raw_model)
                if model_name != raw_model:
                    print(f"[create-images] Model name normalized: '{raw_model}' -> '{model_name}'")
                prompt = scene.get("scene_image_description", "")
                scene_num = scene.get("scene_number", "0")
                
                # Scene 1 is a thumbnail -> handled by other service
                if str(scene_num) == "1":
                    continue

                # Build content parts
                parts = [{"text": prompt}]
                
                # Reference Image URL
                if scene.get("actor_ref") and reference_url:
                    try:
                        actor_url = reference_url
                        dl_resp = requests.get(actor_url)
                        if dl_resp.status_code == 200:
                            mime = dl_resp.headers.get("Content-Type", "image/jpeg")
                            # Sanitize display name
                            disp_name = f"ref_scene_{scene_num}_{len(parts)}"
                            file_uri = upload_to_gemini(dl_resp.content, mime, disp_name)
                            parts.append({"file_data": {"mime_type": mime, "file_uri": file_uri}})
                    except Exception as e:
                        print(f"Warning: Failed to load actor ref for scene {scene_num}: {e}")
                
                # Construct Gemini Request
                gen_cfg: dict = {
                    "imageConfig": {
                        "aspectRatio": aspect_ratio
                    }
                }
                # Gemini 3 image models require responseModalities to be set
                if is_gemini3_image_model(model_name):
                    gen_cfg["responseModalities"] = ["IMAGE"]

                gemini_req = {
                    "contents": [{"parts": parts}],
                    "generationConfig": gen_cfg
                }
                tasks.append({
                    "model": model_name,
                    "body": gemini_req,
                    "filename": f"scene_{scene_num}.png"
                })
        else:
            # Legacy / Direct Schema
            raw_model = req_data.pop("model", "gemini-2.5-flash-image")
            model_name = normalize_model_name(raw_model)
            if model_name != raw_model:
                print(f"[create-images] Model name normalized: '{raw_model}' -> '{model_name}'")
            
            if "generationConfig" not in req_data:
                req_data["generationConfig"] = {}
            if "aspectRatio" in req_data["generationConfig"]:
                del req_data["generationConfig"]["aspectRatio"]
                
            if "imageConfig" not in req_data["generationConfig"]:
                req_data["generationConfig"]["imageConfig"] = {}
            req_data["generationConfig"]["imageConfig"]["aspectRatio"] = aspect_ratio

            # Gemini 3 image models require responseModalities to be set explicitly
            if is_gemini3_image_model(model_name):
                req_data["generationConfig"].setdefault("responseModalities", ["IMAGE"])
            
            # Helper to inject uploaded files if any
            if files: 
                 # Ensure structure
                if "contents" not in req_data:
                    req_data["contents"] = [{"parts": []}]
                
                uploaded_files_uris = []
                for file in files:
                    content = await file.read()
                    mime = file.content_type or "image/jpeg"
                    uri = upload_to_gemini(content, mime, file.filename)
                    uploaded_files_uris.append((uri, mime))
            
                # Inject into first content block
                if uploaded_files_uris:
                    if not req_data["contents"]:
                         req_data["contents"].append({"parts": []})
                    parts_list = req_data["contents"][0].get("parts", [])
                    if not isinstance(parts_list, list):
                        parts_list = []
                        req_data["contents"][0]["parts"] = parts_list
                         
                    for uri, mime in uploaded_files_uris:
                        parts_list.append({
                            "file_data": {"mime_type": mime, "file_uri": uri}
                        })

            tasks.append({
                "model": model_name,
                "body": req_data,
                "filename": "generated.png" # Standard name
            })

        import copy

        def build_body_for_model(original_body: dict, model: str) -> dict:
            """Return a copy of the request body adapted to the target model."""
            body = copy.deepcopy(original_body)
            if "generationConfig" not in body:
                body["generationConfig"] = {}
            gen_cfg = body["generationConfig"]
            if "imageConfig" not in gen_cfg:
                gen_cfg["imageConfig"] = {}

            if is_gemini3_image_model(model):
                gen_cfg.setdefault("responseModalities", ["IMAGE"])
            else:
                # Older models don't support responseModalities or imageSize
                gen_cfg.pop("responseModalities", None)
                gen_cfg["imageConfig"].pop("imageSize", None)
            return body

        def call_gemini(model: str, body: dict):
            """Call the API. Returns (response, resp_json, err_msg)."""
            adapted = build_body_for_model(body, model)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={token}"
            print(f"[create-images] Calling model={model} | is_gemini3={is_gemini3_image_model(model)}")
            print(f"[create-images] Request body: {json.dumps(adapted, ensure_ascii=False)[:2000]}")
            resp = requests.post(url, json=adapted)
            if resp.status_code == 200:
                return resp, resp.json(), None
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            print(f"[create-images] ERROR {resp.status_code} for model={model}: {err_msg}")
            return resp, {}, err_msg

        def make_diag(model: str, resp, err_msg: str, body: dict) -> str:
            url_no_key = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            return "\n".join([
                "=== Gemini API Error Diagnostic ===",
                f"Model         : {model}",
                f"URL           : {url_no_key}",
                f"HTTP Status   : {resp.status_code}",
                f"Error Message : {err_msg}",
                "",
                "--- Full API Response ---",
                resp.text,
                "",
                "--- Request Body Sent ---",
                json.dumps(build_body_for_model(body, model), indent=2, ensure_ascii=False),
            ])

        # Fallback chain:
        #   primary model  --(503)--> gemini-3.1-flash-image-preview
        #                  --(any other error)--> gemini-2.5-flash-image
        FALLBACK_ON_503   = "gemini-3.1-flash-image-preview"
        FALLBACK_ON_ERROR = "gemini-2.5-flash-image"

        # Execute Requests
        image_count = 1
        for task in tasks:
            filename      = task['filename']
            original_body = task['body']

            # --- Attempt 1: primary model ---
            resp, resp_json, err_msg = call_gemini(task['model'], original_body)

            if err_msg is not None:
                fallback = FALLBACK_ON_503 if resp.status_code == 503 else FALLBACK_ON_ERROR
                print(f"[create-images] Retrying with fallback model={fallback}")

                # --- Attempt 2: first fallback ---
                resp2, resp_json2, err_msg2 = call_gemini(fallback, original_body)

                if err_msg2 is not None and fallback != FALLBACK_ON_ERROR:
                    # --- Attempt 3: last-resort fallback ---
                    print(f"[create-images] Retrying with last-resort model={FALLBACK_ON_ERROR}")
                    resp3, resp_json3, err_msg3 = call_gemini(FALLBACK_ON_ERROR, original_body)
                    if err_msg3 is not None:
                        diag = make_diag(FALLBACK_ON_ERROR, resp3, err_msg3, original_body)
                        images_data.append((f"{filename}_error.txt", diag.encode('utf-8')))
                        continue
                    resp_json = resp_json3
                elif err_msg2 is not None:
                    diag = make_diag(fallback, resp2, err_msg2, original_body)
                    images_data.append((f"{filename}_error.txt", diag.encode('utf-8')))
                    continue
                else:
                    resp_json = resp_json2

            # Extract Candidates (Images)
            # Note: Gemini 3 image models return intermediate "thought" images
            # (part["thought"] == True) before the final image — skip those.
            candidates = resp_json.get("candidates", [])
            found_image = False
            for i, cand in enumerate(candidates):
                parts = cand.get("content", {}).get("parts", [])
                for j, part in enumerate(parts):
                    # Skip thought/reasoning parts produced by Gemini 3 models
                    if part.get("thought") is True:
                        continue
                    if "inline_data" in part or "inlineData" in part:
                        inline_data = part.get("inline_data") or part.get("inlineData")
                        b64_data = inline_data["data"]
                        mime = inline_data.get("mime_type") or inline_data.get("mimeType") or "image/png"
                        ext = mime.split("/")[-1] if "/" in mime else "png"
                        img_bytes = base64.b64decode(b64_data)
                        final_fname = f"image_{image_count}.{ext}"
                        image_count += 1
                        images_data.append((final_fname, img_bytes))
                        found_image = True

            if not found_image:
                images_data.append((f"{filename}_response.json", json.dumps(resp_json, indent=2).encode('utf-8')))

        # Zip Creation
        zip_path = os.path.join(temp_dir, "images.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for fname, data in images_data:
                zf.writestr(fname, data)
                
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(zip_path, media_type="application/zip", filename="generated_images.zip")

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/upload-to-baserow")
async def upload_to_baserow(
    token: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        # Save file to temp
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
            
        # Baserow upload logic
        url_upload = "https://api.baserow.io/api/user-files/upload-file/"
        headers = {
            "Authorization": f"Token {token}" if not token.startswith("Token ") else token
        }
        
        with open(file_path, "rb") as arquivo:
            files = {
                "file": (file.filename, arquivo, file.content_type)
            }
            response = requests.post(url_upload, headers=headers, files=files)
            
        # Cleanup
        shutil.rmtree(temp_dir)
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"Baserow upload failed: {response.status_code}",
                "details": response.text
            }

    except Exception as e:
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return {"error": str(e)}

@app.post("/update-baserow-media")
async def update_baserow_media(
    token: str = Form(...),
    table_id: int = Form(...),
    row_id: int = Form(...),
    field_name: str = Form("Midia Url"),
    append_to_existing: bool = Form(False),
    cover_image: Optional[UploadFile] = File(None),
    zip_file: Optional[UploadFile] = File(None)
):
    try:
        temp_dir = tempfile.mkdtemp()
        
        headers = {
            "Authorization": f"Token {token}" if not token.startswith("Token ") else token
        }
        
        files_to_update = []
        
        row_url = f"https://api.baserow.io/api/database/rows/table/{table_id}/{row_id}/?user_field_names=true"
        
        # Opcional: manter imagens existentes
        if append_to_existing:
            row_resp = requests.get(row_url, headers=headers)
            if row_resp.status_code == 200:
                existing_files = row_resp.json().get(field_name, [])
                if isinstance(existing_files, list):
                    files_to_update = [{"name": f["name"]} for f in existing_files if "name" in f]
        
        uploaded_files_info = []
        errors = []
        url_upload = "https://api.baserow.io/api/user-files/upload-file/"
        
        # Upload cover_image
        if cover_image:
            file_path = os.path.join(temp_dir, cover_image.filename)
            with open(file_path, "wb") as f:
                f.write(await cover_image.read())
                
            mime_type, _ = mimetypes.guess_type(file_path)
            with open(file_path, "rb") as arquivo:
                baserow_files = {"file": (cover_image.filename, arquivo, mime_type or "application/octet-stream")}
                r = requests.post(url_upload, headers=headers, files=baserow_files)
                
            if r.status_code == 200:
                resp_json = r.json()
                files_to_update.append({"name": resp_json["name"]})
                uploaded_files_info.append(resp_json)
            else:
                errors.append({"filename": cover_image.filename, "error": r.text})
                
        # Upload zip_file
        if zip_file:
            zip_path = os.path.join(temp_dir, zip_file.filename)
            with open(zip_path, "wb") as f:
                f.write(await zip_file.read())
                
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                
            extracted_files_list = []
            for root, _, extracted_files in os.walk(extract_dir):
                for filename in extracted_files:
                    if filename.startswith('.') or "__MACOSX" in root:
                        continue
                    extracted_files_list.append(os.path.join(root, filename))
            
            extracted_files_list.sort()
            
            for file_path in extracted_files_list:
                filename = os.path.basename(file_path)
                mime_type, _ = mimetypes.guess_type(file_path)
                
                with open(file_path, "rb") as arquivo:
                    baserow_files = {"file": (filename, arquivo, mime_type or "application/octet-stream")}
                    r = requests.post(url_upload, headers=headers, files=baserow_files)
                    
                if r.status_code == 200:
                    resp_json = r.json()
                    files_to_update.append({"name": resp_json["name"]})
                    uploaded_files_info.append(resp_json)
                else:
                    errors.append({"filename": filename, "error": r.text})

        # Update row na tabela
        patch_headers = headers.copy()
        patch_headers["Content-Type"] = "application/json"
        
        patch_payload = {
            field_name: files_to_update
        }
        
        patch_resp = requests.patch(row_url, headers=patch_headers, json=patch_payload)
        
        shutil.rmtree(temp_dir)
        
        if patch_resp.status_code == 200:
            return {
                "success": True,
                "row": patch_resp.json(),
                "uploaded_files": uploaded_files_info,
                "errors": errors
            }
        else:
            return {
                "success": False,
                "error": f"Failed to update row (Status {patch_resp.status_code})",
                "details": patch_resp.text,
                "uploaded_files": uploaded_files_info,
                "errors": errors
            }

    except Exception as e:
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return {"error": str(e)}



@app.post("/html-to-image")
async def html_to_image_endpoint(
    background_tasks: BackgroundTasks,
    html: str = Form(...),
    css: str = Form(...),
    width: int = Form(1080),
    height: int = Form(1920)
):
    temp_dir = tempfile.mkdtemp()
    try:
        output_filename = "rendered_image.png"
        output_path = os.path.join(temp_dir, output_filename)
        
        await run_in_threadpool(
            html_img_engine.generate_image_from_html,
            html=html,
            css=css,
            width=width,
            height=height,
            output_path=Path(output_path)
        )
        
        if not os.path.exists(output_path):
             shutil.rmtree(temp_dir)
             return {"error": "HTML rendering failed (no output file created)"}

        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            output_path, 
            media_type="image/png", 
            filename=output_filename
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

class HtmlImageItem(BaseModel):
    html: str
    css: str

class BatchHtmlImageRequest(BaseModel):
    width: int = 1080
    height: int = 1920
    create_first_image: bool = False
    Images: List[HtmlImageItem]

@app.post("/batch-html-to-image")
async def batch_html_to_image_endpoint(
    background_tasks: BackgroundTasks,
    request: BatchHtmlImageRequest
):
    temp_dir = tempfile.mkdtemp()
    try:
        images_data = []
        
        for idx, img_data in enumerate(request.Images):
            # O default é não criar a primeira imagem (idx == 0)
            if idx == 0 and not request.create_first_image:
                continue
                
            output_filename = f"image_{idx + 1}.png"
            output_path = os.path.join(temp_dir, output_filename)
            
            await run_in_threadpool(
                html_img_engine.generate_image_from_html,
                html=img_data.html,
                css=img_data.css,
                width=request.width,
                height=request.height,
                output_path=Path(output_path)
            )
            
            if os.path.exists(output_path):
                images_data.append((output_filename, output_path))
            else:
                shutil.rmtree(temp_dir)
                return {"error": f"Failed to generate {output_filename}"}
                
        # Criação do arquivo zip contendo todas as imagens
        zip_filename = "batch_images.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for fname, filepath in images_data:
                zf.write(filepath, arcname=fname)
                
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            zip_path, 
            media_type="application/zip", 
            filename=zip_filename
        )

    except Exception as e:
        shutil.rmtree(temp_dir)
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=80)