"""Bounded local audio ingestion and measurement using VoiceStudio media tools."""

import json
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import UUID, uuid4

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core import config
from core.path_security import UnsafePath, resolve_within, safe_filename
from services import ffmpeg_utils
from services.longform_render import build_loudnorm_measure_filter, parse_loudnorm_measure
from services.music import projects
from services.music.projects import MusicError
from services.music.schemas import AudioAnalysis, AudioAsset, AudioSource, Rights, Song, now

MAX_AUDIO_BYTES = 256 * 1024 * 1024
MAX_AUDIO_SECONDS = 20 * 60


def _filename(raw_name: str) -> tuple[str, Literal["wav", "mp3"]]:
    try:
        name = safe_filename(raw_name)
    except (UnsafePath, UnicodeError) as exc:
        raise MusicError("unsafe_filename", 422) from exc
    suffix = Path(name).suffix.lower()
    if suffix == ".wav":
        return name, "wav"
    if suffix == ".mp3":
        return name, "mp3"
    raise MusicError("unsupported_format", 415)


async def _inspect(path: Path, decoder: str) -> tuple[str, float, int, int]:
    ffprobe = ffmpeg_utils.find_ffprobe()
    if not ffprobe:
        raise MusicError("media_tools_missing", 503)
    try:
        command = ffmpeg_utils.local_inputs_only([
            ffprobe, "-v", "quiet", "-f", decoder, "-select_streams", "a:0", "-show_entries",
            "stream=codec_name,sample_rate,channels:format=duration,format_name",
            "-of", "json", str(path),
        ], tool="ffprobe")
        status, stdout, _ = await ffmpeg_utils.run_ffmpeg(command, timeout=25)
    except (TimeoutError, OSError) as exc:
        raise MusicError("probe_failed", 422) from exc
    if status:
        raise MusicError("invalid_audio", 422)
    try:
        data = json.loads(stdout)
        container = data["format"]
        track = data["streams"][0]
        duration = float(container["duration"])
        sample_rate = int(track["sample_rate"])
        channels = int(track["channels"])
        codec = track["codec_name"]
        if (
            not 0 < duration <= MAX_AUDIO_SECONDS
            or not 0 < sample_rate <= 384000
            or not 0 < channels <= 32
            or not codec
            or container["format_name"] != decoder
            or (decoder == "mp3" and codec != "mp3")
        ):
            raise ValueError("Audio metadata is outside the supported range")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise MusicError("invalid_audio", 422) from exc
    return codec, duration, sample_rate, channels


async def _measure(path: Path, decoder: str) -> AudioAnalysis:
    ffmpeg = ffmpeg_utils.find_ffmpeg()
    if not ffmpeg:
        raise MusicError("media_tools_missing", 503)
    measurement_filter = build_loudnorm_measure_filter("podcast")
    assert measurement_filter is not None
    args = [
        ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-xerror", "-f", decoder,
        "-i", str(path), "-map", "0:a:0", "-t", str(MAX_AUDIO_SECONDS + 1),
    ]
    try:
        status, _, stderr = await ffmpeg_utils.run_ffmpeg(
            [*args, "-af", measurement_filter, "-f", "null", "-"], timeout=120, capture=False,
        )
        if status:
            # Separate corrupt audio from a local FFmpeg build that cannot
            # measure an otherwise decodable file (e.g. an omitted filter).
            status, _, _ = await ffmpeg_utils.run_ffmpeg(
                [*args[:1], "-v", "error", *args[1:], "-f", "null", "-"],
                timeout=120, capture=False,
            )
            if status:
                raise MusicError("invalid_audio", 422)
            return AudioAnalysis(status="failed", error="analysis_failed")
    except (TimeoutError, OSError) as exc:
        raise MusicError("analysis_timeout", 422) from exc
    measured = parse_loudnorm_measure(stderr.decode("utf-8", errors="replace"))
    if measured is None:
        # Silent audio has no finite LUFS and/or true peak; JSON uses null.
        return AudioAnalysis(status="unavailable", error="no_loudness_result")
    return AudioAnalysis(status="complete", integratedLufs=measured.input_i, truePeakDbtp=measured.input_tp)


async def import_audio(
    request: Request, project_id: UUID, filename: str, source: AudioSource, rights: Rights,
) -> Song:
    name, file_type = _filename(filename)
    if request.headers.get("content-type", "").partition(";")[0].lower() != "application/octet-stream":
        raise MusicError("unsupported_format", 415)
    length = request.headers.get("content-length", "")
    if length.isdecimal() and int(length) > MAX_AUDIO_BYTES:
        raise MusicError("file_too_large", 413)
    await run_in_threadpool(projects.get, project_id)

    root = Path(config.DATA_DIR)
    try:
        originals = resolve_within(root, "music/originals")
        staging = resolve_within(root, "music/staging")
        staging.mkdir(parents=True, exist_ok=True)
        temp = NamedTemporaryFile(dir=staging, prefix="import-", suffix=".part", delete=False)
    except UnsafePath as exc:
        raise MusicError("unsafe_storage", 409) from exc
    staged = Path(temp.name)
    try:
        size = 0
        fingerprint = sha256()
        with temp:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise MusicError("file_too_large", 413)
                fingerprint.update(chunk)
                await run_in_threadpool(temp.write, chunk)
        if size == 0:
            raise MusicError("invalid_audio", 422)
        codec, duration, sample_rate, channels = await _inspect(staged, file_type)
        analysis = await _measure(staged, file_type)
        digest = fingerprint.hexdigest()
        target = resolve_within(originals, f"{project_id}/{digest}.{file_type}")
        asset = AudioAsset(
            id=uuid4(), name=name, fileType=file_type, codec=codec, durationSeconds=duration,
            sampleRateHz=sample_rate, channels=channels, sizeBytes=size, sha256=digest,
            source=source, rights=rights, analysis=analysis, createdAt=now(),
        )
        return await run_in_threadpool(projects.add_audio, project_id, asset, staged, target)
    except UnsafePath as exc:
        raise MusicError("unsafe_storage", 409) from exc
    finally:
        staged.unlink(missing_ok=True)
