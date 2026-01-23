import video_engine
from pathlib import Path
import subprocess
import os

def create_dummy_assets():
    # Create dummy video (2 seconds, red)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=30", 
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", 
        "-c:v", "libx264", "-c:a", "aac", "dummy_video.mp4"
    ], check=True)
    
    # Create dummy narration (1 second)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", 
        "dummy_narration.wav"
    ], check=True)
    
    # Create dummy background (3 seconds)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", 
        "dummy_background.mp3"
    ], check=True)

def test_merge_full():
    print("Testing Merge Full...")
    create_dummy_assets()
    
    output = Path("output_full.mp4")
    if output.exists():
        os.remove(output)
        
    video_engine.merge_video_audio(
        video_input=Path("dummy_video.mp4"),
        output_file=output,
        narration_input=Path("dummy_narration.wav"),
        background_input=Path("dummy_background.mp3"),
        vol_narration=0.8,
        vol_background=0.2,
        fade_duration=0.5
    )
    
    if output.exists() and output.stat().st_size > 0:
        print("SUCCESS: output_full.mp4 created.")
    else:
        print("FAILURE: output_full.mp4 not created.")

def test_merge_no_narration():
    print("\nTesting Merge No Narration (Video + BG)...")
    output = Path("output_bg.mp4")
    if output.exists():
        os.remove(output)
        
    video_engine.merge_video_audio(
        video_input=Path("dummy_video.mp4"),
        output_file=output,
        narration_input=None,
        background_input=Path("dummy_background.mp3"),
        vol_background=0.2,
        fade_duration=0.5
    )
    
    if output.exists() and output.stat().st_size > 0:
        print("SUCCESS: output_bg.mp4 created.")
    else:
        print("FAILURE: output_bg.mp4 not created.")

if __name__ == "__main__":
    try:
        test_merge_full()
        test_merge_no_narration()
    except Exception as e:
        print(f"ERROR: {e}")
