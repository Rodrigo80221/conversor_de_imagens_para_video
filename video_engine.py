import subprocess

import json

from pathlib import Path

from typing import Dict, List, Tuple, Optional

import wave

import contextlib

import whisper

import warnings

import math

import json

import re

import textwrap



COMMON_EXTS = [".png", ".jpg", ".jpeg", ".webp"]



def find_image_file(item: Dict, base_dir: Path) -> Path:
    if "image_file" in item and item["image_file"]:
        p = base_dir / item["image_file"]
        if p.exists():
            return p
            
        base_name = Path(item["image_file"]).stem
        for ext in COMMON_EXTS:
            p_ext = base_dir / f"{base_name}{ext}"
            if p_ext.exists():
                return p_ext

        raise FileNotFoundError(f"image_file não encontrado: {p}")

    img_id = item.get("id", "")
    if not img_id:
        raise ValueError("Item sem 'id'.")

    p = base_dir / img_id
    if p.exists():
        return p
        
    img_id_base = Path(img_id).stem
    for ext in COMMON_EXTS:
        p_ext = base_dir / f"{img_id_base}{ext}"
        if p_ext.exists():
            return p_ext

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



def effect_filter(effect: Dict, w: int, h: int, fps: int, duration: float, idx: int = 0) -> str:

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

        if direction in ("left_to_center", "left_to_right"):
            mask_expr = f"clip(((T/{duration})*1.5 - X/W)*2, 0, 1)"
        else: # "right_to_center", "right_to_left"
            mask_expr = f"clip(((T/{duration})*1.5 - (1-X/W))*2, 0, 1)"

        return (
            f"{base},"
            f"geq=lum='p(X,Y)*{mask_expr}':cb='(p(X,Y)-128)*{mask_expr}+128':cr='(p(X,Y)-128)*{mask_expr}+128',"
            f"fps={fps},format=yuv420p"
        )



    if etype == "slide_vertical":
        direction = effect.get("direction", "bottom_to_top")

        if direction == "top_to_bottom":
            mask_expr = f"clip(((T/{duration})*1.5 - Y/H)*2, 0, 1)"
        else: # "bottom_to_top"
            mask_expr = f"clip(((T/{duration})*1.5 - (1-Y/H))*2, 0, 1)"

        return (
            f"{base},"
            f"geq=lum='p(X,Y)*{mask_expr}':cb='(p(X,Y)-128)*{mask_expr}+128':cr='(p(X,Y)-128)*{mask_expr}+128',"
            f"fps={fps},format=yuv420p"
        )



    if etype == "pan":
        direction = effect.get("direction", "left_to_right")
        speed = float(effect.get("speed", 10))
        extra_w = int(speed * duration)
        wide_w = w + extra_w
        s_base = f"scale={wide_w}:{h}:force_original_aspect_ratio=increase"
        if direction == "left_to_right":
            x_expr = f"(iw-{w})/2 + {extra_w/2.0} - {speed}*t"
        else:
            x_expr = f"(iw-{w})/2 - {extra_w/2.0} + {speed}*t"
        y_expr = f"(ih-{h})/2"
        return f"{s_base},crop={w}:{h}:x='{x_expr}':y='{y_expr}',fps={fps},format=yuv420p"

    if etype == "parallax_fake":
        bg_speed = float(effect.get("bg_speed", 5))
        fg_speed = float(effect.get("fg_speed", 15))
        blur_val = int(effect.get("blur", 15))
        scale = float(effect.get("scale", 1.15))
        return (
            f"split=2[bg_in_{idx}][fg_in_{idx}];"
            f"[bg_in_{idx}]scale={int(w*scale)}:{int(h*scale)}:force_original_aspect_ratio=increase,crop={int(w*scale)}:{int(h*scale)},boxblur={blur_val},crop={w}:{h}:x='(iw-{w})/2 + {bg_speed}*t':y='(ih-{h})/2'[bg_{idx}];"
            f"[fg_in_{idx}]scale={w}:{h}:force_original_aspect_ratio=decrease[fg_{idx}];"
            f"[bg_{idx}][fg_{idx}]overlay=x='(main_w-overlay_w)/2 + {fg_speed}*t':y='(main_h-overlay_h)/2',"
            f"fps={fps},format=yuv420p"
        )

    if etype == "focus_reveal":
        direction = effect.get("direction", "left_to_right")
        blur_strength = int(effect.get("blur_strength", 12))
        softness = float(effect.get("softness", 0.3))
        mult = 1.0 / max(0.01, softness)
        offset_max = 1.0 + softness
        if direction in ("left_to_center", "left_to_right"):
            mask_expr = f"clip(((T/{duration})*{offset_max} - X/W)*{mult}, 0, 1)"
        else:
            mask_expr = f"clip(((T/{duration})*{offset_max} - (1-X/W))*{mult}, 0, 1)"
        return (
            f"{base},split=2[sharp_in_{idx}][blur_in_{idx}];"
            f"[blur_in_{idx}]boxblur={blur_strength}[bg_{idx}];"
            f"[sharp_in_{idx}]format=yuva420p,geq=a='255*{mask_expr}'[fg_{idx}];"
            f"[bg_{idx}][fg_{idx}]overlay,fps={fps},format=yuv420p"
        )

    if etype == "zoom_pan":
        zs = float(effect.get("zoom_start", 1.0))
        ze = float(effect.get("zoom_end", 1.08))
        direction = effect.get("direction", "left_to_right")
        frames = max(1, int(round(duration * fps)))
        step = (ze - zs) / frames
        if direction == "left_to_right":
            x_expr = f"(1 - on/{frames})*(iw - iw/zoom)"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "right_to_left":
            x_expr = f"(on/{frames})*(iw - iw/zoom)"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "top_to_bottom":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(on/{frames})*(ih - ih/zoom)"
        elif direction == "bottom_to_top":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(1 - on/{frames})*(ih - ih/zoom)"
        else:
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"
            
        return (
            f"{base},"
            f"zoompan=z='if(eq(on,0),{zs},min(zoom+{step},{ze}))':"
            f"x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        )

    if etype == "micro_motion":
        zs, ze = 1.0, 1.03
        frames = max(1, int(round(duration * fps)))
        step = (ze - zs) / frames
        x_expr = f"(iw/2-(iw/zoom/2)) + (on/{frames})*10"
        y_expr = f"(ih/2-(ih/zoom/2)) + (on/{frames})*5"
        return (
            f"{base},"
            f"zoompan=z='if(eq(on,0),{zs},min(zoom+{step},{ze}))':"
            f"x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        )

    if etype == "vignette_motion":
        frames = max(1, int(round(duration * fps)))
        return (
            f"{base},"
            f"zoompan=z='if(eq(on,0),1.0,min(zoom+0.001,1.05))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"vignette=angle='PI/3+sin(t*0.5)*0.1',"
            f"format=yuv420p"
        )

    if etype == "light_sweep":
        width = float(effect.get("width", 0.2))
        intensity = float(effect.get("intensity", 0.3))
        pos_expr = f"(T/{duration})*(1+{width*2}) - {width}"
        mask_expr = f"max(0, 1 - abs(X/W - ({pos_expr}))/{width})"
        lum_expr = f"min(255, p(X,Y) + 255*{intensity}*{mask_expr})"
        return (
            f"{base},"
            f"geq=lum='{lum_expr}',"
            f"fps={fps},format=yuv420p"
        )

    if etype == "focus_pull":
        blur_start = int(effect.get("blur_start", 15))
        blur_end = int(effect.get("blur_end", 0))
        if blur_start > blur_end:
            op_expr = f"t/{duration}"
            bot, top = f"blurry_{idx}", f"sharp_{idx}"
        else:
            op_expr = f"t/{duration}"
            bot, top = f"sharp_{idx}", f"blurry_{idx}"
            
        return (
            f"{base},split=2[s_{idx}][b_{idx}];"
            f"[b_{idx}]boxblur={max(blur_start, blur_end)}[blurry_{idx}];"
            f"[s_{idx}]copy[sharp_{idx}];"
            f"[{bot}][{top}]blend=all_expr='A*({op_expr})+B*(1-({op_expr}))',"
            f"fps={fps},format=yuv420p"
        )

    if etype == "rgb_split":
        return f"{base},chromashift=cbh=5:crh=-5,fps={fps},format=yuv420p"

    if etype == "film_grain":
        return f"{base},noise=alls=8:allf=t+u,fps={fps},format=yuv420p"

    if etype == "letterbox":
        lb_h = int(h * 0.8)
        return (
            f"scale={w}:{lb_h}:force_original_aspect_ratio=increase,crop={w}:{lb_h},"
            f"pad={w}:{h}:0:(oh-ih)/2:black,fps={fps},format=yuv420p"
        )

    if etype == "speed_ramp":
        zs = 1.0
        ze = float(effect.get("zoom_end", 1.15))
        frames = max(1, int(round(duration * fps)))
        ease_expr = f"(on/{frames})*(on/{frames})*(3 - 2*(on/{frames}))"
        z_expr = f"{zs} + ({ze}-{zs})*{ease_expr}"
        return (
            f"{base},"
            f"zoompan=z='{z_expr}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
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



        vf = effect_filter(eff, w, h, fps, dur, i)



        out_label = f"v{i}"

        fc_parts.append(

            f"[{i}:v]{vf},trim=duration={dur},setpts=PTS-STARTPTS,fps={fps}[{out_label}]"

        )

        labels.append(out_label)



    current = labels[0]

    current_len = durations[0]



    for i in range(0, len(labels) - 1):
        t = transitions[i] or {}
        ttype = t.get("type", "xfade")

        if ttype == "none":
            td = 0.05
            trans = "fade"
        else:
            td = float(t.get("duration", 0.5))
            trans = "fade"

        offset = max(0.0, current_len - td)
        next_label = labels[i + 1]
        out_label = f"x{i}"
        
        cur_mod = current
        nxt_mod = next_label

        if ttype == "xfade":
            trans = t.get("transition", "fade")
        elif ttype == "slide":
            direction = t.get("direction", "left")
            trans = f"slide{direction}"
        elif ttype == "wipe":
            direction = t.get("direction", "left")
            trans = f"wipe{direction}"
        elif ttype == "zoom":
            direction = t.get("direction", "in")
            trans = f"zoom{direction}"
        elif ttype == "fade_color":
            color = t.get("color", "black")
            trans = "fadewhite" if color == "white" else "fadeblack"
        elif ttype == "blur_transition":
            fc_parts.append(
                f"[{current}]split=2[c1_{i}][c2_{i}];"
                f"[c1_{i}]boxblur=15[cb_{i}];"
                f"[c2_{i}][cb_{i}]blend=all_expr='A*(1-(T-{offset})/{td}) + B*((T-{offset})/{td})':enable='between(t,{offset},{offset}+{td})'[cout_{i}]"
            )
            fc_parts.append(
                f"[{next_label}]split=2[n1_{i}][n2_{i}];"
                f"[n1_{i}]boxblur=15[nb_{i}];"
                f"[n2_{i}][nb_{i}]blend=all_expr='A*(T/{td}) + B*(1-(T/{td}))':enable='between(t,0,{td})'[nout_{i}]"
            )
            cur_mod = f"cout_{i}"
            nxt_mod = f"nout_{i}"
        elif ttype == "directional_blur":
            direction = t.get("direction", "left")
            trans = f"smooth{direction}"
        elif ttype == "mask":
            shape = t.get("shape", "radial")
            if shape == "diagonal": trans = "diagbl"
            elif shape == "gradient": trans = "distance"
            else: trans = "radial"
        elif ttype == "spin":
            style = t.get("style", "rotate")
            trans = style
        elif ttype == "glitch":
            fc_parts.append(
                f"[{current}]chromashift=cbh=15:crh=-15:enable='between(t,{offset},{offset}+{td})'[cg_{i}]"
            )
            fc_parts.append(
                f"[{next_label}]chromashift=cbh=15:crh=-15:enable='between(t,0,{td})'[ng_{i}]"
            )
            cur_mod = f"cg_{i}"
            nxt_mod = f"ng_{i}"
            trans = "pixelize"
        elif ttype == "cross_zoom":
            fc_parts.append(
                f"[{current}]boxblur=10:enable='between(t,{offset},{offset}+{td})'[czc_{i}]"
            )
            fc_parts.append(
                f"[{next_label}]boxblur=10:enable='between(t,0,{td})'[czn_{i}]"
            )
            cur_mod = f"czc_{i}"
            nxt_mod = f"czn_{i}"
            trans = "zoomin"
        elif ttype != "none":
            trans = t.get("transition", "fade")

        fc_parts.append(
            f"[{cur_mod}][{nxt_mod}]"
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

    

    try:

        subprocess.run(cmd, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:

        raise RuntimeError(f"FFmpeg failed with exit code {e.returncode}.\nStderr: {e.stderr}") from e



def get_audio_duration(filename: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", filename
    ]
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(result.stdout.strip())
    except Exception as e:
        # Fallback to wave if ffprobe fails for some reason
        with contextlib.closing(wave.open(filename, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return frames / float(rate)



def get_audio_mean_volume(filename: str) -> float:
    cmd = [
        "ffmpeg", "-i", filename, 
        "-af", "volumedetect", 
        "-vn", "-sn", "-dn", 
        "-f", "null", "/dev/null"
    ]
    try:
        result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, check=True)
        m = re.search(r'mean_volume:\s*([-0-9.]+)\s*dB', result.stderr)
        if m:
            return float(m.group(1))
    except Exception as e:
        print(f"Error getting volume for {filename}: {e}")
    return -20.0

def merge_video_audio(

    video_input: Path,

    output_file: Path,

    narration_input: Optional[Path] = None,

    background_input: Optional[Path] = None,

    vol_narration: float = 1.0,

    vol_background: float = 0.1,

    fade_duration: float = 2.0

):

    """

    Mescla vídeo com narração (opcional) e música de fundo (opcional).

    Aplica fade out no final.

    """

    

    # Se não tiver inputs de áudio extras, podemos retornar o vídeo original ou

    # (se quiser garantir o formato) fazer uma cópia simples.

    # Mas o requisito diz "maybe the video don't will have an music or narration... return a video"

    # Se só tiver vídeo, e nenhum áudio extra, retornamos ele mesmo (ou copiamos).

    if not narration_input and not background_input:

        # Copia simples ou ffmpeg copy

        cmd = ["ffmpeg", "-y", "-i", str(video_input), "-c", "copy", str(output_file)]

        print("Running ffmpeg (copy):", " ".join(cmd))

        subprocess.run(cmd, check=True)

        return



    # Lógica de duração

    # Se tiver narração, a duração é (narração + fade).

    # Se NÃO tiver narração, qual é a duração? 

    # O usuário não especificou, mas presumo que seja a duração do vídeo original ou da música?

    # Vamos assumir:

    # - Se tem narração: Duração = Narração + Fade

    # - Se NÃO tem narração mas tem música: Duração = Vídeo original? Ou Música? 

    #   Geralmente mantemos a duração do vídeo original se for apenas adicionar música de fundo.

    #   MAS, o script original do usuário diz: "O vídeo vai durar o tempo da narração + o tempo do fade out".

    #   E o vídeo é estendido com tpad.

    #   Vamos seguir a lógica do usuário: "extend video".

    

    # Precisamos da duração base para calcular o fade.

    # No script do usuário, ele calculava narr_duration.

    

    narr_duration = 0.0

    if narration_input:

        narr_duration = get_audio_duration(str(narration_input))

        

    # Se não tiver narração, não faz sentido usar a lógica de "estender até acabar a narração".

    # Nesse caso, vamos assumir que usamos a duração do vídeo original como base,

    # ou se for só música, talvez a duração do vídeo.

    

    if narration_input:

        base_duration = narr_duration

        total_duration = base_duration + fade_duration

        start_fade = base_duration

        

        # Filtro complexo do usuário adaptado

        # [0:v] é o vídeo

        # [1:a] seria a narração

        # [2:a] seria o background

        

        # O script original assume que SEMPRE tem os 3 arquivos.

        # Vamos adaptar para quando falta um deles.

        

        inputs = ["-i", str(video_input)]

        

        # Mapa de índices

        # 0: video

        input_idx = 1

        

        narr_idx = -1

        if narration_input:

            inputs.extend(["-i", str(narration_input)])

            narr_idx = input_idx

            input_idx += 1

            

        bg_idx = -1

        if background_input:

            inputs.extend(["-stream_loop", "-1", "-i", str(background_input)])

            bg_idx = input_idx

            input_idx += 1

            

        # Construção do Filter Complex

        fc = []

        

        # Vídeo: tpad para estender (congelar o ultimo frame) se o vídeo for menor que o áudio

        # Mas o script original usa tpad=stop=-1:stop_mode=clone

        fc.append(f"[0:v]tpad=stop=-1:stop_mode=clone[v_ext]")

        fc.append(f"[v_ext]fade=t=out:st={start_fade}:d={fade_duration}[v_final]")

        

        # Áudio
        audio_mix_parts = []
        
        if narr_idx != -1:
            # apad ensures narration stream doesn't end before the background or total_duration,
            fc.append(f"[{narr_idx}:a]volume={vol_narration},apad[a_narr]")
            audio_mix_parts.append("[a_narr]")
            
        if bg_idx != -1:
            # Automagic volume calculation
            # We want the background music to have a steady, constant volume that sits nicely under the narration.
            bg_mean = -20.0
            if background_input:
                bg_mean = get_audio_mean_volume(str(background_input))
                
            narr_mean = -20.0
            if narration_input:
                narr_mean = get_audio_mean_volume(str(narration_input))
                
            # Aim for background to be ~14 dB quieter than the narration track
            target_bg_db = narr_mean - 14.0
            
            # If the user passed vol_background different than the default 0.1, 
            # we can apply it as an additional offset or just rely on auto. 
            # Since auto is requested, we compute the required gain to hit target_bg_db.
            gain_db = target_bg_db - bg_mean
            
            # Cap the maximum boost to avoid distortion if background is extremely quiet
            gain_db = min(gain_db, 2.0)
            
            fc.append(f"[{bg_idx}:a]volume={gain_db}dB,asetpts=N/SR/TB[a_bg]")
            audio_mix_parts.append("[a_bg]")
            
        # Mixagem
        if len(audio_mix_parts) == 2:
             # Constant level mixing - no ducking, just perfectly balanced steady levels
             fc.append(f"{''.join(audio_mix_parts)}amix=inputs=2:duration=longest:normalize=0[a_mix]")
             fc.append(f"[a_mix]afade=t=out:st={start_fade}:d={fade_duration}[a_final]")
        elif len(audio_mix_parts) == 1:
             # Só um audio, aplica fade direto
             fc.append(f"{audio_mix_parts[0]}afade=t=out:st={start_fade}:d={fade_duration}[a_final]")
        else:
             # Sem audio? (Não deve cair aqui pelo if inicial)
             pass



        cmd = [

            'ffmpeg', '-y',

            *inputs,

            '-filter_complex', ";".join(fc),

            '-map', '[v_final]',

            '-map', '[a_final]',

            '-c:v', 'libx264',

            '-c:a', 'aac',

            '-t', str(total_duration),

            str(output_file)

        ]

        

    else:

        # SEM Narração.

        # Se tiver só background music + video.

        # Geralmente queremos que o vídeo mantenha sua duração original, e a música toque de fundo.

        # Ou queremos estender o vídeo para durar a música toda? (Pouco provável).

        # Vamos assumir: Duração = Duração do Vídeo Original.

        # O usuário disse: "maybe the video don't will have an music or narration... return a video"

        # "video_input... narration_input or not... background_input or not"

        

        # Se só tiver vídeo e background, vamos mixar o audio do vídeo (se tiver) com o background?

        # Ou substituir? O script original do usuário IGNORA o áudio do vídeo original (não mapeia [0:a]).

        # Ele usa apenas narração e background.

        # Então se não tiver narração, mas tiver background, vamos colocar o background no vídeo.

        

        # Vamos pegar a duração do vídeo original usando ffprobe?

        # Ou simplesmente aplicamos o background cortando quando o vídeo acabar.

        # O usuário forneceu logic para "merge_extend_video". A intenção parece ser criar vídeos narrados.

        # Se não tem narração, talvez não deva estender.

        

        # Vamos implementar o caso "Somente vídeo + Música de Fundo" mantendo a duração do vídeo.

        

        inputs = ["-i", str(video_input)]

        inputs.extend(["-stream_loop", "-1", "-i", str(background_input)])

        

        # Pegar duração do vídeo via ffprobe para o fade?

        # Se não quisermos usar ffprobe, podemos usar '-shortest' no ffmpeg, 

        # mas queremos o fade out...

        

        # Para simplificar e evitar dependência complexa de ffprobe agora (embora já tenhamos subprocess),

        # vamos tentar usar uma estratégia que não exija saber a duração exata a priori se possível,

        # ou usamos o `get_wav_duration` se o input fosse wav, mas video é mp4.

        

        # Vou usar ffprobe para pegar duração do vídeo, é mais seguro.

        

        def get_video_duration(fpath):

            result = subprocess.run(

                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(fpath)],

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT

            )

            return float(result.stdout)

            

        vid_duration = get_video_duration(video_input)

        

        # Vamos aplicar fade out no final do vídeo

        start_fade = max(0, vid_duration - fade_duration)

        

        fc = []

        # Audio do background

        fc.append(f"[1:a]volume={vol_background},afade=t=out:st={start_fade}:d={fade_duration}[a_final]")

        # Video fade out? Se quiser manter consistente

        fc.append(f"[0:v]fade=t=out:st={start_fade}:d={fade_duration}[v_final]")

        

        cmd = [

            'ffmpeg', '-y',

            *inputs,

            '-filter_complex', ";".join(fc),

            '-map', '[v_final]',

            '-map', '[a_final]',

            '-c:v', 'libx264',

            '-c:a', 'aac',

            '-t', str(vid_duration),

            str(output_file)

        ]



    print("Running ffmpeg (merge):", " ".join(cmd))

    try:

        subprocess.run(cmd, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:

        raise RuntimeError(f"FFmpeg merge failed.\nStderr: {e.stderr}") from e



def get_video_dimensions(video_path: Path):

    """

    Uses ffprobe to get the real video dimensions.

    """

    cmd = [

        "ffprobe", 

        "-v", "error", 

        "-select_streams", "v:0", 

        "-show_entries", "stream=width,height", 

        "-of", "json", 

        str(video_path)

    ]

    try:

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)

        width = int(data["streams"][0]["width"])

        height = int(data["streams"][0]["height"])

        return width, height

    except Exception as e:

        print(f"Error probing video: {e}")

        # Last resort fallback, but try to be conservative

        return 1920, 1080 



def color_to_ass(hex_color: str, opacity: int = 100) -> str:
    """
    Converte HEX padrão (#RRGGBB) para o formato ASS (&HAABBGGRR).
    opacity: 0-100 (%), onde 100 = totalmente opaco, 0 = totalmente transparente.
    No formato ASS, o canal Alpha vai de 00 (opaco) a FF (transparente).
    """
    hex_color = hex_color.lstrip("#")

    if len(hex_color) != 6:
        return "&H00FFFFFF"  # Branco opaco padrão se der erro

    # Converte opacity (0-100%) para alpha ASS (00-FF invertido)
    opacity = max(0, min(100, opacity))
    alpha = int((100 - opacity) * 255 / 100)
    alpha_hex = format(alpha, '02X')

    # ASS usa BGR ao invés de RGB
    r, g, b = hex_color[:2], hex_color[2:4], hex_color[4:]

    return f"&H{alpha_hex}{b}{g}{r}"


def process_highlight_tags(srt_text: str, highlight_color: str, font_color: str, font_opacity: int = 100) -> str:
    """
    Converte tags <highlight>...</highlight> no texto SRT para formatação HTML-like aceita nativamente pelo FFmpeg.
    """
    try:
        # Apenas garante que a cor esteja no formato correto com a hashtag
        if not highlight_color.startswith('#'):
            highlight_color = f"#{highlight_color}"
            
        # Pega apenas a parte RGB caso venha com Alpha (#RRGGBBAA -> #RRGGBB)
        rgb_color = highlight_color[:7]

        # No formato SRT, a maneira mais segura e suportada nativamente pelo FFmpeg 
        # para alterar cores inline é usar a tag <font color="#RRGGBB">
        
        # Substitui a tag de abertura
        result = re.sub(
            r'<\s*highlight\s*>',
            lambda m: f'<font color="{rgb_color}">',
            srt_text,
            flags=re.IGNORECASE
        )
        # Substitui a tag de fechamento
        result = re.sub(
            r'<\s*/\s*highlight\s*>',
            lambda m: '</font>',
            result,
            flags=re.IGNORECASE
        )
        # Remove qualquer tag malformada restante
        result = re.sub(r'<\s*/?\s*highlight[^>]*>', '', result, flags=re.IGNORECASE)
        
        return result
    except Exception as e:
        # Em caso de falha, remove as tags silenciosamente
        print(f"Warning: Error processing highlight tags: {e}")
        try:
            return re.sub(r'</?highlight[^>]*>', '', srt_text)
        except Exception:
            return srt_text



def parse_timestamp(t_str: str) -> float:

    # 00:00:27,330

    h, m, s_ms = t_str.split(':')

    s, ms = s_ms.split(',')

    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0



def format_timestamp(t: float) -> str:

    h = int(t // 3600)

    m = int((t % 3600) // 60)

    s = int(t % 60)

    ms = int(round((t - int(t)) * 1000))

    if ms >= 1000:

        s += 1

        ms -= 1000

    if s >= 60:

        m += 1

        s -= 60

    if m >= 60:

        h += 1

        m -= 60

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"



def process_srt_limit_lines(srt_path: Path, max_lines: int, max_chars: int = 40):

    if max_lines <= 0:

        return

        

    try:

        content = srt_path.read_text(encoding='utf-8')

    except Exception as e:

        print(f"Error reading SRT: {e}")

        return



    # Normalize line endings

    content = content.replace('\r\n', '\n').replace('\r', '\n')

    blocks = content.strip().split('\n\n')

    

    new_blocks = []

    

    for block in blocks:

        lines = block.strip().split('\n')

        if len(lines) < 3: 

            continue

            

        # Parse logic

        if "-->" in lines[1]:

            time_line = lines[1]

            text_lines = lines[2:]

        elif "-->" in lines[0]:

            time_line = lines[0]

            text_lines = lines[1:]

        else:

            continue

        

        try:

            start_str, end_str = time_line.split(' --> ')

            start_t = parse_timestamp(start_str.strip())

            end_t = parse_timestamp(end_str.strip())

        except Exception as e:

            print(f"Error parsing timestamp {time_line}: {e}")

            continue



        # 1. FLATTEN and RE-WRAP

        # The user wants to "optimize space". Typical SRT has line breaks for phrasing.

        # But if we want to enforce max_lines and avoid FFmpeg wrapping, it's safer to flow the text.

        # We join with spaces.

        full_text = " ".join([l.strip() for l in text_lines]).strip()

        

        # Wrap strictly using max_chars

        wrapped_lines = textwrap.wrap(full_text, width=max_chars)

        

        # If empty, ensure at least one empty line

        if not wrapped_lines:

            wrapped_lines = [""]

            

        text_lines = wrapped_lines

        

        # 2. Check line count

        if len(text_lines) <= max_lines:

            # If it fits, use it. 

            # (Optional: We could try to balance lines if len < max_lines but > 1, 

            # but textwrap fills top-down. Usually acceptable).

            new_blocks.append((start_t, end_t, text_lines))

        else:

            # Split into multiple time-blocks

            # We need to distribute the "duration" among the chunks of lines.

            duration = end_t - start_t

            

            # Create chunks of max_lines

            # e.g. 5 lines, max_lines=2 -> [2, 2, 1]

            chunks = [text_lines[i:i + max_lines] for i in range(0, len(text_lines), max_lines)]

            

            # Distribute time based on character count ratio

            full_text_len = len(full_text)

            if full_text_len == 0: full_text_len = 1

            

            current_start = start_t

            for i, chunk in enumerate(chunks):

                # Calculate chunk text length

                chunk_text = " ".join(chunk)

                chunk_len = len(chunk_text)

                

                if i == len(chunks) - 1:

                    chunk_end = end_t

                else:

                    # Proportional duration

                    ratio = chunk_len / full_text_len

                    # Heuristic: Add a small buffer or min duration? 

                    # For now strictly proportional

                    chunk_dur = duration * ratio

                    chunk_end = current_start + chunk_dur

                

                new_blocks.append((current_start, chunk_end, chunk))

                current_start = chunk_end

                

    # Rewrite

    with open(srt_path, 'w', encoding='utf-8') as f:

        for i, (s, e, lines) in enumerate(new_blocks, 1):

             f.write(f"{i}\n")

             f.write(f"{format_timestamp(s)} --> {format_timestamp(e)}\n")

             for l in lines:

                 f.write(l + "\n")

             f.write("\n")



def enforce_subtitle_pause(srt_path: Path, pause_ms: int):
    if pause_ms <= 0:
        return
        
    try:
        content = srt_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Error reading SRT for pause: {e}")
        return

    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = content.strip().split('\n\n')
    
    new_blocks = []
    pause_sec = pause_ms / 1000.0
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2: 
            continue
            
        time_line_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_line_idx = i
                break
                
        if time_line_idx == -1:
            new_blocks.append(block)
            continue
            
        time_line = lines[time_line_idx]
        text_lines = lines[time_line_idx + 1:]
        
        try:
            start_str, end_str = time_line.split(' --> ')
            start_t = parse_timestamp(start_str.strip())
            end_t = parse_timestamp(end_str.strip())
        except Exception:
            new_blocks.append(block)
            continue
            
        if start_t < pause_sec:
            start_t = pause_sec
            
        if end_t < pause_sec:
            end_t = pause_sec
            
        lines[time_line_idx] = f"{format_timestamp(start_t)} --> {format_timestamp(end_t)}"
        new_blocks.append("\n".join(lines[:time_line_idx + 1] + text_lines))

    with open(srt_path, 'w', encoding='utf-8') as f:
        for block in new_blocks:
            f.write(block + "\n\n")

# Valores padrão para as configurações visuais de legendas
_SUBTITLE_DEFAULTS = {
    "font_family":    "Poppins",
    "font_weight":    700,        # Negrito moderado
    "border_width":   1,          # Contorno fino (estava muito grosso)
    "font_opacity":   100,
    "shadow_enabled": True,       # Ativamos uma sombra muito sutil
    "shadow_opacity": 40,         # Sombra mais suave
    "shadow_depth":   1,          # Leve descolamento para dar leitura sem borrar
    "highlight_color": "#FFD633",
}


def _resolve_subtitle_param(value, key: str, cast_type=None):
    """
    Retorna value se for válido, caso contrário retorna o default.
    Aceita None, string vazia ou tipo incorreto como "inválido".
    """
    default = _SUBTITLE_DEFAULTS[key]
    if value is None:
        return default
    if cast_type is not None:
        try:
            return cast_type(value)
        except (ValueError, TypeError):
            return default
    if isinstance(value, str) and value.strip() == "":
        return default
    return value


def add_subtitles(
    video_input: Path,
    srt_input: Path,
    output_file: Path,
    position_y: int = 0,           # 0 = Base absoluta, + = Sobe em direção ao topo
    font_color: str = "#FFFFFF",
    outline_color: str = "#000000",
    font_size: int = 24,
    max_lines: Optional[int] = None,
    # Novos parâmetros visuais (todos opcionais com fallback para defaults)
    font_family: Optional[str] = None,
    font_weight: Optional[int] = None,
    border_width: Optional[int] = None,
    font_opacity: Optional[int] = None,
    shadow_enabled: Optional[bool] = None,
    shadow_opacity: Optional[int] = None,
    shadow_depth: Optional[int] = None,
    highlight_color: Optional[str] = None,
):

    

    # Calculate approx max chars based on video width

    # We try to wrap before ffmpeg does.

    # Default fallback

    max_chars = 40 

    

    try:

        w, h = get_video_dimensions(video_input)

        if w > 0 and font_size > 0:

            # Heuristic: 

            # Average char width ~ 0.5 * font_size (pixels)

            # Safe area ~ 0.85 * width (give margin)

            # Max chars = (0.85 * w) / (0.65 * font_size)

            # Increased char width estimate to 0.65 just to be safer (wider chars)

            max_chars = int((w * 0.85) / (font_size * 0.65))

            if max_chars < 15: max_chars = 15 

            print(f"DEBUG: Estimated max_chars={max_chars} for width={w}, font={font_size}")

    except Exception as e:

        print(f"Warning: Could not determine video dimensions for char limit: {e}")



    # Process SRT to enforce max_lines if requested
    if max_lines is not None and max_lines > 0:
        process_srt_limit_lines(srt_input, max_lines, max_chars=max_chars)

    # Resolve parâmetros visuais com fallback para defaults
    r_font_family   = _resolve_subtitle_param(font_family,   "font_family")
    r_font_weight   = _resolve_subtitle_param(font_weight,   "font_weight",   int)
    r_border_width  = _resolve_subtitle_param(border_width,  "border_width",  int)
    r_font_opacity  = _resolve_subtitle_param(font_opacity,  "font_opacity",  int)
    r_shadow_enabled= _resolve_subtitle_param(shadow_enabled,"shadow_enabled")
    r_shadow_opacity= _resolve_subtitle_param(shadow_opacity,"shadow_opacity",int)
    r_shadow_depth  = _resolve_subtitle_param(shadow_depth,  "shadow_depth",  int)
    r_highlight_color = _resolve_subtitle_param(highlight_color, "highlight_color")

    # Processa tags <highlight> no SRT antes de passar ao FFmpeg
    try:
        srt_content = srt_input.read_text(encoding="utf-8")
        srt_processed = process_highlight_tags(srt_content, r_highlight_color, font_color, r_font_opacity)
        srt_input.write_text(srt_processed, encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not process highlight tags in SRT: {e}")

    # Prepara cores com suporte a opacidade
    primary_colour     = color_to_ass(font_color, r_font_opacity)
    outline_colour_ass = color_to_ass(outline_color, 100)
    # Sombra: BackColour com opacidade configurável
    shadow_colour_ass  = color_to_ass("#000000", r_shadow_opacity if r_shadow_enabled else 0)

    # Bold: ativado quando font_weight >= 600
    bold_flag = 1 if r_font_weight >= 600 else 0

    # Shadow depth: profundidade da sombra (0 = desligada)
    shadow_value = r_shadow_depth if r_shadow_enabled else 0

    # Alignment=2 (Base Central). MarginV define quantos pixels subir a partir da base.
    alignment = 2
    margin_v = position_y

    # Constrói o estilo forçado
    # BorderStyle=1 (Outline + Shadow)
    force_style = (
        f"Fontname={r_font_family},Bold={bold_flag},"
        f"Alignment={alignment},MarginV={margin_v},Fontsize={font_size},"
        f"PrimaryColour={primary_colour},OutlineColour={outline_colour_ass},"
        f"BackColour={shadow_colour_ass},"
        f"BorderStyle=1,Outline={r_border_width},Shadow={shadow_value}"
    )

    

    print(f"DEBUG: Aplicando legendas com MarginV={margin_v} (Distância do fundo)")



    # Escapar nome do arquivo para o filtro

    srt_filename = srt_input.name

    vf_arg = f"subtitles='{srt_filename}':force_style='{force_style}'"



    cmd = [

        "ffmpeg", "-y",

        "-i", str(video_input),

        "-vf", vf_arg,

        "-c:a", "copy",       # Copia áudio (rápido)

        "-c:v", "libx264",    # Re-codifica vídeo (necessário para queimar legenda)

        "-preset", "fast",    # Velocidade de encode

        str(output_file)

    ]



    # Executa a partir da pasta do SRT para evitar erros de caminho no Windows

    cwd = srt_input.parent

    

    try:

        subprocess.run(cmd, check=True, cwd=cwd)

    except subprocess.CalledProcessError as e:

        raise RuntimeError(f"Erro no FFmpeg ao adicionar legendas") from e





def generate_subtitles(

    audio_path: Path,

    output_srt_path: Optional[Path] = None,

    words_per_line: int = 5,

    model_size: str = "medium",

    language: Optional[str] = None

) -> str:

    """

    Generates an SRT string from an audio file using OpenAI Whisper.

    Groups words based on words_per_line constraint.

    If output_srt_path is provided, also saves to file.

    If language is None, Whisper will auto-detect.

    """

    

    warnings.filterwarnings("ignore")

    

    print(f"Loading Whisper model ({model_size})...")

    model = whisper.load_model(model_size)

    

    print(f"Transcribing audio (Language: {language or 'Auto-detect'})...")

    # Using word_timestamps=True to get word-level precision

    result = model.transcribe(str(audio_path), language=language, word_timestamps=True)

    

    def fmt(t):

        h = int(t // 3600)

        m = int((t % 3600) // 60)

        s = int(t % 60)

        ms = int((t - int(t)) * 1000)

        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"



    lines_srt = []

    counter = 1

    

    all_words = []

    for seg in result["segments"]:

        if 'words' in seg:

            for w in seg['words']:

                all_words.append(w)



    # Group words

    current_group = []

    

    for i, word_info in enumerate(all_words):

        text = word_info['word'].strip()

        if not text:

            continue

            

        current_group.append(word_info)

        

        # Check if we reached the limit or it's the last word

        if len(current_group) >= words_per_line or i == len(all_words) - 1:

            start_time = current_group[0]['start']

            end_time = current_group[-1]['end']

            text_content = " ".join([w['word'].strip() for w in current_group])

            

            lines_srt.append(str(counter))

            lines_srt.append(f"{fmt(start_time)} --> {fmt(end_time)}")

            lines_srt.append(text_content)

            lines_srt.append("")

            

            counter += 1

            current_group = []



    srt_content = "\n".join(lines_srt)

    

    if output_srt_path:

        output_srt_path.write_text(srt_content, encoding="utf-8")

        print(f"Subtitles generated at: {output_srt_path}")

        

    return srt_content



def get_audio_channels(file_path: Path) -> int:

    """

    Uses ffprobe to get the number of audio channels.

    """

    cmd = [

        "ffprobe", 

        "-v", "error", 

        "-select_streams", "a:0", 

        "-show_entries", "stream=channels", 

        "-of", "json", 

        str(file_path)

    ]

    try:

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)

        if "streams" in data and len(data["streams"]) > 0:

            return int(data["streams"][0]["channels"])

        return 2 # Default to stereo if unsure

    except Exception as e:

        print(f"Error probing audio channels: {e}")

        return 2



def add_silence_to_audio(input_file: Path, output_file: Path, duration_ms: int):

    """

    Adds silence at the beginning of the audio file using adelay filter.

    """

    # First, try to detect channels to be safe, although newer ffmpeg supports all=1

    channels = get_audio_channels(input_file)

    

    # Construct adelay string: "1000|1000" for stereo

    # adelay string format: "del1|del2|del3..."

    delays = "|".join([str(duration_ms)] * channels)

    

    cmd = [

        "ffmpeg", "-y",

        "-i", str(input_file),

        "-af", f"adelay={delays}",

        str(output_file)

    ]

    

    print(f"Running ffmpeg (add_silence): {' '.join(cmd)}")

    try:

        subprocess.run(cmd, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:

        msg = f"FFmpeg add_silence failed.\nStderr: {e.stderr}"

        print(msg)

        raise RuntimeError(msg) from e







def humanize_audio(input_file: Path, output_file: Path, preset: str = "celular"):

    """

    Applies audio processing to simulate natural environments.

    Presets:

    - celular: Generic phone recording (bandpass, mild compression)

    - whatsapp: Aggressive compression, lower bandwidth, mono

    - room: Slight reverb/ambience

    """

    

    filters = []

    

    # Common normalization to ensure consistent levels before processing

    # filters.append("loudnorm=I=-16:TP=-1.5:LRA=11") # Optional: normalize loudness first

    

    if preset == "whatsapp":

        # Simulação de áudio comprimido de app de mensagem

        # Bandpass mais estreito (200Hz - 3400Hz)

        filters.append("highpass=f=200,lowpass=f=3400")

        # Compressão para nivelar a voz

        filters.append("acompressor=ratio=5:attack=25:release=50:threshold=0.1")

        # Leve distorção ou equalização para "colorir"

        filters.append("equalizer=f=500:t=q:w=1:g=2") # Boost mids slightly

        

    elif preset == "celular":

        # Simulação de chamada telefônica

        # Bandpass padrão telecom (300Hz - 3400Hz)

        filters.append("highpass=f=300,lowpass=f=3400")

        filters.append("acompressor=ratio=3:threshold=0.1")

        

    elif preset == "room":

        # Simulação de ambiente (sala)

        # Cortar graves muito profundos e agudos extremos

        filters.append("highpass=f=100,lowpass=f=10000")

        # Echo para simular reflexão de parede (reverb simples)

        # in_gain=0.6, out_gain=0.3, delays=20|30, decays=0.2|0.1

        filters.append("aecho=0.8:0.3:20|40:0.3|0.2")

        

    else: # Generic/Meeting

        filters.append("highpass=f=80")

        filters.append("acompressor=ratio=2:threshold=0.2")



    filter_str = ",".join(filters)

    if not filter_str:

        filter_str = "anull"



    cmd = [

        "ffmpeg", "-y",

        "-i", str(input_file),

        "-af", filter_str,

        # Force mono for whatsapp/celular for realism

        "-ac", "1" if preset in ["whatsapp", "celular"] else "2",

        # Sample rate reduction for whatsapp to strict 16k or 24k helps sells the effect

        "-ar", "16000" if preset == "whatsapp" else "44100",

        str(output_file)

    ]

    

    print(f"Running humanize ({preset}): {' '.join(cmd)}")

    try:

        subprocess.run(cmd, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:

         raise RuntimeError(f"FFmpeg humanize failed: {e.stderr}")

