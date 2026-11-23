"""End-to-end local production with actual FFmpeg, SQLite and the shared queue."""

import json
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.music import router
from core import config, db
from core.job_queue import JobQueue
from services.music import production as production_service
from api.routers import music as music_router
from services.music.production import ProductionRequest, Track, mix_filters

BASE = "/music/projects"


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("VOICESTUDIO_MUSIC_DEMUCS_REPO", str(tmp_path / "models"))
    monkeypatch.delenv("VOICESTUDIO_MUSIC_REMOTION_BROWSER", raising=False)
    db.ensure_schema()
    queue = JobQueue(name="music-test")
    monkeypatch.setattr(production_service, "gpu_queue", queue)
    monkeypatch.setattr(music_router, "gpu_queue", queue)

    @asynccontextmanager
    async def lifespan(_):
        try:
            yield
        finally:
            await queue.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    tone = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=48000:duration=1", str(tone)],
                   check=True, timeout=10)
    with TestClient(app, client=("127.0.0.1", 51404)) as client:
        song = client.post(BASE, json={"title": "Production"}).json()
        url = f"{BASE}/{song['id']}"
        source = client.post(url + "/audio", content=tone.read_bytes(), headers={
            "Content-Type": "application/octet-stream", "X-Music-Filename": "tone.wav"
        })
        assert source.status_code == 200, source.text
        asset = source.json()["audioAssets"][0]
        yield client, url, asset["id"], tmp_path


def settle(client, project_url, run_id):
    for _ in range(150):
        rows = client.get(project_url + "/production").json()
        run = next(row for row in rows if row["id"] == run_id)
        if run["state"] not in {"pending", "running"}:
            return run
        time.sleep(0.05)
    pytest.fail("Production job did not settle")


def test_real_mix_and_video(workbench):
    client, url, asset, folder = workbench
    lyric_id = str(uuid4())
    line = chr(0x6708) + chr(0x5149)
    assert client.put(url + "/lyrics", json={"id": lyric_id, "text": "[Chorus]\n" + line}).status_code == 200

    background = folder / "background.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=green:s=128x72:r=30:d=0.5", "-c:v", "libx264", str(background)],
                   check=True, timeout=10)
    media = client.post(url + "/video", content=background.read_bytes(),
                        headers={"Content-Type": "application/octet-stream"})
    assert media.status_code == 201, media.text
    for aspect, width, height in (("portrait", 1080, 1920), ("landscape", 1920, 1080)):
        response = client.post(url + "/production", json={
            "audioId": asset, "lyricsId": lyric_id, "aspect": aspect,
            "videoId": media.json()["id"] if aspect == "portrait" else None,
            "tracks": [{"stem": "source", "gain": -3, "bass": 2, "compress": True}],
        })
        assert response.status_code == 202, response.text
        run = settle(client, url, response.json()["id"])
        assert (run["state"], run["completed"]) == ("done", ["inputs", "stems", "mix", "mv", "export"]), run
        assert run["analysis"]["integratedLufs"] is not None
        files = f"{url}/production/{run['id']}/files/"
        assert client.get(files + "waveform.png").content.startswith(b"\x89PNG")
        captions = client.get(files + "lyrics.ass").text
        assert captions.count(r"{\kf") == 2
        assert client.get(files + "mix.wav", headers={"Range": "bytes=0-15"}).status_code == 206
        result = client.get(files + "mv.mp4")
        assert result.status_code == 200 and result.headers["content-type"] == "video/mp4"
        output = folder / f"{aspect}.mp4"
        output.write_bytes(result.content)
        raw = subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)], timeout=10)
        video, sound = json.loads(raw)["streams"]
        assert (video["width"], video["height"], sound["codec_name"]) == (width, height, "aac")
        assert client.get(files + "production.json").json()["artifactSha256"]["mv.mp4"]
        assert client.get(files + "vocals.wav").status_code == 404


def test_missing_weights_and_invalid_storyboard(workbench):
    client, url, asset, _ = workbench
    missing = client.post(url + "/production", json={"audioId": asset, "separation": "two"})
    assert missing.status_code == 409 and missing.json()["detail"] == "demucs_weights_missing"
    invalid = client.post(url + "/production", json={"audioId": asset, "storyboard": [
        {"startMs": 0, "endMs": 1500, "text": "Too long"}
    ]})
    assert invalid.status_code == 422
    assert client.get(url + "/production").json() == []


