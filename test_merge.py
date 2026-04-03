from pathlib import Path
from video_engine import merge_video_audio
import traceback

try:
    merge_video_audio(
        video_input=Path(r"C:\Users\rodri\Downloads\video.mp4"),
        output_file=Path(r"C:\Users\rodri\Downloads\output_test.mp4"),
        narration_input=Path(r"C:\Users\rodri\Downloads\narration.wav"),
        background_input=Path(r"C:\Users\rodri\Downloads\background-music.mp3"),
        vol_narration=1.0,
        vol_background=1.0,
        fade_duration=2.0
    )
    print("Success: Generated C:\\Users\\rodri\\Downloads\\output_test.mp4")
except Exception as e:
    print("Error:")
    traceback.print_exc()
