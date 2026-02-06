from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from typing import Optional
from enum import Enum
from fastapi.responses import FileResponse
import uvicorn
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
from starlette.concurrency import run_in_threadpool

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Online", "message": "API de Video/Audio rodando no Easypanel!"}

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
    output_name: str = Form("video_subbed")
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
            font_size=font_size
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

if __name__ == "__main__":

    uvicorn.run(app, host="0.0.0.0", port=80)