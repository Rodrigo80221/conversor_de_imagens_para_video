from pathlib import Path
import video_engine
import os

def test_autogen():
    print("Testing Autogen Subtitles...")
    audio_path = Path("dummy_narration.wav")
    if not audio_path.exists():
        print("dummy_narration.wav not found. Please run verify_engine.py first or provide a file.")
        return

    try:
        print("Calling generate_subtitles...")
        # Reduce words per line to 2 to see effect easily
        # Now it returns a string and output_srt_path is optional
        srt_content = video_engine.generate_subtitles(audio_path, output_srt_path=None, words_per_line=2, model_size="tiny")
        
        if srt_content:
           print(f"SUCCESS: Subtitles generated (length {len(srt_content)} chars).")
           print("Content:")
           print(srt_content)
        else:
           print("FAILURE: SRT content empty.")
           
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_autogen()
