import subprocess
import json
from pathlib import Path
from typing import Dict, List, Tuple

COMMON_EXTS = [".png", ".jpg", ".jpeg", ".webp"]

def find_image_file(item: Dict, base_dir: Path) -> Path:
    if "image_file" in item and item["image_file"]:
        p = base_dir / item["image_file"]
        if p.exists():
            return p
        raise FileNotFoundError(f"image_file não encontrado: {p}")

    img_id = item.get("id", "")
    if not img_id:
        raise ValueError("Item sem 'id'.")

    p = base_dir / img_id
    if p.exists():
        return p

    for ext in COMMON_EXTS:
        p = base_dir / f"{img_id}{ext}"
        if p.exists():
            return p

    raise FileNotFoundError(
        f"Não encontrei arquivo para '{img_id}'. "
        f"Nomeie como img01.png/.jpg etc, ou use 'image_file' no JSON."
    )

def get_video_settings(cfg: Dict) -> Tuple[int, int, int]:
    res = cfg.get("video", {}).get("resolution", "1080x1920")
    fps = int(cfg.get("video", {}).get("fps", 30))
    try:
        w, h = res.lower().split("x")
        return int(w), int(h), fps
    except Exception:
        raise ValueError(f"resolution inválida: {res} (ex: '1080x1920')")

def effect_filter(effect: Dict, w: int, h: int, fps: int, duration: float) -> str:
    etype = (effect or {}).get("type", "none")
    base = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"

    if etype == "none":
        return f"{base},fps={fps},format=yuv420p"

    if etype == "zoom_slow":
        zs = float(effect.get("zoom_start", 1.0))
        ze = float(effect.get("zoom_end", 1.15))
        step = float(effect.get("zoom_step", 0.0015))
        frames = max(1, int(round(duration * fps)))

        return (
            f"{base},"
            f"zoompan=z='if(eq(on,0),{zs},min(zoom+{step},{ze}))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        )

    if etype == "fade":
        fin = effect.get("fade_in", {}) or {}
        fout = effect.get("fade_out", {}) or {}
        st_in = float(fin.get("start_time", 0.0))
        d_in = float(fin.get("duration", 0.5))
        st_out = float(fout.get("start_time", max(0.0, duration - 0.5)))
        d_out = float(fout.get("duration", 0.5))
        return (
            f"{base},fps={fps},"
            f"fade=t=in:st={st_in}:d={d_in},"
            f"fade=t=out:st={st_out}:d={d_out},"
            f"format=yuv420p"
        )

    if etype == "slide_horizontal":
        direction = effect.get("direction", "left_to_center")
        wide_w = int(w * 2)

        if direction == "left_to_center":
            x_expr = f"(t/{duration})*{w/2}"
        elif direction == "right_to_center":
            x_expr = f"{w}-(t/{duration})*{w/2}"
        elif direction == "right_to_left":
            x_expr = f"{w}-(t/{duration})*{w}"
        else:
            x_expr = f"(t/{duration})*{w}"

        return (
            f"scale={wide_w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:x='{x_expr}':y=0,"
            f"fps={fps},format=yuv420p"
        )

    if etype == "slide_vertical":
        direction = effect.get("direction", "bottom_to_top")
        tall_h = int(effect.get("source_scale_height", int(h * 1.25)))
        delta = max(1, tall_h - h)

        if direction == "bottom_to_top":
            y_expr = f"{delta}-(t/{duration})*{delta}"
        elif direction == "top_to_bottom":
            y_expr = f"(t/{duration})*{delta}"
        else:
            y_expr = f"{delta}-(t/{duration})*{delta}"

        return (
            f"scale={w}:{tall_h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:x=0:y='{y_expr}',"
            f"fps={fps},format=yuv420p"
        )

    return f"{base},fps={fps},format=yuv420p"

def build_ffmpeg_command(cfg: Dict, base_dir: Path, out_path: Path) -> List[str]:
    w, h, fps = get_video_settings(cfg)

    images = cfg.get("timeline", {}).get("images", [])
    if not images:
        raise ValueError("JSON sem timeline.images")

    images = sorted(images, key=lambda x: int(x.get("order", 9999)))

    input_files: List[Path] = []
    durations: List[float] = []
    transitions: List[Dict] = []

    for item in images:
        input_files.append(find_image_file(item, base_dir))
        durations.append(float(item.get("duration_seconds", 5)))
        transitions.append(item.get("transition_to_next", {}) or {})

    cmd = ["ffmpeg", "-y"]

    for img_file, dur in zip(input_files, durations):
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", str(img_file)]

    fc_parts: List[str] = []
    labels: List[str] = []

    for i, item in enumerate(images):
        eff = item.get("effect", {}) or {"type": "none"}
        dur = durations[i]

        vf = effect_filter(eff, w, h, fps, dur)

        out_label = f"v{i}"
        fc_parts.append(
            f"[{i}:v]{vf},trim=duration={dur},setpts=PTS-STARTPTS[{out_label}]"
        )
        labels.append(out_label)

    current = labels[0]
    current_len = durations[0]

    for i in range(0, len(labels) - 1):
        t = transitions[i] or {}
        ttype = t.get("type", "xfade")

        if ttype == "none":
            trans = "fade"
            td = 0.0
        else:
            trans = t.get("transition", "fade")
            td = float(t.get("duration", 0.5))

        offset = max(0.0, current_len - td)

        next_label = labels[i + 1]
        out_label = f"x{i}"

        fc_parts.append(
            f"[{current}][{next_label}]"
            f"xfade=transition={trans}:duration={td}:offset={offset},"
            f"format=yuv420p[{out_label}]"
        )

        current_len = current_len + durations[i + 1] - td
        current = out_label

    filter_complex = ";".join(fc_parts)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{current}]",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    return cmd

def generate_video_from_config(cfg: Dict, base_dir: Path, output_file: Path):
    cmd = build_ffmpeg_command(cfg, base_dir, output_file)
    print("Running ffmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=True)
