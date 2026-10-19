import os
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).parent / "fonts"


def resolve_fonts(profile="auto"):
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    original = (
        Path(os.environ.get("VIDEO_EDITING_SERIF_FONT", str(windows / "BASKVILL.TTF"))),
        Path(os.environ.get("VIDEO_EDITING_SANS_FONT", str(windows / "segoeui.ttf"))),
    )
    available = all(p.is_file() for p in original)
    if profile == "original" and not available:
        raise ValueError("Baskerville/Segoe UI indisponiveis. Configure VIDEO_EDITING_SERIF_FONT e VIDEO_EDITING_SANS_FONT ou use open.")
    if profile != "open" and available:
        paths = original
    else:
        paths = (ROOT / "LibreBaskerville.ttf", ROOT / "SourceSans3.ttf")
    names = tuple(ImageFont.truetype(str(path), 24).getname()[0] for path in paths)
    return paths, names


def font_info():
    result = {}
    for profile in ("auto", "original", "open"):
        try:
            _, names = resolve_fonts(profile)
            result[profile] = {"available": True, "serif": names[0], "sans": names[1]}
        except (ValueError, OSError):
            result[profile] = {"available": False}
    return result
