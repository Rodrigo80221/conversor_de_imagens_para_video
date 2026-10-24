"""Local speech-recording cleanup using FFmpeg and streaming PCM edits."""
import json
import math
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

MAX_DURATION = 1800
PROCESS_TIMEOUT = 180


class VoiceError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class VoiceOptions:
    trim_start: bool = True
    trim_end: bool = True
    shorten_pauses: bool = True
    reduce_noise: bool = True
    silence_threshold_db: float = -35.0
    min_pause_seconds: float = 1.0
    keep_pause_seconds: float = 0.25
    edge_padding_seconds: float = 0.05
    noise_reduction_db: float = 12.0
    noise_floor_db: float = -40.0
    output_format: str = "wav"


def run(command, message):
    try:
        result = subprocess.run(command, capture_output=True, timeout=PROCESS_TIMEOUT)
    except FileNotFoundError:
        raise VoiceError("FFmpeg/ffprobe indisponivel no servidor.", 503) from None
    except subprocess.TimeoutExpired:
        raise VoiceError("Tempo limite ao processar a gravacao.", 504) from None
    if result.returncode:
        # Do not return subprocess logs, local paths or the user's recording data.
        raise VoiceError(message)
    return result


def parse_silences(log, duration):
    intervals = []
    start = None
    for kind, value in re.findall(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)", log):
        value = min(duration, max(0.0, float(value)))
        if kind == "start":
            start = value
        elif start is not None:
            if value > start:
                intervals.append((start, value))
            start = None
    if start is not None and start < duration:
        intervals.append((start, duration))
    return intervals


def removal_intervals(silences, duration, options):
    """Only selected operations can remove time; edge silence is never a middle pause."""
    cuts = []
    for start, end in silences:
        at_start, at_end = start <= 0.001, end >= duration - 0.001
        if at_start and at_end:
            if options.trim_start or options.trim_end:
                raise VoiceError("Nenhum trecho acima do limiar de silencio. Ajuste silence_threshold_db ou desative os cortes de borda.")
            continue
        if at_start:
            if options.trim_start:
                cuts.append((0.0, max(0.0, end - options.edge_padding_seconds)))
        elif at_end:
            if options.trim_end:
                cuts.append((min(duration, start + options.edge_padding_seconds), duration))
        elif options.shorten_pauses and end - start >= options.min_pause_seconds:
            half = options.keep_pause_seconds / 2
            cuts.append((start + half, end - half))
    return [(a, b) for a, b in cuts if b > a]


def splice_wav(source, target, cuts):
    with wave.open(str(source), "rb") as incoming:
        rate = incoming.getframerate()
        total = incoming.getnframes()
        # Convert to frames once, preserving every frame outside the selected cuts.
        frame_cuts = [(max(0, round(a * rate)), min(total, round(b * rate))) for a, b in cuts]
        with wave.open(str(target), "wb") as outgoing:
            outgoing.setparams(incoming.getparams())
            cursor = 0
            for start, end in frame_cuts + [(total, total)]:
                incoming.setpos(cursor)
                left = max(0, start - cursor)
                while left:
                    count = min(left, 65536)
                    outgoing.writeframesraw(incoming.readframes(count))
                    left -= count
                cursor = max(cursor, end)


def process_voice(source: Path, folder: Path, options: VoiceOptions):
    if options.keep_pause_seconds >= options.min_pause_seconds:
        raise VoiceError("keep_pause_seconds deve ser menor que min_pause_seconds.")
    if options.output_format not in ("wav", "mp3", "webm"):
        raise VoiceError("output_format deve ser wav, mp3 ou webm.")
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise VoiceError("FFmpeg/ffprobe indisponivel no servidor.", 503)
    probe = run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(source)],
                "Arquivo de audio invalido ou formato nao suportado.")
    try:
        info = json.loads(probe.stdout)
        stream = next(s for s in info["streams"] if s.get("codec_type") == "audio")
        channels = int(stream["channels"])
        rate = int(stream["sample_rate"])
        if channels not in (1, 2) or not 8000 <= rate <= 96000:
            raise ValueError()
        duration_hint = info.get("format", {}).get("duration", stream.get("duration"))
        if duration_hint is not None and math.isfinite(float(duration_hint)) and float(duration_hint) > MAX_DURATION:
            raise VoiceError("Gravacao maior que 30 minutos.", 413)
    except (KeyError, ValueError, StopIteration, TypeError):
        raise VoiceError("Envie audio mono ou estereo com frequencia entre 8 e 96 kHz.") from None
    decoded = folder / "decoded.wav"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
               "-map", "0:a:0", "-vn", "-t", str(MAX_DURATION + 1)]
    if options.reduce_noise:
        command += ["-af", f"afftdn=nr={options.noise_reduction_db}:nf={options.noise_floor_db}:tn=1:gs=5"]
    command += ["-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le", str(decoded)]
    run(command, "Nao foi possivel decodificar ou reduzir ruido desta gravacao.")
    with wave.open(str(decoded), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0:
        raise VoiceError("Gravacao sem amostras de audio.")
    if duration > MAX_DURATION:
        raise VoiceError("Gravacao maior que 30 minutos.", 413)
    silences = []
    if options.trim_start or options.trim_end or options.shorten_pauses:
        detected = run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(decoded), "-af",
                        f"silencedetect=noise={options.silence_threshold_db}dB:d=0.05", "-f", "null", "-"],
                       "Nao foi possivel detectar os silencios.")
        silences = parse_silences(detected.stderr.decode("utf-8", errors="replace"), duration)
    cuts = removal_intervals(silences, duration, options)
    edited = folder / "edited.wav"
    splice_wav(decoded, edited, cuts)
    with wave.open(str(edited), "rb") as wav:
        output_duration = wav.getnframes() / wav.getframerate()
    if output_duration <= 0:
        raise VoiceError("Os ajustes removeram todo o audio; reduza o limiar de silencio.")
    output = folder / f"processed_voice.{options.output_format}"
    if options.output_format == "wav":
        shutil.move(str(edited), output)
    else:
        codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if options.output_format == "mp3" else ["-c:a", "libopus", "-b:a", "96k"]
        run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(edited), *codec, str(output)],
            "Nao foi possivel converter para o formato de saida.")
    return output, {"input_duration": duration, "output_duration": output_duration,
                    "removed_seconds": duration - output_duration, "cuts": len(cuts)}
