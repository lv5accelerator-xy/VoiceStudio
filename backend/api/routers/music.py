"""Music workspace API. Text is local and audio uploads are streamed to disk."""

from contextlib import contextmanager
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.dependencies import require_admin
from services.music import audio, projects
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
