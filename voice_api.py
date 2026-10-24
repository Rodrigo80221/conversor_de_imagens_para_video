"""Multipart API for browser microphone recordings. No cloud credentials required."""
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from voice_engine import VoiceError, VoiceOptions, process_voice

router = APIRouter(tags=["Voice audio"])
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class VoiceParameters(BaseModel):
    trim_start: bool = True
    trim_end: bool = True
    shorten_pauses: bool = True
    reduce_noise: bool = True
    silence_threshold_db: float = Field(default=-35, ge=-80, le=-15, allow_inf_nan=False)
    min_pause_seconds: float = Field(default=1.0, ge=0.2, le=30, allow_inf_nan=False)
    keep_pause_seconds: float = Field(default=0.25, ge=0.05, le=5, allow_inf_nan=False)
    edge_padding_seconds: float = Field(default=0.05, ge=0, le=0.5, allow_inf_nan=False)
    noise_reduction_db: float = Field(default=12, ge=1, le=30, allow_inf_nan=False)
    noise_floor_db: float = Field(default=-40, ge=-80, le=-20, allow_inf_nan=False)
    output_format: Literal["wav", "mp3", "webm"] = "wav"

    @model_validator(mode="after")
    def pause_bounds(self):
        if self.keep_pause_seconds >= self.min_pause_seconds:
            raise ValueError("keep_pause_seconds deve ser menor que min_pause_seconds.")
        return self


def voice_parameters(
    trim_start: Annotated[bool, Form()] = True,
    trim_end: Annotated[bool, Form()] = True,
    shorten_pauses: Annotated[bool, Form()] = True,
    reduce_noise: Annotated[bool, Form()] = True,
    silence_threshold_db: Annotated[float, Form(ge=-80, le=-15, allow_inf_nan=False)] = -35,
    min_pause_seconds: Annotated[float, Form(ge=0.2, le=30, allow_inf_nan=False)] = 1.0,
    keep_pause_seconds: Annotated[float, Form(ge=0.05, le=5, allow_inf_nan=False)] = 0.25,
    edge_padding_seconds: Annotated[float, Form(ge=0, le=0.5, allow_inf_nan=False)] = 0.05,
    noise_reduction_db: Annotated[float, Form(ge=1, le=30, allow_inf_nan=False)] = 12,
    noise_floor_db: Annotated[float, Form(ge=-80, le=-20, allow_inf_nan=False)] = -40,
    output_format: Annotated[Literal["wav", "mp3", "webm"], Form()] = "wav",
):
    if keep_pause_seconds >= min_pause_seconds:
        raise HTTPException(422, "keep_pause_seconds deve ser menor que min_pause_seconds.")
    return VoiceParameters(**locals())


@router.post("/process-voice", summary="Tratar gravacao de voz: silencios, pausas e ruido")
def process_voice_endpoint(file: Annotated[UploadFile, File(description="Gravacao do microfone: WebM/Opus, WAV, MP3, M4A/AAC ou OGG.")],
                           parameters: Annotated[VoiceParameters, Depends(voice_parameters)]):
    # Sync endpoint: FastAPI executes upload/FFmpeg work in its thread pool.
    folder = Path(tempfile.mkdtemp(prefix="process_voice_"))
    try:
        source = folder / "recording.bin"
        size = 0
        with source.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Gravacao maior que 100 MiB.")
                target.write(chunk)
        if not size:
            raise HTTPException(422, "Envie uma gravacao com conteudo.")
        output, stats = process_voice(source, folder, VoiceOptions(**parameters.model_dump()))
        media_type = {"wav": "audio/wav", "mp3": "audio/mpeg", "webm": "audio/webm"}[parameters.output_format]
        return FileResponse(output, media_type=media_type, filename=output.name,
                            headers={"X-Audio-Input-Duration": f"{stats['input_duration']:.3f}",
                                     "X-Audio-Output-Duration": f"{stats['output_duration']:.3f}",
                                     "X-Audio-Removed-Seconds": f"{stats['removed_seconds']:.3f}",
                                     "X-Audio-Cuts": str(stats["cuts"])},
                            background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True))
    except VoiceError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(exc.status, str(exc)) from None
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        file.file.close()
