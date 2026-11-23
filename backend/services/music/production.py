"""Local music production using the shared job queue and media tools."""

import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from shutil import copyfile, which
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core import config, job_store
from core.job_queue import Job, gpu_queue
from core.path_security import resolve_within
from services import ffmpeg_utils
from services.karaoke_ass import build_ass
from services.music import audio, projects
from services.music.projects import MusicError
from services.music.schemas import InputModel

logger = logging.getLogger(__name__)
JOB_TYPE = "music_production"
WEIGHT = "955717e8-8726e21a.th"
Stem = Literal["vocals", "accompaniment", "drums", "bass", "other", "source"]
Artifact = Literal["vocals.wav", "accompaniment.wav", "drums.wav", "bass.wav", "other.wav", "mix.wav", "lyrics.ass", "mv.mp4", "waveform.png", "production.json", "provider.mp4"]


class Track(InputModel):
    stem: Stem
    gain: float = Field(default=0, ge=-60, le=12)
    mute: bool = False
    solo: bool = False
    bass: float = Field(default=0, ge=-15, le=15)
    treble: float = Field(default=0, ge=-15, le=15)
    compress: bool = False


class Cue(InputModel):
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0, le=1200000)
    text: Annotated[str, Field(min_length=1, max_length=500)]


class ProductionRequest(InputModel):
    audioId: UUID
    lyricsId: UUID | None = None
    promptId: UUID | None = None
    videoId: UUID | None = None
    videoPrompt: str = Field(default="", max_length=2000)
    separation: Literal["none", "two", "four"] = "none"
    tracks: list[Track] = Field(default_factory=list, max_length=4)
    renderVideo: bool = True
    aspect: Literal["portrait", "landscape"] = "portrait"
    bpm: int = Field(default=96, ge=20, le=300)
    storyboard: list[Cue] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_plan(self):
        if self.videoId and self.videoPrompt.strip():
            raise ValueError("Choose an imported background or a provider prompt")
        allowed = {
            "none": {"source"}, "two": {"vocals", "accompaniment"},
            "four": {"vocals", "drums", "bass", "other"},
        }[self.separation]
        stems = [track.stem for track in self.tracks]
        if len(set(stems)) != len(stems) or not set(stems) <= allowed:
            raise ValueError("Tracks must be unique and match the separation mode")
        end = 0
        for cue in self.storyboard:
            if cue.startMs < end or cue.endMs <= cue.startMs:
                raise ValueError("Storyboard cues must be ordered, non-overlapping and have positive duration")
            end = cue.endMs
        return self


class ProductionState(InputModel):
    id: UUID
    state: Literal["pending", "running", "done", "failed", "cancelled"]
    error: str | None = None
    settings: ProductionRequest
    completed: list[str]
    artifacts: list[Artifact]
    analysis: audio.AudioAnalysis | None = None


def output_root(project_id: UUID, run_id: UUID) -> Path:
    return resolve_within(config.DATA_DIR, f"music/production/{project_id}/{run_id}")


def video_path(project_id: UUID, video_id: UUID) -> Path:
    return resolve_within(config.DATA_DIR, f"music/video/{project_id}/{video_id}.mp4")


def model_path() -> Path:
    if location := os.environ.get("VOICESTUDIO_MUSIC_DEMUCS_REPO"):
        return Path(location) / WEIGHT
    cache = os.environ.get("TORCH_HOME")
    if cache:
        return Path(cache) / "hub" / "checkpoints" / WEIGHT
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "torch" / "hub" / "checkpoints" / WEIGHT


def file_digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def local_weight() -> Path:
    path = model_path()
    if not path.is_file():
        raise MusicError("demucs_weights_missing", 409)
    if not file_digest(path).startswith("8726e21a"):
        raise MusicError("demucs_weights_invalid", 409)
    return path


