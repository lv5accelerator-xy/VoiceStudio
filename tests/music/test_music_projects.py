"""Music P1 API, data isolation, upload limits and real media regression tests."""

import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.music import router
from core import config, db
from services.music import audio, projects

BASE = "/music/projects"
LYRICS = "".join(chr(code) for code in (0x6708, 0x5149, 0x843D, 0x5728, 0x7A97, 0x8FB9))
FILENAME = LYRICS + ".wav"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "DB_PATH", config.DB_PATH)
    db.ensure_schema()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, client=("127.0.0.1", 51234)) as test_client:
        yield test_client


@pytest.fixture
def song(client):
    response = client.post(BASE, json={"title": LYRICS})
    assert response.status_code == 201
    return response.json()


def _upload(client, url, data, name, **params):
    return client.post(url + "/audio", content=data, params=params, headers={
        "Content-Type": "application/octet-stream",
        "X-Music-Filename": quote(name, safe=""),
    })


def _tone(path: Path, amplitude=8000):
    sample_rate = 48000
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        cycle = struct.pack("<480h", *(int(amplitude * math.sin(2 * math.pi * frame / 48)) for frame in range(480)))
        output.writeframes(cycle * 200)
    return path


def _require_media_tools():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for real audio tests")


def test_project_metadata_versions_and_reopening(client, song):
    url = f"{BASE}/{song['id']}"
    assert song["schemaVersion"] == 1
    assert song["language"] == "zh-CN"
    assert song["status"] == "draft"
    assert client.put(url, json={"title": " ", "revision": 0}).status_code == 422
    assert client.put(url, json={"bpm": 400, "revision": 0}).status_code == 422
    metadata = {"title": "Night train", "revision": 0, "theme": "Home", "status": "writing",
                "genre": "Mandopop", "bpm": 96, "targetSeconds": 180}
    update = client.put(url, json=metadata)
    assert update.status_code == 200 and update.json()["revision"] == 1
    assert client.put(url, json=metadata).json() == update.json()
    assert client.put(url, json={**metadata, "title": "Stale"}).status_code == 409

    first = {"id": str(uuid4()), "text": f"[Verse 1]\n{LYRICS}"}
    second = {"id": str(uuid4()), "text": f"[Chorus]\n{LYRICS}!"}
    for body in (first, first, {**first, "id": str(uuid4())}, second):
        assert client.put(url + "/lyrics", json=body).status_code == 200
    assert client.put(url + "/lyrics", json={**first, "text": "Edit immutable version"}).status_code == 409
    assert client.put(url + "/lyrics", json={**second, "text": "  "}).status_code == 422

    prompt = {"id": str(uuid4()), "stylePrompt": "Mandopop, 96 BPM, acoustic piano",
              "exclusions": "EDM", "explanation": LYRICS}
    assert client.put(url + "/suno-prompts", json={**prompt, "stylePrompt": ""}).status_code == 422
    assert client.put(url + "/suno-prompts", json=prompt).status_code == 200
    with TestClient(client.app, client=("127.0.0.1", 51235)) as reopened_client:
        reopened = reopened_client.get(url).json()
        assert reopened["title"] == "Night train"
        assert reopened["bpm"] == 96 and reopened["status"] == "writing"
        assert [version["text"] for version in reopened["lyricsVersions"]] == [first["text"], second["text"]]
        assert reopened["sunoPrompts"][0]["explanation"] == LYRICS
        assert reopened_client.get(BASE).json()[0]["id"] == reopened["id"]


def test_receiver_rejects_paths_fake_media_and_unbounded_stream(client, song, tmp_path, monkeypatch):
    url = f"{BASE}/{song['id']}"
    for name in ("../a.wav", r"..\a.wav", r"C:\a.wav", "https://example.com/a.wav"):
        response = _upload(client, url, b"abc", name)
        assert (response.status_code, response.json()["detail"]) == (422, "unsafe_filename")
    assert _upload(client, url, b"x", "a.m4a").status_code == 415
    assert _upload(client, url, b"", FILENAME).status_code == 422
    monkeypatch.setattr(audio, "MAX_AUDIO_BYTES", 128)
    over_limit = _upload(client, url, iter([b"x" * 64] * 3), FILENAME)
    assert (over_limit.status_code, over_limit.json()["detail"]) == (413, "file_too_large")
    assert _upload(client, url, b"x" * 129, FILENAME).status_code == 413
    assert client.get(url).json()["audioAssets"] == []
    assert not list((tmp_path / "music" / "staging").iterdir())
    assert not (tmp_path / "music" / "originals").exists()


