import replicate
import os
import requests
from pathlib import Path

# Ensure token is set from Easypanel variable
if "MUSIC_API_TOKEN" in os.environ:
    os.environ["REPLICATE_API_TOKEN"] = os.environ["MUSIC_API_TOKEN"]

# Default to the one provided if not set (fallback, but ideally should be env only)
# Removing hardcoded token to avoid git push rejection (Secret Scanning)
if "REPLICATE_API_TOKEN" not in os.environ:
    print("WARNING: REPLICATE_API_TOKEN or MUSIC_API_TOKEN not set in environment.")

# Use variable for model version, fallback to default
DEFAULT_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"
MODEL_VERSION = os.environ.get("MUSIC_MODEL_VERSION", DEFAULT_MODEL)

def generate_music(prompt: str, duration: int, output_path: Path) -> Path:
    """
    Generates music using Replicate's MusicGen model.
    """
    print(f"🎵 Starting music generation for prompt: '{prompt}' ({duration}s)")
    
    try:
        output = replicate.run(
            MODEL_VERSION,
            input={
                "prompt": prompt,
                "model_version": "stereo-large",
                "duration": duration,
                "output_format": "mp3"
            }
        )
        
        # replicate returns a string URL or list of URLs
        audio_url = output[0] if isinstance(output, list) else output
        print(f"✅ Generated! URL: {audio_url}")
        
        print("⬇️ Downloading file...")
        response = requests.get(audio_url)
        response.raise_for_status()
        
        with open(output_path, "wb") as file:
            file.write(response.content)
            
        print(f"🎉 Saved to {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ Error generating music: {e}")
        raise RuntimeError(f"Music generation failed: {e}") from e
