import video_engine
import shutil
import json
from pathlib import Path
import os

def test_engine():
    # Setup temp dir
    test_dir = Path("test_video_gen")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()

    # Copy image (using the one currently in the brain dir, I'll need to know the path or just create a dummy one if I can't access it easily, but I have the path from metadata)
    # Actually, I'll just create a dummy image using ffmpeg if possible, or assume the user has images. 
    # Let's try to copy the uploaded image if valid, otherwise create a colored square.
    
    # Path provided in prompt metadata: 
    # C:/Users/rodri/.gemini/antigravity/brain/bd73b97b-06cb-4200-8b29-1c8fb46ee482/uploaded_image_1769084052835.png
    src_img = Path("C:/Users/rodri/.gemini/antigravity/brain/bd73b97b-06cb-4200-8b29-1c8fb46ee482/uploaded_image_1769084052835.png")
    
    img0 = test_dir / "image_0.png"
    img1 = test_dir / "image_1.png"
    
    if src_img.exists():
        shutil.copy(src_img, img0)
        shutil.copy(src_img, img1)
    else:
        print("Source image not found, generating dummy images with ffmpeg...")
        # Generate red and blue images
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=0.1", "-frames:v", "1", str(img0)], check=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=0.1", "-frames:v", "1", str(img1)], check=True)

    # Config from user prompt
    config = {
      "video": {
        "resolution": "1080x1920",
        "fps": 30
      },
      "timeline": {
        "images": [
          {
            "id": "image_0",
            "image_file": "image_0.png",
            "duration_seconds": 2,
            "effect": { "type": "zoom_slow" },
            "transition_to_next": { "type": "xfade", "duration": 0.5 }
          },
          {
             "id": "image_1",
             "image_file": "image_1.png",
             "duration_seconds": 2,
             "effect": { "type": "fade" }
          }
        ]
      }
    }

    output_file = test_dir / "output.mp4"
    
    print("Starting video generation...")
    video_engine.generate_video_from_config(config, test_dir, output_file)
    
    if output_file.exists():
        print(f"SUCCESS: Video generated at {output_file}")
        print(f"Size: {output_file.stat().st_size} bytes")
    else:
        print("FAILURE: Output file not found.")

if __name__ == "__main__":
    test_engine()
