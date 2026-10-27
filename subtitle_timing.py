"""Validate SRT times before burning captions; preserve text and highlight tags."""
import re


class SubtitleTimingError(ValueError):
    def __init__(self, message, cue=None):
        super().__init__(message)
        self.cue = cue


TIME = r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})"
TIMELINE = re.compile(rf"^{TIME}\s*-->\s*{TIME}$")


def validate_srt_timings(content, video_duration=None):
    content = content.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n[ \t]*\n', content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise SubtitleTimingError('SRT invalido: cada bloco exige numero, intervalo e texto.')
        cue = int(lines[0].strip())
        match = TIMELINE.fullmatch(lines[1].strip())
        if not match:
            raise SubtitleTimingError(f'Legenda {cue}: intervalo invalido. Use HH:MM:SS,mmm --> HH:MM:SS,mmm.', cue)
        v = list(map(int, match.groups()))
        start = v[0]*3600 + v[1]*60 + v[2] + v[3]/1000
        end = v[4]*3600 + v[5]*60 + v[6] + v[7]/1000
        if end <= start:
            raise SubtitleTimingError(f'Legenda {cue}: o fim deve ser maior que o inicio.', cue)
        if cues:
            previous = cues[-1]
            if start < previous['start']:
                raise SubtitleTimingError(f'Legenda {cue}: inicio fora de ordem cronologica.', cue)
            if previous['end'] > start + 0.001:
                raise SubtitleTimingError(
                    f"Legenda {previous['cue']}: termina em {previous['end']:.3f}s, "
                    f"depois do inicio da legenda {cue} ({start:.3f}s). Corrija o tempo final para evitar sobreposicao.", previous['cue'])
        cues.append({'cue': cue, 'start': start, 'end': end})
    if not cues:
        raise SubtitleTimingError('SRT vazio.')
    if video_duration is not None:
        for item in cues:
            if item['end'] > video_duration + 0.1:
                raise SubtitleTimingError(
                    f"Legenda {item['cue']}: termina em {item['end']:.3f}s, "
                    f"alem da duracao do video ({video_duration:.3f}s). Confira se o SRT pertence a este video.", item['cue'])
    return cues
