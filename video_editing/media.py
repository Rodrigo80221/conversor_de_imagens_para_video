import json
import os
import subprocess
import threading
import time
from pathlib import Path


class Cancelled(Exception):
    pass


def run(args, cancel=None, timeout=900):
    """Bounded subprocess with cancellation and disk-backed diagnostics."""
    import tempfile
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise Cancelled()
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(args, stdout=log, stderr=log)
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if cancel.wait(0.1):
                    raise Cancelled()
                if time.monotonic() > deadline:
                    raise RuntimeError("Processamento excedeu o tempo limite.")
            if proc.returncode:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 4000))
                raise RuntimeError(log.read().decode("utf-8", errors="replace"))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def ffmpeg():
    return os.environ.get("VIDEO_EDITING_FFMPEG", "ffmpeg")


def probe(path):
    command = [os.environ.get("VIDEO_EDITING_FFPROBE", "ffprobe"), "-v", "error",
               "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,image2,png_pipe,jpeg_pipe",
               "-show_streams", "-show_format", "-of", "json", str(path)]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=30, check=True)
        data = json.loads(proc.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
    except (subprocess.SubprocessError, StopIteration, json.JSONDecodeError) as exc:
        raise ValueError("Arquivo sem imagem/video valido ou nao suportado pelo FFmpeg.") from exc
    rotation = next((s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s), 0)
    rotation = int(rotation or video.get("tags", {}).get("rotate", 0))
    width, height = video["width"], video["height"]
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {"width": width, "height": height, "rotation": rotation,
            "duration": float(data.get("format", {}).get("duration", video.get("duration", 0))),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
            "color_transfer": video.get("color_transfer", "unknown"),
            "codec": video["codec_name"]}


def normalize_image(source, target):
    from PIL import Image, ImageOps
    if source.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError as exc:
            raise ValueError("Instale pillow-heif para importar HEIC/HEIF.") from exc
    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im)
        im.load()
        # Resolve alpha against black instead of silently dropping it.
        rgba = im.convert("RGBA")
        result = Image.new("RGBA", im.size, "black")
        result.alpha_composite(rgba)
        result.convert("RGB").save(target)
        return {"width": im.width, "height": im.height, "rotation": 0,
                "duration": 0, "has_audio": False, "color_transfer": "srgb", "codec": "png"}
