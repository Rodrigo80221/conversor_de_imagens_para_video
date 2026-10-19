from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Grade(StrictModel):
    contrast: float = Field(1.035, ge=0.5, le=1.5)
    brightness: float = Field(0.006, ge=-0.2, le=0.2)
    saturation: float = Field(0.94, ge=0, le=2)
    red_shadows: float = Field(0.012, ge=-0.2, le=0.2)
    blue_shadows: float = Field(-0.009, ge=-0.2, le=0.2)
    red_highlights: float = Field(0.014, ge=-0.2, le=0.2)
    blue_highlights: float = Field(-0.012, ge=-0.2, le=0.2)


class Typography(StrictModel):
    # auto uses installed Windows fonts, otherwise the bundled OFL families.
    font_profile: Literal["auto", "original", "open"] = "auto"
    caption_size: int = Field(62, ge=20, le=120)
    title_size: int = Field(122, ge=30, le=180)
    small_size: int = Field(25, ge=16, le=60)


class Transition(StrictModel):
    type: Literal["cut", "dissolve"] = "cut"
    duration: float = Field(0.3, ge=0.1, le=2)


class Shot(StrictModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    start: float = Field(0, ge=0)
    duration: float = Field(ge=0.3, le=60)
    speed: float = Field(1, ge=0.5, le=2)
    crop_x: float = Field(0.5, ge=0, le=1)
    crop_y: float = Field(0.5, ge=0, le=1)
    photo_zoom: float = Field(1.03, ge=1, le=1.15)
    audio: Literal["original", "mute"] = "original"
    caption: str = Field("", max_length=120)
    kicker: str = Field("", max_length=80)
    title: str = Field("", max_length=80)
    subtitle: str = Field("", max_length=100)
    closing: str = Field("", max_length=100)
    transition_to_next: Transition = Field(default_factory=Transition)


class Recipe(StrictModel):
    version: Literal["1"] = "1"
    width: int = Field(1080, ge=240, le=1920)
    height: int = Field(1920, ge=240, le=1920)
    fps: Literal[30] = 30
    crf: int = Field(19, ge=16, le=28)
    audio: Literal["original", "mute"] = "original"
    fade_in: float = Field(0.25, ge=0, le=2)
    fade_out: float = Field(0.6, ge=0, le=2)
    grade: Grade = Field(default_factory=Grade)
    typography: Typography = Field(default_factory=Typography)
    shots: list[Shot] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def timeline(self):
        if self.width % 2 or self.height % 2:
            raise ValueError("width e height devem ser pares.")
        if self.shots[-1].transition_to_next.type != "cut":
            raise ValueError("A ultima cena nao pode ter transicao para a proxima.")
        incoming = 0
        for i, shot in enumerate(self.shots):
            # Quantize to the video clock so audio and video boundaries agree.
            shot.duration = round(shot.duration * self.fps) / self.fps
            tr = shot.transition_to_next
            tr.duration = round(tr.duration * self.fps) / self.fps
            outgoing = tr.duration if tr.type == "dissolve" else 0
            if incoming + outgoing >= shot.duration:
                raise ValueError(f"Transicoes consomem toda a cena {i + 1}.")
            incoming = outgoing
        if self.duration > 180:
            raise ValueError("Esta versao aceita ate 180 segundos por edicao.")
        if self.fade_in > self.shots[0].duration or self.fade_out > self.shots[-1].duration:
            raise ValueError("Fade maior que a cena inicial/final.")
        return self

    @property
    def duration(self):
        return round(sum(s.duration for s in self.shots) - sum(
            s.transition_to_next.duration for s in self.shots[:-1]
            if s.transition_to_next.type == "dissolve"
        ), 6)


class InspectRequest(StrictModel):
    asset_ids: list[str] = Field(min_length=1, max_length=150)


class PreviewRequest(StrictModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    times: list[float] | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def timestamps(self):
        if self.times and any(t < 0 for t in self.times):
            raise ValueError("Tempos devem ser positivos.")
        return self
