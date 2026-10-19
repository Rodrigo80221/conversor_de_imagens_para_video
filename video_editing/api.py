import os
import secrets
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .engine import contact_sheet
from .fonts import font_info
from .models import InspectRequest, PreviewRequest, Recipe
from .service import Busy, Service


@asynccontextmanager
async def lifespan(app):
    root = os.environ.get("VIDEO_EDITING_DATA_DIR", ".video-editing-data")
    service = Service(root)
    app.state.video_editing = service
    try:
        yield
    finally:
        service.close()


def authorize(x_video_editing_key: str | None = Header(default=None)):
    key = os.environ.get("VIDEO_EDITING_API_KEY", "")
    if key and not secrets.compare_digest(x_video_editing_key or "", key):
        raise HTTPException(401, "Chave de acesso invalida.")


router = APIRouter(prefix="/video-editing/v1", tags=["Video editing"], lifespan=lifespan,
                   dependencies=[Depends(authorize)])


def service(request: Request):
    return request.app.state.video_editing


def call(fn, *args):
    try:
        return fn(*args)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/assets", status_code=201, summary="Importar um video ou foto")
def upload(request: Request, file: UploadFile = File(...)):
    return call(service(request).import_file, file.file, file.filename)


@router.post("/inspect", summary="Consultar metadados das midias importadas")
def inspect(payload: InspectRequest, request: Request):
    store = service(request)
    return {"assets": [store.public_asset(call(store.asset, id)) for id in payload.asset_ids]}


@router.post("/previews", summary="Gerar folha de contato com tempos de origem")
def previews(payload: PreviewRequest, request: Request):
    asset = call(service(request).asset, payload.asset_id)
    if asset["kind"] == "image":
        times = [0.0]
    else:
        times = payload.times or [asset["duration"] * f for f in (.15, .45, .75)]
        if any(t >= asset["duration"] for t in times):
            raise HTTPException(422, "Tempo de previa fora do video.")
    folder = Path(tempfile.mkdtemp(prefix="video_preview_"))
    try:
        path = contact_sheet(asset, times, folder)
        return FileResponse(path, media_type="image/jpeg", filename="preview.jpg",
                            background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True))
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, "Nao foi possivel gerar a previa desta midia.") from exc


@router.get("/fonts", summary="Consultar fontes disponiveis no servidor")
def fonts():
    return font_info()


@router.post("/render", status_code=202, summary="Enviar receita para renderizacao")
def submit(recipe: Recipe, request: Request):
    item = call(service(request).submit, recipe)
    return links(item)


def links(item):
    prefix = f"/video-editing/v1/jobs/{item['id']}"
    return {**item, "status_url": prefix,
            "result_url": prefix + "/result" if item["status"] == "succeeded" else None}


@router.get("/jobs/{job_id}")
def status(job_id: str, request: Request):
    return links(call(service(request).job, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, request: Request):
    return links(call(service(request).cancel, job_id))


@router.get("/jobs/{job_id}/result")
def result(job_id: str, request: Request):
    store = service(request)
    item = call(store.job, job_id)
    if item["status"] != "succeeded":
        raise HTTPException(409, "O resultado ainda nao esta disponivel.")
    return FileResponse(store.jobs_dir / job_id / "result.mp4", media_type="video/mp4",
                        filename=f"edit_{job_id}.mp4")
