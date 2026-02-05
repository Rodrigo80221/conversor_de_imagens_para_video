import subprocess
import json
from pathlib import Path

def get_video_dimensions(fpath: Path):
    print(f"Testing on: {fpath}")
    try:
        cmd = [
            "ffprobe", "-v", "error", 
            "-select_streams", "v:0",
            # This is the line I suspect might be fragile
            "-show_entries", "stream=width,height,avg_frame_rate:stream_tags=rotate:stream_side_data_list=rotation", 
            "-of", "json", 
            str(fpath)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Raw FFprobe Output:", result.stdout)
        
        data = json.loads(result.stdout)
        
        if not data.get("streams"):
             print("No streams found")
             return 0, 0
             
        stream = data["streams"][0]
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        
        print(f"Base Dims: {width}x{height}")
        
        # Check rotation
        rotation = 0
        
        # Check tags
        tags = stream.get("tags", {})
        if "rotate" in tags:
            try:
                rotation = int(tags["rotate"])
            except:
                pass
        
        print(f"Tags Rotation: {tags.get('rotate')}")
                
        # Check side data (sometimes rotation is here)
        if rotation == 0 and "side_data_list" in stream:
            for sd in stream["side_data_list"]:
                print(f"Side Data found: {sd}")
                if "rotation" in sd:
                    try:
                         rotation = int(sd["rotation"])
                    except:
                        pass
        
        # Normalize rotation
        rotation = rotation % 360
        print(f"Final Rotation: {rotation}")
        
        # Swap if 90 or 270 (vertical)
        if rotation == 90 or rotation == 270:
            print("Swapping dimensions due to rotation")
            return height, width
            
        return width, height
        
    except Exception as e:
        print(f"Error getting video dimensions: {e}")
        return 1080, 1920 # Fallback default

if __name__ == "__main__":
    w, h = get_video_dimensions(Path("dummy_video.mp4"))
    print(f"Result: {w}x{h}")
    
    vertical_pos = 0
    margin_v = int((h / 2) + vertical_pos)
    print(f"Simulating vertical_pos={vertical_pos} => MarginV={margin_v}")
    
    vertical_pos = -900
    margin_v = int((h / 2) + vertical_pos)
    print(f"Simulating vertical_pos={vertical_pos} => MarginV={margin_v}")