def test_track_contract():
    filters = mix_filters([Track(stem="vocals", solo=True, gain=-6), Track(stem="bass")])
    assert "volume=-6.0dB[t0]" in filters and "volume=0[t1]" in filters
    with pytest.raises(ValueError):
        ProductionRequest(audioId=uuid4(), separation="two", tracks=[Track(stem="bass")])


def test_cancel_retry_reuses_completed_mix(workbench, monkeypatch):
    import asyncio
    from services.music import production

    client, url, asset, _ = workbench
    original_render = production.render
    original_mix = production.mix

    async def slow_render(*args):
        while not args[0].is_cancelled:
            await asyncio.sleep(0.01)
        production.verify_active(args[0])

    calls = []
    async def tracked_mix(*args):
        calls.append("mix")
        await original_mix(*args)

    monkeypatch.setattr(production, "render", slow_render)
    monkeypatch.setattr(production, "mix", tracked_mix)
    result = client.post(url + "/production", json={"audioId": asset})
    assert result.status_code == 202
    run_id = result.json()["id"]
    for _ in range(100):
        if "mix" in client.get(url + "/production").json()[0]["completed"]:
            break
        time.sleep(0.05)
    assert client.post(f"{url}/production/{run_id}/cancel").status_code == 200
    assert settle(client, url, run_id)["state"] == "cancelled"
    monkeypatch.setattr(production, "render", original_render)
    retry = client.post(f"{url}/production/{run_id}/retry")
    assert retry.status_code == 202
    retry_id = retry.json()["id"]
    assert settle(client, url, retry_id)["state"] == "done"
    assert calls == ["mix"]

    # Reuse shares the completed mix instead of copying it.
    _, _, _, data = workbench
    project_dir = data / "music" / "production" / url.rsplit("/", 1)[1]
    assert (project_dir / run_id / "mix.wav").stat().st_ino == (project_dir / retry_id / "mix.wav").stat().st_ino

    # Deleting the cancelled run frees its directory without touching the retry.
    assert client.delete(f"{url}/production/{run_id}").status_code == 200
    assert not (project_dir / run_id).exists()
    assert [row["id"] for row in client.get(url + "/production").json()] == [retry_id]
    assert client.post(f"{url}/production/{run_id}/retry").status_code == 404
    assert client.get(f"{url}/production/{retry_id}/files/mix.wav").status_code == 200


def test_provider_receives_only_opted_in_video_prompt(workbench, monkeypatch):
    import sys
    from pathlib import Path

    client, url, asset, _ = workbench
    monkeypatch.setenv("VOICESTUDIO_MUSIC_VIDEO_PROVIDER", sys.executable)
    seen = []
    async def local_provider(_job, cmd, error):
        assert error == "video_provider_failed"
        seen.append(json.loads(Path(cmd[1]).read_text()))
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=navy:s=128x72:r=30:d=0.5", "-c:v", "libx264", cmd[2]],
                       check=True, timeout=10)

    monkeypatch.setattr(production_service, "run_child", local_provider)
    assert client.get(url + "/production/capabilities").json() == {"videoProvider": True}
    result = client.post(url + "/production", json={
        "audioId": asset, "videoPrompt": "A midnight train", "aspect": "landscape",
    })
    assert result.status_code == 202
    completed = settle(client, url, result.json()["id"])
    assert completed["state"] == "done", completed
    assert "provider.mp4" in completed["artifacts"]
    assert seen == [{"prompt": "A midnight train", "aspect": "landscape", "durationSeconds": 1.0}]


def test_delete_guards_active_runs_and_removes_only_derived_outputs(workbench, monkeypatch):
    import asyncio

    client, url, asset, data = workbench
    project_id = url.rsplit("/", 1)[1]

    async def held_render(*args):
        while not args[0].is_cancelled:
            await asyncio.sleep(0.01)
        production_service.verify_active(args[0])

    monkeypatch.setattr(production_service, "render", held_render)
    run_id = client.post(url + "/production", json={"audioId": asset}).json()["id"]
    assert client.delete(f"{url}/production/{run_id}").json()["detail"] == "production_busy"
    assert client.delete(url).json()["detail"] == "production_busy"
    assert client.get(url).status_code == 200
    client.post(f"{url}/production/{run_id}/cancel")
    assert settle(client, url, run_id)["state"] == "cancelled"

    background = data / "music" / "video" / project_id / "clip.mp4"
    background.parent.mkdir(parents=True)
    background.write_bytes(b"clip")
    assert client.delete(url).json() == {"retainedAudio": True}
    assert not (data / "music" / "production" / project_id).exists()
    assert background.is_file()
    assert len(list((data / "music" / "originals" / project_id).iterdir())) == 1
