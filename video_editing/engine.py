"""Only the operations used by the Paris short; no shell/filter input from clients."""
import math

from PIL import Image, ImageDraw, ImageFont

from .fonts import resolve_fonts
from .media import ffmpeg, run


def overlay(recipe, shot, output):
    w, h = recipe.width, recipe.height
    scale = w / 1080
    paths, _ = resolve_fonts(recipe.typography.font_profile)
    im = Image.new("RGBA", (w, h))
    dr = ImageDraw.Draw(im)

    def text(x, y, value, size, sans=False, anchor=None, width=0.84):
        if not value:
            return
        pixel_size = max(8, round(size * scale))
        font = ImageFont.truetype(str(paths[int(sans)]), pixel_size)
        while dr.textbbox((0, 0), value, font=font)[2] > w * width and pixel_size > 8:
            pixel_size -= 1
            font = ImageFont.truetype(str(paths[int(sans)]), pixel_size)
        dr.text((x * w, y * h), value, font=font, anchor=anchor,
                fill=(255, 250, 240, 245), stroke_width=max(0, round(scale)),
                stroke_fill=(0, 0, 0, 35))

    for y in range(round(h * 0.677), h):
        dr.line((0, y, w, y), fill=(0, 0, 0, round(90 * (y / h - 0.677) / 0.323)))
    typ = recipe.typography
    if shot.caption:
        dr.line((w * .078, h * .776, w * .126, h * .776), fill=(227, 205, 161, 235), width=max(1, round(3 * scale)))
        text(.078, .791, shot.caption, typ.caption_size)
        text(.081, .833, shot.kicker, typ.small_size, sans=True)
    if shot.title:
        text(.5, .401, shot.title, typ.title_size, anchor="mm")
        dr.line((w * .409, h * .448, w * .591, h * .448), fill=(227, 205, 161, 255), width=max(1, round(2 * scale)))
        text(.5, .477, shot.subtitle, typ.small_size, sans=True, anchor="mm")
    text(.5, .661, shot.closing, typ.caption_size, anchor="mm")
    im.save(output)


def validate_assets(recipe, assets):
    resolve_fonts(recipe.typography.font_profile)
    warnings = []
    for i, shot in enumerate(recipe.shots):
        a = assets[shot.asset_id]
        if a["kind"] == "image":
            if shot.start != 0 or shot.speed != 1:
                raise ValueError(f"Cena {i + 1}: fotos exigem start=0 e speed=1; use photo_zoom.")
        else:
            if shot.start + shot.duration * shot.speed > a["duration"] + 1 / recipe.fps:
                raise ValueError(f"Cena {i + 1}: o trecho ultrapassa a duracao do video.")
            if a["color_transfer"] in ("smpte2084", "arib-std-b67"):
                raise ValueError(f"Cena {i + 1}: HDR ainda nao e suportado; converta para SDR antes.")
            if not a["has_audio"] and shot.audio == "original" and recipe.audio == "original":
                warnings.append(f"Cena {i + 1}: arquivo sem audio; sera usado silencio.")
    return warnings


def encode_args(recipe):
    return ["-c:v", "libx264", "-preset", "fast", "-crf", str(recipe.crf), "-threads", "2",
            "-pix_fmt", "yuv420p", "-r", str(recipe.fps), "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-ac", "2", "-map_metadata", "-1", "-video_track_timescale", "15360"]