async def media(job: Job, args: list[str], *, tool: Literal["ffmpeg", "ffprobe"] = "ffmpeg") -> bytes:
    verify_active(job)
    exe = ffmpeg_utils.find_ffmpeg() if tool == "ffmpeg" else ffmpeg_utils.find_ffprobe()
    if not exe:
        raise MusicError("media_tools_missing", 503)
    cmd = ffmpeg_utils.local_inputs_only([exe, *args], tool=tool)
    rc, out, _ = await ffmpeg_utils.run_ffmpeg(cmd, timeout=1800, job_id=job.id)
    if rc:
        raise MusicError("production_media_failed", 422)
    return out


async def separate(job: Job, source: Path, directory: Path, mode: str, weight: Path) -> list[str]:
    with TemporaryDirectory(dir=directory) as working:
        temp = Path(working)
        repo = temp / "model"
        repo.mkdir()
        # --repo and a single signature select the already installed weight.
        await run_in_threadpool(copyfile, weight, repo / WEIGHT)
        path = temp / "source.wav"
        await media(job, ["-v", "error", "-nostdin", "-i", str(source), "-map", "0:a:0", "-c:a", "pcm_f32le", str(path)])
        cmd = [
            sys.executable, "-m", "demucs.separate", "--repo", str(repo), "-n", "955717e8",
            "--float32", "--shifts", "0", "-d", "cpu", "-j", "1", "-o", str(temp),
        ]
        if mode == "two":
            cmd.extend(["--two-stems", "vocals"])
        await run_child(job, [*cmd, str(path)], "demucs_failed")
        names = {"vocals": "vocals", "accompaniment": "no_vocals"} if mode == "two" else {
            name: name for name in ("vocals", "drums", "bass", "other")
        }
        for name, stem in names.items():
            (temp / "955717e8" / "source" / f"{stem}.wav").replace(directory / f"{name}.wav")
        return [f"{name}.wav" for name in names]


def mix_filters(tracks: list[Track]) -> str:
    soloed = any(track.solo and not track.mute for track in tracks)
    chains = []
    for index, track in enumerate(tracks):
        level = "0" if track.mute or (soloed and not track.solo) else f"{track.gain}dB"
        eq = f"bass=g={track.bass},treble=g={track.treble}"
        compressor = ",acompressor=threshold=0.125:ratio=3:attack=10:release=120" if track.compress else ""
        chains.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,{eq}{compressor},volume={level}[t{index}]")
    inputs = "".join(f"[t{i}]" for i in range(len(tracks)))
    chains.append(f"{inputs}amix=inputs={len(tracks)}:duration=longest:normalize=0,alimiter=limit=0.97:level=0:latency=1[mix]")
    return ";".join(chains)


async def mix(job: Job, source: Path, stems: list[str], directory: Path, req: ProductionRequest):
    tracks = req.tracks or [Track(stem=name.removesuffix(".wav")) for name in stems] or [Track(stem="source")]
    args = ["-v", "error", "-nostdin", "-y"]
    for track in tracks:
        path = source if track.stem == "source" else resolve_within(directory, f"{track.stem}.wav")
        args.extend(["-i", str(path)])
    await media(job, [*args, "-filter_complex", mix_filters(tracks), "-map", "[mix]",
                      "-c:a", "pcm_s24le", str(directory / "mix.wav")])


def lyric_cues(text: str, duration: float, storyboard: list[Cue]) -> list[dict]:
    if storyboard:
        items = [(cue.text, cue.startMs / 1000, cue.endMs / 1000) for cue in storyboard]
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("[")][:300]
        items = [(line, duration * i / len(lines), duration * (i + 1) / len(lines)) for i, line in enumerate(lines)]
    return [{"text": line, "start": start, "end": end, "character_karaoke": True}
            for line, start, end in items]


async def run_child(job: Job, cmd: list[str], error: str) -> None:
    from services.proc_registry import register_proc, unregister_proc

    proc = await ffmpeg_utils.spawn_subprocess(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                              stderr=asyncio.subprocess.DEVNULL)
    register_proc(job.id, proc)
    try:
        verify_active(job)
        if await asyncio.wait_for(proc.wait(), 1800):
            raise MusicError(error, 422)
    finally:
        unregister_proc(job.id, proc)
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


