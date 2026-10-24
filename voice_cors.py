"""Browser access for the public voice-processing endpoint only."""
import os

from starlette.middleware.cors import CORSMiddleware


class VoiceCORSMiddleware:
    def __init__(self, app):
        self.app = app
        origins = [value.strip() for value in os.getenv("VOICE_ALLOWED_ORIGINS", "*").split(",") if value.strip()]
        self.voice_app = CORSMiddleware(
            app,
            allow_origins=origins,
            allow_methods=["POST"],
            allow_headers=["Content-Type"],
            expose_headers=["X-Audio-Input-Duration", "X-Audio-Output-Duration",
                            "X-Audio-Removed-Seconds", "X-Audio-Cuts"],
        )

    async def __call__(self, scope, receive, send):
        target = self.voice_app if scope["type"] == "http" and scope["path"].rstrip("/") == "/process-voice" else self.app
        await target(scope, receive, send)
