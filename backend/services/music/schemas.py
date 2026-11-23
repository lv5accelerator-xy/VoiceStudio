"""Persisted and API-facing Music P1 data. Field names match the renderer."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(max_length=500)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Lyrics = Annotated[str, StringConstraints(max_length=24000)]
Prompt = Annotated[str, StringConstraints(max_length=4000)]
SongStatus = Literal["draft", "writing", "ready_for_suno", "audio_imported", "complete"]
AudioSource = Literal["unknown", "suno", "original", "third_party"]
Rights = Literal["unverified", "personal_use", "commercial_confirmed"]


def now() -> datetime:
    return datetime.now(timezone.utc)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SongFields(InputModel):
    title: Title = "Untitled song"
    language: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$", max_length=40)] = "zh-CN"
    genre: Text = ""
    theme: Text = ""
    status: SongStatus = "draft"
    mood: Text = ""
    vocalType: Text = ""
    bpm: Annotated[int, Field(ge=20, le=300)] | None = None
    targetSeconds: Annotated[int, Field(ge=1, le=1200)] | None = None


class SongUpdate(SongFields):
    revision: int = Field(ge=0)


class LyricsInput(InputModel):
    id: UUID
    text: Annotated[Lyrics, StringConstraints(strip_whitespace=True, min_length=1)]


class LyricsVersion(LyricsInput):
    createdAt: datetime


class PromptFields(InputModel):
    style: Text = ""
    mood: Text = ""
    rhythm: Text = ""
    instruments: Text = ""
    vocal: Text = ""
    arrangement: Text = ""
    exclusions: Prompt = ""
    stylePrompt: Prompt = ""
    explanation: Prompt = ""


class PromptInput(PromptFields):
    id: UUID


class PromptVersion(PromptInput):
    createdAt: datetime


class AudioAnalysis(InputModel):
    status: Literal["complete", "unavailable", "failed"]
    integratedLufs: float | None = None
    truePeakDbtp: float | None = None
    error: Literal["no_loudness_result", "analysis_failed"] | None = None


class AudioAsset(InputModel):
    id: UUID
    name: str
    fileType: Literal["wav", "mp3"]
    codec: str
    durationSeconds: float = Field(gt=0)
    sampleRateHz: int = Field(gt=0)
    channels: int = Field(gt=0)
    sizeBytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: AudioSource = "unknown"
    rights: Rights = "unverified"
    analysis: AudioAnalysis
    createdAt: datetime


class SongSummary(InputModel):
    id: UUID
    title: Title
    status: SongStatus
    updatedAt: datetime


class Song(SongFields):
    schemaVersion: Literal[1] = 1
    id: UUID
    revision: int = Field(default=0, ge=0)
    lyricsVersions: list[LyricsVersion] = Field(default_factory=list)
    sunoPrompts: list[PromptVersion] = Field(default_factory=list)
    audioAssets: list[AudioAsset] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime


class DeleteResult(InputModel):
    retainedAudio: Literal[True] = True