def video_provider() -> Path | None:
    configured = os.environ.get("VOICESTUDIO_MUSIC_VIDEO_PROVIDER")
    if configured:
        exe = Path(configured)
        if exe.is_absolute() and exe.is_file():
            return exe
    return None


async def generate_video(job: Job, directory: Path, req: ProductionRequest, duration: float) -> Path:
    provider = video_provider()
    if provider is None:
        raise MusicError("video_provider_unavailable", 503)
    target = directory / "provider.mp4"
    # The opt-in provider receives a prompt and render settings only.
    # It never receives song material, a token from the API, or a project path.
    with TemporaryDirectory() as staging:
        request_file = Path(staging) / "request.json"
        output_file = Path(staging) / "result.mp4"
        request_file.write_text(json.dumps({
            "prompt": req.videoPrompt, "aspect": req.aspect, "durationSeconds": duration,
        }), encoding="utf-8")
        await run_child(job, [str(provider), str(request_file), str(output_file)], "video_provider_failed")
        if output_file.is_symlink() or not output_file.is_file() or output_file.stat().st_size > audio.MAX_AUDIO_BYTES:
            raise MusicError("video_provider_failed", 422)
        await validate_video(job, output_file)
        await run_in_threadpool(copyfile, output_file, target)
    return target


async def remotion_background(job: Job, directory: Path, req: ProductionRequest,
                              duration: float, width: int, height: int) -> Path | None:
    browser = os.environ.get("VOICESTUDIO_MUSIC_REMOTION_BROWSER")
    if not browser:
        return None
    module = Path(__file__).resolve().parents[3] / "music-mv-renderer" / "render.mjs"
    node = which("node")
    if not (module.is_file() and Path(browser).is_file() and node):
        raise MusicError("remotion_unavailable", 503)
    background = directory / "background.mp4"
    await run_child(job, [node, str(module), browser, str(background), str(width), str(height),
                          str(duration), str(req.bpm)], "remotion_failed")
    return background