def render_clip(recipe, shot, asset, folder, n, cancel):
    w, h, fps, dur = recipe.width, recipe.height, recipe.fps, shot.duration
    card = folder / f"overlay_{n:03}.png"
    overlay(recipe, shot, card)
    args = [ffmpeg(), "-v", "error", "-y", "-threads", "2"]
    source = str(asset["path"])
    if asset["kind"] == "image":
        args += ["-loop", "1", "-framerate", str(fps), "-i", source]
        frames = max(1, round(dur * fps) - 1)
        base = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
                f"crop={w*2}:{h*2}:(iw-ow)*{shot.crop_x}:(ih-oh)*{shot.crop_y},"
                f"zoompan=z='1+{shot.photo_zoom-1}*on/{frames}':"
                f"x='(iw-iw/zoom)*{shot.crop_x}':y='(ih-ih/zoom)*{shot.crop_y}':d=1:s={w}x{h}:fps={fps}")
    else:
        args += ["-ss", str(shot.start), "-t", str(dur * shot.speed + .1), "-i", source]
        base = (f"setpts=(PTS-STARTPTS)/{shot.speed},"
                f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}:(iw-ow)*{shot.crop_x}:(ih-oh)*{shot.crop_y},fps={fps},"
                "tpad=stop_mode=clone:stop_duration=0.1")
    args += ["-i", str(card), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    g = recipe.grade
    base += (f",setsar=1,eq=contrast={g.contrast}:brightness={g.brightness}:saturation={g.saturation},"
             f"colorbalance=rs={g.red_shadows}:bs={g.blue_shadows}:rh={g.red_highlights}:bh={g.blue_highlights},format=yuv420p")
    filters = f"[0:v]{base}[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p"
    if n == 0 and recipe.fade_in:
        filters += f",fade=t=in:st=0:d={recipe.fade_in}"
    if n == len(recipe.shots)-1 and recipe.fade_out:
        filters += f",fade=t=out:st={dur-recipe.fade_out}:d={recipe.fade_out}"
    filters += "[v];"
    original = (recipe.audio == "original" and shot.audio == "original" and asset["has_audio"])
    if original:
        filters += f"[0:a:0]asetpts=PTS-STARTPTS,atempo={shot.speed},aresample=48000,apad,atrim=duration={dur}"
    else:
        filters += f"[2:a]atrim=duration={dur},asetpts=PTS-STARTPTS"
    filters += f",afade=t=in:d=0.012,afade=t=out:st={dur-.025}:d=0.025[a]"
    raw = folder / f"raw_{n:03}.mp4"
    dest = folder / f"clip_{n:03}.mp4"
    args += ["-filter_complex_threads", "1", "-filter_complex", filters, "-map", "[v]", "-map", "[a]",
             "-t", str(dur), *encode_args(recipe), str(raw)]
    run(args, cancel)
    # FFmpeg can retain an input display matrix after autorotation + overlay.
    # Remux explicitly removes it without re-encoding the upright pixels.
    run([ffmpeg(), "-v", "error", "-y", "-display_rotation", "0", "-i", str(raw),
         "-c", "copy", str(dest)], cancel)
    raw.unlink()
    return dest


def render(recipe, assets, folder, cancel, progress):
    clips = []
    for i, shot in enumerate(recipe.shots):
        progress(.8 * i / len(recipe.shots), f"Renderizando cena {i+1}/{len(recipe.shots)}")
        clips.append(render_clip(recipe, shot, assets[shot.asset_id], folder, i, cancel))
    groups = []
    current, length = clips[0], recipe.shots[0].duration
    for i in range(len(clips)-1):
        tr = recipe.shots[i].transition_to_next
        if tr.type == "cut":
            groups.append(current)
            current, length = clips[i+1], recipe.shots[i+1].duration
        else:
            dest = folder / f"dissolve_{i:03}.mp4"
            length_next = length + recipe.shots[i+1].duration - tr.duration
            filters = (f"[0:v]settb=AVTB,setpts=PTS-STARTPTS[a];[1:v]settb=AVTB,setpts=PTS-STARTPTS[b];"
                       f"[a][b]xfade=transition=fade:duration={tr.duration}:offset={length-tr.duration},format=yuv420p[v];"
                       f"[0:a]atrim=duration={length},asetpts=PTS-STARTPTS[a0];"
                       f"[1:a]atrim=duration={recipe.shots[i+1].duration},asetpts=PTS-STARTPTS[a1];"
                       f"[a0][a1]acrossfade=d={tr.duration}:c1=tri:c2=tri[a]")
            run([ffmpeg(), "-v", "error", "-y", "-threads", "2", "-i", str(current),
                 "-threads", "2", "-i", str(clips[i+1]), "-filter_complex_threads", "1",
                 "-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-t", str(length_next),
                 *encode_args(recipe), str(dest)], cancel)
            current, length = dest, length_next
        progress(.8 + .15 * (i+1) / max(1, len(clips)-1), "Montando transicoes")
    groups.append(current)
    # Generated numeric basenames avoid quoting/path injection in the concat list.
    concat = folder / "concat.txt"
    concat.write_text("\n".join(f"file '{p.name}'" for p in groups), encoding="utf-8")
    output = folder / "result.mp4"
    audio_args = ["-an"] if recipe.audio == "mute" else ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    run([ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", str(concat),
         "-map", "0:v:0", "-c:v", "copy", *audio_args, "-t", str(recipe.duration),
         "-movflags", "+faststart", str(output)], cancel)
    progress(.98, "Validando arquivo final")
    return output


def contact_sheet(asset, times, folder):
    paths, _ = resolve_fonts("open")
    font = ImageFont.truetype(str(paths[1]), 20)
    cols = min(4, len(times))
    sheet = Image.new("RGB", (cols * 240, math.ceil(len(times) / cols) * 360), "#161b20")
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(times):
        frame = folder / f"frame_{i}.jpg"
        run([ffmpeg(), "-v", "error", "-y", "-ss", str(t), "-i", str(asset["path"]),
             "-frames:v", "1", "-vf", "scale=232:316:force_original_aspect_ratio=decrease", str(frame)], timeout=45)
        with Image.open(frame) as image:
            x, y = (i % cols) * 240, (i // cols) * 360
            sheet.paste(image, (x + (240 - image.width)//2, y + (320 - image.height)//2))
            draw.text((x+8, y+329), f"{t:.2f}s", font=font, fill="white")
    result = folder / "preview.jpg"
    sheet.save(result, quality=90)
    return result
