"""Music workspace API. Text is local and audio uploads are streamed to disk."""

from contextlib import contextmanager
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.dependencies import require_admin
from fastapi.responses import FileResponse

from core import job_store
from core.job_queue import gpu_queue
from core.path_security import resolve_within
from services import proc_registry
from services.music import audio, production, projects
from services.music.projects import MusicError
from services.music.schemas import (
    AudioSource,
    DeleteResult,
    LyricsInput,
    PromptInput,
    Rights,
    Song,
    SongFields,
    SongSummary,
    SongUpdate,
)

router = APIRouter(prefix="/music/projects", tags=["Music"], dependencies=[Depends(require_admin)])


@contextmanager
def _music_errors():
    try:
        yield
    except MusicError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail="storage_failed") from exc


@router.get("")
def list_music_projects() -> list[SongSummary]:
    return projects.list_projects()


@router.post("", status_code=201)
def create_music_project(fields: SongFields) -> Song:
    return projects.create(fields)


@router.get("/{project_id}")
def get_music_project(project_id: UUID) -> Song:
    with _music_errors():
        return projects.get(project_id)


@router.put("/{project_id}")
def update_music_project(project_id: UUID, fields: SongUpdate) -> Song:
    with _music_errors():
        return projects.update(project_id, fields)


@router.delete("/{project_id}")
def delete_music_project(project_id: UUID) -> DeleteResult:
    projects.delete(project_id)
    return DeleteResult()


@router.put("/{project_id}/lyrics")
def save_music_lyrics(project_id: UUID, fields: LyricsInput) -> Song:
    with _music_errors():
        return projects.add_version(project_id, fields)


@router.put("/{project_id}/suno-prompts")
def save_music_suno_prompt(project_id: UUID, fields: PromptInput) -> Song:
    with _music_errors():
        return projects.add_version(project_id, fields)


@router.post("/{project_id}/audio", openapi_extra={
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    },
})
async def import_music_audio(
    request: Request,
    project_id: UUID,
    x_music_filename: Annotated[str, Header(max_length=720, description="UTF-8 filename, percent-encoded")],
    source: AudioSource = "unknown",
    rights: Rights = "unverified",
) -> Song:
    with _music_errors():
        return await audio.import_audio(request, project_id, unquote(x_music_filename), source, rights)

@router.get("/{project_id}/production/capabilities")
def music_production_capabilities(project_id: UUID) -> dict[str, bool]:
    with _music_errors():
        projects.get(project_id)
        return {"videoProvider": production.video_provider() is not None}


@router.get("/{project_id}/production")
def list_music_production(project_id: UUID) -> list[production.ProductionState]:
    with _music_errors():
        projects.get(project_id)
        return [
            production.snapshot(row)
            for row in job_store.list_jobs(project_id=str(project_id), types=(production.JOB_TYPE,), limit=20)
        ]


@router.post("/{project_id}/production", status_code=202)
async def run_music_production(project_id: UUID, settings: production.ProductionRequest) -> production.ProductionState:
    with _music_errors():
        return await production.start(project_id, settings)


@router.post("/{project_id}/production/{run_id}/retry", status_code=202)
async def retry_music_production(project_id: UUID, run_id: UUID) -> production.ProductionState:
    with _music_errors():
        previous = production.get(project_id, run_id)
        if previous.state not in {"failed", "cancelled"}:
            raise MusicError("production_busy", 409)
        return await production.start(project_id, previous.settings, previous)


@router.post("/{project_id}/production/{run_id}/cancel")
async def cancel_music_production(project_id: UUID, run_id: UUID) -> production.ProductionState:
    with _music_errors():
        current = production.get(project_id, run_id)
        if current.state in {"pending", "running"} and await gpu_queue.cancel(str(run_id)):
            job = gpu_queue.get(str(run_id))
            if job and job.done_event.is_set():
                job_store.retire_if_active(str(run_id), "cancelled")
            proc_registry.kill_job_procs(str(run_id))
        return production.get(project_id, run_id)


@router.get("/{project_id}/production/{run_id}/files/{name}", response_class=FileResponse)
def open_music_artifact(project_id: UUID, run_id: UUID, name: production.Artifact) -> FileResponse:
    with _music_errors():
        projects.get(project_id)
        state = production.get(project_id, run_id)
        path = resolve_within(production.output_root(project_id, run_id), name)
        if name not in state.artifacts or not path.is_file():
            raise MusicError("production_missing", 404)
        suffix_type = {".wav": "audio/wav", ".mp4": "video/mp4", ".ass": "text/plain", ".png": "image/png", ".json": "application/json"}
        return FileResponse(path, media_type=suffix_type[path.suffix], filename=name,
                            content_disposition_type="inline" if path.suffix in {".wav", ".mp4", ".png"} else "attachment",
                            headers={"X-Content-Type-Options": "nosniff"})


@router.post("/{project_id}/video", status_code=201)
async def upload_music_video(project_id: UUID, request: Request) -> production.VideoAsset:
    with _music_errors():
        return await production.upload_video(request, project_id)