async def render(job: Job, directory: Path, req: ProductionRequest, lyrics: str, duration: float, video: Path | None):
    from api.routers.dub_export import _ffmpeg_filter_escape

    width, height = (1080, 1920) if req.aspect == "portrait" else (1920, 1080)
    captions = directory / "lyrics.ass"
    captions.write_text(build_ass(lyric_cues(lyrics, duration, req.storyboard), play_res=(width, height)), encoding="utf-8")
    ratio = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    background = video or await remotion_background(job, directory, req, duration, width, height)
    backdrop = ["-stream_loop", "-1", "-f", "mov", "-i", str(background)] if background else [
        "-f", "lavfi", "-i", f"color=c=0x131a2b:s={width}x{height}:r=30",
    ]
    escaped = _ffmpeg_filter_escape(str(captions))
    beat = f"lt(mod(t,{60 / req.bpm:.8f}),0.10)"
    graph = (
        f"[0:v]{ratio},fps=30,drawbox=x=0:y=0:w=iw:h=8:color=0x6b9ffd:t=fill:enable='{beat}',"
        f"fade=t=in:d=0.25,fade=t=out:st={max(0,duration-0.25):.4f}:d=0.25,ass='{escaped}'[video]"
    )
    await media(job, ["-v", "error", "-nostdin", "-y", *backdrop, "-i", str(directory / "mix.wav"),
                      "-filter_complex_threads", "2", "-filter_complex", graph, "-map", "[video]", "-map", "1:a",
                      "-t", str(duration), "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(directory / "mv.mp4")])


def snapshot(row: dict) -> ProductionState:
    run_id = UUID(row["id"])
    request = ProductionRequest.model_validate_json(row["meta_json"])
    events = [json.loads(item["payload"]) for item in job_store.events_since(row["id"])]
    return ProductionState(
        id=run_id, state=row["status"], error=row["error"], settings=request,
        completed=[item["stage"] for item in events],
        artifacts=[name for item in events for name in item.get("artifacts", [])],
        analysis=next((item["analysis"] for item in reversed(events) if "analysis" in item), None),
    )


def get(project_id: UUID, run_id: UUID) -> ProductionState:
    row = job_store.get(str(run_id))
    if not row or row["type"] != JOB_TYPE or row["project_id"] != str(project_id):
        raise MusicError("production_missing", 404)
    return snapshot(row)


def verify_active(job: Job) -> None:
    if job.is_cancelled:
        raise asyncio.CancelledError


async def start(project_id: UUID, req: ProductionRequest, previous: ProductionState | None = None) -> ProductionState:
    project = projects.get(project_id)
    asset = next((item for item in project.audioAssets if item.id == req.audioId), None)
    if not asset:
        raise MusicError("production_input_missing", 422)
    lyric = next((item for item in project.lyricsVersions if item.id == req.lyricsId), None)
    if (req.lyricsId and lyric is None) or (req.promptId and not any(item.id == req.promptId for item in project.sunoPrompts)):
        raise MusicError("production_input_missing", 422)
    source = resolve_within(config.DATA_DIR, f"music/originals/{project_id}/{asset.sha256}.{asset.fileType}")
    video = video_path(project_id, req.videoId) if req.videoId else None
    if not source.is_file() or (video and not video.is_file()):
        raise MusicError("production_input_missing", 422)
    if req.renderVideo and req.videoPrompt.strip() and not (previous and "provider.mp4" in previous.artifacts) and not video_provider():
        raise MusicError("video_provider_unavailable", 503)
    if req.storyboard and req.storyboard[-1].endMs > round(asset.durationSeconds * 1000):
        raise MusicError("storyboard_outside_audio", 422)
    reusable = previous if previous and previous.settings == req else None
    if reusable and not all(
        resolve_within(output_root(project_id, reusable.id), name).is_file() for name in reusable.artifacts
    ):
        reusable = None
    reuse_stems = bool(reusable and "stems" in reusable.completed)
    weight = await run_in_threadpool(local_weight) if req.separation != "none" and not reuse_stems else None
    if job_store.list_jobs(status="active", project_id=str(project_id), types=(JOB_TYPE,), limit=1):
        raise MusicError("production_busy", 409)
    run_id = uuid4()
    ident = str(run_id)
    directory = output_root(project_id, run_id)

    def checkpoint(stage: str, files: list[str], analysis=None) -> None:
        data = {"stage": stage, "artifacts": files}
        if analysis is not None:
            data["analysis"] = analysis.model_dump(mode="json")
        job_store.append_event(ident, json.dumps(data))

    async def run(job: Job):
        job_store.mark_running(ident)
        try:
            directory.mkdir(parents=True)
            checkpoint("inputs", [])
            stems = []
            if reuse_stems:
                stems = [name for name in reusable.artifacts if name in {"vocals.wav", "accompaniment.wav", "drums.wav", "bass.wav", "other.wav"}]
                for name in stems:
                    await run_in_threadpool(copyfile, resolve_within(output_root(project_id, reusable.id), name), directory / name)
            elif weight:
                stems = await separate(job, source, directory, req.separation, weight)
            verify_active(job)
            checkpoint("stems", stems)
            if reusable and "mix" in reusable.completed:
                await run_in_threadpool(copyfile, output_root(project_id, reusable.id) / "mix.wav", directory / "mix.wav")
                report = reusable.analysis
            else:
                await mix(job, source, stems, directory, req)
                report = await audio._measure(directory / "mix.wav", "wav")
            verify_active(job)
            await media(job, ["-v", "error", "-nostdin", "-y", "-i", str(directory / "mix.wav"),
                              "-lavfi", "showwavespic=s=960x120:colors=0x6b9ffd", "-frames:v", "1",
                              "-threads", "1", "-update", "1", str(directory / "waveform.png")])
            verify_active(job)
            checkpoint("mix", ["mix.wav", "waveform.png"], report)
            background = video
            if req.renderVideo:
                if req.videoPrompt.strip():
                    if reusable and "provider.mp4" in reusable.artifacts:
                        background = directory / "provider.mp4"
                        await run_in_threadpool(copyfile, output_root(project_id, reusable.id) / "provider.mp4", background)
                    else:
                        background = await generate_video(job, directory, req, asset.durationSeconds)
                    verify_active(job)
                    checkpoint("video", ["provider.mp4"])
                await render(job, directory, req, lyric.text if lyric else "", asset.durationSeconds, background)
                verify_active(job)
                checkpoint("mv", ["mv.mp4", "lyrics.ass"])
            completed = get(project_id, run_id)
            artifact_hashes = {}
            for name in completed.artifacts:
                artifact_hashes[name] = await run_in_threadpool(file_digest, directory / name)
            verify_active(job)
            (directory / "production.json").write_text(json.dumps({
                "schemaVersion": 1, "settings": req.model_dump(mode="json"),
                "inputSha256": asset.sha256, "artifactSha256": artifact_hashes,
                "videoSha256": await run_in_threadpool(file_digest, background) if background else None,
                "videoRenderer": ("remotion-and-ffmpeg" if (directory / "background.mp4").is_file()
                                  else "ffmpeg") if req.renderVideo else None,
            }, indent=2), encoding="utf-8")
            checkpoint("export", ["production.json"])
            job_store.mark_done(ident)
        except asyncio.CancelledError:
            job_store.mark_cancelled(ident)
            raise
        except Exception as exc:
            verify_cancelled = job.is_cancelled
            if verify_cancelled:
                job_store.mark_cancelled(ident)
            else:
                logger.warning("Music production stopped (%s)", type(exc).__name__, exc_info=True)
                job_store.mark_failed(ident, exc.code if isinstance(exc, MusicError) else "production_failed")

    job_store.create(ident, type=JOB_TYPE, project_id=str(project_id), meta=req.model_dump(mode="json"))
    await gpu_queue.start()
    gpu_queue.purge_finished()
    await gpu_queue.submit("Music production", run, job_id=ident)
    return get(project_id, run_id)


class VideoAsset(InputModel):
    id: UUID


async def validate_video(job: Job, path: Path) -> None:
    info = await media(job, [
        "-v", "quiet", "-f", "mov", "-select_streams", "v:0", "-show_entries",
        "stream=width,height:format=duration", "-of", "json", str(path),
    ], tool="ffprobe")
    try:
        details = json.loads(info)
        stream = details["streams"][0]
        if not 0 < float(details["format"]["duration"]) <= 1200 or not (
            0 < int(stream["width"]) <= 4096 and 0 < int(stream["height"]) <= 4096
        ):
            raise ValueError("Video limits exceeded")
    except (ValueError, IndexError, TypeError, KeyError) as exc:
        raise MusicError("production_media_failed", 422) from exc


async def upload_video(request: Request, project_id: UUID) -> VideoAsset:
    from tempfile import NamedTemporaryFile
    from starlette.requests import ClientDisconnect

    projects.get(project_id)
    if request.headers.get("content-type") != "application/octet-stream":
        raise MusicError("unsupported_format", 415)
    asset = VideoAsset(id=uuid4())
    path = video_path(project_id, asset.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    file = NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False)
    temp = Path(file.name)
    try:
        size = 0
        with file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > audio.MAX_AUDIO_BYTES:
                    raise MusicError("file_too_large", 413)
                await run_in_threadpool(file.write, chunk)
        await validate_video(Job(str(asset.id), "Video probe", None), temp)
        projects.get(project_id)
        temp.replace(path)
        return asset
    except ClientDisconnect as exc:
        raise MusicError("production_media_failed", 422) from exc
    finally:
        temp.unlink(missing_ok=True)
