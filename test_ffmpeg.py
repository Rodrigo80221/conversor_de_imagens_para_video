import os
from pathlib import Path
import subprocess
from video_engine import merge_video_audio

def create_dummy_media():
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1", "-c:v", "libx264", "vid.mp4"])
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=3", "-c:a", "pcm_s16le", "narr.wav"])
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-c:a", "libmp3lame", "bg.mp3"])

create_dummy_media()
try:
    merge_video_audio(
        video_input=Path("vid.mp4"),
        output_file=Path("out.mp4"),
        narration_input=Path("narr.wav"),
        background_input=Path("bg.mp3"),
        vol_narration=1.0,
        vol_background=1.0,
        fade_duration=1.0
    )
    print("Success")
except Exception as e:
    print("Error:", str(e))
