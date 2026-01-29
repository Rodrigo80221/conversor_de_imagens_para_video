from pathlib import Path
import video_engine
import os

def test_autogen():
    print("Testing Autogen Subtitles...")
    audio_path = Path("dummy_narration.wav")
    if not audio_path.exists():
        print("dummy_narration.wav not found. Please run verify_engine.py first or provide a file.")
        # Try to creat using verify_engine approach if module allows, or just fail
        return

    output_srt = Path("test_autogen.srt")
    if output_srt.exists():
        os.remove(output_srt)

    try:
        print("Calling generate_subtitles...")
        # Reduce words per line to 2 to see effect easily
        video_engine.generate_subtitles(audio_path, output_srt, words_per_line=2, model_size="tiny") 
        # Use tiny model for speed in verification if possible, 
        # though function default is medium. verify_engine doesn't expose model_size, so I need to check if I added it.
        # I added model_size param in my edit? Let me check my own edit.
        # Yes: def generate_subtitles(..., model_size: str = "medium"):
        
        if output_srt.exists():
           print(f"SUCCESS: {output_srt} created.")
           print("Content:")
           print(output_srt.read_text(encoding="utf-8"))
        else:
           print("FAILURE: SRT file not created.")
           
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_autogen()
