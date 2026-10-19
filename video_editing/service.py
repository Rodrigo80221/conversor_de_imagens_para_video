import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .engine import render, validate_assets
from .fonts import resolve_fonts
from .media import Cancelled, normalize_image, probe

ID = re.compile(r"^[a-f0-9]{32}$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv"}
ACTIVE = {"queued", "running", "cancelling"}


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class Busy(ValueError):
    pass


class Service:
    """One bounded worker, durable results, explicit single-process ownership."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lease = (self.root / "worker.lock").open("a+b")
        try:
            self._lease.seek(0, 2)
            if self._lease.tell() == 0:
                self._lease.write(b"0")
                self._lease.flush()
            self._lease.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            raise RuntimeError("VIDEO_EDITING_DATA_DIR ja esta em uso. Execute com --workers 1.") from exc
        self.assets_dir = self.root / "assets"
        self.jobs_dir = self.root / "jobs"
        self.assets_dir.mkdir(exist_ok=True)
        self.jobs_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.events = {}
        for path in self.jobs_dir.glob("*/job.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["status"] in ACTIVE:
                item.update(status="failed", stage="Interrompido", error="Servidor reiniciado durante a tarefa.")
                write_json(path, item)
            self.jobs[item["id"]] = item
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-editing")
        self.closing = False

    def close(self):
        with self.lock:
            self.closing = True
            for event in self.events.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
        if os.name == "nt":
            import msvcrt
            self._lease.seek(0)
            msvcrt.locking(self._lease.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._lease, fcntl.LOCK_UN)
        self._lease.close()

    def asset(self, asset_id):
        if not ID.fullmatch(asset_id):
            raise ValueError("asset_id invalido.")
        path = self.assets_dir / asset_id / "asset.json"
        if not path.is_file():
            raise FileNotFoundError("Midia nao encontrada.")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["path"] = path.parent / value["stored_name"]
        return value

    @staticmethod
    def public_asset(value):
        return {k: v for k, v in value.items() if k not in {"path", "stored_name"}}

    def import_file(self, file, filename):
        ext = Path(filename or "").suffix.lower()
        if ext not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            raise ValueError("Formato aceito: MP4, MOV, M4V, MKV, PNG, JPG, WEBP ou HEIC/HEIF.")
        asset_id = uuid.uuid4().hex
        folder = self.assets_dir / asset_id
        folder.mkdir()
        source = folder / ("source" + ext)
        limit = int(os.environ.get("VIDEO_EDITING_MAX_UPLOAD_MB", "512")) * 1024 * 1024
        try:
            size = 0
            with source.open("wb") as target:
                while chunk := file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Arquivo excede VIDEO_EDITING_MAX_UPLOAD_MB.")
                    target.write(chunk)
            kind = "image" if ext in IMAGE_EXTENSIONS else "video"
            if kind == "image":
                path = folder / "normalized.png"
                try:
                    metadata = normalize_image(source, path)
                except (OSError, SyntaxError) as exc:
                    raise ValueError("Imagem invalida ou formato nao suportado.") from exc
                source.unlink()
            else:
                path = source
                metadata = probe(path)
                if metadata["duration"] <= 0:
                    raise ValueError("Duracao de video invalida.")
            if metadata["width"] * metadata["height"] > 100_000_000:
                raise ValueError("Resolucao excede 100 megapixels.")
            value = {"asset_id": asset_id, "filename": filename, "kind": kind,
                     "stored_name": path.name, "bytes": size, **metadata}
            write_json(folder / "asset.json", value)
            return self.public_asset(value)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def submit(self, recipe):
        assets = {s.asset_id: self.asset(s.asset_id) for s in recipe.shots}
        warnings = validate_assets(recipe, assets)
        _, font_names = resolve_fonts(recipe.typography.font_profile)
        with self.lock:
            if self.closing or sum(j["status"] in ACTIVE for j in self.jobs.values()) >= 8:
                raise Busy("Fila cheia; tente novamente depois.")
            job_id = uuid.uuid4().hex
            folder = self.jobs_dir / job_id
            folder.mkdir()
            write_json(folder / "recipe.json", recipe.model_dump())
            item = {"id": job_id, "status": "queued", "progress": 0, "stage": "Na fila",
                    "created_at": time.time(), "updated_at": time.time(), "duration": recipe.duration,
                    "fonts": {"serif": font_names[0], "sans": font_names[1]}, "warnings": warnings,
                    "error": None}
            self.jobs[job_id] = item
            self.events[job_id] = threading.Event()
            write_json(folder / "job.json", item)
            self.executor.submit(self._work, job_id, recipe, assets)
            return dict(item)

    def _update(self, job_id, **changes):
        with self.lock:
            self.jobs[job_id].update(changes, updated_at=time.time())
            write_json(self.jobs_dir / job_id / "job.json", self.jobs[job_id])

    def _work(self, job_id, recipe, assets):
        folder = self.jobs_dir / job_id
        event = self.events[job_id]
        try:
            with self.lock:
                if event.is_set():
                    raise Cancelled()
                self._update(job_id, status="running")
            def progress(value, stage):
                if event.is_set():
                    raise Cancelled()
                self._update(job_id, progress=round(value, 3), stage=stage)
            output = render(recipe, assets, folder, event, progress)
            actual = probe(output)
            if (actual["width"], actual["height"]) != (recipe.width, recipe.height):
                raise RuntimeError("Dimensoes finais diferentes da receita.")
            if abs(actual["duration"] - recipe.duration) > .1:
                raise RuntimeError("Duracao final diferente da receita.")
            if recipe.audio == "original" and not actual["has_audio"]:
                raise RuntimeError("Faixa de audio ausente na exportacao.")
            with self.lock:
                if event.is_set():
                    raise Cancelled()
                self._update(job_id, status="succeeded", progress=1, stage="Concluido")
        except Cancelled:
            self._update(job_id, status="cancelled", stage="Cancelado")
        except Exception as exc:
            self._update(job_id, status="failed", stage="Falhou", error=str(exc)[-4000:])
        finally:
            keep = {"job.json", "recipe.json"}
            if self.jobs[job_id]["status"] == "succeeded":
                keep.add("result.mp4")
            for path in folder.iterdir():
                if path.is_file() and path.name not in keep:
                    path.unlink(missing_ok=True)
            with self.lock:
                self.events.pop(job_id, None)

    def job(self, job_id):
        with self.lock:
            if not ID.fullmatch(job_id) or job_id not in self.jobs:
                raise FileNotFoundError("Tarefa nao encontrada.")
            return dict(self.jobs[job_id])

    def cancel(self, job_id):
        with self.lock:
            item = self.job(job_id)
            if item["status"] not in ACTIVE:
                raise Busy("Esta tarefa ja terminou.")
            self.events[job_id].set()
            self._update(job_id, status="cancelling", stage="Cancelamento solicitado")
            return self.job(job_id)