def test_real_audio_loudness_duplicate_silence_and_deletion(client, song, tmp_path):
    _require_media_tools()
    url = f"{BASE}/{song['id']}"
    wav = _tone(tmp_path / FILENAME)
    mp3 = tmp_path / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", str(mp3)],
        check=True, timeout=30,
    )
    for path, codec in ((wav, "pcm_s16le"), (mp3, "mp3")):
        original = path.read_bytes()
        result = _upload(client, url, original, path.name, source="suno")
        assert result.status_code == 200, result.text
        asset = result.json()["audioAssets"][-1]
        assert asset["name"] == path.name and asset["codec"] == codec
        assert asset["source"] == "suno" and asset["rights"] == "unverified"
        assert asset["durationSeconds"] == pytest.approx(2.0, abs=0.1)
        assert asset["sampleRateHz"] == 48000 and asset["channels"] == 1
        assert asset["sizeBytes"] == len(original)
        assert asset["sha256"] == hashlib.sha256(original).hexdigest()
        assert asset["analysis"]["status"] == "complete"
        assert asset["analysis"]["integratedLufs"] == pytest.approx(-15.25, abs=1.0)
        assert asset["analysis"]["truePeakDbtp"] == pytest.approx(-12.25, abs=1.0)
        assert _upload(client, url, original, path.name).json() == result.json()
        assert path.read_bytes() == original

    silence = _tone(tmp_path / "silence.wav", amplitude=0)
    asset = _upload(client, url, silence.read_bytes(), silence.name).json()["audioAssets"][-1]
    assert asset["analysis"] == {
        "status": "unavailable", "error": "no_loudness_result",
        "integratedLufs": None, "truePeakDbtp": None,
    }
    for name, content in (("fake.wav", b"invalid"), ("wrong.wav", mp3.read_bytes())):
        rejected = _upload(client, url, content, name)
        assert (rejected.status_code, rejected.json()["detail"]) == (422, "invalid_audio")
    originals = tmp_path / "music" / "originals" / song["id"]
    assert sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in originals.iterdir()) == sorted(
        asset["sha256"] for asset in client.get(url).json()["audioAssets"]
    )
    assert client.delete(url).json() == {"retainedAudio": True}
    assert client.get(url).status_code == 404
    assert len(list(originals.iterdir())) == 3
    assert not list((tmp_path / "music" / "staging").iterdir())


def test_audio_transaction_rolls_back_and_retry_recovers(client, song, tmp_path, monkeypatch):
    _require_media_tools()
    url = f"{BASE}/{song['id']}"
    wav = _tone(tmp_path / FILENAME).read_bytes()
    real_write = projects._write

    def failed_write(conn, project):
        real_write(conn, project)
        raise OSError("test interruption before commit")

    monkeypatch.setattr(projects, "_write", failed_write)
    assert _upload(client, url, wav, FILENAME).status_code == 507
    assert client.get(url).json()["audioAssets"] == []
    assert not list((tmp_path / "music" / "staging").iterdir())
    monkeypatch.setattr(projects, "_write", real_write)
    final = _upload(client, url, wav, FILENAME)
    assert final.status_code == 200 and len(final.json()["audioAssets"]) == 1
    assert len(list((tmp_path / "music" / "originals" / song["id"]).iterdir())) == 1


def test_namespace_migration_preserves_existing_projects(client):
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic = Config(str(ini))
    with db.db_conn() as conn:
        conn.execute("DROP TABLE music_projects")
        conn.execute(
            "INSERT INTO studio_projects (id, name, state_json) VALUES (?, ?, ?)",
            ("original", "Existing dubbing project", json.dumps({"timeline": [1]})),
        )
    command.stamp(alembic, "0019_list_sort_indexes")
    command.upgrade(alembic, "head")
    assert client.post(BASE, json={"title": "New song"}).status_code == 201
    with db.db_conn() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0020_music_projects"
        original = conn.execute("SELECT * FROM studio_projects WHERE id='original'").fetchone()
        assert original["name"] == "Existing dubbing project"
        assert json.loads(original["state_json"]) == {"timeline": [1]}


def test_remote_consumer_cannot_read_or_write_music(client, monkeypatch):
    monkeypatch.delenv("OMNIVOICE_SERVER_MODE", raising=False)
    with TestClient(client.app, client=("192.0.2.1", 51234)) as guest:
        assert guest.get(BASE).status_code == 403
        assert guest.post(BASE, json={"title": "Guest"}).status_code == 403
