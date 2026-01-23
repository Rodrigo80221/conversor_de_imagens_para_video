import subprocess
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import wave
import contextlib
import os

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
            f"[{i}:v]{vf},trim=duration={dur},setpts=PTS-STARTPTS,fps={fps}[{out_label}]"
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
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg failed with exit code {e.returncode}.\nStderr: {e.stderr}") from e

def get_wav_duration(filename: str) -> float:
    with contextlib.closing(wave.open(filename, 'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)

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
        narr_duration = get_wav_duration(str(narration_input))
        
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
            fc.append(f"[{narr_idx}:a]volume={vol_narration}[a_narr]")
            audio_mix_parts.append("[a_narr]")
            
        if bg_idx != -1:
            fc.append(f"[{bg_idx}:a]volume={vol_background}[a_bg]")
            audio_mix_parts.append("[a_bg]")
            
        # Mixagem
        if len(audio_mix_parts) == 2:
             fc.append(f"{''.join(audio_mix_parts)}amix=inputs=2:dropout_transition=2[a_mix]")
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
