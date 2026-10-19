"""Optional standalone entry point: uvicorn video_editing.app:app --workers 1."""
from fastapi import FastAPI
from .api import router

app = FastAPI(title="Video Editing API", version="1.0")
app.include_router(router)
