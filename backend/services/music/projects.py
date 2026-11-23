"""SQLite transactions for isolated music projects and immutable versions."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection
from uuid import UUID, uuid4

from core.db import db_conn
from services.music.schemas import (
    AudioAsset,
    LyricsInput,
    LyricsVersion,
    PromptInput,
    PromptVersion,
    Song,
    SongFields,
    SongSummary,
    SongUpdate,
    now,
)

MAX_VERSIONS = 100
MAX_AUDIO_ASSETS = 30


class MusicError(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def _get(conn: Connection, project_id: UUID) -> Song:
    row = conn.execute("SELECT document FROM music_projects WHERE id=?", (str(project_id),)).fetchone()
    if row is None:
        raise MusicError("project_missing", 404)
    return Song.model_validate_json(row["document"])


def get(project_id: UUID) -> Song:
    with db_conn() as conn:
        return _get(conn, project_id)


def list_projects() -> list[SongSummary]:
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT id, updated_at AS updatedAt,
                   json_extract(document, '$.title') AS title,
                   coalesce(json_extract(document, '$.status'), 'draft') AS status
            FROM music_projects ORDER BY updated_at DESC, id
        """).fetchall()
    return [SongSummary.model_validate(dict(row)) for row in rows]


def create(fields: SongFields) -> Song:
    timestamp = now()
    project = Song(**fields.model_dump(), id=uuid4(), createdAt=timestamp, updatedAt=timestamp)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO music_projects (id, updated_at, document) VALUES (?, ?, ?)",
            (str(project.id), timestamp.isoformat(), project.model_dump_json()),
        )
    return project


@contextmanager
def _edit(project_id: UUID) -> Iterator[tuple[Connection, Song]]:
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        yield conn, _get(conn, project_id)


def _write(conn: Connection, project: Song) -> None:
    project.updatedAt = now()
    conn.execute(
        "UPDATE music_projects SET updated_at=?, document=? WHERE id=?",
        (project.updatedAt.isoformat(), project.model_dump_json(), str(project.id)),
    )


def update(project_id: UUID, fields: SongUpdate) -> Song:
    with _edit(project_id) as (conn, project):
        changes = fields.model_dump(exclude={"revision"})
        if all(getattr(project, field) == value for field, value in changes.items()):
            return project
        if fields.revision != project.revision:
            raise MusicError("project_conflict", 409)
        project = project.model_copy(update={**changes, "revision": project.revision + 1})
        _write(conn, project)
    return project


def add_version(project_id: UUID, fields: LyricsInput | PromptInput) -> Song:
    with _edit(project_id) as (conn, project):
        if isinstance(fields, LyricsInput):
            version = LyricsVersion(**fields.model_dump(), createdAt=now())
            versions = project.lyricsVersions
        else:
            if not fields.stylePrompt.strip():
                raise MusicError("prompt_required", 422)
            version = PromptVersion(**fields.model_dump(), createdAt=now())
            versions = project.sunoPrompts

        existing = next((item for item in versions if item.id == version.id), None)
        if existing is not None:
            if existing.model_dump(exclude={"createdAt"}) != fields.model_dump():
                raise MusicError("version_conflict", 409)
            return project
        if len(versions) >= MAX_VERSIONS:
            raise MusicError("version_limit", 409)
        if versions and versions[-1].model_dump(exclude={"id", "createdAt"}) == fields.model_dump(exclude={"id"}):
            return project
        if isinstance(version, LyricsVersion):
            project.lyricsVersions.append(version)
        else:
            project.sunoPrompts.append(version)
        _write(conn, project)
    return project


def delete(project_id: UUID) -> None:
    # Originals are explicitly retained, even if project metadata is removed.
    with db_conn() as conn:
        conn.execute("DELETE FROM music_projects WHERE id=?", (str(project_id),))


def add_audio(project_id: UUID, asset: AudioAsset, staged: Path, target: Path) -> Song:
    with _edit(project_id) as (conn, project):
        for index, existing in enumerate(project.audioAssets):
            if existing.sha256 == asset.sha256:
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    staged.replace(target)
                if existing.analysis.status != "complete" and asset.analysis.status == "complete":
                    project.audioAssets[index] = existing.model_copy(update={"analysis": asset.analysis})
                    _write(conn, project)
                return project
        if len(project.audioAssets) >= MAX_AUDIO_ASSETS:
            raise MusicError("asset_limit", 409)
        # A stopped process can leave a complete, unreferenced original. Reuse
        # the content-addressed location on retry. Publish files before rows.
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(target)
        project.audioAssets.append(asset)
        _write(conn, project)
    return project
