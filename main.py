from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
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
    file: UploadFile = File(...)
):
    try:
        config_data = json.loads(config)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in 'config' field"}

    # Create temp dir
    temp_dir = tempfile.mkdtemp()
    
    try:
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=80)